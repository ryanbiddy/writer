"""Writer-owned local authentication material."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from writer.storage import default_data_dir

TOKEN_ENV = "WRITER_TOKEN"


def token_path() -> Path:
    return default_data_dir() / "writer.token"


def ensure_token(path: str | Path | None = None) -> str:
    configured = str(os.environ.get(TOKEN_ENV) or "").strip()
    if configured:
        return configured
    target = Path(path) if path is not None else token_path()
    if target.is_file():
        value = target.read_text(encoding="utf-8").strip()
        if value:
            return value
    target.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    target.write_text(value + "\n", encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return value
