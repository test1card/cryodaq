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


async def test_start_connects_before_one_all_topic_subscription() -> None:
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
            ("subscribe", b""),
        ]
    finally:
        await live.stop()


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
    with pytest.raises(ValueError, match="multipart"):
        await live._handle_frame([DEFAULT_TOPIC + b".suffix", b"x"])

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
        b'{"ok":true,"proto":1,"schema":"cryodaq.periodic.query/v1","state_revision":true,"state_token":"x","active":{}}',
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
