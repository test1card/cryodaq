"""Lightweight pub/sub event bus for engine events (not Reading data)."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class EngineEvent:
    """An engine-level event published to EventBus subscribers."""

    event_type: str  # "alarm_fired", "alarm_cleared", "phase_transition", "experiment_finalize", …
    timestamp: datetime
    payload: dict[str, Any]
    experiment_id: str | None = None


@dataclass(frozen=True, slots=True)
class RequiredEventPublicationReceipt:
    """Unforgeable proof of one all-target EventBus admission cut."""

    event_digest: str
    admitted_subscribers: int
    subscriber_names: tuple[str, ...]
    event_identity: str | None
    payload_digest: str | None
    _authority: object = field(repr=False, compare=False)


class EventBus:
    """Lightweight pub/sub for engine events (not Reading data).

    Subscribers receive a dedicated asyncio.Queue.  After any retained required
    observer settles, queue fanout is non-blocking: a full queue logs a warning
    and drops the event rather than blocking the engine event loop.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, asyncio.Queue[EngineEvent]] = {}
        self._required_publication_authority = object()
        self._required_observer_name: str | None = None
        self._required_observer: Callable[[EngineEvent], Awaitable[None]] | None = None

    def retain_required_observer(
        self,
        name: str,
        observer: Callable[[EngineEvent], Awaitable[None]],
    ) -> None:
        """Retain the sole persistence-first observer for ordinary events."""

        if type(name) is not str or not name or len(name) > 128 or not name.isascii():
            raise ValueError("required EventBus observer name is invalid")
        if not callable(observer):
            raise TypeError("required EventBus observer must be callable")
        if self._required_observer is not None:
            raise RuntimeError("required EventBus observer is already retained")
        self._required_observer_name = name
        self._required_observer = observer

    def release_required_observer(self, name: str) -> None:
        """Release only the exact named persistence observer owner."""

        if name != self._required_observer_name or self._required_observer is None:
            raise RuntimeError("required EventBus observer owner does not match")
        self._required_observer_name = None
        self._required_observer = None

    async def subscribe(self, name: str, *, maxsize: int = 1000) -> asyncio.Queue[EngineEvent]:
        """Register a named subscriber and return its dedicated queue."""
        if name in self._subscribers:
            logger.warning("EventBus: duplicate subscribe '%s' — replacing existing queue", name)
        q: asyncio.Queue[EngineEvent] = asyncio.Queue(maxsize=maxsize)
        self._subscribers[name] = q
        return q

    def unsubscribe(self, name: str) -> None:
        """Remove a subscriber by name. No-op if not registered."""
        self._subscribers.pop(name, None)

    async def publish(self, event: EngineEvent) -> None:
        """Persist through the retained observer, then fan out best-effort.

        A persistence FAILURE propagates BEFORE the fan-out, so no subscriber ever
        observes a transition that has no durable incident behind it. The previous
        form captured every exception, fanned out anyway, and re-raised at the end --
        which meant operator notifications could report an alarm that storage had
        already refused.

        CANCELLATION IS TREATED DIFFERENTLY, ON PURPOSE. The observer shields its
        durable write, so a cancellation reported after that write means the incident
        HAS settled. Aborting the fan-out there would withhold an alarm that storage
        accepted -- a worse failure than the one this change prevents. So the
        cancellation is held, the fan-out runs, and it is raised afterwards.
        """

        if type(event) is not EngineEvent:
            raise TypeError("EventBus publication must be an exact EngineEvent")
        cancelled_after_persisting: asyncio.CancelledError | None = None
        required_observer = self._required_observer
        if required_observer is not None:
            try:
                await required_observer(copy.deepcopy(event))
            except asyncio.CancelledError as exc:
                # Cancellation is NOT a persistence failure, and the difference decides
                # whether the operator hears about this alarm. The observer shields its
                # durable write, so when it reports cancellation the incident has already
                # settled -- there IS a durable record behind this transition. Withholding
                # the fan-out would then hide an alarm that storage accepted. Fan out, then
                # let the cancellation propagate to the caller.
                cancelled_after_persisting = exc
        for name, q in list(self._subscribers.items()):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "EventBus: subscriber '%s' queue full, dropping %s",
                    name,
                    event.event_type,
                )
        if cancelled_after_persisting is not None:
            raise cancelled_after_persisting

    async def publish_required(
        self,
        event: EngineEvent,
        *,
        event_identity: str | None = None,
        payload_digest: str | None = None,
    ) -> RequiredEventPublicationReceipt:
        """Atomically admit one identity-bound event to every retained queue.

        Unlike :meth:`publish`, this path never drops, partially fans out, or
        reports success without at least one target. Queue capacity and event
        detachment are preflighted for the complete subscriber cut before the
        first enqueue. Consumer processing is intentionally outside this
        admission receipt's authority boundary.
        """

        if type(event) is not EngineEvent:
            raise TypeError("required publication event must be exactly EngineEvent")
        if event.event_type == "alarm_fired":
            raise ValueError("alarm_fired must use persistence-aware publish")
        if (event_identity is None) is not (payload_digest is None):
            raise ValueError("required publication identity and payload digest must be supplied together")
        if event_identity is not None:
            if (
                type(event_identity) is not str
                or not 1 <= len(event_identity) <= 128
                or any(not (char.isascii() and (char.isalnum() or char in "_.-")) for char in event_identity)
            ):
                raise ValueError("required publication event identity is invalid")
            if (
                type(payload_digest) is not str
                or len(payload_digest) != 64
                or any(char not in "0123456789abcdef" for char in payload_digest)
            ):
                raise ValueError("required publication payload digest is invalid")
            if (
                event.payload.get("cycle_identity") != event_identity
                or event.payload.get("source_digest") != payload_digest
            ):
                raise ValueError("required publication event identity does not match its payload")

        try:
            canonical_event = json.dumps(
                {
                    "event_type": event.event_type,
                    "timestamp": event.timestamp.isoformat(),
                    "payload": event.payload,
                    "experiment_id": event.experiment_id,
                },
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (AttributeError, TypeError, ValueError):
            raise ValueError("required publication event is not canonically serializable") from None
        event_digest = hashlib.sha256(canonical_event).hexdigest()

        subscriber_names = tuple(sorted(self._subscribers))
        if not subscriber_names:
            raise RuntimeError("required EventBus publication has no retained subscriber")
        queues = tuple(self._subscribers[name] for name in subscriber_names)
        full_subscribers = tuple(name for name, queue in zip(subscriber_names, queues, strict=True) if queue.full())
        if full_subscribers:
            raise RuntimeError("required event publication capacity unavailable: " + ", ".join(full_subscribers))

        # Pre-create every detached envelope. A hostile/malformed nested
        # payload therefore fails before any queue observes a partial cut.
        detached_events = tuple(copy.deepcopy(event) for _queue in queues)
        for queue, detached in zip(queues, detached_events, strict=True):
            queue.put_nowait(detached)

        return RequiredEventPublicationReceipt(
            event_digest=event_digest,
            admitted_subscribers=len(subscriber_names),
            subscriber_names=subscriber_names,
            event_identity=event_identity,
            payload_digest=payload_digest,
            _authority=self._required_publication_authority,
        )

    def validates_required_publication(
        self,
        receipt: object,
        *,
        event_identity: str,
        payload_digest: str,
    ) -> bool:
        """Validate a receipt issued by this exact EventBus instance."""

        return (
            type(receipt) is RequiredEventPublicationReceipt
            and receipt._authority is self._required_publication_authority
            and receipt.event_identity == event_identity
            and receipt.payload_digest == payload_digest
            and len(receipt.event_digest) == 64
            and all(char in "0123456789abcdef" for char in receipt.event_digest)
            and receipt.admitted_subscribers > 0
            and receipt.admitted_subscribers == len(receipt.subscriber_names)
            and receipt.subscriber_names == tuple(sorted(set(receipt.subscriber_names)))
        )

    @property
    def subscriber_count(self) -> int:
        """Number of currently registered subscribers."""
        return len(self._subscribers)
