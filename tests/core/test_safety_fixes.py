"""Tests for SafetyManager safety fixes.

Covers:
  Fix 1 — FAULT_LATCHED is sticky: not cleared by request_stop or emergency_off.
  Fix 2 — SENSOR_ERROR status blocks run; NaN value triggers fault.
  Fix 4 — Rate-of-change check is unit-gated (Volts ignored, Kelvin detected).
  Fix 5 — SafetyEvent carries channel and value when faulting.

Also updates test_disk_monitor.py patterns: all disk tests mock shutil.disk_usage
via the correct module path "cryodaq.core.disk_monitor.shutil.disk_usage".
"""

from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.base import ChannelStatus, Reading

# ---------------------------------------------------------------------------
# Helpers (mirror test_safety_manager.py conventions)
# ---------------------------------------------------------------------------


def _mock_keithley():
    k = MagicMock()
    k.connected = True
    k.emergency_off = AsyncMock()
    k.stop_source = AsyncMock()
    k.start_source = AsyncMock()
    return k


async def _make_manager(*, mock=True, keithley=None, stale=10.0):
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=keithley, mock=mock)
    mgr._config.stale_timeout_s = stale
    mgr._config.cooldown_before_rearm_s = 0.1
    mgr._config.require_keithley_for_run = not mock
    await mgr.start()
    return mgr, broker


async def _feed(
    broker,
    channel="Т1 Криостат верх",
    value=4.5,
    unit="K",
    status=ChannelStatus.OK,
):
    r = Reading.now(channel=channel, value=value, unit=unit, instrument_id="test", status=status)
    await broker.publish(r)
    await asyncio.sleep(0.02)


async def _get_to_running(mgr, broker):
    """Bring manager to RUNNING (mock mode, no critical channels required)."""
    mgr._config.critical_channels = []
    await _feed(broker)
    await asyncio.sleep(1.5)
    assert mgr.state == SafetyState.READY
    result = await mgr.request_run(0.5, 40.0, 1.0)
    assert result["ok"] is True
    assert mgr.state == SafetyState.RUNNING


# ---------------------------------------------------------------------------
# Fix 1 — FAULT_LATCHED is a latch: operator stop / emergency_off must not
#          silently clear it.
# ---------------------------------------------------------------------------


async def test_fault_latched_not_cleared_by_stop():
    """request_stop() while FAULT_LATCHED must leave state as FAULT_LATCHED."""
    mgr, broker = await _make_manager()
    try:
        await _get_to_running(mgr, broker)

        # Trigger fault directly
        await mgr._fault("Тест: устройство отказало")
        assert mgr.state == SafetyState.FAULT_LATCHED

        result = await mgr.request_stop()

        # State must remain FAULT_LATCHED — a plain stop must not clear the latch
        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"Expected FAULT_LATCHED after request_stop, got {mgr.state}"
        )
        assert result["ok"] is False, "request_stop() from FAULT_LATCHED should report ok=False"
    finally:
        await mgr.stop()


async def test_fault_latched_not_cleared_by_emergency():
    """emergency_off() while FAULT_LATCHED must call keithley.emergency_off but
    must NOT transition the state machine away from FAULT_LATCHED."""
    k = _mock_keithley()
    mgr, broker = await _make_manager(mock=False, keithley=k)
    try:
        await _get_to_running(mgr, broker)

        await mgr._fault("Тест: перегрев")
        assert mgr.state == SafetyState.FAULT_LATCHED

        result = await mgr.emergency_off()

        # Hardware output must have been driven off
        k.emergency_off.assert_called()

        # The fault latch must persist — emergency_off is NOT an acknowledge
        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"emergency_off must not clear FAULT_LATCHED, got {mgr.state}"
        )
        # Production contract: emergency_off() from FAULT_LATCHED returns ok=True
        # but includes latched=True to signal the fault is still active.
        # (Verified in safety_manager.py:410-418: the latched branch returns
        # ok=True, latched=True, with warning="Outputs disabled but fault remains latched")
        assert result["ok"] is True, (
            f"emergency_off from FAULT_LATCHED should return ok=True (outputs disabled), "
            f"got ok={result.get('ok')}"
        )
        assert result.get("latched") is True, (
            f"emergency_off from FAULT_LATCHED must set latched=True, got {result}"
        )
    finally:
        await mgr.stop()


async def test_fault_recovery_only_through_acknowledge():
    """Full happy-path: RUNNING → FAULT_LATCHED → acknowledge → MANUAL_RECOVERY → READY."""
    mgr, broker = await _make_manager()
    try:
        await _get_to_running(mgr, broker)

        # Inject fault
        await mgr._fault("Тест: нарушение условий")
        assert mgr.state == SafetyState.FAULT_LATCHED

        # Cooldown must pass first (set to 0.1 s in _make_manager)
        await asyncio.sleep(0.2)

        result = await mgr.acknowledge_fault("Проверено, всё исправлено")
        assert result["ok"] is True, f"acknowledge_fault failed: {result}"
        assert mgr.state == SafetyState.MANUAL_RECOVERY

        # Feed fresh data so preconditions pass
        await _feed(broker)
        await asyncio.sleep(1.5)

        assert mgr.state == SafetyState.READY, (
            f"Expected READY after MANUAL_RECOVERY + good data, got {mgr.state}"
        )
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# Fix 2 — SENSOR_ERROR / NaN value handling
# ---------------------------------------------------------------------------


async def test_error_status_blocks_run():
    """A critical channel in SENSOR_ERROR status must prevent request_run."""
    mgr, broker = await _make_manager()
    mgr._config.critical_channels = [re.compile("Т1.*")]
    try:
        # Feed an errored reading for the critical channel
        await _feed(
            broker,
            channel="Т1 Криостат верх",
            value=0.0,
            unit="K",
            status=ChannelStatus.SENSOR_ERROR,
        )
        await asyncio.sleep(1.5)  # let monitor loop run

        result = await mgr.request_run(0.5, 40.0, 1.0)

        assert result["ok"] is False, "request_run must fail when critical channel has SENSOR_ERROR"
        # The error message should mention the channel status or the channel name
        error_text = result.get("error", "")
        assert error_text, "Should provide an error message"
    finally:
        await mgr.stop()


async def test_nan_value_triggers_fault():
    """A NaN reading on a monitored channel while RUNNING must trigger FAULT_LATCHED."""
    mgr, broker = await _make_manager(stale=30.0)
    mgr._config.critical_channels = [re.compile("Т7.*")]
    try:
        # Seed a good reading so we can reach RUNNING
        await _feed(broker, channel="Т7 Нагреватель", value=4.5, unit="K")
        await asyncio.sleep(1.5)
        result = await mgr.request_run(0.5, 40.0, 1.0)
        assert result["ok"] is True
        assert mgr.state == SafetyState.RUNNING

        # Feed a NaN reading for the critical channel
        await _feed(broker, channel="Т7 Нагреватель", value=float("nan"), unit="K")
        await asyncio.sleep(1.5)  # let monitor loop tick

        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"NaN reading must cause FAULT_LATCHED, got {mgr.state}"
        )
    finally:
        await mgr.stop()


async def test_ok_status_passes():
    """A reading with ChannelStatus.OK on a critical channel must allow request_run."""
    mgr, broker = await _make_manager()
    mgr._config.critical_channels = [re.compile("Т1.*")]
    try:
        await _feed(
            broker,
            channel="Т1 Криостат верх",
            value=4.5,
            unit="K",
            status=ChannelStatus.OK,
        )
        await asyncio.sleep(1.5)

        result = await mgr.request_run(0.5, 40.0, 1.0)

        assert result["ok"] is True, (
            f"request_run must succeed with OK status reading, error: {result.get('error')}"
        )
        assert mgr.state == SafetyState.RUNNING
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# Fix 4 — Rate-of-change check is limited to temperature channels (unit == "K")
# ---------------------------------------------------------------------------


async def test_rate_limit_ignores_non_temperature():
    """Voltage readings with huge dV/dt must NOT trigger FAULT_LATCHED.

    The voltage channel IS configured as critical so the stale-check machinery
    is active.  Unit is 'V', not 'K', so _collect_loop must exclude it from
    the rate estimator.  A slope that would definitely fault a K-channel
    (>60 samples, +100 V per sample) must leave state == RUNNING.
    """
    mgr, broker = await _make_manager(stale=30.0)
    # Make voltage channel critical — stale machinery is now engaged.
    # stale_timeout_s=30 and we keep feeding, so stale-check won't fire either.
    mgr._config.critical_channels = [re.compile(r"Keithley/voltage")]
    mgr._config.max_dT_dt_K_per_min = 5.0
    try:
        # Seed a fresh voltage reading so the channel is not stale at run-start
        await _feed(broker, channel="Keithley/voltage", value=0.0, unit="V")
        await asyncio.sleep(1.5)
        result = await mgr.request_run(0.5, 40.0, 1.0)
        assert result["ok"] is True, f"request_run failed: {result.get('error')}"
        assert mgr.state == SafetyState.RUNNING

        # Publish >=60 voltage readings at a slope that would fault if unit were K.
        # Unit is "V" so _collect_loop must gate them out of the rate estimator.
        for i in range(65):
            v = float(i) * 100.0  # +100 V per sample → enormous rate if it were K
            r = Reading.now(channel="Keithley/voltage", value=v, unit="V", instrument_id="test")
            await broker.publish(r)
            await asyncio.sleep(0.01)

        # Allow monitor loop to run
        await asyncio.sleep(1.5)

        # Primary assertion: manager stayed RUNNING — voltage is excluded at the
        # unit level even though the channel IS critical.
        assert mgr.state == SafetyState.RUNNING, (
            f"Voltage rate change must not trigger FAULT_LATCHED, got {mgr.state}"
        )
        # Secondary: confirm the estimator has NO entry for the voltage channel.
        assert "Keithley/voltage" not in mgr._rate_estimator.channels(), (
            "Voltage channel must not be pushed into the rate estimator (unit != 'K')"
        )
    finally:
        await mgr.stop()


async def test_rate_limit_catches_critical_temperature():
    """Temperature readings on a CRITICAL channel rising faster than max_dT_dt_K_per_min must FAULT."""  # noqa: E501
    mgr, broker = await _make_manager(stale=30.0)
    mgr._config.critical_channels = [re.compile("Т1.*")]
    mgr._config.max_dT_dt_K_per_min = 5.0
    try:
        # Phase 2c CC I.3: SafetyManager rate estimator now requires >=60
        # samples (was 10) before producing a slope estimate. The test
        # therefore needs to push enough data to fill the buffer before any
        # rate-based fault check can trigger.
        for i in range(80):
            # +1 K per sample at 1 ms cadence → effectively a steep rise
            temp = 4.0 + i * 1.0
            r = Reading.now(channel="Т1 Криостат верх", value=temp, unit="K", instrument_id="test")
            await broker.publish(r)
            await asyncio.sleep(0.001)

        await asyncio.sleep(1.5)

        # Reach RUNNING — we need data already in buffers
        if mgr.state in (SafetyState.SAFE_OFF, SafetyState.READY):
            result = await mgr.request_run(0.5, 40.0, 1.0)
            if not result["ok"]:
                # Already faulted — that's fine, test passes
                assert mgr.state == SafetyState.FAULT_LATCHED
                return

        # Feed more rapidly rising samples to keep triggering rate check
        for i in range(80):
            temp = 84.0 + i * 1.0
            r = Reading.now(channel="Т1 Криостат верх", value=temp, unit="K", instrument_id="test")
            await broker.publish(r)
            await asyncio.sleep(0.001)

        await asyncio.sleep(1.5)

        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"Rapid temperature rise on critical channel must trigger FAULT_LATCHED, got {mgr.state}"  # noqa: E501
        )
    finally:
        await mgr.stop()


async def test_rate_limit_ignores_non_critical_channel():
    """Temperature readings on a NON-critical channel must NOT trigger FAULT_LATCHED,
    even if dT/dt exceeds the limit. This prevents disconnected sensors (e.g. T4)
    with noisy readings from blocking Keithley start_source."""
    mgr, broker = await _make_manager(stale=30.0)
    mgr._config.critical_channels = [re.compile("Т1.*")]
    mgr._config.max_dT_dt_K_per_min = 5.0
    try:
        # Feed good data on critical channel to reach RUNNING
        await _feed(broker, channel="Т1 Криостат верх", value=4.5, unit="K")
        await asyncio.sleep(1.5)
        result = await mgr.request_run(0.5, 40.0, 1.0)
        assert result["ok"] is True
        assert mgr.state == SafetyState.RUNNING

        # Feed >=60 rapidly changing data on a NON-critical channel (T4 — disconnected sensor).
        # 65 samples guarantees the rate estimator CAN compute a rate for this channel
        # (needs >= min_points=60), so the test actually exercises the critical-channel
        # gate rather than just relying on the estimator returning None.
        for i in range(65):
            temp = 4.0 + i * 10.0  # +10 K per sample → well above 5 K/min limit
            r = Reading.now(channel="Т4 Радиатор 2", value=temp, unit="K", instrument_id="test")
            await broker.publish(r)
            await asyncio.sleep(0.01)

        # Keep critical channel fresh so stale-check doesn't fire
        await _feed(broker, channel="Т1 Криостат верх", value=4.5, unit="K")
        await asyncio.sleep(1.5)

        # Confirm the estimator DID record the non-critical channel (received enough samples)
        assert mgr._rate_estimator.buffer_size("Т4 Радиатор 2") >= 60, (
            "Expected >=60 samples in rate estimator for Т4 to prove the channel gate was tested"
        )
        assert mgr.state == SafetyState.RUNNING, (
            f"Non-critical channel rate must not trigger FAULT_LATCHED, got {mgr.state}"
        )
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# Fix 5 — SafetyEvent carries channel name and numeric value
# ---------------------------------------------------------------------------


async def test_fault_event_has_channel_and_value():
    """on_interlock_trip must produce an event with channel and value populated."""
    mgr, broker = await _make_manager()
    try:
        await mgr.on_interlock_trip("overheat", "T7", 350.0)

        assert mgr.state == SafetyState.FAULT_LATCHED

        events = mgr.get_events()
        # Find the FAULT_LATCHED transition event
        fault_events = [e for e in events if e.to_state == SafetyState.FAULT_LATCHED]
        assert fault_events, "No FAULT_LATCHED event found in event history"

        ev = fault_events[-1]
        assert ev.channel == "T7", f"Event channel must be 'T7', got '{ev.channel}'"
        assert ev.value == pytest.approx(350.0), f"Event value must be 350.0, got {ev.value}"
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# RateEstimator integration — verify SafetyManager uses RateEstimator
# ---------------------------------------------------------------------------


async def test_rate_limit_faults_on_critical_channel():
    """Black-box rate-limit invariant: a steep dT/dt on a CRITICAL channel while
    RUNNING latches FAULT_LATCHED. (The sibling test above already proves a steep
    rate on a NON-critical channel does NOT fault.) Replaces a prior test that
    only asserted private attributes (_rate_estimator present, _rate_buffers
    absent) and so could not catch a rate limiter that silently stopped working.
    """
    mgr, broker = await _make_manager(stale=30.0)
    try:
        crit = "Т1 Криостат верх"
        # critical_channels holds compiled regex patterns, not raw strings.
        mgr._config.critical_channels = [re.compile(re.escape(crit))]
        # Reach RUNNING with the critical channel fresh and in-range.
        await _feed(broker, channel=crit, value=4.5, unit="K")
        await asyncio.sleep(1.5)
        assert mgr.state == SafetyState.READY
        assert (await mgr.request_run(0.5, 40.0, 1.0))["ok"] is True
        assert mgr.state == SafetyState.RUNNING

        # Drive a steep dT/dt on the critical channel. The RateEstimator needs
        # >= min_points (60) samples in-window before it reports a rate, so feed
        # 65 rising samples (+0.5 K each, kept < 40 K). dT/dt is then far above
        # the 5 K/min limit.
        for i in range(65):
            r = Reading.now(
                channel=crit, value=4.5 + i * 0.5, unit="K", instrument_id="test"
            )
            await broker.publish(r)
            await asyncio.sleep(0.01)
        await asyncio.sleep(1.5)

        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"steep dT/dt on a critical channel must latch FAULT, got {mgr.state}"
        )
        reason = mgr.fault_reason.lower()
        assert "rate" in reason or "dt" in reason or "k/min" in reason, (
            f"fault_reason should name the rate-limit cause, got {mgr.fault_reason!r}"
        )
    finally:
        await mgr.stop()
