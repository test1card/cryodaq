"""DataBroker — центральная шина данных движка CryoDAQ.

Принимает Reading от драйверов, раздаёт подписчикам (writer, alarms, ZMQ publisher)
через ограниченные asyncio.Queue. Переполненные очереди сбрасывают старые данные
(OverflowPolicy.DROP_OLDEST) — утечки памяти недопустимы.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 10_000


class OverflowPolicy(Enum):
    """Политика при переполнении очереди подписчика."""

    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"


@dataclass
class Subscription:
    """Подписка на данные брокера."""

    name: str
    queue: asyncio.Queue[Reading]
    policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST
    filter_fn: Callable[[Reading], bool] | None = None
    dropped: int = field(default=0, init=False)


class DataBroker:
    """Fan-out брокер: драйверы публикуют Reading, подписчики получают копии.

    Использование::

        broker = DataBroker()
        q = broker.subscribe("sqlite_writer", maxsize=5000)
        await broker.publish(reading)
        r = await q.get()
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, Subscription] = {}
        self._lock = asyncio.Lock()
        self._total_published: int = 0

    async def subscribe(
        self,
        name: str,
        *,
        maxsize: int = DEFAULT_QUEUE_SIZE,
        policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST,
        filter_fn: Callable[[Reading], bool] | None = None,
    ) -> asyncio.Queue[Reading]:
        """Создать подписку. Возвращает очередь для чтения."""
        async with self._lock:
            if name in self._subscribers:
                raise ValueError(f"Подписчик '{name}' уже зарегистрирован")
            queue: asyncio.Queue[Reading] = asyncio.Queue(maxsize=maxsize)
            self._subscribers[name] = Subscription(
                name=name, queue=queue, policy=policy, filter_fn=filter_fn
            )
            logger.info("Подписчик '%s' зарегистрирован (maxsize=%d)", name, maxsize)
            return queue

    async def unsubscribe(self, name: str) -> None:
        """Удалить подписку."""
        async with self._lock:
            sub = self._subscribers.pop(name, None)
            if sub:
                logger.info("Подписчик '%s' удалён (потеряно сообщений: %d)", name, sub.dropped)

    async def publish(self, reading: Reading) -> None:
        """Разослать Reading всем подписчикам."""
        self._total_published += 1
        for sub in tuple(self._subscribers.values()):
            try:
                if sub.filter_fn and not sub.filter_fn(reading):
                    continue
                if sub.queue.full():
                    if sub.policy == OverflowPolicy.DROP_OLDEST:
                        try:
                            sub.queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        sub.dropped += 1
                    elif sub.policy == OverflowPolicy.DROP_NEWEST:
                        sub.dropped += 1
                        continue
                try:
                    sub.queue.put_nowait(reading)
                except asyncio.QueueFull:
                    sub.dropped += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "DataBroker subscriber '%s' raised during publish; continuing fan-out",
                    sub.name,
                )

    async def publish_batch(self, readings: list[Reading]) -> None:
        """Опубликовать пакет показаний."""
        for reading in readings:
            await self.publish(reading)

    @property
    def stats(self) -> dict[str, dict[str, int]]:
        """Статистика по подписчикам (для мониторинга)."""
        return {
            name: {
                "queued": sub.queue.qsize(),
                "dropped": sub.dropped,
            }
            for name, sub in self._subscribers.items()
        } | {"_total_published": {"count": self._total_published}}
