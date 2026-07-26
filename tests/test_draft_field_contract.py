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


BAD_FIELDS = (
    ({"title": 123}, "draft.title must be a string"),
    ({"title": []}, "draft.title must be a string"),
    ({"title": {}}, "draft.title must be a string"),
    ({"brief": 456}, "draft.brief must be a string"),
    ({"brief": []}, "draft.brief must be a string"),
    ({"brief": {}}, "draft.brief must be a string"),
    ({"created_at": 789}, "draft.created_at must be a string"),
    ({"created_at": []}, "draft.created_at must be a string"),
    ({"created_at": {}}, "draft.created_at must be a string"),
    ({"updated_at": 999}, "draft.updated_at must be a string"),
    ({"updated_at": []}, "draft.updated_at must be a string"),
    ({"updated_at": {}}, "draft.updated_at must be a string"),
)


def payload(**fields) -> dict:
    return {"kind": "blog", "body": "A measured draft.", **fields}


@pytest.mark.parametrize(
    ("fields", "field"),
    (
        ({"title": 123}, "title"),
        ({"brief": 456}, "brief"),
        ({"created_at": 789}, "created_at"),
        ({"updated_at": 999}, "updated_at"),
    ),
)
def test_draft_contract_rejects_non_string_fields(fields, field):
    with pytest.raises(
        SchemaError,
        match=rf"^draft\.{field} must be a string$",
    ):
        DraftContract.from_dict(payload(**fields))


@pytest.mark.parametrize(("fields", "error"), BAD_FIELDS)
def test_direct_tool_rejects_non_string_draft_fields(
        tmp_path, fields, error):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        result = WriterTools(store).save_draft(payload(**fields))

        assert result == {"ok": False, "error": error}
        assert store.entity_counts()["drafts"] == 0
    finally:
        store.close()


def test_valid_draft_strings_round_trip_without_type_drift(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        result = WriterTools(store).save_draft(payload(
            title="Measured",
            brief="Preserve the exact types.",
            created_at="2030-01-02T03:04:05Z",
        ))

        assert result["ok"] is True
        saved = result["draft"]
        restored = store.get_draft(saved["id"]).to_dict()
        assert saved == restored
    finally:
        store.close()


@pytest.mark.parametrize(
    ("fields", "error"),
    (
        ({"title": 123}, "draft.title must be a string"),
        ({"brief": 456}, "draft.brief must be a string"),
        ({"created_at": 789}, "draft.created_at must be a string"),
        ({"updated_at": 999}, "draft.updated_at must be a string"),
    ),
)
def test_fastmcp_rejects_non_string_draft_fields(
        tmp_path, fields, error):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        server = build_server(WriterTools(store))

        async def call_tool():
            return await server._tool_manager.call_tool(
                "save_draft",
                {"draft": payload(**fields)},
                convert_result=False,
            )

        assert asyncio.run(call_tool()) == {"ok": False, "error": error}
        assert store.entity_counts()["drafts"] == 0
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


def post_draft(server, body):
    request = urllib.request.Request(
        "http://127.0.0.1:"
        f"{int(server.server_address[1])}/api/writer/v1/drafts",
        data=json.dumps(body).encode("utf-8"),
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


@pytest.mark.parametrize(
    ("fields", "error"),
    (
        ({"title": 123}, "draft.title must be a string"),
        ({"brief": 456}, "draft.brief must be a string"),
        ({"created_at": 789}, "draft.created_at must be a string"),
        ({"updated_at": 999}, "draft.updated_at must be a string"),
    ),
)
def test_http_rejects_non_string_draft_fields(
        writer_http, fields, error):
    status, rejected = post_draft(
        writer_http,
        payload(**fields),
    )

    assert status == 400
    assert rejected["error"] == {
        "code": "request_failed",
        "message": error,
    }
    assert writer_http.store.entity_counts()["drafts"] == 0
