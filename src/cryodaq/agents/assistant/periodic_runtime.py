"""Private production adapters for the H3 periodic-PNG authority.

The shared GUI/LLM ZMQ clients intentionally do not participate here.  This
module owns a separate, closed transport contract whose constructors allocate
no sockets, contexts, HTTP sessions, or child processes.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import ipaddress
import itertools
import json
import logging
import math
import re
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import msgpack
import zmq
import zmq.asyncio
from zmq.utils.monitor import parse_monitor_message

from cryodaq.agents.assistant.periodic_delivery import (
    PeriodicDelivery,
    PeriodicDeliveryContext,
    PeriodicDeliveryOutcome,
    PeriodicDeliveryReceipt,
    PeriodicDeliveryResult,
)
from cryodaq.agents.assistant.periodic_png import (
    AlarmQueryResult,
    LiveSourceCut,
    PeriodicPngCoordinator,
    PeriodicSourceUnavailable,
)
from cryodaq.agents.assistant.periodic_telegram import (
    PeriodicTelegramClient,
    TelegramOutcome,
)
from cryodaq.core.zmq_bridge import (
    DEFAULT_CMD_ADDR,
    DEFAULT_PUB_ADDR,
    DEFAULT_TOPIC,
    EVENTS_TOPIC,
    MAX_DATA_MSG_SIZE,
    PERIODIC_BARRIER_SCHEMA,
    PERIODIC_BARRIER_TOPIC,
    PERIODIC_MAX_SEQUENCE,
    PERIODIC_QUERY_MAX_BYTES,
    PERIODIC_QUERY_SCHEMA,
    PERIODIC_STREAM_SCHEMA,
    PROTOCOL_VERSION,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.periodic_config import PeriodicPngConfig
from cryodaq.periodic_state import periodic_telegram_destination_fingerprint
from cryodaq.report_process import ReportProcessRunner
from cryodaq.storage.archive_reader import ArchiveReader

_TOKEN = re.compile(r"[0-9a-f]{32}")
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_QUERY_REQUEST_BYTES = 1024
_MAX_SNAPSHOT_RESPONSE_BYTES = 60 * 1024
_MAX_JSON_DEPTH = 8
_MAX_JSON_MAPPINGS = 512
_MAX_JSON_LISTS = 256
_MAX_JSON_ITEMS = 16_384
_DEFAULT_READY_TIMEOUT_S = 2.0
_READY_MAX_ATTEMPTS = 3
_DEFAULT_PROVISIONAL_FRAMES = 512
_DEFAULT_PROVISIONAL_BYTES = 4 * 1024 * 1024
_GENERATION_COUNTER = itertools.count(1)
_MONITOR_FAILURE_EVENTS = frozenset(
    {
        zmq.EVENT_DISCONNECTED,
        zmq.EVENT_CONNECT_RETRIED,
        zmq.EVENT_CLOSED,
        zmq.EVENT_MONITOR_STOPPED,
    }
)


_log = logging.getLogger(__name__)

# The topics this source participates in.
#
# ZMQ SUBSCRIBE MATCHES BY PREFIX, NOT BY EQUALITY, and that is why admission cannot be
# a refusal. Subscribing to b"readings" also delivers a future b"readings.detail", and
# no list this consumer keeps can prevent that -- the publisher owns its own topics.
# So `_handle_frame` IGNORES AND COUNTS a frame on a topic outside this tuple, and
# refuses only what is genuinely malformed. A refusal invalidates the whole generation,
# and a topic somebody else added must never be able to kill this source. Measured on
# 2026-08-20: an ordinary `operator.snapshot` did exactly that.
#
# Equality between this tuple and the SUBSCRIBE list is still required, because a topic
# subscribed but not admitted is a silent drop, and one admitted but not subscribed is a
# frame that never arrives.
_PARTICIPATING_TOPICS: tuple[bytes, ...] = (DEFAULT_TOPIC, EVENTS_TOPIC, PERIODIC_BARRIER_TOPIC)

# THE READING CONTRACT, SPLIT INTO WHAT MUST BE THERE AND WHAT MAY BE.
#
# This used to be one set compared with `!=`, which refuses a reading that carries an
# extra field just as hard as one that is missing a required field. `zmq_bridge._pack_reading`
# attaches `desc`, the channel-descriptor envelope, whenever it has one -- so an ordinary
# reading with a descriptor was refused, and the refusal INVALIDATES THE WHOLE GENERATION.
# Measured on Ubuntu 22.04 on 2026-08-20, after the topic fix removed the previous
# dominant cause, `a reading had an unexpected shape` became the most frequent reason the
# periodic source lost authority.
#
# The check stays fail-closed on an unknown key. What changed is that a field the
# publisher documents as optional is no longer treated as an unknown one.
_READING_REQUIRED_KEYS: frozenset[str] = frozenset({"ts", "iid", "ch", "v", "u", "st", "raw", "meta", "transport"})
_READING_OPTIONAL_KEYS: frozenset[str] = frozenset({"desc"})


# One line per distinct reason per minute. A run that flaps once a second for a week
# must leave a diagnosis, not a log nobody can open; and the FIRST occurrence of each
# reason is always written, because that is the one that says what happened.
_DISCONTINUITY_LOG_INTERVAL_S = 60.0
_last_discontinuity_log: dict[str, float] = {}


# A CLOSED VOCABULARY, not the exception text. The receive loop catches whatever the
# frame handler raised, and putting that message into the reason would put frame content
# -- values, identifiers, addresses -- into a log line and into a durable health record.
# The category says which CLASS of thing went wrong, which is what a diagnosis needs.
_INVALIDATION_CATEGORIES: dict[type[BaseException], str] = {
    ValueError: "a frame was rejected as malformed, out of sequence, or counter-inconsistent",
    TypeError: "a frame carried a value of the wrong type",
    KeyError: "a frame was missing a required field",
    OSError: "the subscriber transport failed",
}


class _FrameRejected(ValueError):
    """A frame this source refused, carrying the CATEGORY of the refusal.

    WHY THE CATEGORY IS CHOSEN HERE. The receive loop catches whatever the frame handler
    raised, and a class-only mapping gave one sentence to six different conditions -- a
    malformed wire payload, a sequence gap, a changed publisher counter, a provisional
    overflow, an orphan barrier, and a callback that returned an awaitable. Those
    implicate different components and need different remedies. The rejection site is the
    only place that knows which one it was, so it says so.

    It stays a `ValueError` so every existing handler keeps working, and the detail
    message is unchanged -- the category is the addition, and it is the part that reaches
    the log and the durable record. The detail never does, because a frame's own text
    carries values, channel names and addresses.
    """

    def __init__(self, category: str, detail: str) -> None:
        super().__init__(detail)
        self.category = category


def _invalidation_category(error: BaseException | None) -> str:
    """Name the class of failure that took authority, never its text."""

    if error is None:
        return "the live generation was invalidated"
    if isinstance(error, _FrameRejected):
        # Chosen at the rejection site, which is the only place that knew.
        return error.category
    for kind, category in _INVALIDATION_CATEGORIES.items():
        if isinstance(error, kind):
            return category
    return f"the receive path failed with {type(error).__name__}"


def _say_discontinuity(reason: str) -> None:
    """Write the reason at most once a minute, per reason."""

    now = time.monotonic()
    previous = _last_discontinuity_log.get(reason)
    if previous is not None and now - previous < _DISCONTINUITY_LOG_INTERVAL_S:
        return
    _last_discontinuity_log[reason] = now
    _log.warning("Periodic live source lost authority: because=%s", reason)


class PeriodicLiveDiscontinuity(PeriodicSourceUnavailable):
    """Fixed failure raised after the private live generation loses authority.

    WHY IT CARRIES A REASON. Sixteen places construct this, and every one of them
    produced the same sentence. The supervisor turns it into the health code
    `periodic_engine_unavailable` and stops there, so a run that never allocates a
    periodic slot -- and therefore never seals a receipt, and therefore refuses the
    assistant fault -- leaves no evidence of WHICH condition fired. That is the
    difference between a week-long run that can be diagnosed and one that cannot.

    The reason is recorded on construction rather than at each raise site, so a new
    site cannot be added silently: the default reads `unstated`, and a test refuses it.
    """

    def __init__(self, reason: str = "unstated") -> None:
        super().__init__(f"periodic live stream discontinuity (because={reason})")
        self.reason = reason
        _say_discontinuity(reason)


@dataclass(frozen=True, slots=True)
class BarrierQueryResult:
    """Closed result of one engine barrier request."""

    ok: bool
    nonce: str | None
    cut: LiveSourceCut | None
    error_code: str | None

    def __post_init__(self) -> None:
        if type(self.ok) is not bool:
            raise TypeError("ok must be a boolean")
        if self.ok:
            if (
                not isinstance(self.nonce, str)
                or _TOKEN.fullmatch(self.nonce) is None
                or not isinstance(self.cut, LiveSourceCut)
                or self.error_code is not None
            ):
                raise ValueError("successful barrier result is inconsistent")
        elif (
            self.nonce is not None
            or self.cut is not None
            or self.error_code
            not in {
                "transport_unavailable",
                "response_invalid",
            }
        ):
            raise ValueError("failed barrier result is inconsistent")


class _BarrierAuthority(Protocol):
    async def barrier(self, nonce: str) -> BarrierQueryResult: ...


@dataclass(frozen=True, slots=True)
class _Transport:
    session_id: str
    sequence: int
    persistence_authoritative: bool


@dataclass(frozen=True, slots=True)
class _ProvisionalFrame:
    sequence: int
    kind: Literal["reading", "event", "filtered"]
    value: Reading | Mapping[str, object] | None
    encoded_bytes: int


def _reject_nonfinite(token: str) -> float:
    raise ValueError("non-finite JSON value")


def _parse_finite_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    return value


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise ValueError("invalid JSON object key")
        result[key] = value
    return result


def _reject_msgpack_pairs(pairs: list[tuple[object, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise ValueError("invalid msgpack object key")
        result[key] = value
    return result


def _bounded_json(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > PERIODIC_QUERY_MAX_BYTES:
        raise ValueError("invalid response bytes")
    parsed = json.loads(
        raw.decode("utf-8", errors="strict"),
        parse_constant=_reject_nonfinite,
        parse_float=_parse_finite_float,
        object_pairs_hook=_reject_duplicate_pairs,
    )
    mappings = 0
    lists = 0
    items = 0

    def visit(value: object, depth: int) -> None:
        nonlocal mappings, lists, items
        if depth > _MAX_JSON_DEPTH:
            raise ValueError("response nesting is excessive")
        if isinstance(value, Mapping):
            mappings += 1
            items += len(value)
            if mappings > _MAX_JSON_MAPPINGS:
                raise ValueError("too many response mappings")
            for key, item in value.items():
                if not isinstance(key, str) or len(key.encode("utf-8")) > 256:
                    raise ValueError("invalid response key")
                visit(item, depth + 1)
        elif isinstance(value, list):
            lists += 1
            items += len(value)
            if lists > _MAX_JSON_LISTS:
                raise ValueError("too many response lists")
            for item in value:
                visit(item, depth + 1)
        elif isinstance(value, str):
            if len(value.encode("utf-8")) > PERIODIC_QUERY_MAX_BYTES:
                raise ValueError("oversized response string")
        elif value is not None and not isinstance(value, (bool, int, float)):
            raise ValueError("invalid response value")
        if items > _MAX_JSON_ITEMS:
            raise ValueError("too many response items")

    visit(parsed, 0)
    if not isinstance(parsed, dict):
        raise ValueError("response must be a mapping")
    return parsed


def _consume_future_exception(future: asyncio.Future[object]) -> None:
    if not future.cancelled():
        future.exception()


def _exact_int(value: object, *, minimum: int = 0, maximum: int = PERIODIC_MAX_SEQUENCE) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("invalid integer")
    return value


def _finite_number(value: object, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError("invalid number")
    return result


def _text(value: object, *, maximum: int, allow_empty: bool = True) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ValueError("invalid text")
    if len(value.encode("utf-8", errors="strict")) > maximum:
        raise ValueError("oversized text")
    return value


def _validate_loopback_endpoint(address: str) -> str:
    if not isinstance(address, str):
        raise TypeError("engine endpoint must be text")
    parsed = urlsplit(address)
    if parsed.scheme != "tcp" or parsed.username is not None or parsed.password is not None:
        raise ValueError("periodic engine endpoint must be loopback TCP")
    try:
        host = parsed.hostname
        port = parsed.port
        ip = ipaddress.ip_address(host) if host is not None else None
    except ValueError as exc:
        raise ValueError("periodic engine endpoint must be loopback TCP") from exc
    if ip is None or not ip.is_loopback or port is None or not 1 <= port <= 65535:
        raise ValueError("periodic engine endpoint must be loopback TCP")
    if parsed.path or parsed.query or parsed.fragment:
        raise ValueError("periodic engine endpoint must be loopback TCP")
    return address


def _validate_alarm_active(active: object) -> Mapping[str, object]:
    if not isinstance(active, Mapping) or len(active) > 128:
        raise ValueError("invalid active alarms")
    previous_id: str | None = None
    for alarm_id, alarm in active.items():
        identifier = _text(alarm_id, maximum=256, allow_empty=False)
        if any(ord(character) < 32 or ord(character) == 127 for character in identifier):
            raise ValueError("invalid alarm id")
        if previous_id is not None and identifier <= previous_id:
            raise ValueError("alarm identifiers are not canonical")
        previous_id = identifier
        if not isinstance(alarm, Mapping) or set(alarm) != {
            "level",
            "triggered_at",
            "channels",
            "acknowledged",
            "acknowledged_at",
        }:
            raise ValueError("invalid active alarm")
        if alarm["level"] not in {"INFO", "WARNING", "CRITICAL"}:
            raise ValueError("invalid alarm level")
        _finite_number(alarm["triggered_at"])
        channels = alarm["channels"]
        if not isinstance(channels, list) or len(channels) > 64:
            raise ValueError("invalid alarm channels")
        previous_channel: str | None = None
        for raw_channel in channels:
            channel = _text(raw_channel, maximum=256, allow_empty=False)
            if any(ord(character) < 32 or ord(character) == 127 for character in channel):
                raise ValueError("invalid alarm channel")
            if previous_channel is not None and channel <= previous_channel:
                raise ValueError("alarm channels are not canonical")
            previous_channel = channel
        acknowledged = alarm["acknowledged"]
        if type(acknowledged) is not bool:
            raise ValueError("invalid alarm acknowledgement")
        if acknowledged:
            _finite_number(alarm["acknowledged_at"])
        elif alarm["acknowledged_at"] is not None:
            raise ValueError("invalid alarm acknowledgement time")
    return active


def _parse_cut(payload: Mapping[str, object], *, generation: int) -> tuple[str, LiveSourceCut]:
    expected = {
        "ok",
        "proto",
        "schema",
        "nonce",
        "session_id",
        "sequence",
        "published_at",
        "reading_drop_count",
        "publish_failure_count",
        "alarm_state_revision",
        "alarm_state_token",
    }
    if set(payload) != expected or payload.get("ok") is not True:
        raise ValueError("invalid barrier response shape")
    if type(payload["proto"]) is not int or payload["proto"] != PROTOCOL_VERSION:
        raise ValueError("invalid protocol version")
    if payload["schema"] != PERIODIC_BARRIER_SCHEMA:
        raise ValueError("invalid barrier schema")
    nonce = _text(payload["nonce"], maximum=32, allow_empty=False)
    session = _text(payload["session_id"], maximum=32, allow_empty=False)
    token = _text(payload["alarm_state_token"], maximum=71, allow_empty=False)
    if _TOKEN.fullmatch(nonce) is None or _TOKEN.fullmatch(session) is None or _HASH.fullmatch(token) is None:
        raise ValueError("invalid barrier token")
    return nonce, LiveSourceCut(
        session_id=session,
        generation=generation,
        sequence=_exact_int(payload["sequence"], minimum=1),
        published_at=_finite_number(payload["published_at"]),
        reading_drop_count=_exact_int(payload["reading_drop_count"]),
        publish_failure_count=_exact_int(payload["publish_failure_count"]),
        alarm_state_revision=_exact_int(payload["alarm_state_revision"]),
        alarm_state_token=token,
    )


class PeriodicEngineQuery:
    """Closed, one-request-per-socket client for H3 engine authority."""

    def __init__(
        self,
        address: str = DEFAULT_CMD_ADDR,
        *,
        timeout_s: float = 1.8,
        _context_factory: Callable[[], zmq.asyncio.Context] = zmq.asyncio.Context,
    ) -> None:
        self._address = _validate_loopback_endpoint(address)
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)):
            raise TypeError("timeout_s must be numeric")
        self._timeout_s = float(timeout_s)
        if not math.isfinite(self._timeout_s) or not 0.05 <= self._timeout_s < 2.0:
            raise ValueError("timeout_s must be finite and below the engine envelope")
        if not callable(_context_factory):
            raise TypeError("context factory is required")
        self._context_factory = _context_factory
        self._closed = False
        self._operation_lock = asyncio.Lock()

    async def _request(self, payload: Mapping[str, object]) -> bytes:
        if self._closed:
            raise RuntimeError("periodic engine query is closed")
        request = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        if not request or len(request) >= _MAX_QUERY_REQUEST_BYTES:
            raise ValueError("periodic request is oversized")
        async with self._operation_lock:
            if self._closed:
                raise RuntimeError("periodic engine query is closed")
            context: zmq.asyncio.Context | None = None
            socket: zmq.asyncio.Socket | None = None
            response: bytes | None = None
            primary_error: BaseException | None = None
            try:
                context = self._context_factory()
                socket = context.socket(zmq.REQ)
                socket.setsockopt(zmq.LINGER, 0)
                socket.setsockopt(zmq.MAXMSGSIZE, PERIODIC_QUERY_MAX_BYTES)
                timeout_ms = max(1, int(self._timeout_s * 1000))
                socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
                socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
                socket.connect(self._address)
                async with asyncio.timeout(self._timeout_s):
                    await socket.send(request)
                    response = await socket.recv()
                if type(response) is not bytes:
                    raise ValueError("invalid response frame")
            except BaseException as exc:
                primary_error = exc
            cleanup_error: BaseException | None = None
            try:
                if socket is not None:
                    socket.close(linger=0)
            except BaseException as exc:
                cleanup_error = exc
            try:
                if context is not None:
                    context.term()
            except BaseException as exc:
                cleanup_error = cleanup_error or exc
            if primary_error is not None:
                if cleanup_error is not None:
                    raise primary_error from cleanup_error
                raise primary_error
            if cleanup_error is not None:
                raise cleanup_error
            assert response is not None
            return response

    async def barrier(self, nonce: str) -> BarrierQueryResult:
        if not isinstance(nonce, str) or _TOKEN.fullmatch(nonce) is None:
            return BarrierQueryResult(False, None, None, "response_invalid")
        try:
            raw = await self._request(
                {
                    "cmd": "periodic_subscription_barrier",
                    "schema": PERIODIC_QUERY_SCHEMA,
                    "nonce": nonce,
                }
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return BarrierQueryResult(False, None, None, "transport_unavailable")
        try:
            response = _bounded_json(raw)
            if response.get("ok") is False:
                if (
                    set(response) != {"ok", "proto", "schema", "error_code"}
                    or type(response.get("proto")) is not int
                    or response["proto"] != PROTOCOL_VERSION
                    or response.get("schema") != PERIODIC_BARRIER_SCHEMA
                    or response.get("error_code")
                    not in {
                        "barrier_invalid",
                        "barrier_timeout",
                        "barrier_unavailable",
                        "barrier_unstable",
                    }
                ):
                    raise ValueError("invalid barrier failure")
                return BarrierQueryResult(False, None, None, "transport_unavailable")
            observed_nonce, cut = _parse_cut(response, generation=1)
            if observed_nonce != nonce:
                raise ValueError("nonce mismatch")
            return BarrierQueryResult(True, observed_nonce, cut, None)
        except (TypeError, ValueError, UnicodeError, OverflowError):
            return BarrierQueryResult(False, None, None, "response_invalid")

    async def alarm_snapshot(self) -> AlarmQueryResult:
        try:
            raw = await self._request({"cmd": "periodic_alarm_snapshot", "schema": PERIODIC_QUERY_SCHEMA})
        except asyncio.CancelledError:
            raise
        except Exception:
            return AlarmQueryResult(False, None, None, None, "transport_unavailable")
        try:
            if len(raw) > _MAX_SNAPSHOT_RESPONSE_BYTES:
                raise ValueError("snapshot response is oversized")
            response = _bounded_json(raw)
            if type(response.get("proto")) is not int or response["proto"] != PROTOCOL_VERSION:
                raise ValueError("invalid protocol version")
            if response.get("schema") != PERIODIC_QUERY_SCHEMA or type(response.get("ok")) is not bool:
                raise ValueError("invalid snapshot envelope")
            if response["ok"] is False:
                if set(response) != {"ok", "proto", "schema", "error_code"}:
                    raise ValueError("invalid failure response")
                if response["error_code"] != "snapshot_unavailable":
                    raise ValueError("unknown failure response")
                return AlarmQueryResult(False, None, None, None, "snapshot_unavailable")
            if set(response) != {
                "ok",
                "proto",
                "schema",
                "state_revision",
                "state_token",
                "active",
            }:
                raise ValueError("invalid snapshot response")
            revision = _exact_int(response["state_revision"])
            token = _text(response["state_token"], maximum=71, allow_empty=False)
            active = _validate_alarm_active(response["active"])
            canonical = json.dumps(
                active,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
            expected_token = "sha256:" + hashlib.sha256(canonical).hexdigest()
            if _HASH.fullmatch(token) is None or not secrets.compare_digest(token, expected_token):
                raise ValueError("invalid snapshot authority")
            payload: Mapping[str, object] = {"ok": True, "active": active}
            return AlarmQueryResult(True, payload, token, revision, None)
        except (TypeError, ValueError, UnicodeError, OverflowError):
            return AlarmQueryResult(False, None, None, None, "response_invalid")

    async def close(self) -> None:
        async with self._operation_lock:
            self._closed = True


class _PeriodicAlarmAdapter:
    def __init__(self, query: PeriodicEngineQuery) -> None:
        self._query = query

    async def snapshot(self) -> AlarmQueryResult:
        return await self._query.alarm_snapshot()

    async def close(self) -> None:
        await self._query.close()


class SequencedPeriodicLiveSources:
    """Private SUB authority with one globally sequenced transport generation."""

    def __init__(
        self,
        query: _BarrierAuthority,
        address: str = DEFAULT_PUB_ADDR,
        *,
        ready_timeout_s: float = _DEFAULT_READY_TIMEOUT_S,
        max_provisional_frames: int = _DEFAULT_PROVISIONAL_FRAMES,
        max_provisional_bytes: int = _DEFAULT_PROVISIONAL_BYTES,
        _context_factory: Callable[[], zmq.asyncio.Context] = zmq.asyncio.Context,
    ) -> None:
        self._address = _validate_loopback_endpoint(address)
        if query is None or not callable(getattr(query, "barrier", None)):
            raise TypeError("barrier authority is required")
        self._query = query
        if isinstance(ready_timeout_s, bool) or not isinstance(ready_timeout_s, (int, float)):
            raise TypeError("ready_timeout_s must be numeric")
        self._ready_timeout_s = float(ready_timeout_s)
        if not math.isfinite(self._ready_timeout_s) or not 0.05 <= self._ready_timeout_s <= 10.0:
            raise ValueError("ready timeout is invalid")
        if type(max_provisional_frames) is not int or not 1 <= max_provisional_frames <= 4096:
            raise ValueError("provisional frame bound is invalid")
        if type(max_provisional_bytes) is not int or not 1024 <= max_provisional_bytes <= 64 * 1024 * 1024:
            raise ValueError("provisional byte bound is invalid")
        self._max_provisional_frames = max_provisional_frames
        self._max_provisional_bytes = max_provisional_bytes
        self._context_factory = _context_factory
        self._context: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._monitor: zmq.asyncio.Socket | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._ready_task: asyncio.Task[Any] | None = None
        self._on_reading: Callable[[Any], object] | None = None
        self._on_event: Callable[[Mapping[str, object]], object] | None = None
        self._failure: asyncio.Future[None] | None = None
        self._connected: asyncio.Event | None = None
        self._state_lock = asyncio.Lock()
        # Frames delivered by prefix matching on a topic this source does not
        # participate in. Counted rather than refused; see _handle_frame.
        self._foreign_topic_frames = 0
        self._ready_active = False
        self._ready_nonce: str | None = None
        self._retired_ready_nonces: set[str] = set()
        self._ready_marker: asyncio.Future[LiveSourceCut] | None = None
        self._running = False
        self._stopping = False
        self._invalid = False
        # Set the moment authority is lost, and read by `wait()`. A default that says
        # nothing would let a reader mistake "no reason recorded" for "no reason".
        self._invalidation_reason = "the live generation was invalidated"
        self._closed = False
        self._generation = next(_GENERATION_COUNTER)
        self._session_id: str | None = None
        self._last_sequence: int | None = None
        self._drop_baseline: int | None = None
        self._failure_baseline: int | None = None
        self._provisional_cut: LiveSourceCut | None = None
        self._provisional_last: int | None = None
        self._provisional: list[_ProvisionalFrame] = []
        self._provisional_bytes = 0

    def _invalidate(self, reason: str = "the live generation was invalidated") -> None:
        """Take the generation down and REMEMBER WHY, so a later reader is not guessing."""

        if self._invalid or self._stopping:
            return
        self._invalid = True
        self._invalidation_reason = reason
        self._running = False
        self._provisional.clear()
        self._provisional_bytes = 0
        current = asyncio.current_task()
        for task in (self._receive_task, self._monitor_task):
            if task is not None and task is not current and not task.done():
                task.cancel()
        discontinuity = PeriodicLiveDiscontinuity(reason)
        marker = self._ready_marker
        if marker is not None and not marker.done():
            marker.set_exception(discontinuity)
        failure = self._failure
        if failure is not None and not failure.done():
            failure.set_result(None)
        connected = self._connected
        if connected is not None:
            connected.set()

    @staticmethod
    def _transport(value: object) -> _Transport:
        if not isinstance(value, Mapping) or set(value) != {
            "schema",
            "session_id",
            "sequence",
            "persistence_authoritative",
        }:
            raise _FrameRejected("the frame carried an invalid transport envelope", "invalid transport")
        session = _text(value["session_id"], maximum=32, allow_empty=False)
        if value["schema"] != PERIODIC_STREAM_SCHEMA or _TOKEN.fullmatch(session) is None:
            raise _FrameRejected("the frame carried an invalid transport envelope", "invalid transport")
        authoritative = value["persistence_authoritative"]
        if type(authoritative) is not bool:
            raise _FrameRejected("the frame carried an invalid transport envelope", "invalid transport")
        try:
            sequence = _exact_int(value["sequence"], minimum=1)
        except ValueError as exc:
            raise _FrameRejected("the transport sequence was invalid", "invalid transport sequence") from exc
        return _Transport(session, sequence, authoritative)

    @classmethod
    def _reading(cls, raw: bytes) -> tuple[_Transport, Reading]:
        if not raw or len(raw) > MAX_DATA_MSG_SIZE:
            raise _FrameRejected("a reading frame did not parse", "invalid reading frame")
        data = msgpack.unpackb(
            raw,
            raw=False,
            strict_map_key=True,
            object_pairs_hook=_reject_msgpack_pairs,
            max_str_len=MAX_DATA_MSG_SIZE,
            max_bin_len=MAX_DATA_MSG_SIZE,
            max_array_len=1024,
            max_map_len=1024,
        )
        if not isinstance(data, dict):
            raise _FrameRejected(
                "a reading payload was not a mapping",
                "invalid reading shape: the reading is not a mapping",
            )
        keys = set(data)
        missing = sorted(_READING_REQUIRED_KEYS - keys)
        unexpected = sorted(keys - _READING_REQUIRED_KEYS - _READING_OPTIONAL_KEYS)
        if missing or unexpected:
            # The KEY NAMES, never a value. The required set is a fixed vocabulary, and an
            # unexpected key is reported by COUNT rather than by name, because an unknown
            # name is not a fixed vocabulary and could carry content from the wire.
            raise _FrameRejected(
                "a reading was missing required fields or carried unknown fields",
                f"invalid reading shape: missing={missing} unexpected_key_count={len(unexpected)}",
            )
        transport = cls._transport(data["transport"])
        timestamp = _finite_number(data["ts"])
        instrument = _text(data["iid"], maximum=256)
        channel = _text(data["ch"], maximum=256, allow_empty=False)
        unit = _text(data["u"], maximum=128)
        status = ChannelStatus(_text(data["st"], maximum=32, allow_empty=False))
        value = data["v"]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise _FrameRejected("a reading value was not usable", "invalid reading value")
        raw_value = data["raw"]
        if raw_value is not None and (isinstance(raw_value, bool) or not isinstance(raw_value, (int, float))):
            raise _FrameRejected("a raw reading value was not usable", "invalid raw reading value")
        metadata = data["meta"]
        if not isinstance(metadata, dict) or len(metadata) > 256:
            raise _FrameRejected("a reading's metadata was not usable", "invalid reading metadata")
        reading = Reading(
            timestamp=datetime.fromtimestamp(timestamp, tz=UTC),
            instrument_id=instrument,
            channel=channel,
            value=value,
            unit=unit,
            status=status,
            raw=raw_value,
            metadata=metadata,
        )
        return transport, reading

    @classmethod
    def _event(cls, raw: bytes) -> tuple[_Transport, Mapping[str, object]]:
        event = _bounded_json(raw)
        if set(event) != {"event_type", "ts", "payload", "experiment_id", "transport"}:
            raise _FrameRejected("an event had an unexpected shape", "invalid event shape")
        transport = cls._transport(event["transport"])
        if transport.persistence_authoritative:
            raise _FrameRejected(
                "an event claimed persistence authority it does not have", "event cannot claim persistence authority"
            )
        _text(event["event_type"], maximum=128, allow_empty=False)
        _finite_number(event["ts"])
        if not isinstance(event["payload"], Mapping) or len(event["payload"]) > 256:
            raise _FrameRejected("an event payload did not parse", "invalid event payload")
        if event["experiment_id"] is not None:
            _text(event["experiment_id"], maximum=256, allow_empty=False)
        public = dict(event)
        public.pop("transport")
        return transport, public

    @staticmethod
    def _call(callback: Callable[[Any], object], value: object) -> None:
        try:
            result = callback(value)
        except Exception as exc:
            raise _FrameRejected("a periodic live callback failed", "periodic callback failed") from exc
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise _FrameRejected(
                "a periodic callback returned an awaitable instead of running synchronously",
                "periodic live callbacks must be synchronous",
            )

    def _validate_next(self, session: str, sequence: int, *, provisional: bool) -> None:
        expected_session = (
            self._provisional_cut.session_id if provisional and self._provisional_cut else self._session_id
        )
        previous = self._provisional_last if provisional else self._last_sequence
        if expected_session != session or previous is None or sequence != previous + 1:
            raise _FrameRejected("the global stream sequence has a gap", "stream discontinuity")

    async def _semantic_frame(self, topic: bytes, raw: bytes) -> tuple[_Transport, _ProvisionalFrame]:
        if topic == DEFAULT_TOPIC:
            try:
                transport, reading = self._reading(raw)
            except _FrameRejected:
                raise
            except (TypeError, ValueError) as exc:
                raise _FrameRejected("a reading frame did not validate", "invalid reading fields") from exc
            if transport.persistence_authoritative:
                return transport, _ProvisionalFrame(transport.sequence, "reading", reading, len(raw))
            return transport, _ProvisionalFrame(transport.sequence, "filtered", None, len(raw))
        if topic == EVENTS_TOPIC:
            try:
                transport, event = self._event(raw)
            except _FrameRejected:
                raise
            except (TypeError, ValueError) as exc:
                raise _FrameRejected("an event frame did not validate", "invalid event fields") from exc
            return transport, _ProvisionalFrame(transport.sequence, "event", event, len(raw))
        raise _FrameRejected(
            "a frame arrived on a topic this source does not participate in", "unknown participating topic"
        )

    def _dispatch(self, frame: _ProvisionalFrame) -> None:
        if frame.kind == "reading":
            assert self._on_reading is not None
            self._call(self._on_reading, frame.value)
        elif frame.kind == "event":
            assert self._on_event is not None
            self._call(self._on_event, frame.value)

    async def _handle_barrier(self, raw: bytes) -> None:
        payload = _bounded_json(raw)
        marker_keys = {
            "proto",
            "schema",
            "nonce",
            "session_id",
            "sequence",
            "published_at",
            "reading_drop_count",
            "publish_failure_count",
            "alarm_state_revision",
            "alarm_state_token",
        }
        if set(payload) != marker_keys:
            raise _FrameRejected("a barrier marker had an unexpected shape", "invalid barrier marker shape")
        nonce, cut = _parse_cut({"ok": True, **payload}, generation=self._generation)
        marker = self._ready_marker
        if self._ready_active and self._session_id is None and nonce in self._retired_ready_nonces:
            # A successful REP may precede a startup marker that was still in
            # the SUB pipe when its bounded attempt expired.  It cannot grant
            # readiness for a later nonce, and everything before the later
            # matching marker remains outside the accepted stream prefix.
            return
        if not self._ready_active or nonce != self._ready_nonce or marker is None or marker.done():
            raise _FrameRejected("a barrier answer arrived that no request expected", "orphan barrier")
        if self._session_id is None:
            if self._provisional_cut is not None:
                raise _FrameRejected("a second startup barrier arrived for one request", "duplicate startup barrier")
            self._provisional_cut = cut
            self._provisional_last = cut.sequence
        else:
            self._validate_next(cut.session_id, cut.sequence, provisional=False)
            if cut.reading_drop_count != self._drop_baseline or cut.publish_failure_count != self._failure_baseline:
                raise _FrameRejected("the publisher's drop or failure counters changed", "publisher counters changed")
            self._last_sequence = cut.sequence
        marker.set_result(cut)

    async def _handle_frame(self, parts: list[bytes]) -> None:
        if not parts:
            raise _FrameRejected("the multipart frame was empty", "invalid multipart frame")
        if parts[0] not in _PARTICIPATING_TOPICS:
            # NOT OURS, AND NOT A VIOLATION. A SUBSCRIBE is a byte PREFIX, so subscribing
            # to b"readings" also delivers anything the publisher later names
            # b"readings.<something>". Refusing that would let one new publisher topic
            # invalidate this source's whole generation -- the exact failure this class was
            # just corrected for. Count it and move on.
            self._foreign_topic_frames += 1
            return
        # THE FRAME COUNT IS A RULE ABOUT OUR OWN TOPICS, so it is applied after the topic
        # is classified and never before. Checking it first would make a foreign topic
        # fatal whenever it used one or three parts instead of two -- the non-fatal
        # handling above would then have protected only foreign topics that happened to
        # share our envelope shape, which is no protection at all.
        if len(parts) != 2:
            raise _FrameRejected("a known topic's multipart frame was not exactly two parts", "invalid multipart frame")
        async with self._state_lock:
            if self._invalid or not self._running:
                raise PeriodicLiveDiscontinuity("a frame arrived after the source stopped")
            if parts[0] == PERIODIC_BARRIER_TOPIC:
                await self._handle_barrier(parts[1])
                return
            transport, frame = await self._semantic_frame(parts[0], parts[1])
            if self._session_id is not None:
                self._validate_next(transport.session_id, transport.sequence, provisional=False)
                self._dispatch(frame)
                self._last_sequence = transport.sequence
            elif self._provisional_cut is not None:
                self._validate_next(transport.session_id, transport.sequence, provisional=True)
                if len(self._provisional) >= self._max_provisional_frames:
                    raise _FrameRejected("the provisional buffer overflowed", "provisional frame overflow")
                if self._provisional_bytes + frame.encoded_bytes > self._max_provisional_bytes:
                    raise _FrameRejected("the provisional buffer overflowed", "provisional byte overflow")
                self._provisional.append(frame)
                self._provisional_bytes += frame.encoded_bytes
                self._provisional_last = transport.sequence
            # Frames preceding the first nonce marker are deliberately ignored.

    async def _receive_loop(self) -> None:
        try:
            while self._running:
                socket = self._socket
                if socket is None:
                    raise RuntimeError("subscriber unavailable")
                parts = await socket.recv_multipart()
                await self._handle_frame(parts)
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            self._invalidate(f"the receive loop stopped: {_invalidation_category(error)}")
        else:
            if not self._stopping:
                self._invalidate("the receive loop ended while the source was still running")

    async def _monitor_loop(self) -> None:
        try:
            while self._running:
                monitor = self._monitor
                if monitor is None:
                    raise RuntimeError("monitor unavailable")
                message = parse_monitor_message(await monitor.recv_multipart())
                event = message.get("event")
                if event == zmq.EVENT_CONNECTED:
                    connected = self._connected
                    if connected is not None:
                        connected.set()
                    continue
                if event == zmq.EVENT_CONNECT_RETRIED:
                    connected = self._connected
                    if connected is not None and not connected.is_set():
                        # A SUB may start before the engine binds.  Retrying is
                        # expected until the first connection; after that,
                        # DISCONNECTED remains terminal authority loss.
                        continue
                    self._invalidate("the subscriber retried its connection after it had connected once")
                    return
                if event in _MONITOR_FAILURE_EVENTS:
                    self._invalidate(f"the subscriber socket reported event {event!r}")
                    return
        except asyncio.CancelledError:
            raise
        except BaseException as error:
            self._invalidate(f"the socket monitor stopped: the monitor path failed with {type(error).__name__}")
        else:
            if not self._stopping:
                self._invalidate("the socket monitor ended while the source was still running")

    async def start(
        self,
        on_reading: Callable[[Any], object],
        on_event: Callable[[Mapping[str, object]], object],
    ) -> None:
        if self._closed:
            raise RuntimeError("periodic live source is closed")
        if self._running or self._receive_task is not None or self._context is not None:
            raise RuntimeError("periodic live source is already started")
        if not callable(on_reading) or not callable(on_event):
            raise TypeError("live callbacks are required")
        self._on_reading = on_reading
        self._on_event = on_event
        self._failure = asyncio.get_running_loop().create_future()
        self._failure.add_done_callback(_consume_future_exception)
        self._connected = asyncio.Event()
        try:
            self._context = self._context_factory()
            self._socket = self._context.socket(zmq.SUB)
            self._socket.setsockopt(zmq.LINGER, 0)
            self._socket.setsockopt(zmq.MAXMSGSIZE, MAX_DATA_MSG_SIZE)
            self._socket.setsockopt(zmq.RECONNECT_IVL, 500)
            self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)
            self._monitor = self._socket.get_monitor_socket(
                events=(
                    zmq.EVENT_CONNECTED
                    | zmq.EVENT_DISCONNECTED
                    | zmq.EVENT_CONNECT_RETRIED
                    | zmq.EVENT_CLOSED
                    | zmq.EVENT_MONITOR_STOPPED
                )
            )
            self._monitor.setsockopt(zmq.LINGER, 0)
            self._socket.connect(self._address)
            # SUBSCRIBE TO WHAT THIS SOURCE PARTICIPATES IN, AND TO NOTHING ELSE.
            #
            # This used to subscribe to every topic with `b""`, and the reasoning was
            # sound when it was written: one subscription is one propagation unit, so
            # receiving the exact nonce barrier also proved that readings and events use
            # the same active SUB pipe. That argument still holds with three
            # subscriptions -- one socket, one connection, one pipe -- and the all-topic
            # form acquired a defect the day a FOURTH topic appeared on the publisher.
            #
            # `zmq_bridge.publish_operator_snapshot` sends `operator.snapshot` on the
            # sole PUB socket. An all-topic subscriber receives it, `_handle_frame`
            # refuses it as a frame that is not two parts on a participating topic, and
            # that refusal INVALIDATES THE WHOLE GENERATION. Measured on Ubuntu 22.04 on
            # 2026-08-20, it was the most frequent reason the periodic source lost
            # authority during a run -- which is why no periodic slot was ever allocated
            # and no receipt could be sealed.
            #
            # Connect-before-subscribe is required by the supported macOS/Python/pyzmq
            # combination, so the order below is deliberate.
            for topic in _PARTICIPATING_TOPICS:
                self._socket.setsockopt(zmq.SUBSCRIBE, topic)
            self._running = True
            self._receive_task = asyncio.create_task(self._receive_loop(), name="periodic_live_receive")
            self._monitor_task = asyncio.create_task(self._monitor_loop(), name="periodic_live_monitor")
        except BaseException as primary:
            try:
                await self.stop()
            except BaseException as cleanup_error:
                raise primary from cleanup_error
            raise

    @staticmethod
    def _same_evidence(left: LiveSourceCut, right: LiveSourceCut) -> bool:
        return (
            left.session_id == right.session_id
            and left.sequence == right.sequence
            and left.published_at == right.published_at
            and left.reading_drop_count == right.reading_drop_count
            and left.publish_failure_count == right.publish_failure_count
            and left.alarm_state_revision == right.alarm_state_revision
            and left.alarm_state_token == right.alarm_state_token
        )

    async def _retire_startup_attempt(
        self,
        nonce: str,
        marker: asyncio.Future[LiveSourceCut],
        *,
        require_no_evidence: bool,
    ) -> bool:
        async with self._state_lock:
            if (
                self._session_id is not None
                or self._invalid
                or not self._running
                or (require_no_evidence and (marker.done() or self._provisional_cut is not None))
            ):
                return False
            self._retired_ready_nonces.add(nonce)
            self._provisional.clear()
            self._provisional_bytes = 0
            self._provisional_cut = None
            self._provisional_last = None
            self._ready_nonce = None
            self._ready_marker = None
        if not marker.done():
            marker.cancel()
        return True

    async def ready(self) -> LiveSourceCut:
        if not self._running or self._invalid or self._stopping:
            raise PeriodicLiveDiscontinuity("ready was asked of a source that is not running")
        if self._ready_active:
            raise RuntimeError("periodic barrier is already in flight")
        self._ready_active = True
        self._ready_task = asyncio.current_task()
        try:
            marker_cut: LiveSourceCut | None = None
            connected = self._connected
            if connected is None:
                raise PeriodicLiveDiscontinuity("there is no connection event to wait on")
            for attempt in range(_READY_MAX_ATTEMPTS):
                nonce = secrets.token_hex(16)
                if nonce in self._retired_ready_nonces:
                    raise PeriodicLiveDiscontinuity("the generated barrier nonce was already retired")
                marker = asyncio.get_running_loop().create_future()
                marker.add_done_callback(_consume_future_exception)
                self._ready_nonce = nonce
                self._ready_marker = marker
                query_result: BarrierQueryResult | None = None
                try:
                    async with asyncio.timeout(self._ready_timeout_s):
                        if attempt == 0:
                            await connected.wait()
                        if self._invalid or not self._running:
                            raise PeriodicLiveDiscontinuity("the source stopped while waiting to connect")
                        query_result = await self._query.barrier(nonce)
                        if not query_result.ok:
                            error_code = query_result.error_code
                            if (
                                attempt + 1 < _READY_MAX_ATTEMPTS
                                and type(error_code) is str
                                and error_code == "transport_unavailable"
                                and await self._retire_startup_attempt(nonce, marker, require_no_evidence=True)
                            ):
                                continue
                            if type(error_code) is not str:
                                failure_reason = "the engine barrier query returned an unsupported failure code"
                            elif error_code == "transport_unavailable":
                                failure_reason = "the engine barrier transport was unavailable"
                            elif error_code == "response_invalid":
                                failure_reason = "the engine barrier response was invalid"
                            else:
                                failure_reason = "the engine barrier query returned an unsupported failure code"
                            raise PeriodicLiveDiscontinuity(failure_reason)
                        if query_result.nonce != nonce or query_result.cut is None:
                            raise PeriodicLiveDiscontinuity(
                                "the barrier answer named a different nonce or carried no cut"
                            )
                        marker_cut = await marker
                except TimeoutError:
                    can_retry = (
                        attempt + 1 < _READY_MAX_ATTEMPTS
                        and query_result is not None
                        and query_result.ok
                        and query_result.nonce == nonce
                        and query_result.cut is not None
                        and self._session_id is None
                        and not self._invalid
                        and self._running
                    )
                    if not can_retry or not await self._retire_startup_attempt(
                        nonce, marker, require_no_evidence=False
                    ):
                        raise PeriodicLiveDiscontinuity(
                            "the engine barrier timed out and could not be retried"
                        ) from None
                    continue
                if not self._same_evidence(query_result.cut, marker_cut):
                    raise PeriodicLiveDiscontinuity(
                        "the barrier answer and the published marker describe different evidence"
                    )
                break
            if marker_cut is None:
                raise PeriodicLiveDiscontinuity("the barrier produced no cut")
            async with self._state_lock:
                if self._session_id is None:
                    if self._provisional_cut != marker_cut:
                        raise PeriodicLiveDiscontinuity(
                            "the provisional cut does not match the cut the barrier established"
                        )
                    self._session_id = marker_cut.session_id
                    self._drop_baseline = marker_cut.reading_drop_count
                    self._failure_baseline = marker_cut.publish_failure_count
                    self._last_sequence = marker_cut.sequence
                    for frame in self._provisional:
                        if frame.sequence != self._last_sequence + 1:
                            raise PeriodicLiveDiscontinuity("a held frame is out of sequence")
                        self._dispatch(frame)
                        self._last_sequence = frame.sequence
                    self._provisional.clear()
                    self._provisional_bytes = 0
                    self._provisional_cut = None
                    self._provisional_last = None
            return marker_cut
        except asyncio.CancelledError:
            self._invalidate("the barrier was cancelled")
            raise
        except BaseException as exc:
            # KEEP THE NAME THE BARRIER ALREADY CHOSE. Replacing it with the class name
            # threw away a reason that had been worked out -- and the live watcher, which
            # `_invalidate` releases, then reported the generic replacement to whoever was
            # waiting. The immediate caller saw the detail; the later observer did not.
            reason = (
                exc.reason
                if isinstance(exc, PeriodicLiveDiscontinuity)
                else exc.category
                if isinstance(exc, _FrameRejected)
                else f"the barrier failed with {type(exc).__name__}"
            )
            self._invalidate(reason)
            if isinstance(exc, PeriodicLiveDiscontinuity):
                raise
            raise PeriodicLiveDiscontinuity(reason) from None
        finally:
            self._ready_active = False
            self._ready_task = None
            self._ready_nonce = None
            self._retired_ready_nonces.clear()
            self._ready_marker = None

    def complete_since(self, cut: LiveSourceCut) -> bool:
        return bool(
            isinstance(cut, LiveSourceCut)
            and self._running
            and not self._invalid
            and cut.generation == self._generation
            and cut.session_id == self._session_id
            and self._last_sequence is not None
            and self._last_sequence >= cut.sequence
            and cut.reading_drop_count == self._drop_baseline
            and cut.publish_failure_count == self._failure_baseline
        )

    async def wait(self) -> None:
        failure = self._failure
        if failure is None:
            raise RuntimeError("periodic live source is not started")
        await asyncio.shield(failure)
        if self._invalid:
            # The reason the generation went down, not the fact that it is down. The
            # second is what a caller already knows.
            raise PeriodicLiveDiscontinuity(self._invalidation_reason)

    async def _stop_impl(self) -> None:
        self._stopping = True
        self._running = False
        first_error: BaseException | None = None
        ready_task = self._ready_task
        if ready_task is not None and ready_task is not asyncio.current_task():
            ready_task.cancel()
            await asyncio.gather(ready_task, return_exceptions=True)
        tasks = tuple(task for task in (self._receive_task, self._monitor_task) if task is not None)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._receive_task = None
        self._monitor_task = None
        try:
            if self._socket is not None:
                self._socket.disable_monitor()
        except BaseException as exc:
            first_error = exc
        try:
            if self._monitor is not None:
                self._monitor.close(linger=0)
        except BaseException as exc:
            first_error = first_error or exc
        finally:
            self._monitor = None
        try:
            if self._socket is not None:
                self._socket.close(linger=0)
        except BaseException as exc:
            first_error = first_error or exc
        finally:
            self._socket = None
        try:
            if self._context is not None:
                self._context.term()
        except BaseException as exc:
            first_error = first_error or exc
        finally:
            self._context = None
        marker = self._ready_marker
        if marker is not None and not marker.done():
            marker.set_exception(PeriodicLiveDiscontinuity("the source stopped while a barrier was in flight"))
        failure = self._failure
        if failure is not None and not failure.done():
            failure.set_result(None)
        self._ready_active = False
        self._ready_task = None
        self._ready_nonce = None
        self._retired_ready_nonces.clear()
        self._ready_marker = None
        self._session_id = None
        self._last_sequence = None
        self._drop_baseline = None
        self._failure_baseline = None
        self._on_reading = None
        self._on_event = None
        self._connected = None
        self._provisional.clear()
        self._provisional_bytes = 0
        self._provisional_cut = None
        self._provisional_last = None
        self._closed = True
        self._stopping = False
        if first_error is not None:
            raise first_error

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop_impl(), name="periodic_live_cleanup")
        cleanup_task = self._stop_task
        cancelled: asyncio.CancelledError | None = None
        current = asyncio.current_task()
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError as exc:
                cancelled = exc
                if current is not None:
                    current.uncancel()
        cleanup_error = cleanup_task.exception()
        if cancelled is not None:
            if cleanup_error is not None:
                raise cancelled from cleanup_error
            raise cancelled
        if cleanup_error is not None:
            raise cleanup_error


type PeriodicCoordinatorFactory = Callable[[PeriodicPngConfig], PeriodicPngCoordinator]
type PeriodicDeliveryFactory = Callable[[], PeriodicDelivery]


class _DeliveryLeaseSlot:
    """Bind a custom session lease only after the coordinator graph is complete."""

    def __init__(self) -> None:
        self._target: PeriodicDelivery | None = None

    def bind(self, target: PeriodicDelivery) -> None:
        if self._target is not None:
            raise RuntimeError("periodic delivery lease is already bound")
        if target is None:
            raise TypeError("periodic delivery factory returned no session lease")
        # The factory's PeriodicDelivery return type is its closed contract.
        # Do not perform a fallible probe after session acquisition: binding
        # this fresh slot is the final graph-construction operation.
        self._target = target

    async def send_artifact(
        self,
        photo: bytes,
        caption: str,
        context: PeriodicDeliveryContext,
    ) -> PeriodicDeliveryResult:
        target = self._target
        if target is None:
            raise RuntimeError("periodic delivery lease is not bound")
        return await target.send_artifact(photo, caption, context)

    async def close(self) -> None:
        target = self._target
        if target is not None:
            await target.close()


class _TelegramPeriodicDelivery:
    """Map the accepted Telegram client to the provider-neutral delivery seam."""

    def __init__(self, config: PeriodicPngConfig) -> None:
        self._client = PeriodicTelegramClient(config)
        self._close_task: asyncio.Task[None] | None = None

    async def send_artifact(
        self,
        photo: bytes,
        caption: str,
        context: PeriodicDeliveryContext,
    ) -> PeriodicDeliveryResult:
        try:
            caption_bytes = caption.encode("utf-8", errors="strict")
        except (AttributeError, UnicodeEncodeError):
            caption_bytes = b""
        if (
            not isinstance(context, PeriodicDeliveryContext)
            or type(photo) is not bytes
            or (
                len(photo) != context.artifact_size
                or "sha256:" + hashlib.sha256(photo).hexdigest() != context.artifact_sha256
                or len(caption_bytes) != context.caption_size
                or "sha256:" + hashlib.sha256(caption_bytes).hexdigest() != context.caption_sha256
            )
        ):
            return PeriodicDeliveryResult(
                PeriodicDeliveryOutcome.NOT_SENT,
                None,
                False,
                None,
                "delivery_context_mismatch",
                "periodic payload contradicts its fenced delivery context",
            )
        result = await self._client.send_photo(photo, caption)
        outcome = PeriodicDeliveryOutcome(result.outcome.value)
        receipt = (
            PeriodicDeliveryReceipt("telegram", str(result.message_id), None)
            if result.outcome is TelegramOutcome.ACCEPTED
            else None
        )
        retryable = (
            result.outcome is TelegramOutcome.REJECTED and result.error_code == "telegram_retryable_rejection"
        ) or (
            result.outcome is TelegramOutcome.NOT_SENT
            and result.error_code in {"telegram_connect_failed", "client_busy"}
        )
        return PeriodicDeliveryResult(
            outcome,
            receipt,
            retryable,
            result.retry_after_s,
            result.error_code,
            result.error_text,
        )

    async def close(self) -> None:
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._client.close())
        await asyncio.shield(self._close_task)


def make_periodic_coordinator_factory(
    *,
    data_dir: Path,
    archive_dir: Path,
    _delivery_factory: PeriodicDeliveryFactory | None = None,
    _destination_fingerprint: str | None = None,
    _delivery_kind: str | None = None,
) -> PeriodicCoordinatorFactory:
    """Return the resource-free H3 graph seam consumed by Slice F.

    No socket, HTTP session, or child is opened by this function or by the
    returned factory.  Coordinator start remains the sole lifecycle boundary.
    """

    resolved_data = Path(data_dir)
    resolved_archive = Path(archive_dir)
    local_parts = (_delivery_factory, _destination_fingerprint, _delivery_kind)
    if any(part is not None for part in local_parts) and not all(part is not None for part in local_parts):
        raise ValueError("local delivery factory, destination fingerprint, and kind are mutually required")
    if _delivery_factory is not None:
        if type(_destination_fingerprint) is not str or _HASH.fullmatch(_destination_fingerprint) is None:
            raise ValueError("local delivery destination fingerprint is invalid")
        if type(_delivery_kind) is not str or _delivery_kind != "soak_local":
            raise ValueError("custom periodic delivery kind must be soak_local")

    def build(config: PeriodicPngConfig) -> PeriodicPngCoordinator:
        if not isinstance(config, PeriodicPngConfig) or not config.enabled:
            raise ValueError("runnable periodic config is required")
        query = PeriodicEngineQuery(DEFAULT_CMD_ADDR)
        alarm_query = _PeriodicAlarmAdapter(query)
        live = SequencedPeriodicLiveSources(query, DEFAULT_PUB_ADDR)
        archive = ArchiveReader(resolved_data, resolved_archive)
        runner = ReportProcessRunner(resolved_data, timeout_s=config.render_timeout_s)
        delivery: PeriodicDelivery
        slot: _DeliveryLeaseSlot | None = None
        if _delivery_factory is None:
            delivery = _TelegramPeriodicDelivery(config)
        else:
            slot = _DeliveryLeaseSlot()
            delivery = slot
        coordinator = PeriodicPngCoordinator(
            data_dir=resolved_data,
            config=config,
            live_sources=live,
            alarm_query=alarm_query,
            archive_query=archive.query_reading_rows_bounded,
            runner=runner,
            delivery=delivery,
            destination_fingerprint=(
                periodic_telegram_destination_fingerprint(config.telegram_chat_id)
                if _destination_fingerprint is None
                else _destination_fingerprint
            ),
            expected_delivery_kind="telegram" if _delivery_kind is None else _delivery_kind,
        )
        if slot is not None:
            # This is deliberately the final operation in graph construction:
            # a custom session lease cannot exist while a later constructor
            # can still fail and orphan it.
            slot.bind(_delivery_factory())
        return coordinator

    return build


__all__ = [
    "BarrierQueryResult",
    "PeriodicEngineQuery",
    "PeriodicLiveDiscontinuity",
    "SequencedPeriodicLiveSources",
    "make_periodic_coordinator_factory",
]
