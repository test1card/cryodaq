"""Regression tests for Telegram verify_ssl config knob."""

from __future__ import annotations

import aiohttp
import pytest
import yaml

from cryodaq.notifications.telegram import TelegramNotifier
from cryodaq.notifications.telegram_commands import TelegramCommandBot


def test_notifier_from_config_reads_verify_ssl_false(tmp_path) -> None:
    config_path = tmp_path / "notifications.local.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "telegram": {
                    "bot_token": "token:ABC",
                    "chat_id": 123,
                    "verify_ssl": False,
                }
            }
        ),
        encoding="utf-8",
    )

    notifier = TelegramNotifier.from_config(config_path)

    assert notifier._verify_ssl is False


def test_command_bot_accepts_verify_ssl_false() -> None:
    bot = TelegramCommandBot(
        bot_token="token:ABC",
        allowed_chat_ids=[123],
        verify_ssl=False,
    )

    assert bot._verify_ssl is False


@pytest.mark.parametrize("cls_name", ["notifier", "command_bot"])
async def test_get_session_passes_ssl_false_to_tcpconnector(
    cls_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    real_connector = aiohttp.TCPConnector

    def connector_spy(*args, **kwargs):
        captured["ssl"] = kwargs.get("ssl")
        return real_connector(*args, **kwargs)

    monkeypatch.setattr(aiohttp, "TCPConnector", connector_spy)
    if cls_name == "notifier":
        obj = TelegramNotifier(bot_token="token:ABC", chat_id=123, verify_ssl=False)
    else:
        obj = TelegramCommandBot(
            bot_token="token:ABC",
            allowed_chat_ids=[123],
            verify_ssl=False,
        )

    session = await obj._get_session()
    try:
        assert captured["ssl"] is False
    finally:
        await session.close()

