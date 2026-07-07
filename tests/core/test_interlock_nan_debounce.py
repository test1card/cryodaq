"""Tests for P2-5: interlock NaN debounced escalation (NaN-доктрина Phase 2).

Semantics under test:
- Transient non-usable reading (NaN / error-status) on an interlock-protected
  channel → CRITICAL log + alarm-v2 event, NO trip.
- Persistent non-usable (≥min_duration_s AND ≥min_samples consecutive) while
  the safety state is RUNNING → escalate to SafetyManager FAULT_LATCHED.
- Outside RUNNING → log/alarm only, never fault.
- A usable reading resets the debounce window.
- Non-usability is the doctrine predicate (is_usable), not a float check:
  finite value + error status still counts as non-usable.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import pytest

from cryodaq.core.broker import DataBroker
from cryodaq.core.interlock import InterlockCondition, InterlockEngine
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.base import ChannelStatus, Reading

_BASE = datetime(2026, 7, 7, 12, 0, 0, tzinfo=UTC)


class _FakePublisher:
    """Captures publish_diagnostic_alarm calls (alarm-v2 emission surface)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float]] = []

    def publish_diagnostic_alarm(self, channel_id, severity, age_seconds):
        self.calls.append((channel_id, severity, age_seconds))
        return None


async def _noop() -> None:
    return None


def _reading(
    *,
    channel: str = "Т5 Зона нагрева",
    value: float = float("nan"),
    offset_s: float = 0.0,
    status: ChannelStatus = ChannelStatus.SENSOR_ERROR,
    unit: str = "K",
) -> Reading:
    return Reading(
        timestamp=_BASE + timedelta(seconds=offset_s),
        instrument_id="test",
        channel=channel,
        value=value,
        unit=unit,
        status=status,
    )


def _make_engine(
    *,
    publisher=None,
    handler=None,
    min_samples: int = 5,
    min_duration_s: float = 10.0,
) -> InterlockEngine:
    engine = InterlockEngine(
        broker=DataBroker(),
        actions={"emergency_off": _noop},
        alarm_publisher=publisher,
        dead_channel_handler=handler,
    )
    engine.add_condition(
        InterlockCondition(
            name="overheat_zone",
            description="Перегрев зоны нагрева",
            channel_pattern=r"Т5 .*",
            threshold=350.0,
            comparison=">",
            action="emergency_off",
        )
    )
    engine._nonusable_min_samples = min_samples
    engine._nonusable_min_duration_s = min_duration_s
    return engine


# ---------------------------------------------------------------------------
# (a) single NaN reading on interlock channel → no escalation, log + alarm
# ---------------------------------------------------------------------------


async def test_single_nonusable_logs_and_alarms_no_escalation(caplog) -> None:
    pub = _FakePublisher()
    escalations: list = []

    async def handler(condition, reading):
        escalations.append((condition, reading))

    engine = _make_engine(publisher=pub, handler=handler)

    with caplog.at_level(logging.CRITICAL, logger="cryodaq.core.interlock"):
        await engine._process_reading(_reading(value=float("nan"), offset_s=0.0))

    assert escalations == [], "single blip must NOT escalate"
    assert pub.calls, "single non-usable reading must emit an alarm-v2 event"
    assert pub.calls[0][0] == "Т5 Зона нагрева"
    assert any(rec.levelno == logging.CRITICAL for rec in caplog.records), (
        "single non-usable reading must produce a CRITICAL log"
    )


# ---------------------------------------------------------------------------
# (b) 5+ non-usable spanning >=10s while RUNNING → escalation fires
# ---------------------------------------------------------------------------


async def test_persistent_nonusable_escalates() -> None:
    escalations: list = []

    async def handler(condition, reading):
        escalations.append((condition.name, reading.channel))
        # S1: the handler now signals whether a fault was latched. Returning
        # True marks the window escalated so it does not re-fire on later
        # non-usable samples. (A handler that declines — returns False — leaves
        # the window un-escalated so the next sample retries; see the
        # fail-open leak test below.)
        return True

    engine = _make_engine(handler=handler, min_samples=5, min_duration_s=10.0)

    # 5 consecutive non-usable samples, spanning 0..12 s (>= 10 s).
    for i, off in enumerate((0.0, 3.0, 6.0, 9.0, 12.0)):
        await engine._process_reading(_reading(value=float("nan"), offset_s=off))
        if i < 4:
            assert escalations == [], f"must not escalate before threshold (sample {i})"

    assert escalations == [("overheat_zone", "Т5 Зона нагрева")], (
        "5 non-usable samples over >=10 s must escalate exactly once"
    )

    # Further non-usable samples do NOT re-escalate (window already escalated).
    await engine._process_reading(_reading(value=float("nan"), offset_s=15.0))
    assert len(escalations) == 1, "escalation must fire at most once per window"


# ---------------------------------------------------------------------------
# (b-integration) persistence while RUNNING → real SafetyManager FAULT_LATCHED
# ---------------------------------------------------------------------------


async def test_persistent_nonusable_faults_via_real_safety_manager() -> None:
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=None, mock=True)
    mgr._config.require_keithley_for_run = False
    await mgr.start()
    try:
        # Drive to RUNNING (mock mode, no critical channels required).
        mgr._config.critical_channels = []
        await broker.publish(Reading.now("Т1 верх", 4.5, "K", instrument_id="t"))
        await asyncio.sleep(1.5)
        res = await mgr.request_run(0.5, 40.0, 1.0)
        assert res["ok"] is True
        assert mgr.state == SafetyState.RUNNING

        async def handler(condition, reading):
            return await mgr.on_interlock_dead_channel(
                condition.name, reading.channel, value=reading.value
            )

        engine = _make_engine(handler=handler, min_samples=5, min_duration_s=10.0)
        for off in (0.0, 3.0, 6.0, 9.0, 12.0):
            await engine._process_reading(_reading(value=float("nan"), offset_s=off))

        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"persistent dead interlock channel while RUNNING must latch FAULT, got {mgr.state}"
        )
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# (c) same persistence while NOT running → no fault
# ---------------------------------------------------------------------------


async def test_dead_channel_no_fault_when_not_running() -> None:
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=None, mock=True)
    await mgr.start()
    try:
        assert mgr.state == SafetyState.SAFE_OFF
        await mgr.on_interlock_dead_channel("overheat_zone", "Т5 Зона нагрева", value=float("nan"))
        assert mgr.state == SafetyState.SAFE_OFF, (
            "dead interlock channel while NOT running must never fault"
        )
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# (d) usable reading mid-stream resets the debounce window
# ---------------------------------------------------------------------------


async def test_usable_reading_resets_debounce() -> None:
    escalations: list = []

    async def handler(condition, reading):
        escalations.append(reading.channel)

    engine = _make_engine(handler=handler, min_samples=5, min_duration_s=10.0)

    # 4 bad, then 1 good (reset), then 4 more bad — no window ever reaches 5.
    for off in (0.0, 3.0, 6.0, 9.0):
        await engine._process_reading(_reading(value=float("nan"), offset_s=off))
    # good reading resets the window
    await engine._process_reading(
        _reading(value=42.0, offset_s=12.0, status=ChannelStatus.OK)
    )
    for off in (15.0, 18.0, 21.0, 24.0):
        await engine._process_reading(_reading(value=float("nan"), offset_s=off))

    assert escalations == [], "a usable reading must reset the consecutive-non-usable window"


# ---------------------------------------------------------------------------
# (e) finite value + error status counts as non-usable (doctrine, not float)
# ---------------------------------------------------------------------------


async def test_finite_error_status_is_nonusable() -> None:
    escalations: list = []

    async def handler(condition, reading):
        escalations.append(reading.channel)

    engine = _make_engine(handler=handler, min_samples=5, min_duration_s=10.0)

    # Finite values but SENSOR_ERROR status — must be treated as non-usable.
    for off in (0.0, 3.0, 6.0, 9.0, 12.0):
        await engine._process_reading(
            _reading(value=123.4, offset_s=off, status=ChannelStatus.SENSOR_ERROR)
        )

    assert escalations == ["Т5 Зона нагрева"], (
        "finite value + error status must count as non-usable and escalate"
    )


# ---------------------------------------------------------------------------
# regression: a usable threshold breach still trips normally
# ---------------------------------------------------------------------------


async def test_usable_threshold_breach_still_trips() -> None:
    tripped: list = []

    async def action() -> None:
        tripped.append(True)

    engine = InterlockEngine(broker=DataBroker(), actions={"emergency_off": action})
    engine.add_condition(
        InterlockCondition(
            name="overheat_zone",
            description="Перегрев",
            channel_pattern=r"Т5 .*",
            threshold=350.0,
            comparison=">",
            action="emergency_off",
        )
    )
    await engine._process_reading(
        _reading(value=400.0, offset_s=0.0, status=ChannelStatus.OK)
    )
    assert tripped == [True], "a finite over-threshold reading must trip exactly as before"


# ---------------------------------------------------------------------------
# S1 (CRITICAL fail-open): escalated flag must NOT leak when escalation is
# declined because the manager is not RUNNING.
# ---------------------------------------------------------------------------


async def test_escalated_flag_not_leaked_when_not_running() -> None:
    """A window that reaches the escalation threshold while the manager is NOT
    RUNNING must not stay marked escalated. Otherwise the still-dead channel
    never faults once RUNNING begins (until a usable reading resets it) — a
    fail-open session leak. Fail-closed: escalated stays False, and the first
    non-usable sample after RUNNING begins latches FAULT.
    """
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=None, mock=True)
    mgr._config.require_keithley_for_run = False
    mgr._config.critical_channels = []
    await mgr.start()
    try:

        async def handler(condition, reading):
            return await mgr.on_interlock_dead_channel(
                condition.name, reading.channel, value=reading.value
            )

        engine = _make_engine(handler=handler, min_samples=5, min_duration_s=10.0)

        # Escalation threshold reached while SAFE_OFF → declined, must NOT latch.
        assert mgr.state == SafetyState.SAFE_OFF
        for off in (0.0, 3.0, 6.0, 9.0, 12.0):
            await engine._process_reading(_reading(value=float("nan"), offset_s=off))
        assert mgr.state == SafetyState.SAFE_OFF, "must not fault while not RUNNING"
        window = engine._nonusable_windows["Т5 Зона нагрева"]
        assert window.escalated is False, (
            "escalation declined (not RUNNING) must NOT mark the window escalated — "
            "otherwise the dead channel never re-escalates once RUNNING begins"
        )

        # Transition to RUNNING.
        await broker.publish(Reading.now("Т1 верх", 4.5, "K", instrument_id="t"))
        await asyncio.sleep(1.5)
        res = await mgr.request_run(0.5, 40.0, 1.0)
        assert res["ok"] is True
        assert mgr.state == SafetyState.RUNNING

        # ONE more non-usable sample on the still-dead channel must fault now.
        await engine._process_reading(_reading(value=float("nan"), offset_s=15.0))
        assert mgr.state == SafetyState.FAULT_LATCHED, (
            "first non-usable sample after RUNNING begins must fault (fail-closed)"
        )
        assert engine._nonusable_windows["Т5 Зона нагрева"].escalated is True, (
            "once the fault is latched the window must be marked escalated"
        )
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# S2 (HIGH): +inf overrange on an above-threshold interlock is direct evidence
# of the guarded hazard — insta-trip, do NOT wait out the non-usable debounce.
# ---------------------------------------------------------------------------


def _trip_engine(*, comparison: str, threshold: float, handler=None) -> tuple[InterlockEngine, list]:
    tripped: list = []

    async def action() -> None:
        tripped.append(True)

    engine = InterlockEngine(
        broker=DataBroker(),
        actions={"emergency_off": action},
        dead_channel_handler=handler,
    )
    engine.add_condition(
        InterlockCondition(
            name="iface",
            description="направленный интерлок",
            channel_pattern=r"Т5 .*",
            threshold=threshold,
            comparison=comparison,
            action="emergency_off",
        )
    )
    return engine, tripped


async def test_positive_inf_overrange_insta_trips_above_threshold() -> None:
    engine, tripped = _trip_engine(comparison=">", threshold=350.0)
    # A normal below-threshold reading, then +inf/OVERRANGE (sensor pegged HIGH).
    await engine._process_reading(_reading(value=300.0, offset_s=0.0, status=ChannelStatus.OK))
    assert tripped == [], "below-threshold reading must not trip"
    await engine._process_reading(
        _reading(value=float("inf"), offset_s=0.5, status=ChannelStatus.OVERRANGE)
    )
    assert tripped == [True], (
        "+inf on an above-threshold interlock must trip at once, not wait for debounce"
    )


async def test_negative_inf_insta_trips_below_threshold() -> None:
    engine, tripped = _trip_engine(comparison="<", threshold=1.0)
    # -inf (pegged LOW) on a below-threshold interlock is the dangerous side.
    await engine._process_reading(
        _reading(value=float("-inf"), offset_s=0.0, status=ChannelStatus.UNDERRANGE)
    )
    assert tripped == [True], "-inf on a below-threshold interlock must insta-trip (symmetric)"


async def test_positive_inf_safe_side_debounces() -> None:
    """+inf on a BELOW-threshold interlock is the SAFE side — no directional
    danger — so it stays on the non-usable debounce path, not an insta-trip."""
    escalations: list = []

    async def handler(condition, reading):
        escalations.append(reading.channel)
        return False

    engine, tripped = _trip_engine(comparison="<", threshold=1.0, handler=handler)
    await engine._process_reading(
        _reading(value=float("inf"), offset_s=0.0, status=ChannelStatus.OVERRANGE)
    )
    assert tripped == [], "+inf on a below-threshold interlock is the safe side — must not trip"
    window = engine._nonusable_windows.get("Т5 Зона нагрева")
    assert window is not None, "safe-side infinity must feed the non-usable debounce window"
    assert window.count == 1


async def test_nan_still_debounces_not_insta_trip() -> None:
    """Regression guard for S2: NaN carries no directional evidence, so it must
    keep the debounce path even on an above-threshold interlock."""
    escalations: list = []

    async def handler(condition, reading):
        escalations.append(reading.channel)
        return True

    engine, tripped = _trip_engine(comparison=">", threshold=350.0, handler=handler)
    await engine._process_reading(_reading(value=float("nan"), offset_s=0.0))
    assert tripped == [], "NaN must never insta-trip"
    assert engine._nonusable_windows["Т5 Зона нагрева"].count == 1, "NaN must debounce"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
