"""Writer's direct MCP surface.

Handlers are SDK-free and return errors as data. The optional MCP dependency is
loaded only when the stdio server starts.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable

from writer import voice_dna
from writer.engagement import EngagementDelivery
from writer.schemas import (
    AssemblyQuery,
    Beat,
    DraftContract,
    Shot,
    SourceSnapshot,
    VoiceSampleContract,
)
from writer.scripts import ScriptService
from writer.storage import WriterStore
from writer.uoink_client import (
    UOINK_TOKEN_ENV,
    UoinkClient,
)
from writer.writing import WritingService, validate_composition

TOOL_NAMES = (
    "prepare_draft",
    "save_draft",
    "get_draft",
    "save_piece",
    "list_pieces",
    "validate_composition",
    "prepare_script",
    "save_script",
    "critique_script",
    "revise_script",
    "derive_shot_list",
    "export_shot_list",
    "add_voice_sample",
    "list_voice_samples",
    "remove_voice_sample",
    "scan_voice",
    "writer_status",
)


def _ok(**fields: Any) -> dict[str, Any]:
    return {"ok": True, **fields}


def _err(message: str) -> dict[str, Any]:
    return {"ok": False, "error": str(message)}


def _source_list(value: Any) -> list[SourceSnapshot]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("sources must be a list")
    return [
        item if isinstance(item, SourceSnapshot)
        else SourceSnapshot.from_dict(item)
        for item in value
    ]


def _beat_list(value: Any) -> list[Beat]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("beats must be a list")
    return [
        item if isinstance(item, Beat) else Beat.from_dict(item)
        for item in value
    ]


def _shot_list(value: Any) -> list[Shot]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("shots must be a list")
    return [
        item if isinstance(item, Shot) else Shot.from_dict(item)
        for item in value
    ]


def _assembly(value: Any) -> AssemblyQuery | None:
    if value is None:
        return None
    if isinstance(value, AssemblyQuery):
        return value.validate()
    if not isinstance(value, dict):
        raise ValueError("assembly_query must be an object")
    return AssemblyQuery.from_dict(value)


class WriterTools:
    def __init__(
            self, store: WriterStore, *,
            uoink: UoinkClient | None = None):
        self.store = store
        self.writing = WritingService(store, uoink=uoink)
        self.scripts = ScriptService(store, uoink=uoink)
        self.uoink = uoink
        self.engagement = EngagementDelivery(store, uoink=uoink)

    @staticmethod
    def _call(function: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            return function()
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
            return _err(str(exc))

    def prepare_draft(
            self, kind: str, brief: str,
            draft_text: str = "",
            sources: list[dict[str, Any]] | None = None,
            voice_sample_ids: list[int] | None = None,
            angle: str = "",
            target_length: int | None = None) -> dict[str, Any]:
        return self._call(lambda: _ok(prompt=self.writing.prepare_draft(
            kind=kind,
            brief=brief,
            draft_text=draft_text,
            sources=_source_list(sources),
            voice_sample_ids=voice_sample_ids,
            angle=angle,
            target_length=target_length,
        ).to_dict()))

    def attach_uoink_source(self, item_id: str) -> dict[str, Any]:
        return self._call(lambda: _ok(
            source=self.writing.attach_uoink_source(
                item_id).to_dict()))

    def validate_composition(
            self, kind: str, blocks: list[str],
            credit_lines: list[str] | None = None,
            attribution_enabled: bool = True) -> dict[str, Any]:
        return self._call(lambda: _ok(report=validate_composition(
            kind=kind,
            blocks=blocks,
            credit_lines=credit_lines,
            attribution_enabled=attribution_enabled,
        )))

    def save_draft(self, draft: dict[str, Any]) -> dict[str, Any]:
        return self._call(lambda: _ok(
            draft=self.store.save_draft(
                DraftContract.from_dict(draft)).to_dict()))

    def get_draft(self, draft_id: int) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            draft = self.store.get_draft(draft_id)
            if draft is None:
                return _err(f"draft not found: {draft_id}")
            return _ok(draft=draft.to_dict())
        return self._call(work)

    def save_piece(self, piece: dict[str, Any]) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            payload = dict(piece)
            payload["sources"] = _source_list(payload.get("sources"))
            saved = self.writing.save_piece(**payload)
            return _ok(
                piece=saved.to_dict(),
                engagement=self.engagement.deliver_entity(
                    "piece", int(saved.id)),
            )
        return self._call(work)

    def list_pieces(
            self, kind: str = "", limit: int = 100) -> dict[str, Any]:
        return self._call(lambda: _ok(pieces=[
            piece.to_dict()
            for piece in self.store.list_pieces(
                kind=kind or None, limit=limit)
        ]))

    def prepare_script(
            self, brief: str,
            assembly_query: dict[str, Any] | None = None,
            sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return self._call(lambda: _ok(prompt=self.scripts.prepare_script(
            brief=brief,
            assembly_query=_assembly(assembly_query),
            sources=_source_list(sources),
        ).to_dict()))

    def save_script(self, script: dict[str, Any]) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            payload = dict(script)
            if "beats" in payload:
                payload["beats"] = _beat_list(payload["beats"])
            if "shots" in payload:
                payload["shots"] = _shot_list(payload["shots"])
            if "sources" in payload:
                payload["sources"] = _source_list(payload["sources"])
            if "assembly_query" in payload:
                payload["assembly_query"] = _assembly(
                    payload["assembly_query"])
            saved = self.scripts.save_script(**payload)
            return _ok(
                script=saved.to_dict(),
                engagement=self.engagement.deliver_entity(
                    "script", int(saved.id)),
            )
        return self._call(work)

    def critique_script(
            self, script_id: int, *,
            findings: dict[str, Any] | None = None,
            focus: str = "",
            draft_text: str = "") -> dict[str, Any]:
        def work() -> dict[str, Any]:
            if findings is None:
                prompt = self.scripts.prepare_critique(
                    script_id, focus=focus)
                return _ok(
                    mode="context_only", prompt=prompt.to_dict())
            critique = self.scripts.save_critique(
                script_id,
                findings=findings,
                draft_text=draft_text or None,
            )
            return _ok(
                mode="persisted", critique=critique.to_dict())
        return self._call(work)

    def revise_script(
            self, script_id: int, *,
            revised_script: dict[str, Any] | None = None,
            critique_id: int | None = None,
            instructions: str = "") -> dict[str, Any]:
        def work() -> dict[str, Any]:
            if revised_script is None:
                prompt = self.scripts.prepare_revision(
                    script_id,
                    critique_id=critique_id,
                    instructions=instructions,
                )
                return _ok(
                    mode="context_only", prompt=prompt.to_dict())
            payload = dict(revised_script)
            payload["parent_id"] = script_id
            saved = self.save_script(payload)
            if not saved.get("ok"):
                return saved
            return _ok(
                mode="persisted",
                script=saved["script"],
                engagement=saved["engagement"],
            )
        return self._call(work)

    def derive_shot_list(self, script_id: int) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            saved = self.scripts.derive_shots(script_id)
            return _ok(
                script=saved.to_dict(),
                engagement=self.engagement.deliver_entity(
                    "script", int(saved.id)),
            )
        return self._call(work)

    def export_shot_list(
            self, script_id: int, output: str,
            title: str = "") -> dict[str, Any]:
        return self._call(lambda: _ok(
            document=self.scripts.export_shot_list(
                script_id, output, title=title).to_dict(),
            output=str(Path(output).expanduser()),
        ))

    def add_voice_sample(
            self, sample: dict[str, Any]) -> dict[str, Any]:
        return self._call(lambda: _ok(
            voice_sample=self.store.add_voice_sample(
                VoiceSampleContract.from_dict(sample)).to_dict()))

    def list_voice_samples(
            self, active_only: bool = False) -> dict[str, Any]:
        return self._call(lambda: _ok(voice_samples=[
            sample.to_dict()
            for sample in self.store.list_voice_samples(
                active_only=active_only)
        ]))

    def remove_voice_sample(self, sample_id: int) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            removed = self.store.remove_voice_sample(sample_id)
            if not removed:
                return _err(
                    f"voice sample not found: {sample_id}")
            return _ok(removed=True, id=sample_id)
        return self._call(work)

    def scan_voice(self, text: str) -> dict[str, Any]:
        return _ok(
            warnings=voice_dna.scan(text),
            warning_copy=voice_dna.warning_copy(),
        )

    def writer_status(self) -> dict[str, Any]:
        return _ok(
            service="writer",
            schema_version=1,
            database="ready",
            uoink=(
                "configured" if self.uoink is not None
                else "not_configured"
            ),
            engagement=self.store.engagement_status(),
            counts={
                "drafts": len(self.store.list_drafts(limit=500)),
                "pieces": len(self.store.list_pieces(limit=500)),
                "scripts": len(self.store.list_scripts(limit=500)),
                "voice_samples": len(
                    self.store.list_voice_samples()),
            },
        )


def _optional_uoink() -> UoinkClient | None:
    if not str(os.environ.get(UOINK_TOKEN_ENV) or "").strip():
        return None
    try:
        return UoinkClient.from_env()
    except (OSError, RuntimeError, ValueError):
        # Optional peer drift must not prevent Writer's direct MCP server
        # from starting. `writer doctor` retains the exact unhealthy result.
        return None


def build_server(tools: WriterTools | None = None):
    from mcp.server.fastmcp import FastMCP

    active = tools or WriterTools(
        WriterStore.open(), uoink=_optional_uoink())
    mcp = FastMCP(
        "writer",
        instructions=(
            "Writer drafts prose and scripts in the user's voice. "
            "Prepare context, write with your model, then save the result. "
            "Uoink sources are optional. Writer never sends or posts copy."
        ),
    )
    descriptions = {
        "prepare_draft": (
            "Prepare model-neutral prose context. Sources are optional; "
            "manual and pasted-text work stays standalone."),
        "save_draft": "Save or update an editable local draft.",
        "get_draft": "Read one editable local draft by integer id.",
        "save_piece": (
            "Save an immutable prose version after generation or editing."),
        "list_pieces": "List immutable prose versions.",
        "validate_composition": (
            "Calculate local length and credit-footer checks. This never "
            "opens a site or sends copy."),
        "prepare_script": (
            "Prepare structured script context. Optionally assemble Uoink "
            "corpus references through its v1 loopback contract."),
        "save_script": "Save an immutable structured script version.",
        "critique_script": (
            "Without findings, prepare critique context. With findings, "
            "save the critique beside the script."),
        "revise_script": (
            "Without revised_script, prepare revision context. With one, "
            "save an immutable child version."),
        "derive_shot_list": (
            "Create a new script version with format-based shot cues."),
        "export_shot_list": (
            "Save a user-chosen versioned Markdown shot-list file. This "
            "writes only the explicit output path and never calls Zing."),
        "add_voice_sample": "Add a local Writer voice sample.",
        "list_voice_samples": "List local Writer voice samples.",
        "remove_voice_sample": "Delete one local Writer voice sample.",
        "scan_voice": (
            "Scan text locally for Voice DNA warnings. No model call."),
        "writer_status": (
            "Read path-free Writer health, optional peer state, and counts."),
    }
    for name in TOOL_NAMES:
        function = getattr(active, name)
        mcp.tool(name=name, description=descriptions[name])(function)
    return mcp


def _print_config() -> int:
    config = {
        "mcpServers": {
            "writer": {
                "command": sys.executable,
                "args": ["-m", "writer.cli", "serve-mcp"],
            }
        }
    }
    print(json.dumps(config, indent=2))
    return 0


def run(argv: list[str]) -> int:
    if "--print-config" in argv:
        return _print_config()
    try:
        import mcp  # noqa: F401
    except ImportError:
        print(
            "writer serve-mcp needs the MCP SDK: "
            'python -m pip install "ryan-writer[mcp]"',
            file=sys.stderr,
        )
        return 2
    build_server().run()
    return 0
