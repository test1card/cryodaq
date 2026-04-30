"""Tests for F30 Live Query Agent — service adapters (Phase A)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.assistant.query.adapters.alarm_adapter import AlarmAdapter
from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot
from cryodaq.agents.assistant.query.adapters.composite_adapter import CompositeAdapter
from cryodaq.agents.assistant.query.adapters.cooldown_adapter import CooldownAdapter
from cryodaq.agents.assistant.query.adapters.experiment_adapter import ExperimentAdapter
from cryodaq.agents.assistant.query.adapters.sqlite_adapter import SQLiteAdapter
from cryodaq.agents.assistant.query.adapters.vacuum_adapter import VacuumAdapter
from cryodaq.agents.assistant.query.schemas import (
    AlarmStatusResult,
    CompositeStatus,
    CooldownETA,
    VacuumETA,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reading(channel: str, value: float, unit: str = "K") -> MagicMock:
    r = MagicMock()
    r.channel = channel
    r.value = value
    r.unit = unit
    r.timestamp = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    return r


def _make_broker(readings: list | None = None) -> MagicMock:
    broker = MagicMock()
    queue: asyncio.Queue = asyncio.Queue()
    broker.subscribe = AsyncMock(return_value=queue)
    broker.unsubscribe = AsyncMock()
    broker.publish = AsyncMock()
    broker._queue = queue
    if readings:
        for r in readings:
            queue.put_nowait(r)
    return broker


# ---------------------------------------------------------------------------
# BrokerSnapshot
# ---------------------------------------------------------------------------


async def test_broker_snapshot_latest_per_channel() -> None:
    """After consuming a reading, latest() returns the value."""
    r = _make_reading("T_cold", 12.5)
    broker = _make_broker(readings=[r])
    snap = BrokerSnapshot(broker)
    await snap.start()
    await asyncio.sleep(0.05)  # let consume loop run

    result = await snap.latest("T_cold")
    assert result is not None
    assert result.value == 12.5

    await snap.stop()


async def test_broker_snapshot_handles_no_data() -> None:
    """latest() returns None for an unseen channel."""
    broker = _make_broker()
    snap = BrokerSnapshot(broker)
    await snap.start()
    await asyncio.sleep(0.02)

    result = await snap.latest("T_unknown")
    assert result is None

    await snap.stop()


async def test_broker_snapshot_latest_all_returns_all_channels() -> None:
    """latest_all() returns a dict with all consumed channels."""
    readings = [
        _make_reading("T_cold", 10.0),
        _make_reading("T_warm", 80.0),
    ]
    broker = _make_broker(readings=readings)
    snap = BrokerSnapshot(broker)
    await snap.start()
    await asyncio.sleep(0.05)

    all_ch = await snap.latest_all()
    assert "T_cold" in all_ch
    assert "T_warm" in all_ch

    await snap.stop()


# ---------------------------------------------------------------------------
# CooldownAdapter
# ---------------------------------------------------------------------------


async def test_cooldown_adapter_returns_none_when_inactive() -> None:
    """Returns None when CooldownService.last_prediction() is None."""
    service = MagicMock()
    service.last_prediction.return_value = None
    adapter = CooldownAdapter(service)
    result = await adapter.eta()
    assert result is None


async def test_cooldown_adapter_parses_prediction() -> None:
    """Correctly wraps a last_prediction dict into CooldownETA."""
    service = MagicMock()
    service.last_prediction.return_value = {
        "t_remaining_hours": 5.0,
        "t_remaining_ci68": (4.0, 6.5),
        "progress": 0.65,
        "phase": "COOLING",
        "n_references": 12,
        "cooldown_active": True,
        "T_cold": 50.0,
        "T_warm": 120.0,
    }
    adapter = CooldownAdapter(service)
    result = await adapter.eta()
    assert isinstance(result, CooldownETA)
    assert result.t_remaining_hours == 5.0
    assert result.t_remaining_low_68 == 4.0
    assert result.t_remaining_high_68 == 6.5
    assert result.progress == pytest.approx(0.65)
    assert result.phase == "COOLING"
    assert result.cooldown_active is True
    assert result.T_cold == 50.0


async def test_cooldown_adapter_returns_none_when_service_is_none() -> None:
    adapter = CooldownAdapter(None)
    assert await adapter.eta() is None


# ---------------------------------------------------------------------------
# VacuumAdapter
# ---------------------------------------------------------------------------


async def test_vacuum_adapter_target_format() -> None:
    """VacuumAdapter matches eta_targets by value proximity."""
    pred = MagicMock()
    pred.eta_targets = {"1.00e-06": 3600.0}
    pred.trend = "falling"
    pred.confidence = 0.92

    predictor = MagicMock()
    predictor.get_prediction.return_value = pred

    adapter = VacuumAdapter(predictor)
    result = await adapter.eta_to_target(1e-6)
    assert isinstance(result, VacuumETA)
    assert result.trend == "falling"
    assert result.confidence == pytest.approx(0.92)
    assert result.target_mbar == 1e-6


async def test_vacuum_adapter_returns_none_when_predictor_is_none() -> None:
    adapter = VacuumAdapter(None)
    assert await adapter.eta_to_target(1e-6) is None


async def test_vacuum_adapter_returns_none_when_no_prediction() -> None:
    predictor = MagicMock()
    predictor.get_prediction.return_value = None
    adapter = VacuumAdapter(predictor)
    assert await adapter.eta_to_target(1e-6) is None


# ---------------------------------------------------------------------------
# SQLiteAdapter
# ---------------------------------------------------------------------------


async def test_sqlite_adapter_range_stats_window() -> None:
    """Correctly computes min/max/mean/std from read_readings_history."""
    now = datetime.now(UTC).timestamp()
    readings_data = {
        "T_cold": [
            (now - 3500, 10.0),
            (now - 3000, 11.0),
            (now - 2000, 12.0),
            (now - 1000, 13.0),
            (now - 100, 14.0),
        ]
    }
    reader = MagicMock()
    reader.read_readings_history = AsyncMock(return_value=readings_data)

    adapter = SQLiteAdapter(reader)
    result = await adapter.range_stats("T_cold", window_minutes=60)

    assert result is not None
    assert result.channel == "T_cold"
    assert result.n_samples == 5
    assert result.min_value == 10.0
    assert result.max_value == 14.0
    assert result.mean_value == pytest.approx(12.0)
    assert result.std_value > 0


async def test_sqlite_adapter_returns_none_for_empty_channel() -> None:
    reader = MagicMock()
    reader.read_readings_history = AsyncMock(return_value={"T_cold": []})
    adapter = SQLiteAdapter(reader)
    result = await adapter.range_stats("T_cold", window_minutes=60)
    assert result is None


# ---------------------------------------------------------------------------
# AlarmAdapter
# ---------------------------------------------------------------------------


async def test_alarm_adapter_active_alarms() -> None:
    """Returns AlarmStatusResult with structured info from engine."""
    engine = MagicMock()
    engine.get_active_alarm_details.return_value = [
        {
            "alarm_id": "T1_high",
            "level": "WARNING",
            "channel_pattern": "T_cold",
            "triggered_at": datetime(2026, 5, 1, 11, 0, 0, tzinfo=UTC),
        }
    ]
    adapter = AlarmAdapter(engine)
    result = await adapter.active()
    assert isinstance(result, AlarmStatusResult)
    assert result.count == 1
    assert result.active[0].alarm_id == "T1_high"
    assert result.active[0].level == "WARNING"


async def test_alarm_adapter_returns_empty_when_no_alarms() -> None:
    engine = MagicMock()
    engine.get_active_alarm_details.return_value = []
    adapter = AlarmAdapter(engine)
    result = await adapter.active()
    assert result.count == 0


async def test_alarm_adapter_returns_empty_when_engine_is_none() -> None:
    adapter = AlarmAdapter(None)
    result = await adapter.active()
    assert result.count == 0


# ---------------------------------------------------------------------------
# ExperimentAdapter
# ---------------------------------------------------------------------------


async def test_experiment_adapter_phase_age() -> None:
    """Returns ExperimentStatus with non-zero experiment_age_s."""
    started = time.time() - 3600.0  # 1 hour ago
    em = MagicMock()
    em.active_experiment_id = "exp-001"
    em.get_current_phase.return_value = "COOL"
    em._get_phase_started_at.return_value = started + 1800  # phase started 30 min ago
    active = MagicMock()
    active.experiment_id = "exp-001"
    active.started_at = started
    active.target_temp = 4.0
    active.sample_id = "S-001"
    em.active_experiment = active

    adapter = ExperimentAdapter(em)
    result = await adapter.status()

    assert result is not None
    assert result.experiment_id == "exp-001"
    assert result.phase == "COOL"
    assert result.experiment_age_s > 3500  # ~3600s
    assert result.target_temp == 4.0
    assert result.sample_id == "S-001"


async def test_experiment_adapter_returns_none_when_no_experiment() -> None:
    em = MagicMock()
    em.active_experiment_id = None
    adapter = ExperimentAdapter(em)
    result = await adapter.status()
    assert result is None


async def test_experiment_adapter_returns_none_when_manager_is_none() -> None:
    adapter = ExperimentAdapter(None)
    assert await adapter.status() is None


# ---------------------------------------------------------------------------
# CompositeAdapter
# ---------------------------------------------------------------------------


async def _make_composite_adapter(
    snapshot_all: dict | Exception = None,
    cd_eta=None,
    vac_eta=None,
    alarm_result=None,
    exp_status=None,
) -> tuple[CompositeAdapter, MagicMock, MagicMock, MagicMock, MagicMock, MagicMock]:
    snap = MagicMock()
    snap.latest_all = AsyncMock(
        return_value={} if snapshot_all is None else snapshot_all
        if not isinstance(snapshot_all, Exception) else None
    )
    if isinstance(snapshot_all, Exception):
        snap.latest_all.side_effect = snapshot_all

    cooldown = MagicMock()
    cooldown.eta = AsyncMock(return_value=cd_eta)

    vacuum = MagicMock()
    vacuum.eta_to_target = AsyncMock(return_value=vac_eta)

    alarms = MagicMock()
    alarm_obj = alarm_result or AlarmStatusResult()
    alarms.active = AsyncMock(return_value=alarm_obj)

    experiment = MagicMock()
    experiment.status = AsyncMock(return_value=exp_status)

    adapter = CompositeAdapter(
        broker_snapshot=snap,
        cooldown=cooldown,
        vacuum=vacuum,
        alarms=alarms,
        experiment=experiment,
    )
    return adapter, snap, cooldown, vacuum, alarms, experiment


async def test_composite_adapter_parallel_fetch() -> None:
    """All adapters are called and results merged into CompositeStatus."""
    snap_data = {"T_cold": _make_reading("T_cold", 15.0)}
    adapter, *_ = await _make_composite_adapter(snapshot_all=snap_data)
    result = await adapter.status()
    assert isinstance(result, CompositeStatus)
    assert result.key_temperatures["T_cold"] == 15.0
    assert result.active_alarms == []


async def test_composite_adapter_handles_partial_failure() -> None:
    """Single adapter exception does not crash composite fetch."""
    adapter, snap, *_ = await _make_composite_adapter()
    snap.latest_all.side_effect = RuntimeError("broker unavailable")

    result = await adapter.status()
    assert isinstance(result, CompositeStatus)
    # Gracefully degraded — snapshot failed but status still returned
    assert result.key_temperatures["T_cold"] is None
