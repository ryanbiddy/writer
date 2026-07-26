from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.request

import pytest

from writer.http_api import create_server
from writer.mcp_server import WriterTools, build_server
from writer.schemas import PieceContract, SchemaError
from writer.storage import WriterStore


BAD_PARENT_IDS = (True, False, "1", 1.0, 0, -1, [], {})
ERROR = "piece.parent_id must be null or a positive integer"


def piece(body: str, *, parent_id=None) -> dict:
    payload = {"kind": "blog", "body": body}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return payload


@pytest.mark.parametrize("bad_id", BAD_PARENT_IDS)
def test_piece_contract_rejects_parent_aliases(bad_id):
    with pytest.raises(
        SchemaError,
        match=r"^piece\.parent_id must be",
    ):
        PieceContract(
            kind="blog",
            body="child",
            parent_id=bad_id,
        ).validate()


def test_direct_tool_rejects_aliases_without_linking(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        tools = WriterTools(store)
        assert tools.save_piece(piece("parent"))["piece"]["id"] == 1

        for bad_id in BAD_PARENT_IDS:
            assert tools.save_piece(
                piece("must not persist", parent_id=bad_id)
            ) == {"ok": False, "error": ERROR}
            assert store.entity_counts()["pieces"] == 1

        child = tools.save_piece(piece("child", parent_id=1))
        assert child["ok"] is True
        assert child["piece"]["parent_id"] == 1
        assert child["piece"]["version"] == 2
        assert store.entity_counts()["pieces"] == 2
    finally:
        store.close()


def test_fastmcp_rejects_parent_aliases_without_linking(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        tools = WriterTools(store)
        tools.save_piece(piece("parent"))
        server = build_server(tools)

        async def call_tool(bad_id):
            return await server._tool_manager.call_tool(
                "save_piece",
                {"piece": piece("must not persist", parent_id=bad_id)},
                convert_result=False,
            )

        for bad_id in BAD_PARENT_IDS:
            assert asyncio.run(call_tool(bad_id)) == {
                "ok": False,
                "error": ERROR,
            }
            assert store.entity_counts()["pieces"] == 1
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


def post_piece(server, payload):
    request = urllib.request.Request(
        "http://127.0.0.1:"
        f"{int(server.server_address[1])}/api/writer/v1/pieces",
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


def test_http_rejects_parent_aliases_without_linking(writer_http):
    status, saved = post_piece(writer_http, piece("parent"))
    assert status == 200
    assert saved["data"]["piece"]["id"] == 1

    for bad_id in BAD_PARENT_IDS:
        status, rejected = post_piece(
            writer_http,
            piece("must not persist", parent_id=bad_id),
        )
        assert status == 400
        assert rejected["error"] == {
            "code": "request_failed",
            "message": ERROR,
        }
        assert writer_http.store.entity_counts()["pieces"] == 1
