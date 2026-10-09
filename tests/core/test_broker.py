"""Tests for DataBroker — fan-out message bus with overflow policies."""

from __future__ import annotations

import asyncio
import logging

import pytest

from cryodaq.core.broker import DataBroker, OverflowPolicy
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
    assert received is r


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

    assert q1.get_nowait() is r
    assert q2.get_nowait() is r
    assert q3.get_nowait() is r


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
    assert q.get_nowait() is r2  # r1 was dropped
    assert q.get_nowait() is r3
    assert q.get_nowait() is r4

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
    assert q.get_nowait() is r1  # original contents untouched
    assert q.get_nowait() is r2
    assert q.get_nowait() is r3

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
    assert q.get_nowait() is r_t1
    assert q.get_nowait() is r_t3


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
    assert q.get_nowait() is r1


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
        assert q.get_nowait() is expected


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
    assert q_good.get_nowait() is r
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
