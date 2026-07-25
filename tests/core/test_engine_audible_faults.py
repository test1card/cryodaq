"""A3 — audible faults: safety-fault + outside-RUNNING staleness get sound.

Covers the two extracted, importable helpers so the PRODUCTION dispatch
logic is exercised directly (same rationale as ``_drain_dispatch_tasks`` /
``_alarm_v2_feed_loop`` in test_engine_task_supervision.py):

  * ``_dispatch_alarm_notification`` — the shared alarm_fired (+ optional
    Telegram) dispatch that ``_safety_fault_log_callback`` and the
    outside-RUNNING dead-channel handler both reuse. Same channel
    alarm-v2/cooldown-alarm/vacuum-guard/task-supervisor already use.
  * ``_should_dispatch_dead_channel_alarm`` — the once-per-episode debounce
    gate for the outside-RUNNING dead-channel audible alert.
"""

from __future__ import annotations

import asyncio

import pytest

from cryodaq.core.event_bus import EventBus
from cryodaq.engine import _dispatch_alarm_notification, _should_dispatch_dead_channel_alarm

# ---------------------------------------------------------------------------
# Part (a): _dispatch_alarm_notification
# ---------------------------------------------------------------------------


class _FakeTelegramBot:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def _send_to_all(self, text: str) -> None:
        self.sent.append(text)


async def test_dispatch_publishes_alarm_fired_event() -> None:
    bus = EventBus()
    queue = await bus.subscribe("test")
    tasks: set[asyncio.Task] = set()

    await _dispatch_alarm_notification(
        bus,
        tasks,
        alarm_id="safety_fault_interlock",
        level="CRITICAL",
        message="Safety fault: interlock tripped",
        experiment_id="exp-1",
        channel="smua",
        value=42.0,
    )

    event = queue.get_nowait()
    assert event.event_type == "alarm_fired"
    assert event.experiment_id == "exp-1"
    assert event.payload == {
        "alarm_id": "safety_fault_interlock",
        "level": "CRITICAL",
        "message": "Safety fault: interlock tripped",
        "channels": ["smua"],
        "values": [42.0],
    }


async def test_dispatch_without_channel_uses_empty_lists() -> None:
    bus = EventBus()
    queue = await bus.subscribe("test")
    tasks: set[asyncio.Task] = set()

    await _dispatch_alarm_notification(
        bus,
        tasks,
        alarm_id="safety_fault",
        level="CRITICAL",
        message="Safety fault: disk full",
        experiment_id=None,
    )

    event = queue.get_nowait()
    assert event.payload["channels"] == []
    assert event.payload["values"] == []


async def test_dispatch_sends_telegram_when_bot_configured() -> None:
    bus = EventBus()
    await bus.subscribe("test")
    tasks: set[asyncio.Task] = set()
    bot = _FakeTelegramBot()

    await _dispatch_alarm_notification(
        bus,
        tasks,
        alarm_id="safety_fault_interlock",
        level="CRITICAL",
        message="Safety fault: interlock tripped",
        experiment_id="exp-1",
        telegram_bot=bot,
        channel="smua",
        value=1.0,
    )
    # Fire-and-forget: give the created task a chance to run.
    for _ in range(20):
        if bot.sent:
            break
        await asyncio.sleep(0)

    assert bot.sent == ["⚠ [CRITICAL] safety_fault_interlock\nSafety fault: interlock tripped"]
    # Strong-ref set must drain back to empty once the task completes.
    for _ in range(20):
        if not tasks:
            break
        await asyncio.sleep(0)
    assert tasks == set()


async def test_dispatch_no_telegram_when_bot_not_configured() -> None:
    bus = EventBus()
    await bus.subscribe("test")
    tasks: set[asyncio.Task] = set()

    await _dispatch_alarm_notification(
        bus,
        tasks,
        alarm_id="safety_fault",
        level="CRITICAL",
        message="Safety fault: disk full",
        experiment_id=None,
        telegram_bot=None,
    )

    assert tasks == set(), "no telegram_bot configured -> no dispatch task created"


# ---------------------------------------------------------------------------
# Part (b): _should_dispatch_dead_channel_alarm debounce gate
# ---------------------------------------------------------------------------


def test_first_decline_fires_once() -> None:
    sent: set[str] = set()
    assert _should_dispatch_dead_channel_alarm("k", False, sent) is True
    assert sent == {"k"}


def test_repeat_decline_is_debounced() -> None:
    sent: set[str] = set()
    assert _should_dispatch_dead_channel_alarm("k", False, sent) is True
    # Same channel keeps declining (SafetyManager retries every sample by
    # design) -> must NOT fire again while still in the same episode.
    assert _should_dispatch_dead_channel_alarm("k", False, sent) is False
    assert _should_dispatch_dead_channel_alarm("k", False, sent) is False
    assert sent == {"k"}


def test_escalated_clears_the_flag_and_never_fires() -> None:
    sent: set[str] = set()
    assert _should_dispatch_dead_channel_alarm("k", False, sent) is True
    # RUNNING begins / fault latches -> escalated True. Must not fire (a
    # real CRITICAL fault alarm covers this via the safety-fault path) and
    # must clear bookkeeping so a later, distinct episode can alert again.
    assert _should_dispatch_dead_channel_alarm("k", True, sent) is False
    assert sent == set()


def test_new_episode_after_escalation_fires_again() -> None:
    sent: set[str] = set()
    assert _should_dispatch_dead_channel_alarm("k", False, sent) is True
    assert _should_dispatch_dead_channel_alarm("k", True, sent) is False
    # A fresh decline streak after the previous one escalated is a new
    # episode -> must alert again, not stay silenced forever.
    assert _should_dispatch_dead_channel_alarm("k", False, sent) is True
    assert sent == {"k"}


def test_channels_are_independent() -> None:
    sent: set[str] = set()
    assert _should_dispatch_dead_channel_alarm("a", False, sent) is True
    assert _should_dispatch_dead_channel_alarm("b", False, sent) is True
    assert sent == {"a", "b"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
