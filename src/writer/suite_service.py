"""Writer-owned suite discovery, health, and runtime-lease contracts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SERVICE_ID = "writer"
SERVICE_NAME = "Writer"
DEFAULT_PORT = 5181
HEALTH_PATH = "/api/suite/v1/health"
MANIFEST_PATH = "/.well-known/suite-service.json"
CAPABILITIES = (
    "writer.api/1",
    "writer.shot-list/1",
)
UI = {
    "home": "/",
    "routes": {
        "editor": "/",
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _base_url(host: str, port: int) -> str:
    value = str(host or "").strip()
    if value not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("suite service address must be loopback")
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("suite service port is invalid")
    rendered = f"[{value}]" if ":" in value else value
    return f"http://{rendered}:{port}"


def service_manifest(service_version: str) -> dict:
    return {
        "ok": True,
        "contract": "ryan.suite.service",
        "version": 1,
        "service": {
            "id": SERVICE_ID,
            "name": SERVICE_NAME,
            "service_version": service_version,
            "api_version": 1,
            "resident": True,
            "default_port": DEFAULT_PORT,
            "health": {
                "contract": "ryan.suite.health",
                "version": 1,
                "href": HEALTH_PATH,
            },
            "capabilities": list(CAPABILITIES),
            "ui": {
                "home": UI["home"],
                "routes": dict(UI["routes"]),
            },
            "mcp": {
                "name": SERVICE_ID,
                "transport": "stdio",
            },
        },
    }


def health_payload(service_version: str, *, database_ok: bool) -> dict:
    checks = [
        {"id": "core", "required": True, "status": "ready"},
        {
            "id": "database",
            "required": True,
            "status": "ready" if database_ok else "failed",
        },
    ]
    ok = database_ok
    return {
        "ok": ok,
        "contract": "ryan.suite.health",
        "version": 1,
        "service_id": SERVICE_ID,
        "service_version": service_version,
        "state": "ready" if ok else "needs_attention",
        "checks": checks,
    }


def runtime_registry_dir(
    *,
    platform_name: str | None = None,
    environ: dict[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    platform_name = platform_name or sys.platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if platform_name == "win32":
        local = environ.get("LOCALAPPDATA")
        base = Path(local) if local else home / "AppData" / "Local"
        return base / "RyanSuite" / "services.d"
    if platform_name == "darwin":
        return home / "Library" / "Application Support" / "RyanSuite" / "services.d"
    state = environ.get("XDG_STATE_HOME")
    base = Path(state) if state else home / ".local" / "state"
    return base / "ryan-suite" / "services.d"


def runtime_lease(
    service_version: str,
    *,
    host: str,
    port: int,
    pid: int,
    started_at: str,
) -> dict:
    base_url = _base_url(host, port)
    return {
        "contract": "ryan.suite.runtime-lease",
        "version": 1,
        "service_id": SERVICE_ID,
        "service_version": service_version,
        "api_version": 1,
        "base_url": base_url,
        "health_url": f"{base_url}{HEALTH_PATH}",
        "manifest_url": f"{base_url}{MANIFEST_PATH}",
        "capabilities": list(CAPABILITIES),
        "ui": {
            "home": UI["home"],
            "routes": dict(UI["routes"]),
        },
        "pid": int(pid),
        "started_at": started_at,
    }


def write_runtime_lease(
    registry_dir: Path | None = None,
    *,
    service_version: str,
    host: str,
    port: int,
    pid: int,
    started_at: str,
) -> Path:
    registry = (
        runtime_registry_dir() if registry_dir is None else Path(registry_dir)
    )
    registry.mkdir(parents=True, exist_ok=True)
    destination = registry / f"{SERVICE_ID}.json"
    encoded = (
        json.dumps(
            runtime_lease(
                service_version,
                host=host,
                port=port,
                pid=pid,
                started_at=started_at,
            ),
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    temporary: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{SERVICE_ID}-",
            suffix=".tmp",
            dir=str(registry),
        )
        temporary = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            os.replace(temporary, destination)
            temporary = None
            try:
                os.chmod(destination, 0o600)
            except OSError:
                pass
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def remove_runtime_lease(
    lease_path: Path,
    *,
    pid: int,
    started_at: str,
) -> bool:
    path = Path(lease_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    if (
        not isinstance(payload, dict)
        or payload.get("service_id") != SERVICE_ID
        or payload.get("pid") != int(pid)
        or payload.get("started_at") != started_at
    ):
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True
