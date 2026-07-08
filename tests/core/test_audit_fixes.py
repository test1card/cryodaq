"""Regression tests for audit-found bugs (BUG-1 through BUG-6)."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading

# ---------------------------------------------------------------------------
# BUG-1: Safety state machine race — request_run rejected during _fault()
# ---------------------------------------------------------------------------


async def test_request_run_rejected_during_fault() -> None:
    """request_run() must see FAULT_LATCHED even when called during _fault() await."""
    from cryodaq.core.safety_broker import SafetyBroker
    from cryodaq.core.safety_manager import SafetyManager, SafetyState
    from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B

    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)

    # Start smua
    result = await sm.request_run(0.5, 40.0, 1.0, channel="smua")
    assert result["ok"]
    assert sm.state == SafetyState.RUNNING

    # Patch emergency_off to yield control (simulates slow I/O)
    original_emergency_off = k.emergency_off
    fault_entered = asyncio.Event()
    proceed = asyncio.Event()

    async def slow_emergency_off(channel=None):
        fault_entered.set()
        await proceed.wait()  # yield point — event loop runs other tasks
        return await original_emergency_off(channel)

    k.emergency_off = slow_emergency_off

    # Start _fault as a task
    fault_task = asyncio.create_task(sm._fault("test fault"))

    # Wait until _fault has started (entered emergency_off await)
    await fault_entered.wait()

    # NOW try to start smub — should be rejected because state is FAULT_LATCHED
    result = await sm.request_run(0.3, 20.0, 0.5, channel="smub")
    assert not result["ok"], "request_run must be rejected during _fault()"
    assert "FAULT" in result.get("error", "")

    # Let _fault complete
    proceed.set()
    await fault_task

    assert sm.state == SafetyState.FAULT_LATCHED
    assert len(sm._active_sources) == 0

    await k.disconnect()


async def test_fault_sets_state_before_emergency_off() -> None:
    """_fault() must set FAULT_LATCHED before any await."""
    from cryodaq.core.safety_broker import SafetyBroker
    from cryodaq.core.safety_manager import SafetyManager, SafetyState
    from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B

    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)

    await sm.request_run(0.5, 40.0, 1.0, channel="smua")

    state_during_eoff = None
    original_emergency_off = k.emergency_off

    async def check_state_off(channel=None):
        nonlocal state_during_eoff
        state_during_eoff = sm.state
        return await original_emergency_off(channel)

    k.emergency_off = check_state_off

    await sm._fault("test")

    # State must have been FAULT_LATCHED BEFORE emergency_off ran
    assert state_during_eoff == SafetyState.FAULT_LATCHED


# ---------------------------------------------------------------------------
# BUG-2: SQLite executor shutdown order
# ---------------------------------------------------------------------------


async def test_sqlite_stop_after_write(tmp_path, monkeypatch) -> None:
    """stop() after write_immediate must not lose data."""
    import cryodaq.storage.sqlite_writer as _sw_mod

    # The WAL-version guard fires on first SQLiteWriter() in the process.
    # Force one clean pass with the bypass env var so subsequent tests in this
    # session also skip the guard (global _SQLITE_VERSION_CHECKED stays True).
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")
    _sw_mod._SQLITE_VERSION_CHECKED = False

    from cryodaq.storage.sqlite_writer import SQLiteWriter

    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="test",
        channel="T1",
        value=4.2,
        unit="K",
    )
    await writer.write_immediate([reading])
    await writer.stop()

    # Verify data persists
    import glob

    db_files = glob.glob(str(tmp_path / "data_*.db"))
    assert len(db_files) >= 1
    conn = sqlite3.connect(db_files[0])
    count = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    conn.close()
    assert count == 1


async def test_sqlite_stop_twice_no_crash(tmp_path) -> None:
    """stop() called twice must not crash."""
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.stop()
    await writer.stop()  # second call — should not crash


# ---------------------------------------------------------------------------
# BUG-3: Phase detector state reset
# ---------------------------------------------------------------------------


async def test_phase_detector_reset_between_experiments() -> None:
    """After warmup → reset → room temp readings → 'preparation' not 'teardown'."""
    from plugins.phase_detector import PhaseDetector

    d = PhaseDetector()
    d.configure(
        {
            "temperature_channel": "T7",
            "target_T_K": 4.2,
            "rate_window_s": 60,
            "room_temp_K": 280,
        }
    )

    # Exp1: warmup
    warmup_temps = [4.2 + i * 1.0 for i in range(100)]
    warmup_readings = [
        Reading(
            timestamp=datetime.fromtimestamp(1000 + i * 3.0, tz=UTC),
            instrument_id="test",
            channel="T7",
            value=t,
            unit="K",
        )
        for i, t in enumerate(warmup_temps)
    ]
    await d.process(warmup_readings)
    assert d._warmup_started is True

    # Reset (simulates new experiment)
    d.reset()
    assert d._warmup_started is False
    assert d._last_phase == "unknown"

    # Exp2: room temp → should be "preparation"
    room_readings = [
        Reading(
            timestamp=datetime.fromtimestamp(5000 + i * 3.0, tz=UTC),
            instrument_id="test",
            channel="T7",
            value=295.0,
            unit="K",
        )
        for i in range(100)
    ]
    metrics = await d.process(room_readings)
    phase = None
    for m in metrics:
        if m.metric == "detected_phase":
            phase = m.metadata.get("phase_name")
    assert phase == "preparation", f"Expected 'preparation', got '{phase}'"


async def test_phase_detector_configure_resets_state() -> None:
    """configure() calls reset(), clearing stale state."""
    from plugins.phase_detector import PhaseDetector

    d = PhaseDetector()
    d.configure({"temperature_channel": "T7"})
    d._warmup_started = True
    d._last_phase = "warmup"

    # Re-configure
    d.configure({"temperature_channel": "T7"})
    assert d._warmup_started is False
    assert d._last_phase == "unknown"


# ---------------------------------------------------------------------------
# BUG-4: SQLite writer — non-finite value filtering vs. state-carrying persist
# ---------------------------------------------------------------------------


async def test_sqlite_ok_nonfinite_filtered(tmp_path) -> None:
    """Non-finite values with status OK (default) are filtered; NaN always filtered."""
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    now = datetime.now(UTC)
    readings = [
        Reading(timestamp=now, instrument_id="test", channel="T1", value=4.2, unit="K"),
        # inf/nan with default status=OK → must be filtered
        Reading(timestamp=now, instrument_id="test", channel="T2", value=float("inf"), unit="K"),
        Reading(timestamp=now, instrument_id="test", channel="T3", value=float("nan"), unit="K"),
        Reading(timestamp=now, instrument_id="test", channel="T5", value=5.0, unit="K"),
    ]
    await writer.write_immediate(readings)
    await writer.stop()

    import glob

    db_files = glob.glob(str(tmp_path / "data_*.db"))
    conn = sqlite3.connect(db_files[0])
    channels = [r[0] for r in conn.execute("SELECT channel FROM readings").fetchall()]
    conn.close()

    assert "T1" in channels
    assert "T5" in channels
    assert "T2" not in channels, "inf with status=OK must be filtered"
    assert "T3" not in channels, "nan must always be filtered"


async def test_sqlite_overrange_inf_persists(tmp_path) -> None:
    """OVERRANGE +inf persists as sentinel + status (NaN-doctrine P2-2)."""
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    now = datetime.now(UTC)
    readings = [
        Reading(
            timestamp=now,
            instrument_id="test",
            channel="T_OVR",
            value=float("inf"),
            unit="K",
            status=ChannelStatus.OVERRANGE,
        ),
    ]
    await writer.write_immediate(readings)
    await writer.stop()

    import glob

    db_files = glob.glob(str(tmp_path / "data_*.db"))
    conn = sqlite3.connect(db_files[0])
    rows = conn.execute("SELECT channel, value, status FROM readings").fetchall()
    conn.close()

    assert len(rows) == 1, f"OVERRANGE +inf must be persisted, got rows={rows}"
    assert rows[0][0] == "T_OVR"
    assert rows[0][2] == ChannelStatus.OVERRANGE.value
    import math

    from cryodaq.storage.sentinel import SENTINEL, decode

    assert rows[0][1] == SENTINEL, (
        f"Persisted value must be the sentinel, got {rows[0][1]}"
    )
    assert math.isnan(decode(rows[0][1], rows[0][2]))


async def test_sqlite_underrange_neg_inf_persists(tmp_path) -> None:
    """UNDERRANGE -inf persists as sentinel + status (NaN-doctrine P2-2)."""
    from cryodaq.storage.sqlite_writer import SQLiteWriter

    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()

    now = datetime.now(UTC)
    readings = [
        Reading(
            timestamp=now,
            instrument_id="test",
            channel="T_UNR",
            value=float("-inf"),
            unit="K",
            status=ChannelStatus.UNDERRANGE,
        ),
    ]
    await writer.write_immediate(readings)
    await writer.stop()

    import glob

    db_files = glob.glob(str(tmp_path / "data_*.db"))
    conn = sqlite3.connect(db_files[0])
    rows = conn.execute("SELECT channel, value, status FROM readings").fetchall()
    conn.close()

    assert len(rows) == 1, f"UNDERRANGE -inf must be persisted, got rows={rows}"
    assert rows[0][0] == "T_UNR"
    assert rows[0][2] == ChannelStatus.UNDERRANGE.value
    import math

    from cryodaq.storage.sentinel import SENTINEL, decode

    assert rows[0][1] == SENTINEL, (
        f"Persisted value must be the sentinel, got {rows[0][1]}"
    )
    assert math.isnan(decode(rows[0][1], rows[0][2]))


# ---------------------------------------------------------------------------
# BUG-5: Cooldown estimator unbounded deque
# ---------------------------------------------------------------------------


def test_cooldown_estimator_buffer_has_maxlen() -> None:
    """Buffer deque must have maxlen to prevent OOM on clock skew."""
    from plugins.cooldown_estimator import CooldownEstimator

    est = CooldownEstimator()
    est.configure({"target_channel": "T7", "target_T": 4.2, "fit_window_s": 600})
    assert est._buffer.maxlen is not None
    assert est._buffer.maxlen >= 6000  # at least 10 Hz × 600s


# ---------------------------------------------------------------------------
# BUG-6: GPIB resource leak on clear() failure
# ---------------------------------------------------------------------------


def test_gpib_resource_closed_on_clear_failure() -> None:
    """If res.clear() raises, the opened VISA resource must be closed."""
    from cryodaq.drivers.transport.gpib import GPIBTransport

    transport = GPIBTransport(mock=False)
    transport._resource_str = "GPIB0::12::INSTR"
    transport._bus_prefix = "GPIB0"

    mock_res = MagicMock()
    mock_res.clear.side_effect = Exception("IFC not supported")

    mock_rm = MagicMock()
    mock_rm.open_resource.return_value = mock_res

    with patch.object(GPIBTransport, "_get_rm", return_value=mock_rm):
        with pytest.raises(Exception, match="IFC not supported"):
            transport._blocking_connect()

    # Resource must have been closed despite clear() failure
    mock_res.close.assert_called_once()
    # _resource must still be None (not assigned)
    assert transport._resource is None


# ---------------------------------------------------------------------------
# HI-2 / ME-15: NaN readings must not poison rolling analytics estimators
# ---------------------------------------------------------------------------


def _feed(est_push, reading: Reading) -> bool:
    """Replicate the engine feed-loop gate: usable ⇒ forwarded, else dropped."""
    if reading.is_usable():
        est_push(reading.channel, reading.timestamp.timestamp(), reading.value)
        return True
    return False


def test_nan_poisons_unguarded_rate_estimator() -> None:
    """Characterizes HI-2: one raw NaN blinds get_rate for the whole window."""
    from cryodaq.core.rate_estimator import RateEstimator

    est = RateEstimator(window_s=120.0, min_points=5)
    for i in range(5):
        est.push("T1", float(i), 300.0 - i)
    est.push("T1", 5.0, float("nan"))  # SENSOR_ERROR reading
    for i in range(6, 11):
        est.push("T1", float(i), 300.0 - i)

    assert est.get_rate("T1") is None


def test_finite_error_status_reading_never_reaches_rate_estimator() -> None:
    """Doctrine: a FINITE value carrying an error status is NOT usable, so the
    boundary gate must drop it before the rate estimator sees it.

    This is the case a pure float-finiteness guard (old _push_if_finite) let
    through — status is now the discriminator, not the value.
    """
    from cryodaq.core.rate_estimator import RateEstimator

    est = RateEstimator(window_s=120.0, min_points=3)
    # A flapping sensor can report a plausible finite number with SENSOR_ERROR.
    bad = Reading.now("T1", 999.0, "K", status=ChannelStatus.SENSOR_ERROR)
    assert _feed(est.push, bad) is False
    assert est.buffer_size("T1") == 0


def test_usable_readings_feed_rate_estimator_nan_dropped() -> None:
    """Fed through the doctrine gate, usable readings accumulate and a
    mid-stream non-finite (NaN, error status) reading is dropped, so the
    estimator still yields the correct rate afterward."""
    from cryodaq.core.rate_estimator import RateEstimator

    est = RateEstimator(window_s=120.0, min_points=5)
    for i in range(5):
        assert _feed(est.push, Reading.now("T1", 300.0 - i, "K")) is True
    # SENSOR_ERROR / TIMEOUT reading arrives as NaN
    dropped = Reading.now("T1", float("nan"), "K", status=ChannelStatus.SENSOR_ERROR)
    assert _feed(est.push, dropped) is False
    for i in range(6, 11):
        assert _feed(est.push, Reading.now("T1", 300.0 - i, "K")) is True

    # timestamps are wall-clock (Reading.now); rate is finite and computed
    assert est.get_rate("T1") is not None


def test_vacuum_trend_push_rejects_nonfinite_independently() -> None:
    """ME-15: VacuumTrendPredictor.push keeps its own fail-closed finite guard
    (status-less float API), so a NaN never poisons the buffer even if a caller
    bypasses the Reading boundary. Its P <= 0 log-domain guard also stays."""
    import math

    from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor

    vt = VacuumTrendPredictor(config={})
    vt.push(0.0, 1e-3)
    vt.push(1.0, float("nan"))  # dropped by fail-closed finite guard
    vt.push(2.0, -5.0)  # dropped by log-domain P <= 0 guard
    vt.push(3.0, 9e-4)

    assert len(vt._buffer) == 2
    assert all(math.isfinite(log_p) for _, log_p in vt._buffer)


def test_engine_feed_sites_gate_on_is_usable() -> None:
    """All three estimator feed loops in _run_engine gate on the doctrine
    predicate; the old float-only _push_if_finite helper is gone."""
    import inspect
    import re

    from cryodaq import engine

    assert not hasattr(engine, "_push_if_finite")

    src = re.sub(r"\s+", "", inspect.getsource(engine._run_engine))
    assert "_alarm_v2_rate.push(" in src
    assert "sensor_diag.push(" in src
    assert "vacuum_trend.push(" in src
    # Every feed loop is guarded by the doctrine predicate; no _push_if_finite.
    assert "_push_if_finite" not in src
    assert "ifreading.is_usable():" in src
