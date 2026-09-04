"""Tests for F30 Phase D: Telegram free-text + /ask integration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cryodaq.agents.assistant.live.agent import AssistantConfig
from cryodaq.notifications.telegram_commands import TelegramCommandBot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bot(
    query_agent: object | None = None,
    allowed_ids: list[int] | None = None,
) -> TelegramCommandBot:
    return TelegramCommandBot(
        bot_token="fake:token",
        allowed_chat_ids=allowed_ids or [42],
        commands_enabled=True,
        query_agent=query_agent,
    )


def _msg(text: str, chat_id: int = 42) -> dict:
    return {"text": text, "chat": {"id": chat_id}}


# ---------------------------------------------------------------------------
# Free-text routing
# ---------------------------------------------------------------------------


async def _settle_query(bot) -> None:
    """Wait for the query the bot now runs as a background task.

    Telegram dispatches the query instead of awaiting it: awaiting inline held
    the collect loop for the whole generation, so ordinary commands could not
    be served while the model worked. A test wanting the answer waits for it.
    """

    task = getattr(bot, "_query_task", None)
    if task is not None:
        await asyncio.wait_for(task, timeout=5.0)


async def test_telegram_free_text_routes_to_query_agent() -> None:
    """Non-command message with an attached query agent calls handle_query."""
    qa = MagicMock()
    qa.handle_query = AsyncMock(return_value="T_cold = 12.5 K")

    bot = _make_bot(query_agent=qa)
    bot._send = AsyncMock()

    await bot._handle_text(_msg("какая сейчас температура?"))
    await _settle_query(bot)

    qa.handle_query.assert_awaited_once()
    args, kwargs = qa.handle_query.call_args
    assert args[0] == "какая сейчас температура?"
    assert kwargs.get("chat_id") == 42
    bot._send.assert_awaited_once_with(42, "T_cold = 12.5 K")


async def test_telegram_free_text_stub_when_no_query_agent() -> None:
    """Without a query agent, bot sends the slash-commands-only stub reply."""
    bot = _make_bot(query_agent=None)
    bot._send = AsyncMock()

    await bot._handle_text(_msg("ETA вакуума?"))

    bot._send.assert_awaited_once()
    text = bot._send.call_args.args[1]
    assert "/help" in text


# ---------------------------------------------------------------------------
# /ask command
# ---------------------------------------------------------------------------


async def test_telegram_ask_command_routes_to_query_agent() -> None:
    """/ask <query> strips prefix and routes to query agent."""
    qa = MagicMock()
    qa.handle_query = AsyncMock(return_value="Ответ на запрос.")

    bot = _make_bot(query_agent=qa)
    bot._send = AsyncMock()

    await bot._handle_message(_msg("/ask ETA вакуума?"))
    await _settle_query(bot)

    qa.handle_query.assert_awaited_once()
    assert qa.handle_query.call_args.args[0] == "ETA вакуума?"


async def test_telegram_ask_command_empty_query_sends_usage() -> None:
    """/ask with no text sends a usage hint, does not call query agent."""
    qa = MagicMock()
    qa.handle_query = AsyncMock()

    bot = _make_bot(query_agent=qa)
    bot._send = AsyncMock()

    await bot._handle_message(_msg("/ask"))

    qa.handle_query.assert_not_awaited()
    bot._send.assert_awaited_once()
    assert "ask" in bot._send.call_args.args[1].lower()


# ---------------------------------------------------------------------------
# Timeout and error handling
# ---------------------------------------------------------------------------


class _DeadlineSpy:
    """Records every deadline primitive the query path could reach for.

    Guarding only `asyncio.wait_for` was itself false-green: a deadline
    restored as `async with asyncio.timeout(120):` would have left the test
    passing. Both forms are recorded, and both are proven to fail the control
    independently — see test_the_deadline_control_detects_each_form.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self._real_wait_for = asyncio.wait_for
        self._real_timeout = asyncio.timeout

    def wait_for(self, awaitable, timeout=None, **kwargs):
        self.calls.append(("wait_for", timeout))
        return self._real_wait_for(awaitable, timeout=timeout, **kwargs)

    def timeout(self, delay):
        self.calls.append(("timeout", delay))
        return self._real_timeout(delay)

    def patches(self):
        module = "cryodaq.notifications.telegram_commands.asyncio"
        return (
            patch(f"{module}.wait_for", self.wait_for),
            patch(f"{module}.timeout", self.timeout),
        )


async def _run_query_under_spy(bot, spy: _DeadlineSpy, text: str = "что сейчас?") -> None:
    """Drive one query with both deadline primitives observed."""

    wait_for_patch, timeout_patch = spy.patches()
    with wait_for_patch, timeout_patch:
        await bot._handle_text(_msg(text))
        task = bot._query_task
        assert task is not None, "the query must be dispatched as a task"
        await task  # direct await — deliberately not through wait_for


async def test_telegram_imposes_no_deadline_of_its_own() -> None:
    """A negative control: the query path must reach for no deadline at all.

    An earlier version released the query after milliseconds and asserted the
    answer arrived. That was FALSE GREEN — a millisecond never reaches any
    deadline, so restoring the old 60 s or 120 s limit would have passed it. It
    stood where a guard was supposed to be.

    Why the ABSENCE and not a number: the assistant's command pipeline is
    intent 30 s + generation 300 s + format 30 s = 360 s, so any Telegram-side
    deadline short of that discards an answer still being produced — and
    cancelling here never stops the assistant anyway, whose REP handler stays
    occupied to its own deadline. There is no correct number for Telegram to
    hold, which is why it holds none.
    """

    qa = MagicMock()
    qa.handle_query = AsyncMock(return_value="ответ на долгую генерацию")

    bot = _make_bot(query_agent=qa)
    bot._send = AsyncMock()

    spy = _DeadlineSpy()
    await _run_query_under_spy(bot, spy)

    assert spy.calls == [], (
        f"the Telegram query path reached for a deadline: {spy.calls!r}. The "
        "assistant owns the computation deadline; the proxy owns the transport "
        "cap; Telegram owns only concurrency."
    )

    bot._send.assert_awaited_once()
    assert bot._send.call_args.args[1] == "ответ на долгую генерацию"


@pytest.mark.parametrize("form", ["wait_for", "timeout"])
async def test_the_deadline_control_detects_each_form(form: str) -> None:
    """The control must be able to FAIL, once per primitive it claims to guard.

    A negative control nobody has seen fail is indistinguishable from the
    false-green it replaced. This restores a deadline in each shape the
    production path could plausibly use and asserts the spy notices, so the
    guard above is known to be load-bearing rather than assumed to be.
    """

    async def answer(text: str, *, chat_id):
        return "ответ"

    qa = MagicMock()
    if form == "wait_for":

        async def handle_query(text: str, *, chat_id):
            return await asyncio.wait_for(answer(text, chat_id=chat_id), timeout=120.0)

    else:

        async def handle_query(text: str, *, chat_id):
            async with asyncio.timeout(120.0):
                return await answer(text, chat_id=chat_id)

    qa.handle_query = handle_query

    bot = _make_bot(query_agent=qa)
    bot._send = AsyncMock()

    spy = _DeadlineSpy()
    await _run_query_under_spy(bot, spy)

    assert spy.calls, f"the {form} form went unnoticed — the control is blind to it"
    assert spy.calls[0][0] == form
    assert spy.calls[0][1] == 120.0


async def test_telegram_query_error_user_message() -> None:
    """An agent failure is reported to the operator, from the background task."""

    qa = MagicMock()
    qa.handle_query = AsyncMock(side_effect=RuntimeError("internal error"))

    bot = _make_bot(query_agent=qa)
    bot._send = AsyncMock()

    await bot._handle_text(_msg("что сейчас?"))
    await _settle_query(bot)

    bot._send.assert_awaited_once()
    text = bot._send.call_args.args[1]
    assert "ошибка" in text.lower() or "Гемма" in text


# ---------------------------------------------------------------------------
# AssistantConfig query parsing (engine_constructs / engine_skips tests)
# ---------------------------------------------------------------------------


def test_config_parses_query_agent_params_when_enabled() -> None:
    """AssistantConfig correctly parses all query params from a dict (no engine construction)."""
    cfg = AssistantConfig.from_dict(
        {
            "query": {
                "enabled": True,
                "intent_model": "gemma4:e2b",
                "format_model": "gemma4:e2b",
                "intent_temperature": 0.1,
                "format_temperature": 0.3,
                "intent_timeout_s": 10.0,
                "format_timeout_s": 20.0,
                "rate_limit": {"max_queries_per_chat_per_hour": 30},
            }
        }
    )

    assert cfg.query_enabled is True
    assert cfg.query_intent_model == "gemma4:e2b"
    assert cfg.query_format_model == "gemma4:e2b"
    assert cfg.query_intent_temperature == pytest.approx(0.1)
    assert cfg.query_format_temperature == pytest.approx(0.3)
    assert cfg.query_intent_timeout_s == pytest.approx(10.0)
    assert cfg.query_format_timeout_s == pytest.approx(20.0)
    assert cfg.query_max_per_chat_per_hour == 30


def test_repository_agent_yaml_enables_live_query() -> None:
    """Runtime config must enable free-text Telegram query handling."""
    cfg = AssistantConfig.from_yaml_path(Path("config/agent.yaml"))

    assert cfg.enabled is True
    assert cfg.query_enabled is True


def test_engine_skips_query_agent_when_disabled() -> None:
    """AssistantConfig.query_enabled defaults to False; query section absent → disabled."""
    cfg_default = AssistantConfig()
    assert cfg_default.query_enabled is False

    cfg_from_dict = AssistantConfig.from_dict({})
    assert cfg_from_dict.query_enabled is False

    cfg_explicit_off = AssistantConfig.from_dict({"query": {"enabled": False}})
    assert cfg_explicit_off.query_enabled is False


def test_engine_query_config_missing_models_use_none() -> None:
    """When intent_model/format_model not set, they default to None (use engine default)."""
    cfg = AssistantConfig.from_dict({"query": {"enabled": True}})
    assert cfg.query_intent_model is None
    assert cfg.query_format_model is None
