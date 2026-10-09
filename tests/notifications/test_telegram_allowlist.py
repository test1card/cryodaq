"""Verify Telegram command bot default-deny on empty allowlist (Phase 2b Codex K.1)."""

from __future__ import annotations

import pytest


def test_empty_allowlist_with_commands_enabled_raises():
    from cryodaq.notifications.telegram_commands import TelegramCommandBot

    with pytest.raises(ValueError, match="allowed_chat_ids"):
        TelegramCommandBot(
            bot_token="fake:token",
            allowed_chat_ids=[],
            commands_enabled=True,
        )


def test_none_allowlist_with_commands_enabled_raises():
    from cryodaq.notifications.telegram_commands import TelegramCommandBot

    with pytest.raises(ValueError, match="allowed_chat_ids"):
        TelegramCommandBot(
            bot_token="fake:token",
            allowed_chat_ids=None,
            commands_enabled=True,
        )


def test_empty_allowlist_with_commands_disabled_ok():
    from cryodaq.notifications.telegram_commands import TelegramCommandBot

    bot = TelegramCommandBot(
        bot_token="fake:token",
        allowed_chat_ids=[],
        commands_enabled=False,
    )
    assert bot is not None


def test_non_empty_allowlist_ok():
    from cryodaq.notifications.telegram_commands import TelegramCommandBot

    bot = TelegramCommandBot(
        bot_token="fake:token",
        allowed_chat_ids=[770134831],
        commands_enabled=True,
    )
    assert bot._is_chat_allowed(770134831) is True
    assert bot._is_chat_allowed(999999999) is False


@pytest.mark.asyncio
async def test_handle_message_defense_in_depth_blocks_unknown_chat(caplog):
    """Codex Phase 2b Block C P1: _handle_message must re-check the
    allowlist, not rely on _fetch_updates having filtered upstream.
    Defense-in-depth against future direct callers (and tests).
    """
    import logging
    from unittest.mock import AsyncMock, MagicMock

    from cryodaq.notifications.telegram_commands import TelegramCommandBot

    bot = TelegramCommandBot(
        broker=MagicMock(),
        alarm_engine=MagicMock(),
        bot_token="fake:token",
        allowed_chat_ids=[1234],
        commands_enabled=True,
    )
    bot._send = AsyncMock()
    bot._cmd_status = MagicMock(return_value="status")  # type: ignore[assignment]

    caplog.set_level(logging.WARNING)
    # An unknown chat id reaching _handle_message directly must be denied.
    await bot._handle_message(
        {
            "text": "/status",
            "chat": {"id": 99999999},
            "from": {"id": 1, "username": "u", "first_name": "x"},
        }
    )
    bot._send.assert_not_called()
    assert any("Отклонён" in r.message or "_handle_message" in r.message for r in caplog.records)


def test_default_deny_on_unknown_chat():
    """The check is now ``chat_id in allowed_ids``, not ``allowed and chat_id in``."""
    from cryodaq.notifications.telegram_commands import TelegramCommandBot

    bot = TelegramCommandBot(
        bot_token="fake:token",
        allowed_chat_ids=[1, 2, 3],
        commands_enabled=True,
    )
    assert bot._is_chat_allowed(1) is True
    assert bot._is_chat_allowed(99) is False
