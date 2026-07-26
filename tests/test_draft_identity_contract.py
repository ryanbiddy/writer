from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.request

import pytest

from writer.http_api import create_server
from writer.mcp_server import WriterTools, build_server
from writer.schemas import DraftContract, SchemaError
from writer.storage import WriterStore


BAD_IDS = (True, False, "1", 1.0, 0, -1, [], {})
ERROR = "draft.id must be null or a positive integer"


def draft(body: str, *, draft_id=None) -> dict:
    payload = {"kind": "blog", "body": body}
    if draft_id is not None:
        payload["id"] = draft_id
    return payload


@pytest.mark.parametrize("bad_id", BAD_IDS)
def test_draft_contract_rejects_non_integer_identity(bad_id):
    with pytest.raises(SchemaError, match=r"^draft\.id must be"):
        DraftContract.from_dict(draft("replacement", draft_id=bad_id))


def test_direct_tool_rejects_aliases_without_overwriting(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        tools = WriterTools(store)
        assert tools.save_draft(draft("original"))["draft"]["id"] == 1

        for bad_id in BAD_IDS:
            assert tools.save_draft(
                draft("must not persist", draft_id=bad_id)
            ) == {"ok": False, "error": ERROR}
            assert store.get_draft(1).body == "original"

        updated = tools.save_draft(draft("valid update", draft_id=1))
        assert updated["ok"] is True
        assert updated["draft"]["id"] == 1
        assert store.get_draft(1).body == "valid update"
    finally:
        store.close()


def test_fastmcp_rejects_nested_aliases_without_overwriting(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        tools = WriterTools(store)
        tools.save_draft(draft("original"))
        server = build_server(tools)

        async def call_tool(bad_id):
            return await server._tool_manager.call_tool(
                "save_draft",
                {"draft": draft("must not persist", draft_id=bad_id)},
                convert_result=False,
            )

        for bad_id in BAD_IDS:
            assert asyncio.run(call_tool(bad_id)) == {
                "ok": False,
                "error": ERROR,
            }
            assert store.get_draft(1).body == "original"
    finally:
        store.close()


@pytest.fixture
def writer_http(tmp_path):
    server = create_server(
        host="127.0.0.1",
        port=0,
        token="writer-test-token",
        database=tmp_path / "writer.db",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post_draft(server, payload):
    request = urllib.request.Request(
        "http://127.0.0.1:"
        f"{int(server.server_address[1])}/api/writer/v1/drafts",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Writer-Token": "writer-test-token",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_http_rejects_aliases_without_overwriting(writer_http):
    status, saved = post_draft(writer_http, draft("original"))
    assert status == 200
    assert saved["data"]["draft"]["id"] == 1

    for bad_id in BAD_IDS:
        status, rejected = post_draft(
            writer_http,
            draft("must not persist", draft_id=bad_id),
        )
        assert status == 400
        assert rejected["error"] == {
            "code": "request_failed",
            "message": ERROR,
        }
        assert writer_http.store.get_draft(1).body == "original"
