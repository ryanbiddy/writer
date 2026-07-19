"""S6 conformance tests for Writer's product-owned suite boundaries."""

from __future__ import annotations

import copy
import json
import os
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import regenerate_suite_integration_v1_fixture as regenerate
from writer import __version__, cli, doctor
from writer.http_api import create_server
from writer.mcp_server import WriterTools
from writer.schemas import SourceSnapshot
from writer.storage import WriterStore
from writer.suite_peer import (
    PeerError,
    probe_uoink,
    resolve_uoink_target,
    validate_health,
    validate_runtime_lease,
    validate_service_manifest,
)
from writer import suite_service
from writer.uoink_client import (
    UoinkClient,
    UoinkContractError,
    UoinkUnavailable,
    validate_engagement_response,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "uoink-suite-v1.json"


def _negative(fixture: dict, group: str, name: str) -> dict:
    if group == "runtime_lease":
        payload = copy.deepcopy(fixture["valid"]["runtime_lease"])
    elif group == "service_manifest":
        payload = copy.deepcopy(fixture["valid"]["service_manifest"])
    elif group == "health":
        payload = copy.deepcopy(fixture["valid"]["health"]["ready"])
    else:
        raise AssertionError(f"unknown fixture group: {group}")
    mutation = fixture["negative"][group][name]
    cursor = payload
    parts = mutation["path"].split(".")
    for part in parts[:-1]:
        cursor = cursor[int(part)] if isinstance(cursor, list) else cursor[part]
    final = parts[-1]
    if mutation["operation"] == "set":
        if isinstance(cursor, list):
            cursor[int(final)] = mutation["value"]
        else:
            cursor[final] = mutation["value"]
    else:
        raise AssertionError(f"unknown fixture operation: {mutation}")
    return payload


def _source(item_id: str = "short-123") -> SourceSnapshot:
    return SourceSnapshot(
        provider="uoink",
        provider_ref=f"uoink://item/{item_id}",
        title="Fixture",
        creator="Fixture Creator",
        source_url="https://example.test/short/123",
        credit_line="Source: Fixture by Fixture Creator",
        excerpt="A bounded fixture.",
        attached_at="2026-07-19T12:00:00+00:00",
        credit_required=True,
    ).validate()


def _piece_payload(item_id: str = "short-123") -> dict:
    source = _source(item_id)
    return {
        "kind": "tweet",
        "body": "One measured result.",
        "sources": [source.to_dict()],
        "credit_lines": [source.credit_line],
    }


def test_writer_provider_matches_conformance_fixture():
    expected = json.loads(regenerate.FIXTURE_PATH.read_text(encoding="utf-8"))
    actual = regenerate.generate_fixture()
    assert actual == expected
    assert expected["_fixture"]["contracts"] == [
        "ryan.suite.runtime-lease/1",
        "ryan.suite.service/1",
        "ryan.suite.health/1",
        "writer.shot-list/1",
    ]
    markdown = expected["valid"]["shot_list"]["markdown"]
    headings = [
        "## Hook",
        "## Beats",
        "## Script",
        "## CTA",
        "## Shots",
        "## Credits",
    ]
    assert [markdown.index(heading) for heading in headings] == sorted(
        markdown.index(heading) for heading in headings
    )
    assert "uoink://item/" not in markdown
    assert "Source: Fixture short by Fixture Creator" in markdown


def _request(
    port: int,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    token: bool = True,
) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if token:
        headers["X-Writer-Token"] = "writer-test-token"
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


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
        yield int(server.server_address[1]), server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class UoinkFixtureHandler(BaseHTTPRequestHandler):
    mode = "ready"
    token = "uoink-test-token"
    requests = []

    def log_message(self, format, *args):  # noqa: A002
        return

    def _json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        if self.path == "/.well-known/suite-service.json":
            payload = fixture["valid"]["service_manifest"]
            if type(self).mode == "wrong_service":
                payload = _negative(
                    fixture, "service_manifest", "wrong_service")
            elif type(self).mode == "contract_drift":
                payload = _negative(
                    fixture, "service_manifest", "wrong_version")
            return self._json(200, payload)
        if self.path == "/api/suite/v1/health":
            return self._json(200, fixture["valid"]["health"]["ready"])
        if self.path == "/api/corpus/v1/facets":
            if self.headers.get("X-Uoink-Token") != type(self).token:
                return self._json(403, {
                    "ok": False,
                    "error": "missing or invalid token",
                })
            return self._json(200, {
                "ok": True,
                "contract": "uoink.corpus.read",
                "version": 1,
                "operation": "facets",
                "data": {
                    "facets": {
                        name: []
                        for name in (
                            "platform",
                            "source_type",
                            "author",
                            "channel",
                            "format",
                            "performance_tier",
                            "length_bucket",
                            "topic",
                            "hook_type",
                        )
                    },
                    "date_bounds": {"min": None, "max": None},
                },
            })
        return self._json(404, {"ok": False})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        type(self).requests.append({
            "path": self.path,
            "token": self.headers.get("X-Uoink-Token"),
            "body": body,
        })
        if self.path != "/api/engagement/v1/events":
            return self._json(404, {"ok": False})
        if self.headers.get("X-Uoink-Token") != type(self).token:
            return self._json(403, {
                "ok": False,
                "error": "missing or invalid token",
            })
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        return self._json(200, fixture["valid"]["engagement"]["accepted"])


@pytest.fixture
def uoink_suite_server():
    UoinkFixtureHandler.mode = "ready"
    UoinkFixtureHandler.requests = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), UoinkFixtureHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(httpd.server_address[1])
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_writer_suite_manifest_and_health_are_exact_and_public(
    writer_http, monkeypatch
):
    port, server = writer_http
    status, manifest = _request(
        port,
        "GET",
        "/.well-known/suite-service.json",
        token=False,
    )
    assert status == 200
    assert manifest == suite_service.service_manifest(__version__)
    assert manifest["service"]["capabilities"] == [
        "writer.api/1",
        "writer.shot-list/1",
    ]
    assert set(manifest["service"]) == {
        "id",
        "name",
        "service_version",
        "api_version",
        "resident",
        "default_port",
        "health",
        "capabilities",
        "ui",
        "mcp",
    }

    status, health = _request(
        port,
        "GET",
        "/api/suite/v1/health",
        token=False,
    )
    assert status == 200
    assert health == suite_service.health_payload(
        __version__,
        database_ok=True,
    )
    assert [check["id"] for check in health["checks"]] == [
        "core",
        "database",
    ]
    assert "path" not in json.dumps(health).casefold()

    monkeypatch.setattr(server.store, "database_ready", lambda: False)
    status, health = _request(
        port,
        "GET",
        "/api/suite/v1/health",
        token=False,
    )
    assert status == 200
    assert health["ok"] is False
    assert health["state"] == "needs_attention"
    assert health["checks"][1]["status"] == "failed"


def test_runtime_lease_uses_actual_port_and_owned_cleanup(tmp_path):
    registry = tmp_path / "services.d"
    lease_path = suite_service.write_runtime_lease(
        registry,
        service_version=__version__,
        host="127.0.0.1",
        port=61234,
        pid=1234,
        started_at="2026-07-19T12:00:00Z",
    )
    lease = json.loads(lease_path.read_text(encoding="utf-8"))
    assert lease["base_url"] == "http://127.0.0.1:61234"
    assert lease["health_url"].endswith("/api/suite/v1/health")
    assert set(lease) == {
        "contract",
        "version",
        "service_id",
        "service_version",
        "api_version",
        "base_url",
        "health_url",
        "manifest_url",
        "capabilities",
        "ui",
        "pid",
        "started_at",
    }
    rendered = json.dumps(lease).casefold()
    assert all(
        field not in rendered
        for field in (
            "token",
            "command",
            "arguments",
            "working_directory",
            "database_path",
        )
    )
    assert suite_service.remove_runtime_lease(
        lease_path,
        pid=9999,
        started_at="2026-07-19T12:00:00Z",
    ) is False
    assert suite_service.remove_runtime_lease(
        lease_path,
        pid=1234,
        started_at="2026-07-19T12:00:00Z",
    ) is True


def test_cli_writes_lease_after_bind_and_removes_it(monkeypatch, tmp_path):
    calls = []

    class FakeServer:
        server_address = ("127.0.0.1", 61234)

        def serve_forever(self):
            calls.append("serve")

        def server_close(self):
            calls.append("close")

    monkeypatch.setenv("WRITER_UOINK_TOKEN", "stale-token")
    monkeypatch.setattr(cli, "ensure_token", lambda: "writer-token")
    monkeypatch.setattr(
        cli.UoinkClient,
        "from_env",
        lambda **kwargs: (_ for _ in ()).throw(
            ValueError("invalid optional lease")),
    )
    monkeypatch.setattr(cli, "create_server", lambda **kwargs: FakeServer())
    monkeypatch.setattr(
        suite_service,
        "runtime_registry_dir",
        lambda: tmp_path / "services.d",
    )

    assert cli.main(["serve", "--port", "0"]) == 0
    assert calls == ["serve", "close"]
    assert not (tmp_path / "services.d" / "writer.json").exists()


def test_uoink_fixture_is_pinned_to_landed_provider():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["_upstream"] == {
        "repository": "ryanbiddy/uoink",
        "commit": "3a715c8784c039c7de09e418699cf7d22305e259",
        "fixture": (
            "tests/fixtures/suite_integration_v1/uoink-provider.json"
        ),
        "fixture_sha256": (
            "5701EDFB3C90EC27DB0EB87477266D81B70D22FCE30C9AFD691DD440C865CA84"
        ),
    }


def test_strict_lease_manifest_and_health_validators():
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    valid = fixture["valid"]
    assert validate_runtime_lease(
        valid["runtime_lease"],
        pid_checker=lambda _pid: True,
    )["service_id"] == "uoink"
    assert validate_service_manifest(
        valid["service_manifest"]
    )["service"]["id"] == "uoink"
    assert validate_health(valid["health"]["ready"])["state"] == "ready"

    lease_codes = {
        "unknown_key": "invalid_lease",
        "non_loopback_url": "invalid_lease",
        "token_field": "invalid_lease",
        "path_field": "invalid_lease",
        "command_field": "invalid_lease",
        "wrong_identity": "invalid_lease",
        "dead_pid": "stale_lease",
    }
    for name in fixture["negative"]["runtime_lease"]:
        payload = _negative(fixture, "runtime_lease", name)
        with pytest.raises(PeerError) as raised:
            validate_runtime_lease(
                payload,
                pid_checker=(
                    (lambda _pid: False)
                    if name == "dead_pid"
                    else (lambda _pid: True)
                ),
            )
        assert raised.value.code == lease_codes[name]

    for name in fixture["negative"]["service_manifest"]:
        payload = _negative(fixture, "service_manifest", name)
        with pytest.raises(PeerError):
            validate_service_manifest(payload)
    for name in fixture["negative"]["health"]:
        payload = _negative(fixture, "health", name)
        with pytest.raises(PeerError):
            validate_health(payload)


def test_discovery_order_explicit_then_lease_then_default(
    tmp_path, uoink_suite_server
):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    registry = tmp_path / "services.d"
    registry.mkdir()
    lease = fixture["valid"]["runtime_lease"]
    lease["pid"] = os.getpid()
    lease["base_url"] = f"http://127.0.0.1:{uoink_suite_server}"
    lease["health_url"] = (
        lease["base_url"] + "/api/suite/v1/health"
    )
    lease["manifest_url"] = (
        lease["base_url"] + "/.well-known/suite-service.json"
    )
    (registry / "uoink.json").write_text(
        json.dumps(lease),
        encoding="utf-8",
    )

    target = resolve_uoink_target(
        environ={},
        registry_dir=registry,
        pid_checker=lambda _pid: True,
        check_permissions=False,
    )
    assert target.source == "lease"
    assert target.base_url.endswith(f":{uoink_suite_server}")

    explicit = resolve_uoink_target(
        environ={"WRITER_UOINK_URL": "http://127.0.0.1:61999"},
        registry_dir=registry,
        pid_checker=lambda _pid: True,
        check_permissions=False,
    )
    assert explicit.source == "explicit"
    assert explicit.base_url.endswith(":61999")

    default = resolve_uoink_target(
        environ={},
        registry_dir=tmp_path / "missing",
        pid_checker=lambda _pid: True,
        check_permissions=False,
    )
    assert default.source == "default"
    assert default.base_url == "http://127.0.0.1:5179"


def test_peer_probe_preserves_available_unconfigured_and_errors(
    uoink_suite_server
):
    base = f"http://127.0.0.1:{uoink_suite_server}"
    available = probe_uoink(
        environ={
            "WRITER_UOINK_URL": base,
            "WRITER_UOINK_TOKEN": "uoink-test-token",
        },
        registry_dir=Path("missing"),
        timeout=0.5,
    )
    assert available == {
        "ok": True,
        "contract": "ryan.suite.peer",
        "version": 1,
        "peer": "uoink",
        "state": "available",
        "capabilities": [
            "uoink.corpus.read/1",
            "uoink.engagement.ingest/1",
            "uoink.media.handoff/1",
        ],
    }

    unconfigured = probe_uoink(
        environ={"WRITER_UOINK_URL": base},
        registry_dir=Path("missing"),
        timeout=0.5,
    )
    assert unconfigured["ok"] is True
    assert unconfigured["state"] == "unconfigured"

    auth = probe_uoink(
        environ={
            "WRITER_UOINK_URL": base,
            "WRITER_UOINK_TOKEN": "wrong-token",
        },
        registry_dir=Path("missing"),
        timeout=0.5,
    )
    assert auth["ok"] is False
    assert auth["state"] == "unhealthy"
    assert auth["error"]["code"] == "authentication_failed"

    UoinkFixtureHandler.mode = "wrong_service"
    wrong = probe_uoink(
        environ={"WRITER_UOINK_URL": base},
        registry_dir=Path("missing"),
        timeout=0.5,
    )
    assert wrong["error"]["code"] == "wrong_service"


def test_default_refusal_is_absent_but_explicit_refusal_is_unhealthy(tmp_path):
    absent = probe_uoink(
        environ={},
        registry_dir=tmp_path / "missing",
        default_base_url="http://127.0.0.1:1",
        timeout=0.05,
    )
    assert absent["ok"] is True
    assert absent["state"] == "absent"

    unhealthy = probe_uoink(
        environ={"WRITER_UOINK_URL": "http://127.0.0.1:1"},
        registry_dir=tmp_path / "missing",
        timeout=0.05,
    )
    assert unhealthy["ok"] is False
    assert unhealthy["state"] == "unhealthy"
    assert unhealthy["error"]["code"] in {"unavailable", "timeout"}


def test_client_discovers_valid_runtime_lease(
    tmp_path, monkeypatch, uoink_suite_server
):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    registry = tmp_path / "services.d"
    registry.mkdir()
    lease = fixture["valid"]["runtime_lease"]
    lease["pid"] = os.getpid()
    lease["base_url"] = f"http://127.0.0.1:{uoink_suite_server}"
    lease["health_url"] = lease["base_url"] + "/api/suite/v1/health"
    lease["manifest_url"] = (
        lease["base_url"] + "/.well-known/suite-service.json"
    )
    (registry / "uoink.json").write_text(
        json.dumps(lease),
        encoding="utf-8",
    )
    monkeypatch.delenv("WRITER_UOINK_URL", raising=False)
    monkeypatch.setenv("WRITER_UOINK_TOKEN", "uoink-test-token")
    monkeypatch.setattr(
        suite_service,
        "runtime_registry_dir",
        lambda: registry,
    )
    client = UoinkClient.from_env(timeout=0.5, check_permissions=False)
    assert client.base_url.endswith(f":{uoink_suite_server}")
    assert client.facets()["facets"]["topic"] == []


def test_engagement_client_sends_and_validates_exact_batch(
    uoink_suite_server
):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    request = fixture["valid"]["engagement"]["request"]
    client = UoinkClient(
        f"http://127.0.0.1:{uoink_suite_server}",
        "uoink-test-token",
    )
    assert client.ingest_engagement(request["events"]) == {
        "submitted": 1,
        "accepted": 1,
        "duplicates": 0,
        "rejected": [],
    }
    assert UoinkFixtureHandler.requests[-1] == {
        "path": "/api/engagement/v1/events",
        "token": "uoink-test-token",
        "body": request,
    }

    drifted = copy.deepcopy(fixture["valid"]["engagement"]["accepted"])
    drifted["data"]["unknown"] = True
    with pytest.raises(UoinkContractError) as raised:
        validate_engagement_response(
            drifted,
            submitted=1,
        )
    assert raised.value.code == "contract_mismatch"

    inconsistent = copy.deepcopy(
        fixture["valid"]["engagement"]["accepted"])
    inconsistent["data"]["submitted"] = 2
    with pytest.raises(UoinkContractError, match="inconsistent"):
        validate_engagement_response(
            inconsistent,
            submitted=1,
        )

    wrong_rejection = copy.deepcopy(
        fixture["valid"]["engagement"]["accepted"])
    wrong_rejection["data"] = {
        "submitted": 1,
        "accepted": 0,
        "duplicates": 0,
        "rejected": [{
            "event_id": "writer-not-submitted",
            "code": "not_found",
            "message": "corpus item not found",
            "retryable": False,
        }],
    }
    with pytest.raises(UoinkContractError, match="rejection"):
        validate_engagement_response(
            wrong_rejection,
            submitted=1,
            event_ids={
                "writer-8f1fba1c-96ac-4b69-92f5-932fc2176ed8"
            },
        )


class AcceptingUoink:
    def ingest_engagement(self, events):
        return {
            "submitted": len(events),
            "accepted": len(events),
            "duplicates": 0,
            "rejected": [],
        }


class DownUoink:
    def ingest_engagement(self, events):
        del events
        raise UoinkUnavailable("offline")


class RejectingUoink:
    def ingest_engagement(self, events):
        return {
            "submitted": len(events),
            "accepted": 0,
            "duplicates": 0,
            "rejected": [
                {
                    "event_id": event["event_id"],
                    "code": "not_found",
                    "message": "corpus item not found",
                    "retryable": False,
                }
                for event in events
            ],
        }


@pytest.mark.parametrize(
    "uoink,state,pending,rejected",
    [
        (AcceptingUoink(), "accepted", 0, 0),
        (DownUoink(), "spooled", 1, 0),
        (RejectingUoink(), "rejected", 0, 1),
        (None, "spooled", 1, 0),
    ],
)
def test_saved_piece_reports_and_persists_engagement_outcome(
    tmp_path, uoink, state, pending, rejected
):
    store = WriterStore.open(tmp_path / f"{state}-{pending}.db")
    try:
        tools = WriterTools(store, uoink=uoink)
        result = tools.save_piece(_piece_payload())
        assert result["ok"] is True
        assert result["engagement"]["state"] == state
        assert result["engagement"]["submitted"] == 1
        assert store.engagement_status() == {
            "pending": pending,
            "rejected": rejected,
        }
    finally:
        store.close()


def test_script_and_piece_event_ids_are_stable_and_distinct(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        tools = WriterTools(store, uoink=None)
        piece = tools.save_piece(_piece_payload())
        script = tools.save_script({
            "hook": "A measured hook.",
            "body": "A complete script.",
            "sources": [_source().to_dict()],
        })
        pending = store.pending_engagement(limit=10)
        assert len(pending) == 2
        assert all(
            event["event"]["event_id"].startswith("writer-")
            for event in pending
        )
        assert len({
            event["event"]["event_id"] for event in pending
        }) == 2
        assert piece["engagement"]["state"] == "spooled"
        assert script["engagement"]["state"] == "spooled"
        assert {
            event["event"]["item_ref"] for event in pending
        } == {"uoink://item/short-123"}
    finally:
        store.close()


def test_save_and_outbox_enqueue_are_one_transaction(tmp_path):
    store = WriterStore.open(tmp_path / "writer.db")
    try:
        store.connection.executescript(
            """
            CREATE TRIGGER fail_writer_engagement
            BEFORE INSERT ON engagement_outbox
            BEGIN
              SELECT RAISE(ABORT, 'forced rollback');
            END;
            """
        )
        tools = WriterTools(store, uoink=None)
        result = tools.save_piece(_piece_payload())
        assert result["ok"] is False
        assert store.connection.execute(
            "SELECT COUNT(*) FROM pieces"
        ).fetchone()[0] == 0
        assert store.connection.execute(
            "SELECT COUNT(*) FROM engagement_outbox"
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_http_save_receipt_keeps_secondary_outcome_visible(writer_http):
    port, server = writer_http
    status, payload = _request(
        port,
        "POST",
        "/api/writer/v1/pieces",
        body=_piece_payload(),
    )
    assert status == 200
    assert payload["data"]["engagement"] == {
        "state": "spooled",
        "submitted": 1,
        "accepted": 0,
        "duplicates": 0,
        "spooled": 1,
        "rejected": 0,
    }
    assert server.store.engagement_status()["pending"] == 1


def test_doctor_carries_exact_peer_result(monkeypatch):
    peer = {
        "ok": True,
        "contract": "ryan.suite.peer",
        "version": 1,
        "peer": "uoink",
        "state": "absent",
        "capabilities": [],
    }
    monkeypatch.setattr(doctor, "probe_uoink", lambda **kwargs: peer)
    check = doctor.check_uoink()
    assert check.status == "absent"
    assert check.ok is False
    assert check.result == peer
