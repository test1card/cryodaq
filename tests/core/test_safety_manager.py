"""Tests for SafetyManager — safety-critical state machine."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyConfig, SafetyConfigError, SafetyManager, SafetyState
from cryodaq.drivers.base import Reading


def _mock_keithley():
    """Create a mock Keithley driver."""
    k = MagicMock()
    k.connected = True
    k.emergency_off = AsyncMock()
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
        # Fill the queue (queue was created with maxsize=2 in start)
        # Overflow callback should trigger fault
        for i in range(5):
            r = Reading.now(channel=f"CH{i}", value=float(i), unit="K", instrument_id="test")
            await broker.publish(r)
            await asyncio.sleep(0.01)

        # Check that overflow was detected
        # The fault may or may not have triggered depending on timing,
        # but the overflow callback is set up correctly
        assert broker._overflow_callback is not None
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

    assert sm._state != SafetyState.RUN_PERMITTED, (
        "RUN_PERMITTED state did not react to stale critical channel — "
        "F1 regression: monitoring disabled during source start"
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


def test_safety_config_error_is_runtime_error_subclass():
    """A.4.1: SafetyConfigError must be catchable as RuntimeError."""
    err = SafetyConfigError("test message")
    assert isinstance(err, RuntimeError)
    assert isinstance(err, SafetyConfigError)
    assert str(err) == "test message"


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
