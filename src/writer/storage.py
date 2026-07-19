"""Writer-owned SQLite persistence.

No method accepts an Uoink index, path, or connection. Cross-product source
data enters only as validated `SourceSnapshot` values.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from dataclasses import replace
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from writer.schemas import (
    AssemblyQuery,
    Beat,
    CritiqueContract,
    DraftContract,
    PieceContract,
    ScriptContract,
    Shot,
    SourceSnapshot,
    VoiceSampleContract,
)

VOICE_SAMPLE_CAP = 10
DATA_DIR_ENV = "WRITER_DATA_DIR"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_data_dir() -> Path:
    configured = str(os.environ.get(DATA_DIR_ENV) or "").strip()
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA")
        return (
            Path(root) / "Writer"
            if root else Path.home() / "AppData" / "Local" / "Writer"
        )
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Writer"
    root = os.environ.get("XDG_DATA_HOME")
    return (
        Path(root) / "writer"
        if root else Path.home() / ".local" / "share" / "writer"
    )


def default_database_path() -> Path:
    return default_data_dir() / "writer.db"


def _json(value: Any) -> str:
    if isinstance(value, list):
        value = [
            item.to_dict() if hasattr(item, "to_dict") else item
            for item in value
        ]
    elif hasattr(value, "to_dict"):
        value = value.to_dict()
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        loaded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback
    return loaded


def _sources(value: Any) -> list[SourceSnapshot]:
    loaded = _load_json(value, [])
    if not isinstance(loaded, list):
        return []
    return [
        SourceSnapshot.from_dict(item)
        for item in loaded
        if isinstance(item, dict)
    ]


class WriterStore:
    def __init__(self, path: Path, connection: sqlite3.Connection):
        self.path = path
        self.connection = connection
        self._lock = threading.RLock()

    @classmethod
    def open(cls, path: str | Path | None = None) -> "WriterStore":
        database = Path(
            path if path is not None else default_database_path())
        database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            database,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        store = cls(database, connection)
        store._migrate()
        return store

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def _migrate(self) -> None:
        with self._lock:
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            applied = {
                int(row["version"])
                for row in self.connection.execute(
                    "SELECT version FROM schema_migrations")
            }
            migration_root = files("writer").joinpath("migrations")
            for resource in sorted(
                    migration_root.iterdir(), key=lambda item: item.name):
                if not resource.name.endswith(".sql"):
                    continue
                try:
                    version = int(resource.name.split("_", 1)[0])
                except ValueError:
                    continue
                if version in applied:
                    continue
                self.connection.executescript(
                    resource.read_text(encoding="utf-8"))
                self.connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) "
                    "VALUES (?, ?)",
                    (version, now_iso()),
                )
            self.connection.commit()

    def save_draft(self, draft: DraftContract) -> DraftContract:
        draft.validate()
        timestamp = now_iso()
        with self._lock:
            if draft.id is None:
                created = draft.created_at or timestamp
                cursor = self.connection.execute(
                    "INSERT INTO drafts "
                    "(kind, title, body, brief, sources_json, "
                    "voice_sample_ids_json, created_at, updated_at, "
                    "schema_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        draft.kind,
                        draft.title,
                        draft.body,
                        draft.brief,
                        _json(draft.sources),
                        _json(draft.voice_sample_ids),
                        created,
                        timestamp,
                        draft.schema_version,
                    ),
                )
                draft_id = int(cursor.lastrowid)
            else:
                existing = self.connection.execute(
                    "SELECT created_at FROM drafts WHERE id=?",
                    (draft.id,),
                ).fetchone()
                if existing is None:
                    raise ValueError(f"draft not found: {draft.id}")
                created = str(existing["created_at"])
                self.connection.execute(
                    "UPDATE drafts SET kind=?, title=?, body=?, brief=?, "
                    "sources_json=?, voice_sample_ids_json=?, updated_at=?, "
                    "schema_version=? WHERE id=?",
                    (
                        draft.kind,
                        draft.title,
                        draft.body,
                        draft.brief,
                        _json(draft.sources),
                        _json(draft.voice_sample_ids),
                        timestamp,
                        draft.schema_version,
                        draft.id,
                    ),
                )
                draft_id = draft.id
            self.connection.commit()
        return replace(
            draft,
            id=draft_id,
            created_at=created,
            updated_at=timestamp,
        )

    @staticmethod
    def _draft_row(row: sqlite3.Row | None) -> DraftContract | None:
        if row is None:
            return None
        return DraftContract(
            id=int(row["id"]),
            kind=str(row["kind"]),
            title=str(row["title"] or ""),
            body=str(row["body"] or ""),
            brief=str(row["brief"] or ""),
            sources=_sources(row["sources_json"]),
            voice_sample_ids=[
                int(value)
                for value in _load_json(
                    row["voice_sample_ids_json"], [])
            ],
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            schema_version=int(row["schema_version"]),
        ).validate()

    def get_draft(self, draft_id: int) -> DraftContract | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM drafts WHERE id=?",
                (int(draft_id),),
            ).fetchone()
        return self._draft_row(row)

    def list_drafts(self, *, limit: int = 100) -> list[DraftContract]:
        count = max(1, min(int(limit), 500))
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM drafts ORDER BY updated_at DESC LIMIT ?",
                (count,),
            ).fetchall()
        return [
            draft for row in rows
            if (draft := self._draft_row(row)) is not None
        ]

    def save_piece(self, piece: PieceContract) -> PieceContract:
        piece.validate()
        if piece.id is not None:
            raise ValueError("pieces are immutable; save a revision")
        version = 1
        if piece.parent_id is not None:
            parent = self.get_piece(piece.parent_id)
            if parent is None:
                raise ValueError(
                    f"parent piece not found: {piece.parent_id}")
            version = parent.version + 1
        timestamp = piece.created_at or now_iso()
        with self._lock:
            cursor = self.connection.execute(
                "INSERT INTO pieces "
                "(kind, version, parent_id, title, dek, body, tags_json, "
                "sources_json, credit_lines_json, voice_warnings_json, "
                "voice_sample_ids_json, angle, target_length, created_at, "
                "schema_version) VALUES "
                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    piece.kind,
                    version,
                    piece.parent_id,
                    piece.title,
                    piece.dek,
                    piece.body,
                    _json(piece.tags),
                    _json(piece.sources),
                    _json(piece.credit_lines),
                    _json(piece.voice_warnings),
                    _json(piece.voice_sample_ids),
                    piece.angle,
                    piece.target_length,
                    timestamp,
                    piece.schema_version,
                ),
            )
            self.connection.commit()
        return replace(
            piece,
            id=int(cursor.lastrowid),
            version=version,
            created_at=timestamp,
        )

    @staticmethod
    def _piece_row(row: sqlite3.Row | None) -> PieceContract | None:
        if row is None:
            return None
        return PieceContract(
            id=int(row["id"]),
            kind=str(row["kind"]),
            version=int(row["version"]),
            parent_id=(
                int(row["parent_id"])
                if row["parent_id"] is not None else None
            ),
            title=str(row["title"] or ""),
            dek=str(row["dek"] or ""),
            body=str(row["body"]),
            tags=list(_load_json(row["tags_json"], [])),
            sources=_sources(row["sources_json"]),
            credit_lines=list(
                _load_json(row["credit_lines_json"], [])),
            voice_warnings=list(
                _load_json(row["voice_warnings_json"], [])),
            voice_sample_ids=[
                int(value)
                for value in _load_json(
                    row["voice_sample_ids_json"], [])
            ],
            angle=str(row["angle"] or ""),
            target_length=(
                int(row["target_length"])
                if row["target_length"] is not None else None
            ),
            created_at=str(row["created_at"]),
            schema_version=int(row["schema_version"]),
        ).validate()

    def get_piece(self, piece_id: int) -> PieceContract | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM pieces WHERE id=?",
                (int(piece_id),),
            ).fetchone()
        return self._piece_row(row)

    def list_pieces(self, *, kind: str | None = None,
                    limit: int = 100) -> list[PieceContract]:
        count = max(1, min(int(limit), 500))
        with self._lock:
            if kind:
                rows = self.connection.execute(
                    "SELECT * FROM pieces WHERE kind=? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (kind, count),
                ).fetchall()
            else:
                rows = self.connection.execute(
                    "SELECT * FROM pieces "
                    "ORDER BY created_at DESC LIMIT ?",
                    (count,),
                ).fetchall()
        return [
            piece for row in rows
            if (piece := self._piece_row(row)) is not None
        ]

    def active_voice_sample_count(self) -> int:
        with self._lock:
            row = self.connection.execute(
                "SELECT COUNT(*) AS count FROM voice_samples "
                "WHERE active=1"
            ).fetchone()
        return int(row["count"] if row else 0)

    def add_voice_sample(
            self, sample: VoiceSampleContract) -> VoiceSampleContract:
        sample.validate()
        if sample.id is not None:
            raise ValueError("new voice sample must not have an id")
        timestamp = sample.added_at or now_iso()
        with self._lock:
            if sample.active:
                row = self.connection.execute(
                    "SELECT COUNT(*) AS count FROM voice_samples "
                    "WHERE active=1"
                ).fetchone()
                if int(row["count"] if row else 0) >= VOICE_SAMPLE_CAP:
                    raise ValueError(
                        f"active voice samples capped at "
                        f"{VOICE_SAMPLE_CAP}")
            cursor = self.connection.execute(
                "INSERT INTO voice_samples "
                "(name, source_type, source_url, raw_text, active, "
                "is_default, added_at, schema_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sample.name.strip(),
                    sample.source_type,
                    sample.source_url,
                    sample.raw_text,
                    1 if sample.active else 0,
                    1 if sample.default else 0,
                    timestamp,
                    sample.schema_version,
                ),
            )
            self.connection.commit()
        return replace(
            sample,
            id=int(cursor.lastrowid),
            added_at=timestamp,
        )

    @staticmethod
    def _voice_row(
            row: sqlite3.Row | None) -> VoiceSampleContract | None:
        if row is None:
            return None
        return VoiceSampleContract(
            id=int(row["id"]),
            name=str(row["name"]),
            source_type=str(row["source_type"]),
            source_url=str(row["source_url"] or ""),
            raw_text=str(row["raw_text"] or ""),
            active=bool(row["active"]),
            default=bool(row["is_default"]),
            added_at=str(row["added_at"]),
            schema_version=int(row["schema_version"]),
        ).validate()

    def get_voice_sample(
            self, sample_id: int) -> VoiceSampleContract | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM voice_samples WHERE id=?",
                (int(sample_id),),
            ).fetchone()
        return self._voice_row(row)

    def list_voice_samples(
            self, *, active_only: bool = False) -> list[VoiceSampleContract]:
        sql = "SELECT * FROM voice_samples"
        if active_only:
            sql += " WHERE active=1"
        sql += " ORDER BY added_at DESC, id DESC"
        with self._lock:
            rows = self.connection.execute(sql).fetchall()
        return [
            sample for row in rows
            if (sample := self._voice_row(row)) is not None
        ]

    def update_voice_sample(
            self, sample_id: int, *, name: str | None = None,
            active: bool | None = None) -> VoiceSampleContract:
        existing = self.get_voice_sample(sample_id)
        if existing is None:
            raise ValueError(f"voice sample not found: {sample_id}")
        updated = replace(
            existing,
            name=(name.strip() if name is not None else existing.name),
            active=(bool(active) if active is not None else existing.active),
        )
        updated.validate()
        with self._lock:
            if updated.active and not existing.active:
                row = self.connection.execute(
                    "SELECT COUNT(*) AS count FROM voice_samples "
                    "WHERE active=1"
                ).fetchone()
                if int(row["count"] if row else 0) >= VOICE_SAMPLE_CAP:
                    raise ValueError(
                        f"active voice samples capped at "
                        f"{VOICE_SAMPLE_CAP}")
            self.connection.execute(
                "UPDATE voice_samples SET name=?, active=? WHERE id=?",
                (
                    updated.name,
                    1 if updated.active else 0,
                    sample_id,
                ),
            )
            self.connection.commit()
        return updated

    def remove_voice_sample(self, sample_id: int) -> bool:
        with self._lock:
            cursor = self.connection.execute(
                "DELETE FROM voice_samples WHERE id=?",
                (int(sample_id),),
            )
            self.connection.commit()
        return cursor.rowcount > 0

    def save_script(self, script: ScriptContract) -> ScriptContract:
        script.validate()
        if script.id is not None:
            raise ValueError("scripts are immutable; save a revision")
        version = 1
        if script.parent_id is not None:
            parent = self.get_script(script.parent_id)
            if parent is None:
                raise ValueError(
                    f"parent script not found: {script.parent_id}")
            version = parent.version + 1
        timestamp = script.created_at or now_iso()
        with self._lock:
            cursor = self.connection.execute(
                "INSERT INTO scripts "
                "(version, parent_id, format, target_length_sec, hook, "
                "beats_json, body, cta, shots_json, sources_json, "
                "assembly_query_json, created_at, schema_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    version,
                    script.parent_id,
                    script.format,
                    script.target_length_sec,
                    script.hook,
                    _json(script.beats),
                    script.body,
                    script.cta,
                    _json(script.shots),
                    _json(script.sources),
                    (
                        _json(script.assembly_query)
                        if script.assembly_query is not None else None
                    ),
                    timestamp,
                    script.schema_version,
                ),
            )
            self.connection.commit()
        return replace(
            script,
            id=int(cursor.lastrowid),
            version=version,
            created_at=timestamp,
        )

    @staticmethod
    def _script_row(row: sqlite3.Row | None) -> ScriptContract | None:
        if row is None:
            return None
        query = _load_json(row["assembly_query_json"], None)
        return ScriptContract(
            id=int(row["id"]),
            version=int(row["version"]),
            parent_id=(
                int(row["parent_id"])
                if row["parent_id"] is not None else None
            ),
            format=str(row["format"] or ""),
            target_length_sec=(
                int(row["target_length_sec"])
                if row["target_length_sec"] is not None else None
            ),
            hook=str(row["hook"]),
            beats=[
                Beat.from_dict(item)
                for item in _load_json(row["beats_json"], [])
            ],
            body=str(row["body"] or ""),
            cta=str(row["cta"] or ""),
            shots=[
                Shot.from_dict(item)
                for item in _load_json(row["shots_json"], [])
            ],
            sources=_sources(row["sources_json"]),
            assembly_query=(
                AssemblyQuery.from_dict(query)
                if isinstance(query, dict) else None
            ),
            created_at=str(row["created_at"]),
            schema_version=int(row["schema_version"]),
        ).validate()

    def get_script(self, script_id: int) -> ScriptContract | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM scripts WHERE id=?",
                (int(script_id),),
            ).fetchone()
        return self._script_row(row)

    def list_scripts(self, *, limit: int = 100) -> list[ScriptContract]:
        count = max(1, min(int(limit), 500))
        with self._lock:
            rows = self.connection.execute(
                "SELECT * FROM scripts "
                "ORDER BY created_at DESC LIMIT ?",
                (count,),
            ).fetchall()
        return [
            script for row in rows
            if (script := self._script_row(row)) is not None
        ]

    def save_critique(
            self, critique: CritiqueContract) -> CritiqueContract:
        critique.validate()
        if critique.id is not None:
            raise ValueError("critiques are immutable")
        timestamp = critique.created_at or now_iso()
        with self._lock:
            cursor = self.connection.execute(
                "INSERT INTO critiques "
                "(script_id, piece_id, draft_text, findings_json, mode, "
                "created_at, schema_version) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    critique.script_id,
                    critique.piece_id,
                    critique.draft_text,
                    _json(critique.findings),
                    critique.mode,
                    timestamp,
                    critique.schema_version,
                ),
            )
            self.connection.commit()
        return replace(
            critique,
            id=int(cursor.lastrowid),
            created_at=timestamp,
        )

    @staticmethod
    def _critique_row(
            row: sqlite3.Row | None) -> CritiqueContract | None:
        if row is None:
            return None
        return CritiqueContract(
            id=int(row["id"]),
            script_id=(
                int(row["script_id"])
                if row["script_id"] is not None else None
            ),
            piece_id=(
                int(row["piece_id"])
                if row["piece_id"] is not None else None
            ),
            draft_text=str(row["draft_text"]),
            findings=dict(
                _load_json(row["findings_json"], {})),
            mode=str(row["mode"]),
            created_at=str(row["created_at"]),
            schema_version=int(row["schema_version"]),
        ).validate()

    def list_critiques(
            self, *, script_id: int | None = None,
            piece_id: int | None = None,
            limit: int = 100) -> list[CritiqueContract]:
        count = max(1, min(int(limit), 500))
        where = []
        params: list[Any] = []
        if script_id is not None:
            where.append("script_id=?")
            params.append(int(script_id))
        if piece_id is not None:
            where.append("piece_id=?")
            params.append(int(piece_id))
        sql = "SELECT * FROM critiques"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(count)
        with self._lock:
            rows = self.connection.execute(sql, params).fetchall()
        return [
            critique for row in rows
            if (critique := self._critique_row(row)) is not None
        ]

    def get_critique(
            self, critique_id: int) -> CritiqueContract | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM critiques WHERE id=?",
                (int(critique_id),),
            ).fetchone()
        return self._critique_row(row)
