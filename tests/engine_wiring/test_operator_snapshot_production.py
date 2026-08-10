from __future__ import annotations

import asyncio
import inspect
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cryodaq.channels.descriptors import (
    ChannelCatalog,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.core.alarm_v2 import AlarmEvent, AlarmStateManager
from cryodaq.core.event_bus import EngineEvent, EventBus
from cryodaq.core.zmq_bridge import ZMQPublisher
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.engine import _dispatch_alarm_notification, _run_engine
from cryodaq.engine_wiring.operator_safety_snapshot import (
    OperatorSafetySnapshot,
    PlantHealthFact,
    SafetyLifecycle,
)
from cryodaq.engine_wiring.operator_snapshot_authorities import AuthorityAvailability, CommonCut
from cryodaq.engine_wiring.operator_snapshot_live_authorities import (
    DurableAttentionHistoryFeed,
    LiveAlarmAttentionAuthority,
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
from cryodaq.storage import sqlite_writer as sqlite_writer_module
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
            "verified_off",
            (("smua", "device_reported_off"), ("smub", "device_reported_off")),
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
        "verified_off",
        (("smua", "device_reported_off"), ("smub", "device_reported_off")),
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


async def test_attention_capacity_marker_is_explicit_without_suppressing_alarm_fanout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sqlite_writer_module, "ATTENTION_HISTORY_MAX_ITEMS", 1)
    writer = _writer(tmp_path / "attention-capacity")
    await writer.start_immediate()
    history_feed = DurableAttentionHistoryFeed(writer)
    await history_feed.start()
    event_bus = EventBus()
    event_bus.retain_required_observer("durable_attention_history", history_feed.persist_event)
    subscriber = await event_bus.subscribe("operator")
    first_at = datetime(2026, 8, 10, 12, tzinfo=UTC)
    second_at = first_at + timedelta(minutes=1)

    await event_bus.publish(
        EngineEvent(
            "alarm_fired",
            first_at,
            {
                "alarm_id": "alarm.first",
                "level": "WARNING",
                "message": "First",
                "channels": ["probe.1"],
            },
            "experiment-capacity",
        )
    )
    await event_bus.publish(
        EngineEvent(
            "alarm_fired",
            second_at,
            {
                "alarm_id": "alarm.second",
                "level": "CRITICAL",
                "message": "Second",
                "channels": ["probe.1"],
            },
            "experiment-capacity",
        )
    )

    assert [subscriber.get_nowait().payload["alarm_id"] for _ in range(2)] == [
        "alarm.first",
        "alarm.second",
    ]
    page = await writer.get_attention_history(experiment_id="experiment-capacity", limit=1)
    assert tuple(item.alarm_id for item in page.items) == ("alarm.first",)
    assert page.through_revision == 2
    assert page.capacity_exhausted_at == second_at
    assert history_feed.current_revision is None

    event_bus.release_required_observer("durable_attention_history")
    history_feed.stop()
    await writer.stop()
    await asyncio.get_running_loop().shutdown_default_executor()


async def test_cancelled_alarm_publication_settles_one_incident_before_propagating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _writer(tmp_path / "attention-cancel")
    await writer.start_immediate()
    history_feed = DurableAttentionHistoryFeed(writer)
    await history_feed.start()
    event_bus = EventBus()
    event_bus.retain_required_observer("durable_attention_history", history_feed.persist_event)
    subscriber = await event_bus.subscribe("operator")
    entered = threading.Event()
    released = threading.Event()
    settled = threading.Event()
    real_append = writer._append_attention_history_item_sync

    def blocked_append(item: object, *, require_persisted_incident: bool) -> object:
        entered.set()
        assert released.wait(timeout=5)
        try:
            return real_append(
                item,
                require_persisted_incident=require_persisted_incident,
            )
        finally:
            settled.set()

    monkeypatch.setattr(writer, "_append_attention_history_item_sync", blocked_append)
    event = EngineEvent(
        "alarm_fired",
        datetime(2026, 8, 10, 12, tzinfo=UTC),
        {
            "alarm_id": "alarm.cancel",
            "level": "CRITICAL",
            "message": "Cancellation boundary",
            "channels": ["probe.1"],
        },
        "experiment-cancel",
    )
    caller = asyncio.create_task(event_bus.publish(event))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        caller.cancel()
        await asyncio.sleep(0)
        assert caller.done() is False
        released.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert settled.is_set()

        await event_bus.publish(event)
        page = await writer.get_attention_history(experiment_id="experiment-cancel", limit=2)
        assert tuple(item.alarm_id for item in page.items) == ("alarm.cancel",)
        assert page.through_revision == 1
        assert subscriber.qsize() == 2
    finally:
        released.set()
        if not caller.done():
            await asyncio.gather(caller, return_exceptions=True)
        event_bus.release_required_observer("durable_attention_history")
        history_feed.stop()
        await writer.stop()
        await asyncio.get_running_loop().shutdown_default_executor()


async def test_attention_persistence_failure_preserves_alarm_fanout_and_latches_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _writer(tmp_path / "attention-failure")
    await writer.start_immediate()
    history_feed = DurableAttentionHistoryFeed(writer)
    await history_feed.start()
    event_bus = EventBus()
    event_bus.retain_required_observer("durable_attention_history", history_feed.persist_event)
    subscriber = await event_bus.subscribe("operator")

    async def reject_append(_event: object) -> object:
        raise OSError("control database unavailable")

    monkeypatch.setattr(writer, "append_attention_event", reject_append)
    await _dispatch_alarm_notification(
        event_bus,
        set(),
        alarm_id="alarm.persistence",
        level="CRITICAL",
        message="Persistence failed",
        experiment_id="experiment-stable-8",
        channel="probe.1",
    )

    assert subscriber.get_nowait().payload["alarm_id"] == "alarm.persistence"
    assert history_feed.current_revision is None
    receipt = LiveAlarmAttentionAuthority(AlarmStateManager(), history_feed).snapshot_for_cut(
        CommonCut(1, f"cut-v1:1:{'a' * 64}", datetime.now(UTC))
    )
    assert receipt.availability is AuthorityAvailability.UNAVAILABLE
    assert receipt.unavailable_reason == "attention_authority_unavailable"

    event_bus.release_required_observer("durable_attention_history")
    history_feed.stop()
    await writer.stop()
    await asyncio.get_running_loop().shutdown_default_executor()


async def test_alarm_dispatch_timeline_acknowledgement_and_restart_use_live_owners(tmp_path: Path) -> None:
    data_root = tmp_path / "attention"
    writer = _writer(data_root)
    await writer.start_immediate()
    history_feed = DurableAttentionHistoryFeed(writer)
    await history_feed.start()
    event_bus = EventBus()
    event_bus.retain_required_observer("durable_attention_history", history_feed.persist_event)
    subscriber = await event_bus.subscribe("operator")
    alarm_owner = AlarmStateManager()
    alarm_at = datetime.now(UTC)
    assert (
        alarm_owner.process(
            "alarm.hot",
            AlarmEvent(
                alarm_id="alarm.hot",
                level="CRITICAL",
                message="Temperature high",
                triggered_at=alarm_at.timestamp(),
                channels=["probe.1"],
                values={"probe.1": 9.5},
            ),
            {},
        )
        == "TRIGGERED"
    )

    await _dispatch_alarm_notification(
        event_bus,
        set(),
        alarm_id="alarm.hot",
        level="CRITICAL",
        message="Temperature high",
        experiment_id="experiment-stable-7",
        channel="probe.1",
        value=9.5,
    )
    incident_page = await writer.get_attention_history(
        experiment_id="experiment-stable-7",
        limit=10,
    )
    assert subscriber.get_nowait().payload["alarm_id"] == "alarm.hot"
    assert [item.kind for item in incident_page.items] == ["incident"]
    assert incident_page.items[0].channel_ids == ("probe.1",)
    assert history_feed.current_revision == incident_page.through_revision

    canonical_before = alarm_owner.snapshot_active_canonical()
    revision_before = alarm_owner.state_revision
    acknowledgement = await history_feed.annotate_acknowledgement(
        incident_page.items[0],
        actor="operator-17",
        note="reviewed at console",
        timestamp=incident_page.items[0].timestamp + timedelta(microseconds=1),
    )
    canonical_after = alarm_owner.snapshot_active_canonical()
    assert acknowledgement.annotation_of == incident_page.items[0].event_id
    assert canonical_after == canonical_before
    assert alarm_owner.state_revision == revision_before

    timeline = await writer.get_attention_history(
        experiment_id="experiment-stable-7",
        limit=10,
    )
    assert [item.kind for item in timeline.items] == ["incident", "acknowledgement"]
    assert history_feed.current_revision == timeline.through_revision
    cut_at = max(datetime.now(UTC), timeline.items[-1].timestamp)
    receipt = LiveAlarmAttentionAuthority(alarm_owner, history_feed).snapshot_for_cut(
        CommonCut(1, f"cut-v1:1:{'a' * 64}", cut_at)
    )
    assert receipt.availability is AuthorityAvailability.AVAILABLE
    assert receipt.history_revision == timeline.through_revision
    assert [(alarm.alarm_id, alarm.acknowledged) for alarm in receipt.alarms] == [("alarm.hot", False)]

    event_bus.release_required_observer("durable_attention_history")
    history_feed.stop()
    await writer.stop()

    restarted = _writer(data_root)
    await restarted.start_immediate()
    replayed = await restarted.get_attention_history(
        experiment_id="experiment-stable-7",
        limit=10,
    )
    assert replayed == timeline
    await restarted.stop()
    await asyncio.get_running_loop().shutdown_default_executor()


def test_engine_owns_one_post_scheduler_service_and_stops_it_before_transport() -> None:
    source = inspect.getsource(_run_engine)
    assert source.count("build_operator_snapshot_publication_service(") == 1
    assert source.count('supervisor.spawn,\n                "operator_snapshot_publication"') == 1
    assert source.index("_start_scheduler_with_recording_feed(", source.index("async def _run_engine")) < source.index(
        '"operator_snapshot_publication"'
    )
    shutdown = source.index("await teardown_sequence.settle_ingress_off()")
    snapshot_owner = source.index('"operator_snapshot_publication"', shutdown)
    terminal_dependencies = source.index('"terminal_dependencies"', snapshot_owner)
    assert "_request_and_settle_terminal_task_owner" in source[snapshot_owner:terminal_dependencies]
    assert snapshot_owner < terminal_dependencies


def test_engine_requires_durable_attention_before_alarm_fanout_and_live_snapshot_cut() -> None:
    engine_source = inspect.getsource(_run_engine)
    factory_source = inspect.getsource(build_operator_snapshot_publication_service)

    assert "DurableAttentionHistoryFeed(" in engine_source
    assert "retain_required_observer(" in engine_source
    assert "attention_history_feed=attention_history_feed" in engine_source
    assert "alarm_state_owner=alarm_v2_state_mgr" in engine_source
    assert "LiveAlarmAttentionAuthority(" in factory_source
    assert "attention=LiveAlarmAttentionAuthority" in factory_source
    writer_start = engine_source.index("writer.start_immediate()")
    history_start = engine_source.index("attention_history_feed.start()", writer_start)
    safety_start = engine_source.index("safety_manager.start()", history_start)
    assert writer_start < history_start < safety_start

    shutdown = engine_source.index("await teardown_sequence.settle_ingress_off()")
    dispatch_drain = engine_source.index('"alarm_dispatch_drain"', shutdown)
    observer_cutover = engine_source.index('"durable_attention_history_observer_cutover"', dispatch_drain)
    history_stop = engine_source.index('"durable_attention_history_feed"', observer_cutover)
    terminal_dependencies = engine_source.index('"terminal_dependencies"', history_stop)
    assert dispatch_drain < observer_cutover < history_stop < terminal_dependencies
