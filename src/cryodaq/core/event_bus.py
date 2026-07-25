"""Lightweight pub/sub event bus for engine events (not Reading data)."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
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

    Subscribers receive a dedicated asyncio.Queue. Publish is non-blocking:
    a full queue logs a warning and drops the event rather than blocking
    the engine event loop.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, asyncio.Queue[EngineEvent]] = {}
        self._required_publication_authority = object()

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
        """Fan out event to all subscriber queues (non-blocking; drops on full)."""
        for name, q in list(self._subscribers.items()):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "EventBus: subscriber '%s' queue full, dropping %s",
                    name,
                    event.event_type,
                )

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
