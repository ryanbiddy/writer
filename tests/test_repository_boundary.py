from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "writer"


def test_core_is_stdlib_only_and_never_imports_uoink_modules():
    forbidden = {
        "corpus_contract",
        "corpus_provider",
        "index",
        "memory_layer",
        "server",
        "uoink_mcp_tools",
        "workspaces",
        "writing_studio",
    }
    violations = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0]
                         for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".", 1)[0]]
            for name in names:
                if name in forbidden:
                    violations.append(
                        f"{path.relative_to(ROOT)} imports {name}")
    assert violations == []


def test_contract_contains_no_foreign_sql_or_paths():
    source = (
        PACKAGE / "schemas.py"
    ).read_text(encoding="utf-8").casefold()
    assert "select " not in source
    assert " from yoinks" not in source
    assert "corpus_path" not in source
    assert "sidecar_path" not in source
