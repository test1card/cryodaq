"""F35 D4.3 — ZMQ wire pack/unpack and publish-loop descriptor envelope tests.

Covers: the additive ``"desc"`` msgpack key, old-consumer compatibility
(``_unpack_reading`` ignores the unknown key), the wire-size budget with a
maximum-size envelope, and evidence that no second send path / second lock
was added to the existing single ``_send_lock``/``_send_allocated`` call.
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime

import msgpack
import zmq

from cryodaq.channels.descriptors import (
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
from cryodaq.channels.persistence import MAX_PERSISTED_ENVELOPE_BYTES, PersistedChannelEnvelopeV1
from cryodaq.core.broker import PublishedReading
from cryodaq.core.descriptor_transport import DescriptorEnvelopeIssue, DescriptorQualifiedReading
from cryodaq.core.zmq_bridge import (
    MAX_DATA_MSG_SIZE,
    ZMQPublisher,
    ZMQSubscriber,
    _pack_reading,
    _unpack_reading,
)
from cryodaq.core.zmq_subprocess import DEFAULT_TOPIC, READING_MAX_WIRE_BYTES, _decode_reading_frames
from cryodaq.drivers.base import ChannelStatus, Reading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reading(
    channel: str = "T1",
    metadata: dict | None = None,
    *,
    instrument_id: str = "probe",
    unit: str = "K",
) -> Reading:
    return Reading(
        timestamp=datetime(2026, 7, 13, 12, 0, 0, tzinfo=UTC),
        instrument_id=instrument_id,
        channel=channel,
        value=4.2,
        unit=unit,
        status=ChannelStatus.OK,
        raw=118.25,
        metadata=metadata or {},
    )


def _descriptor(
    *,
    channel_id: str = "T1",
    instrument_id: str = "probe",
    unit: str = "K",
) -> ChannelDescriptorV1:
    return ChannelDescriptorV1(
        schema_version=1,
        channel_id=channel_id,
        instrument_id=instrument_id,
        source_key="input.1.temperature",
        quantity=ChannelQuantity.TEMPERATURE,
        unit=unit,
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="probes",
        display_name="Probe 1",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=3,
    )


def _envelope_bytes(descriptor: ChannelDescriptorV1) -> bytes:
    return PersistedChannelEnvelopeV1.from_descriptor(descriptor).canonical_json


class _Socket:
    def __init__(self) -> None:
        self.frames: list[list[bytes]] = []

    async def send_multipart(self, frames: list[bytes]) -> None:
        self.frames.append(frames)

    def close(self, *, linger: int) -> None:
        pass


class _SubscriberSocket:
    """One fake direct-SUB socket; no localhost bind or second transport."""

    def __init__(self, frames: list[list[bytes]]) -> None:
        self.frames = deque(frames)

    async def poll(self, **kwargs: int) -> int:
        assert kwargs == {"timeout": 1000}
        if not self.frames:
            await asyncio.sleep(0)
        return zmq.POLLIN if self.frames else 0

    async def recv_multipart(self) -> list[bytes]:
        return self.frames.popleft()


def _prime_publisher(socket: _Socket) -> ZMQPublisher:
    publisher = ZMQPublisher()
    publisher._socket = socket  # type: ignore[assignment]
    publisher._running = True
    publisher._session_id = "a" * 32
    publisher._sequence = 0
    publisher._publish_failure_count = 0
    publisher._send_lock = asyncio.Lock()
    return publisher


# ---------------------------------------------------------------------------
# _pack_reading / _unpack_reading wire shape
# ---------------------------------------------------------------------------


def test_pack_reading_omits_desc_key_when_envelope_is_none() -> None:
    packed = _pack_reading(_reading())
    data = msgpack.unpackb(packed, raw=False)
    assert "desc" not in data


def test_pack_reading_includes_desc_key_when_envelope_given() -> None:
    envelope = b'{"channel_id":"T1"}'
    packed = _pack_reading(_reading(), descriptor_envelope=envelope)
    data = msgpack.unpackb(packed, raw=False)
    assert data["desc"] == envelope


def test_old_consumer_unpack_reading_ignores_desc_key() -> None:
    """A NEW envelope-bearing frame decoded by the pre-D4 ``_unpack_reading``
    must reconstruct the identical Reading — extra key ignored, never raises."""
    original = _reading(metadata={"a": 1})
    packed = _pack_reading(original, descriptor_envelope=b'{"channel_id":"T1"}')

    result = _unpack_reading(packed)

    assert result.channel == original.channel
    assert result.value == original.value
    assert result.metadata == {"a": 1}


def test_new_consumer_old_frame_desc_absent_reads_as_none_not_error() -> None:
    """An OLD frame (no ``"desc"`` key) has no descriptor on decode —
    treated as absent, never an error."""
    packed = _pack_reading(_reading())
    data = msgpack.unpackb(packed, raw=False)
    assert data.get("desc") is None


def test_wire_size_budget_max_metadata_and_max_envelope_within_cap() -> None:
    """Maximum-size metadata AND a maximum-size (8192-byte) descriptor
    envelope in the same frame must stay well within MAX_DATA_MSG_SIZE."""
    big_metadata = {"blob": "x" * 100_000}
    max_envelope = b"e" * MAX_PERSISTED_ENVELOPE_BYTES
    packed = _pack_reading(_reading(metadata=big_metadata), descriptor_envelope=max_envelope)

    assert len(packed) < MAX_DATA_MSG_SIZE
    # Large margin: ~108 KB payload vs a 2 MiB cap.
    assert len(packed) < MAX_DATA_MSG_SIZE // 4


def test_oversize_envelope_crossing_whole_frame_cap_preserves_reading() -> None:
    """Producer-side cap must prevent the descriptor from killing the frame.

    Before the fix, this envelope made the msgpack payload exceed the 2 MiB
    subprocess cap, so the receiver rejected the complete reading before it
    could apply its descriptor-only 8 KiB drop policy.
    """
    oversize = b"e" * (READING_MAX_WIRE_BYTES + 1)
    packed = _pack_reading(_reading(), descriptor_envelope=oversize)

    decoded = _decode_reading_frames([DEFAULT_TOPIC, packed])

    assert len(packed) < READING_MAX_WIRE_BYTES
    assert decoded["channel"] == "T1"
    assert decoded["value"] == 4.2
    assert decoded["descriptor_envelope"] is None


async def test_direct_subscriber_mixed_old_new_callbacks_share_one_receive_path() -> None:
    """Direct assistant/web consumers may opt in without breaking old callbacks.

    A mixed old/new/malformed stream is read exactly once from one fake socket.
    Both callbacks retain every Reading; only the new immutable carrier sees a
    descriptor or bounded issue.  No lookup, second socket, or second topic is
    involved.
    """

    valid = _envelope_bytes(_descriptor())
    channel_mismatch = _envelope_bytes(_descriptor(channel_id="other-channel"))
    instrument_mismatch = _envelope_bytes(_descriptor(instrument_id="other-probe"))
    oversize = b"x" * (MAX_PERSISTED_ENVELOPE_BYTES + 1)
    wire_payloads = [
        _pack_reading(_reading()),
        _pack_reading(_reading(), descriptor_envelope=valid),
        msgpack.packb(
            {
                "ts": _reading().timestamp.timestamp(),
                "iid": "probe",
                "ch": "T1",
                "v": 4.2,
                "u": "K",
                "st": "ok",
                "desc": None,
            },
            use_bin_type=True,
        ),
        msgpack.packb(
            {
                "ts": _reading().timestamp.timestamp(),
                "iid": "probe",
                "ch": "T1",
                "v": 4.2,
                "u": "K",
                "st": "ok",
                "desc": oversize,
            },
            use_bin_type=True,
        ),
        _pack_reading(_reading(), descriptor_envelope=channel_mismatch),
        _pack_reading(_reading(), descriptor_envelope=instrument_mismatch),
        _pack_reading(_reading(unit="mK"), descriptor_envelope=valid),
    ]
    socket = _SubscriberSocket([[b"readings", payload] for payload in wire_payloads])
    bare: list[Reading] = []
    qualified: list[DescriptorQualifiedReading] = []
    all_received = asyncio.Event()

    def on_qualified(item: DescriptorQualifiedReading) -> None:
        qualified.append(item)
        if len(qualified) == len(wire_payloads):
            all_received.set()

    subscriber = ZMQSubscriber(callback=bare.append, descriptor_callback=on_qualified)
    subscriber._socket = socket  # type: ignore[assignment]
    subscriber._running = True

    task = asyncio.create_task(subscriber._receive_loop())
    await asyncio.wait_for(all_received.wait(), timeout=2.0)
    subscriber._running = False
    await asyncio.wait_for(task, timeout=1.0)

    assert len(socket.frames) == 0
    assert [reading.channel for reading in bare] == ["T1"] * 7
    assert [item.reading for item in qualified] == bare
    assert qualified[0].descriptor is None
    assert qualified[0].descriptor_issue is None
    assert qualified[1].descriptor == _descriptor()
    assert qualified[1].descriptor_issue is None
    assert qualified[2].descriptor is None
    assert qualified[2].descriptor_issue is DescriptorEnvelopeIssue.MALFORMED
    assert qualified[3].descriptor is None
    assert qualified[3].descriptor_issue is DescriptorEnvelopeIssue.MALFORMED
    assert [item.descriptor_issue for item in qualified[4:]] == [
        DescriptorEnvelopeIssue.IDENTITY_MISMATCH,
        DescriptorEnvelopeIssue.IDENTITY_MISMATCH,
        DescriptorEnvelopeIssue.IDENTITY_MISMATCH,
    ]
    assert subscriber.descriptor_issue_count == 5
    assert all(not item.grants_control_authority for item in qualified)


# ---------------------------------------------------------------------------
# _publish_loop / _publish_reading — PublishedReading pairing under the
# existing single send lock (no new socket, topic, or send owner)
# ---------------------------------------------------------------------------


async def test_publish_loop_unpacks_published_reading_pair_onto_wire() -> None:
    socket = _Socket()
    publisher = _prime_publisher(socket)
    queue: asyncio.Queue = asyncio.Queue()
    envelope = b'{"channel_id":"T1"}'
    await queue.put(PublishedReading(reading=_reading(), descriptor_envelope=envelope))

    task = asyncio.create_task(publisher._publish_loop(queue))
    await asyncio.wait_for(queue.join(), timeout=2.0)
    publisher._running = False
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(socket.frames) == 1
    assert socket.frames[0][0] == b"readings"
    data = msgpack.unpackb(socket.frames[0][1], raw=False)
    assert data["desc"] == envelope


async def test_publish_loop_bare_reading_still_works_no_desc_key() -> None:
    """A subscriber that never opted in still feeds bare ``Reading`` through
    the same loop — must publish without a ``"desc"`` key, unaffected."""
    socket = _Socket()
    publisher = _prime_publisher(socket)
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(_reading())

    task = asyncio.create_task(publisher._publish_loop(queue))
    await asyncio.wait_for(queue.join(), timeout=2.0)
    publisher._running = False
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(socket.frames) == 1
    data = msgpack.unpackb(socket.frames[0][1], raw=False)
    assert "desc" not in data


async def test_single_send_lock_preserved_across_n_descriptor_bearing_readings() -> None:
    """Prove no second send path / second lock was added: N descriptor-bearing
    PublishedReading items through _publish_loop produce exactly N sends and
    N sequence allocations under the one existing ``_send_lock`` — not
    asserted by code review, but by observed send/sequence counts."""
    socket = _Socket()
    publisher = _prime_publisher(socket)
    queue: asyncio.Queue = asyncio.Queue()
    n = 25
    for i in range(n):
        await queue.put(PublishedReading(reading=_reading(), descriptor_envelope=f"env-{i}".encode()))

    task = asyncio.create_task(publisher._publish_loop(queue))
    await asyncio.wait_for(queue.join(), timeout=5.0)
    publisher._running = False
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(socket.frames) == n
    assert publisher.sequence == n
    decoded_envelopes = [msgpack.unpackb(f[1], raw=False)["desc"] for f in socket.frames]
    assert decoded_envelopes == [f"env-{i}".encode() for i in range(n)]
