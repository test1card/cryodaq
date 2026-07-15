from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.descriptor_transport import (
    DescriptorEnvelopeIssue,
    DescriptorQualifiedReading,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.shell.overlays.multiline_panel import MultiLinePanel
from cryodaq.gui.state.descriptor_store import DescriptorStore, IdentityStatus


def _reading(channel: str, unit: str, *, instrument_id: str = "misleading_vendor") -> Reading:
    return Reading(
        timestamp=datetime(2026, 7, 14, tzinfo=UTC),
        instrument_id=instrument_id,
        channel=channel,
        value=1.25,
        unit=unit,
        status=ChannelStatus.OK,
    )


def _descriptor(
    reading: Reading,
    *,
    quantity: ChannelQuantity,
    role: ChannelRole = ChannelRole.PRIMARY_MEASUREMENT,
    safety_class: ChannelSafetyClass = ChannelSafetyClass.OBSERVATIONAL,
    display_group: str = "generic",
    source_key: str = "adversarial.route",
) -> ChannelDescriptorV1:
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=reading.channel,
        instrument_id=reading.instrument_id,
        source_key=source_key,
        quantity=quantity,
        unit=reading.unit,
        role=role,
        safety_class=safety_class,
        display_group=display_group,
        display_name="Misleading display name",
        visible_by_default=True,
        display_order=0,
        descriptor_revision=1,
    )


def _shell() -> SimpleNamespace:
    return SimpleNamespace(
        _calibration_panel=MagicMock(),
        _conductivity_panel=MagicMock(),
        _keithley_panel=MagicMock(),
        _analytics_view=MagicMock(),
        _multiline_panel=MagicMock(),
        _analytics_temperature_snapshot={},
        _analytics_keithley_snapshot={},
        _multiline_snapshot={},
        _push_analytics=MagicMock(),
    )


def _route(shell: SimpleNamespace, reading: Reading, descriptor: ChannelDescriptorV1) -> None:
    MainWindowV2._dispatch_descriptor_reading(shell, reading, descriptor)  # type: ignore[arg-type]


def test_source_metadata_routes_despite_non_vendor_name_and_voltage_suffix_lie() -> None:
    reading = _reading("vacuum/pressure", "V", instrument_id="LakeShore_looking_name")
    descriptor = _descriptor(
        reading,
        quantity=ChannelQuantity.VOLTAGE,
        role=ChannelRole.SOURCE_READBACK,
        safety_class=ChannelSafetyClass.HAZARDOUS_SOURCE_READBACK,
    )
    shell = _shell()

    _route(shell, reading, descriptor)

    shell._keithley_panel.on_reading.assert_called_once_with(reading)
    assert shell._analytics_keithley_snapshot == {reading.channel: reading}
    shell._push_analytics.assert_not_called()


def test_passive_power_named_like_smu_never_routes_to_source_panel() -> None:
    reading = _reading("Keithley_1/smua/power", "W")
    descriptor = _descriptor(reading, quantity=ChannelQuantity.POWER)
    shell = _shell()

    _route(shell, reading, descriptor)

    shell._keithley_panel.on_reading.assert_not_called()
    shell._conductivity_panel.on_reading.assert_not_called()
    assert shell._analytics_keithley_snapshot == {}


def test_pressure_metadata_wins_over_source_like_name() -> None:
    reading = _reading("Keithley_1/smub/power", "mbar")
    descriptor = _descriptor(
        reading,
        quantity=ChannelQuantity.PRESSURE,
        role=ChannelRole.ENVIRONMENT,
        display_group="source-looking",
    )
    shell = _shell()

    _route(shell, reading, descriptor)

    shell._push_analytics.assert_called_once_with("set_pressure_reading", reading)
    shell._keithley_panel.on_reading.assert_not_called()


def test_quantity_and_display_group_select_temperature_raw_and_multiline_sinks() -> None:
    temperature = _reading("VSP63D_1/pressure", "K")
    raw = _reading("not_a_raw_suffix", "sensor_unit")
    length = _reading("MultiLine_1/length_ch1", "mm", instrument_id="MultiLine_1")
    shell = _shell()

    _route(shell, temperature, _descriptor(temperature, quantity=ChannelQuantity.TEMPERATURE))
    _route(shell, raw, _descriptor(raw, quantity=ChannelQuantity.RAW_SENSOR))
    length_descriptor = _descriptor(
        length,
        quantity=ChannelQuantity.LENGTH,
        display_group="интерферометр",
        source_key="length.1",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
    )
    _route(shell, length, length_descriptor)

    shell._conductivity_panel.on_reading.assert_called_once_with(temperature)
    shell._analytics_view.set_temperature_readings.assert_called_once_with({temperature.channel: temperature})
    shell._calibration_panel.on_reading.assert_called_once_with(raw)
    shell._multiline_panel.on_descriptor_reading.assert_called_once_with(length, length_descriptor)


def test_authoritative_multiline_ingress_bypasses_only_legacy_name_filter() -> None:
    app = QApplication.instance() or QApplication([])
    panel = MultiLinePanel()
    try:
        reading = _reading("MultiLine_1/length_ch1", "mm", instrument_id="MultiLine_1")
        descriptor = _descriptor(
            reading,
            quantity=ChannelQuantity.LENGTH,
            display_group="интерферометр",
            source_key="length.1",
            role=ChannelRole.PRIMARY_MEASUREMENT,
            safety_class=ChannelSafetyClass.OBSERVATIONAL,
        )
        shell = _shell()
        shell._multiline_panel = panel

        _route(shell, reading, descriptor)

        assert panel._states[1].current_value_mm == reading.value
        assert shell._multiline_snapshot == {reading.channel: (reading, descriptor)}

        legacy = _reading("ordinary_legacy_channel", "mm")
        panel.on_reading(legacy)
        assert set(panel._states) == {1}
    finally:
        for timer in panel.findChildren(QTimer):
            timer.stop()
        panel.deleteLater()
        app.processEvents()


def test_missing_or_refused_descriptor_keeps_generic_dispatch_only() -> None:
    reading = _reading("MultiLine_1/length_ch1", "mm", instrument_id="MultiLine_1")
    descriptor = _descriptor(
        reading,
        quantity=ChannelQuantity.LENGTH,
        source_key="length.1",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="интерферометр",
    )
    shell = SimpleNamespace(
        _descriptor_store=DescriptorStore(),
        _dispatch_reading=MagicMock(),
        _dispatch_descriptor_reading=MagicMock(),
        _instrument_panel=None,
    )

    MainWindowV2.dispatch_qualified_reading(
        shell,
        DescriptorQualifiedReading(reading=reading, descriptor=None),  # type: ignore[arg-type]
    )
    MainWindowV2.dispatch_qualified_reading(
        shell,
        DescriptorQualifiedReading(
            reading=reading,
            descriptor=descriptor,
            descriptor_issue=DescriptorEnvelopeIssue.MALFORMED,
        ),
    )

    assert shell._dispatch_reading.call_count == 2
    shell._dispatch_descriptor_reading.assert_not_called()


def test_bare_reading_never_inherits_cached_authoritative_specialist_routing() -> None:
    reading = _reading("MultiLine_1/length_ch1", "mm", instrument_id="MultiLine_1")
    descriptor = _descriptor(
        reading,
        quantity=ChannelQuantity.LENGTH,
        source_key="length.1",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="интерферометр",
    )
    shell = SimpleNamespace(
        _descriptor_store=DescriptorStore(),
        _dispatch_reading=MagicMock(),
        _dispatch_descriptor_reading=MagicMock(),
        _instrument_panel=None,
    )

    MainWindowV2.dispatch_qualified_reading(shell, DescriptorQualifiedReading(reading=reading, descriptor=descriptor))
    shell._dispatch_descriptor_reading.assert_called_once_with(reading, descriptor)
    shell._dispatch_descriptor_reading.reset_mock()

    MainWindowV2.dispatch_qualified_reading(
        shell,
        DescriptorQualifiedReading(reading=reading, descriptor=None),  # type: ignore[arg-type]
    )

    assert shell._descriptor_store.view(reading.channel).identity_status is IdentityStatus.AUTHORITATIVE
    shell._dispatch_descriptor_reading.assert_not_called()


def test_same_t12_id_with_non_manifest_identity_never_routes_as_cold_stage() -> None:
    reading = _reading("Т12", "K", instrument_id="LS218_2")
    canonical = _descriptor(
        reading,
        quantity=ChannelQuantity.TEMPERATURE,
        source_key="input.4.temperature",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.SAFETY_CRITICAL_INPUT,
        display_group="компрессор",
    )
    shell = _shell()
    for adversarial in (
        replace(canonical, instrument_id="LS218_1"),
        replace(canonical, source_key="input.3.temperature"),
        replace(canonical, role=ChannelRole.REFERENCE_MEASUREMENT),
        replace(canonical, safety_class=ChannelSafetyClass.OBSERVATIONAL),
        replace(canonical, display_group="криостат"),
    ):
        _route(shell, reading, adversarial)
    shell._push_analytics.assert_not_called()

    _route(shell, reading, canonical)
    shell._push_analytics.assert_called_once_with("set_cold_temperature_reading", reading)


def test_multiline_like_names_without_manifest_identity_never_route() -> None:
    reading = _reading("MultiLine_1/length_ch1", "mm", instrument_id="MultiLine_1")
    canonical = _descriptor(
        reading,
        quantity=ChannelQuantity.LENGTH,
        source_key="length.1",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="интерферометр",
    )
    shell = _shell()
    for adversarial in (
        replace(canonical, channel_id="ordinary_channel"),
        replace(canonical, instrument_id="MultiLine_2"),
        replace(canonical, source_key="length.2"),
        replace(canonical, role=ChannelRole.REFERENCE_MEASUREMENT),
        replace(canonical, display_group="окружение"),
    ):
        _route(shell, reading, adversarial)
    shell._multiline_panel.on_descriptor_reading.assert_not_called()
    assert shell._multiline_snapshot == {}

    _route(shell, reading, canonical)
    shell._multiline_panel.on_descriptor_reading.assert_called_once_with(reading, canonical)
