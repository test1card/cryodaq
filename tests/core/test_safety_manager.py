"""Tests for SafetyManager — safety-critical state machine."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager, SafetyState
from cryodaq.drivers.base import Reading


def _mock_keithley():
    """Create a mock Keithley driver.

    ``emergency_off`` returns True per the CR-2 driver contract: True iff
    every targeted channel's OUTPUT_OFF write succeeded AND readback
    confirmed the output is OFF.
    """
    k = MagicMock()
    k.connected = True
    k.emergency_off = AsyncMock(return_value=True)
    k.stop_source = AsyncMock()
    k.start_source = AsyncMock()
    return k


async def _make_manager(*, mock=True, keithley=None, stale=10.0):
    """Create and start a SafetyManager with SafetyBroker."""
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=keithley, mock=mock)
    mgr._config.stale_timeout_s = stale
    mgr._config.cooldown_before_rearm_s = 0.1  # Fast for tests
    mgr._config.require_keithley_for_run = not mock
    await mgr.start()
    return mgr, broker


async def _feed(broker, channel="Т1 Криостат верх", value=4.5, unit="K"):
    """Publish a reading to the safety broker."""
    r = Reading.now(channel=channel, value=value, unit=unit, instrument_id="test")
    await broker.publish(r)
    await asyncio.sleep(0.02)  # Let collect loop process


# ---------------------------------------------------------------------------
# 1. Initial state is SAFE_OFF
# ---------------------------------------------------------------------------


async def test_initial_state_safe_off():
    mgr, broker = await _make_manager()
    try:
        assert mgr.state == SafetyState.SAFE_OFF
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 2. SAFE_OFF → READY when data arrives (mock mode)
# ---------------------------------------------------------------------------


async def test_safe_off_to_ready():
    mgr, broker = await _make_manager()
    try:
        await _feed(broker, "Т1 Криостат верх", 4.5)
        # Wait for monitor loop to check
        await asyncio.sleep(1.5)
        assert mgr.state == SafetyState.READY
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 3. READY → RUNNING via request_run
# ---------------------------------------------------------------------------


async def test_ready_to_running():
    mgr, broker = await _make_manager()
    try:
        await _feed(broker, "Т1 Криостат верх", 4.5)
        await asyncio.sleep(1.5)
        assert mgr.state == SafetyState.READY

        result = await mgr.request_run(0.5, 40.0, 1.0)
        assert result["ok"] is True
        assert mgr.state == SafetyState.RUNNING
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 4. RUNNING → SAFE_OFF via request_stop
# ---------------------------------------------------------------------------


async def test_running_to_safe_off():
    mgr, broker = await _make_manager()
    try:
        await _feed(broker, "Т1 Криостат верх", 4.5)
        await asyncio.sleep(1.5)
        await mgr.request_run(0.5, 40.0, 1.0)
        assert mgr.state == SafetyState.RUNNING

        result = await mgr.request_stop()
        assert result["ok"] is True
        assert mgr.state == SafetyState.SAFE_OFF
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 5. RUNNING → FAULT_LATCHED on stale data (fail-on-silence)
# ---------------------------------------------------------------------------


async def test_fault_on_stale_data():
    mgr, broker = await _make_manager(stale=1.0)
    mgr._config.critical_channels = []  # No critical channels for READY
    try:
        await _feed(broker, "Т1 Криостат верх", 4.5)
        await asyncio.sleep(1.5)
        # Force to RUNNING
        await mgr.request_run(0.5, 40.0, 1.0)
        assert mgr.state == SafetyState.RUNNING

        # Now add critical channel pattern and stop feeding
        import re

        mgr._config.critical_channels = [re.compile("Т1 .*")]

        # Wait for stale timeout + monitor check
        await asyncio.sleep(2.5)
        assert mgr.state == SafetyState.FAULT_LATCHED
        assert "Устаревшие" in mgr.fault_reason
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 6. FAULT_LATCHED → MANUAL_RECOVERY → READY (recovery flow)
# ---------------------------------------------------------------------------


async def test_recovery_flow():
    mgr, broker = await _make_manager()
    try:
        await _feed(broker, "Т1 Криостат верх", 4.5)
        await asyncio.sleep(1.5)
        await mgr.request_run(0.5, 40.0, 1.0)

        # Force fault
        await mgr._fault("Test fault")
        assert mgr.state == SafetyState.FAULT_LATCHED

        # Wait for cooldown
        await asyncio.sleep(0.2)

        # Acknowledge with reason
        result = await mgr.acknowledge_fault("Проверил — всё ОК")
        assert result["ok"] is True
        assert mgr.state == SafetyState.MANUAL_RECOVERY

        # Feed data and wait for precondition check → READY
        await _feed(broker, "Т1 Криостат верх", 4.5)
        await asyncio.sleep(1.5)
        assert mgr.state == SafetyState.READY
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 7. Acknowledge without reason rejected
# ---------------------------------------------------------------------------


async def test_acknowledge_requires_reason():
    mgr, broker = await _make_manager()
    try:
        await mgr._fault("Test fault")
        await asyncio.sleep(0.2)
        result = await mgr.acknowledge_fault("")
        assert result["ok"] is False
        assert "причину" in result["error"].lower() or "Укажите" in result["error"]
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 8. Cooldown prevents immediate recovery
# ---------------------------------------------------------------------------


async def test_cooldown_before_recovery():
    mgr, broker = await _make_manager()
    mgr._config.cooldown_before_rearm_s = 5.0
    try:
        await mgr._fault("Test fault")
        result = await mgr.acknowledge_fault("Причина")
        assert result["ok"] is False
        assert "Ожидание" in result["error"] or "ещё" in result["error"]
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 9. Emergency off from any state
# ---------------------------------------------------------------------------


async def test_emergency_off_from_running():
    k = _mock_keithley()
    mgr, broker = await _make_manager(mock=False, keithley=k)
    try:
        await _feed(broker, "Т1 Криостат верх", 4.5)
        await asyncio.sleep(1.5)
        await mgr.request_run(0.5, 40.0, 1.0)

        result = await mgr.emergency_off()
        assert result["ok"] is True
        assert mgr.state == SafetyState.SAFE_OFF
        k.emergency_off.assert_called()
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 9b. CR-2: emergency_off FAILS CLOSED when output OFF cannot be confirmed
# ---------------------------------------------------------------------------


async def test_emergency_off_unconfirmed_latches_fault():
    """CR-2: if the driver cannot confirm output OFF (write raised or readback
    still-on → driver returns False), operator emergency_off must NOT report
    success and must NOT transition to SAFE_OFF (which would stop all
    stale/heartbeat/rate monitoring while the SMU may still be sourcing).
    It must latch a FAULT instead."""
    k = _mock_keithley()
    k.emergency_off = AsyncMock(return_value=False)
    mgr, broker = await _make_manager(mock=False, keithley=k)
    try:
        await _feed(broker, "Т1 Криостат верх", 4.5)
        await asyncio.sleep(1.5)
        await mgr.request_run(0.5, 40.0, 1.0)
        assert mgr.state == SafetyState.RUNNING

        result = await mgr.emergency_off()

        assert result["ok"] is False, "must not report success on unconfirmed OFF"
        assert "error" in result
        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"unconfirmed emergency_off must latch FAULT, got {mgr.state}"
        )
        assert mgr.state != SafetyState.SAFE_OFF
    finally:
        await mgr.stop()


async def test_emergency_off_driver_raise_latches_fault():
    """CR-2: a driver emergency_off that RAISES (transport dead mid-call)
    must also fail closed: ok=False + FAULT_LATCHED, never SAFE_OFF."""
    k = _mock_keithley()
    # First call (operator path via _ensure_output_off) raises; the retry
    # inside _fault()'s shielded shutdown also raises — both must be survived.
    k.emergency_off = AsyncMock(side_effect=OSError("transport down"))
    mgr, broker = await _make_manager(mock=False, keithley=k)
    try:
        await _feed(broker, "Т1 Криостат верх", 4.5)
        await asyncio.sleep(1.5)
        await mgr.request_run(0.5, 40.0, 1.0)
        assert mgr.state == SafetyState.RUNNING

        result = await mgr.emergency_off()

        assert result["ok"] is False
        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"emergency_off raise must latch FAULT, got {mgr.state}"
        )
        assert mgr.state != SafetyState.SAFE_OFF
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 10. Cannot start from FAULT_LATCHED
# ---------------------------------------------------------------------------


async def test_cannot_run_from_fault():
    mgr, broker = await _make_manager()
    try:
        await mgr._fault("Test fault")
        result = await mgr.request_run(0.5, 40.0, 1.0)
        assert result["ok"] is False
        assert "FAULT" in result["error"]
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 11. SafetyBroker overflow triggers FAULT
# ---------------------------------------------------------------------------


async def test_broker_overflow_triggers_fault():
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=None, mock=True)
    mgr._config.max_safety_backlog = 2
    mgr._config.cooldown_before_rearm_s = 0.1
    await mgr.start()

    try:
        q = mgr._queue
        assert q is not None and q.maxsize > 0, "safety subscriber queue must be bounded"

        # Fill the safety subscriber queue to capacity *synchronously* — with no
        # await between puts, the manager's consumer task cannot drain it. Then
        # one publish: broker.publish() checks queue.full() before any await and
        # invokes the overflow callback -> SafetyManager._fault(). This makes the
        # overflow deterministic instead of timing-dependent.
        for _ in range(q.maxsize):
            q.put_nowait(
                Reading.now(channel="CHfill", value=0.0, unit="K", instrument_id="test")
            )
        await broker.publish(
            Reading.now(channel="CHoverflow", value=1.0, unit="K", instrument_id="test")
        )

        assert mgr.state == SafetyState.FAULT_LATCHED, (
            f"SafetyBroker overflow must latch FAULT_LATCHED, got {mgr.state}"
        )
        assert "overflow" in mgr.fault_reason.lower(), (
            f"fault_reason must name the overflow cause, got {mgr.fault_reason!r}"
        )
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 12. Keithley required in non-mock mode
# ---------------------------------------------------------------------------


async def test_keithley_required_non_mock():
    broker = SafetyBroker()
    mgr = SafetyManager(broker, keithley_driver=None, mock=False)
    mgr._config.require_keithley_for_run = True
    await mgr.start()
    try:
        result = await mgr.request_run(0.5, 40.0, 1.0)
        assert result["ok"] is False
        assert "Keithley" in result.get("error", "") or "подключён" in result.get("error", "")
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 13. get_status returns correct info
# ---------------------------------------------------------------------------


async def test_get_status():
    mgr, broker = await _make_manager()
    try:
        status = mgr.get_status()
        assert status["state"] == "safe_off"
        assert status["mock"] is True
        assert "fault_reason" in status
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 14. Event history recorded
# ---------------------------------------------------------------------------


async def test_event_history():
    mgr, broker = await _make_manager()
    try:
        await _feed(broker, "Т1 Криостат верх", 4.5)
        await asyncio.sleep(1.5)
        events = mgr.get_events()
        assert len(events) > 0
        assert events[-1].to_state == SafetyState.READY
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# 15. Interlock trip goes through SafetyManager
# ---------------------------------------------------------------------------


async def test_interlock_trip_causes_fault():
    k = _mock_keithley()
    mgr, broker = await _make_manager(mock=False, keithley=k)
    try:
        await _feed(broker, "Т1 Криостат верх", 4.5)
        await asyncio.sleep(1.5)
        await mgr.request_run(0.5, 40.0, 1.0)
        assert mgr.state == SafetyState.RUNNING

        await mgr.on_interlock_trip("overheat", "Т1 Криостат верх", 400.0)
        assert mgr.state == SafetyState.FAULT_LATCHED
        k.emergency_off.assert_called()
    finally:
        await mgr.stop()


# ---------------------------------------------------------------------------
# Phase-2d-A1 regression tests
# ---------------------------------------------------------------------------


async def test_fault_hardware_shutdown_completes_under_cancellation():
    """F2 regression: _fault() hardware shutdown must complete even if
    the calling coroutine is cancelled during the await."""
    emergency_off_calls = []
    shutdown_event = asyncio.Event()

    async def slow_emergency_off(channel=None):
        await asyncio.sleep(0.05)
        emergency_off_calls.append("done")
        shutdown_event.set()

    k = _mock_keithley()
    k.emergency_off.side_effect = slow_emergency_off

    broker = SafetyBroker()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)

    fault_task = asyncio.create_task(sm._fault("test cancellation"))
    await asyncio.sleep(0.01)
    fault_task.cancel()

    try:
        await fault_task
    except asyncio.CancelledError:
        pass

    # Wait briefly for shielded task to finish if still running
    await asyncio.sleep(0.1)

    assert shutdown_event.is_set(), (
        "emergency_off did not complete when _fault() was cancelled — "
        "F2 regression: hardware shutdown is not shielded from cancellation"
    )
    assert emergency_off_calls == ["done"]
    assert sm._state == SafetyState.FAULT_LATCHED


async def test_run_permitted_state_is_actively_monitored():
    """F1 regression: _run_checks() must evaluate stale/rate/heartbeat
    in RUN_PERMITTED state, not just RUNNING."""
    import re

    broker = SafetyBroker()
    sm = SafetyManager(broker, keithley_driver=None, mock=True)

    sm._state = SafetyState.RUN_PERMITTED
    stale_ts = time.monotonic() - 100.0
    sm._latest["Т1 Криостат верх"] = (stale_ts, 77.0, "ok")
    sm._config.critical_channels = [re.compile(r"Т1 .*")]
    sm._config.stale_timeout_s = 10.0

    await sm._run_checks()

    assert sm._state == SafetyState.FAULT_LATCHED, (
        f"Stale critical channel in RUN_PERMITTED must transition to FAULT_LATCHED, "
        f"got {sm._state}. F1 regression: monitoring disabled during source start"
    )
    # fault_reason must contain the exact stale channel name — prod format is
    # "Устаревшие данные канала {ch}" (safety_manager.py:951).
    # The weak "or Устаревшие" branch is intentionally removed: a generic stale
    # message without the channel name would pass the old check but miss a
    # regression where the wrong channel (or no channel) is reported.
    assert "Т1 Криостат верх" in sm._fault_reason, (
        f"fault_reason must name the stale channel 'Т1 Криостат верх', got: {sm._fault_reason!r}"
    )


async def test_rate_fault_latches_within_35s_at_deployed_2s_poll():
    """HI-1 regression: a 10 K/min ramp at the deployed 2.0 s poll must latch a
    rate FAULT within ~35 s of data — not after a ~120 s dead-window.

    Feeds 2 s-spaced readings directly into the SafetyManager's rate estimator
    with controlled timestamps (same time-injection approach as the other rate
    tests — no sleeping) and keeps _latest fresh so stale checks don't fire.
    """
    import re

    broker = SafetyBroker()
    sm = SafetyManager(broker, keithley_driver=None, mock=True)
    sm._config.critical_channels = [re.compile(r"Т1 .*")]
    sm._config.stale_timeout_s = 10.0

    channel = "Т1 Криостат верх"
    sm._state = SafetyState.RUNNING

    t0 = 1_000_000.0
    ramp_per_sec = 10.0 / 60.0  # 10 K/min, twice the 5 K/min limit

    fault_at_s: float | None = None
    for i in range(18):  # 18 samples × 2 s = 34 s of simulated data
        t = t0 + 2.0 * i
        sm._rate_estimator.push(channel, t, 80.0 + ramp_per_sec * (t - t0))
        sm._latest[channel] = (time.monotonic(), 80.0, "ok")  # always fresh
        await sm._run_checks()
        if sm._state == SafetyState.FAULT_LATCHED:
            fault_at_s = 2.0 * i
            break

    assert fault_at_s is not None, (
        "10 K/min ramp produced no rate FAULT within 34 s of 2 s-spaced data — "
        "HI-1 dead-window: the dT/dt gate cannot arm at the deployed poll rate"
    )
    assert fault_at_s <= 35.0
    assert "Rate limit exceeded" in sm._fault_reason, (
        f"fault_reason must be the rate-limit fault, got: {sm._fault_reason!r}"
    )


def test_load_config_fails_on_missing_file(tmp_path):
    """C.2 regression: missing safety.yaml must be startup-fatal."""
    sm = SafetyManager(SafetyBroker(), mock=True)
    with pytest.raises(SafetyConfigError, match="not found"):
        sm.load_config(tmp_path / "nonexistent.yaml")


def test_load_config_fails_on_empty_critical_channels(tmp_path):
    """C.2 regression: empty critical_channels must be startup-fatal."""
    cfg = tmp_path / "safety.yaml"
    cfg.write_text("critical_channels: []\nstale_timeout_s: 10.0\n")
    sm = SafetyManager(SafetyBroker(), mock=True)
    with pytest.raises(SafetyConfigError, match="no critical_channels"):
        sm.load_config(cfg)


def test_load_config_fails_on_all_invalid_regex(tmp_path):
    """C.2 regression: all-invalid regex must be startup-fatal."""
    cfg = tmp_path / "safety.yaml"
    cfg.write_text("critical_channels:\n  - '[invalid(regex'\nstale_timeout_s: 10.0\n")
    sm = SafetyManager(SafetyBroker(), mock=True)
    with pytest.raises(SafetyConfigError, match="invalid.*regex"):
        sm.load_config(cfg)


def test_load_config_succeeds_with_valid_config(tmp_path):
    """Positive case: valid config loads correctly."""
    cfg = tmp_path / "safety.yaml"
    cfg.write_text(
        "critical_channels:\n"
        "  - 'Т1 .*'\n"
        "  - 'Т7 .*'\n"
        "stale_timeout_s: 10.0\n"
        "heartbeat_timeout_s: 15.0\n"
    )
    sm = SafetyManager(SafetyBroker(), mock=True)
    sm.load_config(cfg)
    assert len(sm._config.critical_channels) == 2
    # Verify actual pattern strings loaded correctly
    pattern_strings = [p.pattern for p in sm._config.critical_channels]
    assert "Т1 .*" in pattern_strings, f"Expected 'Т1 .*' in patterns, got {pattern_strings}"
    assert "Т7 .*" in pattern_strings, f"Expected 'Т7 .*' in patterns, got {pattern_strings}"
    # Verify numeric timeout values were parsed (not just defaulted)
    assert sm._config.stale_timeout_s == 10.0, (
        f"stale_timeout_s must be 10.0, got {sm._config.stale_timeout_s}"
    )
    assert sm._config.heartbeat_timeout_s == 15.0, (
        f"heartbeat_timeout_s must be 15.0, got {sm._config.heartbeat_timeout_s}"
    )


def test_safety_config_error_is_runtime_error_subclass():
    """A.4.1: SafetyConfigError must be catchable as RuntimeError."""
    err = SafetyConfigError("test message")
    assert isinstance(err, RuntimeError)
    assert isinstance(err, SafetyConfigError)
    assert str(err) == "test message"


def test_load_config_fails_on_non_list_critical_channels(tmp_path):
    """A.4.1 residual: critical_channels: 123 (not a list) must raise SafetyConfigError."""
    cfg = tmp_path / "safety.yaml"
    cfg.write_text("critical_channels: 123\n")
    sm = SafetyManager(SafetyBroker(), mock=True)
    with pytest.raises(SafetyConfigError, match="must be a list"):
        sm.load_config(cfg)


def test_load_config_fails_on_non_string_pattern(tmp_path):
    """A.4.1 residual: critical_channels: [123] (non-string) must raise SafetyConfigError."""
    cfg = tmp_path / "safety.yaml"
    cfg.write_text("critical_channels:\n  - 123\n")
    sm = SafetyManager(SafetyBroker(), mock=True)
    with pytest.raises(SafetyConfigError, match="invalid.*regex"):
        sm.load_config(cfg)


def test_load_config_fails_on_non_numeric_timeout(tmp_path):
    """A.4.1 residual: non-numeric stale_timeout_s must raise SafetyConfigError."""
    cfg = tmp_path / "safety.yaml"
    cfg.write_text("critical_channels:\n  - 'Т1 .*'\nstale_timeout_s: 'not_a_number'\n")
    sm = SafetyManager(SafetyBroker(), mock=True)
    with pytest.raises(SafetyConfigError, match="invalid config value"):
        sm.load_config(cfg)


def test_load_config_fails_on_non_dict_source_limits(tmp_path):
    """A.4.1 residual: non-mapping source_limits must raise SafetyConfigError."""
    cfg = tmp_path / "safety.yaml"
    cfg.write_text("critical_channels:\n  - 'Т1 .*'\nsource_limits: 'not_a_dict'\n")
    sm = SafetyManager(SafetyBroker(), mock=True)
    with pytest.raises(SafetyConfigError, match="invalid config value"):
        sm.load_config(cfg)


def test_load_config_fails_on_non_numeric_source_limit_value(tmp_path):
    """A.4.1 residual: non-numeric source limit must raise SafetyConfigError."""
    cfg = tmp_path / "safety.yaml"
    cfg.write_text("critical_channels:\n  - 'Т1 .*'\nsource_limits:\n  max_power_w: [1, 2, 3]\n")
    sm = SafetyManager(SafetyBroker(), mock=True)
    with pytest.raises(SafetyConfigError, match="invalid config value"):
        sm.load_config(cfg)


async def test_fault_writes_machine_event_to_operator_log():
    """H.6: _fault() must emit a machine event via fault_log_callback."""
    log_calls = []

    async def fake_log_callback(source, message, channel="", value=0.0):
        log_calls.append({"source": source, "message": message, "channel": channel})

    broker = SafetyBroker()
    sm = SafetyManager(broker, mock=True, fault_log_callback=fake_log_callback)

    await sm._fault("test reason", channel="Т1 Криостат верх", value=999.0)

    assert len(log_calls) == 1
    assert log_calls[0]["source"] == "safety_manager"
    assert "test reason" in log_calls[0]["message"]
    assert log_calls[0]["channel"] == "Т1 Криостат верх"


async def test_fault_continues_if_log_callback_raises():
    """H.6: _fault() must not propagate if fault_log_callback fails."""

    async def broken_callback(**kwargs):
        raise RuntimeError("log write failed")

    broker = SafetyBroker()
    sm = SafetyManager(broker, mock=True, fault_log_callback=broken_callback)

    await sm._fault("test")  # must not raise
    assert sm._state == SafetyState.FAULT_LATCHED


async def test_fault_works_without_log_callback():
    """H.6: _fault() must work when fault_log_callback is None (backward compat)."""
    broker = SafetyBroker()
    sm = SafetyManager(broker, mock=True)  # no callback

    await sm._fault("test")
    assert sm._state == SafetyState.FAULT_LATCHED


async def test_keithley_heartbeat_monitored_in_run_permitted():
    """A.3.1: RUN_PERMITTED must detect stuck start_source() via
    heartbeat timeout even when _active_sources is empty."""
    import re

    k = _mock_keithley()
    broker = SafetyBroker()
    sm = SafetyManager(broker, keithley_driver=k, mock=False)

    sm._config.critical_channels = [re.compile(r"Т1 .*")]
    sm._config.stale_timeout_s = 60.0
    sm._config.heartbeat_timeout_s = 0.5

    now = time.monotonic()
    sm._latest["Т1 Криостат верх"] = (now, 77.0, "ok")

    sm._state = SafetyState.RUN_PERMITTED
    sm._run_permitted_since = now - 10.0  # 10s ago, well past 0.5s timeout
    assert not sm._active_sources

    await sm._run_checks()

    assert sm._state == SafetyState.FAULT_LATCHED, (
        "RUN_PERMITTED did not detect stuck start_source() via heartbeat timeout"
    )


# ---------------------------------------------------------------------------
# Jules review: cancellation shielding on post-fault paths
# ---------------------------------------------------------------------------


async def test_fault_log_callback_survives_outer_cancellation():
    """Jules: _fault_log_callback must complete even if outer _fault()
    is cancelled after hardware shutdown."""
    callback_started = asyncio.Event()
    callback_completed = asyncio.Event()

    async def slow_callback(*, source, message, channel, value):
        callback_started.set()
        await asyncio.sleep(0.1)
        callback_completed.set()

    broker = SafetyBroker()
    sm = SafetyManager(broker, mock=True, fault_log_callback=slow_callback)

    fault_task = asyncio.create_task(sm._fault("test cancellation", channel="smua", value=1.0))
    await asyncio.wait_for(callback_started.wait(), timeout=2.0)
    fault_task.cancel()

    try:
        await fault_task
    except asyncio.CancelledError:
        pass

    await asyncio.sleep(0.2)  # allow shielded task to finish

    assert callback_completed.is_set(), (
        "Cancellation of _fault() swallowed the shielded post-mortem log callback"
    )


async def test_safe_off_fault_latched_shields_emergency_off():
    """Jules: _safe_off's _ensure_output_off must complete even if
    the outer task is cancelled while fault is latched."""
    off_started = asyncio.Event()
    off_completed = asyncio.Event()

    async def slow_emergency_off(channel=None):
        off_started.set()
        await asyncio.sleep(0.1)
        off_completed.set()

    k = _mock_keithley()
    k.emergency_off.side_effect = slow_emergency_off

    broker = SafetyBroker()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    sm._state = SafetyState.FAULT_LATCHED

    task = asyncio.create_task(sm._safe_off("test", channels={"smua"}))
    await asyncio.wait_for(off_started.wait(), timeout=2.0)
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    await asyncio.sleep(0.2)

    assert off_completed.is_set(), "Cancellation of _safe_off swallowed shielded _ensure_output_off"


# NOTE: a source-grep "regression lock" for the asyncio.shield(log_task) call
# used to live here. Removed in cycle 5 — it was false confidence (a comment
# would satisfy it). The shield is proven behaviorally by
# test_fault_log_callback_survives_outer_cancellation and
# test_fault_log_callback_runs_even_if_publish_fails below.


async def test_fault_log_callback_runs_even_if_publish_fails():
    """Jules R2 Q1: callback must execute even if publish raises."""
    callback_invoked = asyncio.Event()

    async def log_callback(*, source, message, channel, value):
        callback_invoked.set()

    broker = SafetyBroker()
    sm = SafetyManager(broker, mock=True, fault_log_callback=log_callback)
    # Make _publish_keithley_channel_states raise
    sm._data_broker = MagicMock()
    sm._data_broker.publish = AsyncMock(side_effect=RuntimeError("broker exploded"))

    await sm._fault("test publish failure", channel="smua", value=1.0)

    assert callback_invoked.is_set(), (
        "Fault log callback NOT invoked — publish failure swallowed it"
    )


async def test_fault_log_callback_runs_before_publish():
    """Jules R2 Q1: fault_log_callback must complete before _publish_keithley_channel_states.

    The production ordering in _fault() is:
      1. _transition (synchronous — schedules _publish_state as a fire-and-forget task)
      2. emergency_off
      3. fault_log_callback  (shielded — MUST complete before next step)
      4. _publish_keithley_channel_states  (best-effort broadcast, step 5 in code)

    _publish_state from _transition fires as a separate fire-and-forget asyncio task,
    so it races independently and is NOT between callback and channel-states publish.
    This test verifies the shielded ordering: callback completes BEFORE
    _publish_keithley_channel_states starts, which is the Jules R2 Q1 contract.

    Uses an ordered event list to record the actual call sequence.
    """
    call_order: list[str] = []
    callback_reached = asyncio.Event()
    channel_states_started = asyncio.Event()

    async def log_callback(*, source, message, channel, value):
        call_order.append("callback")
        callback_reached.set()

    async def slow_channel_states(reason: str, *, fault_channel=None):
        call_order.append("channel_states_start")
        channel_states_started.set()
        await asyncio.sleep(1.0)

    broker = SafetyBroker()
    sm = SafetyManager(broker, mock=True, fault_log_callback=log_callback)
    # Patch _publish_keithley_channel_states (step 5) to be slow — this is the
    # call that must happen AFTER the callback, per the Jules R2 Q1 contract.
    sm._publish_keithley_channel_states = slow_channel_states

    fault_task = asyncio.create_task(
        sm._fault("test cancel during publish", channel="smua", value=1.0)
    )
    # Wait until _publish_keithley_channel_states has actually started
    await asyncio.wait_for(channel_states_started.wait(), timeout=2.0)
    fault_task.cancel()

    try:
        await fault_task
    except asyncio.CancelledError:
        pass

    assert callback_reached.is_set(), "Log callback not invoked before channel-states publish"
    assert "callback" in call_order, f"callback never recorded in call_order: {call_order}"
    assert "channel_states_start" in call_order, f"channel_states never started: {call_order}"
    callback_idx = call_order.index("callback")
    channel_states_idx = call_order.index("channel_states_start")
    assert callback_idx < channel_states_idx, (
        f"fault_log_callback must complete before _publish_keithley_channel_states; "
        f"got order: {call_order}"
    )


@pytest.mark.asyncio
async def test_update_target_updates_runtime_p_target_immediately():
    """HF1 — update_target() is a delayed-update, not a hardware no-op.

    ``update_target()`` writes the new power target to ``runtime.p_target``
    immediately (within the same call). The hardware voltage converges on the
    *next* poll cycle because ``Keithley2604B.read_channels()`` computes
    ``target_v = sqrt(p_target * R)`` and issues SCPI every cycle.

    This design is intentional: slew-rate limiting and compliance checks live
    in the regulation loop and must not be bypassed by a direct SCPI write
    in the safety manager.
    """
    from unittest.mock import MagicMock

    k = _mock_keithley()
    runtime = MagicMock()
    runtime.active = True
    runtime.p_target = 0.1
    k._channels = {"smua": runtime}

    mgr, _ = await _make_manager(keithley=k, mock=True)
    mgr._keithley = k
    mgr._state = SafetyState.RUNNING
    mgr._active_sources = {"smua"}

    result = await mgr.update_target(0.5, channel="smua")

    assert result["ok"] is True
    assert result["p_target"] == 0.5
    assert runtime.p_target == 0.5, "p_target must update immediately in runtime for next poll cycle"
    await mgr.stop()
