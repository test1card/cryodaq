from __future__ import annotations

import asyncio
import inspect
import time
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
from cryodaq.core.zmq_bridge import ZMQPublisher
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.engine import _run_engine
from cryodaq.engine_wiring.operator_safety_snapshot import (
    OperatorSafetySnapshot,
    PlantHealthFact,
    SafetyLifecycle,
)
from cryodaq.engine_wiring.operator_snapshot_production import (
    build_operator_snapshot_publication_service,
)
from cryodaq.engine_wiring.recording_lifecycle_feed import RecordingLifecycleFeed
from cryodaq.operator_snapshot import (
    AvailabilityTruth,
    OperatorPresentationState,
    ReadinessTruth,
    RecordingTruth,
)
from cryodaq.operator_snapshot_transport import decode_operator_snapshot_frames
from cryodaq.storage.channel_descriptors import LiveChannelDescriptorCatalog
from cryodaq.storage.sqlite_writer import SQLiteWriter


@pytest.fixture(autouse=True)
def _allow_test_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")


class _SafetyOwner:
    def __init__(self) -> None:
        self.snapshot: object = OperatorSafetySnapshot(
            1,
            time.monotonic(),
            SafetyLifecycle.READY,
            ReadinessTruth.READY,
            True,
            (),
            (
                PlantHealthFact(
                    "reviewed_source",
                    "Reviewed source",
                    OperatorPresentationState.OK,
                    "reviewed_source_verified_off",
                ),
            ),
        )

    def snapshot_operator_safety(self) -> object:
        return self.snapshot


class _Socket:
    def __init__(self) -> None:
        self.messages: list[list[bytes]] = []

    async def send_multipart(self, frames: list[bytes]) -> None:
        self.messages.append(frames)


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
        timestamp=datetime(2026, 7, 15, 10, tzinfo=UTC),
        instrument_id="probe",
        channel="probe.1",
        value=value,
        unit="K",
        status=ChannelStatus.OK,
        raw=value,
    )


def _publisher() -> tuple[ZMQPublisher, _Socket]:
    publisher = ZMQPublisher()
    socket = _Socket()
    publisher._socket = socket  # type: ignore[assignment]
    publisher._running = True
    return publisher, socket


async def _ready(feed: RecordingLifecycleFeed, writer: SQLiteWriter, epoch: str = "epoch-1") -> None:
    feed.experiment_active(1, "experiment-1", "Cooldown", "cooldown")
    feed.persistence_started(epoch)
    feed.acquisition_running(1, epoch)
    receipt = await writer.write_committed([_reading(1.0)])
    assert receipt is not None
    feed.persistence_committed(receipt)


async def _attempt(service: object) -> bool:
    service._next_due = 0.0  # type: ignore[attr-defined]
    return await service._publish_if_due()  # type: ignore[attr-defined,no-any-return]


async def _stop_writer(writer: SQLiteWriter) -> None:
    await writer.stop()
    await asyncio.get_running_loop().shutdown_default_executor()


async def test_cold_start_is_dark_until_exact_commit_then_publishes_one_complete_cut(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "data")
    feed = RecordingLifecycleFeed(writer)
    publisher, socket = _publisher()
    service = build_operator_snapshot_publication_service(
        safety_owner=_SafetyOwner(),
        recording_feed=feed,
        publisher=publisher,
        data_root=tmp_path / "state",
    )

    assert await _attempt(service) is False
    assert socket.messages == []
    assert not (tmp_path / "state" / "state" / "operator_snapshot_revision.db").exists()

    await _ready(feed, writer)
    assert await _attempt(service) is True
    snapshot = decode_operator_snapshot_frames(socket.messages[0])
    assert snapshot.cut.revision == 1
    assert snapshot.experiment.recording is RecordingTruth.RECORDING
    assert snapshot.data_integrity.storage is AvailabilityTruth.AVAILABLE
    assert snapshot.readiness.readiness is ReadinessTruth.READY
    await _stop_writer(writer)


@pytest.mark.parametrize("failure", ["stale", "ambiguous", "epoch_mismatch", "disconnected"])
async def test_live_feed_failures_stop_new_publication_without_fallback_cut(
    tmp_path: Path,
    failure: str,
) -> None:
    now = [10.0]
    writer = _writer(tmp_path / failure / "data")
    feed = RecordingLifecycleFeed(writer, persistence_freshness_s=1.0, clock=lambda: now[0])
    safety = _SafetyOwner()
    publisher, socket = _publisher()
    service = build_operator_snapshot_publication_service(
        safety_owner=safety,
        recording_feed=feed,
        publisher=publisher,
        data_root=tmp_path / failure / "state",
    )
    await _ready(feed, writer)
    assert await _attempt(service) is True

    if failure == "stale":
        now[0] = 11.1
    elif failure == "ambiguous":
        feed.persistence_ambiguous()
    elif failure == "epoch_mismatch":
        feed.persistence_stopped()
        feed.acquisition_stopped(2)
        feed.persistence_started("persistence-2")
        feed.acquisition_running(3, "acquisition-2")
        receipt = await writer.write_committed([_reading(2.0)])
        assert receipt is not None
        with pytest.raises(ValueError, match="epoch does not match"):
            feed.persistence_committed(receipt)
    else:
        safety.snapshot = object()

    published = await _attempt(service)
    if failure == "disconnected":
        assert published is False
        assert len(socket.messages) == 1
        assert service.last_published_revision == 1
    else:
        assert published is True
        degraded = decode_operator_snapshot_frames(socket.messages[-1])
        assert degraded.cut.revision == 2
        assert degraded.experiment.recording is RecordingTruth.NOT_RECORDING
        assert degraded.data_integrity.storage is AvailabilityTruth.UNAVAILABLE
        assert degraded.data_integrity.status.state is OperatorPresentationState.WARNING
    await _stop_writer(writer)


async def test_expired_safety_cut_cannot_publish_or_retain_ready_output(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "data")
    feed = RecordingLifecycleFeed(writer)
    safety = _SafetyOwner()
    publisher, socket = _publisher()
    service = build_operator_snapshot_publication_service(
        safety_owner=safety,
        recording_feed=feed,
        publisher=publisher,
        data_root=tmp_path / "state",
    )
    await _ready(feed, writer)
    assert await _attempt(service) is True
    assert decode_operator_snapshot_frames(socket.messages[-1]).readiness.readiness is ReadinessTruth.READY

    safety.snapshot = OperatorSafetySnapshot(
        2,
        0.0,
        SafetyLifecycle.READY,
        ReadinessTruth.READY,
        True,
        (),
        (
            PlantHealthFact(
                "reviewed_source",
                "Reviewed source",
                OperatorPresentationState.OK,
                "reviewed_source_verified_off",
            ),
        ),
    )
    assert await _attempt(service) is False
    assert len(socket.messages) == 1
    assert service.last_published_revision == 1
    await _stop_writer(writer)


async def test_shutdown_is_dark_and_restart_uses_next_durable_revision(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "data")
    feed = RecordingLifecycleFeed(writer)
    await _ready(feed, writer)
    publisher, socket = _publisher()
    first = build_operator_snapshot_publication_service(
        safety_owner=_SafetyOwner(),
        recording_feed=feed,
        publisher=publisher,
        data_root=tmp_path / "state",
    )
    assert await _attempt(first) is True
    owner = asyncio.create_task(first.run())
    first.request_stop()
    await owner
    assert first.running is False
    assert len(socket.messages) == 1

    restarted = build_operator_snapshot_publication_service(
        safety_owner=_SafetyOwner(),
        recording_feed=feed,
        publisher=publisher,
        data_root=tmp_path / "state",
    )
    assert await _attempt(restarted) is True
    assert [decode_operator_snapshot_frames(frames).cut.revision for frames in socket.messages] == [1, 2]
    await _stop_writer(writer)


def test_engine_owns_one_post_scheduler_service_and_stops_it_before_transport() -> None:
    source = inspect.getsource(_run_engine)
    assert source.count("build_operator_snapshot_publication_service(") == 1
    assert source.count('"operator_snapshot_publication"') == 2
    assert source.index("_start_scheduler_with_recording_feed(", source.index("async def _run_engine")) < source.index(
        '"operator_snapshot_publication"'
    )
    assert source.index("operator_snapshot_service.request_stop()") < source.index("await zmq_pub.stop()")
