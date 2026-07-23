from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_distinguishes_public_source_from_unreleased_package() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(readme.split())

    assert "repository is private" not in readme
    assert "source repository is public" in normalized
    assert "package has not been released or distributed" in normalized
