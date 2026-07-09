"""Structural gates for the engine wiring decomposition."""

from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import cryodaq.engine as engine_mod


def _engine_tree() -> ast.Module:
    path = pathlib.Path(engine_mod.__file__)
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_run_engine_contains_no_nested_defs_or_lambdas() -> None:
    tree = _engine_tree()
    run_engine = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_engine"
    )
    offenders = [
        node
        for node in ast.walk(run_engine)
        if node is not run_engine
        and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda))
    ]
    rendered = [
        f"{type(node).__name__}:{getattr(node, 'name', '<lambda>')}:{node.lineno}"
        for node in offenders
    ]
    assert rendered == [], f"_run_engine still owns nested callables: {rendered}"


def test_engine_wiring_submodules_import_without_engine_reverse_cycle() -> None:
    snippet = (
        "import sys\n"
        "import cryodaq.engine_wiring.runtime_tasks\n"
        "import cryodaq.engine_wiring.supervision\n"
        "assert 'cryodaq.engine' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_helpers_remain_compatibly_importable_from_engine() -> None:
    expected = {
        "_AlarmRingBuffer",
        "_alarm_ring_buffer_loop",
        "_alarm_v2_feed_loop",
        "_format_diag_telegram_messages",
    }
    assert expected <= set(vars(engine_mod))


def test_run_engine_wires_every_extracted_runtime_task() -> None:
    tree = _engine_tree()
    run_engine = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run_engine"
    )
    loaded_names = {
        node.id
        for node in ast.walk(run_engine)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    expected = {
        "alarm_ring_feed",
        "alarm_v2_feed_readings",
        "alarm_v2_tick",
        "assistant_event_relay_loop",
        "cold_rotation_scheduler",
        "cooldown_alarm_tick_loop",
        "leak_rate_feed",
        "sensor_diag_feed",
        "sensor_diag_tick",
        "track_runtime_signals",
        "vacuum_guard_tick_loop",
        "vacuum_trend_feed",
        "vacuum_trend_tick",
    }
    assert expected <= loaded_names
