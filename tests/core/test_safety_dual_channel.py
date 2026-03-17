from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager, SafetyState
from cryodaq.drivers.base import Reading


def _mock_keithley():
    driver = MagicMock()
    driver.connected = True
    driver.emergency_off = AsyncMock()
    driver.stop_source = AsyncMock()
    driver.start_source = AsyncMock()
    return driver


async def _make_manager(*, mock: bool = True, keithley=None):
    broker = SafetyBroker()
    manager = SafetyManager(broker, keithley_driver=keithley, mock=mock)
    manager._config.cooldown_before_rearm_s = 0.1
    manager._config.require_keithley_for_run = not mock
    await manager.start()
    return manager, broker


async def _feed_ready(broker: SafetyBroker) -> None:
    await broker.publish(Reading.now(channel="T1", value=4.5, unit="K", instrument_id="test"))
    await asyncio.sleep(1.2)


async def test_request_run_accepts_smub_channel() -> None:
    manager, broker = await _make_manager()
    try:
        await _feed_ready(broker)
        result = await manager.request_run(0.5, 40.0, 1.0, channel="smub")
        assert result["ok"] is True
        assert result["channel"] == "smub"
        assert manager.state == SafetyState.RUNNING
        assert manager.get_status()["active_channels"] == ["smub"]
    finally:
        await manager.stop()


async def test_dual_channel_runtime_keeps_running_until_last_channel_stops() -> None:
    manager, broker = await _make_manager()
    try:
        await _feed_ready(broker)
        await manager.request_run(0.5, 40.0, 1.0, channel="smua")
        await manager.request_run(0.3, 20.0, 0.5, channel="smub")

        stop_a = await manager.request_stop(channel="smua")
        assert stop_a["ok"] is True
        assert manager.state == SafetyState.RUNNING
        assert manager.get_status()["active_channels"] == ["smub"]

        stop_b = await manager.request_stop(channel="smub")
        assert stop_b["ok"] is True
        assert manager.state == SafetyState.SAFE_OFF
        assert manager.get_status()["active_channels"] == []
    finally:
        await manager.stop()


async def test_channel_scoped_emergency_off_preserves_other_channel() -> None:
    keithley = _mock_keithley()
    manager, broker = await _make_manager(mock=False, keithley=keithley)
    try:
        await _feed_ready(broker)
        await manager.request_run(0.5, 40.0, 1.0, channel="smua")
        await manager.request_run(0.3, 20.0, 0.5, channel="smub")

        result = await manager.emergency_off(channel="smua")

        assert result["ok"] is True
        keithley.emergency_off.assert_awaited_with("smua")
        assert manager.state == SafetyState.RUNNING
        assert manager.get_status()["active_channels"] == ["smub"]
    finally:
        await manager.stop()


async def test_invalid_channel_rejected_early() -> None:
    manager, broker = await _make_manager()
    try:
        await _feed_ready(broker)
        try:
            await manager.request_run(0.5, 40.0, 1.0, channel="smuc")
        except ValueError as exc:
            assert "Invalid Keithley channel" in str(exc)
        else:
            raise AssertionError("Invalid channel was not rejected")
    finally:
        await manager.stop()
