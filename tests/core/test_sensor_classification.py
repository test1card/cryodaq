"""Verify sensor channel classification (Phase 2c user report)."""
from __future__ import annotations

import pytest

from cryodaq.core.sensor_diagnostics import (
    SensorDiagnosticsEngine,
    is_physical_sensor,
)


# ---------------------------------------------------------------------------
# is_physical_sensor()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("channel", [
    "Т1 Криостат верх",
    "Т9 Компрессор вход",
    "Т15",
    "lakeshore/Т11 Холодная плита",
    "VSP63D_1/pressure",
    "thyracont/pressure",
])
def test_physical_sensors_included(channel):
    assert is_physical_sensor(channel) is True, (
        f"{channel!r} should be classified as physical sensor"
    )


@pytest.mark.parametrize("channel", [
    "system/disk_free_gb",
    "system/heartbeat",
    "analytics/safety_state",
    "analytics/keithley_channel_state/smua",
    "analytics/alarm_count",
    "Keithley_1/smua/voltage",
    "Keithley_1/smua/current",
    "Keithley_1/smua/power",
    "Keithley_1/smua/resistance",
    "Keithley_1/smub/voltage",
    "Keithley_1/smub/power",
])
def test_derived_channels_excluded(channel):
    assert is_physical_sensor(channel) is False, (
        f"{channel!r} is derived/computed, must NOT be classified as physical sensor"
    )


def test_empty_channel_id_returns_false():
    assert is_physical_sensor("") is False


def test_arbitrary_string_returns_false():
    """Strings that match neither pattern set default to False (conservative)."""
    assert is_physical_sensor("random_string") is False
    assert is_physical_sensor("foo/bar/baz") is False


# ---------------------------------------------------------------------------
# SensorDiagnosticsEngine.push() filters at ingest
# ---------------------------------------------------------------------------

def test_push_silently_drops_derived_channel():
    """The engine must not even buffer derived channels — health is
    meaningless for them and they would clutter the panel."""
    engine = SensorDiagnosticsEngine()
    engine.push("system/disk_free_gb", 1.0, 50.0)
    engine.push("analytics/safety_state", 1.0, 0.0)
    engine.push("Keithley_1/smua/voltage", 1.0, 0.0)
    engine.update()
    diags = engine.get_diagnostics()
    assert diags == {}, (
        f"Derived channels should not produce diagnostics, got: {list(diags.keys())}"
    )


def test_push_keeps_physical_channels():
    """Physical sensors must continue to flow through normally."""
    engine = SensorDiagnosticsEngine()
    for i in range(50):
        engine.push("Т1 Криостат верх", float(i), 4.5 + 0.001 * i)
    engine.update()
    diags = engine.get_diagnostics()
    assert "Т1 Криостат верх" in diags


def test_summary_count_excludes_derived():
    """The Header count (16✓ 1⚠ 20✗) was inflated by 20 derived '0' rows.
    After Phase 2c those rows aren't even in the engine."""
    engine = SensorDiagnosticsEngine()

    # Real physical channels
    for i in range(60):
        engine.push("Т1 Криостат верх", float(i), 4.5)
    # Derived junk that used to inflate the count
    for i in range(60):
        engine.push("Keithley_1/smua/voltage", float(i), 0.0)
        engine.push("system/disk_free_gb", float(i), 50.0)
        engine.push("analytics/safety_state", float(i), 0.0)

    engine.update()
    summary = engine.get_summary()
    assert summary.total_channels == 1, (
        f"Summary should reflect only physical sensors, got total={summary.total_channels}"
    )
