from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.request

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from writer.http_api import create_server
from writer.mcp_server import WriterTools, build_server
from writer.storage import WriterStore
from writer.writing import validate_composition


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
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post_composition(port, payload):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/writer/v1/composition/validate",
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


@pytest.mark.parametrize("bad_value", ["false", 0, 1, None, [], {}])
def test_core_requires_real_attribution_boolean(bad_value):
    with pytest.raises(
        ValueError,
        match=r"^attribution_enabled must be a boolean$",
    ):
        validate_composition(
            kind="tweet",
            blocks=["Measured result."],
            credit_lines=["via Example"],
            attribution_enabled=bad_value,
        )


@pytest.mark.parametrize(
    "bad_value",
    ["via Example", 0, 1, False, {}, ["via Example", 0]],
)
def test_core_requires_credit_line_list_of_strings(bad_value):
    with pytest.raises(
        ValueError,
        match=r"^credit_lines must be null or a list of strings$",
    ):
        validate_composition(
            kind="tweet",
            blocks=["Measured result."],
            credit_lines=bad_value,
        )


@pytest.mark.parametrize("bad_value", ["false", 0, 1, None, [], {}])
def test_http_requires_real_attribution_boolean(writer_http, bad_value):
    status, payload = post_composition(writer_http, {
        "kind": "tweet",
        "blocks": ["Measured result."],
        "credit_lines": ["via Example"],
        "attribution_enabled": bad_value,
    })

    assert status == 400
    assert payload["error"]["message"] == (
        "attribution_enabled must be a boolean")


@pytest.mark.parametrize(
    "bad_value",
    ["via Example", 0, 1, False, {}, ["via Example", 0]],
)
def test_http_requires_credit_line_list_of_strings(
        writer_http, bad_value):
    status, payload = post_composition(writer_http, {
        "kind": "tweet",
        "blocks": ["Measured result."],
        "credit_lines": bad_value,
    })

    assert status == 400
    assert payload["error"]["message"] == (
        "credit_lines must be null or a list of strings")


@pytest.mark.parametrize("enabled", [True, False])
def test_real_attribution_booleans_retain_exact_meaning(
        writer_http, enabled):
    status, payload = post_composition(writer_http, {
        "kind": "tweet",
        "blocks": ["Measured result."],
        "credit_lines": ["via Example"],
        "attribution_enabled": enabled,
    })

    assert status == 200
    report = payload["data"]["report"]
    assert report["attribution_enabled"] is enabled
    assert report["footer_text"] == ("via Example" if enabled else "")


def test_null_credit_lines_remain_valid(writer_http):
    status, payload = post_composition(writer_http, {
        "kind": "tweet",
        "blocks": ["Measured result."],
        "credit_lines": None,
    })

    assert status == 200
    assert payload["data"]["report"]["footer_text"] == ""


@pytest.mark.parametrize("bad_value", ["false", "true", 0, 1])
def test_mcp_does_not_coerce_attribution_boolean(tmp_path, bad_value):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        server = build_server(WriterTools(store))

        async def call_tool():
            return await server._tool_manager.call_tool(
                "validate_composition",
                {
                    "kind": "tweet",
                    "blocks": ["Measured result."],
                    "credit_lines": ["via Example"],
                    "attribution_enabled": bad_value,
                },
                convert_result=False,
            )

        with pytest.raises(ToolError, match="valid boolean"):
            asyncio.run(call_tool())
    finally:
        store.close()


def test_mcp_composition_schema_matches_enforced_types(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        server = build_server(WriterTools(store))
        tools = asyncio.run(server.list_tools())
        schema = next(
            tool.inputSchema
            for tool in tools
            if tool.name == "validate_composition"
        )

        assert schema["properties"]["attribution_enabled"]["type"] == (
            "boolean")
        assert schema["properties"]["credit_lines"]["anyOf"][0] == {
            "items": {"type": "string"},
            "type": "array",
        }
    finally:
        store.close()
