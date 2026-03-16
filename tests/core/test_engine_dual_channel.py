from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cryodaq.engine import _run_keithley_command


async def test_engine_passes_channel_to_start() -> None:
    safety_manager = AsyncMock()
    safety_manager.request_run.return_value = {"ok": True}

    await _run_keithley_command(
        "keithley_start",
        {"channel": "smub", "p_target": 0.5, "v_comp": 40.0, "i_comp": 1.0},
        safety_manager,
    )

    safety_manager.request_run.assert_awaited_once_with(0.5, 40.0, 1.0, channel="smub")


async def test_engine_passes_channel_to_stop_and_emergency() -> None:
    safety_manager = AsyncMock()
    safety_manager.request_stop.return_value = {"ok": True}
    safety_manager.emergency_off.return_value = {"ok": True}

    await _run_keithley_command("keithley_stop", {"channel": "smua"}, safety_manager)
    await _run_keithley_command("keithley_emergency_off", {"channel": "smub"}, safety_manager)

    safety_manager.request_stop.assert_awaited_once_with(channel="smua")
    safety_manager.emergency_off.assert_awaited_once_with(channel="smub")


async def test_engine_rejects_invalid_channel() -> None:
    with pytest.raises(ValueError, match="Invalid Keithley channel"):
        await _run_keithley_command("keithley_start", {"channel": "smuc"}, AsyncMock())
