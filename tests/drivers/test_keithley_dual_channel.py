from __future__ import annotations

from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B


async def test_global_emergency_off_clears_both_channels() -> None:
    driver = Keithley2604B("K1", "USB::mock", mock=True)
    await driver.connect()
    await driver.start_source("smua", 0.5, 40.0, 1.0)
    await driver.start_source("smub", 0.3, 20.0, 0.5)

    await driver.emergency_off()

    assert not driver.any_active
    assert driver.active_channels == []
    await driver.disconnect()


async def test_one_channel_stop_does_not_wipe_other_runtime() -> None:
    driver = Keithley2604B("K1", "USB::mock", mock=True)
    await driver.connect()
    await driver.start_source("smua", 0.5, 40.0, 1.0)
    await driver.start_source("smub", 0.3, 20.0, 0.5)

    smub_before = driver._channels["smub"].p_target
    await driver.stop_source("smua")

    assert driver._channels["smub"].active is True
    assert driver._channels["smub"].p_target == smub_before
    await driver.disconnect()
