"""DataBroker — центральная шина данных движка CryoDAQ.

Принимает Reading от драйверов, раздаёт подписчикам (writer, alarms, ZMQ publisher)
через ограниченные asyncio.Queue. Переполненные очереди сбрасывают старые данные
(OverflowPolicy.DROP_OLDEST) — утечки памяти недопустимы.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

from cryodaq.channels.persistence import MAX_PERSISTED_ENVELOPE_BYTES
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

DEFAULT_QUEUE_SIZE = 10_000
REQUIRED_PUBLICATION_TIMEOUT_S = 5.0

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


@dataclass(frozen=True, slots=True)
class RequiredPublicationReceipt:
    """Broker-issued proof that the retained publisher accepted one event."""

    request_id: str
    request_fingerprint: str
    _authority: object = field(repr=False, compare=False)


class _RequiredPublicationState(Enum):
    UNCLAIMED = "unclaimed"
    CLAIMED = "claimed"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class _RequiredPublicationCallerCancelled(RuntimeError):
    """Internal marker for a safely withdrawn cancelled publication."""


@dataclass(slots=True)
class RequiredPublication:
    """One revocable-until-claimed required-publisher envelope."""

    reading: Reading
    request_id: str
    request_fingerprint: str
    _settlement: asyncio.Future[None] = field(repr=False)
    _state: _RequiredPublicationState = field(
        default=_RequiredPublicationState.UNCLAIMED,
        init=False,
        repr=False,
    )

    def claim(self) -> Reading:
        """Irrevocably acquire the envelope before beginning its send."""

        if self._state is not _RequiredPublicationState.UNCLAIMED:
            raise RuntimeError("required publication is no longer claimable")
        self._state = _RequiredPublicationState.CLAIMED
        return self.reading

    def acknowledge(self) -> None:
        if self._state is _RequiredPublicationState.UNCLAIMED:
            raise RuntimeError("required publication must be claimed before acknowledgement")
        if self._state is _RequiredPublicationState.CLAIMED:
            self._state = _RequiredPublicationState.ACKNOWLEDGED
            self._settlement.set_result(None)
            return
        if self._state is _RequiredPublicationState.ACKNOWLEDGED:
            return
        raise RuntimeError("required publication is no longer acknowledgeable")

    def reject(self) -> None:
        if self._state in (
            _RequiredPublicationState.UNCLAIMED,
            _RequiredPublicationState.CLAIMED,
        ):
            self._state = _RequiredPublicationState.REJECTED
            self._settlement.set_exception(RuntimeError("required publisher did not settle the event"))
            return
        if self._state in (
            _RequiredPublicationState.REJECTED,
            _RequiredPublicationState.WITHDRAWN,
        ):
            return
        raise RuntimeError("acknowledged required publication cannot be rejected")

    def _withdraw_if_unclaimed(self, failure: RuntimeError) -> bool:
        if self._state is not _RequiredPublicationState.UNCLAIMED:
            return False
        self._state = _RequiredPublicationState.WITHDRAWN
        self._settlement.set_exception(failure)
        return True


async def _await_required_publication(envelope: RequiredPublication) -> None:
    """Await exact ACK/REJECT while retaining claimed work on cancellation."""

    cancellation: asyncio.CancelledError | None = None
    settlement = envelope._settlement

    async def observe() -> BaseException | None:
        try:
            await settlement
        except BaseException as exc:
            return exc
        return None

    observer = asyncio.create_task(
        observe(),
        name="required-publication-terminal-observer",
    )
    while not observer.done():
        try:
            await asyncio.shield(observer)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
            envelope._withdraw_if_unclaimed(_RequiredPublicationCallerCancelled())
    settlement_error = observer.result()
    if isinstance(settlement_error, _RequiredPublicationCallerCancelled):
        if cancellation is None:
            raise RuntimeError("required publication withdrawal lost caller cancellation") from None
        raise cancellation
    if settlement_error is not None:
        if cancellation is not None and not isinstance(settlement_error, asyncio.CancelledError):
            raise settlement_error from cancellation
        raise settlement_error
    if cancellation is not None:
        raise cancellation


class OverflowPolicy(Enum):
    """Политика при переполнении очереди подписчика."""

    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"


@dataclass
class Subscription:
    """Подписка на данные брокера."""

    name: str
    queue: asyncio.Queue[Any]
    policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST
    filter_fn: Callable[[Reading], bool] | None = None
    # F35 D4: opt-in only. False (default) reproduces current behaviour
    # exactly — the subscriber's queue keeps carrying bare Reading.
    wants_descriptor_envelope: bool = False
    required_publisher: bool = False
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
        self._required_publisher_name: str | None = None
        self._required_publication_authority = object()

    async def subscribe(
        self,
        name: str,
        *,
        maxsize: int = DEFAULT_QUEUE_SIZE,
        policy: OverflowPolicy = OverflowPolicy.DROP_OLDEST,
        filter_fn: Callable[[Reading], bool] | None = None,
        wants_descriptor_envelope: bool = False,
        required_publisher: bool = False,
    ) -> asyncio.Queue[Any]:
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
        if type(required_publisher) is not bool:
            raise TypeError("required_publisher must be exactly bool")
        async with self._lock:
            if name in self._subscribers:
                raise ValueError(f"Подписчик '{name}' уже зарегистрирован")
            if required_publisher and self._required_publisher_name is not None:
                raise RuntimeError("required publisher is already registered")
            queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
            self._subscribers[name] = Subscription(
                name=name,
                queue=queue,
                policy=policy,
                filter_fn=filter_fn,
                wants_descriptor_envelope=wants_descriptor_envelope,
                required_publisher=required_publisher,
            )
            if required_publisher:
                self._required_publisher_name = name
            logger.info("Подписчик '%s' зарегистрирован (maxsize=%d)", name, maxsize)
            return queue

    async def unsubscribe(
        self,
        name: str,
        *,
        expected_queue: asyncio.Queue[Any] | None = None,
    ) -> bool:
        """Remove one subscription, optionally only for its exact queue owner.

        Lifecycle rollback must never remove a same-name subscription acquired
        by another owner. Callers that retain the queue returned by
        :meth:`subscribe` can bind removal to that exact object with
        ``expected_queue``. The legacy name-only form remains an unconditional
        administrative removal.
        """

        async with self._lock:
            sub = self._subscribers.get(name)
            if sub is None or (expected_queue is not None and sub.queue is not expected_queue):
                return False
            self._subscribers.pop(name)
            if sub:
                if sub.required_publisher and self._required_publisher_name == name:
                    self._required_publisher_name = None
                    while True:
                        try:
                            queued = sub.queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                        try:
                            if type(queued) is RequiredPublication:
                                queued.reject()
                        finally:
                            sub.queue.task_done()
                logger.info("Подписчик '%s' удалён (потеряно сообщений: %d)", name, sub.dropped)
            return True

    async def publish_required(
        self,
        reading: Reading,
        *,
        request_id: str,
        request_fingerprint: str,
    ) -> RequiredPublicationReceipt:
        """Issue authority only after the retained publisher settles a send."""

        if (
            type(request_id) is not str
            or len(request_id) != 32
            or any(char not in "0123456789abcdef" for char in request_id)
        ):
            raise ValueError("required publication request_id is invalid")
        if (
            type(request_fingerprint) is not str
            or len(request_fingerprint) != 64
            or any(char not in "0123456789abcdef" for char in request_fingerprint)
        ):
            raise ValueError("required publication fingerprint is invalid")
        loop = asyncio.get_running_loop()
        settlement: asyncio.Future[None] = loop.create_future()
        async with self._lock:
            name = self._required_publisher_name
            sub = self._subscribers.get(name) if name is not None else None
            if sub is None or not sub.required_publisher:
                raise RuntimeError("required publisher is unavailable")
            if sub.queue.full():
                raise RuntimeError("required publisher queue is full")
            envelope = RequiredPublication(
                # Required publications carry audit evidence; detach nested
                # metadata too so a caller cannot mutate the queued event
                # after admission but before the publisher settles it.
                reading=replace(reading, metadata=copy.deepcopy(reading.metadata)),
                request_id=request_id,
                request_fingerprint=request_fingerprint,
                _settlement=settlement,
            )
            sub.queue.put_nowait(envelope)
        expiry = loop.call_later(
            REQUIRED_PUBLICATION_TIMEOUT_S,
            envelope._withdraw_if_unclaimed,
            RuntimeError("required publisher settlement timed out before claim"),
        )
        try:
            await _await_required_publication(envelope)
        finally:
            expiry.cancel()
        return RequiredPublicationReceipt(
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            _authority=self._required_publication_authority,
        )

    def validates_required_publication(
        self,
        receipt: object,
        *,
        request_id: str,
        request_fingerprint: str,
    ) -> bool:
        """Accept only a receipt issued by this exact broker instance."""

        return (
            type(receipt) is RequiredPublicationReceipt
            and receipt._authority is self._required_publication_authority
            and receipt.request_id == request_id
            and receipt.request_fingerprint == request_fingerprint
        )

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
        metadata = copy.deepcopy(reading.metadata)
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
                    # Filters are untrusted subscriber policy. Give them a
                    # disposable copy, then construct delivery independently
                    # so a predicate cannot smuggle metadata mutations into
                    # the accepted reading or retain a reference to it.
                    filter_reading = replace(delivered, metadata=copy.deepcopy(delivered.metadata))
                    if not sub.filter_fn(filter_reading):
                        continue
                subscriber_reading = replace(delivered, metadata=copy.deepcopy(delivered.metadata))
                item: Reading | PublishedReading = (
                    PublishedReading(reading=subscriber_reading, descriptor_envelope=descriptor_envelope)
                    if sub.wants_descriptor_envelope
                    else subscriber_reading
                )
                if sub.queue.full():
                    if sub.required_publisher:
                        # Ordinary telemetry may be dropped, but it must never
                        # evict a retained required-publication envelope.
                        sub.dropped += 1
                        continue
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
