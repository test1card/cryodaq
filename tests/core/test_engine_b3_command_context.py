"""Behavior checks for the importable engine command context."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from cryodaq.core.zmq_bridge import (
    PERIODIC_BARRIER_SCHEMA,
    PERIODIC_QUERY_SCHEMA,
    PROTOCOL_VERSION,
    ZMQCommandServer,
)
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


async def test_periodic_barrier_command_is_closed_and_delegates_exact_nonce() -> None:
    context = _context()
    context.zmq_publisher = MagicMock()
    context.zmq_publisher.barrier = AsyncMock(
        return_value={
            "ok": False,
            "schema": PERIODIC_BARRIER_SCHEMA,
            "error_code": "barrier_timeout",
        }
    )
    nonce = "a" * 32

    result = await _handle_gui_command(
        {
            "cmd": "periodic_subscription_barrier",
            "schema": PERIODIC_QUERY_SCHEMA,
            "nonce": nonce,
        },
        context=context,
    )

    assert result["error_code"] == "barrier_timeout"
    context.zmq_publisher.barrier.assert_awaited_once_with(nonce)

    for invalid in (
        {
            "cmd": "periodic_subscription_barrier",
            "schema": PERIODIC_QUERY_SCHEMA,
            "nonce": nonce,
            "extra": True,
        },
        {
            "cmd": "periodic_subscription_barrier",
            "schema": PERIODIC_QUERY_SCHEMA,
            "nonce": True,
        },
        {
            "cmd": "periodic_subscription_barrier",
            "schema": PERIODIC_QUERY_SCHEMA,
            "nonce": "A" * 32,
        },
    ):
        rejected = await _handle_gui_command(invalid, context=context)
        assert rejected == {
            "ok": False,
            "schema": PERIODIC_BARRIER_SCHEMA,
            "error_code": "barrier_invalid",
        }


async def test_periodic_alarm_snapshot_is_minimal_and_wire_envelope_has_proto() -> None:
    context = _context()
    context.alarm_v2_state_mgr.snapshot_active_canonical.return_value = SimpleNamespace(
        state_revision=4,
        state_token="sha256:" + "b" * 64,
        active={
            "alarm": {
                "level": "CRITICAL",
                "triggered_at": 1.0,
                "channels": ["T1"],
                "acknowledged": False,
                "acknowledged_at": None,
            }
        },
    )

    result = await _handle_gui_command(
        {"cmd": "periodic_alarm_snapshot", "schema": PERIODIC_QUERY_SCHEMA},
        context=context,
    )
    wire = json.loads(ZMQCommandServer()._encode_reply(result))

    assert wire == {**result, "proto": PROTOCOL_VERSION}
    assert set(wire) == {
        "ok",
        "proto",
        "schema",
        "state_revision",
        "state_token",
        "active",
    }


async def test_periodic_alarm_snapshot_caps_complete_wire_response_and_echoes_nothing() -> None:
    context = _context()
    hostile = "secret-hostile-text"
    context.alarm_v2_state_mgr.snapshot_active_canonical.return_value = SimpleNamespace(
        state_revision=1,
        state_token="sha256:" + "c" * 64,
        active={
            "alarm": {
                "level": "WARNING",
                "triggered_at": 1.0,
                "channels": [hostile * 4000],
            }
        },
    )

    result = await _handle_gui_command(
        {"cmd": "periodic_alarm_snapshot", "schema": PERIODIC_QUERY_SCHEMA},
        context=context,
    )

    assert result == {
        "ok": False,
        "schema": PERIODIC_QUERY_SCHEMA,
        "error_code": "snapshot_unavailable",
    }
    assert hostile not in json.dumps(result)


async def test_periodic_alarm_snapshot_reuses_compact_finite_wire_envelope() -> None:
    context = _context()
    active = {}
    for alarm_index in range(128):
        alarm_id = f"a{alarm_index:03d}"
        active[alarm_id] = {
            "level": "WARNING",
            "triggered_at": 100.0,
            "channels": [f"{channel_index:02d}-" + "x" * 16 for channel_index in range(16)],
            "acknowledged": False,
            "acknowledged_at": None,
        }
    context.alarm_v2_state_mgr.snapshot_active_canonical.return_value = SimpleNamespace(
        state_revision=0,
        state_token="sha256:" + "0" * 64,
        active=active,
    )

    result = await _handle_gui_command(
        {"cmd": "periodic_alarm_snapshot", "schema": PERIODIC_QUERY_SCHEMA},
        context=context,
    )

    wire = ZMQCommandServer()._encode_reply(result)
    assert result["ok"] is True
    assert len(wire) == 58_672
    assert len(wire) <= 60 * 1024
    assert wire == result.wire
    assert b"NaN" not in wire


async def test_periodic_alarm_snapshot_rejects_unknown_request_fields() -> None:
    context = _context()
    result = await _handle_gui_command(
        {
            "cmd": "periodic_alarm_snapshot",
            "schema": PERIODIC_QUERY_SCHEMA,
            "extra": False,
        },
        context=context,
    )
    assert result == {
        "ok": False,
        "schema": PERIODIC_QUERY_SCHEMA,
        "error_code": "snapshot_unavailable",
    }
