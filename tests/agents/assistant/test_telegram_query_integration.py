"""Tests for F30 Phase D: Telegram free-text + /ask integration."""

from __future__ import annotations

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


async def test_telegram_free_text_routes_to_query_agent() -> None:
    """Non-command message with an attached query agent calls handle_query."""
    qa = MagicMock()
    qa.handle_query = AsyncMock(return_value="T_cold = 12.5 K")

    bot = _make_bot(query_agent=qa)
    bot._send = AsyncMock()

    await bot._handle_text(_msg("какая сейчас температура?"))

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


async def test_telegram_query_timeout_user_message() -> None:
    """When handle_query times out, bot sends a friendly timeout message."""
    qa = MagicMock()
    qa.handle_query = AsyncMock(return_value="ok")

    bot = _make_bot(query_agent=qa)
    bot._send = AsyncMock()

    async def _timeout(coro, **_kw):
        coro.close()
        raise TimeoutError()

    with patch("cryodaq.notifications.telegram_commands.asyncio.wait_for", new=_timeout):
        await bot._handle_text(_msg("ETA охлаждения?"))

    bot._send.assert_awaited_once()
    text = bot._send.call_args.args[1]
    assert "30s" in text or "долго" in text


async def test_telegram_query_error_user_message() -> None:
    """When handle_query raises unexpected exception, bot sends error message."""
    qa = MagicMock()
    qa.handle_query = AsyncMock(return_value="ok")

    bot = _make_bot(query_agent=qa)
    bot._send = AsyncMock()

    async def _error(coro, **_kw):
        coro.close()
        raise RuntimeError("internal error")

    with patch("cryodaq.notifications.telegram_commands.asyncio.wait_for", new=_error):
        await bot._handle_text(_msg("что сейчас?"))

    bot._send.assert_awaited_once()
    text = bot._send.call_args.args[1]
    assert "ошибка" in text.lower() or "Гемма" in text


# ---------------------------------------------------------------------------
# AssistantConfig query parsing (engine_constructs / engine_skips tests)
# ---------------------------------------------------------------------------


def test_engine_constructs_query_agent_when_enabled() -> None:
    """AssistantConfig correctly parses query.enabled=true."""
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
