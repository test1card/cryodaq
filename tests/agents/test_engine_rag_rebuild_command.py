"""The live engine command seam never dispatches RAG index mutation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.engine import EngineCommandContext, _handle_gui_command


def _context() -> EngineCommandContext:
    safety_manager = MagicMock()
    safety_manager.get_status.return_value = {"state": "ready"}
    sink_registry = MagicMock()
    sink_registry.dispatch = AsyncMock()
    return EngineCommandContext(
        safety_manager=safety_manager,
        event_logger=MagicMock(),
        sink_registry=sink_registry,
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


@pytest.mark.parametrize("action", ["rag.rebuild_index", "rag.rebuild_status"])
async def test_live_engine_rag_rebuild_commands_never_dispatch(
    action: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_index = AsyncMock(return_value={"indexed": 1})
    monkeypatch.setattr("cryodaq.agents.rag.indexer.build_index", build_index)
    context = _context()
    context.mutation_capability_token = "current-token-1234"
    forbidden_target = tmp_path / "live-index-must-not-exist"
    command = {"cmd": action, "target": str(forbidden_target)}
    if action == "rag.rebuild_index":
        command.update(
            {
                "protocol_major": 1,
                "mutation_capability": "cryodaq_mutation_v1",
                "capability_token": "current-token-1234",
            }
        )

    result = await _handle_gui_command(
        command,
        context=context,
    )

    assert result["ok"] is False
    assert result.get("available") is not True
    assert result.get("state") not in {"running", "complete"}
    if action == "rag.rebuild_index":
        assert result["error_code"] == "assistant_read_only"
        assert result["delivery_state"] == "not_dispatched"
        assert result["commit_state"] == "not_committed"
    build_index.assert_not_awaited()
    context.sink_registry.dispatch.assert_not_awaited()
    assert not forbidden_target.exists()
