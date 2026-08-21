from __future__ import annotations

import asyncio
import hashlib
import json
import socket as network_socket
from datetime import UTC, datetime

import msgpack
import pytest
import zmq
import zmq.asyncio

from cryodaq.agents.assistant import periodic_runtime
from cryodaq.agents.assistant.periodic_png import LiveSourceCut
from cryodaq.agents.assistant.periodic_runtime import (
    BarrierQueryResult,
    PeriodicEngineQuery,
    PeriodicLiveDiscontinuity,
    SequencedPeriodicLiveSources,
)
from cryodaq.agents.assistant_main import _RemoteEngineStateCache
from cryodaq.core.zmq_bridge import (
    DEFAULT_TOPIC,
    EVENTS_TOPIC,
    PERIODIC_BARRIER_SCHEMA,
    PERIODIC_BARRIER_TOPIC,
    PERIODIC_QUERY_SCHEMA,
    PERIODIC_STREAM_SCHEMA,
    PROTOCOL_VERSION,
)

pytestmark = pytest.mark.asyncio

SESSION = "1" * 32
TOKEN = "sha256:" + "2" * 64
EMPTY_TOKEN = "sha256:" + hashlib.sha256(b"{}").hexdigest()


class _FakeSocket:
    def __init__(self, response: bytes | asyncio.Future[bytes]) -> None:
        self.response = response
        self.options: list[tuple[int, object]] = []
        self.address: str | None = None
        self.request: bytes | None = None
        self.sent = asyncio.Event()
        self.closed = False

    def setsockopt(self, option: int, value: object) -> None:
        self.options.append((option, value))

    def connect(self, address: str) -> None:
        self.address = address

    async def send(self, request: bytes) -> None:
        self.request = request
        self.sent.set()

    async def recv(self) -> bytes:
        if isinstance(self.response, asyncio.Future):
            return await self.response
        return self.response

    def close(self, *, linger: int) -> None:
        assert linger == 0
        self.closed = True


class _FakeContext:
    def __init__(self, response: bytes | asyncio.Future[bytes]) -> None:
        self.socket_instance = _FakeSocket(response)
        self.terminated = False

    def socket(self, socket_type: int) -> _FakeSocket:
        assert socket_type == zmq.REQ
        return self.socket_instance

    def term(self) -> None:
        self.terminated = True


class _BlockingMonitor:
    def __init__(self) -> None:
        self.closed = False

    def setsockopt(self, _option: int, _value: object) -> None:
        pass

    async def recv_multipart(self) -> list[bytes]:
        await asyncio.Future()
        raise AssertionError("unreachable")

    def close(self, *, linger: int) -> None:
        assert linger == 0
        self.closed = True


class _OrderedSubSocket:
    def __init__(self, operations: list[tuple[str, object]]) -> None:
        self.operations = operations
        self.monitor = _BlockingMonitor()

    def setsockopt(self, option: int, value: object) -> None:
        if option == zmq.SUBSCRIBE:
            self.operations.append(("subscribe", value))

    def get_monitor_socket(self, *, events: int) -> _BlockingMonitor:
        assert events
        return self.monitor

    def connect(self, address: str) -> None:
        self.operations.append(("connect", address))

    async def recv_multipart(self) -> list[bytes]:
        await asyncio.Future()
        raise AssertionError("unreachable")

    def disable_monitor(self) -> None:
        pass

    def close(self, *, linger: int) -> None:
        assert linger == 0


class _OrderedSubContext:
    def __init__(self, operations: list[tuple[str, object]]) -> None:
        self.socket_instance = _OrderedSubSocket(operations)

    def socket(self, socket_type: int) -> _OrderedSubSocket:
        assert socket_type == zmq.SUB
        return self.socket_instance

    def term(self) -> None:
        pass


def _cut(sequence: int, *, nonce: str, drops: int = 3, failures: int = 4) -> tuple[LiveSourceCut, bytes]:
    cut = LiveSourceCut(SESSION, 1, sequence, 10.5, drops, failures, 7, TOKEN)
    wire = json.dumps(
        {
            "proto": PROTOCOL_VERSION,
            "schema": PERIODIC_BARRIER_SCHEMA,
            "nonce": nonce,
            "session_id": SESSION,
            "sequence": sequence,
            "published_at": 10.5,
            "reading_drop_count": drops,
            "publish_failure_count": failures,
            "alarm_state_revision": 7,
            "alarm_state_token": TOKEN,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return cut, wire


def _reading(sequence: int, *, authoritative: bool, metadata: dict[str, object] | None = None) -> bytes:
    return msgpack.packb(
        {
            "ts": datetime.now(UTC).timestamp(),
            "iid": "ls",
            "ch": f"T{sequence}",
            "v": float(sequence),
            "u": "K",
            "st": "ok",
            "raw": None,
            "meta": metadata or {},
            "transport": {
                "schema": PERIODIC_STREAM_SCHEMA,
                "session_id": SESSION,
                "sequence": sequence,
                "persistence_authoritative": authoritative,
            },
        },
        use_bin_type=True,
    )


def _event(sequence: int) -> bytes:
    return json.dumps(
        {
            "event_type": "alarm_fired",
            "ts": 10.0,
            "payload": {"alarm_id": "a"},
            "experiment_id": None,
            "transport": {
                "schema": PERIODIC_STREAM_SCHEMA,
                "session_id": SESSION,
                "sequence": sequence,
                "persistence_authoritative": False,
            },
        }
    ).encode()


async def _until(condition, *, timeout: float = 5.0) -> bool:
    """Poll a condition to a deadline instead of sleeping for a guessed interval.

    A fixed sleep before asserting delivery is a race dressed as a test: on a loaded
    runner the receive task may legitimately not have run yet, and the guard fails while
    the transport is behaving correctly. Polling to a generous deadline is deterministic
    in both directions -- it returns as soon as the condition holds, and it fails only
    when the condition never holds.
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.005)
    return condition()


async def _publisher() -> tuple[zmq.asyncio.Context, zmq.asyncio.Socket, str]:
    context = zmq.asyncio.Context()
    socket = context.socket(zmq.PUB)
    socket.setsockopt(zmq.LINGER, 0)
    port = socket.bind_to_random_port("tcp://127.0.0.1")
    return context, socket, f"tcp://127.0.0.1:{port}"


def _free_loopback_port() -> int:
    with network_socket.socket(network_socket.AF_INET, network_socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


async def test_constructor_is_resource_free_and_rejects_non_loopback() -> None:
    calls = 0

    def factory() -> zmq.asyncio.Context:
        nonlocal calls
        calls += 1
        return zmq.asyncio.Context()

    query = PeriodicEngineQuery(_context_factory=factory)
    live = SequencedPeriodicLiveSources(query, _context_factory=factory)
    assert calls == 0
    assert live._socket is None
    with pytest.raises(ValueError, match="loopback"):
        PeriodicEngineQuery("tcp://0.0.0.0:5556")


async def test_start_connects_before_subscribing_to_the_participating_topics() -> None:
    """Connect first, then subscribe -- and subscribe to those three topics only.

    The all-topic subscription this replaces also received `operator.snapshot`, which
    the publisher sends on the same socket. `_handle_frame` refuses a frame on a topic
    this source does not participate in, and that refusal invalidates the whole
    generation, so an ordinary operator snapshot took the periodic source's authority.

    Connect-before-subscribe is required by the supported macOS/Python/pyzmq
    combination, so the ORDER is part of what this pins.
    """

    class Query:
        async def barrier(self, _nonce: str) -> BarrierQueryResult:
            raise AssertionError

    operations: list[tuple[str, object]] = []
    context = _OrderedSubContext(operations)
    live = SequencedPeriodicLiveSources(
        Query(),
        _context_factory=lambda: context,  # type: ignore[arg-type]
    )
    try:
        await live.start(lambda _reading: None, lambda _event: None)
        assert operations == [
            ("connect", "tcp://127.0.0.1:5555"),
            ("subscribe", DEFAULT_TOPIC),
            ("subscribe", EVENTS_TOPIC),
            ("subscribe", PERIODIC_BARRIER_TOPIC),
        ]
        assert b"" not in [value for name, value in operations if name == "subscribe"], (
            "an all-topic subscription also receives operator.snapshot, which this source "
            "refuses as a protocol violation"
        )
    finally:
        await live.stop()


async def test_the_subscription_and_the_refusal_name_the_same_topics() -> None:
    """A topic in one and not the other is either a silent drop or a fatal refusal."""

    from cryodaq.agents.assistant import periodic_runtime

    assert periodic_runtime._PARTICIPATING_TOPICS == (
        DEFAULT_TOPIC,
        EVENTS_TOPIC,
        PERIODIC_BARRIER_TOPIC,
    )
    # And the publisher's fourth topic is deliberately NOT in it.
    from cryodaq.core.zmq_subprocess import OPERATOR_SNAPSHOT_TOPIC

    assert OPERATOR_SNAPSHOT_TOPIC not in periodic_runtime._PARTICIPATING_TOPICS


async def test_startup_marker_buffers_then_filters_and_dispatches_in_order() -> None:
    context, publisher, address = await _publisher()
    readings: list[str] = []
    events: list[str] = []

    class Query:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            cut, marker = _cut(10, nonce=nonce)
            await publisher.send_multipart([PERIODIC_BARRIER_TOPIC, marker])
            await publisher.send_multipart([DEFAULT_TOPIC, _reading(11, authoritative=False)])
            await publisher.send_multipart([DEFAULT_TOPIC, _reading(12, authoritative=True)])
            await publisher.send_multipart([EVENTS_TOPIC, _event(13)])
            await asyncio.sleep(0.02)
            assert readings == []
            assert events == []
            return BarrierQueryResult(True, nonce, cut, None)

    live = SequencedPeriodicLiveSources(Query(), address)
    try:
        await live.start(
            lambda reading: readings.append(reading.channel),
            lambda event: events.append(str(event["event_type"])),
        )
        cut = await live.ready()
        assert cut.generation == live._generation
        assert readings == ["T12"]
        assert events == ["alarm_fired"]
        assert live.complete_since(cut)
    finally:
        await live.stop()
        publisher.close(linger=0)
        context.term()


async def test_the_engines_fourth_topic_never_reaches_this_source_over_a_real_socket() -> None:
    """The laboratory failure, reproduced through a real PUB/SUB socket rather than a mock.

    The assertions on the mocked socket compare constants: they show the SUBSCRIBE list is
    the intended one, and nothing more. What actually cost the laboratory a week was
    transport behaviour -- an `operator.snapshot` published on the SAME socket arrived,
    `_handle_frame` refused it, and the refusal invalidated the whole live generation.

    So this publishes that fourth topic on the real socket after readiness and then a
    perfectly ordinary reading, and requires the reading to arrive with the generation
    still authoritative. Under the previous `SUBSCRIBE b""` the snapshot was delivered and
    this goes red.
    """

    from cryodaq.core.zmq_subprocess import OPERATOR_SNAPSHOT_TOPIC

    context, publisher, address = await _publisher()
    readings: list[str] = []

    class Query:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            cut, marker = _cut(10, nonce=nonce)
            await publisher.send_multipart([PERIODIC_BARRIER_TOPIC, marker])
            return BarrierQueryResult(True, nonce, cut, None)

    live = SequencedPeriodicLiveSources(Query(), address)
    try:
        await live.start(lambda reading: readings.append(reading.channel), lambda _event: None)
        await live.ready()

        await publisher.send_multipart([OPERATOR_SNAPSHOT_TOPIC, b"an operator snapshot payload"])
        await publisher.send_multipart([DEFAULT_TOPIC, _reading(11, authoritative=True)])
        assert await _until(lambda: readings == ["T11"]), readings
        assert live._invalid is False, "an operator snapshot took the live generation's authority"
        assert live._foreign_topic_frames == 0, "the snapshot should not have been delivered at all"
    finally:
        await live.stop()
        publisher.close(linger=0)
        context.term()


async def test_a_topic_that_extends_a_subscribed_one_is_counted_not_fatal() -> None:
    """ZMQ SUBSCRIBE is a byte PREFIX, so this source cannot choose what arrives.

    Subscribing to `b"readings"` also delivers a future `b"readings.detail"`. No list this
    consumer keeps can prevent that -- the publisher owns its own topics. If admission
    refused such a frame, one new publisher topic would invalidate an unrelated consumer's
    whole generation: the same failure shape that has just been corrected and registered.

    Measured 2026-08-21: no topic in use today is a byte-prefix of another, so this is a
    guard against the next one being added, not a reproduction of a live defect. That is
    exactly why it is written now -- the cost of finding out later is a laboratory week.
    """

    context, publisher, address = await _publisher()
    readings: list[str] = []

    class Query:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            cut, marker = _cut(10, nonce=nonce)
            await publisher.send_multipart([PERIODIC_BARRIER_TOPIC, marker])
            return BarrierQueryResult(True, nonce, cut, None)

    live = SequencedPeriodicLiveSources(Query(), address)
    try:
        await live.start(lambda reading: readings.append(reading.channel), lambda _event: None)
        await live.ready()

        # A topic the publisher might add tomorrow. It starts with a subscribed one, so the
        # socket delivers it whatever this source intended.
        await publisher.send_multipart([DEFAULT_TOPIC + b".detail", b"payload of a topic added later"])
        assert await _until(lambda: live._foreign_topic_frames == 1), (
            "the prefix-extension frame was not delivered"
        )
        assert live._invalid is False, "a topic somebody else added invalidated this generation"

        # And the source still works afterwards, which is the point of not refusing.
        await publisher.send_multipart([DEFAULT_TOPIC, _reading(11, authoritative=True)])
        assert await _until(lambda: readings == ["T11"]), readings
    finally:
        await live.stop()
        publisher.close(linger=0)
        context.term()


async def test_a_foreign_topic_is_ignored_whatever_shape_its_envelope_has() -> None:
    """The frame count is a rule about OUR topics, so it cannot be applied before the topic.

    A future topic is free to use one frame or three. If the count were checked first, such
    a frame would raise and invalidate the generation, and the non-fatal handling would
    have protected only foreign topics that happened to share our two-part envelope --
    which is no protection at all. Driven over the real socket, because the shape of what
    ZMQ delivers is the whole question.
    """

    context, publisher, address = await _publisher()
    readings: list[str] = []

    class Query:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            cut, marker = _cut(10, nonce=nonce)
            await publisher.send_multipart([PERIODIC_BARRIER_TOPIC, marker])
            return BarrierQueryResult(True, nonce, cut, None)

    live = SequencedPeriodicLiveSources(Query(), address)
    try:
        await live.start(lambda reading: readings.append(reading.channel), lambda _event: None)
        await live.ready()

        await publisher.send_multipart([DEFAULT_TOPIC + b".one"])
        await publisher.send_multipart([DEFAULT_TOPIC + b".three", b"second", b"third"])
        assert await _until(lambda: live._foreign_topic_frames == 2), live._foreign_topic_frames
        assert live._invalid is False, "a foreign envelope shape invalidated the generation"

        await publisher.send_multipart([DEFAULT_TOPIC, _reading(11, authoritative=True)])
        assert await _until(lambda: readings == ["T11"]), readings
    finally:
        await live.stop()
        publisher.close(linger=0)
        context.term()


async def test_the_shared_sequence_belongs_only_to_the_topics_that_are_followed() -> None:
    """Ignoring a foreign frame is safe only if that frame never took a sequence number.

    `_allocate_sequence` advances ONE counter for the whole socket, and this subscriber
    validates that counter for continuity. If a future topic were published through the
    allocating path, ignoring its frame would leave a GAP, and the next participating frame
    would invalidate the generation anyway -- the ignore would have bought nothing.

    So the publisher refuses to allocate for a topic outside the sequenced set, and it
    refuses BEFORE the counter moves, so the refusal itself leaves no gap.
    """

    from cryodaq.core.zmq_bridge import _SEQUENCED_TOPICS, ZMQPublisher

    assert _SEQUENCED_TOPICS == periodic_runtime._PARTICIPATING_TOPICS, (
        "the topics that consume the sequence and the topics this source follows must be "
        "the same set, or a published frame creates a gap nobody can close"
    )

    publisher = ZMQPublisher()
    publisher._send_lock = asyncio.Lock()
    before = publisher._sequence
    with pytest.raises(ValueError, match="sequenced topics"):
        await publisher._send_allocated(b"readings.detail", lambda _sequence: b"payload")
    assert publisher._sequence == before, "a refused topic still moved the counter"


async def test_a_publisher_nobody_follows_is_refused_before_it_can_swallow_a_queue() -> None:
    """The refusal has to happen at CONSTRUCTION, because the send path swallows.

    `_publish_loop` catches whatever `_publish_reading` raises and still calls
    `queue.task_done()`. So a publisher built on a topic outside the sequenced set would
    drain its queue while sending nothing: every reading lost, the queue reporting itself
    handled, and the publisher still alive. The per-send guard alone therefore converts a
    wiring mistake into silent data loss, which is the one outcome this project exists to
    prevent.

    No production call site passes a custom topic today, measured 2026-08-21 -- the three
    constructions in `src/` all take the default. This refuses the shape rather than
    waiting for someone to reach it.
    """

    from cryodaq.core.zmq_bridge import ZMQPublisher

    with pytest.raises(ValueError, match="subscribers follow"):
        ZMQPublisher(topic=b"nobody.follows.this")

    # And the ordinary construction is untouched.
    assert ZMQPublisher()._topic == DEFAULT_TOPIC


async def test_a_malformed_frame_on_a_participating_topic_is_still_refused() -> None:
    """The boundary: ignoring a foreign topic must not soften the real contract.

    A frame that is not two parts, or a reading whose shape is wrong on a topic this
    source DOES participate in, is a protocol violation and still invalidates the
    generation. Only "this frame is not addressed to me" became non-fatal.
    """

    live = SequencedPeriodicLiveSources(_UnusedQuery())
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()

    with pytest.raises(ValueError, match="invalid multipart frame"):
        await live._handle_frame([DEFAULT_TOPIC])
    with pytest.raises(ValueError, match="invalid multipart frame"):
        await live._handle_frame([DEFAULT_TOPIC, b"one", b"two"])
    assert live._foreign_topic_frames == 0


class _UnusedQuery:
    async def barrier(self, _nonce: str) -> BarrierQueryResult:
        raise AssertionError("this test never reaches the barrier")


async def test_startup_retries_dropped_first_marker_with_fresh_matching_nonce() -> None:
    nonces: list[str] = []
    readings: list[str] = []

    class Query:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            nonces.append(nonce)
            cut, marker = _cut(len(nonces), nonce=nonce)
            if len(nonces) > 1:
                await live._handle_frame([PERIODIC_BARRIER_TOPIC, marker])
                await live._handle_frame([DEFAULT_TOPIC, _reading(len(nonces) + 1, authoritative=True)])
            return BarrierQueryResult(True, nonce, cut, None)

    live = SequencedPeriodicLiveSources(Query(), ready_timeout_s=0.05)
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._connected = asyncio.Event()
    live._connected.set()
    live._on_reading = lambda reading: readings.append(reading.channel)
    live._on_event = lambda _event: None
    try:
        cut = await live.ready()
        assert len(nonces) == 2
        assert len(set(nonces)) == 2
        assert cut.sequence == 2
        assert readings == ["T3"]
        assert live.complete_since(cut)
    finally:
        live._running = False
        await live.stop()


async def test_startup_retries_transport_unavailable_before_any_evidence() -> None:
    nonces: list[str] = []

    class Query:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            nonces.append(nonce)
            if len(nonces) == 1:
                return BarrierQueryResult(False, None, None, "transport_unavailable")
            cut, marker = _cut(1, nonce=nonce)
            await live._handle_frame([PERIODIC_BARRIER_TOPIC, marker])
            return BarrierQueryResult(True, nonce, cut, None)

    live = SequencedPeriodicLiveSources(Query(), ready_timeout_s=0.05)
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._connected = asyncio.Event()
    live._connected.set()
    try:
        cut = await live.ready()
        assert cut.sequence == 1
        assert len(nonces) == 2
        assert len(set(nonces)) == 2
    finally:
        live._running = False
        await live.stop()


async def test_startup_never_retries_semantic_query_failure() -> None:
    calls = 0

    class Query:
        async def barrier(self, _nonce: str) -> BarrierQueryResult:
            nonlocal calls
            calls += 1
            return BarrierQueryResult(False, None, None, "response_invalid")

    live = SequencedPeriodicLiveSources(Query(), ready_timeout_s=0.05)
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._connected = asyncio.Event()
    live._connected.set()
    try:
        with pytest.raises(PeriodicLiveDiscontinuity):
            await live.ready()
        assert calls == 1
    finally:
        await live.stop()


async def test_startup_never_retries_transport_failure_after_marker_evidence() -> None:
    calls = 0

    class Query:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            nonlocal calls
            calls += 1
            _cut_value, marker = _cut(1, nonce=nonce)
            await live._handle_frame([PERIODIC_BARRIER_TOPIC, marker])
            return BarrierQueryResult(False, None, None, "transport_unavailable")

    live = SequencedPeriodicLiveSources(Query(), ready_timeout_s=0.05)
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._connected = asyncio.Event()
    live._connected.set()
    try:
        with pytest.raises(PeriodicLiveDiscontinuity):
            await live.ready()
        assert calls == 1
    finally:
        await live.stop()


async def test_startup_transport_retry_exhaustion_is_fixed_and_bounded() -> None:
    nonces: list[str] = []

    class Query:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            nonces.append(nonce)
            return BarrierQueryResult(False, None, None, "transport_unavailable")

    live = SequencedPeriodicLiveSources(Query(), ready_timeout_s=0.05)
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._connected = asyncio.Event()
    live._connected.set()
    try:
        with pytest.raises(PeriodicLiveDiscontinuity):
            await live.ready()
        assert len(nonces) == periodic_runtime._READY_MAX_ATTEMPTS
        assert len(set(nonces)) == periodic_runtime._READY_MAX_ATTEMPTS
        assert live._invalid
    finally:
        await live.stop()


async def test_adapter_retries_fresh_req_when_server_binds_after_first_failure() -> None:
    context, publisher, pub_address = await _publisher()
    cmd_address = f"tcp://127.0.0.1:{_free_loopback_port()}"
    engine_query = PeriodicEngineQuery(cmd_address, timeout_s=0.05)
    first_failure = asyncio.Event()
    nonces: list[str] = []

    class ObservedQuery:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            nonces.append(nonce)
            result = await engine_query.barrier(nonce)
            if len(nonces) == 1:
                assert not result.ok
                assert result.error_code == "transport_unavailable"
                first_failure.set()
            return result

    live = SequencedPeriodicLiveSources(ObservedQuery(), pub_address, ready_timeout_s=0.2)
    server: zmq.asyncio.Socket | None = None
    server_task: asyncio.Task[None] | None = None
    ready_task: asyncio.Task[LiveSourceCut] | None = None
    try:
        await live.start(lambda _reading: None, lambda _event: None)
        ready_task = asyncio.create_task(live.ready())
        await asyncio.wait_for(first_failure.wait(), timeout=1)

        server = context.socket(zmq.REP)
        server.setsockopt(zmq.LINGER, 0)
        server.bind(cmd_address)

        async def serve() -> None:
            sequence = 1
            while True:
                request = json.loads((await server.recv()).decode())
                nonce = request["nonce"]
                _cut_value, marker = _cut(sequence, nonce=nonce)
                await publisher.send_multipart([PERIODIC_BARRIER_TOPIC, marker])
                response = json.loads(marker)
                response["ok"] = True
                await server.send(json.dumps(response).encode())
                sequence += 1

        server_task = asyncio.create_task(serve())
        cut = await asyncio.wait_for(ready_task, timeout=2)
        assert cut.sequence >= 1
        assert len(nonces) >= 2
        assert nonces[0] != nonces[1]
    finally:
        if ready_task is not None and not ready_task.done():
            ready_task.cancel()
            await asyncio.gather(ready_task, return_exceptions=True)
        if server_task is not None:
            server_task.cancel()
            await asyncio.gather(server_task, return_exceptions=True)
        await live.stop()
        await engine_query.close()
        if server is not None:
            server.close(linger=0)
        publisher.close(linger=0)
        context.term()


async def test_startup_marker_retry_exhaustion_fails_closed_at_fixed_bound() -> None:
    nonces: list[str] = []

    class Query:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            nonces.append(nonce)
            cut, _marker = _cut(len(nonces), nonce=nonce)
            return BarrierQueryResult(True, nonce, cut, None)

    live = SequencedPeriodicLiveSources(Query(), ready_timeout_s=0.05)
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._connected = asyncio.Event()
    live._connected.set()
    try:
        with pytest.raises(PeriodicLiveDiscontinuity):
            await live.ready()
        assert len(nonces) == periodic_runtime._READY_MAX_ATTEMPTS
        assert len(set(nonces)) == periodic_runtime._READY_MAX_ATTEMPTS
        assert live._invalid
    finally:
        await live.stop()


async def test_retired_marker_never_satisfies_a_later_fresh_nonce() -> None:
    nonces: list[str] = []

    class Query:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            nonces.append(nonce)
            cut, _current_marker = _cut(len(nonces), nonce=nonce)
            if len(nonces) > 1:
                _stale_cut, stale_marker = _cut(len(nonces) - 1, nonce=nonces[-2])
                await live._handle_frame([PERIODIC_BARRIER_TOPIC, stale_marker])
            return BarrierQueryResult(True, nonce, cut, None)

    live = SequencedPeriodicLiveSources(Query(), ready_timeout_s=0.05)
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._connected = asyncio.Event()
    live._connected.set()
    try:
        with pytest.raises(PeriodicLiveDiscontinuity):
            await live.ready()
        assert len(nonces) == periodic_runtime._READY_MAX_ATTEMPTS
        assert len(set(nonces)) == periodic_runtime._READY_MAX_ATTEMPTS
        assert live._session_id is None
        assert live._invalid
    finally:
        await live.stop()


async def test_sequence_gap_invalidates_and_wait_raises_fixed_error() -> None:
    context, publisher, address = await _publisher()

    class Query:
        async def barrier(self, nonce: str) -> BarrierQueryResult:
            cut, marker = _cut(1, nonce=nonce)
            await publisher.send_multipart([PERIODIC_BARRIER_TOPIC, marker])
            return BarrierQueryResult(True, nonce, cut, None)

    live = SequencedPeriodicLiveSources(Query(), address)
    try:
        await live.start(lambda _reading: None, lambda _event: None)
        cut = await live.ready()
        await publisher.send_multipart([DEFAULT_TOPIC, _reading(3, authoritative=True)])
        with pytest.raises(PeriodicLiveDiscontinuity, match="periodic live stream discontinuity"):
            await asyncio.wait_for(live.wait(), timeout=1)
        assert not live.complete_since(cut)
    finally:
        await live.stop()
        publisher.close(linger=0)
        context.term()


async def test_concurrent_ready_is_rejected_without_second_query() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    class Query:
        async def barrier(self, _nonce: str) -> BarrierQueryResult:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            raise RuntimeError

    live = SequencedPeriodicLiveSources(Query())
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._connected = asyncio.Event()
    live._connected.set()
    first = asyncio.create_task(live.ready())
    await started.wait()
    with pytest.raises(RuntimeError, match="already in flight"):
        await live.ready()
    release.set()
    with pytest.raises(PeriodicLiveDiscontinuity):
        await first
    assert calls == 1
    live._running = False
    await live.stop()


async def test_generation_is_instance_unique_and_old_cut_never_aliases() -> None:
    class Query:
        async def barrier(self, _nonce: str) -> BarrierQueryResult:
            raise AssertionError

    first = SequencedPeriodicLiveSources(Query())
    second = SequencedPeriodicLiveSources(Query())
    assert first._generation != second._generation
    old = LiveSourceCut(SESSION, first._generation, 1, 10.5, 3, 4, 7, TOKEN)
    second._running = True
    second._session_id = SESSION
    second._last_sequence = 20
    second._drop_baseline = 3
    second._failure_baseline = 4
    assert not second.complete_since(old)
    second._running = False
    await second.stop()


async def test_forbidden_marker_ok_prefix_topic_and_changed_baseline_fail_closed() -> None:
    class Query:
        async def barrier(self, _nonce: str) -> BarrierQueryResult:
            raise AssertionError

    live = SequencedPeriodicLiveSources(Query())
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._ready_active = True
    live._ready_nonce = "a" * 32
    live._ready_marker = asyncio.get_running_loop().create_future()
    _cut_value, marker = _cut(1, nonce="a" * 32)
    forbidden = json.loads(marker)
    forbidden["ok"] = True
    with pytest.raises(ValueError, match="marker shape"):
        await live._handle_frame([PERIODIC_BARRIER_TOPIC, json.dumps(forbidden).encode()])
    # DELIBERATE REVERSAL, 2026-08-21. This line used to require a refusal for a topic that
    # merely EXTENDS a subscribed one, and that is now wrong: ZMQ SUBSCRIBE matches by byte
    # prefix, so subscribing to b"readings" delivers a future b"readings.detail" whatever
    # this source intends. Refusing it invalidates the whole live generation -- so one new
    # topic on the publisher would kill an unrelated consumer, which is the exact failure
    # this branch exists to correct, arriving by a second door.
    #
    # Fail-closed is preserved where it means something: the frame is not ACTED ON, and no
    # reading from it reaches the broker. It is counted instead of being made fatal.
    # See test_a_topic_that_extends_a_subscribed_one_is_counted_not_fatal.
    before = live._foreign_topic_frames
    await live._handle_frame([DEFAULT_TOPIC + b".suffix", b"x"])
    assert live._foreign_topic_frames == before + 1

    live._session_id = SESSION
    live._last_sequence = 1
    live._drop_baseline = 3
    live._failure_baseline = 4
    _changed, changed_marker = _cut(2, nonce="a" * 32, drops=4)
    with pytest.raises(ValueError, match="counters"):
        await live._handle_frame([PERIODIC_BARRIER_TOPIC, changed_marker])
    live._running = False
    await live.stop()


async def test_provisional_byte_cap_event_authority_and_async_callback_fail_closed() -> None:
    class Query:
        async def barrier(self, _nonce: str) -> BarrierQueryResult:
            raise AssertionError

    live = SequencedPeriodicLiveSources(Query(), max_provisional_bytes=1024)
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._on_reading = lambda _reading: None
    live._on_event = lambda _event: None
    live._provisional_cut = LiveSourceCut(SESSION, live._generation, 1, 10.5, 3, 4, 7, TOKEN)
    live._provisional_last = 1
    await live._handle_frame([DEFAULT_TOPIC, _reading(2, authoritative=True, metadata={"pad": "x" * 700})])
    with pytest.raises(ValueError, match="byte overflow"):
        await live._handle_frame([DEFAULT_TOPIC, _reading(3, authoritative=True, metadata={"pad": "x" * 700})])

    authoritative_event = json.loads(_event(2))
    authoritative_event["transport"]["persistence_authoritative"] = True
    with pytest.raises(ValueError, match="cannot claim"):
        live._event(json.dumps(authoritative_event).encode())

    async def callback(_reading: object) -> None:
        await asyncio.sleep(0)

    live._session_id = SESSION
    live._last_sequence = 3
    live._on_reading = callback
    with pytest.raises(ValueError, match="synchronous"):
        await live._handle_frame([DEFAULT_TOPIC, _reading(4, authoritative=True)])
    live._running = False
    await live.stop()


async def test_msgpack_duplicate_keys_and_monitor_stopped_are_pinned() -> None:
    packer = msgpack.Packer(use_bin_type=True)
    duplicate = b"".join(
        [
            packer.pack_map_header(2),
            packer.pack("transport"),
            packer.pack({}),
            packer.pack("transport"),
            packer.pack({}),
        ]
    )
    with pytest.raises(ValueError, match="msgpack object key"):
        SequencedPeriodicLiveSources._reading(duplicate)
    assert zmq.EVENT_MONITOR_STOPPED in periodic_runtime._MONITOR_FAILURE_EVENTS


async def test_monitor_tolerates_only_preconnect_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    class Query:
        async def barrier(self, _nonce: str) -> BarrierQueryResult:
            raise AssertionError

    class Monitor:
        def __init__(self) -> None:
            self.events: asyncio.Queue[int] = asyncio.Queue()

        async def recv_multipart(self) -> list[int]:
            return [await self.events.get()]

        def close(self, *, linger: int) -> None:
            assert linger == 0

    monitor = Monitor()
    monkeypatch.setattr(
        periodic_runtime,
        "parse_monitor_message",
        lambda frames: {"event": frames[0]},
    )
    live = SequencedPeriodicLiveSources(Query())
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._connected = asyncio.Event()
    live._monitor = monitor  # type: ignore[assignment]
    live._monitor_task = asyncio.create_task(live._monitor_loop())
    await monitor.events.put(zmq.EVENT_CONNECT_RETRIED)
    await asyncio.sleep(0)
    assert not live._invalid
    assert not live._connected.is_set()

    await monitor.events.put(zmq.EVENT_CONNECTED)
    await asyncio.wait_for(live._connected.wait(), timeout=1)
    await monitor.events.put(zmq.EVENT_CONNECT_RETRIED)
    await asyncio.wait_for(live._failure, timeout=1)
    assert live._invalid
    await live.stop()


async def test_stop_is_shared_idempotent_and_terminal() -> None:
    class Query:
        async def barrier(self, _nonce: str) -> BarrierQueryResult:
            raise AssertionError

    live = SequencedPeriodicLiveSources(Query())
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    await asyncio.gather(live.stop(), live.stop())
    await live.stop()
    assert live._closed
    assert live._session_id is None
    with pytest.raises(RuntimeError, match="closed"):
        await live.start(lambda _reading: None, lambda _event: None)


async def test_invalidation_wakes_connect_gate_and_forbids_later_callback() -> None:
    class Query:
        async def barrier(self, _nonce: str) -> BarrierQueryResult:
            raise AssertionError

    observed: list[str] = []
    live = SequencedPeriodicLiveSources(Query())
    live._running = True
    live._failure = asyncio.get_running_loop().create_future()
    live._connected = asyncio.Event()
    live._session_id = SESSION
    live._last_sequence = 1
    live._on_reading = lambda reading: observed.append(reading.channel)
    live._on_event = lambda _event: None
    live._invalidate()
    assert live._connected.is_set()
    with pytest.raises(PeriodicLiveDiscontinuity):
        await live._handle_frame([DEFAULT_TOPIC, _reading(2, authoritative=True)])
    assert observed == []
    await live.stop()


async def test_closed_barrier_failure_maps_to_fixed_transport_code() -> None:
    response = json.dumps(
        {
            "ok": False,
            "proto": PROTOCOL_VERSION,
            "schema": PERIODIC_BARRIER_SCHEMA,
            "error_code": "barrier_unavailable",
        }
    ).encode()
    context = _FakeContext(response)
    query = PeriodicEngineQuery(_context_factory=lambda: context)  # type: ignore[arg-type]
    result = await query.barrier("a" * 32)
    assert not result.ok
    assert result.error_code == "transport_unavailable"
    assert context.socket_instance.closed
    assert context.terminated


@pytest.mark.parametrize(
    "response",
    [
        json.dumps(
            {
                "ok": True,
                "proto": PROTOCOL_VERSION,
                "schema": PERIODIC_QUERY_SCHEMA,
                "state_revision": 1,
                "state_token": EMPTY_TOKEN,
                "active": {},
                "private": "forbidden",
            }
        ).encode(),
        json.dumps(
            {
                "ok": True,
                "proto": PROTOCOL_VERSION,
                "schema": PERIODIC_QUERY_SCHEMA,
                "state_revision": 1,
                "state_token": TOKEN,
                "active": {},
            }
        ).encode(),
        b" " * (60 * 1024 + 1),
    ],
    ids=("extra-field", "token-mismatch", "wire-oversize"),
)
async def test_snapshot_extra_token_mismatch_and_full_wire_oversize_fail_closed(
    response: bytes,
) -> None:
    context = _FakeContext(response)
    query = PeriodicEngineQuery(_context_factory=lambda: context)  # type: ignore[arg-type]
    result = await query.alarm_snapshot()
    assert not result.ok
    assert result.error_code == "response_invalid"
    assert context.socket_instance.closed
    assert context.terminated


async def test_query_cancellation_closes_then_fresh_operation_succeeds() -> None:
    blocked: asyncio.Future[bytes] = asyncio.get_running_loop().create_future()
    nonce = "b" * 32
    _cut_value, marker = _cut(5, nonce=nonce)
    success = json.loads(marker)
    success["ok"] = True
    first_context = _FakeContext(blocked)
    second_context = _FakeContext(json.dumps(success).encode())
    contexts = [first_context, second_context]

    def factory() -> _FakeContext:
        return contexts.pop(0)

    query = PeriodicEngineQuery(_context_factory=factory)  # type: ignore[arg-type]
    task = asyncio.create_task(query.barrier(nonce))
    await first_context.socket_instance.sent.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert first_context.socket_instance.closed
    assert first_context.terminated

    result = await query.barrier(nonce)
    assert result.ok
    assert result.cut is not None and result.cut.sequence == 5
    assert second_context.socket_instance.closed
    assert second_context.terminated


async def test_query_uses_fresh_req_and_parses_closed_responses() -> None:
    context = zmq.asyncio.Context()
    server = context.socket(zmq.REP)
    server.setsockopt(zmq.LINGER, 0)
    port = server.bind_to_random_port("tcp://127.0.0.1")
    address = f"tcp://127.0.0.1:{port}"
    query = PeriodicEngineQuery(address)
    nonce = "a" * 32

    async def serve() -> None:
        first = json.loads((await server.recv()).decode())
        assert first == {
            "cmd": "periodic_subscription_barrier",
            "nonce": nonce,
            "schema": PERIODIC_QUERY_SCHEMA,
        }
        cut, marker = _cut(5, nonce=nonce)
        del cut
        reply = json.loads(marker)
        reply["ok"] = True
        await server.send(json.dumps(reply).encode())
        second = json.loads((await server.recv()).decode())
        assert second == {"cmd": "periodic_alarm_snapshot", "schema": PERIODIC_QUERY_SCHEMA}
        await server.send(
            json.dumps(
                {
                    "ok": True,
                    "proto": PROTOCOL_VERSION,
                    "schema": PERIODIC_QUERY_SCHEMA,
                    "state_revision": 9,
                    "state_token": EMPTY_TOKEN,
                    "active": {},
                }
            ).encode()
        )

    task = asyncio.create_task(serve())
    try:
        barrier = await query.barrier(nonce)
        snapshot = await query.alarm_snapshot()
        assert barrier.ok and barrier.cut is not None and barrier.cut.sequence == 5
        assert snapshot.ok and snapshot.state_revision == 9
        await task
    finally:
        await query.close()
        server.close(linger=0)
        context.term()


@pytest.mark.parametrize(
    "body",
    [
        b'{"ok":true,"ok":true}',
        (
            f'{{"ok":true,"proto":{PROTOCOL_VERSION},'
            '"schema":"cryodaq.periodic.query/v1","state_revision":true,'
            '"state_token":"x","active":{}}}'
        ).encode(),
        b'{"ok":true,"proto":1e999,"schema":"cryodaq.periodic.query/v1","state_revision":1,"state_token":"x","active":{}}',
    ],
)
async def test_query_rejects_duplicate_boolean_integer_and_nonfinite(body: bytes) -> None:
    context = zmq.asyncio.Context()
    server = context.socket(zmq.REP)
    server.setsockopt(zmq.LINGER, 0)
    port = server.bind_to_random_port("tcp://127.0.0.1")
    query = PeriodicEngineQuery(f"tcp://127.0.0.1:{port}")

    async def serve() -> None:
        await server.recv()
        await server.send(body)

    task = asyncio.create_task(serve())
    try:
        result = await query.alarm_snapshot()
        assert not result.ok
        assert result.error_code == "response_invalid"
        await task
    finally:
        await query.close()
        server.close(linger=0)
        context.term()


async def test_engine_disconnect_invalidates_cached_context() -> None:
    first_cycle_done = asyncio.Event()
    allow_disconnect = asyncio.Event()
    disconnect_cycle_done = asyncio.Event()
    now = datetime.now(UTC).isoformat()

    def receipt(scope: str) -> dict[str, object]:
        return {
            "schema": "assistant_context_receipt_v1",
            "log_scope": scope,
            "experiment_id": "exp-1",
            "engine_incarnation": "engine-1",
            "experiment_incarnation": "experiment-1",
            "revision": 7,
            "order": 11,
            "query_start": None,
            "query_end": None,
            "received_at": now,
            "freshness_s": 30.0,
        }

    class Client:
        calls = 0

        async def call(self, command: dict[str, object]) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                assert command == {"cmd": "experiment_status"}
                return {
                    "ok": True,
                    "active_experiment": {"experiment_id": "exp-1"},
                    "current_phase": "COOLDOWN",
                    "phases": [],
                    "scope_receipt": receipt("experiment_status"),
                }
            if self.calls == 2:
                assert command == {"cmd": "get_sensor_diagnostics"}
                first_cycle_done.set()
                return {
                    "ok": True,
                    "summary": {
                        "total_channels": 1,
                        "healthy": 1,
                        "warning": 0,
                        "critical": 0,
                        "worst_channel": "T1",
                        "worst_score": 100,
                        "worst_flags": [],
                    },
                    "scope_receipt": receipt("sensor_diagnostics"),
                }
            await allow_disconnect.wait()
            if self.calls == 3:
                return {"ok": False, "error": "engine disconnected"}
            disconnect_cycle_done.set()
            return {"ok": False, "error": "engine disconnected"}

    cache = _RemoteEngineStateCache(Client(), poll_interval_s=0.0)
    await cache.start()
    try:
        await asyncio.wait_for(first_cycle_done.wait(), 1.0)
        await asyncio.sleep(0)
        assert cache.active_experiment_id == "exp-1"
        assert cache.get_current_phase() == "COOLDOWN"
        assert cache.get_summary() is not None

        allow_disconnect.set()
        await asyncio.wait_for(disconnect_cycle_done.wait(), 1.0)
        await asyncio.sleep(0)

        assert cache.active_experiment_id is None
        assert cache.get_current_phase() is None
        assert cache.get_phase_history() == []
        assert cache.get_summary() is None
    finally:
        await cache.stop()


def _status_receipt(scope: str, *, experiment_id: str = "exp-1") -> dict[str, object]:
    return {
        "schema": "assistant_context_receipt_v1",
        "log_scope": scope,
        "experiment_id": experiment_id,
        "engine_incarnation": "engine-1",
        "experiment_incarnation": "experiment-1",
        "revision": 7,
        "order": 11,
        "query_start": None,
        "query_end": None,
        "received_at": datetime.now(UTC).isoformat(),
        "freshness_s": 30.0,
    }


async def test_missing_phase_keys_in_reply_resolve_to_unavailable_not_empty() -> None:
    """A receipt-valid experiment_status reply that is missing BOTH
    ``current_phase`` and ``phases`` entirely (schema skew / engine defect —
    not an explicit empty value) must not be accepted as "an active
    experiment with no phases". The whole reply is structurally untrustworthy,
    so it must be invalidated exactly like a failed receipt validation
    invalidates the cache (active_experiment_id -> None too), not silently
    downgraded into a confident-but-wrong empty phase history.
    """
    first_cycle_done = asyncio.Event()
    park = asyncio.Event()

    class Client:
        calls = 0

        async def call(self, command: dict[str, object]) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                assert command == {"cmd": "experiment_status"}
                # current_phase / phases deliberately absent — the defect.
                return {
                    "ok": True,
                    "active_experiment": {"experiment_id": "exp-1"},
                    "scope_receipt": _status_receipt("experiment_status"),
                }
            if self.calls == 2:
                assert command == {"cmd": "get_sensor_diagnostics"}
                first_cycle_done.set()
                return {"ok": False, "error": "not needed for this test"}
            await park.wait()
            raise AssertionError("parked client unexpectedly resumed")

    cache = _RemoteEngineStateCache(Client(), poll_interval_s=0.0)
    await cache.start()
    try:
        await asyncio.wait_for(first_cycle_done.wait(), 1.0)
        await asyncio.sleep(0)
        assert cache.active_experiment_id is None
        assert cache.get_current_phase() is None
        assert cache.get_phase_history() == []
    finally:
        await cache.stop()


async def test_malformed_receipt_valid_diagnostics_summary_is_unavailable_not_zero() -> None:
    published = asyncio.Event()
    park = asyncio.Event()

    class Client:
        calls = 0

        async def call(self, command: dict[str, object]) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                assert command == {"cmd": "experiment_status"}
                return {
                    "ok": True,
                    "active_experiment": {"experiment_id": "exp-1"},
                    "current_phase": "COOLDOWN",
                    "phases": [],
                    "scope_receipt": _status_receipt("experiment_status"),
                }
            if self.calls == 2:
                assert command == {"cmd": "get_sensor_diagnostics"}
                published.set()
                return {
                    "ok": True,
                    "summary": {"total_channels": 1, "healthy": 1, "critical": 0},
                    "scope_receipt": _status_receipt("sensor_diagnostics"),
                }
            await park.wait()
            raise AssertionError("parked client unexpectedly resumed")

    cache = _RemoteEngineStateCache(Client(), poll_interval_s=0.0)
    await cache.start()
    try:
        await asyncio.wait_for(published.wait(), 1.0)
        await asyncio.sleep(0)
        assert cache.active_experiment_id == "exp-1"
        assert cache.get_summary() is None
    finally:
        await cache.stop()


async def test_malformed_sensor_summary_renders_unavailable_not_zero() -> None:
    from types import SimpleNamespace

    from cryodaq.agents.assistant.live.context_builder import PeriodicReportContext

    context = PeriodicReportContext(
        window_minutes=60,
        active_experiment_id=None,
        active_experiment_phase=None,
        sensor_health_summary=SimpleNamespace(
            total_channels=1,
            healthy=True,
            critical=0,
            worst_channel="T1",
            worst_score=0,
            worst_flags=[],
        ),
    )

    assert "недоступ" in context.to_template_dict()["sensor_health_section"]


async def test_explicit_empty_phases_with_keys_present_is_legitimate_empty_history() -> None:
    """A genuinely fresh experiment (no phase transition yet) still gets
    BOTH keys from the real engine's ExperimentManager.get_status_payload()
    (core/experiment.py) — current_phase=None, phases=[] — present but
    empty, never absent. That is a legitimate, known, empty phase history
    for a known active experiment, and must resolve normally (NOT to
    unavailable) — distinguishing an absent key (unknown) from an explicit
    empty value (known-and-empty) is exactly the invariant this defect is
    about.
    """
    first_cycle_done = asyncio.Event()
    park = asyncio.Event()

    class Client:
        calls = 0

        async def call(self, command: dict[str, object]) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                assert command == {"cmd": "experiment_status"}
                return {
                    "ok": True,
                    "active_experiment": {"experiment_id": "exp-1"},
                    "current_phase": None,
                    "phases": [],
                    "scope_receipt": _status_receipt("experiment_status"),
                }
            if self.calls == 2:
                assert command == {"cmd": "get_sensor_diagnostics"}
                first_cycle_done.set()
                return {"ok": False, "error": "not needed for this test"}
            await park.wait()
            raise AssertionError("parked client unexpectedly resumed")

    cache = _RemoteEngineStateCache(Client(), poll_interval_s=0.0)
    await cache.start()
    try:
        await asyncio.wait_for(first_cycle_done.wait(), 1.0)
        await asyncio.sleep(0)
        assert cache.active_experiment_id == "exp-1"
        assert cache.get_current_phase() is None
        assert cache.get_phase_history() == []
    finally:
        await cache.stop()


async def test_complete_valid_status_reply_is_unaffected_by_key_presence_check() -> None:
    """A fully-populated, receipt-valid experiment_status reply (both keys
    present with real values) must behave exactly as before this fix."""
    first_cycle_done = asyncio.Event()
    park = asyncio.Event()

    class Client:
        calls = 0

        async def call(self, command: dict[str, object]) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                assert command == {"cmd": "experiment_status"}
                return {
                    "ok": True,
                    "active_experiment": {"experiment_id": "exp-1"},
                    "current_phase": "COOLDOWN",
                    "phases": [{"phase": "COOLDOWN"}],
                    "scope_receipt": _status_receipt("experiment_status"),
                }
            if self.calls == 2:
                assert command == {"cmd": "get_sensor_diagnostics"}
                first_cycle_done.set()
                return {"ok": False, "error": "not needed for this test"}
            await park.wait()
            raise AssertionError("parked client unexpectedly resumed")

    cache = _RemoteEngineStateCache(Client(), poll_interval_s=0.0)
    await cache.start()
    try:
        await asyncio.wait_for(first_cycle_done.wait(), 1.0)
        await asyncio.sleep(0)
        assert cache.active_experiment_id == "exp-1"
        assert cache.get_current_phase() == "COOLDOWN"
        assert cache.get_phase_history() == [{"phase": "COOLDOWN"}]
    finally:
        await cache.stop()


async def test_live_runtime_consumes_context_receipt_and_expires_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.agents import assistant_main
    from cryodaq.agents.assistant.shared import context_reader

    published = asyncio.Event()
    park = asyncio.Event()
    received_at = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)

    class _ClockDateTime:
        current = received_at

        @classmethod
        def fromisoformat(cls, value: str) -> datetime:
            return datetime.fromisoformat(value)

        @classmethod
        def now(cls, tz=None) -> datetime:
            del tz
            return cls.current

        @classmethod
        def fromtimestamp(cls, value: float, tz=None) -> datetime:
            return datetime.fromtimestamp(value, tz=tz)

    monkeypatch.setattr(context_reader, "datetime", _ClockDateTime)
    monkeypatch.setattr(assistant_main, "datetime", _ClockDateTime)

    def fresh_receipt(scope: str) -> dict[str, object]:
        return {
            "schema": "assistant_context_receipt_v1",
            "log_scope": scope,
            "experiment_id": "exp-fresh",
            "engine_incarnation": "engine-current",
            "experiment_incarnation": "experiment-current",
            "revision": 3,
            "order": 5,
            "query_start": None,
            "query_end": None,
            "received_at": received_at.isoformat(),
            "freshness_s": 5.0,
        }

    class Client:
        calls = 0

        async def call(self, command: dict[str, object]) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                assert command == {"cmd": "experiment_status"}
                return {
                    "ok": True,
                    "active_experiment": {"experiment_id": "exp-fresh"},
                    "current_phase": "COOLDOWN",
                    "phases": [{"phase": "COOLDOWN"}],
                    "scope_receipt": fresh_receipt("experiment_status"),
                }
            if self.calls == 2:
                assert command == {"cmd": "get_sensor_diagnostics"}
                return {
                    "ok": True,
                    "summary": {
                        "total_channels": 1,
                        "healthy": 1,
                        "warning": 0,
                        "critical": 0,
                        "worst_channel": "T1",
                        "worst_score": 100,
                        "worst_flags": [],
                    },
                    "scope_receipt": fresh_receipt("sensor_diagnostics"),
                }
            published.set()
            await park.wait()
            raise AssertionError("parked client unexpectedly resumed")

    cache = _RemoteEngineStateCache(Client(), poll_interval_s=0.0)
    await cache.start()
    try:
        await asyncio.wait_for(published.wait(), 1.0)
        assert cache.active_experiment_id == "exp-fresh"
        assert cache.get_current_phase() == "COOLDOWN"
        assert cache.get_phase_history() == [{"phase": "COOLDOWN"}]
        summary = cache.get_summary()
        assert summary is not None
        assert summary.healthy == 1

        _ClockDateTime.current = datetime(2026, 7, 22, 12, 0, 6, tzinfo=UTC)
        assert cache.active_experiment_id is None
        assert cache.get_current_phase() is None
        assert cache.get_phase_history() == []
        assert cache.get_summary() is None
    finally:
        await cache.stop()


def _published_reading_bytes(*, descriptor_envelope: bytes | None) -> bytes:
    """Build a reading frame with the PRODUCTION packer.

    Hand-building the payload is how producer and consumer drift apart without a test
    noticing: the consumer's expectation gets written twice, once in production and once
    in the test, and the producer is in neither. `_pack_reading` is what the engine
    actually calls, so a rename or an omission there reddens this instead of reaching a
    laboratory run.
    """

    from datetime import UTC, datetime

    from cryodaq.core.zmq_bridge import _pack_reading
    from cryodaq.drivers.base import ChannelStatus, Reading

    reading = Reading(
        timestamp=datetime.fromtimestamp(1_700_000_000.0, tz=UTC),
        instrument_id="ls",
        channel="T2",
        value=2.0,
        unit="K",
        status=ChannelStatus.OK,
        raw=None,
        metadata={},
    )
    return _pack_reading(
        reading,
        transport={
            "schema": "cryodaq.periodic.stream/v1",
            "session_id": "1" * 32,
            "sequence": 1,
            "persistence_authoritative": True,
        },
        descriptor_envelope=descriptor_envelope,
    )


async def test_a_reading_carrying_a_descriptor_envelope_is_accepted() -> None:
    """The publisher attaches `desc` whenever it has a channel-descriptor envelope.

    Its own docstring calls that key additive and expects a consumer to ignore unknown
    keys structurally. This consumer did not: it compared the key set with `!=`, so an
    ordinary reading with a descriptor was refused exactly as hard as one missing a
    required field -- and the refusal invalidates the whole generation.

    Measured on Ubuntu 22.04 on 2026-08-20, after the topic fix removed the previous
    dominant cause, this became the most frequent reason the source lost authority.
    """

    from cryodaq.agents.assistant.periodic_runtime import SequencedPeriodicLiveSources

    frame = _published_reading_bytes(descriptor_envelope=b"an opaque descriptor envelope")
    transport, reading = SequencedPeriodicLiveSources._reading(frame)

    assert reading.channel == "T2"
    assert transport.sequence == 1


async def test_a_reading_without_a_descriptor_is_still_accepted() -> None:
    """The publisher omits the key entirely when it has nothing to attach."""

    from cryodaq.agents.assistant.periodic_runtime import SequencedPeriodicLiveSources

    frame = _published_reading_bytes(descriptor_envelope=None)
    _transport, reading = SequencedPeriodicLiveSources._reading(frame)

    assert reading.channel == "T2"


async def test_a_reading_missing_a_required_field_is_still_refused() -> None:
    """Accepting a documented optional field must not relax the contract."""

    import msgpack
    import pytest as _pytest

    from cryodaq.agents.assistant.periodic_runtime import SequencedPeriodicLiveSources

    # The production packer always writes the required keys, so this one is built by
    # REMOVING a key from a real frame rather than by writing a payload from scratch.
    frame = _published_reading_bytes(descriptor_envelope=None)
    payload = msgpack.unpackb(frame, raw=False)
    del payload["transport"]

    with _pytest.raises(ValueError, match="missing="):
        SequencedPeriodicLiveSources._reading(msgpack.packb(payload, use_bin_type=True))


async def test_an_unknown_field_is_refused_and_not_echoed() -> None:
    """Fail-closed on a key nobody documented -- and the message must not carry the wire."""

    import msgpack
    import pytest as _pytest

    from cryodaq.agents.assistant.periodic_runtime import SequencedPeriodicLiveSources

    frame = _published_reading_bytes(descriptor_envelope=None)
    payload = msgpack.unpackb(frame, raw=False)
    payload["smuggled_secret_name"] = 1

    with _pytest.raises(ValueError) as raised:
        SequencedPeriodicLiveSources._reading(msgpack.packb(payload, use_bin_type=True))

    said = str(raised.value)
    assert "unexpected_key_count=1" in said
    assert "smuggled_secret_name" not in said, "an unknown key name reached the message"


async def test_every_key_the_publisher_writes_is_known_to_this_consumer() -> None:
    """The producer/consumer contract, checked in one place instead of two.

    This is the drift itself: the publisher grew `desc` and the consumer's key set did
    not. Asking the packer what it writes -- with and without the optional envelope --
    makes a future addition redden here rather than in a laboratory run.
    """

    import msgpack

    from cryodaq.agents.assistant import periodic_runtime

    known = periodic_runtime._READING_REQUIRED_KEYS | periodic_runtime._READING_OPTIONAL_KEYS
    for envelope in (None, b"an opaque descriptor envelope"):
        written = set(msgpack.unpackb(_published_reading_bytes(descriptor_envelope=envelope), raw=False))
        unknown = sorted(written - known)
        assert not unknown, f"the publisher writes keys this consumer refuses: {unknown}"
        missing = sorted(periodic_runtime._READING_REQUIRED_KEYS - written)
        assert not missing, f"the consumer requires keys the publisher does not write: {missing}"
