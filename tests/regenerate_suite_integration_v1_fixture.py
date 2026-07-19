"""Regenerate Writer's synthetic S6 provider-conformance fixture.

Run:
    python tests/regenerate_suite_integration_v1_fixture.py

Check:
    python tests/regenerate_suite_integration_v1_fixture.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from writer import __version__, suite_service  # noqa: E402
from writer.mcp_server import WriterTools  # noqa: E402
from writer.schemas import Beat, Shot, SourceSnapshot  # noqa: E402
from writer.scripts import ScriptService  # noqa: E402
from writer.storage import WriterStore  # noqa: E402

FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "suite_integration_v1"
    / "writer-provider.json"
)
STARTED_AT = "2026-07-19T12:00:00Z"


def _source() -> SourceSnapshot:
    return SourceSnapshot(
        provider="uoink",
        provider_ref="uoink://item/short-123",
        title="Fixture short",
        creator="Fixture Creator",
        source_url="https://example.test/short/123",
        credit_line=(
            "Source: Fixture short by Fixture Creator -- "
            "https://example.test/short/123"
        ),
        excerpt="A bounded source snapshot.",
        attached_at=STARTED_AT,
        credit_required=True,
    ).validate()


def generate_fixture() -> dict:
    with tempfile.TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        store = WriterStore.open(root / "writer.db")
        try:
            service = ScriptService(store)
            script = service.save_script(
                hook="One local handoff kept the source credit.",
                format="tutorial",
                beats=[
                    Beat(
                        "proof",
                        "Show the verified local artifact.",
                        "0:00-0:08",
                    )
                ],
                body="The complete fixture script.",
                cta="Open the saved shot list.",
                shots=[
                    Shot(
                        scene=1,
                        label="proof",
                        cues=["screen recording", "close-up hands"],
                    )
                ],
                sources=[_source()],
            )
            output = root / "shot-list.md"
            with patch(
                "writer.scripts.now_iso",
                return_value=STARTED_AT,
            ):
                document = service.export_shot_list(
                    int(script.id),
                    output,
                    title="Fixture shot list",
                )
            shot_list = {
                "contract": "writer.shot-list",
                "version": 1,
                "document": document.to_dict(),
                "markdown": output.read_text(encoding="utf-8"),
            }
        finally:
            store.close()

        receipt_store = WriterStore.open(root / "receipt.db")
        try:
            tools = WriterTools(receipt_store, uoink=None)
            with patch(
                "writer.storage._utc_z",
                return_value=STARTED_AT,
            ):
                receipt = tools.save_piece({
                    "kind": "tweet",
                    "body": "One measured result.",
                    "sources": [_source().to_dict()],
                    "credit_lines": [_source().credit_line],
                })["engagement"]
            outbox = receipt_store.pending_engagement(limit=10)
        finally:
            receipt_store.close()

    manifest = suite_service.service_manifest(__version__)
    lease = suite_service.runtime_lease(
        __version__,
        host="127.0.0.1",
        port=5181,
        pid=1234,
        started_at=STARTED_AT,
    )
    health = suite_service.health_payload(
        __version__,
        database_ok=True,
    )
    return {
        "_fixture": {
            "contracts": [
                "ryan.suite.runtime-lease/1",
                "ryan.suite.service/1",
                "ryan.suite.health/1",
                "writer.shot-list/1",
            ],
            "provider": "Writer",
            "regenerate": (
                "python tests/regenerate_suite_integration_v1_fixture.py"
            ),
            "check": (
                "python tests/regenerate_suite_integration_v1_fixture.py --check"
            ),
            "data": "synthetic",
            "network": "none",
        },
        "valid": {
            "runtime_lease": lease,
            "service_manifest": manifest,
            "health": health,
            "shot_list": shot_list,
            "engagement": {
                "receipt": receipt,
                "outbox": outbox,
            },
        },
        "negative": {
            "runtime_lease": {
                "unknown_key": {
                    "operation": "set",
                    "path": "surprise",
                    "value": True,
                },
                "non_loopback_url": {
                    "operation": "set",
                    "path": "base_url",
                    "value": "http://192.0.2.10:5181",
                },
                "token_field": {
                    "operation": "set",
                    "path": "token",
                    "value": "must-not-cross",
                },
                "path_field": {
                    "operation": "set",
                    "path": "database_path",
                    "value": "C:\\private\\writer.db",
                },
                "command_field": {
                    "operation": "set",
                    "path": "command",
                    "value": ["python", "-m", "writer.cli"],
                },
            },
            "service_manifest": {
                "wrong_version": {
                    "operation": "set",
                    "path": "version",
                    "value": 2,
                },
                "token_field": {
                    "operation": "set",
                    "path": "service.token",
                    "value": "must-not-cross",
                },
            },
            "health": {
                "inconsistent_ok": {
                    "operation": "set",
                    "path": "ok",
                    "value": False,
                },
                "path_field": {
                    "operation": "set",
                    "path": "checks.0.path",
                    "value": "C:\\private",
                },
            },
            "shot_list": {
                "wrong_front_matter": {
                    "replace": [
                        "document_type: writer.shot-list",
                        "document_type: writer.shot-list-v2",
                    ]
                },
                "duplicate_front_matter": {
                    "insert_after": [
                        "document_type: writer.shot-list",
                        "document_type: writer.shot-list",
                    ]
                },
                "wrong_heading_order": {
                    "swap": ["## Beats", "## Script"]
                },
                "invalid_id": {
                    "replace": [
                        "source_script_id: 1",
                        "source_script_id: zero",
                    ]
                },
                "invalid_time": {
                    "replace": [
                        f"generated_at: {STARTED_AT}",
                        "generated_at: yesterday",
                    ]
                },
                "oversized": {
                    "append_bytes": 1048577
                },
                "non_utf8": {
                    "bytes_hex": "fffe00"
                },
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = (
        json.dumps(generate_fixture(), indent=2, ensure_ascii=False) + "\n"
    )
    if args.check:
        if not FIXTURE_PATH.is_file():
            print(f"missing fixture: {FIXTURE_PATH}", file=sys.stderr)
            return 1
        if FIXTURE_PATH.read_text(encoding="utf-8") != rendered:
            print(
                "Writer suite integration fixture is stale; regenerate it",
                file=sys.stderr,
            )
            return 1
        print("ok  Writer suite integration fixture is current")
        return 0
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {FIXTURE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
