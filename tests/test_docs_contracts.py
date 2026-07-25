from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_names_public_prerelease_without_claiming_pypi() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "repository is private" not in readme
    assert "source repository is public" in normalized
    assert "package has not been released or distributed" not in normalized
    assert "public v0.1.0.dev0 pre-release" in normalized
    assert (
        "https://github.com/ryanbiddy/writer/releases/tag/v0.1.0.dev0"
        in readme
    )
    assert "package is not on PyPI" in normalized
    assert (
        'python -m pip install '
        '".\\ryan_writer-0.1.0.dev0-py3-none-any.whl[mcp]"'
        in normalized
    )
