from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.engine_wiring.recording_lifecycle_feed import RecordingLifecycleFeed
from cryodaq.operator_snapshot import AvailabilityTruth, RecordingTruth
from cryodaq.storage.channel_descriptors import LiveChannelDescriptorCatalog
from cryodaq.storage.sqlite_writer import SQLiteWriter


@pytest.fixture(autouse=True)
def _allow_test_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")


def _writer(path: Path) -> SQLiteWriter:
    descriptor = ChannelDescriptorV1(
        schema_version=1,
        channel_id="probe.1",
        instrument_id="probe",
        source_key="input.1.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit="K",
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="probes",
        display_name="Probe 1",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=1,
    )
    return SQLiteWriter(path, channel_catalog=LiveChannelDescriptorCatalog(ChannelCatalog((descriptor,))))


def _reading(value: float) -> Reading:
    return Reading(
        timestamp=datetime(2026, 7, 14, 10, tzinfo=UTC),
        instrument_id="probe",
        channel="probe.1",
        value=value,
        unit="K",
        status=ChannelStatus.OK,
        raw=value,
    )


async def _ready(feed: RecordingLifecycleFeed, epoch: str = "acquisition-1") -> None:
    feed.experiment_active(1, "experiment-1", "Cooldown")
    feed.persistence_started(epoch)
    feed.acquisition_running(1, epoch)




class _ObserverHarness:
    """The exact shape Scheduler uses, with its error handling."""

    def __init__(self, feed: RecordingLifecycleFeed) -> None:
        self._persistence_commit_observer = feed.persistence_committed
        self.ambiguity_calls = 0
        self.refusals: list[str] = []

    def _observe_persistence_ambiguity(self) -> None:
        self.ambiguity_calls += 1

    # Verbatim from Scheduler._observe_persistence_commit (scheduler.py:1502-1510).
    def observe(self, receipt: object) -> None:
        observer = self._persistence_commit_observer
        if observer is None:
            return
        try:
            observer(receipt)
        except Exception as exc:
            self.refusals.append(str(exc))
            self._observe_persistence_ambiguity()


async def test_recovery_through_the_scheduler_observer_path(tmp_path: Path) -> None:
    """Interruption, refused replay, then a genuine later commit resumes."""
    writer = _writer(tmp_path)
    now = [10.0]
    feed = RecordingLifecycleFeed(writer, persistence_freshness_s=1.0, clock=lambda: now[0])
    await _ready(feed, "acq-1")
    harness = _ObserverHarness(feed)

    first = await writer.write_committed([_reading(1.0)])
    assert first is not None
    harness.observe(first)
    assert harness.refusals == []
    interrupted_session = feed.snapshot().recording_session_id
    assert feed.persistence_snapshot().storage is AvailabilityTruth.AVAILABLE

    # Interruption: freshness expiry closes the segment as ambiguous.
    now[0] = 11.1
    assert feed.persistence_snapshot().storage is AvailabilityTruth.UNAVAILABLE

    # A genuinely later commit, observed exactly as the scheduler observes it.
    later = await writer.write_committed([_reading(2.0)])
    assert later is not None
    harness.observe(later)

    assert harness.refusals == [], f"the scheduler path still refused: {harness.refusals}"
    assert harness.ambiguity_calls == 0
    resumed = feed.persistence_snapshot()
    assert resumed.storage is AvailabilityTruth.AVAILABLE
    assert feed.snapshot().recording is RecordingTruth.RECORDING
    assert ":recovery-" in (resumed.recording_epoch_id or "")
    assert feed.snapshot().recording_session_id != interrupted_session
    await writer.stop()


async def test_the_failed_receipt_cannot_be_replayed_through_the_scheduler(tmp_path: Path) -> None:
    """The receipt that caused the interruption is not evidence of recovery."""
    writer = _writer(tmp_path)
    feed = RecordingLifecycleFeed(writer)
    feed.experiment_active(1, "experiment-1", "Cooldown")
    feed.persistence_started("acq-old")
    feed.acquisition_running(1, "acq-new")
    harness = _ObserverHarness(feed)

    receipt = await writer.write_committed([_reading(1.0)])
    assert receipt is not None

    # The mismatch closes the segment; the scheduler logs and reports ambiguity.
    harness.observe(receipt)
    assert len(harness.refusals) == 1
    assert harness.ambiguity_calls == 1
    assert feed.persistence_snapshot().storage is AvailabilityTruth.UNAVAILABLE

    # Replaying the SAME receipt is refused, and does not resume anything.
    harness.observe(receipt)
    assert len(harness.refusals) == 2
    assert "commit after the interruption" in harness.refusals[1]
    assert feed.persistence_snapshot().storage is AvailabilityTruth.UNAVAILABLE
    assert feed.snapshot().recording is RecordingTruth.NOT_RECORDING

    # Only a later commit resumes.
    later = await writer.write_committed([_reading(2.0)])
    assert later is not None
    harness.observe(later)
    assert len(harness.refusals) == 2, "a genuine later commit must not be refused"
    assert feed.persistence_snapshot().storage is AvailabilityTruth.AVAILABLE
    await writer.stop()


async def test_a_deliberate_stop_stays_refused_through_the_scheduler(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    feed = RecordingLifecycleFeed(writer)
    await _ready(feed, "acq-1")
    harness = _ObserverHarness(feed)
    first = await writer.write_committed([_reading(1.0)])
    assert first is not None
    harness.observe(first)

    feed.persistence_stopped()
    later = await writer.write_committed([_reading(2.0)])
    assert later is not None
    harness.observe(later)

    assert len(harness.refusals) == 1
    assert "ambiguous interruption" in harness.refusals[0]
    assert harness.ambiguity_calls == 1
    assert feed.persistence_snapshot().storage is not AvailabilityTruth.AVAILABLE
    await writer.stop()
