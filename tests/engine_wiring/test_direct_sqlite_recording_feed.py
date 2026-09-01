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


async def test_real_owner_issued_commit_drives_recording_and_direct_integrity(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    feed = RecordingLifecycleFeed(writer)
    await _ready(feed)
    receipt = await writer.write_committed([_reading(1.0)])
    assert receipt is not None

    persistence = feed.persistence_committed(receipt)
    recording = feed.snapshot()

    assert persistence.committed_materialization_revision == receipt.commit_revision == 1
    assert persistence.pending_count == 0
    assert persistence.dropped_or_rejected_count == 0
    assert persistence.storage is AvailabilityTruth.AVAILABLE
    assert persistence.reason == "direct_sqlite_commit"
    assert recording.recording is RecordingTruth.RECORDING
    assert recording.persistence_epoch_id == "acquisition-1"
    assert feed.persistence_committed(receipt) is persistence
    await writer.stop()


async def test_loss_latches_epoch_and_later_commit_cannot_restore_recording(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    feed = RecordingLifecycleFeed(writer)
    await _ready(feed)
    first = await writer.write_committed([_reading(1.0)])
    assert first is not None
    feed.persistence_committed(first)
    assert feed.snapshot().recording is RecordingTruth.RECORDING

    rejected = feed.persistence_rejected(2, "descriptor_commit_refused")
    assert rejected.dropped_or_rejected_count == 2
    assert rejected.storage is AvailabilityTruth.UNAVAILABLE
    assert feed.snapshot().recording is RecordingTruth.NOT_RECORDING

    second = await writer.write_committed([_reading(2.0)])
    assert second is not None
    after = feed.persistence_committed(second)
    assert after.committed_materialization_revision == second.commit_revision
    assert after.storage is AvailabilityTruth.UNAVAILABLE
    assert feed.snapshot().recording is RecordingTruth.NOT_RECORDING
    await writer.stop()


async def test_freshness_expiry_is_ambiguous_without_invented_loss(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    now = [10.0]
    feed = RecordingLifecycleFeed(writer, persistence_freshness_s=1.0, clock=lambda: now[0])
    await _ready(feed)
    receipt = await writer.write_committed([_reading(1.0)])
    assert receipt is not None
    feed.persistence_committed(receipt)
    now[0] = 11.1

    assert feed.snapshot().recording is RecordingTruth.NOT_RECORDING
    persistence = feed.persistence_snapshot()
    assert persistence.storage is AvailabilityTruth.UNAVAILABLE
    assert persistence.dropped_or_rejected_count == 0
    assert persistence.reason == "cancellation_ambiguous"
    interrupted_session = feed.snapshot().recording_session_id

    # A later PROVEN commit starts a NEW segment rather than wedging forever.
    # SQLite had already committed; only the bookkeeping was stuck.
    later = await writer.write_committed([_reading(2.0)])
    assert later is not None
    feed.persistence_committed(later)

    resumed = feed.persistence_snapshot()
    assert resumed.storage is AvailabilityTruth.AVAILABLE
    assert feed.snapshot().recording is RecordingTruth.RECORDING
    # The interrupted interval is not hidden: the segment is renamed and the
    # recording session is retired, so the gap is permanent in the identities.
    assert ":recovery-" in (resumed.recording_epoch_id or "")
    assert feed.snapshot().recording_session_id != interrupted_session
    await writer.stop()


async def test_foreign_receipt_cannot_change_live_truth(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "owner")
    foreign = _writer(tmp_path / "foreign")
    feed = RecordingLifecycleFeed(writer)
    await _ready(feed)
    receipt = await foreign.write_committed([_reading(1.0)])
    assert receipt is not None

    with pytest.raises(ValueError, match="exact SQLiteWriter provenance"):
        feed.persistence_committed(receipt)

    assert feed.snapshot().persistence_revision == 0
    assert feed.persistence_snapshot().storage is AvailabilityTruth.UNKNOWN
    await writer.stop()
    await foreign.stop()


async def test_genuine_commit_cannot_join_different_acquisition_and_persistence_epochs(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    feed = RecordingLifecycleFeed(writer)
    feed.experiment_active(1, "experiment-1", "Cooldown")
    feed.persistence_started("old-persistence-epoch")
    feed.acquisition_running(1, "new-acquisition-epoch")
    receipt = await writer.write_committed([_reading(1.0)])
    assert receipt is not None and writer.owns_commit(receipt)

    with pytest.raises(ValueError, match="acquisition epoch does not match"):
        feed.persistence_committed(receipt)

    assert feed.snapshot().recording is RecordingTruth.NOT_RECORDING
    assert feed.snapshot().persistence_epoch_id is None
    assert feed.persistence_snapshot().storage is AvailabilityTruth.UNAVAILABLE

    # The mismatch closed the old segment; the same proven receipt then opens a
    # recovery segment bound to the acquisition epoch that is ACTUALLY running.
    # That is honest: the data committed, and the record says where it belongs.
    feed.persistence_committed(receipt)
    resumed = feed.persistence_snapshot()
    assert resumed.storage is AvailabilityTruth.AVAILABLE
    assert (resumed.recording_epoch_id or "").startswith("new-acquisition-epoch:recovery-")
    await writer.stop()


async def test_failed_replacement_start_terminalizes_old_persistence_epoch(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    feed = RecordingLifecycleFeed(writer)
    await _ready(feed, "old-epoch")
    first = await writer.write_committed([_reading(1.0)])
    assert first is not None
    feed.persistence_committed(first)
    feed.acquisition_stopped(2)

    with pytest.raises(ValueError, match="already active"):
        feed.persistence_started("new-epoch")

    feed.acquisition_running(3, "new-epoch")
    stale = await writer.write_committed([_reading(2.0)])
    assert stale is not None and writer.owns_commit(stale)

    # The failed replacement left the old segment terminal. A proven commit
    # under the new acquisition epoch resumes into a recovery segment instead
    # of wedging the feed for the life of the process.
    feed.persistence_committed(stale)
    assert feed.snapshot().recording is RecordingTruth.RECORDING
    assert (feed.persistence_snapshot().recording_epoch_id or "").startswith("new-epoch:recovery-")
    await writer.stop()


async def test_recovery_requires_a_running_acquisition_epoch(tmp_path: Path) -> None:
    """A segment with nothing to belong to would be a fiction.

    Also the startup window: commits landing before acquisition_running is fed
    are refused here and recovered on the next one, instead of wedging the feed
    for the life of the process.
    """
    writer = _writer(tmp_path)
    now = [10.0]
    feed = RecordingLifecycleFeed(writer, persistence_freshness_s=1.0, clock=lambda: now[0])
    await _ready(feed, "epoch-a")
    first = await writer.write_committed([_reading(1.0)])
    assert first is not None
    feed.persistence_committed(first)

    # Close the segment through freshness expiry, then remove the acquisition.
    now[0] = 11.1
    assert feed.persistence_snapshot().storage is AvailabilityTruth.UNAVAILABLE
    feed.acquisition_stopped(2)

    orphan = await writer.write_committed([_reading(2.0)])
    assert orphan is not None
    with pytest.raises(ValueError, match="running acquisition epoch"):
        feed.persistence_committed(orphan)
    assert feed.persistence_snapshot().storage is not AvailabilityTruth.AVAILABLE
    await writer.stop()


async def test_a_foreign_receipt_can_never_open_a_recovery_segment(tmp_path: Path) -> None:
    """Provenance is checked before recovery is even considered."""
    writer = _writer(tmp_path / "owner")
    foreign = _writer(tmp_path / "foreign")
    feed = RecordingLifecycleFeed(writer)
    await _ready(feed, "epoch-a")
    feed.acquisition_stopped(2)
    feed.acquisition_running(3, "epoch-b")

    receipt = await foreign.write_committed([_reading(1.0)])
    assert receipt is not None
    with pytest.raises(ValueError, match="exact SQLiteWriter provenance"):
        feed.persistence_committed(receipt)
    assert feed.persistence_snapshot().storage is not AvailabilityTruth.AVAILABLE
    await writer.stop()
    await foreign.stop()
