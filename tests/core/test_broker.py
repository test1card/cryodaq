"""Tests for DataBroker — fan-out message bus with overflow policies."""

from __future__ import annotations

import asyncio
import logging

import pytest

from cryodaq.core.broker import (
    PERSISTENCE_AUTHORITATIVE_METADATA_KEY,
    DataBroker,
    OverflowPolicy,
)
from cryodaq.drivers.base import Reading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reading(channel: str = "CH1", value: float = 4.5, unit: str = "K") -> Reading:
    return Reading.now(channel, value, unit, instrument_id="test")


# ---------------------------------------------------------------------------
# 1. subscribe() returns an asyncio.Queue
# ---------------------------------------------------------------------------


async def test_subscribe_creates_queue() -> None:
    broker = DataBroker()
    q = await broker.subscribe("test_sub", maxsize=10)
    assert isinstance(q, asyncio.Queue)


# ---------------------------------------------------------------------------
# 2. publish() delivers the reading to a subscriber's queue
# ---------------------------------------------------------------------------


async def test_publish_delivers_to_subscriber() -> None:
    broker = DataBroker()
    q = await broker.subscribe("reader", maxsize=10)

    r = _reading("T1", 4.2)
    await broker.publish(r)

    received = q.get_nowait()
    assert received == r
    assert received is not r


# ---------------------------------------------------------------------------
# 3. All subscribers receive the same reading (fan-out)
# ---------------------------------------------------------------------------


async def test_multiple_subscribers() -> None:
    broker = DataBroker()
    q1 = await broker.subscribe("sub1", maxsize=10)
    q2 = await broker.subscribe("sub2", maxsize=10)
    q3 = await broker.subscribe("sub3", maxsize=10)

    r = _reading("T2", 77.0)
    await broker.publish(r)

    delivered = q1.get_nowait()
    assert delivered == r
    assert delivered is not r
    assert q2.get_nowait() is delivered
    assert q3.get_nowait() is delivered


# ---------------------------------------------------------------------------
# 4. DROP_OLDEST policy: full queue drops oldest entry when a new one arrives
# ---------------------------------------------------------------------------


async def test_overflow_drop_oldest() -> None:
    broker = DataBroker()
    q = await broker.subscribe("overflow_sub", maxsize=3, policy=OverflowPolicy.DROP_OLDEST)

    # Fill the queue to capacity
    r1 = _reading("T1", 1.0)
    r2 = _reading("T1", 2.0)
    r3 = _reading("T1", 3.0)
    for r in (r1, r2, r3):
        await broker.publish(r)

    assert q.qsize() == 3

    # Publish one more — r1 (oldest) should be evicted
    r4 = _reading("T1", 4.0)
    await broker.publish(r4)

    assert q.qsize() == 3
    assert q.get_nowait() == r2  # r1 was dropped
    assert q.get_nowait() == r3
    assert q.get_nowait() == r4

    # stats should show at least one dropped reading
    stats = broker.stats
    assert stats["overflow_sub"]["dropped"] >= 1


# ---------------------------------------------------------------------------
# 5. DROP_NEWEST policy: full queue discards the incoming reading
# ---------------------------------------------------------------------------


async def test_overflow_drop_newest() -> None:
    broker = DataBroker()
    q = await broker.subscribe("newest_sub", maxsize=3, policy=OverflowPolicy.DROP_NEWEST)

    r1 = _reading("T1", 1.0)
    r2 = _reading("T1", 2.0)
    r3 = _reading("T1", 3.0)
    for r in (r1, r2, r3):
        await broker.publish(r)

    # Publish one more — it should be silently dropped
    r4 = _reading("T1", 4.0)
    await broker.publish(r4)

    assert q.qsize() == 3
    assert q.get_nowait() == r1  # original contents untouched
    assert q.get_nowait() == r2
    assert q.get_nowait() == r3

    stats = broker.stats
    assert stats["newest_sub"]["dropped"] >= 1


# ---------------------------------------------------------------------------
# 6. filter_fn: subscriber only receives readings that pass the filter
# ---------------------------------------------------------------------------


async def test_filter_function() -> None:
    broker = DataBroker()

    # Only accept readings on channel "T1"
    q = await broker.subscribe(
        "filtered_sub",
        maxsize=10,
        filter_fn=lambda r: r.channel == "T1",
    )

    r_t1 = _reading("T1", 4.0)
    r_t2 = _reading("T2", 5.0)
    r_t3 = _reading("T1", 6.0)

    await broker.publish(r_t1)
    await broker.publish(r_t2)  # filtered out
    await broker.publish(r_t3)

    assert q.qsize() == 2
    assert q.get_nowait() == r_t1
    assert q.get_nowait() == r_t3


# ---------------------------------------------------------------------------
# 7. unsubscribe: queue stops receiving after removal
# ---------------------------------------------------------------------------


async def test_unsubscribe() -> None:
    broker = DataBroker()
    q = await broker.subscribe("leaving_sub", maxsize=10)

    r1 = _reading("T1", 1.0)
    await broker.publish(r1)
    assert q.qsize() == 1

    await broker.unsubscribe("leaving_sub")

    r2 = _reading("T1", 2.0)
    await broker.publish(r2)

    # Queue should still contain only r1; r2 was published after unsubscribe
    assert q.qsize() == 1
    assert q.get_nowait() == r1


# ---------------------------------------------------------------------------
# 8. stats returns correct counts for queued and dropped readings
# ---------------------------------------------------------------------------


async def test_stats() -> None:
    broker = DataBroker()
    await broker.subscribe("stats_sub", maxsize=2, policy=OverflowPolicy.DROP_OLDEST)

    await broker.publish(_reading("T1", 1.0))
    await broker.publish(_reading("T1", 2.0))
    # Queue is full; this will cause a drop
    await broker.publish(_reading("T1", 3.0))

    stats = broker.stats
    assert stats["stats_sub"]["queued"] == 2
    assert stats["stats_sub"]["dropped"] == 1
    assert stats["_total_published"]["count"] == 3


# ---------------------------------------------------------------------------
# 9. publish_batch delivers all readings in order
# ---------------------------------------------------------------------------


async def test_publish_batch() -> None:
    broker = DataBroker()
    q = await broker.subscribe("batch_sub", maxsize=20)

    readings = [_reading("T1", float(i)) for i in range(5)]
    await broker.publish_batch(readings)

    assert q.qsize() == 5
    for expected in readings:
        assert q.get_nowait() == expected


# ---------------------------------------------------------------------------
# 10. Registering the same subscriber name twice raises ValueError
# ---------------------------------------------------------------------------


async def test_duplicate_subscriber_rejected() -> None:
    broker = DataBroker()
    await broker.subscribe("unique_name", maxsize=10)

    with pytest.raises(ValueError, match="уже зарегистрирован"):
        await broker.subscribe("unique_name", maxsize=10)


# ---------------------------------------------------------------------------
# 11-14. Subscriber exception isolation (Tier 1 Fix B)
# ---------------------------------------------------------------------------


async def test_exception_isolation_one_bad_subscriber() -> None:
    """A subscriber whose filter raises does not prevent delivery to siblings."""
    broker = DataBroker()
    q_bad = await broker.subscribe(
        "bad_filter",
        maxsize=10,
        filter_fn=lambda r: 1 / 0,
    )
    q_good = await broker.subscribe("good", maxsize=10)

    r = _reading("T1", 77.0)
    await broker.publish(r)

    assert q_good.qsize() == 1
    assert q_good.get_nowait() == r
    assert q_bad.qsize() == 0


async def test_exception_isolation_cancelled_error_propagates() -> None:
    """CancelledError from a subscriber filter must propagate, not be swallowed."""
    broker = DataBroker()

    def cancelling_filter(r: Reading) -> bool:
        raise asyncio.CancelledError()

    await broker.subscribe("canceller", maxsize=10, filter_fn=cancelling_filter)

    with pytest.raises(asyncio.CancelledError):
        await broker.publish(_reading())


async def test_exception_isolation_logs_subscriber_name(caplog: pytest.LogCaptureFixture) -> None:
    """Exception log mentions which subscriber failed for debuggability."""
    broker = DataBroker()
    await broker.subscribe(
        "misbehaving_widget",
        maxsize=10,
        filter_fn=lambda r: 1 / 0,
    )

    with caplog.at_level(logging.ERROR):
        await broker.publish(_reading())

    assert any("misbehaving_widget" in rec.message for rec in caplog.records)


async def test_exception_isolation_publish_batch() -> None:
    """publish_batch() honors the same isolation via delegation to publish()."""
    broker = DataBroker()
    await broker.subscribe("bad", maxsize=100, filter_fn=lambda r: 1 / 0)
    q_good = await broker.subscribe("good", maxsize=100)

    readings = [_reading("T1", float(i)) for i in range(5)]
    await broker.publish_batch(readings)

    assert q_good.qsize() == 5


# ---------------------------------------------------------------------------
# subscribe() rejects a non-positive maxsize (A3): maxsize=0 → unbounded queue
# whose full() never fires, defeating the overflow policy (memory leak).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_maxsize", [0, -1, -1000])
async def test_subscribe_rejects_nonpositive_maxsize(bad_maxsize: int) -> None:
    broker = DataBroker()
    with pytest.raises(ValueError, match="maxsize must be > 0"):
        await broker.subscribe("greedy", maxsize=bad_maxsize)
    # Rejection must not half-register the subscriber.
    assert "greedy" not in broker.stats


async def test_subscribe_accepts_positive_maxsize() -> None:
    broker = DataBroker()
    q = await broker.subscribe("ok", maxsize=1)
    assert q.maxsize == 1


# ---------------------------------------------------------------------------
# H3.6A: queue accounting and persistence-authority propagation
# ---------------------------------------------------------------------------


def _persistence_authority(reading: Reading) -> object:
    return reading.metadata.get(PERSISTENCE_AUTHORITATIVE_METADATA_KEY, False)


async def test_drop_oldest_repeated_overflow_drain_and_join_is_exact() -> None:
    broker = DataBroker()
    queue = await broker.subscribe(
        "zmq_publisher",
        maxsize=2,
        policy=OverflowPolicy.DROP_OLDEST,
    )

    for value in range(7):
        await broker.publish(_reading(value=float(value)))

    assert broker.stats["zmq_publisher"] == {"queued": 2, "dropped": 5}
    assert [queue.get_nowait().value for _ in range(2)] == [5.0, 6.0]
    queue.task_done()
    queue.task_done()
    await asyncio.wait_for(queue.join(), timeout=0.1)


async def test_drop_newest_never_acknowledges_rejected_item() -> None:
    broker = DataBroker()
    queue = await broker.subscribe(
        "zmq_publisher",
        maxsize=2,
        policy=OverflowPolicy.DROP_NEWEST,
    )

    for value in range(7):
        await broker.publish(_reading(value=float(value)))

    assert broker.stats["zmq_publisher"] == {"queued": 2, "dropped": 5}
    assert [queue.get_nowait().value for _ in range(2)] == [0.0, 1.0]
    queue.task_done()
    queue.task_done()
    await asyncio.wait_for(queue.join(), timeout=0.1)


@pytest.mark.parametrize("bad_authority", [None, 0, 1, "true", object()])
async def test_publish_rejects_non_bool_persistence_authority(
    bad_authority: object,
) -> None:
    broker = DataBroker()
    queue = await broker.subscribe("reader", maxsize=2)

    with pytest.raises(TypeError, match="persistence_authoritative must be exactly bool"):
        await broker.publish(
            _reading(),
            persistence_authoritative=bad_authority,  # type: ignore[arg-type]
        )

    assert queue.empty()
    assert broker.stats["_total_published"]["count"] == 0


@pytest.mark.parametrize("bad_authority", [None, 0, 1, "false", object()])
async def test_publish_batch_rejects_non_bool_authority_before_partial_delivery(
    bad_authority: object,
) -> None:
    broker = DataBroker()
    queue = await broker.subscribe("reader", maxsize=2)

    with pytest.raises(TypeError, match="persistence_authoritative must be exactly bool"):
        await broker.publish_batch(
            [_reading(value=1.0), _reading(value=2.0)],
            persistence_authoritative=bad_authority,  # type: ignore[arg-type]
        )

    assert queue.empty()
    assert broker.stats["_total_published"]["count"] == 0


@pytest.mark.parametrize("authority", [False, True])
async def test_publish_copies_authority_without_mutating_caller(
    authority: bool,
) -> None:
    broker = DataBroker()
    queue = await broker.subscribe("reader", maxsize=2)
    original_metadata = {
        "source": "instrument",
        PERSISTENCE_AUTHORITATIVE_METADATA_KEY: not authority,
    }
    reading = _reading()
    object.__setattr__(reading, "metadata", original_metadata.copy())

    await broker.publish(reading, persistence_authoritative=authority)

    delivered = queue.get_nowait()
    assert delivered is not reading
    assert delivered.metadata is not reading.metadata
    assert delivered.channel == reading.channel
    assert _persistence_authority(delivered) is authority
    assert reading.metadata == original_metadata


async def test_publish_default_authority_is_exact_false() -> None:
    broker = DataBroker()
    queue = await broker.subscribe("reader", maxsize=2)
    reading = _reading()

    await broker.publish(reading)

    delivered = queue.get_nowait()
    assert delivered == reading
    assert delivered is not reading
    assert _persistence_authority(delivered) is False
    assert PERSISTENCE_AUTHORITATIVE_METADATA_KEY not in reading.metadata


async def test_caller_cannot_forge_authority_after_enqueue() -> None:
    broker = DataBroker()
    queue = await broker.subscribe("reader", maxsize=2)
    reading = _reading()

    await broker.publish(reading)
    reading.metadata[PERSISTENCE_AUTHORITATIVE_METADATA_KEY] = True
    reading.metadata["late_mutation"] = "caller-owned"

    delivered = queue.get_nowait()
    assert delivered is not reading
    assert _persistence_authority(delivered) is False
    assert "late_mutation" not in delivered.metadata


async def test_publish_batch_propagates_authority_to_every_copy() -> None:
    broker = DataBroker()
    queue = await broker.subscribe("reader", maxsize=3)
    readings = [_reading(value=float(value)) for value in range(3)]

    await broker.publish_batch(readings, persistence_authoritative=True)

    delivered = [queue.get_nowait() for _ in readings]
    assert all(got is not original for got, original in zip(delivered, readings, strict=True))
    assert all(_persistence_authority(got) is True for got in delivered)
    assert all(PERSISTENCE_AUTHORITATIVE_METADATA_KEY not in item.metadata for item in readings)


async def test_authority_filter_sees_sanitized_detached_reading() -> None:
    broker = DataBroker()
    queue = await broker.subscribe(
        "authority_only",
        maxsize=2,
        filter_fn=lambda item: item.metadata.get(PERSISTENCE_AUTHORITATIVE_METADATA_KEY) is True,
    )
    forged = _reading()
    forged.metadata[PERSISTENCE_AUTHORITATIVE_METADATA_KEY] = True

    await broker.publish(forged)
    await broker.publish(forged, persistence_authoritative=True)

    assert queue.qsize() == 1
    delivered = queue.get_nowait()
    assert delivered is not forged
    assert _persistence_authority(delivered) is True
    assert forged.metadata[PERSISTENCE_AUTHORITATIVE_METADATA_KEY] is True


async def test_filter_mutation_cannot_forge_shared_delivery_authority() -> None:
    broker = DataBroker()
    observed_authority: list[bool] = []

    def mutating_filter(item: Reading) -> bool:
        item.metadata[PERSISTENCE_AUTHORITATIVE_METADATA_KEY] = True
        item.metadata["filter_mutation"] = "private"
        return True

    def false_authority_filter(item: Reading) -> bool:
        authority = item.metadata.get(PERSISTENCE_AUTHORITATIVE_METADATA_KEY, False)
        observed_authority.append(authority is True)
        return authority is False

    mutator_queue = await broker.subscribe(
        "mutating_filter",
        maxsize=1,
        filter_fn=mutating_filter,
    )
    authority_queue = await broker.subscribe(
        "false_authority_filter",
        maxsize=1,
        filter_fn=false_authority_filter,
    )

    await broker.publish(_reading())

    mutator_delivery = mutator_queue.get_nowait()
    authority_delivery = authority_queue.get_nowait()
    assert observed_authority == [False]
    assert mutator_delivery is authority_delivery
    assert _persistence_authority(mutator_delivery) is False
    assert "filter_mutation" not in mutator_delivery.metadata


async def test_authority_copy_preserves_filter_and_drop_oldest_policy() -> None:
    broker = DataBroker()
    queue = await broker.subscribe(
        "filtered",
        maxsize=1,
        policy=OverflowPolicy.DROP_OLDEST,
        filter_fn=lambda item: item.channel == "T1",
    )

    await broker.publish(_reading("T2", 1.0), persistence_authoritative=True)
    await broker.publish(_reading("T1", 2.0), persistence_authoritative=False)
    await broker.publish(_reading("T1", 3.0), persistence_authoritative=True)

    assert broker.stats["filtered"] == {"queued": 1, "dropped": 1}
    delivered = queue.get_nowait()
    assert delivered.value == 3.0
    assert _persistence_authority(delivered) is True
    queue.task_done()
    await asyncio.wait_for(queue.join(), timeout=0.1)
