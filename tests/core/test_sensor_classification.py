"""Verify sensor channel classification (Phase 2c user report)."""

from __future__ import annotations

import pytest

from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.sensor_diagnostics import (
    SensorDiagnosticsEngine,
    is_physical_sensor,
)


def _descriptor(
    channel_id: str,
    *,
    quantity: ChannelQuantity = ChannelQuantity.TEMPERATURE,
    unit: str = "K",
    role: ChannelRole = ChannelRole.PRIMARY_MEASUREMENT,
) -> ChannelDescriptorV1:
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel_id,
        instrument_id="probe",
        source_key="input.measurement",
        quantity=quantity,
        unit=unit,
        role=role,
        safety_class=(
            ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK
            if role is ChannelRole.SOURCE_READBACK
            else ChannelSafetyClass.OBSERVATIONAL
        ),
        display_group="probes",
        display_name=channel_id,
        visible_by_default=True,
        display_order=0,
        descriptor_revision=1,
    )


def _engine_with_catalog(*descriptors: ChannelDescriptorV1) -> SensorDiagnosticsEngine:
    engine = SensorDiagnosticsEngine()
    # The production constructor receives this immutable snapshot.  Assign it
    # here so these behavioural regressions fail against the pre-fix engine
    # rather than only because that constructor argument did not yet exist.
    engine._channel_catalog = ChannelCatalog(descriptors)
    return engine


# ---------------------------------------------------------------------------
# is_physical_sensor()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "channel",
    [
        "Т1 Криостат верх",
        "Т9 Компрессор вход",
        "Т15",
        "lakeshore/Т11 Холодная плита",
        "lakeshore/temperature",
    ],
)
def test_physical_sensors_included(channel):
    assert is_physical_sensor(channel) is True, f"{channel!r} should be classified as physical sensor"


@pytest.mark.parametrize(
    "channel",
    [
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
        "VSP63D_1/pressure",
        "thyracont/pressure",
    ],
)
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


def test_known_temperature_descriptor_is_accepted_regardless_of_name():
    engine = _engine_with_catalog(_descriptor("cold_head"))

    engine.push("cold_head", 1.0, 4.5)

    assert "cold_head" in engine._buffers


def test_known_source_readback_descriptor_beats_temperature_like_name():
    engine = _engine_with_catalog(
        _descriptor(
            "rack/T1/voltage",
            quantity=ChannelQuantity.VOLTAGE,
            unit="V",
            role=ChannelRole.SOURCE_READBACK,
        )
    )

    engine.push("rack/T1/voltage", 1.0, 0.0)

    assert engine._buffers == {}


@pytest.mark.parametrize(
    ("unit", "role"),
    [
        ("°C", ChannelRole.PRIMARY_MEASUREMENT),
        ("K", ChannelRole.DERIVED),
        ("K", ChannelRole.EVENT),
    ],
)
def test_known_descriptor_requires_kelvin_temperature_measurement_role(unit, role):
    engine = _engine_with_catalog(_descriptor("T1", unit=unit, role=role))

    engine.push("T1", 1.0, 4.5)

    assert engine._buffers == {}


def test_known_descriptor_beats_derived_name_regex():
    engine = _engine_with_catalog(_descriptor("Keithley_1/smua/voltage"))

    engine.push("Keithley_1/smua/voltage", 1.0, 4.5)

    assert "Keithley_1/smua/voltage" in engine._buffers


def test_legacy_temperature_name_without_descriptor_uses_fallback():
    engine = _engine_with_catalog()

    engine.push("T1", 1.0, 4.5)

    assert "T1" in engine._buffers


def test_known_pressure_descriptor_does_not_reach_temperature_scorer():
    engine = _engine_with_catalog(
        _descriptor(
            "VSP63D_1/pressure",
            quantity=ChannelQuantity.PRESSURE,
            unit="mbar",
            role=ChannelRole.PRIMARY_MEASUREMENT,
        )
    )

    for index in range(10):
        engine.push("VSP63D_1/pressure", float(index), 1e-5)
    engine.update()

    assert engine.get_diagnostics() == {}


def test_push_silently_drops_derived_channel():
    """The engine must not even buffer derived channels — health is
    meaningless for them and they would clutter the panel."""
    engine = SensorDiagnosticsEngine()
    engine.push("system/disk_free_gb", 1.0, 50.0)
    engine.push("analytics/safety_state", 1.0, 0.0)
    engine.push("Keithley_1/smua/voltage", 1.0, 0.0)
    engine.update()
    diags = engine.get_diagnostics()
    assert diags == {}, f"Derived channels should not produce diagnostics, got: {list(diags.keys())}"


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
