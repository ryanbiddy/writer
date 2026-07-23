from __future__ import annotations

import asyncio

import pytest

from writer import __version__
from writer.mcp_server import TOOL_NAMES, WriterTools, build_server
from writer.storage import WriterStore


EXPECTED_TOOLS = {
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
}


def test_mcp_surface_is_product_owned_and_complete():
    assert set(TOOL_NAMES) == EXPECTED_TOOLS
    assert not any(name.startswith("uoink_") for name in TOOL_NAMES)
    assert not any(name.startswith("zing_") for name in TOOL_NAMES)


def test_fastmcp_registers_the_same_surface(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        server = build_server(WriterTools(store))

        async def names():
            return {
                tool.name for tool in await server.list_tools()}

        assert asyncio.run(names()) == EXPECTED_TOOLS
        assert server._mcp_server.version == __version__
    finally:
        store.close()


def test_handlers_keep_errors_as_data_and_support_manual_work(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        tools = WriterTools(store)
        prepared = tools.prepare_draft(
            kind="newsletter",
            brief="Use my original notes.",
            draft_text="Manual notes.",
        )
        assert prepared["ok"] is True
        assert prepared["prompt"]["sources"] == []

        draft = tools.save_draft({
            "kind": "newsletter",
            "body": "Manual notes.",
        })
        assert draft["ok"] is True
        assert tools.get_draft(draft["draft"]["id"])["draft"][
            "body"] == "Manual notes."

        missing = tools.get_draft(999)
        assert missing == {
            "ok": False,
            "error": "draft not found: 999",
        }
    finally:
        store.close()


def test_mcp_script_critique_two_phase(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        tools = WriterTools(store)
        saved = tools.save_script({
            "hook": "The test took 12 seconds.",
            "body": "A complete script.",
        })
        script_id = saved["script"]["id"]
        context = tools.critique_script(script_id, focus="pacing")
        assert context["ok"] is True
        assert context["mode"] == "context_only"
        persisted = tools.critique_script(
            script_id,
            findings={"pacing": "Cut the first sentence."},
        )
        assert persisted["ok"] is True
        assert persisted["mode"] == "persisted"
        revision = tools.revise_script(
            script_id,
            critique_id=persisted["critique"]["id"],
        )
        assert revision["mode"] == "context_only"
    finally:
        store.close()


@pytest.mark.parametrize(
    ("method", "payload"),
    [
        (
            "save_piece",
            {"kind": "blog", "body": "Body.", "unexpected": True},
        ),
        (
            "save_script",
            {"hook": "Hook.", "unexpected": True},
        ),
        (
            "save_script",
            {"hook": "Hook.", "beats": [1]},
        ),
        (
            "save_draft",
            {
                "kind": "blog",
                "sources": [{
                    "provider": "uoink",
                    "provider_ref": 1,
                }],
            },
        ),
        (
            "add_voice_sample",
            {
                "name": "Voice",
                "source_type": "text",
                "raw_text": "Plain sample.",
                "unexpected": True,
            },
        ),
    ],
)
def test_nested_payload_errors_remain_tool_data(tmp_path, method, payload):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        result = getattr(WriterTools(store), method)(payload)
        assert result["ok"] is False
        assert result["error"].startswith("invalid request: ")
    finally:
        store.close()


def test_writer_status_counts_every_record_beyond_list_page_cap(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        store.connection.executemany(
            "INSERT INTO drafts "
            "(kind, title, body, brief, sources_json, "
            "voice_sample_ids_json, created_at, updated_at, schema_version) "
            "VALUES ('blog', '', '', '', '[]', '[]', ?, ?, 1)",
            [
                (f"2026-07-19T00:{index // 60:02d}:{index % 60:02d}Z",) * 2
                for index in range(501)
            ],
        )
        store.connection.commit()

        status = WriterTools(store).writer_status()

        assert status["counts"]["drafts"] == 501
    finally:
        store.close()
