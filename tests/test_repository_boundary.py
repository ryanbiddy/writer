from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "writer"
FORBIDDEN_FOREIGN_IMPORTS = {
    "uoink",
    "yoink",
    "corpus_contract",
    "corpus_provider",
    "index",
    "memory_layer",
    "server",
    "uoink_mcp_tools",
    "workspaces",
    "writing_studio",
}
FORBIDDEN_FOREIGN_STORAGE_MARKERS = {
    " from yoinks",
    " join yoinks",
    "uoink.db",
    "index.db",
    "sidecar_path",
}


def test_core_is_stdlib_only_and_never_imports_uoink_modules():
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
                if name in FORBIDDEN_FOREIGN_IMPORTS:
                    violations.append(
                        f"{path.relative_to(ROOT)} imports {name}")
    assert violations == []


def test_package_contains_no_foreign_storage_access():
    violations = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                value = node.value.casefold()
                for marker in FORBIDDEN_FOREIGN_STORAGE_MARKERS:
                    if marker in value:
                        violations.append(
                            f"{path.relative_to(ROOT)} contains {marker!r}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "sqlite3"
                and node.func.attr == "connect"
                and path.name != "storage.py"
            ):
                violations.append(
                    f"{path.relative_to(ROOT)} opens SQLite outside storage")
    assert violations == []
