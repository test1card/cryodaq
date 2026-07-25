"""Descriptor-qualified, observational input contract for experiment reports.

This adapter is deliberately separate from the current synchronous report
extractor.  It lets the reviewed descriptor replay reader feed a report without
placing canonical identity in mutable ``Reading.metadata`` or teaching the
reporter vendor/channel naming conventions.  The final extractor cutover can
bind this projection after its bounded async read has settled.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from cryodaq.reporting.data import HistoricalReading, ReportDataset
from cryodaq.storage.broker_replay import DescriptorReplayBatch, DescriptorReplayReading
from cryodaq.storage.descriptor_archive import (
    PersistedChannelEnvelopeError,
    decode_persisted_channel_envelope,
)

MAX_REPORT_DESCRIPTOR_ISSUES = 32


@dataclass(frozen=True, slots=True)
class DescriptorReportProjection:
    """One immutable report input plus bounded integrity evidence."""

    readings: tuple[HistoricalReading, ...]
    alarm_readings: tuple[HistoricalReading, ...]
    complete: bool
    issues: tuple[str, ...]
    issue_overflow: int
    omitted_corrupt_rows: int

    @property
    def grants_control_authority(self) -> bool:
        return False


def _matches_envelope(row: DescriptorReplayReading) -> bool:
    descriptor = row.descriptor
    if descriptor.legacy:
        return (
            descriptor.envelope_json is None
            and descriptor.quantity == "legacy_unknown"
            and descriptor.role == "legacy_unknown"
            and row.instrument_id == descriptor.instrument_id
            and row.channel_id == descriptor.display_name
            and row.unit == descriptor.unit
        )
    if type(descriptor.envelope_json) is not bytes:
        return False
    try:
        envelope = decode_persisted_channel_envelope(descriptor.envelope_json)
    except (TypeError, PersistedChannelEnvelopeError):
        return False
    value = envelope.descriptor
    return descriptor.envelope_json == envelope.canonical_json and (
        row.instrument_id,
        row.channel_id,
        row.unit,
        descriptor.descriptor_hash,
        descriptor.channel_id,
        descriptor.instrument_id,
        descriptor.source_key,
        descriptor.descriptor_revision,
        descriptor.quantity,
        descriptor.unit,
        descriptor.role,
        descriptor.safety_class,
        descriptor.display_group,
        descriptor.display_name,
        descriptor.visible_by_default,
        descriptor.display_order,
    ) == (
        value.instrument_id,
        value.channel_id,
        value.unit,
        value.descriptor_hash,
        value.channel_id,
        value.instrument_id,
        value.source_key,
        value.descriptor_revision,
        value.quantity.value,
        value.unit,
        value.role.value,
        value.safety_class.value,
        value.display_group,
        value.display_name,
        value.visible_by_default,
        value.display_order,
    )


def _sort_key(reading: HistoricalReading) -> tuple[object, ...]:
    descriptor = reading.descriptor
    if descriptor is None or descriptor.legacy:
        return (
            1,
            "legacy",
            2**31 - 1,
            reading.channel,
            reading.channel,
            "",
            reading.timestamp,
            reading.instrument_id,
        )
    return (
        0,
        descriptor.display_group,
        descriptor.display_order,
        descriptor.display_name,
        descriptor.channel_id,
        descriptor.descriptor_hash,
        reading.timestamp,
        reading.instrument_id,
    )


def project_descriptor_replay(batch: DescriptorReplayBatch) -> DescriptorReportProjection:
    """Validate and deterministically project one replay batch for reporting.

    Present-but-corrupt descriptor identity is omitted and reported.  Only an
    already explicit ``legacy_unknown`` replay row receives legacy treatment.
    """

    if type(batch) is not DescriptorReplayBatch:
        raise TypeError("batch must be exactly DescriptorReplayBatch")
    issues = [f"{item.code.value}:{item.source}" for item in batch.issues]
    overflow = batch.issue_overflow
    omitted = 0
    projected: list[HistoricalReading] = []
    for row in batch.readings:
        if type(row) is not DescriptorReplayReading or not _matches_envelope(row):
            omitted += 1
            issue = "descriptor_projection_corrupt:replay_adapter"
            if len(issues) < MAX_REPORT_DESCRIPTOR_ISSUES:
                issues.append(issue)
            else:
                overflow += 1
            continue
        descriptor = row.descriptor
        projected.append(
            HistoricalReading(
                timestamp=row.timestamp,
                instrument_id=row.instrument_id,
                channel=row.channel_id,
                value=float("nan") if row.value is None else row.value,
                unit=row.unit,
                status=row.status,
                descriptor=descriptor,
                legacy=descriptor.legacy,
            )
        )
    readings = tuple(sorted(projected, key=_sort_key))
    alarm_readings = tuple(
        row
        for row in readings
        if (row.descriptor is not None and not row.descriptor.legacy and row.descriptor.role == "event")
        or (row.legacy and row.channel.startswith("alarm/"))
    )
    return DescriptorReportProjection(
        readings=readings,
        alarm_readings=alarm_readings,
        complete=batch.complete and omitted == 0,
        issues=tuple(issues[:MAX_REPORT_DESCRIPTOR_ISSUES]),
        issue_overflow=overflow,
        omitted_corrupt_rows=omitted,
    )


def bind_descriptor_projection(dataset: ReportDataset, projection: DescriptorReportProjection) -> ReportDataset:
    """Return a dataset with one descriptor projection as its sole data truth."""

    if type(dataset) is not ReportDataset or type(projection) is not DescriptorReportProjection:
        raise TypeError("report descriptor binding requires exact contract values")
    issues = projection.issues
    if projection.issue_overflow:
        issues = (*issues, f"issue_overflow:{projection.issue_overflow}")
    return replace(
        dataset,
        readings=list(projection.readings),
        alarm_readings=list(projection.alarm_readings),
        descriptor_complete=projection.complete,
        descriptor_issues=issues,
    )


__all__ = [
    "MAX_REPORT_DESCRIPTOR_ISSUES",
    "DescriptorReportProjection",
    "bind_descriptor_projection",
    "project_descriptor_replay",
]
