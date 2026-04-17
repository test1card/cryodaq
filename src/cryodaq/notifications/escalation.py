"""Цепочка эскалации Telegram-уведомлений при критических событиях.

EscalationService рассылает сообщения по заданной цепочке чатов с задержками.
При отмене (проблема решена) — отменяет ещё не отправленные уведомления.

Конфигурация (config/notifications.yaml или .local.yaml):

    escalation:
      - chat_id: 123456789    # первый получатель — без задержки
        delay_minutes: 0
      - chat_id: 987654321    # старший инженер — через 15 мин
        delay_minutes: 15
      - chat_id: 111222333    # руководитель — через 30 мин
        delay_minutes: 30
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cryodaq.notifications.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


class EscalationService:
    """Цепочка эскалации при missed prompts и критических событиях."""

    def __init__(self, notifier: TelegramNotifier, config: dict) -> None:
        """
        Параметры
        ----------
        notifier:
            TelegramNotifier для отправки сообщений.
        config:
            Словарь конфигурации уведомлений. Ожидается ключ ``escalation``
            со списком ``{chat_id, delay_minutes}``.
        """
        self._notifier = notifier
        self._chain: list[dict] = config.get("escalation", [])
        self._pending: dict[str, asyncio.Task] = {}

    async def escalate(self, event_type: str, message: str) -> None:
        """Запустить цепочку эскалации.

        Создаёт asyncio-задачи для каждого уровня цепочки. Каждый уровень
        ждёт свою задержку и затем отправляет сообщение.

        Параметры
        ----------
        event_type:
            Тип события (например, ``"shift_missed"``, ``"emergency"``).
            Используется как ключ для отмены через :meth:`cancel`.
        message:
            Текст уведомления.
        """
        for level in self._chain:
            chat_id = level.get("chat_id")
            if not chat_id:
                continue
            delay_s = float(level.get("delay_minutes", 0)) * 60
            key = f"{event_type}_{chat_id}"
            # Отменить предыдущую задачу для этого ключа, если есть
            existing = self._pending.get(key)
            if existing and not existing.done():
                existing.cancel()
            task = asyncio.create_task(
                self._delayed_send(chat_id, message, delay_s),
                name=f"escalation_{key}",
            )
            self._pending[key] = task
            logger.debug("Эскалация %s: chat_id=%s, задержка=%.0f с", event_type, chat_id, delay_s)

    async def cancel(self, event_type: str) -> None:
        """Отменить все pending-уведомления для данного типа события.

        Параметры
        ----------
        event_type:
            Тип события для отмены (должен совпадать с переданным в :meth:`escalate`).
        """
        prefix = f"{event_type}_"
        to_cancel = [key for key in list(self._pending) if key.startswith(prefix)]
        for key in to_cancel:
            task = self._pending.pop(key)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if to_cancel:
            logger.info("Эскалация %s отменена (%d задач)", event_type, len(to_cancel))

    async def _delayed_send(self, chat_id: int, message: str, delay_s: float) -> None:
        try:
            if delay_s > 0:
                await asyncio.sleep(delay_s)
            await self._notifier.send_message(chat_id, message)
            logger.info("Эскалация отправлена: chat_id=%s", chat_id)
        except asyncio.CancelledError:
            logger.debug("Эскалация отменена до отправки: chat_id=%s", chat_id)
            raise
        except Exception as exc:
            logger.error("Ошибка отправки эскалации на chat_id=%s: %s", chat_id, exc)
