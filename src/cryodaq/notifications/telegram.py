"""Уведомления о тревогах через Telegram Bot API.

TelegramNotifier — async-коллбэк для AlarmEngine.  Отправляет
форматированные сообщения в указанный чат при активации/сбросе тревог.

Конфигурация (config/notifications.yaml):

    telegram:
      bot_token: "123456:ABC-DEF..."
      chat_id: -1001234567890
      send_cleared: true           # отправлять ли уведомление о сбросе
      timeout_s: 10.0              # таймаут HTTP-запроса
"""

from __future__ import annotations

import logging
from datetime import timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Эмодзи по уровню критичности
_SEVERITY_EMOJI: dict[str, str] = {
    "info": "ℹ️",
    "warning": "⚠️",
    "critical": "🚨",
}

# Эмодзи по типу события
_EVENT_EMOJI: dict[str, str] = {
    "activated": "🔔",
    "cleared": "✅",
    "acknowledged": "👁",
}


class TelegramNotifier:
    """Отправка уведомлений о тревогах через Telegram.

    Используется как notifier-коллбэк для AlarmEngine::

        notifier = TelegramNotifier.from_config(Path("config/notifications.yaml"))
        alarm_engine = AlarmEngine(broker, notifiers=[notifier])

    Параметры
    ----------
    bot_token:
        Токен Telegram-бота (от @BotFather).
    chat_id:
        ID чата или группы для отправки уведомлений.
    send_cleared:
        Отправлять ли уведомления при сбросе тревоги.  По умолчанию True.
    timeout_s:
        Таймаут HTTP-запроса к Telegram API.  По умолчанию 10 с.
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: int | str,
        *,
        send_cleared: bool = True,
        timeout_s: float = 10.0,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._send_cleared = send_cleared
        self._timeout_s = timeout_s
        self._api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    @classmethod
    def from_config(cls, config_path: Path) -> TelegramNotifier:
        """Создать notifier из YAML-файла конфигурации.

        Ожидаемая структура::

            telegram:
              bot_token: "..."
              chat_id: ...
              send_cleared: true
              timeout_s: 10.0

        Параметры
        ----------
        config_path:
            Путь к config/notifications.yaml.

        Исключения
        ----------
        FileNotFoundError:  Файл не найден.
        KeyError:           Отсутствуют обязательные поля.
        """
        if not config_path.exists():
            raise FileNotFoundError(
                f"Файл конфигурации уведомлений не найден: {config_path}"
            )

        with config_path.open(encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh)

        tg = raw["telegram"]
        return cls(
            bot_token=str(tg["bot_token"]),
            chat_id=tg["chat_id"],
            send_cleared=bool(tg.get("send_cleared", True)),
            timeout_s=float(tg.get("timeout_s", 10.0)),
        )

    async def __call__(self, event: Any) -> None:
        """Async-коллбэк для AlarmEngine.

        Параметры
        ----------
        event:
            Экземпляр AlarmEvent (из cryodaq.core.alarm).
        """
        # Пропустить cleared, если не настроено
        if event.event_type == "cleared" and not self._send_cleared:
            return

        # Пропустить acknowledged (внутреннее событие)
        if event.event_type == "acknowledged":
            return

        text = self._format_message(event)
        await self._send(text)

    # ------------------------------------------------------------------
    # Форматирование сообщения
    # ------------------------------------------------------------------

    def _format_message(self, event: Any) -> str:
        """Сформировать текст уведомления."""
        severity_str = event.severity.value if hasattr(event.severity, "value") else str(event.severity)
        severity_emoji = _SEVERITY_EMOJI.get(severity_str, "❓")
        event_emoji = _EVENT_EMOJI.get(event.event_type, "")

        # Время в московском часовом поясе (UTC+3) — стандарт для ФИАН
        ts = event.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        time_str = ts.strftime("%H:%M:%S %d.%m.%Y")

        if event.event_type == "activated":
            header = f"{event_emoji} {severity_emoji} ТРЕВОГА"
        elif event.event_type == "cleared":
            header = f"{event_emoji} Тревога снята"
        else:
            header = f"{event_emoji} {event.event_type}"

        lines = [
            header,
            "",
            f"<b>{event.alarm_name}</b>",
            f"Канал: <code>{event.channel}</code>",
            f"Значение: <b>{event.value:.4g}</b>",
            f"Порог: {event.threshold:.4g}",
            f"Уровень: {severity_str.upper()}",
            f"Время: {time_str}",
        ]

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Отправка HTTP-запроса
    # ------------------------------------------------------------------

    async def _send(self, text: str) -> None:
        """Отправить сообщение через Telegram Bot API.

        Использует aiohttp для асинхронной отправки.  При недоступности
        библиотеки или ошибке сети — логирует и продолжает работу.
        """
        try:
            import aiohttp
        except ImportError:
            logger.error(
                "Библиотека aiohttp не установлена — Telegram-уведомления недоступны. "
                "Установите: pip install aiohttp"
            )
            return

        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            timeout = aiohttp.ClientTimeout(total=self._timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(self._api_url, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error(
                            "Telegram API ответил %d: %s", resp.status, body[:200],
                        )
                    else:
                        logger.debug("Telegram-уведомление отправлено: %s", text[:80])
        except Exception as exc:
            logger.error("Ошибка отправки Telegram-уведомления: %s", exc)
