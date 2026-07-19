from __future__ import annotations

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from writer.schemas import AssemblyQuery
from writer.uoink_client import (
    UoinkClient,
    UoinkContractError,
    UoinkUnavailable,
    validate_envelope,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "uoink-corpus-v1.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


class FixtureHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, format, *args):  # noqa: A002
        return

    def _send(self, payload: dict, status: int = 200):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        type(self).requests.append({
            "method": "GET",
            "path": self.path,
            "token": self.headers.get("X-Uoink-Token"),
        })
        if self.path.startswith("/api/corpus/v1/search"):
            return self._send(FIXTURE["search"])
        if self.path == "/api/corpus/v1/items/video-contract":
            return self._send(FIXTURE["get"])
        if self.path == "/api/corpus/v1/items/missing":
            return self._send(FIXTURE["missing"], 404)
        if self.path == "/api/corpus/v1/taste":
            return self._send(FIXTURE["taste"])
        self._send({"ok": False, "error": "unexpected"}, 404)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append({
            "method": "POST",
            "path": self.path,
            "token": self.headers.get("X-Uoink-Token"),
            "body": body,
        })
        if self.path == "/api/corpus/v1/assemble":
            return self._send(FIXTURE["assemble"])
        self._send({"ok": False, "error": "unexpected"}, 404)


@pytest.fixture
def uoink_server():
    FixtureHandler.requests = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(httpd.server_address[1])
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_black_box_search_get_taste_and_assembly(uoink_server):
    client = UoinkClient(
        f"http://127.0.0.1:{uoink_server}", "fixture-token")

    search = client.search(q="saved hour", limit=10)
    detail = client.get("video-contract")
    taste = client.taste()
    assembly = client.assemble(AssemblyQuery(
        format="talking_head",
        topic="Local AI",
        hook_target="curiosity_gap",
        n_examples=5,
    ))

    assert search["page"]["state"] == "matches"
    assert search["items"][0]["id"] == "video-contract"
    assert detail["content"]["available"] is True
    assert taste["anchors"]["best"][0]["id"] == "video-contract"
    assert assembly["assembled"][0]["video_id"] == "video-contract"
    assert FixtureHandler.requests[-1] == {
        "method": "POST",
        "path": "/api/corpus/v1/assemble",
        "token": "fixture-token",
        "body": {
            "format": "talking_head",
            "topic": "Local AI",
            "hook_target": "curiosity_gap",
            "your_channel": None,
            "n_examples": 5,
        },
    }
    assert all(
        request["token"] == "fixture-token"
        for request in FixtureHandler.requests)


def test_item_becomes_portable_writer_snapshot(uoink_server):
    client = UoinkClient(
        f"http://127.0.0.1:{uoink_server}", "fixture-token")
    snapshot = client.attach_source("video-contract")

    assert snapshot.provider == "uoink"
    assert snapshot.provider_ref == "uoink://item/video-contract"
    assert snapshot.title == "The saved hour"
    assert snapshot.creator == "Fixture Creator"
    assert snapshot.credit_required is True
    assert "Fixture Creator" in snapshot.credit_line
    assert "local workflow" in snapshot.excerpt
    assert "path" not in snapshot.to_dict()

    # The snapshot remains sufficient after the optional peer stops.
    serialized = snapshot.to_json()
    assert "uoink://item/video-contract" in serialized
    assert "The saved hour" in serialized


def test_contract_failure_is_data_not_shape_guessing(uoink_server):
    client = UoinkClient(
        f"http://127.0.0.1:{uoink_server}", "fixture-token")
    with pytest.raises(UoinkContractError) as raised:
        client.get("missing")
    assert raised.value.code == "not_found"
    assert raised.value.status == 404
    assert raised.value.retryable is False


def test_strict_envelope_rejects_drift():
    drifted = copy.deepcopy(FIXTURE["get"])
    drifted["data"]["item"]["corpus_path"] = "must not cross"
    with pytest.raises(UoinkContractError) as raised:
        validate_envelope("get", drifted)
    assert raised.value.code == "contract_mismatch"
    assert "corpus_path" in raised.value.message

    wrong_version = copy.deepcopy(FIXTURE["search"])
    wrong_version["version"] = 2
    with pytest.raises(UoinkContractError, match="version"):
        validate_envelope("search", wrong_version)


def test_absent_uoink_fails_calmly():
    client = UoinkClient(
        "http://127.0.0.1:1", "fixture-token", timeout=0.1)
    with pytest.raises(UoinkUnavailable) as raised:
        client.search(limit=10)
    assert "Uoink is unavailable" in str(raised.value)


def test_fixture_is_pinned_to_cm12_merge():
    assert FIXTURE["_upstream"] == {
        "repository": "ryanbiddy/uoink",
        "commit": "1895899d3eb51a70d6ec0f75f03f5bdef43c5ee6",
        "fixture": "tests/fixtures/corpus_contract_v1/provider.json",
        "fixture_sha256": (
            "8578D4D3258F4B552664019781AAC2052794A40087CF941B07F723605CEADED5"
        ),
        "contract": "uoink.corpus.read",
        "version": 1,
    }
