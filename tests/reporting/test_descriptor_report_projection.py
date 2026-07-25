from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.reporting.data import ReportDataset
from cryodaq.reporting.descriptor_projection import (
    bind_descriptor_projection,
    project_descriptor_replay,
)
from cryodaq.reporting.generator import ReportGenerator
from cryodaq.storage.archive_reader import BoundedReadIssue, BoundedReadIssueCode
from cryodaq.storage.broker_replay import DescriptorReplayBatch, DescriptorReplayReading
from cryodaq.storage.descriptor_archive import (
    ResolvedStorageDescriptor,
    resolve_legacy_descriptor,
)


def _descriptor(
    channel_id: str,
    *,
    source_key: str,
    quantity: ChannelQuantity,
    unit: str,
    display_group: str,
    display_name: str,
    display_order: int,
    role: ChannelRole = ChannelRole.PRIMARY_MEASUREMENT,
    visible: bool = True,
) -> ChannelDescriptorV1:
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel_id,
        instrument_id="instrument-a",
        source_key=source_key,
        quantity=quantity,
        unit=unit,
        role=role,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group=display_group,
        display_name=display_name,
        visible_by_default=visible,
        display_order=display_order,
        descriptor_revision=3,
    )


def _resolved(value: ChannelDescriptorV1) -> ResolvedStorageDescriptor:
    envelope = PersistedChannelEnvelopeV1.from_descriptor(value).canonical_json
    return ResolvedStorageDescriptor(
        descriptor_hash=value.descriptor_hash,
        channel_id=value.channel_id,
        instrument_id=value.instrument_id,
        source_key=value.source_key,
        descriptor_revision=value.descriptor_revision,
        quantity=value.quantity.value,
        unit=value.unit,
        role=value.role.value,
        safety_class=value.safety_class.value,
        display_group=value.display_group,
        display_name=value.display_name,
        visible_by_default=value.visible_by_default,
        display_order=value.display_order,
        envelope_json=envelope,
        legacy=False,
    )


def _row(
    descriptor: ResolvedStorageDescriptor,
    *,
    second: int,
    value: float | None = 1.0,
) -> DescriptorReplayReading:
    return DescriptorReplayReading(
        timestamp=datetime(2026, 7, 12, 12, 0, second, tzinfo=UTC),
        instrument_id=descriptor.instrument_id,
        channel_id=descriptor.channel_id,
        value=value,
        unit=descriptor.unit,
        status="ok",
        descriptor=descriptor,
    )


def _batch(*rows: DescriptorReplayReading) -> DescriptorReplayBatch:
    return DescriptorReplayBatch(
        readings=tuple(rows),
        complete=True,
        truncated=False,
        issues=(),
        issue_overflow=0,
        discovered_channels=tuple(sorted({row.channel_id for row in rows})),
        rows_examined=len(rows),
        rows_dropped_by_caps=0,
        retained_encoded_bytes=1024,
    )


def _dataset() -> ReportDataset:
    return ReportDataset(
        metadata={
            "experiment": {"custom_fields": {}},
            "template": {},
        }
    )


def test_projection_preserves_exact_descriptor_envelope_and_display_order() -> None:
    later_group = _resolved(
        _descriptor(
            "channel-z",
            source_key="input.z.temperature",
            quantity=ChannelQuantity.TEMPERATURE,
            unit="K",
            display_group="B group",
            display_name="First by time",
            display_order=1,
        )
    )
    first_group = _resolved(
        _descriptor(
            "channel-a",
            source_key="input.a.temperature",
            quantity=ChannelQuantity.TEMPERATURE,
            unit="K",
            display_group="A group",
            display_name="Second by time",
            display_order=9,
        )
    )
    projection = project_descriptor_replay(_batch(_row(later_group, second=1), _row(first_group, second=2)))

    assert [row.channel for row in projection.readings] == ["channel-a", "channel-z"]
    assert projection.complete is True
    assert projection.grants_control_authority is False
    for reading in projection.readings:
        original = first_group if reading.channel == "channel-a" else later_group
        assert reading.descriptor is original
        assert (
            reading.descriptor.descriptor_hash,
            reading.descriptor.descriptor_revision,
            reading.descriptor.envelope_json,
        ) == (
            original.descriptor_hash,
            original.descriptor_revision,
            original.envelope_json,
        )
        assert reading.grants_control_authority is False


def test_projection_omits_forged_descriptor_and_report_shows_integrity_issue(
    tmp_path: Path,
) -> None:
    valid = _resolved(
        _descriptor(
            "stage",
            source_key="input.stage.temperature",
            quantity=ChannelQuantity.TEMPERATURE,
            unit="K",
            display_group="Cryostat",
            display_name="Stage",
            display_order=1,
        )
    )
    forged = replace(valid, display_name="Forged display authority")
    batch = replace(
        _batch(_row(forged, second=1)),
        issues=(
            BoundedReadIssue(
                code=BoundedReadIssueCode.DESCRIPTOR_HASH_MISSING,
                source="cold-sidecar",
            ),
        ),
    )

    projection = project_descriptor_replay(batch)
    dataset = bind_descriptor_projection(_dataset(), projection)
    document = ReportGenerator(tmp_path)._build_document(
        dataset,
        tmp_path / "assets",
        ("experiment_metadata_section",),
    )
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)

    assert projection.readings == ()
    assert projection.omitted_corrupt_rows == 1
    assert projection.complete is False
    assert "идентичность дескрипторов не подтверждена" in text
    assert "descriptor_projection_corrupt:replay_adapter" in text
    assert "descriptor_hash_missing:cold-sidecar" in text


def test_generator_sections_use_descriptor_semantics_and_bound_legacy_fallback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    temperature_named_pressure = _resolved(
        _descriptor(
            "vacuum/pressure",
            source_key="input.stage.temperature",
            quantity=ChannelQuantity.TEMPERATURE,
            unit="K",
            display_group="Thermal",
            display_name="Stage temperature",
            display_order=4,
        )
    )
    pressure_named_power = _resolved(
        _descriptor(
            "heater/power",
            source_key="input.vacuum.pressure",
            quantity=ChannelQuantity.PRESSURE,
            unit="mbar",
            display_group="Vacuum",
            display_name="Main chamber",
            display_order=2,
        )
    )
    power_neutral_name = _resolved(
        _descriptor(
            "source-readback",
            source_key="input.heater.power",
            quantity=ChannelQuantity.POWER,
            unit="W",
            display_group="Sources",
            display_name="Heater A power",
            display_order=1,
        )
    )
    hidden_power = _resolved(
        _descriptor(
            "hidden/power",
            source_key="input.hidden.power",
            quantity=ChannelQuantity.POWER,
            unit="W",
            display_group="Sources",
            display_name="Hidden power",
            display_order=0,
            visible=False,
        )
    )
    legacy_descriptor = resolve_legacy_descriptor("legacy-meter", "legacy/smua/power", "W")
    projection = project_descriptor_replay(
        _batch(
            _row(pressure_named_power, second=1, value=0.001),
            _row(temperature_named_pressure, second=2, value=4.2),
            _row(power_neutral_name, second=3, value=2.5),
            _row(hidden_power, second=4, value=99.0),
            DescriptorReplayReading(
                timestamp=datetime(2026, 7, 12, 12, 0, 5, tzinfo=UTC),
                instrument_id=legacy_descriptor.instrument_id,
                channel_id=legacy_descriptor.display_name,
                value=0.5,
                unit=legacy_descriptor.unit,
                status="ok",
                descriptor=legacy_descriptor,
            ),
        )
    )
    dataset = bind_descriptor_projection(_dataset(), projection)
    captured: dict[str, tuple[str, ...]] = {}

    def capture(_document, _dataset, _role, title, readings, _path, **_kwargs):
        captured[title] = tuple(row.channel for row in readings)

    monkeypatch.setattr("cryodaq.reporting.sections._add_archived_or_multichannel", capture)
    document = ReportGenerator(tmp_path)._build_document(
        dataset,
        tmp_path / "assets",
        ("cooldown_section", "thermal_section", "pressure_section"),
    )
    table_text = "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)

    assert captured["Температура каналов"] == ("vacuum/pressure",)
    assert captured["Мощность Keithley"] == ("source-readback", "legacy/smua/power")
    assert captured["Давление"] == ("heater/power",)
    assert "Heater A power" in table_text
    assert "Hidden power" not in table_text


def test_event_role_is_alarm_authority_not_channel_prefix() -> None:
    event = _resolved(
        _descriptor(
            "state-neutral",
            source_key="input.state.event",
            quantity=ChannelQuantity.EVENT_STATE,
            unit="state",
            display_group="Events",
            display_name="Interlock state",
            display_order=1,
            role=ChannelRole.EVENT,
        )
    )
    misleading = _resolved(
        _descriptor(
            "alarm/not-an-event",
            source_key="input.stage.temperature",
            quantity=ChannelQuantity.TEMPERATURE,
            unit="K",
            display_group="Thermal",
            display_name="Alarm-prefixed temperature",
            display_order=2,
        )
    )

    projection = project_descriptor_replay(_batch(_row(misleading, second=1), _row(event, second=2)))

    assert [row.channel for row in projection.alarm_readings] == ["state-neutral"]
