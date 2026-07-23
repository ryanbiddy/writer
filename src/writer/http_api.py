"""Writer's authenticated loopback HTTP API and standalone editor."""

from __future__ import annotations

import hmac
import json
import logging
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any

from writer import __version__
from writer.mcp_server import WriterTools
from writer.storage import WriterStore
from writer import suite_service
from writer.uoink_client import UoinkClient

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5181
MAX_BODY_BYTES = 2 * 1024 * 1024
CONTRACT = "writer.api"
VERSION = 1
ALLOWED_HOST_NAMES = frozenset({
    DEFAULT_HOST,
    "localhost",
    "127.0.0.1",
    "::1",
    "[::1]",
})
LOG = logging.getLogger(__name__)


def _success(**data: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "contract": CONTRACT,
        "version": VERSION,
        "data": data,
    }


def _failure(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "contract": CONTRACT,
        "version": VERSION,
        "error": {"code": code, "message": message},
    }


class WriterHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
            self, address, handler, *,
            store: WriterStore, token: str):
        self.store = store
        self.writer_token = token
        super().__init__(address, handler)

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            self.store.close()


class WriterHandler(BaseHTTPRequestHandler):
    server: WriterHTTPServer
    tools: WriterTools

    def log_message(self, format, *args):  # noqa: A002
        return

    def _headers(
            self, status: int, content_type: str,
            length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; "
            "img-src 'self' data:; frame-ancestors 'none'",
        )
        self.end_headers()

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(
            payload, ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def _html(self) -> None:
        try:
            text = files("writer").joinpath(
                "_data", "ui", "index.html"
            ).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            self._json(
                500, _failure("ui_unavailable", "Writer UI is unavailable"))
            return
        raw = text.encode("utf-8")
        self._headers(200, "text/html; charset=utf-8", len(raw))
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        supplied = str(self.headers.get("X-Writer-Token") or "")
        expected = self.server.writer_token
        return bool(supplied) and hmac.compare_digest(supplied, expected)

    def _host_allowed(self) -> bool:
        """Reject DNS-rebinding requests before any Writer route runs."""
        host = self.headers.get("Host")
        if host is None:
            return True
        host = host.strip().lower()
        if host.startswith("["):
            name, _, port = host.partition("]")
            name += "]"
            port = port.lstrip(":")
        elif host.count(":") == 1:
            name, _, port = host.partition(":")
        else:
            name, port = host, ""
        if name not in ALLOWED_HOST_NAMES:
            return False
        if port:
            try:
                bound_port = self.server.server_address[1]
            except (AttributeError, IndexError, TypeError):
                bound_port = DEFAULT_PORT
            if port != str(bound_port):
                return False
        return True

    def _reject_bad_host(self) -> bool:
        if self._host_allowed():
            return False
        LOG.warning(
            "rejected %s %s with non-loopback Host %r",
            self.command,
            self.path.split("?", 1)[0],
            self.headers.get("Host"),
        )
        self._json(
            403,
            _failure(
                "forbidden_host",
                "Request Host must be loopback",
            ),
        )
        return True

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._json(
            401,
            _failure(
                "unauthorized",
                "A valid local Writer credential is required",
            ),
        )
        return False

    def _body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY_BYTES:
            self._json(
                413, _failure("body_too_large", "Request body is too large"))
            return None
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(
                400, _failure("invalid_json", "Request body must be JSON"))
            return None
        if not isinstance(value, dict):
            self._json(
                400, _failure("invalid_body", "Request body must be an object"))
            return None
        return value

    def _tool_result(self, result: dict[str, Any]) -> None:
        if result.get("ok"):
            data = {key: value for key, value in result.items()
                    if key != "ok"}
            self._json(200, _success(**data))
            return
        message = str(result.get("error") or "Request failed")
        status = 404 if "not found" in message.casefold() else 400
        self._json(status, _failure("request_failed", message))

    def _dispatch(self, function, *args, **kwargs) -> None:
        try:
            result = function(*args, **kwargs)
        except (TypeError, ValueError) as exc:
            self._json(
                400, _failure("invalid_request", str(exc)))
            return
        self._tool_result(result)

    def _query_limit(self, query: dict[str, list[str]]) -> int | None:
        raw = (query.get("limit") or ["100"])[0]
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            limit = 0
        if not 1 <= limit <= 500:
            self._json(
                400,
                _failure(
                    "invalid_request",
                    "limit must be an integer between 1 and 500",
                ),
            )
            return None
        return limit

    def _query_flag(
            self, query: dict[str, list[str]], name: str) -> bool | None:
        raw = (query.get(name) or ["0"])[0]
        if raw not in {"0", "1"}:
            self._json(
                400,
                _failure(
                    "invalid_request",
                    f"{name} must be 0 or 1",
                ),
            )
            return None
        return raw == "1"

    def do_OPTIONS(self):  # noqa: N802
        if self._reject_bad_host():
            return
        self._headers(204, "text/plain; charset=utf-8", 0)

    def do_GET(self):  # noqa: N802
        if self._reject_bad_host():
            return
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/":
            self._html()
            return
        if path == "/ping":
            self._json(200, {
                "ok": True,
                "service": "writer",
                "version": VERSION,
                "status": "ready",
            })
            return
        if path == "/manifest":
            self._json(200, {
                "ok": True,
                "service": {
                    "id": "writer",
                    "name": "Writer",
                    "default_port": DEFAULT_PORT,
                    "api_contract": CONTRACT,
                    "api_version": VERSION,
                    "mcp_server": "writer",
                    "standalone": True,
                },
            })
            return
        if path == suite_service.MANIFEST_PATH:
            self._json(
                200,
                suite_service.service_manifest(__version__),
            )
            return
        if path == suite_service.HEALTH_PATH:
            self._json(
                200,
                suite_service.health_payload(
                    __version__,
                    database_ok=self.server.store.database_ready(),
                ),
            )
            return
        if not path.startswith("/api/writer/v1") or not self._require_auth():
            if not path.startswith("/api/writer/v1"):
                self._json(
                    404, _failure("not_found", "Route not found"))
            return
        query = urllib.parse.parse_qs(parsed.query)
        if path == "/api/writer/v1/drafts":
            limit = self._query_limit(query)
            if limit is None:
                return
            self._json(200, _success(drafts=[
                draft.to_dict()
                for draft in self.server.store.list_drafts(limit=limit)
            ]))
            return
        match = re.fullmatch(
            r"/api/writer/v1/drafts/(\d+)", path)
        if match:
            self._dispatch(
                self.tools.get_draft, int(match.group(1)))
            return
        if path == "/api/writer/v1/pieces":
            limit = self._query_limit(query)
            if limit is None:
                return
            self._dispatch(
                self.tools.list_pieces,
                kind=(query.get("kind") or [""])[0],
                limit=limit,
            )
            return
        match = re.fullmatch(
            r"/api/writer/v1/pieces/(\d+)", path)
        if match:
            piece = self.server.store.get_piece(int(match.group(1)))
            if piece is None:
                self._json(
                    404, _failure("not_found", "Piece not found"))
            else:
                self._json(200, _success(piece=piece.to_dict()))
            return
        if path == "/api/writer/v1/scripts":
            limit = self._query_limit(query)
            if limit is None:
                return
            self._json(200, _success(scripts=[
                script.to_dict()
                for script in self.server.store.list_scripts(limit=limit)
            ]))
            return
        match = re.fullmatch(
            r"/api/writer/v1/scripts/(\d+)", path)
        if match:
            script = self.server.store.get_script(int(match.group(1)))
            if script is None:
                self._json(
                    404, _failure("not_found", "Script not found"))
            else:
                self._json(200, _success(script=script.to_dict()))
            return
        if path == "/api/writer/v1/voice-samples":
            active_only = self._query_flag(query, "active_only")
            if active_only is None:
                return
            self._dispatch(
                self.tools.list_voice_samples, active_only)
            return
        if path == "/api/writer/v1/status":
            self._dispatch(self.tools.writer_status)
            return
        self._json(404, _failure("not_found", "Route not found"))

    def do_POST(self):  # noqa: N802
        if self._reject_bad_host():
            return
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        if not path.startswith("/api/writer/v1") or not self._require_auth():
            if not path.startswith("/api/writer/v1"):
                self._json(
                    404, _failure("not_found", "Route not found"))
            return
        body = self._body()
        if body is None:
            return
        if path == "/api/writer/v1/drafts":
            self._dispatch(self.tools.save_draft, body)
            return
        if path == "/api/writer/v1/prepare":
            self._dispatch(self.tools.prepare_draft, **body)
            return
        if path == "/api/writer/v1/pieces":
            self._dispatch(self.tools.save_piece, body)
            return
        if path == "/api/writer/v1/composition/validate":
            self._dispatch(
                self.tools.validate_composition, **body)
            return
        if path == "/api/writer/v1/scripts/prepare":
            self._dispatch(self.tools.prepare_script, **body)
            return
        if path == "/api/writer/v1/scripts":
            self._dispatch(self.tools.save_script, body)
            return
        match = re.fullmatch(
            r"/api/writer/v1/scripts/(\d+)/critique", path)
        if match:
            self._dispatch(
                self.tools.critique_script,
                int(match.group(1)), **body)
            return
        match = re.fullmatch(
            r"/api/writer/v1/scripts/(\d+)/revise", path)
        if match:
            self._dispatch(
                self.tools.revise_script,
                int(match.group(1)), **body)
            return
        match = re.fullmatch(
            r"/api/writer/v1/scripts/(\d+)/derive-shots", path)
        if match:
            self._dispatch(
                self.tools.derive_shot_list, int(match.group(1)))
            return
        match = re.fullmatch(
            r"/api/writer/v1/scripts/(\d+)/export", path)
        if match:
            self._dispatch(
                self.tools.export_shot_list,
                int(match.group(1)), **body)
            return
        if path == "/api/writer/v1/voice-samples":
            self._dispatch(self.tools.add_voice_sample, body)
            return
        if path == "/api/writer/v1/voice/scan":
            self._dispatch(
                self.tools.scan_voice,
                str(body.get("text") or ""))
            return
        if path == "/api/writer/v1/sources/uoink":
            item_id = str(body.get("item_id") or "")
            self._dispatch(
                self.tools.attach_uoink_source, item_id)
            return
        self._json(404, _failure("not_found", "Route not found"))

    def do_DELETE(self):  # noqa: N802
        if self._reject_bad_host():
            return
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        if not self._require_auth():
            return
        match = re.fullmatch(
            r"/api/writer/v1/voice-samples/(\d+)", path)
        if match:
            self._dispatch(
                self.tools.remove_voice_sample, int(match.group(1)))
            return
        self._json(404, _failure("not_found", "Route not found"))


def create_server(
        *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
        token: str, database: str | Path | None = None,
        uoink: UoinkClient | None = None) -> WriterHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Writer HTTP must bind to a loopback host")
    if not str(token or "").strip():
        raise ValueError("Writer local credential is required")
    store = WriterStore.open(database)
    tools = WriterTools(store, uoink=uoink)
    tools.engagement.deliver_pending()

    class BoundWriterHandler(WriterHandler):
        pass

    BoundWriterHandler.tools = tools
    return WriterHTTPServer(
        (host, int(port)),
        BoundWriterHandler,
        store=store,
        token=str(token),
    )
