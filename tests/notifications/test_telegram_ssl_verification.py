"""Tests for SSL verification config knob — HF v0.47.1 invariant.

verify_ssl=False must route through aiohttp.TCPConnector(ssl=False).
verify_ssl=True (default) must leave existing behavior intact.
WARNING must be logged once at construction when verify_ssl=False.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cryodaq.notifications.telegram import TelegramNotifier
from cryodaq.notifications.telegram_commands import TelegramCommandBot

# ---------------------------------------------------------------------------
# TelegramNotifier
# ---------------------------------------------------------------------------


def test_notifier_stores_verify_ssl_true() -> None:
    notifier = TelegramNotifier(bot_token="token:ABC", chat_id=123, verify_ssl=True)
    assert notifier._verify_ssl is True


def test_notifier_stores_verify_ssl_false() -> None:
    notifier = TelegramNotifier(bot_token="token:ABC", chat_id=123, verify_ssl=False)
    assert notifier._verify_ssl is False


def test_notifier_default_verify_ssl_is_true() -> None:
    notifier = TelegramNotifier(bot_token="token:ABC", chat_id=123)
    assert notifier._verify_ssl is True


def test_notifier_logs_warning_when_ssl_disabled(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    with caplog.at_level(logging.WARNING, logger="cryodaq.notifications.telegram"):
        TelegramNotifier(bot_token="token:ABC", chat_id=123, verify_ssl=False)
    assert any("SSL" in r.message for r in caplog.records)


def test_notifier_no_warning_when_ssl_enabled(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    with caplog.at_level(logging.WARNING, logger="cryodaq.notifications.telegram"):
        TelegramNotifier(bot_token="token:ABC", chat_id=123, verify_ssl=True)
    ssl_warnings = [r for r in caplog.records if "SSL" in r.message]
    assert not ssl_warnings


async def test_notifier_get_session_uses_connector_ssl_false() -> None:
    notifier = TelegramNotifier(bot_token="token:ABC", chat_id=123, verify_ssl=False)
    with patch("aiohttp.TCPConnector") as mock_connector, \
         patch("aiohttp.ClientSession") as mock_session:
        mock_session.return_value = MagicMock()
        await notifier._get_session()
    mock_connector.assert_called_once_with(ssl=False)


async def test_notifier_get_session_uses_connector_ssl_true() -> None:
    notifier = TelegramNotifier(bot_token="token:ABC", chat_id=123, verify_ssl=True)
    with patch("aiohttp.TCPConnector") as mock_connector, \
         patch("aiohttp.ClientSession") as mock_session:
        mock_session.return_value = MagicMock()
        await notifier._get_session()
    mock_connector.assert_called_once_with(ssl=True)


# ---------------------------------------------------------------------------
# TelegramCommandBot
# ---------------------------------------------------------------------------


def _make_bot(verify_ssl: bool = True) -> TelegramCommandBot:
    return TelegramCommandBot(
        broker=None,
        alarm_engine=None,
        bot_token="token:DEF",
        allowed_chat_ids=[456],
        verify_ssl=verify_ssl,
    )


def test_bot_stores_verify_ssl_true() -> None:
    bot = _make_bot(verify_ssl=True)
    assert bot._verify_ssl is True


def test_bot_stores_verify_ssl_false() -> None:
    bot = _make_bot(verify_ssl=False)
    assert bot._verify_ssl is False


def test_bot_default_verify_ssl_is_true() -> None:
    bot = _make_bot()
    assert bot._verify_ssl is True


def test_bot_logs_warning_when_ssl_disabled(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    with caplog.at_level(logging.WARNING, logger="cryodaq.notifications.telegram_commands"):
        _make_bot(verify_ssl=False)
    assert any("SSL" in r.message for r in caplog.records)


def test_bot_no_warning_when_ssl_enabled(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    with caplog.at_level(logging.WARNING, logger="cryodaq.notifications.telegram_commands"):
        _make_bot(verify_ssl=True)
    ssl_warnings = [r for r in caplog.records if "SSL" in r.message]
    assert not ssl_warnings


async def test_bot_get_session_uses_connector_ssl_false() -> None:
    bot = _make_bot(verify_ssl=False)
    with patch("aiohttp.TCPConnector") as mock_connector, \
         patch("aiohttp.ClientSession") as mock_session:
        mock_session.return_value = MagicMock()
        await bot._get_session()
    mock_connector.assert_called_once_with(ssl=False)


async def test_bot_get_session_uses_connector_ssl_true() -> None:
    bot = _make_bot(verify_ssl=True)
    with patch("aiohttp.TCPConnector") as mock_connector, \
         patch("aiohttp.ClientSession") as mock_session:
        mock_session.return_value = MagicMock()
        await bot._get_session()
    mock_connector.assert_called_once_with(ssl=True)
