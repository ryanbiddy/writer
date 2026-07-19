"""C-01 gate: real ``python -P`` stdio handshake and every tool call."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

try:
    import mcp  # noqa: F401

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False

pytestmark = pytest.mark.skipif(
    not HAVE_SDK,
    reason='mcp SDK not installed (pip install "ryan-writer[mcp]")',
)


def test_all_17_tools_roundtrip_over_real_stdio(tmp_path):
    driver = Path(__file__).with_name("mcp_stdio_smoke.py")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-P",
            str(driver),
            "--data-dir",
            str(tmp_path / "writer-data"),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["tool_count"] == 17
    assert len(report["listed_tools"]) == 17
    assert report["called_tools"] == report["listed_tools"]
    assert report["errors"] == []
