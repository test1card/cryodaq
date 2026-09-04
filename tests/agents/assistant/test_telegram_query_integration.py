"""Tests for F30 Phase D: Telegram free-text + /ask integration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

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


async def test_telegram_imposes_no_deadline_of_its_own() -> None:
    """The replacement for the old timeout test, inverted on purpose.

    Telegram used to cancel at a hardcoded 60 s and report "слишком долго".
    That discarded answers the assistant was still producing — its command
    pipeline is intent 30 s + generation 300 s + format 30 s = 360 s — and
    cancelling here never stopped that work anyway: the assistant's REP handler
    stays occupied to its own deadline, so the cancellation lost the reply and
    freed nothing.

    So the assistant owns the computation deadline and the proxy's 450 s is the
    transport cap. A query far exceeding every timeout Telegram ever imposed
    must still deliver its answer.
    """

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(text: str, *, chat_id):
        started.set()
        await release.wait()
        return "ответ после долгой генерации"

    qa = MagicMock()
    qa.handle_query = slow

    bot = _make_bot(query_agent=qa)
    bot._send = AsyncMock()

    await bot._handle_text(_msg("что сейчас?"))
    await asyncio.wait_for(started.wait(), timeout=1.0)

    # Well past the old 60 s and the later 120 s: nothing here may cancel it.
    assert not bot._query_task.done()
    bot._send.assert_not_awaited()

    release.set()
    await _settle_query(bot)

    bot._send.assert_awaited_once()
    assert bot._send.call_args.args[1] == "ответ после долгой генерации"
    assert "слишком долго" not in bot._send.call_args.args[1], (
        "the operator must get the answer, not a timeout notice"
    )


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
    cfg = AssistantConfig.from_dict({
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
    })

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
