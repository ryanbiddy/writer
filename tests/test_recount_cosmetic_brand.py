"""Keep the Recount candidate label separate from Writer compatibility."""

from __future__ import annotations

import tomllib
from pathlib import Path

from writer import schemas, suite_service
from writer.auth import TOKEN_ENV
from writer.http_api import CONTRACT
from writer.storage import DATA_DIR_ENV


ROOT = Path(__file__).resolve().parents[1]


def test_recount_is_display_only_and_writer_contracts_stay_frozen() -> None:
    project = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    editor = (
        ROOT / "src" / "writer" / "_data" / "ui" / "index.html"
    ).read_text(encoding="utf-8")

    assert readme.startswith("# Recount\n")
    assert "<title>Recount</title>" in editor
    assert "<h1>Recount</h1>" in editor

    assert project["project"]["name"] == "ryan-writer"
    assert project["project"]["scripts"] == {
        "writer": "writer.cli:main"
    }
    assert (ROOT / "src" / "writer").is_dir()
    assert not (ROOT / "src" / "recount").exists()
    assert suite_service.SERVICE_ID == "writer"
    assert suite_service.SERVICE_NAME == "Writer"
    assert suite_service.DEFAULT_PORT == 5181
    assert suite_service.CAPABILITIES == (
        "writer.api/1",
        "writer.shot-list/1",
    )
    assert CONTRACT == "writer.api"
    assert schemas.SHOT_LIST_DOCUMENT_TYPE == "writer.shot-list"
    assert TOKEN_ENV == "WRITER_TOKEN"
    assert DATA_DIR_ENV == "WRITER_DATA_DIR"
    assert "/api/writer/v1" in editor
    assert "X-Writer-Token" in editor
