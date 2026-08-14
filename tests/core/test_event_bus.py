"""Tests for EventBus — pub/sub for engine events."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from cryodaq.core.event_bus import EngineEvent, EventBus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(event_type: str = "alarm_fired", experiment_id: str | None = "exp-001") -> EngineEvent:
    return EngineEvent(
        event_type=event_type,
        timestamp=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        payload={"key": "value"},
        experiment_id=experiment_id,
    )


# ---------------------------------------------------------------------------
# EngineEvent dataclass
# ---------------------------------------------------------------------------


def test_engine_event_fields() -> None:
    ts = datetime(2026, 5, 1, tzinfo=UTC)
    ev = EngineEvent(
        event_type="phase_transition",
        timestamp=ts,
        payload={"phase": "COOL"},
        experiment_id="exp-42",
    )
    assert ev.event_type == "phase_transition"
    assert ev.timestamp == ts
    assert ev.payload == {"phase": "COOL"}
    assert ev.experiment_id == "exp-42"


def test_engine_event_experiment_id_defaults_none() -> None:
    ev = EngineEvent(
        event_type="alarm_cleared",
        timestamp=datetime.now(UTC),
        payload={},
    )
    assert ev.experiment_id is None


# ---------------------------------------------------------------------------
# EventBus — subscribe / publish
# ---------------------------------------------------------------------------


async def test_subscribe_returns_queue() -> None:
    bus = EventBus()
    q = await bus.subscribe("test")
    assert q is not None
    assert q.empty()


async def test_publish_delivers_to_subscriber() -> None:
    bus = EventBus()
    q = await bus.subscribe("consumer")
    ev = _event("alarm_fired")

    await bus.publish(ev)

    assert not q.empty()
    received = q.get_nowait()
    assert received is ev
    assert received.event_type == "alarm_fired"


async def test_publish_fanout_to_multiple_subscribers() -> None:
    bus = EventBus()
    q1 = await bus.subscribe("a")
    q2 = await bus.subscribe("b")
    q3 = await bus.subscribe("c")
    ev = _event("experiment_finalize")

    await bus.publish(ev)

    assert q1.get_nowait() is ev
    assert q2.get_nowait() is ev
    assert q3.get_nowait() is ev


async def test_publish_no_subscribers_does_not_raise() -> None:
    bus = EventBus()
    await bus.publish(_event())  # should not raise


async def test_publish_multiple_events_ordered() -> None:
    bus = EventBus()
    q = await bus.subscribe("ordered")

    ev1 = _event("alarm_fired")
    ev2 = _event("alarm_cleared")
    await bus.publish(ev1)
    await bus.publish(ev2)

    assert q.get_nowait() is ev1
    assert q.get_nowait() is ev2


# ---------------------------------------------------------------------------
# EventBus — full queue behavior
# ---------------------------------------------------------------------------


async def test_required_observer_settles_before_best_effort_fanout() -> None:
    bus = EventBus()
    queue = await bus.subscribe("consumer")
    observed: list[EngineEvent] = []

    async def persist(event: EngineEvent) -> None:
        assert queue.empty()
        observed.append(event)

    bus.retain_required_observer("attention_history", persist)
    event = _event("alarm_fired")
    await bus.publish(event)

    assert observed == [event]
    assert observed[0] is not event
    assert queue.get_nowait() is event


async def test_required_observer_failure_aborts_fanout_and_has_exact_owner() -> None:
    bus = EventBus()
    queue = await bus.subscribe("consumer")

    async def reject(_event: EngineEvent) -> None:
        raise RuntimeError("persistence rejected")

    bus.retain_required_observer("attention_history", reject)
    with pytest.raises(RuntimeError, match="persistence rejected"):
        await bus.publish(_event("alarm_fired"))
    assert queue.empty()

    with pytest.raises(RuntimeError, match="owner does not match"):
        bus.release_required_observer("wrong_owner")
    with pytest.raises(RuntimeError, match="already retained"):
        bus.retain_required_observer("second_owner", reject)

    bus.release_required_observer("attention_history")
    await bus.publish(_event("alarm_fired"))
    assert queue.qsize() == 1


async def test_full_queue_drops_event_with_warning() -> None:
    bus = EventBus()
    q = await bus.subscribe("slow_consumer", maxsize=2)

    # Fill the queue
    await bus.publish(_event("alarm_fired"))
    await bus.publish(_event("alarm_fired"))

    # Third publish should log a warning and not raise
    with patch("cryodaq.core.event_bus.logger") as mock_logger:
        await bus.publish(_event("alarm_fired"))
        mock_logger.warning.assert_called_once()
        call_args = mock_logger.warning.call_args[0]
        assert "slow_consumer" in call_args[1]

    assert q.qsize() == 2  # original two remain


async def test_required_publish_rejects_alarm_path_that_would_bypass_history() -> None:
    bus = EventBus()
    await bus.subscribe("consumer")

    with pytest.raises(ValueError, match="alarm_fired must use persistence-aware publish"):
        await bus.publish_required(_event("alarm_fired"))


async def test_required_publish_preflights_every_subscriber_without_partial_delivery() -> None:
    bus = EventBus()
    first = await bus.subscribe("first", maxsize=1)
    full = await bus.subscribe("full", maxsize=1)
    retained = _event("retained")
    full.put_nowait(retained)

    with pytest.raises(RuntimeError, match="required event publication capacity"):
        await bus.publish_required(_event("cooldown_end"))

    assert first.empty()
    assert full.get_nowait() is retained


async def test_required_publish_returns_digest_bound_receipt_and_isolates_subscribers() -> None:
    bus = EventBus()
    first = await bus.subscribe("first", maxsize=1)
    second = await bus.subscribe("second", maxsize=1)
    event = _event("cooldown_end")

    receipt = await bus.publish_required(event)
    first_event = first.get_nowait()
    second_event = second.get_nowait()

    assert receipt.admitted_subscribers == 2
    assert isinstance(receipt.event_digest, str)
    assert len(receipt.event_digest) == 64
    assert first_event == event
    assert second_event == event
    assert first_event is not event and second_event is not event
    assert first_event is not second_event
    first_event.payload["mutated"] = True
    assert "mutated" not in event.payload
    assert "mutated" not in second_event.payload


# ---------------------------------------------------------------------------
# EventBus — unsubscribe
# ---------------------------------------------------------------------------


async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    q = await bus.subscribe("removable")
    bus.unsubscribe("removable")

    await bus.publish(_event())

    assert q.empty()


async def test_unsubscribe_nonexistent_no_error() -> None:
    bus = EventBus()
    bus.unsubscribe("does_not_exist")  # should not raise


# ---------------------------------------------------------------------------
# EventBus — subscriber_count
# ---------------------------------------------------------------------------


async def test_subscriber_count_empty() -> None:
    bus = EventBus()
    assert bus.subscriber_count == 0


async def test_subscriber_count_after_subscribe() -> None:
    bus = EventBus()
    await bus.subscribe("a")
    await bus.subscribe("b")
    assert bus.subscriber_count == 2


async def test_subscriber_count_after_unsubscribe() -> None:
    bus = EventBus()
    await bus.subscribe("a")
    await bus.subscribe("b")
    bus.unsubscribe("a")
    assert bus.subscriber_count == 1


# ---------------------------------------------------------------------------
# EventBus — re-subscribe (same name replaces queue)
# ---------------------------------------------------------------------------


async def test_resubscribe_replaces_queue() -> None:
    bus = EventBus()
    q1 = await bus.subscribe("agent")
    await bus.publish(_event("alarm_fired"))
    assert q1.qsize() == 1

    # Re-subscribe under same name — new empty queue
    q2 = await bus.subscribe("agent")
    assert q2.empty()
    assert bus.subscriber_count == 1  # still one subscriber

    await bus.publish(_event("alarm_cleared"))
    assert q2.qsize() == 1
    assert q1.qsize() == 1  # old queue not updated anymore
