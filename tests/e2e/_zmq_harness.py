"""Shared production-harness fixture for real-socket ZMQ e2e tests.

Provides:
- ephemeral loopback TCP endpoint allocation (TOCTOU-minor, ZMQPublisher retries);
- a started real ZMQPublisher driven via its asyncio.Queue using PublishedReading
  items so the production _publish_loop + _publish_reading + _pack_reading +
  send_multipart path executes end-to-end;
- a started real ZmqBridge subprocess subscriber;
- drain_until(n, timeout_s) for bounded-deadline polling without time.sleep
  synchronisation;
- deterministic teardown (bridge.shutdown, publisher.stop, context term, LINGER=0).

Hard rules enforced here:
- No fake sockets; no reimplemented transport.
- No time.sleep as a synchronisation primitive.
- Python 3.12+, ruff-clean.
"""

from __future__ import annotations

import asyncio
import socket
import sys
import threading
import time
from collections.abc import Generator
from datetime import UTC, datetime

import pytest

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.channels.persistence import PersistedChannelEnvelopeV1
from cryodaq.core.broker import PublishedReading
from cryodaq.core.zmq_bridge import DEFAULT_TOPIC, ZMQPublisher
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.zmq_client import DescriptorQualifiedReading, ZmqBridge

# ---------------------------------------------------------------------------
# Ephemeral port allocation
# ---------------------------------------------------------------------------


def _allocate_ephemeral_port() -> int:
    """Bind to 127.0.0.1:0, read the OS-assigned port, close immediately.

    Minor TOCTOU on loopback is acceptable; ZMQPublisher retries on EADDRINUSE.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def allocate_pub_addr() -> str:
    """Return a loopback TCP address with an ephemeral port."""
    return f"tcp://127.0.0.1:{_allocate_ephemeral_port()}"


def _new_zmq_event_loop() -> asyncio.AbstractEventLoop:
    """Construct the same selector-capable Windows loop used by production."""
    if sys.platform == "win32":  # pragma: win32 cover
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()


# ---------------------------------------------------------------------------
# Descriptor envelope helpers (production encoder)
# ---------------------------------------------------------------------------


def make_descriptor(
    *,
    channel_id: str,
    instrument_id: str,
    source_key: str,
    unit: str = "K",
    quantity: ChannelQuantity = ChannelQuantity.TEMPERATURE,
    role: ChannelRole = ChannelRole.PRIMARY_MEASUREMENT,
    safety_class: ChannelSafetyClass = ChannelSafetyClass.OBSERVATIONAL,
    display_group: str = "test",
    display_name: str = "Test channel",
    visible_by_default: bool = True,
    display_order: int = 0,
    descriptor_revision: int = 1,
) -> ChannelDescriptorV1:
    """Build a minimal valid ChannelDescriptorV1 for testing."""
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel_id,
        instrument_id=instrument_id,
        source_key=source_key,
        quantity=quantity,
        unit=unit,
        role=role,
        safety_class=safety_class,
        display_group=display_group,
        display_name=display_name,
        visible_by_default=visible_by_default,
        display_order=display_order,
        descriptor_revision=descriptor_revision,
    )


def encode_descriptor_envelope(descriptor: ChannelDescriptorV1) -> bytes:
    """Produce the on-wire persisted channel envelope bytes via the production encoder.

    Uses PersistedChannelEnvelopeV1.from_descriptor (channels/persistence.py)
    which builds the authoritative canonical JSON envelope.  The resulting
    .canonical_json bytes are the exact payload published on the ZMQ wire
    and decoded by the subprocess subscriber.
    """
    envelope = PersistedChannelEnvelopeV1.from_descriptor(descriptor)
    return envelope.canonical_json


# ---------------------------------------------------------------------------
# ZmqHarness: started publisher + bridge
# ---------------------------------------------------------------------------


class ZmqHarness:
    """Holds a live ZMQPublisher + ZmqBridge for one test.

    Use via the ``zmq_harness`` pytest fixture rather than directly.

    Attributes
    ----------
    pub_addr:
        The loopback TCP address both sides share.
    publisher:
        Started ZMQPublisher (asyncio task running in _loop).
    bridge:
        Started ZmqBridge (subprocess subscriber).
    """

    def __init__(
        self,
        pub_addr: str,
        publisher: ZMQPublisher,
        queue: asyncio.Queue,
        bridge: ZmqBridge,
        loop: asyncio.AbstractEventLoop,
        thread: threading.Thread,
    ) -> None:
        self.pub_addr = pub_addr
        self.publisher = publisher
        self._queue = queue
        self.bridge = bridge
        self._loop = loop
        self._thread = thread
        self._teardown_lock = threading.Lock()
        self._teardown_complete = False

    def publish(self, reading: Reading, *, descriptor_envelope: bytes | None = None) -> None:
        """Drive the production publisher path via its asyncio.Queue.

        Places a PublishedReading (or bare Reading for legacy-absent) into the
        queue that _publish_loop drains.  _publish_loop then calls
        _publish_reading which calls _pack_reading then send_multipart —
        the full production serialize+send path.

        Using PublishedReading is the most faithful path because that is exactly
        what DataBroker puts on the queue when the ZMQ publisher subscription
        has wants_descriptor_envelope=True.  Calling _publish_reading directly
        (bypassing the queue) would also work, but routing through the queue
        exercises the exact production flow.
        """
        item: PublishedReading | Reading = (
            PublishedReading(reading=reading, descriptor_envelope=descriptor_envelope)
            if descriptor_envelope is not None
            else reading
        )
        asyncio.run_coroutine_threadsafe(self._queue.put(item), self._loop).result(timeout=5.0)

    def drain_until(
        self,
        n: int,
        timeout_s: float = 10.0,
    ) -> list[DescriptorQualifiedReading]:
        """Poll bridge until n qualified readings arrive or deadline trips.

        Uses bounded-deadline polling with a short poll interval; never uses
        time.sleep as the sole synchronisation primitive.  Fails the test if
        fewer than n readings arrive by the deadline.
        """
        accumulated: list[DescriptorQualifiedReading] = []
        deadline = time.monotonic() + timeout_s
        poll_interval = 0.02  # 20 ms poll — subprocess SUB has RCVTIMEO=100ms
        while time.monotonic() < deadline:
            batch = self.bridge.poll_readings_with_descriptor()
            accumulated.extend(batch)
            if len(accumulated) >= n:
                break
            time.sleep(poll_interval)
        if len(accumulated) < n:
            pytest.fail(f"drain_until: expected {n} readings within {timeout_s}s but only received {len(accumulated)}")
        return accumulated

    def teardown(self) -> None:
        """Deterministic teardown: bridge shutdown, publisher stop, loop cleanup."""
        with self._teardown_lock:
            if self._teardown_complete:
                return
            _settle_harness_resources(
                publisher=self.publisher,
                bridge=self.bridge,
                loop=self._loop,
                thread=self._thread,
            )
            self._teardown_complete = True


# ---------------------------------------------------------------------------
# Pytest fixture
# ---------------------------------------------------------------------------


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Thread target: run the asyncio event loop until loop.stop() is called."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def _stop_join_close_loop(loop: asyncio.AbstractEventLoop, thread: threading.Thread) -> None:
    """Stop the fixture loop, settle its thread, then release loop-owned sockets."""
    if loop.is_running():
        loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5.0)
    assert not thread.is_alive(), "ZMQ harness event-loop thread did not stop within 5 seconds"
    if not loop.is_closed():
        loop.close()


def _stop_publisher(publisher: ZMQPublisher, loop: asyncio.AbstractEventLoop) -> None:
    """Stop a possibly-partial publisher without creating an unawaited coroutine."""
    if loop.is_closed():
        return
    if loop.is_running():
        future = asyncio.run_coroutine_threadsafe(publisher.stop(), loop)
        future.result(timeout=5.0)
        return
    loop.run_until_complete(publisher.stop())


def _settle_harness_resources(
    *,
    publisher: ZMQPublisher | None,
    bridge: ZmqBridge | None,
    loop: asyncio.AbstractEventLoop,
    thread: threading.Thread,
) -> None:
    """Settle every harness owner, continuing after an individual failure."""
    failures: list[tuple[str, BaseException]] = []
    if bridge is not None:
        try:
            # Let both reply consumers leave through their timeout path before
            # shutdown closes the child pipe.  Otherwise the expected EOF is
            # retained by the consumer's ``failure`` traceback together with
            # the bridge and every multiprocessing semaphore it owns.
            bridge._reply_stop.set()
            consumers = (
                (bridge._reply_consumer, bridge._reply_consumer_started),
                (bridge._safe_reply_consumer, bridge._safe_reply_consumer_started),
            )
            for consumer, started in consumers:
                if started and consumer is not None:
                    consumer.join(timeout=2.0)
                    if consumer.is_alive():
                        raise RuntimeError("ZMQ bridge reply consumer did not stop within 2 seconds")
            bridge.close()
        except BaseException as exc:
            failures.append(("bridge close", exc))
    if publisher is not None:
        try:
            _stop_publisher(publisher, loop)
        except BaseException as exc:
            failures.append(("publisher stop", exc))
    try:
        _stop_join_close_loop(loop, thread)
    except BaseException as exc:
        failures.append(("event-loop close", exc))
    if failures:
        detail = "; ".join(f"{label}: {type(exc).__name__}" for label, exc in failures)
        raise RuntimeError(f"ZMQ harness teardown incomplete: {detail}") from failures[0][1]


@pytest.fixture()
def zmq_harness() -> Generator[ZmqHarness, None, None]:
    """Provide a fully started ZMQPublisher + ZmqBridge on an ephemeral loopback port.

    Teardown is deterministic: bridge.shutdown(), publisher.stop(), loop stopped.
    Each fixture invocation gets its own port, loop thread, publisher, and bridge
    subprocess — no shared state between tests.
    """
    pub_addr = allocate_pub_addr()

    # Start a dedicated event loop in a background thread.  On Windows this
    # must be a SelectorEventLoop, matching production's explicit construction;
    # the default ProactorEventLoop cannot provide pyzmq's reader callbacks.
    loop = _new_zmq_event_loop()
    t = threading.Thread(target=_run_loop, args=(loop,), daemon=True)
    t.start()

    publisher: ZMQPublisher | None = None
    bridge: ZmqBridge | None = None
    try:
        publisher = ZMQPublisher(pub_addr, topic=DEFAULT_TOPIC)
        queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)

        # Start the publisher (binds the PUB socket, spawns _publish_loop task).
        fut = asyncio.run_coroutine_threadsafe(publisher.start(queue), loop)
        fut.result(timeout=10.0)

        # Start the bridge subprocess subscriber.
        bridge = ZmqBridge(pub_addr=pub_addr)
        bridge.start()

        # Synchronise on a sentinel reading: publish dummy readings in a tight loop
        # until at least one arrives at the bridge's data_queue.  This is the only
        # reliable way to know that the subprocess SUB socket has completed
        # connect()+subscribe() on Windows (ZMQ connect is non-blocking; the TCP
        # handshake and subscription filter propagation happen asynchronously, and
        # messages published before they complete are silently dropped).
        #
        # The sentinel uses a known channel id "e2e.sentinel" that the test ignores.
        # drain_until filters on count only; the test validates channel ids separately.
        _sentinel_channel = "e2e.sentinel"
        _sentinel_reading = Reading(
            timestamp=datetime.fromtimestamp(0, tz=UTC),
            instrument_id="test_harness",
            channel=_sentinel_channel,
            value=0.0,
            unit="K",
            status=ChannelStatus.OK,
        )

        _sync_deadline = time.monotonic() + 15.0
        _sentinel_arrived = False
        while time.monotonic() < _sync_deadline and not _sentinel_arrived:
            # Publish one sentinel every 100 ms (matches SUB RCVTIMEO).
            asyncio.run_coroutine_threadsafe(queue.put(_sentinel_reading), loop).result(timeout=2.0)
            time.sleep(0.1)
            # Drain and look for the sentinel.
            batch = bridge.poll_readings_with_descriptor()
            for qr in batch:
                if qr.reading.channel == _sentinel_channel:
                    _sentinel_arrived = True
                    break

        if not _sentinel_arrived:
            pytest.fail("ZmqBridge SUB socket did not receive sentinel reading within 15 s")
    except BaseException as setup_error:
        try:
            _settle_harness_resources(
                publisher=publisher,
                bridge=bridge,
                loop=loop,
                thread=t,
            )
        except BaseException as cleanup_error:
            setup_error.add_note(f"fixture cleanup also failed: {cleanup_error}")
        raise

    harness = ZmqHarness(
        pub_addr=pub_addr,
        publisher=publisher,
        queue=queue,
        bridge=bridge,
        loop=loop,
        thread=t,
    )

    try:
        yield harness
    finally:
        harness.teardown()
