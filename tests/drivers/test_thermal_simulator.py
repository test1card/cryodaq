"""Behavioral tests for the coupled mock thermal sample."""

from __future__ import annotations

import math

import pytest

from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B
from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S
from cryodaq.drivers.registry import DriverConstructionContext, construct_driver, validate_instrument_entry
from cryodaq.drivers.thermal_simulator import ThermalSampleSimulator


class ManualClock:
    def __init__(self) -> None:
        self.now_s = 0.0

    def __call__(self) -> float:
        return self.now_s

    def advance(self, seconds: float) -> None:
        self.now_s += seconds


def test_thermal_sample_heats_toward_power_equilibrium_and_cools() -> None:
    clock = ManualClock()
    sample = ThermalSampleSimulator(
        bath_temperature_k=4.0,
        thermal_resistance_k_per_w=5.0,
        time_constant_s=2.0,
        clock=clock,
    )

    assert sample.temperature_pair() == (4.0, 4.0)
    sample.set_power(0.2)
    clock.advance(2.0)
    hot_k, cold_k = sample.temperature_pair()
    assert cold_k == 4.0
    assert hot_k - cold_k == pytest.approx(1.0 - math.exp(-1.0))

    sample.set_power(0.0)
    clock.advance(2.0)
    cooled_hot_k, _ = sample.temperature_pair()
    assert 4.0 < cooled_hot_k < hot_k


async def test_registry_drivers_share_power_and_temperature_state() -> None:
    clock = ManualClock()
    sample = ThermalSampleSimulator(
        bath_temperature_k=4.2,
        thermal_resistance_k_per_w=5.0,
        time_constant_s=1.0,
        clock=clock,
    )
    context = DriverConstructionContext(mock=True, thermal_simulator=sample)
    lakeshore_config = validate_instrument_entry(
        {
            "type": "lakeshore_218s",
            "name": "LS",
            "resource": "GPIB0::12::INSTR",
            "channels": {1: "sample.hot", 2: "sample.cold"},
        }
    )
    keithley_config = validate_instrument_entry(
        {
            "type": "keithley_2604b",
            "name": "K",
            "resource": "USB0::0x05E6::0x2604::MOCK00001::INSTR",
        }
    )
    lakeshore = construct_driver(lakeshore_config, context)
    keithley = construct_driver(keithley_config, context)
    assert isinstance(lakeshore, LakeShore218S)
    assert isinstance(keithley, Keithley2604B)

    await lakeshore.connect()
    await keithley.connect()
    baseline = {reading.channel: reading.value for reading in await lakeshore.read_channels()}
    await keithley.start_source("smua", 0.2, 10.0, 0.5)
    clock.advance(5.0)
    source = {reading.channel: reading.value for reading in await keithley.read_channels()}
    heated = {reading.channel: reading.value for reading in await lakeshore.read_channels()}

    assert source["K/smua/power"] == pytest.approx(0.2, abs=1e-6)
    assert heated["sample.cold"] == baseline["sample.cold"]
    assert heated["sample.hot"] - heated["sample.cold"] > 0.9

    await keithley.update_source_target("smua", 0.4)
    clock.advance(1.0)
    hotter = {reading.channel: reading.value for reading in await lakeshore.read_channels()}
    assert hotter["sample.hot"] > heated["sample.hot"]

    await keithley.stop_source("smua")
    assert sample.power_w == 0.0
    clock.advance(2.0)
    cooling = {reading.channel: reading.value for reading in await lakeshore.read_channels()}
    assert cooling["sample.hot"] < hotter["sample.hot"]

    await keithley.disconnect()
    await lakeshore.disconnect()
