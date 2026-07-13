"""F35 D4.2 — DataBroker opt-in, positionally-paired descriptor envelope companion."""

from __future__ import annotations

import pytest

from cryodaq.channels.persistence import MAX_PERSISTED_ENVELOPE_BYTES
from cryodaq.core.broker import DataBroker, OverflowPolicy, PublishedReading
from cryodaq.drivers.base import Reading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reading(channel: str = "CH1", value: float = 4.5, unit: str = "K") -> Reading:
    return Reading.now(channel, value, unit, instrument_id="test")


# ---------------------------------------------------------------------------
# Opt-out default: byte-for-byte unchanged behaviour
# ---------------------------------------------------------------------------


async def test_opted_out_subscriber_receives_bare_reading_even_with_envelope_given() -> None:
    """A subscriber that never opted in must keep receiving a bare Reading —
    even when the caller supplies a descriptor_envelope for this publish."""
    broker = DataBroker()
    q = await broker.subscribe("legacy_sub", maxsize=10)

    r = _reading("T1", 4.2)
    await broker.publish(r, descriptor_envelope=b'{"channel_id":"T1"}')

    delivered = q.get_nowait()
    assert type(delivered) is Reading
    assert delivered == r


async def test_publish_batch_default_none_envelopes_reproduces_current_behavior_exactly() -> None:
    broker = DataBroker()
    q = await broker.subscribe("writer", maxsize=10)
    readings = [_reading("T1", float(i)) for i in range(3)]

    await broker.publish_batch(readings)

    delivered = [q.get_nowait() for _ in readings]
    assert delivered == readings
    assert all(type(item) is Reading for item in delivered)


# ---------------------------------------------------------------------------
# Opt-in: PublishedReading pairing
# ---------------------------------------------------------------------------


async def test_opted_in_subscriber_receives_published_reading_pair() -> None:
    broker = DataBroker()
    q = await broker.subscribe("zmq_publisher", maxsize=10, wants_descriptor_envelope=True)

    r = _reading("T1", 4.2)
    await broker.publish(r, descriptor_envelope=b'{"channel_id":"T1"}')

    delivered = q.get_nowait()
    assert type(delivered) is PublishedReading
    assert delivered.reading == r
    assert delivered.descriptor_envelope == b'{"channel_id":"T1"}'


async def test_opted_in_subscriber_without_envelope_still_gets_paired_none() -> None:
    """Opting in always yields the pair type; the envelope value itself may
    be None (non-descriptor-authoritative path) — never fabricated."""
    broker = DataBroker()
    q = await broker.subscribe("zmq_publisher", maxsize=10, wants_descriptor_envelope=True)

    await broker.publish(_reading("T1", 1.0))

    delivered = q.get_nowait()
    assert type(delivered) is PublishedReading
    assert delivered.descriptor_envelope is None


async def test_oversize_envelope_drops_descriptor_before_broker_enqueue() -> None:
    """The broker reuses the persisted-envelope cap before queueing a pair.

    This keeps an envelope large enough to cross the ZMQ whole-reading cap
    from consuming queue memory or causing the reading to disappear at the
    downstream frame-size check.
    """
    broker = DataBroker()
    q = await broker.subscribe("zmq_publisher", maxsize=10, wants_descriptor_envelope=True)

    await broker.publish(_reading("T1", 1.0), descriptor_envelope=b"e" * (MAX_PERSISTED_ENVELOPE_BYTES + 1))

    delivered = q.get_nowait()
    assert type(delivered) is PublishedReading
    assert delivered.reading.channel == "T1"
    assert delivered.descriptor_envelope is None


async def test_mixed_subscribers_one_opted_in_one_not_on_same_publish_batch() -> None:
    """Critical case: one publish_batch call fans out to ALL subscribers at
    once — one paired, one bare, both from the SAME call."""
    broker = DataBroker()
    plain_q = await broker.subscribe("writer", maxsize=10)
    paired_q = await broker.subscribe("zmq_publisher", maxsize=10, wants_descriptor_envelope=True)

    readings = [_reading("T1", 1.0), _reading("T1", 2.0)]
    envelopes = [b"env-1", b"env-2"]
    await broker.publish_batch(readings, descriptor_envelopes=envelopes)

    plain = [plain_q.get_nowait() for _ in readings]
    paired = [paired_q.get_nowait() for _ in readings]
    assert all(type(item) is Reading for item in plain)
    assert all(type(item) is PublishedReading for item in paired)
    assert [item.descriptor_envelope for item in paired] == envelopes
    assert [item.reading.value for item in paired] == [r.value for r in readings]
    assert [item.value for item in plain] == [r.value for r in readings]


async def test_publish_batch_positional_pairing_survives_drop_oldest_overflow() -> None:
    """descriptor_envelopes[i] must stay paired with readings[i] by VALUE even
    when DROP_OLDEST evicts earlier queue entries — never by object identity
    or queue slot (risk #3 in the D4 plan)."""
    broker = DataBroker()
    q = await broker.subscribe(
        "zmq_publisher",
        maxsize=2,
        policy=OverflowPolicy.DROP_OLDEST,
        wants_descriptor_envelope=True,
    )
    readings = [_reading("T1", float(i)) for i in range(3)]
    envelopes = [f"env-{i}".encode() for i in range(3)]

    await broker.publish_batch(readings, descriptor_envelopes=envelopes)

    assert q.qsize() == 2
    remaining = [q.get_nowait() for _ in range(2)]
    assert [item.reading.value for item in remaining] == [1.0, 2.0]
    assert [item.descriptor_envelope for item in remaining] == [b"env-1", b"env-2"]


# ---------------------------------------------------------------------------
# Adversarial: cardinality mismatch and type forgery
# ---------------------------------------------------------------------------


async def test_publish_batch_cardinality_mismatch_rejects_before_partial_delivery() -> None:
    broker = DataBroker()
    q = await broker.subscribe("zmq_publisher", maxsize=10, wants_descriptor_envelope=True)
    other_q = await broker.subscribe("writer", maxsize=10)
    readings = [_reading("T1", 1.0), _reading("T1", 2.0)]

    with pytest.raises(ValueError, match="descriptor_envelopes length"):
        await broker.publish_batch(readings, descriptor_envelopes=[b"only-one"])

    assert q.empty()
    assert other_q.empty()
    assert broker.stats["_total_published"]["count"] == 0


async def test_publish_rejects_non_bytes_descriptor_envelope() -> None:
    broker = DataBroker()
    q = await broker.subscribe("zmq_publisher", maxsize=10, wants_descriptor_envelope=True)

    with pytest.raises(TypeError, match="descriptor_envelope must be exactly bytes or None"):
        await broker.publish(_reading(), descriptor_envelope="not-bytes")  # type: ignore[arg-type]

    assert q.empty()


async def test_publish_batch_rejects_non_bytes_item_before_any_delivery() -> None:
    """A single type-forged element anywhere in descriptor_envelopes must
    fail the WHOLE batch closed — no partial/zip-truncated fan-out, matching
    the cardinality-mismatch guarantee."""
    broker = DataBroker()
    q = await broker.subscribe("zmq_publisher", maxsize=10, wants_descriptor_envelope=True)

    with pytest.raises(TypeError, match="descriptor_envelope must be exactly bytes or None"):
        await broker.publish_batch(
            [_reading("T1", 1.0), _reading("T1", 2.0)],
            descriptor_envelopes=[b"ok", "not-bytes"],  # type: ignore[list-item]
        )

    assert q.empty()
    assert broker.stats["_total_published"]["count"] == 0
