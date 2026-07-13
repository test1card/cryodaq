"""DataBroker — центральная шина данных движка CryoDAQ.

Принимает Reading от драйверов, раздаёт подписчикам (writer, alarms, ZMQ publisher)
через ограниченные asyncio.Queue. Переполненные очереди сбрасывают старые данные
(OverflowPolicy.DROP_OLDEST) — утечки памяти недопустимы.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum

from cryodaq.channels.persistence import MAX_PERSISTED_ENVELOPE_BYTES
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 10_000

# Closed engine-transport marker.  It is deliberately outside the public
# Reading schema: DataBroker overwrites any caller-supplied value on a detached
# Reading copy, and the ZMQ publisher must strip it from its own metadata copy
# before encoding public metadata.
PERSISTENCE_AUTHORITATIVE_METADATA_KEY = "_cryodaq_persistence_authoritative"


@dataclass(frozen=True, slots=True)
class PublishedReading:
    """F35 D4: one delivered Reading paired with its descriptor envelope bytes.

    Delivered only to subscribers that opted in via
    ``subscribe(..., wants_descriptor_envelope=True)`` — every other
    subscriber keeps receiving a bare ``Reading``, byte-for-byte unchanged.
    ``descriptor_envelope`` is already-bounded canonical JSON bytes (or
    ``None``) issued upstream by ``SQLiteWriter``'s commit receipt; this
    pairing performs no re-derivation, no lookup, no synthesis. Plain
    in-process data-only value passed by value, never by object identity.
    """

    reading: Reading
    descriptor_envelope: bytes | None


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
    # F35 D4: opt-in only. False (default) reproduces current behaviour
    # exactly — the subscriber's queue keeps carrying bare Reading.
    wants_descriptor_envelope: bool = False
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
        wants_descriptor_envelope: bool = False,
    ) -> asyncio.Queue[Reading]:
        """Создать подписку. Возвращает очередь для чтения.

        ``maxsize`` must be strictly positive. A large buffer is legitimate
        here (subscribers pick their own depth), but ``maxsize=0`` (or
        negative) means an UNBOUNDED queue: ``full()`` never returns True,
        so the DROP_OLDEST / DROP_NEWEST overflow policy never fires and the
        queue grows without limit — the exact memory leak this module's
        contract forbids. Reject it rather than silently treat 0 as infinite.

        ``wants_descriptor_envelope`` (F35 D4): opt-in only, default False.
        When True, this subscriber's queue carries ``PublishedReading``
        (reading + descriptor envelope bytes) instead of a bare ``Reading``.
        Every other subscriber is unaffected.
        """
        if maxsize <= 0:
            raise ValueError(
                f"DataBroker.subscribe maxsize must be > 0 (got {maxsize}); "
                "a non-positive maxsize makes the queue unbounded and defeats "
                "the overflow policy (unbounded memory growth)."
            )
        async with self._lock:
            if name in self._subscribers:
                raise ValueError(f"Подписчик '{name}' уже зарегистрирован")
            queue: asyncio.Queue[Reading] = asyncio.Queue(maxsize=maxsize)
            self._subscribers[name] = Subscription(
                name=name,
                queue=queue,
                policy=policy,
                filter_fn=filter_fn,
                wants_descriptor_envelope=wants_descriptor_envelope,
            )
            logger.info("Подписчик '%s' зарегистрирован (maxsize=%d)", name, maxsize)
            return queue

    async def unsubscribe(self, name: str) -> None:
        """Удалить подписку."""
        async with self._lock:
            sub = self._subscribers.pop(name, None)
            if sub:
                logger.info("Подписчик '%s' удалён (потеряно сообщений: %d)", name, sub.dropped)

    async def publish(
        self,
        reading: Reading,
        *,
        persistence_authoritative: bool = False,
        descriptor_envelope: bytes | None = None,
    ) -> None:
        """Разослать Reading всем подписчикам.

        ``persistence_authoritative`` is an internal provenance bit for closed
        engine transports.  A detached Reading and metadata mapping prevent a
        caller from forging the bit or observing a broker-side mutation.

        ``descriptor_envelope`` (F35 D4): optional, already-bounded canonical
        descriptor bytes for this exact reading. Delivered only to
        subscribers that opted in via ``wants_descriptor_envelope=True``
        (as a ``PublishedReading`` pair); every other subscriber keeps
        receiving the bare detached ``Reading``, unchanged.
        """
        if type(persistence_authoritative) is not bool:
            raise TypeError("persistence_authoritative must be exactly bool")
        if descriptor_envelope is not None and type(descriptor_envelope) is not bytes:
            raise TypeError("descriptor_envelope must be exactly bytes or None")
        if descriptor_envelope is not None and len(descriptor_envelope) > MAX_PERSISTED_ENVELOPE_BYTES:
            logger.warning(
                "Dropping oversized descriptor envelope before broker enqueue (%d > %d bytes)",
                len(descriptor_envelope),
                MAX_PERSISTED_ENVELOPE_BYTES,
            )
            descriptor_envelope = None
        metadata = dict(reading.metadata)
        metadata.pop(PERSISTENCE_AUTHORITATIVE_METADATA_KEY, None)
        if persistence_authoritative:
            metadata[PERSISTENCE_AUTHORITATIVE_METADATA_KEY] = persistence_authoritative
        delivered = replace(
            reading,
            metadata=metadata,
        )
        self._total_published += 1
        for sub in tuple(self._subscribers.values()):
            try:
                if sub.filter_fn:
                    filter_reading = replace(delivered, metadata=dict(delivered.metadata))
                    if not sub.filter_fn(filter_reading):
                        continue
                item: Reading | PublishedReading = (
                    PublishedReading(reading=delivered, descriptor_envelope=descriptor_envelope)
                    if sub.wants_descriptor_envelope
                    else delivered
                )
                if sub.queue.full():
                    if sub.policy == OverflowPolicy.DROP_OLDEST:
                        try:
                            sub.queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        else:
                            sub.queue.task_done()
                        sub.dropped += 1
                    elif sub.policy == OverflowPolicy.DROP_NEWEST:
                        sub.dropped += 1
                        continue
                try:
                    sub.queue.put_nowait(item)
                except asyncio.QueueFull:
                    sub.dropped += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "DataBroker subscriber '%s' raised during publish; continuing fan-out",
                    sub.name,
                )

    async def publish_batch(
        self,
        readings: list[Reading],
        *,
        persistence_authoritative: bool = False,
        descriptor_envelopes: Sequence[bytes | None] | None = None,
    ) -> None:
        """Опубликовать пакет показаний with one exact provenance value.

        ``descriptor_envelopes`` (F35 D4): optional, positionally paired with
        ``readings`` (``descriptor_envelopes[i]`` belongs to ``readings[i]``).
        ``None`` (default) reproduces current behaviour exactly for every
        subscriber. A cardinality mismatch or a non-``bytes``/``None`` element
        is rejected before any delivery — fail closed, never a partial/
        zip-truncated fan-out.
        """
        if type(persistence_authoritative) is not bool:
            raise TypeError("persistence_authoritative must be exactly bool")
        if descriptor_envelopes is not None:
            if len(descriptor_envelopes) != len(readings):
                raise ValueError(
                    f"descriptor_envelopes length ({len(descriptor_envelopes)}) disagrees with "
                    f"readings length ({len(readings)})"
                )
            if any(env is not None and type(env) is not bytes for env in descriptor_envelopes):
                raise TypeError("descriptor_envelope must be exactly bytes or None")
        envelopes = descriptor_envelopes if descriptor_envelopes is not None else [None] * len(readings)
        for reading, envelope in zip(readings, envelopes, strict=True):
            await self.publish(
                reading,
                persistence_authoritative=persistence_authoritative,
                descriptor_envelope=envelope,
            )

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
