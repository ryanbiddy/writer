from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.request

import pytest

from writer.http_api import create_server
from writer.mcp_server import WriterTools, build_server
from writer.schemas import SchemaError, ScriptContract
from writer.storage import WriterStore


BAD_FIELDS = (
    ({"hook": 1}, "script.hook must be a string"),
    ({"hook": []}, "script.hook must be a string"),
    ({"hook": None}, "script.hook must be a string"),
    ({"format": 123}, "script.format must be a string or null"),
    ({"format": []}, "script.format must be a string or null"),
    ({"format": {}}, "script.format must be a string or null"),
    ({"body": 456}, "script.body must be a string or null"),
    ({"body": []}, "script.body must be a string or null"),
    ({"body": {}}, "script.body must be a string or null"),
    ({"cta": 789}, "script.cta must be a string or null"),
    ({"cta": []}, "script.cta must be a string or null"),
    ({"cta": {}}, "script.cta must be a string or null"),
)


def payload(**fields) -> dict:
    return {"hook": "measured hook", **fields}


@pytest.mark.parametrize(
    ("fields", "field"),
    (
        ({"hook": 1}, "hook"),
        ({"format": 123}, "format"),
        ({"body": 456}, "body"),
        ({"cta": 789}, "cta"),
    ),
)
def test_script_contract_rejects_non_string_fields(fields, field):
    with pytest.raises(
        SchemaError,
        match=rf"^script\.{field} must be a string$",
    ):
        ScriptContract(**payload(**fields)).validate()


@pytest.mark.parametrize(("fields", "error"), BAD_FIELDS)
def test_direct_tool_rejects_non_string_fields(
        tmp_path, fields, error):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        result = WriterTools(store).save_script(payload(**fields))

        assert result == {"ok": False, "error": error}
        assert store.entity_counts()["scripts"] == 0
    finally:
        store.close()


def test_valid_script_strings_round_trip_without_type_drift(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        result = WriterTools(store).save_script(payload(
            format="tutorial",
            body="A measured body.",
            cta="Measure one run.",
        ))

        assert result["ok"] is True
        saved = result["script"]
        restored = store.get_script(saved["id"]).to_dict()
        assert saved == restored
    finally:
        store.close()


@pytest.mark.parametrize(
    ("fields", "error"),
    (
        ({"hook": 1}, "script.hook must be a string"),
        ({"format": 123}, "script.format must be a string or null"),
        ({"body": 456}, "script.body must be a string or null"),
        ({"cta": 789}, "script.cta must be a string or null"),
    ),
)
def test_fastmcp_rejects_non_string_script_fields(
        tmp_path, fields, error):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        server = build_server(WriterTools(store))

        async def call_tool():
            return await server._tool_manager.call_tool(
                "save_script",
                {"script": payload(**fields)},
                convert_result=False,
            )

        assert asyncio.run(call_tool()) == {"ok": False, "error": error}
        assert store.entity_counts()["scripts"] == 0
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


def post_script(server, body):
    request = urllib.request.Request(
        "http://127.0.0.1:"
        f"{int(server.server_address[1])}/api/writer/v1/scripts",
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
        ({"hook": 1}, "script.hook must be a string"),
        ({"format": 123}, "script.format must be a string or null"),
        ({"body": 456}, "script.body must be a string or null"),
        ({"cta": 789}, "script.cta must be a string or null"),
    ),
)
def test_http_rejects_non_string_script_fields(
        writer_http, fields, error):
    status, rejected = post_script(
        writer_http,
        payload(**fields),
    )

    assert status == 400
    assert rejected["error"] == {
        "code": "request_failed",
        "message": error,
    }
    assert writer_http.store.entity_counts()["scripts"] == 0
