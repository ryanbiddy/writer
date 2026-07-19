from __future__ import annotations

from writer import cli
from writer.auth import ensure_token


def test_help_and_version(capsys):
    assert cli.main(["--help"]) == 0
    assert "writer serve" in capsys.readouterr().out
    assert cli.main(["--version"]) == 0
    assert "0.1.0" in capsys.readouterr().out


def test_private_token_is_stable(tmp_path):
    path = tmp_path / "writer.token"
    first = ensure_token(path)
    second = ensure_token(path)
    assert first == second
    assert len(first) >= 32
    assert path.read_text(encoding="utf-8").strip() == first
