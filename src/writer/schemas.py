"""Versioned JSON contracts shared by Writer's storage, HTTP, and MCP.

Core contracts use only the standard library. A source is a Writer-owned
display snapshot, never a foreign database row or filesystem path.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

SCHEMA_VERSION = 1
WRITING_KINDS = ("tweet", "thread", "blog", "newsletter", "script")
SOURCE_PROVIDERS = ("original", "paste", "file", "url", "uoink")
UOINK_CONTRACT = "uoink.corpus.read"
UOINK_CONTRACT_VERSION = 1
SHOT_LIST_DOCUMENT_TYPE = "writer.shot-list"
PROMPT_OPERATIONS = (
    "prepare_draft",
    "revise_piece",
    "prepare_script",
    "revise_script",
    "critique_script",
)


class SchemaError(ValueError):
    """A stable schema failure safe to return to a local client."""


class JsonContract:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, **kwargs)


def _version(value: int, label: str) -> None:
    if value != SCHEMA_VERSION:
        raise SchemaError(
            f"{label}.schema_version must be {SCHEMA_VERSION}")


def _kind(value: str) -> None:
    if value not in WRITING_KINDS:
        raise SchemaError(
            "kind must be one of " + ", ".join(WRITING_KINDS))


def is_valid_source_url(value: Any) -> bool:
    """True for the suite's only valid cross-product URL values."""
    if value is None:
        return True
    if not isinstance(value, str) or not value or "\\" in value or any(
            character.isspace() for character in value):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        # Accessing port rejects malformed netlocs such as `:abc`.
        parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.hostname is not None
    )


@dataclass(frozen=True)
class SourceSnapshot(JsonContract):
    """Portable display data for one attached source.

    `provider_ref` is opaque. For Uoink it is `uoink://item/<id>`.
    `credit_required` distinguishes external work from the user's original
    text; required credits are captured at attachment time.
    """

    provider: str
    provider_ref: str = ""
    title: str = ""
    creator: str = ""
    source_url: str | None = None
    credit_line: str = ""
    excerpt: str = ""
    attached_at: str = ""
    credit_required: bool = False
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> "SourceSnapshot":
        _version(self.schema_version, "source")
        if self.provider not in SOURCE_PROVIDERS:
            raise SchemaError(
                "source.provider must be one of "
                + ", ".join(SOURCE_PROVIDERS))
        if self.provider == "uoink":
            parsed = urllib.parse.urlparse(self.provider_ref)
            encoded_id = parsed.path[1:] if parsed.path.startswith("/") else ""
            item_id = urllib.parse.unquote(encoded_id)
            invalid_percent = "%" in re.sub(
                r"%[0-9A-Fa-f]{2}",
                "",
                encoded_id,
            )
            if (
                parsed.scheme != "uoink"
                or parsed.netloc != "item"
                or not encoded_id
                or invalid_percent
                or "/" in encoded_id
                or "/" in item_id
                or "\\" in item_id
                or parsed.params
                or parsed.query
                or parsed.fragment
            ):
                raise SchemaError(
                    "uoink source.provider_ref must identify one "
                    "uoink://item/<id>")
        if not is_valid_source_url(self.source_url):
            raise SchemaError(
                "source.source_url must be null or an HTTP(S) URL")
        if self.credit_required and not self.credit_line.strip():
            raise SchemaError(
                "external source requires a display-safe credit_line")
        return self

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SourceSnapshot":
        data = dict(value)
        # Pre-launch v1 snapshots represented an absent URL as "". Normalize
        # that legacy local value on read; every newly serialized snapshot
        # uses the contract's null representation.
        if data.get("source_url") == "":
            data["source_url"] = None
        return cls(**data).validate()


@dataclass
class DraftContract(JsonContract):
    kind: str
    title: str = ""
    body: str = ""
    brief: str = ""
    sources: list[SourceSnapshot] = field(default_factory=list)
    voice_sample_ids: list[int] = field(default_factory=list)
    id: int | None = None
    created_at: str = ""
    updated_at: str = ""
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> "DraftContract":
        _version(self.schema_version, "draft")
        _kind(self.kind)
        if not isinstance(self.body, str):
            raise SchemaError("draft.body must be a string")
        for source in self.sources:
            source.validate()
        if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in self.voice_sample_ids):
            raise SchemaError(
                "draft.voice_sample_ids must be a list of integers")
        return self

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DraftContract":
        data = dict(value)
        data["sources"] = [
            SourceSnapshot.from_dict(item)
            for item in data.get("sources") or []
        ]
        return cls(**data).validate()


@dataclass(frozen=True)
class Beat(JsonContract):
    label: str
    content: str
    timecode: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Beat":
        return cls(**value)


@dataclass(frozen=True)
class Shot(JsonContract):
    scene: int
    label: str
    cues: list[str] = field(default_factory=list)
    notes: str = ""

    def validate(self) -> "Shot":
        if self.scene < 1:
            raise SchemaError("shot.scene must be positive")
        if not self.label.strip():
            raise SchemaError("shot.label is required")
        if any(not isinstance(value, str) for value in self.cues):
            raise SchemaError("shot.cues must be a list of strings")
        return self

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Shot":
        return cls(**value).validate()


@dataclass
class PieceContract(JsonContract):
    kind: str
    body: str
    title: str = ""
    dek: str = ""
    tags: list[str] = field(default_factory=list)
    sources: list[SourceSnapshot] = field(default_factory=list)
    credit_lines: list[str] = field(default_factory=list)
    voice_warnings: list[dict[str, Any]] = field(default_factory=list)
    voice_sample_ids: list[int] = field(default_factory=list)
    angle: str = ""
    target_length: int | None = None
    id: int | None = None
    version: int = 1
    parent_id: int | None = None
    created_at: str = ""
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> "PieceContract":
        _version(self.schema_version, "piece")
        _kind(self.kind)
        if self.kind == "script":
            raise SchemaError(
                "script output must use ScriptContract")
        if not isinstance(self.body, str) or not self.body:
            raise SchemaError("piece.body is required")
        for source in self.sources:
            source.validate()
            if source.credit_required and source.credit_line not in (
                    self.credit_lines):
                raise SchemaError(
                    "piece must retain every required source credit")
        if self.version < 1:
            raise SchemaError("piece.version must be positive")
        return self

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PieceContract":
        data = dict(value)
        data["sources"] = [
            SourceSnapshot.from_dict(item)
            for item in data.get("sources") or []
        ]
        return cls(**data).validate()


@dataclass(frozen=True)
class AssemblyQuery(JsonContract):
    format: str | None = None
    topic: str | None = None
    hook_target: str | None = None
    your_channel: str | None = None
    n_examples: int = 10

    def validate(self) -> "AssemblyQuery":
        if isinstance(self.n_examples, bool) \
                or not isinstance(self.n_examples, int) \
                or not 1 <= self.n_examples <= 100:
            raise SchemaError(
                "assembly.n_examples must be between 1 and 100")
        for name in (
                "format", "topic", "hook_target", "your_channel"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise SchemaError(
                    f"assembly.{name} must be a string or null")
        return self

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AssemblyQuery":
        return cls(**value).validate()


@dataclass
class PromptContract(JsonContract):
    """A model-neutral handoff from Writer to the calling AI.

    Writer prepares and validates context but does not choose or hide a
    provider. An MCP client can use the prompt directly. A standalone client
    can show it, use a configured provider, or keep working manually.
    """

    operation: str
    system_prompt: str
    instruction: str
    context: dict[str, Any] = field(default_factory=dict)
    sources: list[SourceSnapshot] = field(default_factory=list)
    voice_sample_ids: list[int] = field(default_factory=list)
    dependency_status: dict[str, str] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> "PromptContract":
        _version(self.schema_version, "prompt")
        if self.operation not in PROMPT_OPERATIONS:
            raise SchemaError(
                "prompt.operation must be one of "
                + ", ".join(PROMPT_OPERATIONS))
        if not self.system_prompt.strip():
            raise SchemaError("prompt.system_prompt is required")
        if not self.instruction.strip():
            raise SchemaError("prompt.instruction is required")
        if not isinstance(self.context, dict):
            raise SchemaError("prompt.context must be an object")
        for source in self.sources:
            source.validate()
        if any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in self.voice_sample_ids):
            raise SchemaError(
                "prompt.voice_sample_ids must be a list of integers")
        if not isinstance(self.dependency_status, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in self.dependency_status.items()):
            raise SchemaError(
                "prompt.dependency_status must contain string values")
        return self

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PromptContract":
        data = dict(value)
        data["sources"] = [
            SourceSnapshot.from_dict(item)
            for item in data.get("sources") or []
        ]
        return cls(**data).validate()


@dataclass
class ScriptContract(JsonContract):
    hook: str
    format: str = ""
    target_length_sec: int | None = None
    beats: list[Beat] = field(default_factory=list)
    body: str = ""
    cta: str = ""
    shots: list[Shot] = field(default_factory=list)
    sources: list[SourceSnapshot] = field(default_factory=list)
    assembly_query: AssemblyQuery | None = None
    id: int | None = None
    version: int = 1
    parent_id: int | None = None
    created_at: str = ""
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> "ScriptContract":
        _version(self.schema_version, "script")
        if not self.hook.strip():
            raise SchemaError("script.hook is required")
        if self.target_length_sec is not None and (
                isinstance(self.target_length_sec, bool)
                or not isinstance(self.target_length_sec, int)
                or self.target_length_sec < 1):
            raise SchemaError(
                "script.target_length_sec must be a positive integer")
        for shot in self.shots:
            shot.validate()
        for source in self.sources:
            source.validate()
        if self.assembly_query is not None:
            self.assembly_query.validate()
        if self.version < 1:
            raise SchemaError("script.version must be positive")
        return self

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ScriptContract":
        data = dict(value)
        data["beats"] = [
            Beat.from_dict(item) for item in data.get("beats") or []
        ]
        data["shots"] = [
            Shot.from_dict(item) for item in data.get("shots") or []
        ]
        data["sources"] = [
            SourceSnapshot.from_dict(item)
            for item in data.get("sources") or []
        ]
        if data.get("assembly_query") is not None:
            data["assembly_query"] = AssemblyQuery.from_dict(
                data["assembly_query"])
        return cls(**data).validate()


@dataclass
class CritiqueContract(JsonContract):
    draft_text: str
    findings: dict[str, Any] = field(default_factory=dict)
    script_id: int | None = None
    piece_id: int | None = None
    mode: str = "agent"
    id: int | None = None
    created_at: str = ""
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> "CritiqueContract":
        _version(self.schema_version, "critique")
        if not isinstance(self.draft_text, str):
            raise SchemaError("critique.draft_text must be a string")
        if not isinstance(self.findings, dict):
            raise SchemaError("critique.findings must be an object")
        if self.script_id is None and self.piece_id is None:
            raise SchemaError(
                "critique requires script_id or piece_id")
        return self

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CritiqueContract":
        return cls(**value).validate()


@dataclass
class ShotListDocument(JsonContract):
    title: str
    hook: str
    beats: list[Beat]
    script: str
    cta: str
    shots: list[Shot]
    credits: list[str]
    generated_at: str
    source_script_id: int | None = None
    document_type: str = SHOT_LIST_DOCUMENT_TYPE
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> "ShotListDocument":
        _version(self.schema_version, "shot-list")
        if self.document_type != SHOT_LIST_DOCUMENT_TYPE:
            raise SchemaError(
                f"shot-list.document_type must be "
                f"{SHOT_LIST_DOCUMENT_TYPE}")
        if not self.hook.strip():
            raise SchemaError("shot-list.hook is required")
        for shot in self.shots:
            shot.validate()
        if any(not isinstance(value, str) for value in self.credits):
            raise SchemaError(
                "shot-list.credits must be a list of strings")
        return self

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ShotListDocument":
        data = dict(value)
        data["beats"] = [
            Beat.from_dict(item) for item in data.get("beats") or []
        ]
        data["shots"] = [
            Shot.from_dict(item) for item in data.get("shots") or []
        ]
        return cls(**data).validate()


@dataclass
class VoiceSampleContract(JsonContract):
    name: str
    source_type: str
    raw_text: str = ""
    source_url: str = ""
    active: bool = True
    default: bool = False
    id: int | None = None
    added_at: str = ""
    schema_version: int = SCHEMA_VERSION

    SOURCE_TYPES: ClassVar[tuple[str, ...]] = ("text", "url")

    def validate(self) -> "VoiceSampleContract":
        _version(self.schema_version, "voice-sample")
        if not self.name.strip():
            raise SchemaError("voice-sample.name is required")
        if self.source_type not in self.SOURCE_TYPES:
            raise SchemaError(
                "voice-sample.source_type must be text or url")
        if self.source_type == "text" and not self.raw_text.strip():
            raise SchemaError(
                "text voice sample requires raw_text")
        if self.source_type == "url" and not self.source_url.strip():
            raise SchemaError(
                "url voice sample requires source_url")
        return self

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "VoiceSampleContract":
        return cls(**value).validate()
