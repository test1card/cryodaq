"""Closed H3 periodic stream protocol and publisher authority tests."""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import UTC, datetime
from types import SimpleNamespace

import msgpack
import pytest

from cryodaq.core.broker import PERSISTENCE_AUTHORITATIVE_METADATA_KEY
from cryodaq.core.zmq_bridge import (
    EVENTS_TOPIC,
    PERIODIC_BARRIER_SCHEMA,
    PERIODIC_BARRIER_TOPIC,
    PERIODIC_MAX_SEQUENCE,
    PERIODIC_QUERY_SCHEMA,
    PERIODIC_STREAM_SCHEMA,
    PROTOCOL_VERSION,
    ZMQCommandServer,
    ZMQPublisher,
    _decode_command,
    _unpack_reading,
    encode_periodic_command_reply,
)
from cryodaq.drivers.base import ChannelStatus, Reading


class _Socket:
    def __init__(self) -> None:
        self.frames: list[list[bytes]] = []
        self.failure: BaseException | None = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False
        self.closed = False

    async def send_multipart(self, frames: list[bytes]) -> None:
        self.entered.set()
        if self.block:
            await self.release.wait()
        if self.failure is not None:
            raise self.failure
        self.frames.append(frames)

    def close(self, *, linger: int) -> None:
        assert linger == 0
        self.closed = True


class _Context:
    def __init__(self) -> None:
        self.terminated = False

    def term(self) -> None:
        self.terminated = True


def _reading(*, authoritative: bool) -> Reading:
    metadata = {"public": "yes"}
    if authoritative:
        metadata[PERSISTENCE_AUTHORITATIVE_METADATA_KEY] = True
    return Reading(
        timestamp=datetime(2026, 7, 10, tzinfo=UTC),
        instrument_id="ls218",
        channel="T1",
        value=4.2,
        unit="K",
        status=ChannelStatus.OK,
        metadata=metadata,
    )


def _prime_publisher(*, socket: _Socket | None = None) -> tuple[ZMQPublisher, _Socket]:
    publisher = ZMQPublisher()
    fake = socket or _Socket()
    publisher._socket = fake  # type: ignore[assignment]
    publisher._running = True
    publisher._session_id = "a" * 32
    publisher._sequence = 0
    publisher._publish_failure_count = 0
    publisher._send_lock = asyncio.Lock()
    return publisher, fake


async def test_reading_transport_is_additive_and_internal_marker_is_stripped() -> None:
    publisher, socket = _prime_publisher()

    await publisher._publish_reading(_reading(authoritative=True))

    assert socket.frames[0][0] == b"readings"
    payload = msgpack.unpackb(socket.frames[0][1], raw=False)
    assert payload["meta"] == {"public": "yes"}
    assert payload["transport"] == {
        "schema": PERIODIC_STREAM_SCHEMA,
        "session_id": "a" * 32,
        "sequence": 1,
        "persistence_authoritative": True,
    }


async def test_reading_event_and_barrier_share_one_sequence() -> None:
    publisher, socket = _prime_publisher()
    queue: asyncio.Queue[Reading] = asyncio.Queue()
    publisher._queue = queue
    publisher._task = asyncio.current_task()
    publisher.configure_periodic_authority(
        reading_drop_count=lambda: 3,
        alarm_snapshot=lambda: SimpleNamespace(
            state_revision=7,
            state_token="sha256:" + "b" * 64,
            active={},
        ),
    )

    await publisher._publish_reading(_reading(authoritative=False))
    await publisher.publish_event(
        event_type="alarm_fired",
        timestamp=datetime(2026, 7, 10, tzinfo=UTC),
        payload={"alarm_id": "a"},
        experiment_id="exp",
    )
    barrier = await publisher.barrier("c" * 32)

    reading = msgpack.unpackb(socket.frames[0][1], raw=False)
    event = json.loads(socket.frames[1][1])
    marker = json.loads(socket.frames[2][1])
    assert socket.frames[1][0] == EVENTS_TOPIC
    assert socket.frames[2][0] == PERIODIC_BARRIER_TOPIC
    assert [
        reading["transport"]["sequence"],
        event["transport"]["sequence"],
        marker["sequence"],
    ] == [
        1,
        2,
        3,
    ]
    assert barrier == {**marker, "ok": True}
    assert marker["schema"] == PERIODIC_BARRIER_SCHEMA
    assert marker["proto"] == PROTOCOL_VERSION


async def test_concurrent_reading_and_event_allocate_only_under_send_lock() -> None:
    socket = _Socket()
    socket.block = True
    publisher, _ = _prime_publisher(socket=socket)

    reading = asyncio.create_task(publisher._publish_reading(_reading(authoritative=True)))
    await socket.entered.wait()
    event = asyncio.create_task(
        publisher.publish_event(
            event_type="alarm_fired",
            timestamp=datetime(2026, 7, 10, tzinfo=UTC),
            payload={},
            experiment_id=None,
        )
    )
    await asyncio.sleep(0)
    assert publisher.sequence == 1
    socket.release.set()
    await asyncio.gather(reading, event)

    first = msgpack.unpackb(socket.frames[0][1], raw=False)
    second = json.loads(socket.frames[1][1])
    assert first["transport"]["sequence"] == 1
    assert second["transport"]["sequence"] == 2


async def test_barrier_cannot_overtake_blocked_queued_reading() -> None:
    socket = _Socket()
    socket.block = True
    publisher, _ = _prime_publisher(socket=socket)
    queue: asyncio.Queue[Reading] = asyncio.Queue()
    publisher._queue = queue
    publisher.configure_periodic_authority(
        reading_drop_count=lambda: 0,
        alarm_snapshot=lambda: SimpleNamespace(
            state_revision=0,
            state_token="sha256:" + "0" * 64,
            active={},
        ),
    )
    await queue.put(_reading(authoritative=True))
    publisher._task = asyncio.create_task(publisher._publish_loop(queue))
    await socket.entered.wait()

    barrier = asyncio.create_task(publisher.barrier("6" * 32))
    await asyncio.sleep(0)
    assert not barrier.done()
    assert publisher.sequence == 1
    socket.release.set()
    result = await barrier

    assert result["sequence"] == 2
    assert socket.frames[0][0] == b"readings"
    assert socket.frames[1][0] == PERIODIC_BARRIER_TOPIC
    publisher._running = False
    publisher._task.cancel()
    await asyncio.gather(publisher._task, return_exceptions=True)


async def test_barrier_cancelled_while_waiting_send_lock_allocates_nothing() -> None:
    publisher, _ = _prime_publisher()
    publisher._queue = asyncio.Queue()
    publisher._task = asyncio.current_task()
    publisher.configure_periodic_authority(
        reading_drop_count=lambda: 0,
        alarm_snapshot=lambda: SimpleNamespace(
            state_revision=0,
            state_token="sha256:" + "0" * 64,
            active={},
        ),
    )
    await publisher._send_lock.acquire()
    barrier = asyncio.create_task(publisher.barrier("7" * 32))
    await asyncio.sleep(0)
    barrier.cancel()
    with pytest.raises(asyncio.CancelledError):
        await barrier
    publisher._send_lock.release()

    assert publisher.sequence == 0
    assert publisher.publish_failure_count == 0


async def test_replay_reading_remains_decodable_without_periodic_samplers() -> None:
    publisher, socket = _prime_publisher()
    original = _reading(authoritative=False)

    await publisher._publish_reading(original)

    decoded = _unpack_reading(socket.frames[0][1])
    assert decoded == original
    assert await publisher.barrier("8" * 32) == {
        "ok": False,
        "schema": PERIODIC_BARRIER_SCHEMA,
        "error_code": "barrier_unavailable",
    }


async def test_publish_loop_always_settles_queue_item_and_exposes_sequence_gap() -> None:
    socket = _Socket()
    publisher, _ = _prime_publisher(socket=socket)
    queue: asyncio.Queue[Reading] = asyncio.Queue()
    await queue.put(_reading(authoritative=True))
    socket.failure = RuntimeError("send failed")

    task = asyncio.create_task(publisher._publish_loop(queue))
    await asyncio.wait_for(socket.entered.wait(), timeout=0.2)
    assert publisher.publish_failure_count == 1
    socket.failure = None
    socket.entered.clear()
    await queue.put(_reading(authoritative=True))
    await asyncio.wait_for(socket.entered.wait(), timeout=0.2)
    assert publisher.sequence == 2
    publisher._running = False
    await asyncio.wait_for(queue.join(), timeout=0.2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert publisher.sequence == 2
    assert publisher.publish_failure_count == 1
    assert msgpack.unpackb(socket.frames[0][1], raw=False)["transport"]["sequence"] == 2


async def test_send_cancellation_after_allocation_consumes_sequence_and_counts_failure() -> None:
    socket = _Socket()
    socket.block = True
    publisher, _ = _prime_publisher(socket=socket)

    task = asyncio.create_task(publisher._publish_reading(_reading(authoritative=True)))
    await socket.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert publisher.sequence == 1
    assert publisher.publish_failure_count == 1


async def test_barrier_send_cancellation_is_exposed_by_next_marker() -> None:
    socket = _Socket()
    socket.block = True
    publisher, _ = _prime_publisher(socket=socket)
    publisher._queue = asyncio.Queue()
    publisher._task = asyncio.current_task()
    publisher.configure_periodic_authority(
        reading_drop_count=lambda: 0,
        alarm_snapshot=lambda: SimpleNamespace(
            state_revision=1,
            state_token="sha256:" + "1" * 64,
            active={},
        ),
    )

    first = asyncio.create_task(publisher.barrier("2" * 32))
    await socket.entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert publisher.sequence == 1
    assert publisher.publish_failure_count == 1

    socket.block = False
    socket.entered.clear()
    result = await publisher.barrier("3" * 32)
    assert result["sequence"] == 2
    assert result["publish_failure_count"] == 1


async def test_barrier_cancellation_before_allocation_changes_no_counter() -> None:
    publisher, _ = _prime_publisher()
    queue: asyncio.Queue[Reading] = asyncio.Queue()
    await queue.put(_reading(authoritative=True))
    publisher._queue = queue
    publisher._task = asyncio.current_task()
    publisher.configure_periodic_authority(
        reading_drop_count=lambda: 0,
        alarm_snapshot=lambda: SimpleNamespace(
            state_revision=1,
            state_token="sha256:" + "1" * 64,
            active={},
        ),
    )

    task = asyncio.create_task(publisher.barrier("4" * 32))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert publisher.sequence == 0
    assert publisher.publish_failure_count == 0
    queue.get_nowait()
    queue.task_done()


async def test_sequence_never_wraps_or_sends() -> None:
    publisher, socket = _prime_publisher()
    publisher._sequence = PERIODIC_MAX_SEQUENCE

    with pytest.raises(RuntimeError, match="sequence exhausted"):
        await publisher._publish_reading(_reading(authoritative=True))

    assert publisher.sequence == PERIODIC_MAX_SEQUENCE
    assert socket.frames == []


async def test_barrier_without_live_authority_fails_closed_without_allocation() -> None:
    publisher, socket = _prime_publisher()
    publisher._queue = asyncio.Queue()
    publisher._task = asyncio.current_task()

    result = await publisher.barrier("d" * 32)

    assert result == {
        "ok": False,
        "schema": PERIODIC_BARRIER_SCHEMA,
        "error_code": "barrier_unavailable",
    }
    assert publisher.sequence == 0
    assert socket.frames == []


async def test_barrier_rechecks_publisher_identity_after_join() -> None:
    publisher, socket = _prime_publisher()
    queue: asyncio.Queue[Reading] = asyncio.Queue()
    publisher._queue = queue
    publisher._task = asyncio.current_task()
    publisher.configure_periodic_authority(
        reading_drop_count=lambda: 0,
        alarm_snapshot=lambda: SimpleNamespace(
            state_revision=0,
            state_token="sha256:" + "0" * 64,
            active={},
        ),
    )
    await publisher._send_lock.acquire()
    barrier = asyncio.create_task(publisher.barrier("e" * 32))
    await asyncio.sleep(0)
    publisher._task = asyncio.create_task(asyncio.sleep(60))
    publisher._send_lock.release()

    result = await barrier
    publisher._task.cancel()
    await asyncio.gather(publisher._task, return_exceptions=True)

    assert result["error_code"] == "barrier_unavailable"
    assert publisher.sequence == 0
    assert socket.frames == []


async def test_barrier_rejects_alarm_revision_change_after_send() -> None:
    publisher, socket = _prime_publisher()
    publisher._queue = asyncio.Queue()
    publisher._task = asyncio.current_task()
    revision = {"value": 4}

    def snapshot():
        current = revision["value"]
        revision["value"] += 1
        return SimpleNamespace(
            state_revision=current,
            state_token="sha256:" + "f" * 64,
            active={},
        )

    publisher.configure_periodic_authority(
        reading_drop_count=lambda: 0,
        alarm_snapshot=snapshot,
    )

    result = await publisher.barrier("1" * 32)

    assert result["error_code"] == "barrier_unstable"
    assert publisher.sequence == 1
    assert len(socket.frames) == 1


async def test_stop_during_barrier_send_makes_marker_orphan_and_waits_for_lock() -> None:
    socket = _Socket()
    socket.block = True
    publisher, _ = _prime_publisher(socket=socket)
    publisher._queue = asyncio.Queue()
    publisher._task = asyncio.create_task(asyncio.sleep(60))
    publisher.configure_periodic_authority(
        reading_drop_count=lambda: 0,
        alarm_snapshot=lambda: SimpleNamespace(
            state_revision=2,
            state_token="sha256:" + "2" * 64,
            active={},
        ),
    )

    barrier = asyncio.create_task(publisher.barrier("5" * 32))
    await socket.entered.wait()
    stop = asyncio.create_task(publisher.stop())
    await asyncio.sleep(0)
    assert not stop.done()
    socket.release.set()

    result = await barrier
    await stop
    assert result == {
        "ok": False,
        "schema": PERIODIC_BARRIER_SCHEMA,
        "error_code": "barrier_unavailable",
    }
    assert socket.closed is True
    assert publisher.session_id is None


async def test_cancelled_stop_cleans_resources_then_propagates_cancellation() -> None:
    publisher, socket = _prime_publisher()
    context = _Context()
    publisher._ctx = context  # type: ignore[assignment]
    publisher._queue = asyncio.Queue()
    cancellation_seen = asyncio.Event()
    release_drain = asyncio.Event()

    async def stubborn_drain() -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_seen.set()
            await release_drain.wait()

    publisher._task = asyncio.create_task(stubborn_drain())
    stop = asyncio.create_task(publisher.stop())
    await cancellation_seen.wait()
    stop.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stop

    assert socket.closed is True
    assert context.terminated is True
    assert publisher._task is None
    assert publisher._socket is None
    assert publisher._ctx is None
    assert publisher._queue is None
    assert publisher.session_id is None


async def test_prefailed_drain_task_cleans_resources_then_propagates_error() -> None:
    publisher, socket = _prime_publisher()
    context = _Context()
    publisher._ctx = context  # type: ignore[assignment]
    publisher._queue = asyncio.Queue()

    async def failed_drain() -> None:
        raise RuntimeError("drain failed")

    publisher._task = asyncio.create_task(failed_drain())
    await asyncio.sleep(0)
    assert publisher._task.done()

    with pytest.raises(RuntimeError, match="drain failed"):
        await publisher.stop()

    assert socket.closed is True
    assert context.terminated is True
    assert publisher._task is None
    assert publisher._socket is None
    assert publisher._ctx is None
    assert publisher._queue is None
    assert publisher.session_id is None


async def test_caller_cancellation_outranks_drain_finally_failure_after_cleanup() -> None:
    publisher, socket = _prime_publisher()
    context = _Context()
    publisher._ctx = context  # type: ignore[assignment]
    publisher._queue = asyncio.Queue()
    drain_finally_entered = asyncio.Event()

    async def failing_drain_finally() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            drain_finally_entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise RuntimeError("drain-finally-failed") from None

    publisher._task = asyncio.create_task(failing_drain_finally())
    stop = asyncio.create_task(publisher.stop())
    await drain_finally_entered.wait()
    stop.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stop

    assert socket.closed is True
    assert context.terminated is True
    assert publisher._task is None
    assert publisher._socket is None
    assert publisher._ctx is None
    assert publisher._queue is None
    assert publisher.session_id is None


def test_command_decoder_rejects_duplicate_request_fields() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _decode_command(b'{"cmd":"periodic_alarm_snapshot","cmd":"safety_status","schema":"cryodaq.periodic.query/v1"}')


def test_periodic_reply_encoder_is_compact_sorted_finite_and_exact_once() -> None:
    reply = encode_periodic_command_reply({"schema": PERIODIC_QUERY_SCHEMA, "ok": False, "error_code": "x"})
    assert reply.wire == (b'{"error_code":"x","ok":false,"proto":1,"schema":"cryodaq.periodic.query/v1"}')
    assert ZMQCommandServer()._encode_reply(reply) is reply.wire
    with pytest.raises(ValueError, match="Out of range float"):
        encode_periodic_command_reply({"ok": True, "value": float("nan")})


async def test_start_creates_fresh_session_and_replay_barrier_stays_absent() -> None:
    publisher = ZMQPublisher(f"inproc://periodic-{secrets.token_hex(8)}")
    queue: asyncio.Queue[Reading] = asyncio.Queue()

    await publisher.start(queue)
    first = publisher.session_id
    try:
        assert type(first) is str
        assert len(first) == 32
        assert all(ch in "0123456789abcdef" for ch in first)
        assert await publisher.barrier("a" * 32) == {
            "ok": False,
            "schema": PERIODIC_BARRIER_SCHEMA,
            "error_code": "barrier_unavailable",
        }
        with pytest.raises(RuntimeError, match="already started"):
            await publisher.start(queue)
    finally:
        await publisher.stop()

    await publisher.start(queue)
    try:
        assert publisher.session_id != first
        assert publisher.sequence == 0
        assert publisher.publish_failure_count == 0
    finally:
        await publisher.stop()


async def test_start_bind_failure_restores_resource_free_state(monkeypatch) -> None:
    import cryodaq.core.zmq_bridge as bridge

    async def fail_bind(socket, address: str) -> None:
        raise RuntimeError("bind failed")

    monkeypatch.setattr(bridge, "_bind_with_retry", fail_bind)
    publisher = ZMQPublisher("inproc://never-bound")

    with pytest.raises(RuntimeError, match="bind failed"):
        await publisher.start(asyncio.Queue())

    assert publisher._running is False
    assert publisher._task is None
    assert publisher._socket is None
    assert publisher._ctx is None
    assert publisher._queue is None
    assert publisher.session_id is None
