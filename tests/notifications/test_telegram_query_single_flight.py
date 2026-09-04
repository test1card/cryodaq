"""A slow model answer must not occupy the operator's control surface.

The bot awaited `handle_query` inline in the collect loop. The model answers in
about 58 s on this stand, so for a minute at a time `/status`, `/alarms`,
`/report`, `/log` and `/phase` could not be served — head-of-line blocking on
the only remote control surface the operator has when they are not at the rack.

Raising a Telegram-side timeout made that worse rather than better: it doubled
the blocking window, and cancelling here does not stop the assistant anyway —
its REP handler stays occupied until its own deadline, so the cancellation
discards a reply that is still coming.

So Telegram owns no computation deadline at all. It owns concurrency: exactly
one query in flight, refused fast when busy, settled at shutdown.

These tests drive the real `_handle_text` rather than asserting on a signature.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.notifications.telegram_commands import TelegramCommandBot


def _bot(query_agent) -> TelegramCommandBot:
    broker = MagicMock()
    broker.subscribe = AsyncMock(return_value=asyncio.Queue())
    alarm_engine = MagicMock()
    alarm_engine.get_active.return_value = {}
    bot = TelegramCommandBot(
        broker,
        alarm_engine,
        bot_token="fake:TOKEN",
        allowed_chat_ids=[1234],
        query_agent=query_agent,
    )
    bot._send = AsyncMock()
    return bot


def _msg(text: str) -> dict:
    return {"text": text, "chat": {"id": 1234}}


class _SlowAgent:
    """Stands in for the ~58 s model call, without waiting 58 s."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def handle_query(self, text: str, *, chat_id) -> str:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return f"ответ на {text!r}"


@pytest.mark.asyncio
async def test_a_slow_query_does_not_block_the_caller() -> None:
    """_handle_text returns while the model is still working."""

    agent = _SlowAgent()
    bot = _bot(agent)

    await asyncio.wait_for(bot._handle_text(_msg("ETA вакуума")), timeout=1.0)

    await asyncio.wait_for(agent.started.wait(), timeout=1.0)
    assert bot._query_task is not None and not bot._query_task.done()
    assert bot._send.await_count == 0, "nothing is sent until the answer exists"

    agent.release.set()
    await asyncio.wait_for(bot._query_task, timeout=1.0)
    bot._send.assert_awaited_once()
    assert "ответ на" in bot._send.await_args.args[1]


@pytest.mark.asyncio
async def test_a_second_query_is_refused_immediately_not_queued() -> None:
    """One in flight; the next asker is told so at once, in the same chat."""

    agent = _SlowAgent()
    bot = _bot(agent)

    await bot._handle_text(_msg("первый"))
    await asyncio.wait_for(agent.started.wait(), timeout=1.0)
    first_task = bot._query_task

    await asyncio.wait_for(bot._handle_text(_msg("второй")), timeout=1.0)

    assert agent.calls == 1, "the second query must not reach the model"
    assert bot._query_task is first_task, "the in-flight task must not be replaced"
    bot._send.assert_awaited_once()
    assert "уже думаю" in bot._send.await_args.args[1]

    agent.release.set()
    await asyncio.wait_for(first_task, timeout=1.0)


@pytest.mark.asyncio
async def test_ordinary_commands_are_served_while_the_model_works() -> None:
    """The point of the whole change: /status is not stuck behind a generation."""

    agent = _SlowAgent()
    bot = _bot(agent)
    bot._handle_message = AsyncMock()

    await bot._handle_text(_msg("что сейчас?"))
    await asyncio.wait_for(agent.started.wait(), timeout=1.0)

    await asyncio.wait_for(bot._handle_message(_msg("/status")), timeout=1.0)
    bot._handle_message.assert_awaited_once()

    agent.release.set()
    await asyncio.wait_for(bot._query_task, timeout=1.0)


@pytest.mark.asyncio
async def test_a_finished_query_frees_the_slot() -> None:
    agent = _SlowAgent()
    bot = _bot(agent)

    await bot._handle_text(_msg("первый"))
    await asyncio.wait_for(agent.started.wait(), timeout=1.0)
    agent.release.set()
    await asyncio.wait_for(bot._query_task, timeout=1.0)

    agent.release.clear()
    agent.started.clear()
    await bot._handle_text(_msg("второй"))
    await asyncio.wait_for(agent.started.wait(), timeout=1.0)
    assert agent.calls == 2, "a completed query must not hold the slot"

    agent.release.set()
    await asyncio.wait_for(bot._query_task, timeout=1.0)


@pytest.mark.asyncio
async def test_an_agent_failure_is_reported_and_frees_the_slot() -> None:
    agent = MagicMock()
    agent.handle_query = AsyncMock(side_effect=RuntimeError("assistant down"))
    bot = _bot(agent)

    await bot._handle_text(_msg("вопрос"))
    await asyncio.wait_for(bot._query_task, timeout=1.0)

    bot._send.assert_awaited_once()
    assert "внутренняя ошибка" in bot._send.await_args.args[1]
    assert bot._query_task.done(), "a failed query must not hold the slot"


@pytest.mark.asyncio
async def test_shutdown_settles_an_in_flight_query() -> None:
    """A stop() during the ~58 s generation must not orphan the task."""

    agent = _SlowAgent()
    bot = _bot(agent)

    await bot._handle_text(_msg("вопрос"))
    await asyncio.wait_for(agent.started.wait(), timeout=1.0)
    task = bot._query_task
    assert task is not None and not task.done()

    await asyncio.wait_for(bot.stop(), timeout=5.0)

    assert task.done(), "stop() must settle the in-flight query task"
    assert bot._query_task is None
