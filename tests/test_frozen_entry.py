"""Test frozen entry point structure.

These tests verify the Phase 1 CRITICAL fix for ``multiprocessing.freeze_support``
ordering without actually building a PyInstaller bundle. They are pure AST
inspections and run in any environment.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN_MAIN = REPO_ROOT / "src" / "cryodaq" / "_frozen_main.py"
LAUNCHER = REPO_ROOT / "src" / "cryodaq" / "launcher.py"
GUI_APP = REPO_ROOT / "src" / "cryodaq" / "gui" / "app.py"


def _stmt_index(stmts: list[ast.stmt], predicate) -> int | None:
    for idx, stmt in enumerate(stmts):
        if predicate(stmt):
            return idx
    return None


def test_frozen_main_exists():
    assert FROZEN_MAIN.exists(), "src/cryodaq/_frozen_main.py must exist"


def test_freeze_support_called_before_heavy_imports():
    """``freeze_support()`` MUST be called before any cryodaq.*/PySide6 import.

    Inspects every ``main_*`` function in ``_frozen_main.py`` and verifies the
    statement index of ``freeze_support()`` is strictly less than the first
    cryodaq/PySide6 import.
    """
    tree = ast.parse(FROZEN_MAIN.read_text(encoding="utf-8"))

    main_funcs = [
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name.startswith("main_")
    ]
    assert main_funcs, "_frozen_main.py must define main_* functions"

    for func in main_funcs:
        # Find freeze_support() call
        def is_freeze_support(stmt: ast.stmt) -> bool:
            if not isinstance(stmt, ast.Expr):
                return False
            call = stmt.value
            if not isinstance(call, ast.Call):
                return False
            f = call.func
            return isinstance(f, ast.Attribute) and f.attr == "freeze_support"

        freeze_idx = _stmt_index(func.body, is_freeze_support)

        def is_heavy_import(stmt: ast.stmt) -> bool:
            names: list[str] = []
            if isinstance(stmt, ast.ImportFrom) and stmt.module:
                names.append(stmt.module)
            if isinstance(stmt, ast.Import):
                names.extend(a.name for a in stmt.names)
            return any(n.startswith("cryodaq") or n.startswith("PySide6") for n in names)

        heavy_idx = _stmt_index(func.body, is_heavy_import)

        assert freeze_idx is not None, (
            f"{func.name}: missing freeze_support() call"
        )
        if heavy_idx is not None:
            assert freeze_idx < heavy_idx, (
                f"{func.name}: freeze_support() at stmt {freeze_idx} must come "
                f"BEFORE the first heavy import at stmt {heavy_idx}"
            )


def _no_active_freeze_support_calls(path: Path) -> None:
    """Assert that ``freeze_support`` only appears in comments in *path*."""
    src = path.read_text(encoding="utf-8")
    for line_no, line in enumerate(src.splitlines(), start=1):
        stripped = line.strip()
        if "freeze_support" not in line:
            continue
        # Allow comment lines.
        if stripped.startswith("#"):
            continue
        # Allow comment-prefixed NOTE lines that include a literal mention.
        if "NOTE:" in line and "freeze_support" in line and line.lstrip().startswith("#"):
            continue
        pytest.fail(
            f"{path.name}:{line_no} still references freeze_support() in non-comment "
            f"code: {line!r}"
        )


def test_launcher_main_does_not_call_freeze_support():
    """``launcher.main()`` must NOT call ``freeze_support`` — it's too late."""
    _no_active_freeze_support_calls(LAUNCHER)


def test_gui_app_main_does_not_call_freeze_support():
    """Same constraint for ``gui/app.py``."""
    _no_active_freeze_support_calls(GUI_APP)


def test_frozen_main_imports_in_function_body_only():
    """All cryodaq/PySide6 imports in _frozen_main MUST be inside function bodies,
    NOT at module top level — otherwise they'd run before freeze_support()."""
    tree = ast.parse(FROZEN_MAIN.read_text(encoding="utf-8"))

    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            names: list[str] = []
            if isinstance(stmt, ast.ImportFrom) and stmt.module:
                names.append(stmt.module)
            if isinstance(stmt, ast.Import):
                names.extend(a.name for a in stmt.names)
            for name in names:
                assert not name.startswith("cryodaq"), (
                    f"_frozen_main.py: top-level import of {name!r} would defeat "
                    f"freeze_support() ordering"
                )
                assert not name.startswith("PySide6"), (
                    f"_frozen_main.py: top-level import of {name!r} would defeat "
                    f"freeze_support() ordering"
                )
