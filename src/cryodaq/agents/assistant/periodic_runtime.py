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
import math
import re
import secrets
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

from cryodaq.agents.assistant.periodic_png import (
    AlarmQueryResult,
    LiveSourceCut,
    PeriodicPngCoordinator,
    PeriodicSourceUnavailable,
)
from cryodaq.agents.assistant.periodic_telegram import PeriodicTelegramClient
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


class PeriodicLiveDiscontinuity(PeriodicSourceUnavailable):
    """Fixed failure raised after the private live generation loses authority."""

    def __init__(self) -> None:
        super().__init__("periodic live stream discontinuity")


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
        self._ready_active = False
        self._ready_nonce: str | None = None
        self._retired_ready_nonces: set[str] = set()
        self._ready_marker: asyncio.Future[LiveSourceCut] | None = None
        self._running = False
        self._stopping = False
        self._invalid = False
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

    def _invalidate(self) -> None:
        if self._invalid or self._stopping:
            return
        self._invalid = True
        self._running = False
        self._provisional.clear()
        self._provisional_bytes = 0
        current = asyncio.current_task()
        for task in (self._receive_task, self._monitor_task):
            if task is not None and task is not current and not task.done():
                task.cancel()
        discontinuity = PeriodicLiveDiscontinuity()
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
            raise ValueError("invalid transport")
        session = _text(value["session_id"], maximum=32, allow_empty=False)
        if value["schema"] != PERIODIC_STREAM_SCHEMA or _TOKEN.fullmatch(session) is None:
            raise ValueError("invalid transport")
        authoritative = value["persistence_authoritative"]
        if type(authoritative) is not bool:
            raise ValueError("invalid transport")
        return _Transport(session, _exact_int(value["sequence"], minimum=1), authoritative)

    @classmethod
    def _reading(cls, raw: bytes) -> tuple[_Transport, Reading]:
        if not raw or len(raw) > MAX_DATA_MSG_SIZE:
            raise ValueError("invalid reading frame")
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
        expected = {"ts", "iid", "ch", "v", "u", "st", "raw", "meta", "transport"}
        if not isinstance(data, dict) or set(data) != expected:
            raise ValueError("invalid reading shape")
        transport = cls._transport(data["transport"])
        timestamp = _finite_number(data["ts"])
        instrument = _text(data["iid"], maximum=256)
        channel = _text(data["ch"], maximum=256, allow_empty=False)
        unit = _text(data["u"], maximum=128)
        status = ChannelStatus(_text(data["st"], maximum=32, allow_empty=False))
        value = data["v"]
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise ValueError("invalid reading value")
        raw_value = data["raw"]
        if raw_value is not None and (isinstance(raw_value, bool) or not isinstance(raw_value, (int, float))):
            raise ValueError("invalid raw reading value")
        metadata = data["meta"]
        if not isinstance(metadata, dict) or len(metadata) > 256:
            raise ValueError("invalid reading metadata")
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
            raise ValueError("invalid event shape")
        transport = cls._transport(event["transport"])
        if transport.persistence_authoritative:
            raise ValueError("event cannot claim persistence authority")
        _text(event["event_type"], maximum=128, allow_empty=False)
        _finite_number(event["ts"])
        if not isinstance(event["payload"], Mapping) or len(event["payload"]) > 256:
            raise ValueError("invalid event payload")
        if event["experiment_id"] is not None:
            _text(event["experiment_id"], maximum=256, allow_empty=False)
        public = dict(event)
        public.pop("transport")
        return transport, public

    @staticmethod
    def _call(callback: Callable[[Any], object], value: object) -> None:
        result = callback(value)
        if inspect.isawaitable(result):
            close = getattr(result, "close", None)
            if callable(close):
                close()
            raise ValueError("periodic live callbacks must be synchronous")

    def _validate_next(self, session: str, sequence: int, *, provisional: bool) -> None:
        expected_session = (
            self._provisional_cut.session_id if provisional and self._provisional_cut else self._session_id
        )
        previous = self._provisional_last if provisional else self._last_sequence
        if expected_session != session or previous is None or sequence != previous + 1:
            raise ValueError("stream discontinuity")

    async def _semantic_frame(self, topic: bytes, raw: bytes) -> tuple[_Transport, _ProvisionalFrame]:
        if topic == DEFAULT_TOPIC:
            transport, reading = self._reading(raw)
            if transport.persistence_authoritative:
                return transport, _ProvisionalFrame(transport.sequence, "reading", reading, len(raw))
            return transport, _ProvisionalFrame(transport.sequence, "filtered", None, len(raw))
        if topic == EVENTS_TOPIC:
            transport, event = self._event(raw)
            return transport, _ProvisionalFrame(transport.sequence, "event", event, len(raw))
        raise ValueError("unknown participating topic")

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
            raise ValueError("invalid barrier marker shape")
        nonce, cut = _parse_cut({"ok": True, **payload}, generation=self._generation)
        marker = self._ready_marker
        if self._ready_active and self._session_id is None and nonce in self._retired_ready_nonces:
            # A successful REP may precede a startup marker that was still in
            # the SUB pipe when its bounded attempt expired.  It cannot grant
            # readiness for a later nonce, and everything before the later
            # matching marker remains outside the accepted stream prefix.
            return
        if not self._ready_active or nonce != self._ready_nonce or marker is None or marker.done():
            raise ValueError("orphan barrier")
        if self._session_id is None:
            if self._provisional_cut is not None:
                raise ValueError("duplicate startup barrier")
            self._provisional_cut = cut
            self._provisional_last = cut.sequence
        else:
            self._validate_next(cut.session_id, cut.sequence, provisional=False)
            if cut.reading_drop_count != self._drop_baseline or cut.publish_failure_count != self._failure_baseline:
                raise ValueError("publisher counters changed")
            self._last_sequence = cut.sequence
        marker.set_result(cut)

    async def _handle_frame(self, parts: list[bytes]) -> None:
        if len(parts) != 2 or parts[0] not in {DEFAULT_TOPIC, EVENTS_TOPIC, PERIODIC_BARRIER_TOPIC}:
            raise ValueError("invalid multipart frame")
        async with self._state_lock:
            if self._invalid or not self._running:
                raise PeriodicLiveDiscontinuity()
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
                    raise ValueError("provisional frame overflow")
                if self._provisional_bytes + frame.encoded_bytes > self._max_provisional_bytes:
                    raise ValueError("provisional byte overflow")
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
        except BaseException:
            self._invalidate()
        else:
            if not self._stopping:
                self._invalidate()

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
                    self._invalidate()
                    return
                if event in _MONITOR_FAILURE_EVENTS:
                    self._invalidate()
                    return
        except asyncio.CancelledError:
            raise
        except BaseException:
            self._invalidate()
        else:
            if not self._stopping:
                self._invalidate()

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
            # One all-topic subscription is one propagation unit: receiving
            # the exact nonce barrier therefore also proves that readings and
            # events use the same active SUB pipe.  Connect-before-subscribe is
            # required by the supported macOS/Python/pyzmq combination.
            self._socket.setsockopt(zmq.SUBSCRIBE, b"")
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
            raise PeriodicLiveDiscontinuity()
        if self._ready_active:
            raise RuntimeError("periodic barrier is already in flight")
        self._ready_active = True
        self._ready_task = asyncio.current_task()
        try:
            marker_cut: LiveSourceCut | None = None
            connected = self._connected
            if connected is None:
                raise PeriodicLiveDiscontinuity()
            for attempt in range(_READY_MAX_ATTEMPTS):
                nonce = secrets.token_hex(16)
                if nonce in self._retired_ready_nonces:
                    raise PeriodicLiveDiscontinuity()
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
                            raise PeriodicLiveDiscontinuity()
                        query_result = await self._query.barrier(nonce)
                        if not query_result.ok:
                            if (
                                attempt + 1 < _READY_MAX_ATTEMPTS
                                and query_result.error_code == "transport_unavailable"
                                and await self._retire_startup_attempt(nonce, marker, require_no_evidence=True)
                            ):
                                continue
                            raise PeriodicLiveDiscontinuity()
                        if query_result.nonce != nonce or query_result.cut is None:
                            raise PeriodicLiveDiscontinuity()
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
                        raise PeriodicLiveDiscontinuity() from None
                    continue
                if not self._same_evidence(query_result.cut, marker_cut):
                    raise PeriodicLiveDiscontinuity()
                break
            if marker_cut is None:
                raise PeriodicLiveDiscontinuity()
            async with self._state_lock:
                if self._session_id is None:
                    if self._provisional_cut != marker_cut:
                        raise PeriodicLiveDiscontinuity()
                    self._session_id = marker_cut.session_id
                    self._drop_baseline = marker_cut.reading_drop_count
                    self._failure_baseline = marker_cut.publish_failure_count
                    self._last_sequence = marker_cut.sequence
                    for frame in self._provisional:
                        if frame.sequence != self._last_sequence + 1:
                            raise PeriodicLiveDiscontinuity()
                        self._dispatch(frame)
                        self._last_sequence = frame.sequence
                    self._provisional.clear()
                    self._provisional_bytes = 0
                    self._provisional_cut = None
                    self._provisional_last = None
            return marker_cut
        except asyncio.CancelledError:
            self._invalidate()
            raise
        except BaseException as exc:
            self._invalidate()
            if isinstance(exc, PeriodicLiveDiscontinuity):
                raise
            raise PeriodicLiveDiscontinuity() from None
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
            raise PeriodicLiveDiscontinuity()

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
            marker.set_exception(PeriodicLiveDiscontinuity())
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


def make_periodic_coordinator_factory(
    *,
    data_dir: Path,
    archive_dir: Path,
) -> PeriodicCoordinatorFactory:
    """Return the resource-free H3 graph seam consumed by Slice F.

    No socket, HTTP session, or child is opened by this function or by the
    returned factory.  Coordinator start remains the sole lifecycle boundary.
    """

    resolved_data = Path(data_dir)
    resolved_archive = Path(archive_dir)

    def build(config: PeriodicPngConfig) -> PeriodicPngCoordinator:
        if not isinstance(config, PeriodicPngConfig) or not config.enabled:
            raise ValueError("runnable periodic config is required")
        query = PeriodicEngineQuery(DEFAULT_CMD_ADDR)
        alarm_query = _PeriodicAlarmAdapter(query)
        live = SequencedPeriodicLiveSources(query, DEFAULT_PUB_ADDR)
        archive = ArchiveReader(resolved_data, resolved_archive)
        runner = ReportProcessRunner(resolved_data, timeout_s=config.render_timeout_s)
        telegram = PeriodicTelegramClient(config)
        return PeriodicPngCoordinator(
            data_dir=resolved_data,
            config=config,
            live_sources=live,
            alarm_query=alarm_query,
            archive_query=archive.query_reading_rows_bounded,
            runner=runner,
            telegram=telegram,
        )

    return build


__all__ = [
    "BarrierQueryResult",
    "PeriodicEngineQuery",
    "PeriodicLiveDiscontinuity",
    "SequencedPeriodicLiveSources",
    "make_periodic_coordinator_factory",
]
