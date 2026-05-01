"""Track A — query agent wiring tests.

Verifies that:
- AssistantConfig.query_enabled is gated by agent.yaml query.enabled
- TelegramCommandBot._handle_text routes to query agent when wired
- /ask command routes through _handle_text
- Fallback returned when query agent not wired
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from cryodaq.agents.assistant.live.agent import AssistantConfig
from cryodaq.notifications.telegram_commands import TelegramCommandBot

# ---------------------------------------------------------------------------
# AssistantConfig — query_enabled parsing
# ---------------------------------------------------------------------------


def test_query_enabled_defaults_false() -> None:
    cfg = AssistantConfig.from_yaml_string("")
    assert cfg.query_enabled is False


def test_query_enabled_true_when_yaml_sets_it() -> None:
    yaml = """
agent:
  query:
    enabled: true
"""
    cfg = AssistantConfig.from_yaml_string(yaml)
    assert cfg.query_enabled is True


def test_query_enabled_false_when_explicit_false() -> None:
    yaml = """
agent:
  query:
    enabled: false
"""
    cfg = AssistantConfig.from_yaml_string(yaml)
    assert cfg.query_enabled is False


def test_query_model_params_parsed() -> None:
    yaml = """
agent:
  query:
    enabled: true
    intent_model: gemma4:e2b
    format_model: gemma4:e2b
    intent_temperature: 0.1
    format_temperature: 0.3
    intent_timeout_s: 15.0
    format_timeout_s: 30.0
"""
    cfg = AssistantConfig.from_yaml_string(yaml)
    assert cfg.query_intent_model == "gemma4:e2b"
    assert cfg.query_intent_temperature == 0.1
    assert cfg.query_intent_timeout_s == 15.0
    assert cfg.query_format_timeout_s == 30.0


def test_query_rate_limit_parsed() -> None:
    yaml = """
agent:
  query:
    enabled: true
    rate_limit:
      max_queries_per_chat_per_hour: 30
"""
    cfg = AssistantConfig.from_yaml_string(yaml)
    assert cfg.query_max_per_chat_per_hour == 30


# ---------------------------------------------------------------------------
# TelegramCommandBot — _handle_text routing
# ---------------------------------------------------------------------------


def _make_bot_with_agent(query_agent: object | None) -> TelegramCommandBot:
    bot = TelegramCommandBot(
        broker=None,
        alarm_engine=None,
        bot_token="token:TEST",
        allowed_chat_ids=[111],
    )
    bot._query_agent = query_agent
    return bot


async def test_handle_text_returns_slash_fallback_when_agent_none() -> None:
    bot = _make_bot_with_agent(None)
    sent: list[tuple] = []

    async def fake_send(chat_id: int, text: str, **kwargs: object) -> None:
        sent.append((chat_id, text))

    with patch.object(bot, "_send", side_effect=fake_send):
        msg = {"text": "Привет!", "chat": {"id": 111}}
        await bot._handle_text(msg)

    assert len(sent) == 1
    assert "slash" in sent[0][1].lower() or "/help" in sent[0][1]


async def test_handle_text_calls_query_agent_when_wired() -> None:
    agent = MagicMock()
    agent.handle_query = AsyncMock(return_value="Привет, оператор!")
    bot = _make_bot_with_agent(agent)

    sent: list[str] = []

    async def fake_send(chat_id: int, text: str, **kwargs: object) -> None:
        sent.append(text)

    with patch.object(bot, "_send", side_effect=fake_send):
        msg = {"text": "Привет!", "chat": {"id": 111}}
        await bot._handle_text(msg)

    agent.handle_query.assert_called_once_with("Привет!", chat_id=111)
    assert sent == ["Привет, оператор!"]


async def test_ask_command_routes_to_handle_text() -> None:
    agent = MagicMock()
    agent.handle_query = AsyncMock(return_value="Статус: всё норм")
    bot = _make_bot_with_agent(agent)

    sent: list[str] = []

    async def fake_send(chat_id: int, text: str, **kwargs: object) -> None:
        sent.append(text)

    with patch.object(bot, "_send", side_effect=fake_send):
        msg = {"text": "/ask что сейчас?", "chat": {"id": 111}}
        await bot._handle_message(msg)

    agent.handle_query.assert_called_once_with("что сейчас?", chat_id=111)
    assert "Статус" in sent[0]


async def test_ask_command_empty_query_returns_prompt() -> None:
    bot = _make_bot_with_agent(None)
    sent: list[str] = []

    async def fake_send(chat_id: int, text: str, **kwargs: object) -> None:
        sent.append(text)

    with patch.object(bot, "_send", side_effect=fake_send):
        msg = {"text": "/ask", "chat": {"id": 111}}
        await bot._handle_message(msg)

    assert len(sent) == 1
    assert "ask" in sent[0].lower() or "запрос" in sent[0].lower()


async def test_free_text_routed_to_handle_text_when_allowed() -> None:
    agent = MagicMock()
    agent.handle_query = AsyncMock(return_value="Ответ")
    bot = _make_bot_with_agent(agent)

    sent: list[str] = []

    async def fake_send(chat_id: int, text: str, **kwargs: object) -> None:
        sent.append(text)

    with patch.object(bot, "_send", side_effect=fake_send):
        # Simulate _fetch_updates processing a free-text message
        await bot._handle_text({"text": "что сейчас?", "chat": {"id": 111}})

    agent.handle_query.assert_called_once()
