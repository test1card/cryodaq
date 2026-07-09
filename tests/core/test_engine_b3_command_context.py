"""Behavior checks for the importable engine command context."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from cryodaq.engine import (
    EngineCommandContext,
    _handle_gui_command,
    _multiline_burst_auto_stop,
)


def _context() -> EngineCommandContext:
    safety_manager = MagicMock()
    safety_manager.get_status.return_value = {"state": "ready"}
    return EngineCommandContext(
        safety_manager=safety_manager,
        event_logger=MagicMock(),
        sink_registry=MagicMock(),
        interlock_engine=MagicMock(),
        leak_rate_estimator=MagicMock(),
        leak_cfg={},
        alarm_v2_state_mgr=MagicMock(),
        alarm_ring=MagicMock(),
        broker=MagicMock(),
        experiment_manager=MagicMock(),
        calibration_acquisition=MagicMock(),
        event_bus=MagicMock(),
        cooldown_alarm=None,
        vacuum_guard=None,
        alarm_dispatch_tasks=set(),
        calibration_store=MagicMock(),
        writer=MagicMock(),
        drivers_by_name={},
        sensor_diag=None,
        vacuum_trend=None,
        alarm_v2_state_tracker=MagicMock(),
        multiline_burst_auto_stop_meta={},
        multiline_burst_auto_stop_tasks={},
    )


async def test_importable_command_handler_reads_context() -> None:
    context = _context()

    result = await _handle_gui_command({"cmd": "safety_status"}, context=context)

    assert result == {"ok": True, "state": "ready"}


async def test_command_context_preserves_late_bound_cooldown_service() -> None:
    context = _context()
    assert await _handle_gui_command({"cmd": "cooldown_eta_get"}, context=context) == {
        "ok": True,
        "prediction": None,
    }

    context.cooldown_service = MagicMock()
    context.cooldown_service.last_prediction.return_value = {"eta_h": 2.5}

    result = await _handle_gui_command({"cmd": "cooldown_eta_get"}, context=context)

    assert result == {"ok": True, "prediction": {"eta_h": 2.5}}


async def test_multiline_auto_stop_uses_explicit_dependencies(tmp_path: Path) -> None:
    driver = MagicMock()
    driver.burst_stop = AsyncMock(return_value=tmp_path / "burst.bin")
    tasks: dict[str, asyncio.Task[None]] = {}
    current = asyncio.current_task()
    assert current is not None
    tasks["ml"] = current

    await _multiline_burst_auto_stop(
        "ml",
        0.0,
        drivers_by_name={"ml": driver},
        experiments_root=tmp_path,
        auto_stop_tasks=tasks,
    )

    driver.burst_stop.assert_awaited_once_with(experiments_root=tmp_path)
    assert "ml" not in tasks
