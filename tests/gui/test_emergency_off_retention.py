"""Verify ``_emergency_off_shortcut`` retains its QThread workers (CC B.1)."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MAIN_WINDOW = REPO_ROOT / "src" / "cryodaq" / "gui" / "main_window.py"


def test_emergency_off_retains_workers():
    """Workers must be parented OR stored in ``self._emergency_workers``."""
    src = MAIN_WINDOW.read_text(encoding="utf-8")
    tree = ast.parse(src)

    handler = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_emergency_off_shortcut":
            handler = node
            break

    assert handler is not None, "_emergency_off_shortcut not found in main_window.py"

    parented = False
    stored = False

    for sub in ast.walk(handler):
        if isinstance(sub, ast.Call):
            func = sub.func
            name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else None
            )
            if name == "ZmqCommandWorker":
                for kw in sub.keywords:
                    if kw.arg == "parent":
                        parented = True
                        break

        if isinstance(sub, ast.Attribute) and sub.attr == "_emergency_workers":
            stored = True

    assert parented, (
        "ZmqCommandWorker calls in _emergency_off_shortcut must use parent=self "
        "to satisfy Qt parent ownership"
    )
    assert stored, (
        "Workers must be stored in self._emergency_workers as a Python-side "
        "strong reference (defense-in-depth against Qt parent corner cases)"
    )
