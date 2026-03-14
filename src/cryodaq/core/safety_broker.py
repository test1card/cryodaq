"""Выделенный брокер данных безопасности.

SafetyBroker — отдельный канал от основного DataBroker:
- Прямая доставка от Scheduler к SafetyManager
- Неизменяемый список подписчиков (фиксируется при start)
- Переполнение очереди → FAULT (данные безопасности не отбрасываются)
- Отслеживает время последнего обновления по каждому прибору
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)


class SafetyBrokerOverflow(Exception):
    """Переполнение очереди безопасности — критическая ситуация."""


@dataclass
class _SafetySubscription:
    """Подписка в брокере безопасности (неизменяемая после регистрации)."""

    name: str
    queue: asyncio.Queue[Reading]
    maxsize: int


class SafetyBroker:
    """Выделенный брокер для данных, критичных для безопасности.

    Отличия от DataBroker:
    - Переполнение = FAULT (не DROP_OLDEST)
    - Подписчики фиксируются при freeze(), после чего список неизменяем
    - Отслеживает staleness каждого канала
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, _SafetySubscription] = {}
        self._frozen = False
        self._last_update: dict[str, float] = {}  # channel → monotonic time
        self._total_published: int = 0
        self._overflow_callback: Callable[[], Any] | None = None

    def subscribe(self, name: str, *, maxsize: int = 100) -> asyncio.Queue[Reading]:
        """Зарегистрировать подписчика. Вызывать до freeze()."""
        if self._frozen:
            raise RuntimeError("SafetyBroker заморожен — подписка невозможна")
        if name in self._subscribers:
            raise ValueError(f"Подписчик '{name}' уже зарегистрирован")

        queue: asyncio.Queue[Reading] = asyncio.Queue(maxsize=maxsize)
        self._subscribers[name] = _SafetySubscription(
            name=name, queue=queue, maxsize=maxsize,
        )
        logger.info("SafetyBroker: подписчик '%s' зарегистрирован (maxsize=%d)", name, maxsize)
        return queue

    def freeze(self) -> None:
        """Заморозить список подписчиков. После этого subscribe() недоступен."""
        self._frozen = True
        logger.info(
            "SafetyBroker заморожен: %d подписчиков", len(self._subscribers),
        )

    def set_overflow_callback(self, callback: Callable[[], Any]) -> None:
        """Установить callback на переполнение (вызывает FAULT в SafetyManager)."""
        self._overflow_callback = callback

    async def publish(self, reading: Reading) -> None:
        """Опубликовать Reading всем подписчикам.

        При переполнении любой очереди — вызывает overflow_callback.
        """
        self._total_published += 1
        self._last_update[reading.channel] = time.monotonic()

        for sub in self._subscribers.values():
            if sub.queue.full():
                logger.critical(
                    "SafetyBroker ПЕРЕПОЛНЕНИЕ: подписчик '%s', канал '%s'. "
                    "Данные безопасности потеряны!",
                    sub.name, reading.channel,
                )
                if self._overflow_callback:
                    try:
                        result = self._overflow_callback()
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception:
                        logger.exception("Ошибка в overflow_callback")
                return  # Не пытаемся положить в полную очередь

            try:
                sub.queue.put_nowait(reading)
            except asyncio.QueueFull:
                pass  # Уже обработано выше

    async def publish_batch(self, readings: list[Reading]) -> None:
        """Опубликовать пакет."""
        for reading in readings:
            await self.publish(reading)

    def get_last_update(self, channel: str) -> float:
        """Время последнего обновления канала (monotonic)."""
        return self._last_update.get(channel, 0.0)

    def get_all_last_updates(self) -> dict[str, float]:
        """Все timestamps последних обновлений."""
        return dict(self._last_update)

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "total_published": self._total_published,
            "subscribers": len(self._subscribers),
            "frozen": self._frozen,
            "channels_tracked": len(self._last_update),
        }
