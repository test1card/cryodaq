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




from cryodaq.core.broker import DataBroker
from cryodaq.core.scheduler import Scheduler


def _scheduler(feed: RecordingLifecycleFeed) -> tuple[Scheduler, list[int]]:
    """A REAL Scheduler wired to the feed, exactly as the engine wires it.

    No copy of `_observe_persistence_commit`: this drives the production
    method, so its bare `except Exception`, its log line and its ambiguity
    fallback are the ones under test.
    """
    ambiguity: list[int] = []

    def _ambiguous() -> None:
        ambiguity.append(1)
        feed.persistence_ambiguous()

    scheduler = Scheduler(
        DataBroker(),
        persistence_commit_observer=feed.persistence_committed,
        persistence_ambiguity_observer=_ambiguous,
    )
    return scheduler, ambiguity


async def test_recovery_through_the_scheduler_observer_path(tmp_path: Path) -> None:
    """Interruption, refused replay, then a genuine later commit resumes."""
    writer = _writer(tmp_path)
    now = [10.0]
    feed = RecordingLifecycleFeed(writer, persistence_freshness_s=1.0, clock=lambda: now[0])
    await _ready(feed, "acq-1")
    scheduler, ambiguity = _scheduler(feed)

    first = await writer.write_committed([_reading(1.0)])
    assert first is not None
    scheduler._observe_persistence_commit(first)
    assert ambiguity == []
    interrupted_session = feed.snapshot().recording_session_id
    assert feed.persistence_snapshot().storage is AvailabilityTruth.AVAILABLE

    # Interruption: freshness expiry closes the segment as ambiguous.
    now[0] = 11.1
    assert feed.persistence_snapshot().storage is AvailabilityTruth.UNAVAILABLE

    # A genuinely later commit, observed exactly as the scheduler observes it.
    later = await writer.write_committed([_reading(2.0)])
    assert later is not None
    scheduler._observe_persistence_commit(later)

    assert ambiguity == [], "the real scheduler path refused the recovery"
    assert ambiguity == []
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
    scheduler, ambiguity = _scheduler(feed)

    receipt = await writer.write_committed([_reading(1.0)])
    assert receipt is not None

    # The mismatch closes the segment; the scheduler logs and reports ambiguity.
    scheduler._observe_persistence_commit(receipt)
    assert len(ambiguity) == 1
    assert len(ambiguity) == 1
    assert feed.persistence_snapshot().storage is AvailabilityTruth.UNAVAILABLE

    # Replaying the SAME receipt is refused, and does not resume anything.
    scheduler._observe_persistence_commit(receipt)
    assert len(ambiguity) == 2, "the replay was not refused"
    assert feed.persistence_snapshot().storage is AvailabilityTruth.UNAVAILABLE
    assert feed.snapshot().recording is RecordingTruth.NOT_RECORDING

    # Only a later commit resumes.
    later = await writer.write_committed([_reading(2.0)])
    assert later is not None
    scheduler._observe_persistence_commit(later)
    assert len(ambiguity) == 2, "a genuine later commit must not be refused"
    assert feed.persistence_snapshot().storage is AvailabilityTruth.AVAILABLE
    await writer.stop()


async def test_a_deliberate_stop_stays_refused_through_the_scheduler(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    feed = RecordingLifecycleFeed(writer)
    await _ready(feed, "acq-1")
    scheduler, ambiguity = _scheduler(feed)
    first = await writer.write_committed([_reading(1.0)])
    assert first is not None
    scheduler._observe_persistence_commit(first)

    feed.persistence_stopped()
    later = await writer.write_committed([_reading(2.0)])
    assert later is not None
    scheduler._observe_persistence_commit(later)

    assert len(ambiguity) == 1
    assert len(ambiguity) == 1
    assert feed.persistence_snapshot().storage is not AvailabilityTruth.AVAILABLE
    await writer.stop()
