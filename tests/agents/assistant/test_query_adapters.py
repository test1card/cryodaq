"""Tests for F30 Live Query Agent — service adapters (Phase A)."""

from __future__ import annotations

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
    ActiveAlarmInfo,
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


# ---------------------------------------------------------------------------
# BrokerSnapshot
# ---------------------------------------------------------------------------


async def test_broker_snapshot_latest_per_channel() -> None:
    """After consuming a reading, latest() returns the value.

    B1: BrokerSnapshot now subscribes over ZMQ (tcp://127.0.0.1:5555)
    instead of an in-process DataBroker — these tests feed the reading
    straight into the internal callback instead of going through a fake
    broker queue + .start()/.stop(), which would require a real socket.
    """
    r = _make_reading("T_cold", 12.5)
    snap = BrokerSnapshot()
    await snap._on_reading(r)

    result = await snap.latest("T_cold")
    assert result is not None
    assert result.value == 12.5


async def test_broker_snapshot_handles_no_data() -> None:
    """latest() returns None for an unseen channel."""
    snap = BrokerSnapshot()
    result = await snap.latest("T_unknown")
    assert result is None


async def test_broker_snapshot_latest_all_returns_all_channels() -> None:
    """latest_all() returns a dict with all consumed channels."""
    snap = BrokerSnapshot()
    await snap._on_reading(_make_reading("T_cold", 10.0))
    await snap._on_reading(_make_reading("T_warm", 80.0))

    all_ch = await snap.latest_all()
    assert "T_cold" in all_ch
    assert "T_warm" in all_ch


# ---------------------------------------------------------------------------
# CooldownAdapter
# ---------------------------------------------------------------------------


def _fake_client(reply: dict) -> MagicMock:
    """B1: adapters now call the engine's read-only REP commands over ZMQ
    (via ``EngineQueryClient``) instead of holding a live object reference.
    This builds a minimal stand-in with a mocked ``.call()``."""
    client = MagicMock()
    client.call = AsyncMock(return_value=reply)
    return client


async def test_cooldown_adapter_returns_none_when_inactive() -> None:
    """Returns None when the engine's cooldown_eta_get reports no prediction."""
    adapter = CooldownAdapter(_fake_client({"ok": True, "prediction": None}))
    result = await adapter.eta()
    assert result is None


async def test_cooldown_adapter_parses_prediction() -> None:
    """Correctly wraps a cooldown_eta_get reply into CooldownETA."""
    adapter = CooldownAdapter(
        _fake_client(
            {
                "ok": True,
                "prediction": {
                    "t_remaining_hours": 5.0,
                    "t_remaining_ci68": (4.0, 6.5),
                    "progress": 0.65,
                    "phase": "COOLING",
                    "n_references": 12,
                    "cooldown_active": True,
                    "T_cold": 50.0,
                    "T_warm": 120.0,
                },
            }
        )
    )
    result = await adapter.eta()
    assert isinstance(result, CooldownETA)
    assert result.t_remaining_hours == 5.0
    assert result.t_remaining_low_68 == 4.0
    assert result.t_remaining_high_68 == 6.5
    assert result.progress == pytest.approx(0.65)
    assert result.phase == "COOLING"
    assert result.cooldown_active is True
    assert result.T_cold == 50.0


async def test_cooldown_adapter_returns_none_when_call_fails() -> None:
    adapter = CooldownAdapter(_fake_client({"ok": False, "error": "engine недоступен"}))
    assert await adapter.eta() is None


# ---------------------------------------------------------------------------
# VacuumAdapter
# ---------------------------------------------------------------------------


async def test_vacuum_adapter_target_format() -> None:
    """VacuumAdapter matches eta_targets by value proximity."""
    adapter = VacuumAdapter(
        _fake_client(
            {
                "ok": True,
                "eta_targets": {"1.00e-06": 3600.0},
                "trend": "falling",
                "confidence": 0.92,
            }
        )
    )
    result = await adapter.eta_to_target(1e-6)
    assert isinstance(result, VacuumETA)
    assert result.eta_seconds == pytest.approx(3600.0)
    assert result.target_mbar == 1e-6
    assert result.trend == "falling"
    assert result.confidence == pytest.approx(0.92)


async def test_vacuum_adapter_returns_none_when_call_fails() -> None:
    adapter = VacuumAdapter(_fake_client({"ok": False, "error": "engine недоступен"}))
    assert await adapter.eta_to_target(1e-6) is None


async def test_vacuum_adapter_returns_none_when_no_prediction() -> None:
    adapter = VacuumAdapter(_fake_client({"ok": True, "status": "no_data"}))
    assert await adapter.eta_to_target(1e-6) is None


# ---------------------------------------------------------------------------
# SQLiteAdapter
# ---------------------------------------------------------------------------


async def test_sqlite_adapter_range_stats_window() -> None:
    """Correctly computes min/max/mean/std from readings_history reply."""
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
    adapter = SQLiteAdapter(_fake_client({"ok": True, "data": readings_data}))
    result = await adapter.range_stats("T_cold", window_minutes=60)

    assert result is not None
    assert result.channel == "T_cold"
    assert result.n_samples == 5
    assert result.min_value == 10.0
    assert result.max_value == 14.0
    assert result.mean_value == pytest.approx(12.0)
    assert result.std_value > 0


async def test_sqlite_adapter_returns_none_for_empty_channel() -> None:
    adapter = SQLiteAdapter(_fake_client({"ok": True, "data": {"T_cold": []}}))
    result = await adapter.range_stats("T_cold", window_minutes=60)
    assert result is None


async def test_sqlite_adapter_returns_none_when_call_fails() -> None:
    adapter = SQLiteAdapter(_fake_client({"ok": False, "error": "engine недоступен"}))
    result = await adapter.range_stats("T_cold", window_minutes=60)
    assert result is None


# ---------------------------------------------------------------------------
# AlarmAdapter
# ---------------------------------------------------------------------------


async def test_alarm_adapter_active_alarms() -> None:
    """Returns AlarmStatusResult with structured info from the engine's
    alarm_v2_status REP reply."""
    triggered_at = datetime(2026, 5, 1, 11, 0, 0, tzinfo=UTC).timestamp()
    adapter = AlarmAdapter(
        _fake_client(
            {
                "ok": True,
                "active": {
                    "T1_high": {
                        "level": "WARNING",
                        "message": "T_cold above threshold",
                        "triggered_at": triggered_at,
                        "channels": ["T_cold"],
                        "acknowledged": False,
                        "acknowledged_at": None,
                        "acknowledged_by": None,
                    }
                },
            }
        )
    )
    result = await adapter.active()
    assert isinstance(result, AlarmStatusResult)
    assert result.count == 1
    assert result.active[0].alarm_id == "T1_high"
    assert result.active[0].level == "WARNING"
    assert result.active[0].channels == ["T_cold"]


async def test_alarm_adapter_returns_empty_when_no_alarms() -> None:
    adapter = AlarmAdapter(_fake_client({"ok": True, "active": {}}))
    result = await adapter.active()
    assert result.count == 0


async def test_alarm_adapter_returns_empty_when_call_fails() -> None:
    adapter = AlarmAdapter(_fake_client({"ok": False, "error": "engine недоступен"}))
    result = await adapter.active()
    assert result.count == 0


# ---------------------------------------------------------------------------
# ExperimentAdapter
# ---------------------------------------------------------------------------


async def test_experiment_adapter_active_experiment() -> None:
    """Returns ExperimentStatus built from the engine's experiment_status reply.

    B1: ``target_temp``/``sample_id``/``experiment_age_s``/
    ``experiment_started_human`` are documented dead-attribute parity (see
    experiment_adapter.py module docstring) — always None/0.0 in
    production before this extraction too.
    """
    adapter = ExperimentAdapter(
        _fake_client(
            {
                "ok": True,
                "current_phase": "COOL",
                "phase_started_at": time.time() - 1800,
                "active_experiment": {"experiment_id": "exp-001"},
            }
        )
    )
    result = await adapter.status()

    assert result is not None
    assert result.experiment_id == "exp-001"
    assert result.phase == "COOL"
    assert result.target_temp is None
    assert result.sample_id is None
    assert result.experiment_age_s == 0.0


async def test_experiment_adapter_returns_none_when_no_experiment() -> None:
    adapter = ExperimentAdapter(_fake_client({"ok": True, "active_experiment": None}))
    result = await adapter.status()
    assert result is None


async def test_experiment_adapter_returns_none_when_call_fails() -> None:
    adapter = ExperimentAdapter(_fake_client({"ok": False, "error": "engine недоступен"}))
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
    # CompositeAdapter uses latest_with_labels() — convert Reading mocks to labeled format
    if isinstance(snapshot_all, Exception):
        snap.latest_with_labels = AsyncMock(side_effect=snapshot_all)
    else:
        raw = snapshot_all or {}
        labeled: dict = {}
        for ch, reading in raw.items():
            labeled[ch] = {
                "value": getattr(reading, "value", reading),
                "unit": getattr(reading, "unit", "K"),
                "display_name": ch,
                "timestamp": getattr(reading, "timestamp", datetime.now(UTC)),
            }
        snap.latest_with_labels = AsyncMock(return_value=labeled)
    snap.oldest_age_s = AsyncMock(return_value=None)

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
    sentinel_cd = CooldownETA(
        t_remaining_hours=3.5,
        t_remaining_low_68=3.0,
        t_remaining_high_68=4.0,
        progress=0.45,
        phase="cooldown",
        n_references=12,
        cooldown_active=True,
        T_cold=42.0,
    )
    sentinel_vac = VacuumETA(
        current_mbar=1e-3,
        eta_seconds=3600.0,
        target_mbar=1e-6,
        trend="falling",
        confidence=0.8,
    )
    sentinel_alarm = AlarmStatusResult(
        active=[ActiveAlarmInfo(
            alarm_id="ALM-1",
            level="WARNING",
            channels=["T_cold"],
            triggered_at=None,
        )]
    )
    adapter, snap, cooldown, vacuum, alarms, experiment = await _make_composite_adapter(
        snapshot_all=snap_data,
        cd_eta=sentinel_cd,
        vac_eta=sentinel_vac,
        alarm_result=sentinel_alarm,
    )
    result = await adapter.status()
    assert isinstance(result, CompositeStatus)
    # Temperature merged from snapshot
    assert result.key_temperatures["T_cold"] == 15.0
    # Cooldown ETA passed through — a bug dropping it would fail here
    assert result.cooldown_eta is sentinel_cd
    # Vacuum ETA passed through — a bug dropping it would fail here
    assert result.vacuum_eta is sentinel_vac
    # Alarm merged — a bug dropping alarms would fail here
    assert len(result.active_alarms) == 1
    assert result.active_alarms[0].alarm_id == "ALM-1"
    # All sub-adapters must have been awaited in parallel
    snap.latest_with_labels.assert_awaited_once()
    cooldown.eta.assert_awaited_once()
    vacuum.eta_to_target.assert_awaited_once()
    alarms.active.assert_awaited_once()
    experiment.status.assert_awaited_once()


async def test_composite_adapter_handles_partial_failure() -> None:
    """Single adapter exception does not crash composite fetch."""
    adapter, snap, *_ = await _make_composite_adapter()
    snap.latest_with_labels.side_effect = RuntimeError("broker unavailable")

    result = await adapter.status()
    assert isinstance(result, CompositeStatus)
    # Gracefully degraded — snapshot failed, key_temperatures is empty
    assert result.key_temperatures == {}
    assert result.snapshot_empty is True
