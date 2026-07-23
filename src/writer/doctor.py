"""Truthful first-run checks for Writer.

Required checks cover Writer's standalone local store and the data bundled in
the installed wheel. MCP and Uoink are optional: their absence is reported as
a degraded mode and never disguised as a core-product failure.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from dataclasses import asdict, dataclass
from importlib.resources import files
from typing import Callable

from writer import __version__
from writer.mcp_server import TOOL_NAMES
from writer.storage import WriterStore
from writer.suite_peer import probe_uoink


@dataclass(frozen=True)
class Check:
    name: str
    required: bool
    ok: bool
    status: str
    detail: str
    fix: str = ""
    result: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def check_database() -> Check:
    store = None
    try:
        store = WriterStore.open()
        quick = store.connection.execute(
            "PRAGMA quick_check").fetchone()
        result = str(quick[0] if quick else "")
        version_row = store.connection.execute(
            "SELECT COALESCE(MAX(version), 0) "
            "FROM schema_migrations").fetchone()
        version = int(version_row[0] if version_row else 0)
        if result != "ok":
            raise RuntimeError(f"SQLite quick_check returned {result!r}")
        if version < 1:
            raise RuntimeError("no Writer schema migration is applied")
        return Check(
            "database", True, True, "ready",
            f"SQLite quick_check passed; schema v{version}",
        )
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        return Check(
            "database", True, False, "failed", str(exc),
            "Set WRITER_DATA_DIR to a writable local folder and rerun "
            "`writer doctor`.",
        )
    finally:
        if store is not None:
            store.close()


def check_packaged_data() -> Check:
    try:
        root = files("writer")
        required = {
            "database migration": root.joinpath(
                "migrations", "0001_initial.sql"),
            "engagement migration": root.joinpath(
                "migrations", "0002_engagement_outbox.sql"),
            "engagement retry migration": root.joinpath(
                "migrations", "0003_engagement_next_attempt.sql"),
            "Voice DNA": root.joinpath(
                "_data", "voice_dna", "VOICE-DNA.md"),
            "editor": root.joinpath("_data", "ui", "index.html"),
        }
        missing = [
            label for label, resource in required.items()
            if not resource.is_file()
        ]
        if missing:
            raise RuntimeError(
                "wheel is missing " + ", ".join(missing))
        for resource in required.values():
            if not resource.read_text(encoding="utf-8").strip():
                raise RuntimeError(
                    f"packaged file is empty: {resource.name}")
        return Check(
            "packaged_data", True, True, "ready",
            "migration, Voice DNA, and editor assets are installed",
        )
    except (OSError, RuntimeError) as exc:
        return Check(
            "packaged_data", True, False, "failed", str(exc),
            'Reinstall the wheel with `python -m pip install --force-reinstall '
            '"ryan-writer[mcp]"`.',
        )


def check_mcp() -> Check:
    if importlib.util.find_spec("mcp") is None:
        return Check(
            "mcp", False, False, "not_installed",
            "manual editor and HTTP API are ready; direct AI connection is "
            "unavailable",
            'Install it with `python -m pip install "ryan-writer[mcp]"`.',
        )
    if len(TOOL_NAMES) != 17 or len(set(TOOL_NAMES)) != 17:
        return Check(
            "mcp", False, False, "invalid_surface",
            f"declared tool surface has {len(TOOL_NAMES)} entries",
            "Reinstall Writer and rerun `writer doctor`.",
        )
    return Check(
        "mcp", False, True, "ready",
        "MCP SDK installed; 17 Writer tools declared",
    )


def check_uoink() -> Check:
    peer = probe_uoink(timeout=0.5)
    state = str(peer["state"])
    if state == "available":
        return Check(
            "uoink", False, True, state,
            "optional peer passed suite discovery, health, and corpus.read v1",
            result=peer,
        )
    if state == "absent":
        return Check(
            "uoink", False, False, state,
            "Uoink is not running; blank-page and pasted-text work remains "
            "available",
            result=peer,
        )
    if state == "unconfigured":
        return Check(
            "uoink", False, False, state,
            "Uoink is available but Writer has no configured credential",
            "Set WRITER_UOINK_TOKEN, then rerun `writer doctor`.",
            result=peer,
        )
    error = peer["error"]
    return Check(
        "uoink", False, False, state,
        f"{error['code']}: {error['message']}",
        "Check Writer's Uoink URL and token, then rerun `writer doctor`.",
        result=peer,
    )


CHECKS: tuple[Callable[[], Check], ...] = (
    check_database,
    check_packaged_data,
    check_mcp,
    check_uoink,
)


def run_checks() -> list[Check]:
    return [check() for check in CHECKS]


def summarize(checks: list[Check]) -> dict:
    required = [check for check in checks if check.required]
    optional = [check for check in checks if not check.required]
    return {
        "ok": all(check.ok for check in required),
        "service": "writer",
        "version": __version__,
        "checks": [check.to_dict() for check in checks],
        "summary": {
            "required_ready": sum(check.ok for check in required),
            "required_total": len(required),
            "optional_ready": sum(check.ok for check in optional),
            "optional_total": len(optional),
        },
    }


def run(argv: list[str] | None = None) -> int:
    args = list(argv or [])
    if any(arg not in {"--json"} for arg in args):
        print("usage: writer doctor [--json]")
        return 2
    payload = summarize(run_checks())
    if "--json" in args:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        verdict = (
            "READY for local writing"
            if payload["ok"]
            else "NOT READY: a required local check failed"
        )
        print("Writer doctor")
        print(verdict)
        for check in payload["checks"]:
            if check["ok"]:
                marker = "ok"
            elif check["required"]:
                marker = "fail"
            else:
                marker = "optional"
            print(
                f"[{marker}] {check['name']}: {check['status']} - "
                f"{check['detail']}"
            )
            if check["fix"]:
                print(f"       fix: {check['fix']}")
    return 0 if payload["ok"] else 1
