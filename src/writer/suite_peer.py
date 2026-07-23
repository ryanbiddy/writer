"""Strict discovery and health probing for Writer's optional Uoink peer."""

from __future__ import annotations

import ctypes
import json
import os
import re
import socket
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from writer import suite_service

DEFAULT_UOINK_URL = "http://127.0.0.1:5179"
UOINK_URL_ENV = "WRITER_UOINK_URL"
UOINK_TOKEN_ENV = "WRITER_UOINK_TOKEN"
UOINK_CAPABILITIES = (
    "uoink.corpus.read/1",
    "uoink.engagement.ingest/1",
    "uoink.media.handoff/1",
)
_LEASE_KEYS = {
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
_SERVICE_KEYS = {
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
_CHECK_KEYS = {"id", "required", "status"}
_UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)


class PeerError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class _TransportError(PeerError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        absence_eligible: bool = False,
    ):
        super().__init__(code, message, retryable=retryable)
        self.absence_eligible = absence_eligible


@dataclass(frozen=True)
class UoinkTarget:
    base_url: str
    source: str


def _error(
    code: str,
    message: str,
    *,
    retryable: bool = False,
) -> PeerError:
    return PeerError(code, message, retryable=retryable)


def _exact(
    value: Any,
    expected: set[str],
    label: str,
    *,
    code: str,
) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise _error(code, f"{label} does not match version 1")
    return value


def _base_url(value: Any, *, code: str) -> str:
    if not isinstance(value, str):
        raise _error(code, "Uoink URL must be an HTTP loopback address")
    try:
        parsed = urllib.parse.urlparse(value.strip())
        port = parsed.port
    except ValueError as error:
        raise _error(
            code,
            "Uoink URL must be an HTTP loopback address",
        ) from error
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or port is None
        or not 1 <= port <= 65535
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise _error(code, "Uoink URL must be an HTTP loopback address")
    return value.strip().rstrip("/")


def _ui(value: Any, *, code: str) -> dict:
    value = _exact(value, {"home", "routes"}, "ui", code=code)
    if not _is_service_ui_path(value["home"]):
        raise _error(code, "ui.home must be a relative service path")
    routes = value["routes"]
    if not isinstance(routes, dict) or any(
        not isinstance(name, str)
        or not _is_service_ui_path(path)
        for name, path in routes.items()
    ):
        raise _error(code, "ui.routes must contain relative service paths")
    return value


def _is_service_ui_path(value: Any) -> bool:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
    ):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return False
    return not parsed.scheme and not parsed.netloc


def _capabilities(value: Any, *, code: str) -> list[str]:
    if (
        not isinstance(value, list)
        or value != sorted(set(value))
        or tuple(value) != UOINK_CAPABILITIES
    ):
        raise _error(code, "Uoink capabilities do not match version 1")
    return value


def process_is_live(pid: int) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1:
        return False
    if sys.platform == "win32":
        process_query = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query,
            False,
            pid,
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not ctypes.windll.kernel32.GetExitCodeProcess(
                handle,
                ctypes.byref(exit_code),
            ):
                return False
            return exit_code.value == 259
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def validate_runtime_lease(
    payload: Any,
    *,
    pid_checker: Callable[[int], bool] = process_is_live,
) -> dict:
    code = "invalid_lease"
    payload = _exact(payload, _LEASE_KEYS, "runtime lease", code=code)
    if (
        payload["contract"] != "ryan.suite.runtime-lease"
        or payload["version"] != 1
        or payload["service_id"] != "uoink"
        or payload["api_version"] != 1
        or not isinstance(payload["service_version"], str)
        or not payload["service_version"]
    ):
        raise _error(code, "runtime lease identity does not match Uoink v1")
    base = _base_url(payload["base_url"], code=code)
    if payload["health_url"] != f"{base}/api/suite/v1/health":
        raise _error(code, "runtime lease health URL is invalid")
    if (
        payload["manifest_url"]
        != f"{base}/.well-known/suite-service.json"
    ):
        raise _error(code, "runtime lease manifest URL is invalid")
    _capabilities(payload["capabilities"], code=code)
    _ui(payload["ui"], code=code)
    pid = payload["pid"]
    if not isinstance(pid, int) or isinstance(pid, bool) or pid < 1:
        raise _error(code, "runtime lease PID is invalid")
    started_at = payload["started_at"]
    if not isinstance(started_at, str) or not _UTC_TIMESTAMP.fullmatch(
        started_at
    ):
        raise _error(code, "runtime lease timestamp is invalid")
    try:
        datetime.fromisoformat(started_at[:-1] + "+00:00")
    except ValueError as error:
        raise _error(code, "runtime lease timestamp is invalid") from error
    if not pid_checker(pid):
        raise _error(
            "stale_lease",
            "Uoink runtime lease process is no longer running",
            retryable=True,
        )
    return payload


def validate_service_manifest(payload: Any) -> dict:
    code = "contract_mismatch"
    payload = _exact(
        payload,
        {"ok", "contract", "version", "service"},
        "service manifest",
        code=code,
    )
    if (
        payload["ok"] is not True
        or payload["contract"] != "ryan.suite.service"
        or payload["version"] != 1
    ):
        raise _error(code, "service manifest contract does not match version 1")
    service = _exact(
        payload["service"],
        _SERVICE_KEYS,
        "service manifest service",
        code=code,
    )
    if service["id"] != "uoink":
        raise _error(
            "wrong_service",
            "configured endpoint is not Uoink",
        )
    if (
        service["name"] != "Uoink"
        or not isinstance(service["service_version"], str)
        or not service["service_version"]
        or service["api_version"] != 1
        or service["resident"] is not True
        or service["default_port"] != 5179
    ):
        raise _error(code, "Uoink service identity does not match version 1")
    health = _exact(
        service["health"],
        {"contract", "version", "href"},
        "service health descriptor",
        code=code,
    )
    if health != {
        "contract": "ryan.suite.health",
        "version": 1,
        "href": "/api/suite/v1/health",
    }:
        raise _error(code, "Uoink health descriptor does not match version 1")
    _capabilities(service["capabilities"], code=code)
    _ui(service["ui"], code=code)
    mcp = _exact(
        service["mcp"],
        {"name", "transport"},
        "service mcp descriptor",
        code=code,
    )
    if mcp != {"name": "uoink", "transport": "stdio"}:
        raise _error(code, "Uoink MCP identity does not match version 1")
    return payload


def validate_health(payload: Any) -> dict:
    code = "contract_mismatch"
    payload = _exact(
        payload,
        {
            "ok",
            "contract",
            "version",
            "service_id",
            "service_version",
            "state",
            "checks",
        },
        "suite health",
        code=code,
    )
    if (
        payload["contract"] != "ryan.suite.health"
        or payload["version"] != 1
        or payload["service_id"] != "uoink"
        or not isinstance(payload["service_version"], str)
        or not payload["service_version"]
        or payload["state"]
        not in {"ready", "ready_with_limits", "needs_attention"}
        or not isinstance(payload["ok"], bool)
    ):
        raise _error(code, "Uoink health identity does not match version 1")
    checks = payload["checks"]
    if not isinstance(checks, list) or len(checks) != 3:
        raise _error(code, "Uoink health checks do not match version 1")
    expected_ids = ["core", "index", "corpus_paths"]
    statuses = []
    for expected_id, check in zip(expected_ids, checks):
        check = _exact(
            check,
            _CHECK_KEYS,
            "suite health check",
            code=code,
        )
        if (
            check["id"] != expected_id
            or check["required"] is not True
            or check["status"]
            not in {"ready", "busy", "degraded", "failed"}
        ):
            raise _error(code, "Uoink health checks do not match version 1")
        statuses.append(check["status"])
    expected_ok = "failed" not in statuses
    if not expected_ok:
        expected_state = "needs_attention"
    elif any(status in {"busy", "degraded"} for status in statuses):
        expected_state = "ready_with_limits"
    else:
        expected_state = "ready"
    if payload["ok"] is not expected_ok or payload["state"] != expected_state:
        raise _error(code, "Uoink health state is internally inconsistent")
    return payload


def _check_lease_permissions(path: Path) -> None:
    if sys.platform == "win32":
        return
    details = path.stat()
    if hasattr(os, "getuid") and details.st_uid != os.getuid():
        raise _error("invalid_lease", "runtime lease has the wrong owner")
    if stat.S_IMODE(details.st_mode) & 0o077:
        raise _error(
            "invalid_lease",
            "runtime lease permissions are not per-user",
        )


def resolve_uoink_target(
    *,
    environ: dict[str, str] | None = None,
    registry_dir: Path | None = None,
    default_base_url: str = DEFAULT_UOINK_URL,
    pid_checker: Callable[[int], bool] = process_is_live,
    check_permissions: bool = True,
) -> UoinkTarget:
    environ = os.environ if environ is None else environ
    if UOINK_URL_ENV in environ:
        try:
            base = _base_url(
                environ.get(UOINK_URL_ENV),
                code="invalid_configuration",
            )
        except PeerError:
            raise
        return UoinkTarget(base_url=base, source="explicit")
    registry = (
        suite_service.runtime_registry_dir()
        if registry_dir is None
        else Path(registry_dir)
    )
    lease_path = registry / "uoink.json"
    if lease_path.exists():
        try:
            if check_permissions:
                _check_lease_permissions(lease_path)
            payload = json.loads(lease_path.read_text(encoding="utf-8"))
        except PeerError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _error(
                "invalid_lease",
                "Uoink runtime lease cannot be validated",
            ) from error
        lease = validate_runtime_lease(
            payload,
            pid_checker=pid_checker,
        )
        return UoinkTarget(
            base_url=lease["base_url"],
            source="lease",
        )
    return UoinkTarget(
        base_url=_base_url(
            default_base_url,
            code="invalid_configuration",
        ),
        source="default",
    )


def _get_json(url: str, *, timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(response.status)
            content_type = response.headers.get_content_type()
            raw = response.read(256 * 1024 + 1)
    except urllib.error.HTTPError as error:
        raise _TransportError(
            "unavailable",
            f"Uoink suite probe returned HTTP {error.code}",
            retryable=True,
        ) from error
    except (TimeoutError, socket.timeout) as error:
        raise _TransportError(
            "timeout",
            "Uoink suite probe timed out",
            retryable=True,
            absence_eligible=True,
        ) from error
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            code = "timeout"
            message = "Uoink suite probe timed out"
        else:
            code = "unavailable"
            message = "Uoink suite probe could not connect"
        raise _TransportError(
            code,
            message,
            retryable=True,
            absence_eligible=True,
        ) from error
    except OSError as error:
        raise _TransportError(
            "unavailable",
            "Uoink suite probe could not connect",
            retryable=True,
            absence_eligible=True,
        ) from error
    if status != 200 or content_type != "application/json":
        raise _TransportError(
            "unavailable",
            "Uoink suite probe returned an invalid transport response",
            retryable=True,
        )
    if len(raw) > 256 * 1024:
        raise _TransportError(
            "unavailable",
            "Uoink suite probe exceeded the response limit",
            retryable=True,
        )
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _TransportError(
            "unavailable",
            "Uoink suite probe returned invalid JSON",
            retryable=True,
        ) from error


def _available(capabilities: list[str]) -> dict:
    return {
        "ok": True,
        "contract": "ryan.suite.peer",
        "version": 1,
        "peer": "uoink",
        "state": "available",
        "capabilities": list(capabilities),
    }


def _calm(state: str) -> dict:
    return {
        "ok": True,
        "contract": "ryan.suite.peer",
        "version": 1,
        "peer": "uoink",
        "state": state,
        "capabilities": [],
    }


def _unhealthy(error: PeerError) -> dict:
    return {
        "ok": False,
        "contract": "ryan.suite.peer",
        "version": 1,
        "peer": "uoink",
        "state": "unhealthy",
        "error": {
            "code": error.code,
            "message": error.message,
            "retryable": error.retryable,
        },
    }


def probe_uoink(
    *,
    environ: dict[str, str] | None = None,
    registry_dir: Path | None = None,
    default_base_url: str = DEFAULT_UOINK_URL,
    timeout: float = 1.0,
    check_permissions: bool = True,
) -> dict:
    environ = os.environ if environ is None else environ
    try:
        target = resolve_uoink_target(
            environ=environ,
            registry_dir=registry_dir,
            default_base_url=default_base_url,
            check_permissions=check_permissions,
        )
    except PeerError as error:
        return _unhealthy(error)
    try:
        manifest = validate_service_manifest(
            _get_json(
                target.base_url
                + "/.well-known/suite-service.json",
                timeout=timeout,
            )
        )
        health = validate_health(
            _get_json(
                target.base_url + "/api/suite/v1/health",
                timeout=timeout,
            )
        )
    except _TransportError as error:
        if target.source == "default" and error.absence_eligible:
            return _calm("absent")
        return _unhealthy(error)
    except PeerError as error:
        return _unhealthy(error)
    if not health["ok"]:
        return _unhealthy(
            _error(
                "peer_unhealthy",
                "Uoink reported that it needs attention",
                retryable=True,
            )
        )
    token = str(environ.get(UOINK_TOKEN_ENV) or "").strip()
    if not token:
        return _calm("unconfigured")
    from writer.uoink_client import (
        UoinkClient,
        UoinkContractError,
        UoinkUnavailable,
    )

    try:
        UoinkClient(
            target.base_url,
            token,
            timeout=timeout,
        ).facets()
    except UoinkContractError as error:
        code = (
            "authentication_failed"
            if error.status in {401, 403}
            or error.code == "authentication_failed"
            else "contract_mismatch"
        )
        return _unhealthy(
            _error(
                code,
                error.message,
                retryable=False,
            )
        )
    except UoinkUnavailable as error:
        return _unhealthy(
            _error(
                getattr(error, "code", "unavailable"),
                str(error),
                retryable=True,
            )
        )
    return _available(manifest["service"]["capabilities"])
