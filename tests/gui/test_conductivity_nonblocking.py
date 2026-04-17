"""Test: auto-sweep methods must not call blocking send_command."""

from __future__ import annotations

import ast
from pathlib import Path


def test_auto_tick_no_blocking_send_command():
    """_auto_tick, _on_auto_start, _on_auto_stop, _auto_complete must not call blocking send_command."""  # noqa: E501
    src = (
        Path(__file__).parents[2] / "src" / "cryodaq" / "gui" / "widgets" / "conductivity_panel.py"
    )
    source = src.read_text(encoding="utf-8")
    tree = ast.parse(source)

    target_methods = {"_auto_tick", "_on_auto_start", "_on_auto_stop", "_auto_complete"}
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in target_methods:
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        if isinstance(func, ast.Name) and func.id == "send_command":
                            violations.append(
                                f"{node.name}:{child.lineno}: blocking send_command()"
                            )

    assert not violations, (
        "Auto-sweep methods must use _send_auto_cmd, not blocking send_command:\n"
        + "\n".join(violations)
    )
