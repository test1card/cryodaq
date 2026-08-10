"""Tests for P2-5: interlock NaN debounced escalation (NaN-доктрина Phase 2).

Semantics under test:
- Transient non-usable reading (NaN / error-status) on an interlock-protected
  channel → CRITICAL log + alarm-v2 event, NO trip.
- Persistent non-usable (≥min_duration_s AND ≥min_samples consecutive) while
  the source lifecycle is RUN_PERMITTED or RUNNING → SafetyManager FAULT_LATCHED.
- Outside the active source lifecycle → no fault, but RUN stays blocked.
- A usable reading clears the blocker and resets the debounce window.
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
_CHANNEL_ID = "Т5"


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
    channel: str = _CHANNEL_ID,
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
    recovery_handler=None,
    min_samples: int = 5,
    min_duration_s: float = 10.0,
) -> InterlockEngine:
    engine = InterlockEngine(
        broker=DataBroker(),
        actions={"emergency_off": _noop},
        alarm_publisher=publisher,
        dead_channel_handler=handler,
        dead_channel_recovery_handler=recovery_handler,
    )
    engine.add_condition(
        InterlockCondition(
            name="overheat_zone",
            description="Перегрев зоны нагрева",
            channel_ids=frozenset({_CHANNEL_ID}),
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
    assert pub.calls[0][0] == _CHANNEL_ID
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

    assert escalations == [("overheat_zone", _CHANNEL_ID)], (
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
            return await mgr.on_interlock_dead_channel(condition.name, reading.channel, value=reading.value)

        engine = _make_engine(handler=handler, min_samples=5, min_duration_s=10.0)
        for off in (0.0, 3.0, 6.0, 9.0, 12.0):
            await engine._process_reading(_reading(value=float("nan"), offset_s=off))

        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"persistent dead interlock channel while RUNNING must latch FAULT, got {mgr.state}"
        )
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# (c) same persistence outside the active source lifecycle → no fault
# ---------------------------------------------------------------------------


async def test_dead_channel_no_fault_outside_active_source_lifecycle() -> None:
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=None, mock=True)
    mgr._config.require_keithley_for_run = False
    mgr._config.critical_channels = []
    await mgr.start()
    try:
        assert mgr.state == SafetyState.SAFE_OFF
        await mgr.on_interlock_dead_channel("overheat_zone", _CHANNEL_ID, value=float("nan"))
        assert mgr.state == SafetyState.SAFE_OFF, (
            "dead interlock channel while source lifecycle is inactive must not fault"
        )
        result = await mgr.request_run(0.5, 40.0, 1.0)
        assert result["ok"] is False
        assert _CHANNEL_ID in result["error"]
        assert "mature_dead_interlock_channel" in {blocker.code for blocker in mgr.snapshot_operator_safety().blockers}
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
    await engine._process_reading(_reading(value=42.0, offset_s=12.0, status=ChannelStatus.OK))
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
        await engine._process_reading(_reading(value=123.4, offset_s=off, status=ChannelStatus.SENSOR_ERROR))

    assert escalations == [_CHANNEL_ID], "finite value + error status must count as non-usable and escalate"


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
            channel_ids=frozenset({_CHANNEL_ID}),
            threshold=350.0,
            comparison=">",
            action="emergency_off",
        )
    )
    await engine._process_reading(_reading(value=400.0, offset_s=0.0, status=ChannelStatus.OK))
    assert tripped == [True], "a finite over-threshold reading must trip exactly as before"


# ---------------------------------------------------------------------------
# S1 (CRITICAL fail-open): escalated flag must NOT leak when escalation is
# declined because the manager is outside RUN_PERMITTED/RUNNING.
# ---------------------------------------------------------------------------


async def test_mature_idle_dead_channel_survives_ack_until_usable_recovery() -> None:
    """A mature canonical blocker survives acknowledgment and clears on evidence."""
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=None, mock=True)
    mgr._config.require_keithley_for_run = False
    mgr._config.critical_channels = []
    mgr._config.cooldown_before_rearm_s = 0.0
    await mgr.start()
    try:

        async def handler(condition, reading):
            return await mgr.on_interlock_dead_channel(condition.name, reading.channel, value=reading.value)

        async def recovery_handler(condition, reading):
            mgr.on_interlock_channel_recovered(condition.name, reading.channel)

        engine = _make_engine(
            handler=handler,
            recovery_handler=recovery_handler,
            min_samples=5,
            min_duration_s=10.0,
        )

        # Threshold maturity while SAFE_OFF does not fault, but it does revoke
        # RUN authority until a usable canonical sample reaches InterlockEngine.
        for off in (0.0, 3.0, 6.0, 9.0, 12.0):
            await engine._process_reading(_reading(value=float("nan"), offset_s=off))
        assert mgr.state == SafetyState.SAFE_OFF
        assert engine._nonusable_windows[_CHANNEL_ID].escalated is False
        blocked = await mgr.request_run(0.5, 40.0, 1.0)
        assert blocked["ok"] is False
        assert _CHANNEL_ID in blocked["error"]

        # A separate acknowledged fault must not erase sensor-death evidence.
        await mgr.latch_fault("synthetic acknowledgment control", "test")
        acknowledged = await mgr.acknowledge_fault("operator control")
        assert acknowledged["ok"] is True
        assert "mature_dead_interlock_channel" in {blocker.code for blocker in mgr.snapshot_operator_safety().blockers}

        # Only a usable reading through the production InterlockEngine path
        # clears both the manager-owned blocker and the debounce window.
        await engine._process_reading(_reading(value=42.0, offset_s=15.0, status=ChannelStatus.OK))
        assert _CHANNEL_ID not in engine._nonusable_windows
        assert "mature_dead_interlock_channel" not in {
            blocker.code for blocker in mgr.snapshot_operator_safety().blockers
        }
        await mgr._run_checks()
        run_result = await mgr.request_run(0.5, 40.0, 1.0)
        assert run_result["ok"] is True
        assert mgr.state == SafetyState.RUNNING

        # A new mature window while RUNNING still latches the fault.
        for off in (18.0, 21.0, 24.0, 27.0, 30.0):
            await engine._process_reading(_reading(value=float("nan"), offset_s=off))
        assert mgr.state == SafetyState.FAULT_LATCHED
        assert engine._nonusable_windows[_CHANNEL_ID].escalated is True
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
            channel_ids=frozenset({_CHANNEL_ID}),
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
    await engine._process_reading(_reading(value=float("inf"), offset_s=0.5, status=ChannelStatus.OVERRANGE))
    assert tripped == [True], "+inf on an above-threshold interlock must trip at once, not wait for debounce"


async def test_negative_inf_insta_trips_below_threshold() -> None:
    engine, tripped = _trip_engine(comparison="<", threshold=1.0)
    # -inf (pegged LOW) on a below-threshold interlock is the dangerous side.
    await engine._process_reading(_reading(value=float("-inf"), offset_s=0.0, status=ChannelStatus.UNDERRANGE))
    assert tripped == [True], "-inf on a below-threshold interlock must insta-trip (symmetric)"


async def test_positive_inf_safe_side_debounces() -> None:
    """+inf on a BELOW-threshold interlock is the SAFE side — no directional
    danger — so it stays on the non-usable debounce path, not an insta-trip."""
    escalations: list = []

    async def handler(condition, reading):
        escalations.append(reading.channel)
        return False

    engine, tripped = _trip_engine(comparison="<", threshold=1.0, handler=handler)
    await engine._process_reading(_reading(value=float("inf"), offset_s=0.0, status=ChannelStatus.OVERRANGE))
    assert tripped == [], "+inf on a below-threshold interlock is the safe side — must not trip"
    window = engine._nonusable_windows.get(_CHANNEL_ID)
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
    assert engine._nonusable_windows[_CHANNEL_ID].count == 1, "NaN must debounce"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
