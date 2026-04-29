"""Tests for F23 (RateEstimator timestamp), F24 (interlock acknowledge ZMQ), F25 (SQLite gate).

F23: SafetyManager._collect_loop must use reading.timestamp.timestamp() not time.monotonic().
F24: InterlockEngine.acknowledge() re-arms TRIPPED interlock; KeyError for unknown name.
F25: _check_sqlite_version() hard-fails on affected versions; CRYODAQ_ALLOW_BROKEN_SQLITE=1 bypass.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

import cryodaq.storage.sqlite_writer as _sw
from cryodaq.core.interlock import InterlockCondition, InterlockEngine, InterlockState
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.drivers.base import Reading

# ---------------------------------------------------------------------------
# F23 — RateEstimator uses measurement timestamp not dequeue time
# ---------------------------------------------------------------------------


def _make_reading(channel: str, value: float, ts: datetime) -> Reading:
    return Reading(
        timestamp=ts,
        instrument_id="LS218",
        channel=channel,
        value=value,
        unit="K",
    )


@pytest.mark.asyncio
async def test_rate_estimator_uses_measurement_timestamp_not_dequeue() -> None:
    """_collect_loop must push reading.timestamp.timestamp() to rate_estimator.

    Under queue backlog, time.monotonic() clusters near dequeue time. Using
    reading.timestamp (actual measurement time) gives correct dT/dt estimates.
    """
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=None, mock=True)

    pushed: list[float] = []
    original_push = mgr._rate_estimator.push

    def capture(channel: str, ts: float, value: float) -> None:
        pushed.append(ts)
        original_push(channel, ts, value)

    mgr._rate_estimator.push = capture  # type: ignore[method-assign]

    # Timestamp clearly in the past (far from current monotonic time)
    fixed_ts = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)
    reading = _make_reading("T1", 100.0, fixed_ts)

    await mgr.start()
    try:
        assert mgr._queue is not None
        await mgr._queue.put(reading)
        await asyncio.sleep(0.05)  # Allow _collect_loop to process
    finally:
        await mgr.stop()

    assert len(pushed) == 1, "Rate estimator push should have been called once"
    expected_ts = fixed_ts.timestamp()
    assert abs(pushed[0] - expected_ts) < 0.001, (
        f"Rate estimator received ts={pushed[0]:.3f}, expected reading.timestamp="
        f"{expected_ts:.3f}. Using dequeue time (time.monotonic()) instead of "
        f"measurement timestamp would give a very different value."
    )


# ---------------------------------------------------------------------------
# F24 — Interlock acknowledge ZMQ command
# ---------------------------------------------------------------------------


def _make_interlock_engine() -> InterlockEngine:
    async def _noop() -> None:
        pass

    return InterlockEngine(broker=None, actions={"emergency_off": _noop})  # type: ignore[arg-type]


def test_interlock_acknowledge_re_arms_tripped_interlock() -> None:
    """acknowledge() transitions TRIPPED → ARMED so interlock resumes monitoring."""
    engine = _make_interlock_engine()
    cond = InterlockCondition(
        name="overheat",
        description="T too high",
        channel_pattern=r"T\d+",
        threshold=300.0,
        comparison=">",
        action="emergency_off",
    )
    engine.add_condition(cond)

    # Manually put interlock into TRIPPED state (simulates a prior trip)
    engine._interlocks["overheat"].state = InterlockState.TRIPPED

    # Operator acknowledges after clearing the condition
    engine.acknowledge("overheat")

    assert engine._interlocks["overheat"].state == InterlockState.ARMED, (
        "acknowledge() should transition TRIPPED → ARMED"
    )


def test_interlock_acknowledge_raises_for_unknown_name() -> None:
    """acknowledge() raises KeyError when interlock name not registered."""
    engine = _make_interlock_engine()
    with pytest.raises(KeyError):
        engine.acknowledge("nonexistent_interlock")


def test_interlock_acknowledge_idempotent_on_already_armed() -> None:
    """acknowledge() on already-ARMED interlock should not raise."""
    engine = _make_interlock_engine()
    cond = InterlockCondition(
        name="test",
        description="test",
        channel_pattern=r"T\d+",
        threshold=300.0,
        comparison=">",
        action="emergency_off",
    )
    engine.add_condition(cond)
    # Already ARMED — should not raise
    engine.acknowledge("test")
    assert engine._interlocks["test"].state == InterlockState.ARMED


# ---------------------------------------------------------------------------
# F25 — SQLite WAL startup gate
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_sqlite_check():
    """Reset the module-level checked flag before each F25 test.

    Teardown sets True (not False) to prevent the gate from firing in
    subsequent tests on machines with affected SQLite (e.g. 3.50.4).
    """
    _sw._SQLITE_VERSION_CHECKED = False
    yield
    _sw._SQLITE_VERSION_CHECKED = True


def test_startup_gates_on_known_broken_sqlite_version() -> None:
    """Hard-fail when SQLite version is in the affected [3.7.0, 3.51.3) range."""
    broken_version = (3, 50, 0)  # Clearly in the affected range
    with patch.object(_sw.sqlite3, "sqlite_version_info", broken_version):
        with pytest.raises(RuntimeError, match="WAL-reset corruption bug"):
            _sw._check_sqlite_version()


def test_env_var_bypass_allows_broken_version(caplog) -> None:
    """CRYODAQ_ALLOW_BROKEN_SQLITE=1 bypasses gate and logs a warning."""
    broken_version = (3, 50, 0)
    with patch.object(_sw.sqlite3, "sqlite_version_info", broken_version):
        with patch.dict("os.environ", {"CRYODAQ_ALLOW_BROKEN_SQLITE": "1"}):
            with caplog.at_level("WARNING", logger="cryodaq.storage.sqlite_writer"):
                _sw._check_sqlite_version()  # Must not raise
    assert "bypassing" in caplog.text.lower() or "bypass" in caplog.text.lower()


def test_safe_sqlite_version_does_not_raise() -> None:
    """No gate triggered when SQLite version is >= 3.51.3."""
    safe_version = (3, 51, 3)
    with patch.object(_sw.sqlite3, "sqlite_version_info", safe_version):
        _sw._check_sqlite_version()  # Must not raise


def test_sqlite_version_check_idempotent() -> None:
    """Second call with same version is a no-op (gate only runs once per process)."""
    broken_version = (3, 50, 0)
    _sw._SQLITE_VERSION_CHECKED = True  # Already checked
    with patch.object(_sw.sqlite3, "sqlite_version_info", broken_version):
        _sw._check_sqlite_version()  # Must not raise — already checked


# ---------------------------------------------------------------------------
# F26 — SQLite WAL gate backport whitelist
# ---------------------------------------------------------------------------


def test_sqlite_3_44_6_backport_safe_passes() -> None:
    """Version (3, 44, 6) is in SQLITE_BACKPORT_SAFE and must not raise."""
    with patch.object(_sw.sqlite3, "sqlite_version_info", (3, 44, 6)):
        _sw._check_sqlite_version()  # Must not raise


def test_sqlite_3_50_7_backport_safe_passes() -> None:
    """Version (3, 50, 7) is in SQLITE_BACKPORT_SAFE and must not raise."""
    with patch.object(_sw.sqlite3, "sqlite_version_info", (3, 50, 7)):
        _sw._check_sqlite_version()  # Must not raise


@pytest.mark.parametrize(
    "version",
    [
        (3, 44, 5),  # one below 3.44.6 — not in whitelist
        (3, 44, 7),  # one above 3.44.6 — backport was single-version only
        (3, 50, 6),  # one below 3.50.7 — not in whitelist
        (3, 50, 8),  # one above 3.50.7 — no backport in 3.50.8..3.51.2
    ],
)
def test_sqlite_adjacent_versions_still_raise(version: tuple[int, int, int]) -> None:
    """Adjacent versions to whitelist entries still raise RuntimeError."""
    with patch.object(_sw.sqlite3, "sqlite_version_info", version):
        with pytest.raises(RuntimeError, match="WAL-reset corruption bug"):
            _sw._check_sqlite_version()
