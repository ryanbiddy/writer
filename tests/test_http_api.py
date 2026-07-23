from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from writer.http_api import create_server


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


def call(port, method, path, body=None, *, token=True, host=None):
    raw = (
        json.dumps(body).encode("utf-8")
        if body is not None else None
    )
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-Writer-Token"] = "writer-test-token"
    if host is not None:
        headers["Host"] = host
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=raw,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_ping_and_manifest_are_public_path_free(writer_http):
    status, ping = call(writer_http, "GET", "/ping", token=False)
    assert status == 200
    assert ping == {
        "ok": True,
        "service": "writer",
        "version": 1,
        "status": "ready",
    }
    status, manifest = call(
        writer_http, "GET", "/manifest", token=False)
    assert status == 200
    assert manifest["service"]["id"] == "writer"
    assert manifest["service"]["default_port"] == 5181
    serialized = json.dumps(manifest)
    assert "writer.db" not in serialized
    assert "token" not in serialized.casefold()


def test_private_api_rejects_missing_token(writer_http):
    status, payload = call(
        writer_http, "GET", "/api/writer/v1/drafts", token=False)
    assert status == 401
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/ping", None),
        ("POST", "/api/writer/v1/drafts", {
            "kind": "blog",
            "title": "Blocked",
            "body": "Must not save",
        }),
        ("DELETE", "/api/writer/v1/voice-samples/1", None),
        ("OPTIONS", "/api/writer/v1/drafts", None),
    ],
)
def test_rejects_dns_rebinding_host_before_every_route(
        writer_http, method, path, body):
    status, payload = call(
        writer_http,
        method,
        path,
        body,
        host="evil.attacker.test",
    )
    assert status == 403
    assert payload["error"] == {
        "code": "forbidden_host",
        "message": "Request Host must be loopback",
    }


def test_host_guard_accepts_loopback_name_and_bound_port(writer_http):
    status, ping = call(
        writer_http,
        "GET",
        "/ping",
        token=False,
        host=f"localhost:{writer_http}",
    )
    assert status == 200
    assert ping["status"] == "ready"

    status, payload = call(
        writer_http,
        "GET",
        "/ping",
        token=False,
        host="127.0.0.1:1",
    )
    assert status == 403
    assert payload["error"]["code"] == "forbidden_host"


def test_invalid_request_returns_json_instead_of_dropping_connection(
        writer_http):
    status, payload = call(
        writer_http, "POST", "/api/writer/v1/prepare", {
            "unexpected": True,
        })
    assert status == 400
    assert payload["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(
    "path",
    [
        "/api/writer/v1/drafts?limit=nope",
        "/api/writer/v1/pieces?limit=0",
        "/api/writer/v1/scripts?limit=501",
    ],
)
def test_invalid_list_limit_returns_json_instead_of_dropping_connection(
        writer_http, path):
    status, payload = call(writer_http, "GET", path)

    assert status == 400
    assert payload["error"] == {
        "code": "invalid_request",
        "message": "limit must be an integer between 1 and 500",
    }


def test_invalid_active_only_flag_returns_json(writer_http):
    status, payload = call(
        writer_http,
        "GET",
        "/api/writer/v1/voice-samples?active_only=maybe",
    )

    assert status == 400
    assert payload["error"] == {
        "code": "invalid_request",
        "message": "active_only must be 0 or 1",
    }


def test_manual_draft_and_source_free_prepare_round_trip(writer_http):
    status, saved = call(writer_http, "POST", "/api/writer/v1/drafts", {
        "kind": "blog",
        "title": "Manual",
        "body": "My local draft.",
    })
    assert status == 200
    assert saved["data"]["draft"]["id"] == 1
    status, restored = call(
        writer_http, "GET", "/api/writer/v1/drafts/1")
    assert status == 200
    assert restored["data"]["draft"]["body"] == "My local draft."

    status, prepared = call(
        writer_http, "POST", "/api/writer/v1/prepare", {
            "kind": "blog",
            "brief": "Tighten this.",
            "draft_text": "My local draft.",
        })
    assert status == 200
    prompt = prepared["data"]["prompt"]
    assert prompt["dependency_status"] == {
        "uoink": "not_requested"}
    assert prompt["context"]["draft_text"] == "My local draft."


def test_voice_sample_scan_piece_and_script_routes(writer_http, tmp_path):
    status, sample = call(
        writer_http, "POST", "/api/writer/v1/voice-samples", {
            "name": "Fixture voice",
            "source_type": "text",
            "raw_text": "Name the measured result.",
        })
    assert status == 200
    assert sample["data"]["voice_sample"]["id"] == 1

    status, scan = call(
        writer_http, "POST", "/api/writer/v1/voice/scan", {
            "text": "A robust plan.",
        })
    assert status == 200
    assert scan["data"]["warnings"][0]["phrase"] == "robust"

    status, piece = call(
        writer_http, "POST", "/api/writer/v1/pieces", {
            "kind": "tweet",
            "body": "One measured result.",
            "voice_sample_ids": [1],
        })
    assert status == 200
    assert piece["data"]["piece"]["id"] == 1

    status, script = call(
        writer_http, "POST", "/api/writer/v1/scripts", {
            "hook": "The local run took 12 seconds.",
            "format": "tutorial",
            "beats": [
                {"label": "proof", "content": "Show the result."}
            ],
            "body": "A complete script.",
            "cta": "Measure one run.",
        })
    assert status == 200
    script_id = script["data"]["script"]["id"]
    status, derived = call(
        writer_http, "POST",
        f"/api/writer/v1/scripts/{script_id}/derive-shots", {})
    assert status == 200
    derived_id = derived["data"]["script"]["id"]
    assert derived["data"]["script"]["shots"][0]["scene"] == 1

    output = tmp_path / "shot-list.md"
    status, exported = call(
        writer_http, "POST",
        f"/api/writer/v1/scripts/{derived_id}/export", {
            "output": str(output),
        })
    assert status == 200
    assert exported["data"]["document"]["document_type"] == (
        "writer.shot-list")
    assert output.is_file()


def test_ui_is_standalone_and_honest(writer_http):
    with urllib.request.urlopen(
            f"http://127.0.0.1:{writer_http}/", timeout=3) as response:
        text = response.read().decode("utf-8")
    assert response.status == 200
    assert "<title>Recount</title>" in text
    assert "Save draft" in text
    assert "Attach Uoink source" in text
    assert "Connect an AI through Recount's MCP server" in text
    assert "publish" not in text.casefold()
