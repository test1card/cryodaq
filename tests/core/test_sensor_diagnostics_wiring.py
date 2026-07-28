"""Production wiring contract for descriptor-aware sensor diagnostics."""

from __future__ import annotations

import ast
from pathlib import Path

_ENGINE_PATH = Path(__file__).resolve().parents[2] / "src" / "cryodaq" / "engine.py"


def test_production_sensor_diagnostics_constructor_receives_live_catalog_snapshot() -> None:
    """The production call must pass a snapshot, not a mock or mutable owner."""
    tree = ast.parse(_ENGINE_PATH.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "SensorDiagnosticsEngine"
    ]

    assert any(
        keyword.arg == "channel_catalog"
        and isinstance(keyword.value, ast.Call)
        and isinstance(keyword.value.func, ast.Attribute)
        and keyword.value.func.attr == "storage_catalog_snapshot"
        and isinstance(keyword.value.func.value, ast.Name)
        and keyword.value.func.value.id == "live_descriptor_catalog"
        for call in calls
        for keyword in call.keywords
    )
