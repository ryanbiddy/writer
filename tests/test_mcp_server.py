from __future__ import annotations

import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from writer import __version__
from writer.mcp_server import TOOL_NAMES, WriterTools, build_server
from writer.schemas import VoiceSampleContract
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
    ("call", "error"),
    [
        (lambda tools: tools.get_draft(True), "draft_id"),
        (lambda tools: tools.list_pieces(limit="1"), "limit"),
        (lambda tools: tools.critique_script(True), "script_id"),
        (
            lambda tools: tools.revise_script(
                1, critique_id="1"),
            "critique_id",
        ),
        (lambda tools: tools.derive_shot_list(False), "script_id"),
        (
            lambda tools: tools.export_shot_list(
                "1", "must-not-exist.md"),
            "script_id",
        ),
        (
            lambda tools: tools.list_voice_samples(
                active_only="false"),
            "active_only",
        ),
    ],
)
def test_direct_scalar_aliases_fail_before_domain_work(
        tmp_path, monkeypatch, call, error):
    monkeypatch.chdir(tmp_path)
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        result = call(WriterTools(store))

        assert result["ok"] is False
        assert error in result["error"]
        assert not (tmp_path / "must-not-exist.md").exists()
    finally:
        store.close()


@pytest.mark.parametrize("bad_id", [True, False, "1", 1.0, None, [], {}])
def test_remove_voice_sample_rejects_alias_without_deleting(
        tmp_path, bad_id):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        sample = store.add_voice_sample(VoiceSampleContract(
            name="Keep me",
            source_type="text",
            raw_text="A measured local voice sample.",
        ))

        result = WriterTools(store).remove_voice_sample(bad_id)

        assert result == {
            "ok": False,
            "error": "sample_id must be a positive integer",
        }
        assert store.get_voice_sample(sample.id) == sample
    finally:
        store.close()


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "prepare_draft",
            {
                "kind": "blog",
                "brief": "Measured note.",
                "target_length": True,
            },
        ),
        (
            "prepare_draft",
            {
                "kind": "blog",
                "brief": "Measured note.",
                "voice_sample_ids": ["1"],
            },
        ),
        ("get_draft", {"draft_id": "1"}),
        ("list_pieces", {"limit": True}),
        ("critique_script", {"script_id": "1"}),
        (
            "revise_script",
            {"script_id": 1, "critique_id": "1"},
        ),
        ("derive_shot_list", {"script_id": False}),
        (
            "export_shot_list",
            {"script_id": "1", "output": "must-not-exist.md"},
        ),
        ("list_voice_samples", {"active_only": "false"}),
        ("remove_voice_sample", {"sample_id": "1"}),
    ],
)
def test_fastmcp_rejects_scalar_aliases(
        tmp_path, monkeypatch, tool_name, arguments):
    monkeypatch.chdir(tmp_path)
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        server = build_server(WriterTools(store))

        async def call_tool():
            return await server._tool_manager.call_tool(
                tool_name,
                arguments,
                convert_result=False,
            )

        with pytest.raises(ToolError):
            asyncio.run(call_tool())
        assert not (tmp_path / "must-not-exist.md").exists()
    finally:
        store.close()


def test_fastmcp_strict_scalars_keep_the_public_schema(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        server = build_server(WriterTools(store))
        tools = {
            tool.name: tool.inputSchema
            for tool in asyncio.run(server.list_tools())
        }

        assert tools["remove_voice_sample"]["properties"]["sample_id"][
            "type"] == "integer"
        assert tools["list_voice_samples"]["properties"]["active_only"][
            "type"] == "boolean"
        assert tools["prepare_draft"]["properties"]["voice_sample_ids"][
            "anyOf"][0] == {
                "items": {"type": "integer"},
                "type": "array",
            }
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


@pytest.mark.parametrize(
    ("script", "error"),
    [
        (
            {
                "hook": "Hook.",
                "beats": [{"label": 123, "content": []}],
            },
            "beat.label must be a string",
        ),
        (
            {
                "hook": "Hook.",
                "shots": [{
                    "scene": True,
                    "label": "proof",
                    "cues": ["wide"],
                }],
            },
            "shot.scene must be positive",
        ),
        (
            {
                "hook": "Hook.",
                "shots": [{
                    "scene": 1,
                    "label": "proof",
                    "cues": "wide",
                }],
            },
            "shot.cues must be a list of strings",
        ),
        (
            {
                "hook": "Hook.",
                "shots": [{
                    "scene": 1,
                    "label": "proof",
                    "cues": ["wide"],
                    "notes": [],
                }],
            },
            "shot.notes must be a string",
        ),
    ],
)
def test_malformed_nested_script_fields_are_not_persisted(
        tmp_path, script, error):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        result = WriterTools(store).save_script(script)

        assert result["ok"] is False
        assert result["error"] == error
        assert store.list_scripts() == []
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
