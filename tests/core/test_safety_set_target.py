"""Tests for SafetyManager.update_target() and update_limits()."""

from __future__ import annotations

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B


async def _make_running(sm: SafetyManager, channel: str = "smua") -> None:
    """Helper: bring SafetyManager to RUNNING with an active channel."""
    result = await sm.request_run(0.5, 40.0, 1.0, channel=channel)
    assert result["ok"], result


# ---------------------------------------------------------------------------
# update_target
# ---------------------------------------------------------------------------


async def test_update_target_active_channel() -> None:
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    await _make_running(sm, "smua")

    result = await sm.update_target(0.8, channel="smua")
    assert result["ok"]
    assert result["p_target"] == 0.8
    assert k._channels["smua"].p_target == 0.8

    await k.disconnect()


async def test_update_target_exceeds_max_power() -> None:
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    await _make_running(sm, "smua")

    result = await sm.update_target(999.0, channel="smua")
    assert not result["ok"]
    assert "exceeds" in result["error"]

    await k.disconnect()


async def test_update_target_inactive_channel() -> None:
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)

    result = await sm.update_target(0.5, channel="smua")
    assert not result["ok"]
    assert "not active" in result["error"]

    await k.disconnect()


async def test_update_target_fault_latched() -> None:
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    await _make_running(sm, "smua")

    # Force fault
    await sm._fault("test fault")
    assert sm.state == SafetyState.FAULT_LATCHED

    result = await sm.update_target(0.5, channel="smua")
    assert not result["ok"]
    assert "FAULT" in result["error"]

    await k.disconnect()


async def test_update_target_zero_rejected() -> None:
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    await _make_running(sm, "smua")

    result = await sm.update_target(0.0, channel="smua")
    assert not result["ok"]
    assert "must be > 0" in result["error"]

    await k.disconnect()


# ---------------------------------------------------------------------------
# update_limits
# ---------------------------------------------------------------------------


async def test_update_limits_v_comp() -> None:
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    await _make_running(sm, "smua")

    result = await sm.update_limits(channel="smua", v_comp=20.0)
    assert result["ok"]
    assert result["v_comp"] == 20.0
    assert k._channels["smua"].v_comp == 20.0

    await k.disconnect()


async def test_update_limits_i_comp() -> None:
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    await _make_running(sm, "smua")

    result = await sm.update_limits(channel="smua", i_comp=0.5)
    assert result["ok"]
    assert result["i_comp"] == 0.5
    assert k._channels["smua"].i_comp == 0.5

    await k.disconnect()


async def test_update_limits_exceeds_max_voltage() -> None:
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    await _make_running(sm, "smua")

    result = await sm.update_limits(channel="smua", v_comp=999.0)
    assert not result["ok"]
    assert "exceeds" in result["error"]

    await k.disconnect()


async def test_update_limits_exceeds_max_current() -> None:
    broker = SafetyBroker()
    k = Keithley2604B("k", "USB::MOCK", mock=True)
    await k.connect()
    sm = SafetyManager(broker, keithley_driver=k, mock=True)
    await _make_running(sm, "smua")

    result = await sm.update_limits(channel="smua", i_comp=999.0)
    assert not result["ok"]
    assert "exceeds" in result["error"]

    await k.disconnect()
