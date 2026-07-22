from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "src" / "cryodaq" / "engine.py"
CONFIG = ROOT / "config" / "physical_alarms.yaml"


def test_engine_uses_strict_atomic_physical_alarm_loader() -> None:
    tree = ast.parse(ENGINE.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "cryodaq.core.physical_alarms_config"
        for alias in node.names
    }
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "load_production_physical_alarms_config"
    ]
    permissive_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"load_physical_alarms_config", "load_channel_landmarks"}
    }
    assert "load_production_physical_alarms_config" in imported
    assert len(calls) == 1
    assert permissive_calls == set()

    assignment = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and node.value is calls[0]
            and len(node.targets) == 1
            and isinstance(node.targets[0], (ast.Tuple, ast.List))
        ),
        None,
    )
    assert assignment is not None
    assert [item.id for item in assignment.targets[0].elts if isinstance(item, ast.Name)] == [
        "_cooldown_cfg",
        "_vacuum_cfg",
        "_landmarks",
    ]


def test_landmark_schema_and_aliases_are_exact(tmp_path: Path) -> None:
    module = importlib.import_module("cryodaq.core.physical_alarms_config")
    loader = getattr(module, "load_production_physical_alarms_config")
    error = getattr(module, "PhysicalAlarmsConfigError")
    cooldown, vacuum, landmarks = loader(CONFIG)
    assert cooldown["warm_channel"] == "\u042211"
    assert cooldown["cold_channel"] == "\u042212"
    assert vacuum["reference_temp_channel"] == "\u042212"
    assert set(landmarks) == {"\u042211", "\u042212"}
    assert all(
        isinstance(entry, dict)
        and set(entry) == {"role", "physical", "aliases"}
        and isinstance(entry["aliases"], list)
        and entry["aliases"]
        and len(entry["aliases"]) == len(set(entry["aliases"]))
        for entry in landmarks.values()
    )

    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text(
        "cooldown: {}\ncooldown: {}\nvacuum: {}\nlandmarks: {}\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(error, match="duplicate"):
        loader(duplicate)
    aliased = tmp_path / "alias.yaml"
    aliased.write_text(
        "cooldown: &same {}\nvacuum: *same\nlandmarks: {}\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(error, match="aliases"):
        loader(aliased)
