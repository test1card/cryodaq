"""ZMQ-мост между engine и GUI.

ZMQPublisher — PUB-сокет в engine, сериализует Reading через msgpack.
ZMQSubscriber — SUB-сокет в GUI-процессе, десериализует и вызывает callback.
ZMQCommandServer — REP-сокет в engine, принимает JSON-команды от GUI.

Модель доверия (trust model)
----------------------------
The REP command socket accepts hardware-control commands **without
authentication**. This is BY-DESIGN, not an oversight — an accepted risk
under the single-operator-lab threat model (D7.2 accepted). CryoDAQ runs
on one operator PC; anyone with a shell on that host already owns the
instruments regardless of any REP-level auth, so a token here would add
ceremony without changing the trust boundary.

The accepted risk is bounded by these compensating controls:

- **Loopback-only bind, wildcard-bind rejected.** PUB/REP default to
  ``tcp://127.0.0.1:*`` (``DEFAULT_PUB_ADDR`` / ``DEFAULT_CMD_ADDR``), and
  ``_bind_with_retry`` calls ``_reject_wildcard_bind`` to raise ``ValueError``
  on any ``0.0.0.0`` / ``*`` / ``::`` address — the loopback bind is enforced,
  not merely the default. The kernel then refuses any off-host connection, so
  the unauthenticated surface is not reachable from the LAN. Specific-interface
  binds are still allowed for the SSH-tunnel-to-loopback deployment rule.
- **Socket-level size caps.** ``ZMQ_MAXMSGSIZE`` (``MAX_CMD_MSG_SIZE`` /
  ``MAX_DATA_MSG_SIZE``) makes libzmq drop an oversize frame before it is
  allocated in user space (audit C.2 / D6).
- **Bounded msgpack decode.** ``_unpack_reading`` re-checks the frame size
  and bounds every decoded element (``max_*_len``) so a crafted frame
  cannot drive a huge allocation.
- **Finite-clean command decode.** ``_decode_command`` rejects
  NaN/Infinity/overflow literals so a non-finite setpoint can never slip
  past the downstream limit guards.
- **SafetyManager is the sole on/off authority.** A REP command *requests*
  an action; it never overrides the safety FSM. SAFE_OFF stays the
  default and any run still requires continuous proof of health.
- **Tiered handler timeouts.** ``_timeout_for`` bounds wall-clock time per
  command via ``asyncio.wait_for``. Caveat: ``wait_for`` can only cancel at an
  ``await`` point — it cannot preempt a *synchronous* blocking handler before
  its first await, so a handler that blocks the event loop is not bounded by
  this timeout. The engine keeps its command handlers async/non-blocking for
  this reason; the timeout bounds cooperative handlers, not CPU/IO-blocking
  ones.
- **Defensive dispatch.** Malformed shapes (non-dict payloads) are rejected
  in ``ZMQCommandServer._run_handler``; unknown command names fall through
  to the engine handler's ``{"ok": False, "error": "unknown command: ..."}``
  reply — an unknown command is refused, never silently ignored or crashed.

**LAN exposure MUST go through an SSH tunnel** (forward 127.0.0.1 on the
remote to 127.0.0.1 on the engine host). Never bind these sockets to
``0.0.0.0`` — that would expose the unauthenticated hardware-control
surface to the network and void the trust model above.
"""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import math
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import version as _pkg_version
from typing import Any, Literal

import msgpack
import zmq
import zmq.asyncio

from cryodaq.channels.persistence import MAX_PERSISTED_ENVELOPE_BYTES
from cryodaq.core.broker import PERSISTENCE_AUTHORITATIVE_METADATA_KEY, PublishedReading
from cryodaq.core.command_authority import CommandClass, classify_engine_command
from cryodaq.core.descriptor_transport import (
    DescriptorQualifiedReading,
    qualify_reading_descriptor,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.operator_snapshot import OperatorSnapshot
from cryodaq.operator_snapshot_transport import encode_operator_snapshot_frames

logger = logging.getLogger(__name__)


def _reject_nonfinite(token: str) -> float:
    """``json.loads`` ``parse_constant`` hook — reject NaN/Infinity literals."""
    raise ValueError(f"non-finite JSON literal: {token}")


def _parse_finite_float(token: str) -> float:
    """``json.loads`` ``parse_float`` hook — reject overflowing floats.

    ``parse_constant`` only fires for the literal ``NaN``/``Infinity`` tokens;
    a perfectly valid JSON number like ``1e999`` parses to ``inf`` via the
    default float parser. Reject those here too so the boundary is fully
    finite-clean.
    """
    value = float(token)
    if not math.isfinite(value):
        raise ValueError(f"non-finite JSON number: {token}")
    return value


def _parse_bounded_int(token: str) -> int:
    """Reject integer literals too large for any CryoDAQ command field."""

    digits = token.removeprefix("-")
    if len(digits) > MAX_COMMAND_JSON_INTEGER_DIGITS:
        raise ValueError("JSON integer literal is too large")
    return int(token)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _validate_command_json(value: object) -> dict[str, Any]:
    """Validate root shape and bound aggregate JSON structure iteratively."""

    if type(value) is not dict:
        raise ValueError("command JSON root must be an object")

    item_count = 0
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        current, depth = pending.pop()
        item_count += 1
        if item_count > MAX_COMMAND_JSON_ITEMS:
            raise ValueError("command JSON contains too many items")
        if depth > MAX_COMMAND_JSON_DEPTH:
            raise ValueError("command JSON is nested too deeply")

        if type(current) is dict:
            for key, child in current.items():
                if type(key) is not str or len(key) > MAX_COMMAND_JSON_KEY_CHARS:
                    raise ValueError("command JSON key is invalid or too long")
                pending.append((child, depth + 1))
        elif type(current) is list:
            pending.extend((child, depth + 1) for child in current)
        elif type(current) is str:
            if len(current.encode("utf-8")) > MAX_CMD_MSG_SIZE:
                raise ValueError("command JSON string is too long")
        elif current is not None and type(current) not in {bool, int, float}:
            raise ValueError("command JSON contains an unsupported value")

    return value


def _decode_command(raw: bytes | str) -> dict[str, Any]:
    """Decode a command frame, rejecting non-finite numeric values.

    Python's ``json`` accepts the non-standard ``NaN``/``Infinity``/``-Infinity``
    tokens by default, and a large literal like ``1e999`` parses to ``inf``; a
    non-finite setpoint would then defeat the downstream ``> max`` / ``<= 0``
    limit guards (IEEE-754 makes those comparisons False) and reach the
    hardware. Rejecting both forms at this trust boundary keeps the whole
    command surface finite-clean. A rejected value surfaces as a ``ValueError``,
    handled identically to malformed JSON by the caller.
    """
    encoded_size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
    if encoded_size > MAX_CMD_MSG_SIZE:
        raise ValueError("command frame exceeds maximum size")
    try:
        decoded = json.loads(
            raw,
            parse_constant=_reject_nonfinite,
            parse_float=_parse_finite_float,
            parse_int=_parse_bounded_int,
            object_pairs_hook=_reject_duplicate_pairs,
        )
    except (RecursionError, OverflowError) as exc:
        raise ValueError("command JSON structure is invalid") from exc
    return _validate_command_json(decoded)


DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
DEFAULT_CMD_ADDR = "tcp://127.0.0.1:5556"
DEFAULT_TOPIC = b"readings"

# B1 (agents/ process extraction): additive second topic on the SAME PUB
# socket/port carrying EngineEvent notifications (alarm_fired,
# experiment_finalize, ...) for the new cryodaq-assistant process. Existing
# GUI subscribers only ``.subscribe(DEFAULT_TOPIC)`` (b"readings"), so this
# frame type is invisible to them — no protocol break, no port change.
EVENTS_TOPIC = b"events"

PERIODIC_STREAM_SCHEMA = "cryodaq.periodic.stream/v1"
PERIODIC_BARRIER_SCHEMA = "cryodaq.periodic.barrier/v1"
PERIODIC_QUERY_SCHEMA = "cryodaq.periodic.query/v1"
PERIODIC_BARRIER_TOPIC = b"periodic.barrier"
PERIODIC_QUERY_MAX_BYTES = 64 * 1024
PERIODIC_MAX_SEQUENCE = 2**63 - 1
_PERIODIC_BARRIER_TIMEOUT_S = 1.5
_PERIODIC_TOKEN_PREFIX = "sha256:"

# Version of the ZMQ REP command envelope and PUB frame encodings this module
# defines (topics, msgpack/JSON shapes — see docs/protocol.md). REST
# (web/server.py's GET /api/version) imports this same constant instead of
# declaring its own: the ZMQ and REST surfaces ship together from one
# package build, so one number is honest; a REST-only break would still
# warrant bumping this the same way a ZMQ-only break would.
PROTOCOL_VERSION = 2


def _bounded_action_label(action: object) -> str:
    """Return a bounded log label that cannot inject control characters."""

    if type(action) is not str or not action:
        return "<invalid>"
    return "".join(char if char.isascii() and (char.isalnum() or char in "._-") else "?" for char in action[:128])


def _post_dispatch_failure(
    action: object,
    *,
    error_code: str,
    error: str,
) -> dict[str, Any]:
    """Describe a failure after a handler may have changed state."""

    command_class = classify_engine_command(action)
    return {
        "ok": False,
        "error_code": error_code,
        "error": error,
        "delivery_state": "dispatched",
        "commit_state": ("not_applicable" if command_class is CommandClass.READ else "unknown"),
        "retry_safe": command_class is CommandClass.READ,
    }


def encode_command_reply(reply: dict[str, Any]) -> bytes:
    """Serialize the one authoritative REP envelope used on the wire."""
    if type(reply) is not dict:
        raise TypeError("command reply must be an exact dict")
    try:
        wire = json.dumps(
            {**reply, "proto": PROTOCOL_VERSION},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (RecursionError, OverflowError) as exc:
        raise ValueError("command reply structure is invalid") from exc
    if len(wire) > MAX_COMMAND_REPLY_SIZE:
        raise ValueError("command reply exceeds maximum size")
    return wire


class PeriodicCommandReply(dict[str, Any]):
    """Closed H3 reply whose exact validated wire bytes are reused by REP."""

    def __init__(self, reply: dict[str, Any], wire: bytes) -> None:
        super().__init__(reply)
        self.wire = wire


def encode_periodic_command_reply(reply: dict[str, Any]) -> PeriodicCommandReply:
    """Encode one compact, sorted, finite H3 reply exactly once."""
    envelope = {**reply, "proto": PROTOCOL_VERSION}
    wire = json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return PeriodicCommandReply(reply, wire)


try:
    _APP_VERSION = _pkg_version("cryodaq")
except Exception:
    _APP_VERSION = "dev"

_SERVER_LABELS = frozenset({"engine", "assistant"})

# Audit C.2 / D6: socket-level size caps on the unauthenticated
# loopback command/data path. libzmq (ZMQ_MAXMSGSIZE) drops an oversize
# frame before it is allocated in user space — this is the trust-boundary
# guard, not the post-recv len() check. Commands are small JSON; data
# frames are single msgpack Readings. Both caps are deliberately generous
# vs. real traffic so legitimate payloads are never clipped.
MAX_CMD_MSG_SIZE = 256 * 1024  # 256 KiB — commands are tiny JSON objects
MAX_DATA_MSG_SIZE = 2 * 1024 * 1024  # 2 MiB — one msgpack Reading, generous
MAX_COMMAND_REPLY_SIZE = 4 * 1024 * 1024
MAX_COMMAND_JSON_DEPTH = 16
MAX_COMMAND_JSON_ITEMS = 2048
MAX_COMMAND_JSON_KEY_CHARS = 256
MAX_COMMAND_JSON_INTEGER_DIGITS = 64

_SERIALIZATION_ERROR_WIRE = encode_command_reply(
    {
        "ok": False,
        "error_code": "command_reply_serialization_failed",
        "error": "Command reply could not be serialized; outcome may be unknown.",
        "delivery_state": "dispatched",
        "commit_state": "unknown",
        "retry_safe": False,
    }
)

# IV.3 Finding 7: per-command tiered handler timeout.
# A flat 2 s envelope was wrong for stateful transitions —
# experiment_finalize / abort / create and calibration curve
# import/export/fit routinely exceed 2 s (SQLite writes + DOCX/PDF
# report generation). When they timed out the outer REP reply path
# still fired (the original code already returned {ok: False}), but
# the operator saw a "handler timeout (2s)" error that was a lie:
# the operation usually completed a few seconds later. Fast status
# polls stay on the 2 s envelope; known-slow commands get 30 s.
HANDLER_TIMEOUT_FAST_S = 2.0
HANDLER_TIMEOUT_SLOW_S = 55.0  # H7: bumped from 30 — Ollama cold-start

_SLOW_COMMANDS: frozenset[str] = frozenset(
    {
        "experiment_finalize",
        "experiment_stop",
        "experiment_abort",
        "experiment_create",
        "experiment_create_retroactive",
        "experiment_start",
        "experiment_generate_report",
        "calibration_curve_import",
        "calibration_curve_export",
        "calibration_v2_fit",
        "calibration_v2_extract",
        # Safety commands that drive USBTMC hardware — must not be cancelled
        # by the fast 2-second envelope during a slow USB transaction.
        "keithley_emergency_off",
        "keithley_stop",
        # F34: GUI chat overlay routes through AssistantQueryAgent (Ollama
        # round-trip + audit log + adapter fanout). Fast 2 s envelope is
        # too tight; the helper's own asyncio.wait_for fires at 25 s,
        # comfortably inside this 30 s server cap and the 35 s subprocess /
        # GUI socket timeouts.
        "assistant.query",
    }
)


def _timeout_for(cmd: Any) -> float:
    """Return the handler timeout envelope for ``cmd``.

    Slow commands get ``HANDLER_TIMEOUT_SLOW_S``; everything else
    gets ``HANDLER_TIMEOUT_FAST_S``. Unknown / malformed payloads
    fall back to fast — a cmd that isn't in the slow set must not
    trigger the longer wait by accident.
    """
    if not isinstance(cmd, dict):
        return HANDLER_TIMEOUT_FAST_S
    action = cmd.get("cmd")
    if isinstance(action, str) and action in _SLOW_COMMANDS:
        return HANDLER_TIMEOUT_SLOW_S
    return HANDLER_TIMEOUT_FAST_S


# Phase 2b H.4: bind with EADDRINUSE retry. On Windows the socket from a
# SIGKILL'd engine can hold the port for up to 240s (TIME_WAIT). Linux is
# usually fine due to SO_REUSEADDR but the same logic protects both.
_BIND_MAX_ATTEMPTS = 10
_BIND_INITIAL_DELAY_S = 0.5
_BIND_MAX_DELAY_S = 10.0


_WILDCARD_BIND_HOSTS = frozenset({"0.0.0.0", "*", "::"})


def _reject_wildcard_bind(address: str) -> None:
    """Refuse a wildcard bind (``0.0.0.0`` / ``*`` / ``::``).

    The trust model (module docstring) treats the loopback bind as a
    compensating control for the unauthenticated hardware-control surface.
    A wildcard bind would expose that surface to the LAN. LAN access MUST go
    through an SSH tunnel to 127.0.0.1 — never bind a wildcard. Loopback and
    specific-interface addresses are unaffected.
    """
    host = address
    if "://" in host:
        host = host.split("://", 1)[1]
    # Strip the :PORT suffix and any IPv6 brackets: tcp://[::]:5555 → ::
    host = host.rsplit(":", 1)[0].strip("[]")
    if host in _WILDCARD_BIND_HOSTS:
        raise ValueError(
            f"refusing wildcard bind {address!r}: the ZMQ command/data surface "
            "is unauthenticated — bind loopback (127.0.0.1) and reach it over an "
            "SSH tunnel, never expose it to the LAN via 0.0.0.0/*/::"
        )


async def _bind_with_retry(socket: Any, address: str) -> None:
    """Bind a ZMQ socket, retrying on EADDRINUSE with exponential backoff.

    Async so the EADDRINUSE backoff yields to the event loop instead of
    freezing it: bind() runs on async start paths, and a synchronous
    ``time.sleep`` here would stall the whole engine loop for the entire
    backoff (up to ~55 s worst case) on a port collision. ``asyncio.sleep``
    keeps the loop live while the port frees up.

    Caller MUST set ``zmq.LINGER = 0`` on the socket BEFORE calling this
    helper, otherwise close() will hold the address even after retry succeeds.
    """
    # Fail fast on a wildcard bind before touching the socket or the retry loop.
    _reject_wildcard_bind(address)
    delay = _BIND_INITIAL_DELAY_S
    for attempt in range(_BIND_MAX_ATTEMPTS):
        try:
            socket.bind(address)
            if attempt > 0:
                logger.info(
                    "ZMQ bound to %s after %d retries",
                    address,
                    attempt,
                )
            return
        except zmq.ZMQError as exc:
            # libzmq maps EADDRINUSE to its own errno value.
            is_addr_in_use = exc.errno == zmq.EADDRINUSE or exc.errno == errno.EADDRINUSE
            if not is_addr_in_use:
                raise
            if attempt == _BIND_MAX_ATTEMPTS - 1:
                logger.critical(
                    "ZMQ bind FAILED after %d attempts: %s still in use. Check for stale sockets via lsof/netstat.",
                    _BIND_MAX_ATTEMPTS,
                    address,
                )
                raise
            logger.warning(
                "ZMQ bind EADDRINUSE on %s, retry in %.1fs (attempt %d/%d)",
                address,
                delay,
                attempt + 1,
                _BIND_MAX_ATTEMPTS,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, _BIND_MAX_DELAY_S)


def _pack_reading(
    reading: Reading,
    *,
    transport: dict[str, Any] | None = None,
    public_metadata: dict[str, Any] | None = None,
    descriptor_envelope: bytes | None = None,
) -> bytes:
    """Сериализовать Reading в msgpack.

    ``descriptor_envelope`` (F35 D4): optional additive top-level key
    (``"desc"``). Omitted entirely when ``None`` — a consumer still running
    the pre-D4 ``_unpack_reading()`` builds ``Reading(...)`` from named keys
    only and structurally ignores unknown keys, so this frame stays
    byte-for-byte backward compatible for any such consumer.
    """
    data = {
        "ts": reading.timestamp.timestamp(),
        "iid": reading.instrument_id,
        "ch": reading.channel,
        "v": reading.value,
        "u": reading.unit,
        "st": reading.status.value,
        "raw": reading.raw,
        "meta": reading.metadata if public_metadata is None else public_metadata,
    }
    if transport is not None:
        data["transport"] = transport
    if descriptor_envelope is not None and type(descriptor_envelope) is not bytes:
        logger.warning("Dropping malformed descriptor envelope before ZMQ serialization")
        descriptor_envelope = None
    elif descriptor_envelope is not None and len(descriptor_envelope) > MAX_PERSISTED_ENVELOPE_BYTES:
        logger.warning(
            "Dropping oversized descriptor envelope before ZMQ serialization (%d > %d bytes)",
            len(descriptor_envelope),
            MAX_PERSISTED_ENVELOPE_BYTES,
        )
        descriptor_envelope = None
    if descriptor_envelope is not None:
        data["desc"] = descriptor_envelope
    return msgpack.packb(data, use_bin_type=True)


def _pack_event(
    event_type: str,
    timestamp: datetime,
    payload: dict,
    experiment_id: str | None,
    *,
    transport: dict[str, Any] | None = None,
) -> bytes:
    """Сериализовать EngineEvent в JSON для топика ``events``.

    JSON (not msgpack) because EngineEvent payloads are heterogeneous,
    application-defined dicts (alarm details, experiment metadata, ...)
    rather than the fixed Reading schema — JSON keeps this frame
    self-describing without a second bespoke packer.
    """
    data = {
        "event_type": event_type,
        "ts": timestamp.timestamp(),
        "payload": payload,
        "experiment_id": experiment_id,
    }
    if transport is not None:
        data["transport"] = transport
    return json.dumps(data, default=str).encode("utf-8")


def _unpack_event(payload: bytes) -> dict[str, Any]:
    """Десериализовать событие из топика ``events``.

    Same defence-in-depth as ``_unpack_reading``: size-bound before
    decode (events are small JSON objects; this cap is generous).
    """
    if len(payload) > MAX_DATA_MSG_SIZE:
        raise ValueError(f"event frame too large: {len(payload)} > {MAX_DATA_MSG_SIZE}")
    return json.loads(payload.decode("utf-8"))


def _unpack_reading_data(payload: bytes) -> tuple[Reading, object, bool]:
    """Десериализовать Reading из msgpack.

    Defence in depth over the SUB socket's ``ZMQ_MAXMSGSIZE`` cap: reject an
    oversize frame up front (guards paths that don't come through the capped
    socket), and bound each decoded element so a crafted frame can't drive a
    huge allocation during unpacking. msgpack 1.x has no ``max_buffer_size``
    on ``unpackb`` — the per-type ``max_*_len`` caps are the equivalent, and
    they raise ``ValueError`` when exceeded.
    """
    if len(payload) > MAX_DATA_MSG_SIZE:
        raise ValueError(f"msgpack frame too large: {len(payload)} > {MAX_DATA_MSG_SIZE}")
    data = msgpack.unpackb(
        payload,
        raw=False,
        max_str_len=MAX_DATA_MSG_SIZE,
        max_bin_len=MAX_DATA_MSG_SIZE,
        max_array_len=MAX_DATA_MSG_SIZE,
        max_map_len=MAX_DATA_MSG_SIZE,
    )
    reading = Reading(
        timestamp=datetime.fromtimestamp(data["ts"], tz=UTC),
        instrument_id=data.get("iid", ""),
        channel=data["ch"],
        value=data["v"],
        unit=data["u"],
        status=ChannelStatus(data["st"]),
        raw=data.get("raw"),
        metadata=data.get("meta", {}),
    )
    return reading, data.get("desc"), "desc" in data


def _unpack_reading(payload: bytes) -> Reading:
    """Deserialize a Reading while ignoring the additive descriptor field."""

    reading, _, _ = _unpack_reading_data(payload)
    return reading


def _unpack_qualified_reading(payload: bytes) -> DescriptorQualifiedReading:
    """Deserialize once and strictly qualify the optional descriptor field."""

    reading, descriptor_payload, descriptor_present = _unpack_reading_data(payload)
    return qualify_reading_descriptor(
        reading,
        descriptor_payload,
        envelope_present=descriptor_present,
    )


class ZMQPublisher:
    """PUB-сокет: engine публикует Reading для GUI и внешних подписчиков.

    Использование::

        pub = ZMQPublisher("tcp://127.0.0.1:5555")
        await pub.start(queue)   # asyncio.Queue[Reading] от DataBroker
        ...
        await pub.stop()
    """

    def __init__(self, address: str = DEFAULT_PUB_ADDR, *, topic: bytes = DEFAULT_TOPIC) -> None:
        self._address = address
        self._topic = topic
        self._ctx: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._total_sent: int = 0
        self._queue: asyncio.Queue[Reading] | None = None
        self._session_id: str | None = None
        self._sequence = 0
        self._publish_failure_count = 0
        self._send_lock = asyncio.Lock()
        self._reading_drop_count: Callable[[], int] | None = None
        self._alarm_snapshot: Callable[[], Any] | None = None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def publish_failure_count(self) -> int:
        return self._publish_failure_count

    def configure_periodic_authority(
        self,
        *,
        reading_drop_count: Callable[[], int],
        alarm_snapshot: Callable[[], Any],
    ) -> None:
        """Install live-engine-only barrier samplers without breaking replay."""
        self._reading_drop_count = reading_drop_count
        self._alarm_snapshot = alarm_snapshot

    def _transport(self, sequence: int, *, authoritative: bool) -> dict[str, Any]:
        session_id = self._session_id
        if session_id is None:
            raise RuntimeError("publisher session unavailable")
        return {
            "schema": PERIODIC_STREAM_SCHEMA,
            "session_id": session_id,
            "sequence": sequence,
            "persistence_authoritative": authoritative,
        }

    def _allocate_sequence(self) -> int:
        if self._sequence >= PERIODIC_MAX_SEQUENCE:
            raise RuntimeError("periodic stream sequence exhausted")
        self._sequence += 1
        return self._sequence

    async def _send_allocated(
        self,
        topic: bytes,
        encode: Callable[[int], bytes],
    ) -> int:
        """Allocate, encode, and send while the caller owns ``_send_lock``."""
        sequence = self._allocate_sequence()
        try:
            frame = encode(sequence)
            socket = self._socket
            if socket is None:
                raise RuntimeError("publisher socket unavailable")
            await socket.send_multipart([topic, frame])
        except BaseException:
            self._publish_failure_count += 1
            raise
        self._total_sent += 1
        return sequence

    async def _publish_reading(self, reading: Reading, *, descriptor_envelope: bytes | None = None) -> None:
        metadata = dict(reading.metadata)
        authoritative = metadata.pop(PERSISTENCE_AUTHORITATIVE_METADATA_KEY, False) is True
        async with self._send_lock:
            await self._send_allocated(
                self._topic,
                lambda sequence: _pack_reading(
                    reading,
                    transport=self._transport(
                        sequence,
                        authoritative=authoritative,
                    ),
                    public_metadata=metadata,
                    descriptor_envelope=descriptor_envelope,
                ),
            )

    async def _publish_loop(self, queue: asyncio.Queue[Reading]) -> None:
        while self._running:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                # F35 D4: the zmq_publisher subscription opts in to
                # DataBroker's descriptor-envelope companion, so this queue
                # carries PublishedReading pairs instead of bare Reading.
                if type(item) is PublishedReading:
                    await self._publish_reading(item.reading, descriptor_envelope=item.descriptor_envelope)
                else:
                    await self._publish_reading(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка отправки ZMQ")
            finally:
                queue.task_done()

    async def publish_event(
        self,
        *,
        event_type: str,
        timestamp: datetime,
        payload: dict,
        experiment_id: str | None,
    ) -> None:
        """Publish one EngineEvent on the ``events`` topic (best-effort).

        B1: separate from the Reading queue path — events are ad-hoc
        (alarm_fired, experiment_finalize, ...), not a steady stream, so
        they are sent directly rather than routed through the
        Reading-typed ``_publish_loop`` queue. No-op if the socket isn't
        started yet (mirrors the Reading path's silent-drop-until-ready
        behaviour); a send failure is logged, never raised — a lost
        event must not affect the safety-critical engine loop.
        """
        if self._socket is None or not self._running:
            return
        try:
            async with self._send_lock:
                await self._send_allocated(
                    EVENTS_TOPIC,
                    lambda sequence: _pack_event(
                        event_type,
                        timestamp,
                        payload,
                        experiment_id,
                        transport=self._transport(
                            sequence,
                            authoritative=False,
                        ),
                    ),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка отправки ZMQ события %s", event_type)

    async def publish_operator_snapshot(self, snapshot: OperatorSnapshot) -> bool:
        """Publish one complete observational snapshot on the sole PUB socket.

        Encoding and the multipart send happen under the same lock used by
        readings and events.  A presentation-path failure is observable but
        deliberately cannot escape into safety or control behavior.
        """
        try:
            async with self._send_lock:
                frames = encode_operator_snapshot_frames(snapshot)
                socket = self._socket
                if not self._running or socket is None:
                    raise RuntimeError("publisher socket unavailable")
                await socket.send_multipart(list(frames))
                self._total_sent += 1
                return True
        except asyncio.CancelledError:
            self._publish_failure_count += 1
            raise
        except Exception:
            self._publish_failure_count += 1
            logger.exception("Ошибка отправки operator snapshot")
            return False

    @staticmethod
    def _barrier_error(code: str) -> dict[str, Any]:
        return {
            "ok": False,
            "schema": PERIODIC_BARRIER_SCHEMA,
            "error_code": code,
        }

    def _publisher_alive(
        self,
        *,
        task: asyncio.Task[None],
        queue: asyncio.Queue[Reading],
    ) -> bool:
        return (
            self._running
            and self._task is task
            and not task.done()
            and self._queue is queue
            and self._socket is not None
            and self._session_id is not None
            and self._sequence < PERIODIC_MAX_SEQUENCE
        )

    async def barrier(self, nonce: str) -> dict[str, Any]:
        """Publish one queue fence and return its byte-equivalent evidence."""
        if type(nonce) is not str or len(nonce) != 32 or any(ch not in "0123456789abcdef" for ch in nonce):
            return self._barrier_error("barrier_invalid")
        task = self._task
        queue = self._queue
        if (
            task is None
            or queue is None
            or self._reading_drop_count is None
            or self._alarm_snapshot is None
            or not self._publisher_alive(task=task, queue=queue)
        ):
            return self._barrier_error("barrier_unavailable")

        try:
            async with asyncio.timeout(_PERIODIC_BARRIER_TIMEOUT_S):
                await queue.join()
                async with self._send_lock:
                    if not self._publisher_alive(task=task, queue=queue):
                        return self._barrier_error("barrier_unavailable")
                    drop_count = self._reading_drop_count()
                    snapshot = self._alarm_snapshot()
                    if type(drop_count) is not int or drop_count < 0:
                        return self._barrier_error("barrier_unavailable")
                    revision = snapshot.state_revision
                    token = snapshot.state_token
                    if (
                        type(revision) is not int
                        or revision < 0
                        or type(token) is not str
                        or len(token) != len(_PERIODIC_TOKEN_PREFIX) + 64
                        or not token.startswith(_PERIODIC_TOKEN_PREFIX)
                        or any(ch not in "0123456789abcdef" for ch in token[7:])
                    ):
                        return self._barrier_error("barrier_unavailable")
                    published_at = time.time()
                    if not math.isfinite(published_at):
                        return self._barrier_error("barrier_unavailable")
                    session_id = self._session_id
                    failure_count = self._publish_failure_count

                    def encode(sequence: int) -> bytes:
                        payload = {
                            "proto": PROTOCOL_VERSION,
                            "schema": PERIODIC_BARRIER_SCHEMA,
                            "nonce": nonce,
                            "session_id": session_id,
                            "sequence": sequence,
                            "published_at": published_at,
                            "reading_drop_count": drop_count,
                            "publish_failure_count": failure_count,
                            "alarm_state_revision": revision,
                            "alarm_state_token": token,
                        }
                        return json.dumps(
                            payload,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        ).encode("utf-8")

                    sequence = await self._send_allocated(
                        PERIODIC_BARRIER_TOPIC,
                        encode,
                    )
                    if not self._publisher_alive(task=task, queue=queue):
                        return self._barrier_error("barrier_unavailable")
                    try:
                        post_revision = self._alarm_snapshot().state_revision
                        post_drop_count = self._reading_drop_count()
                    except BaseException:
                        self._publish_failure_count += 1
                        raise
                    if (
                        type(post_revision) is not int
                        or post_revision != revision
                        or type(post_drop_count) is not int
                        or post_drop_count != drop_count
                    ):
                        return self._barrier_error("barrier_unstable")
                    return {
                        "ok": True,
                        "proto": PROTOCOL_VERSION,
                        "schema": PERIODIC_BARRIER_SCHEMA,
                        "nonce": nonce,
                        "session_id": session_id,
                        "sequence": sequence,
                        "published_at": published_at,
                        "reading_drop_count": drop_count,
                        "publish_failure_count": failure_count,
                        "alarm_state_revision": revision,
                        "alarm_state_token": token,
                    }
        except TimeoutError:
            return self._barrier_error("barrier_timeout")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Periodic barrier failed")
            return self._barrier_error("barrier_unavailable")

    async def start(self, queue: asyncio.Queue[Reading]) -> None:
        if self._running or self._task is not None or self._socket is not None or self._ctx is not None:
            raise RuntimeError("ZMQPublisher is already started")
        self._queue = queue
        self._session_id = secrets.token_hex(16)
        self._sequence = 0
        self._publish_failure_count = 0
        self._send_lock = asyncio.Lock()
        self._ctx = zmq.asyncio.Context()
        self._socket = self._ctx.socket(zmq.PUB)
        # Phase 2b H.4: LINGER=0 so the socket doesn't hold the port open
        # after close — relevant on Windows where TIME_WAIT can keep
        # 5555 occupied for 240s after a SIGKILL'd engine.
        self._socket.setsockopt(zmq.LINGER, 0)
        # IV.6: TCP_KEEPALIVE previously added here on the idle-reap
        # hypothesis (commit f5f9039). revised analysis disproved
        # that — Ubuntu 120 s deterministic failure with default
        # tcp_keepalive_time=7200 s rules out kernel reaping. Keepalive
        # reverted on the command path (REQ + REP); retained on the
        # SUB drain path in zmq_subprocess.sub_drain_loop as an
        # orthogonal safeguard for long between-experiment pauses.
        try:
            await _bind_with_retry(self._socket, self._address)
            self._running = True
            self._task = asyncio.create_task(
                self._publish_loop(queue),
                name="zmq_publisher",
            )
        except BaseException:
            self._running = False
            if self._socket is not None:
                self._socket.close(linger=0)
                self._socket = None
            if self._ctx is not None:
                self._ctx.term()
                self._ctx = None
            self._queue = None
            self._session_id = None
            raise
        logger.info("ZMQPublisher запущен: %s", self._address)

    async def stop(self) -> None:
        self._running = False
        caller_task = asyncio.current_task()
        caller_cancel_baseline = caller_task.cancelling() if caller_task is not None else 0
        first_error: BaseException | None = None
        drain_task = self._task
        if drain_task is not None:
            drain_task.cancel()
            try:
                await drain_task
            except asyncio.CancelledError as exc:
                if caller_task is not None and caller_task.cancelling() > caller_cancel_baseline:
                    first_error = exc
            except BaseException as exc:
                first_error = exc
            finally:
                self._task = None
            if (
                caller_task is not None
                and caller_task.cancelling() > caller_cancel_baseline
                and not isinstance(first_error, asyncio.CancelledError)
            ):
                first_error = asyncio.CancelledError()

        async def _cleanup() -> None:
            cleanup_error: BaseException | None = None
            async with self._send_lock:
                try:
                    if self._socket:
                        self._socket.close(linger=0)
                except BaseException as exc:
                    cleanup_error = exc
                finally:
                    self._socket = None
                try:
                    if self._ctx:
                        self._ctx.term()
                except BaseException as exc:
                    if cleanup_error is None:
                        cleanup_error = exc
                finally:
                    self._ctx = None
                    self._queue = None
                    self._session_id = None
            if cleanup_error is not None:
                raise cleanup_error

        cleanup_task = asyncio.create_task(
            _cleanup(),
            name="zmq_publisher_cleanup",
        )
        while True:
            try:
                await asyncio.shield(cleanup_task)
                break
            except asyncio.CancelledError as exc:
                if caller_task is not None and caller_task.cancelling() > caller_cancel_baseline:
                    first_error = exc
                elif first_error is None:
                    first_error = exc
                if cleanup_task.done():
                    try:
                        cleanup_task.result()
                    except BaseException as cleanup_exc:
                        if first_error is None:
                            first_error = cleanup_exc
                    break
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
                break
        logger.info("ZMQPublisher остановлен (отправлено: %d)", self._total_sent)
        if first_error is not None:
            raise first_error


class ZMQSubscriber:
    """SUB-сокет: GUI-процесс подписывается на поток данных от engine.

    Использование::

        async def on_reading(r: Reading):
            print(r.channel, r.value)

        sub = ZMQSubscriber("tcp://127.0.0.1:5555", callback=on_reading)
        await sub.start()
        ...
        await sub.stop()

    ``descriptor_callback`` is an additive opt-in for consumers that need the
    provider-neutral immutable descriptor-qualified carrier.  Supplying it does
    not disable or change the legacy bare ``callback``; both observe the same
    frame from the same socket and receive path.
    """

    def __init__(
        self,
        address: str = DEFAULT_PUB_ADDR,
        *,
        topic: bytes = DEFAULT_TOPIC,
        callback: Callable[[Reading], object] | None = None,
        descriptor_callback: Callable[[DescriptorQualifiedReading], object] | None = None,
    ) -> None:
        self._address = address
        self._topic = topic
        self._callback = callback
        self._descriptor_callback = descriptor_callback
        self._ctx: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._total_received: int = 0
        self._descriptor_issue_count: int = 0

    async def _receive_loop(self) -> None:
        while self._running:
            try:
                events = await self._socket.poll(timeout=1000)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка poll ZMQ")
                continue
            if not (events & zmq.POLLIN):
                continue
            try:
                parts = await self._socket.recv_multipart()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка приёма ZMQ")
                continue
            if len(parts) != 2:
                continue
            try:
                if self._descriptor_callback is None:
                    reading = _unpack_reading(parts[1])
                    qualified = None
                else:
                    qualified = _unpack_qualified_reading(parts[1])
                    reading = qualified.reading
                    if qualified.descriptor_issue is not None:
                        self._descriptor_issue_count = min(
                            (1 << 64) - 1,
                            self._descriptor_issue_count + 1,
                        )
                self._total_received += 1
            except Exception:
                logger.exception("Ошибка десериализации Reading")
                continue
            if self._callback:
                try:
                    result = self._callback(reading)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.exception("Ошибка в callback подписчика")
            if self._descriptor_callback and qualified is not None:
                try:
                    result = self._descriptor_callback(qualified)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.exception("Ошибка в descriptor callback подписчика")

    @property
    def descriptor_issue_count(self) -> int:
        """Saturating count of refused present descriptor envelopes."""

        return self._descriptor_issue_count

    async def start(self) -> None:
        self._ctx = zmq.asyncio.Context()
        self._socket = self._ctx.socket(zmq.SUB)
        self._socket.setsockopt(zmq.LINGER, 0)
        # Audit C.2 / D6: drop oversize inbound frames at the socket
        # level, before libzmq allocates them (set before connect()).
        self._socket.setsockopt(zmq.MAXMSGSIZE, MAX_DATA_MSG_SIZE)
        self._socket.setsockopt(zmq.RECONNECT_IVL, 500)
        self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)
        self._socket.setsockopt(zmq.RCVTIMEO, 3000)
        self._socket.connect(self._address)
        self._socket.subscribe(self._topic)
        self._running = True
        self._task = asyncio.create_task(self._receive_loop(), name="zmq_subscriber")
        logger.info("ZMQSubscriber подключён: %s", self._address)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._socket:
            self._socket.close(linger=0)
            self._socket = None
        if self._ctx:
            self._ctx.term()
            self._ctx = None
        logger.info("ZMQSubscriber остановлен (получено: %d)", self._total_received)


class ZMQEventSubscriber:
    """SUB-сокет на топик ``events``: cryodaq-assistant подписывается на
    EngineEvent-уведомления (alarm_fired, experiment_finalize, ...).

    Same socket options / reconnect semantics as :class:`ZMQSubscriber`
    (kept separate rather than parametrising ``ZMQSubscriber`` — the two
    have different payload/topic/unpack shapes and this avoids risking a
    regression in the well-exercised Reading subscriber).
    """

    def __init__(
        self,
        address: str = DEFAULT_PUB_ADDR,
        *,
        callback: Callable[[dict], object] | None = None,
    ) -> None:
        self._address = address
        self._callback = callback
        self._ctx: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def _receive_loop(self) -> None:
        while self._running:
            try:
                events = await self._socket.poll(timeout=1000)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка poll ZMQ (events)")
                continue
            if not (events & zmq.POLLIN):
                continue
            try:
                parts = await self._socket.recv_multipart()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка приёма ZMQ (events)")
                continue
            if len(parts) != 2:
                continue
            try:
                event = _unpack_event(parts[1])
            except Exception:
                logger.exception("Ошибка десериализации события")
                continue
            if self._callback:
                try:
                    result = self._callback(event)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.exception("Ошибка в callback подписчика событий")

    async def start(self) -> None:
        self._ctx = zmq.asyncio.Context()
        self._socket = self._ctx.socket(zmq.SUB)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.setsockopt(zmq.MAXMSGSIZE, MAX_DATA_MSG_SIZE)
        self._socket.setsockopt(zmq.RECONNECT_IVL, 500)
        self._socket.setsockopt(zmq.RECONNECT_IVL_MAX, 5000)
        self._socket.setsockopt(zmq.RCVTIMEO, 3000)
        self._socket.connect(self._address)
        self._socket.subscribe(EVENTS_TOPIC)
        self._running = True
        self._task = asyncio.create_task(self._receive_loop(), name="zmq_event_subscriber")
        logger.info("ZMQEventSubscriber подключён: %s", self._address)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._socket:
            self._socket.close(linger=0)
            self._socket = None
        if self._ctx:
            self._ctx.term()
            self._ctx = None
        logger.info("ZMQEventSubscriber остановлен")


class ZMQCommandServer:
    """REP-сокет: engine принимает JSON-команды от GUI.

    Использование::

        async def handler(cmd: dict) -> dict:
            return {"ok": True}

        srv = ZMQCommandServer(handler=handler)
        await srv.start()
        ...
        await srv.stop()
    """

    def __init__(
        self,
        address: str = DEFAULT_CMD_ADDR,
        *,
        handler: Callable[[dict[str, Any]], Any] | None = None,
        handler_timeout_s: float | None = None,
        server_label: Literal["engine", "assistant"] = "engine",
    ) -> None:
        if not isinstance(server_label, str) or server_label not in _SERVER_LABELS:
            allowed = ", ".join(sorted(_SERVER_LABELS))
            raise ValueError(f"server_label must be one of: {allowed}")
        self._address = address
        self._handler = handler
        self._server_role = server_label
        # IV.3 Finding 7: honour an explicit override (tests supply one
        # to exercise the timeout path without sleeping for 2 s), but
        # the production path uses the tiered ``_timeout_for(cmd)``
        # helper so slow commands get 30 s and fast commands 2 s.
        self._handler_timeout_override_s = handler_timeout_s
        self._ctx: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._task: asyncio.Task[None] | None = None
        self._restart_task: asyncio.Task[None] | None = None
        self._handler_tasks: set[asyncio.Task[Any]] = set()
        self._uncertain_authority_tasks: set[asyncio.Task[Any]] = set()
        self._running = False
        self._shutdown_requested = False

    def _start_serve_task(self) -> None:
        """Spawn the command loop exactly once while the server is running."""
        if not self._running or self._shutdown_requested:
            return
        if self._task is not None and not self._task.done():
            return
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._serve_loop(), name="zmq_cmd_server")
        self._task.add_done_callback(self._on_serve_task_done)

    def _observe_handler_task(
        self,
        task: asyncio.Task[Any],
        *,
        action: str,
    ) -> None:
        """Consume a detached handler result without exposing its payload."""

        self._handler_tasks.discard(task)
        self._uncertain_authority_tasks.discard(task)
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error(
                "ZMQ detached command handler failed: action=%s exception=%s",
                action,
                type(exc).__name__,
            )
        else:
            logger.warning(
                "ZMQ detached command handler settled after reply: action=%s",
                action,
            )

    def _detach_handler_task(
        self,
        task: asyncio.Task[Any],
        *,
        action: str,
        command_class: CommandClass,
    ) -> None:
        """Cancel without waiting and quarantine uncertain command authority."""

        if command_class is not CommandClass.READ:
            self._uncertain_authority_tasks.add(task)
        task.add_done_callback(
            lambda settled, label=action: self._observe_handler_task(
                settled,
                action=label,
            )
        )
        if command_class is CommandClass.READ:
            task.cancel()

    async def _open_bound_socket(self) -> zmq.asyncio.Socket:
        """Create and bind a fresh REP socket with the full boundary policy."""

        if self._ctx is None:
            raise RuntimeError("ZMQ command context is not available")
        socket = self._ctx.socket(zmq.REP)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.MAXMSGSIZE, MAX_CMD_MSG_SIZE)
        try:
            await _bind_with_retry(socket, self._address)
        except BaseException:
            socket.close(linger=0)
            raise
        return socket

    async def _restart_after_unexpected_exit(self) -> None:
        """Replace a possibly poisoned REP socket before restarting its loop."""

        current = asyncio.current_task()
        try:
            old_socket, self._socket = self._socket, None
            if old_socket is not None:
                old_socket.close(linger=0)
            if self._shutdown_requested or not self._running:
                return
            self._socket = await self._open_bound_socket()
            if self._shutdown_requested or not self._running:
                self._socket.close(linger=0)
                self._socket = None
                return
            # Release recovery ownership before the replacement task can run.
            # If that task exits immediately, its done callback must be able to
            # schedule a second socket replacement rather than observe this
            # almost-finished recovery task and leave the server ownerless.
            if self._restart_task is current:
                self._restart_task = None
            self._start_serve_task()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._running = False
            logger.error(
                "ZMQCommandServer socket recovery failed: exception=%s",
                type(exc).__name__,
            )
        finally:
            if self._restart_task is current:
                self._restart_task = None

    def _on_serve_task_done(self, task: asyncio.Task[None]) -> None:
        """Restart the REP loop after unexpected task exit."""
        if task is not self._task:
            return

        try:
            exc = task.exception()
        except asyncio.CancelledError:
            exc = None

        self._task = None
        if self._shutdown_requested or not self._running:
            return

        if exc is not None:
            logger.error(
                "ZMQCommandServer serve loop crashed; replacing socket: exception=%s",
                type(exc).__name__,
            )
        else:
            logger.error("ZMQCommandServer serve loop exited unexpectedly; replacing socket")

        loop = task.get_loop()
        if loop.is_closed():
            logger.error("ZMQCommandServer loop is closed; cannot restart serve loop")
            return
        if self._restart_task is None or self._restart_task.done():
            self._restart_task = loop.create_task(
                self._restart_after_unexpected_exit(),
                name="zmq_cmd_server_recover",
            )

    async def _run_handler(self, cmd: dict[str, Any]) -> dict[str, Any]:
        """Execute the command handler with a bounded wall-clock timeout.

        IV.3 Finding 7: always returns a dict. REP sockets require exactly
        one send() per recv(); any path that silently raises here would
        leave REP wedged and cascade every subsequent command into
        timeouts. Timeout fired or unexpected handler exception both
        yield an ``ok=False`` reply with the failure reason and — on
        timeout — the ``_handler_timeout`` marker so callers can tell
        the difference from a normal handler-reported error.
        """
        # Answer discovery before application dispatch so it remains available
        # even if no command handler is configured.
        if isinstance(cmd, dict) and str(cmd.get("cmd", "")) == "protocol_version":
            return {
                "ok": True,
                "proto": PROTOCOL_VERSION,
                "server": self._server_label(),
                "app_version": _APP_VERSION,
            }

        if self._handler is None:
            return {"ok": False, "error": "no handler"}

        # IV.3 Finding 7 amend: _serve_loop forwards any valid JSON,
        # not only objects. A scalar or list payload (valid JSON, wrong
        # shape) previously raised AttributeError on cmd.get(...) and
        # fell out to the outer serve-loop catch — still sent a reply
        # so REP was not wedged, but the failure path was accidental.
        # Validate the shape here so _run_handler's "always returns a
        # dict" contract is explicit rather than luck-dependent.
        if not isinstance(cmd, dict):
            logger.warning(
                "ZMQ command payload is %s, not dict — rejecting.",
                type(cmd).__name__,
            )
            return {
                "ok": False,
                "error": f"invalid payload: expected object, got {type(cmd).__name__}",
            }

        raw_action = cmd.get("cmd")
        action = _bounded_action_label(raw_action)
        timeout = (
            self._handler_timeout_override_s if self._handler_timeout_override_s is not None else _timeout_for(cmd)
        )

        async def _invoke() -> Any:
            result = self._handler(cmd)
            if asyncio.iscoroutine(result):
                result = await result
            return result

        handler_task = asyncio.create_task(
            _invoke(),
            name=f"zmq_command_handler:{action}",
        )
        self._handler_tasks.add(handler_task)
        try:
            done, _pending = await asyncio.wait({handler_task}, timeout=timeout)
        except asyncio.CancelledError:
            handler_task.add_done_callback(
                lambda settled, label=action: self._observe_handler_task(
                    settled,
                    action=label,
                )
            )
            handler_task.cancel()
            raise

        if not done:
            handler_task.add_done_callback(
                lambda settled, label=action: self._observe_handler_task(
                    settled,
                    action=label,
                )
            )
            handler_task.cancel()
            logger.error(
                "ZMQ command handler timeout: action=%s",
                action,
            )
            reply = _post_dispatch_failure(
                raw_action,
                error_code="command_handler_timeout",
                error="Command handler timed out; outcome may be unknown.",
            )
            reply["_handler_timeout"] = True
            return reply

        self._handler_tasks.discard(handler_task)
        try:
            result = handler_task.result()
        except TimeoutError:
            logger.error(
                "ZMQ command handler reported timeout: action=%s",
                action,
            )
            reply = _post_dispatch_failure(
                raw_action,
                error_code="command_handler_timeout",
                error="Command handler timed out; outcome may be unknown.",
            )
            reply["_handler_timeout"] = True
            return reply
        except asyncio.CancelledError:
            logger.error("ZMQ command handler cancelled itself: action=%s", action)
            return _post_dispatch_failure(
                raw_action,
                error_code="command_handler_cancelled",
                error="Command handler was cancelled; outcome may be unknown.",
            )
        except Exception as exc:
            logger.error(
                "ZMQ command handler failed: action=%s exception=%s",
                action,
                type(exc).__name__,
            )
            return _post_dispatch_failure(
                raw_action,
                error_code="command_handler_failed",
                error="Command handler failed; outcome may be unknown.",
            )

        if isinstance(result, dict):
            return result
        logger.error(
            "ZMQ command handler returned invalid type: action=%s result_type=%s",
            action,
            type(result).__name__,
        )
        return _post_dispatch_failure(
            raw_action,
            error_code="command_handler_contract_invalid",
            error="Command handler returned an invalid reply; outcome may be unknown.",
        )

    def _server_label(self) -> str:
        """Return the explicit role advertised by ``protocol_version``."""
        return self._server_role

    def _encode_reply(self, reply: dict[str, Any]) -> bytes:
        """Serialize a REP reply, injecting the additive ``proto`` field.

        Success, malformed-JSON reject, handler timeout/exception, and
        recoverable serialization-failure replies pass through this method
        before ``send()``. Other keys are preserved; the authoritative
        ``proto`` value replaces any handler-provided value so handlers cannot
        omit or spoof the envelope version.
        """
        if isinstance(reply, PeriodicCommandReply):
            return reply.wire
        return encode_command_reply(reply)

    async def _serve_loop(self) -> None:
        while self._running:
            socket = self._socket
            if socket is None:
                raise RuntimeError("ZMQ command socket is not available")
            try:
                events = await socket.poll(timeout=1000)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "ZMQ command poll failed: exception=%s",
                    type(exc).__name__,
                )
                raise
            if not (events & zmq.POLLIN):
                continue
            try:
                raw = await socket.recv()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "ZMQ command receive failed: exception=%s",
                    type(exc).__name__,
                )
                raise

            # Exactly one send attempt follows each successful recv. If that
            # attempt fails or is cancelled, the REP state is unknowable and
            # the task exits so its supervisor replaces the socket.
            try:
                cmd = _decode_command(raw)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError, TypeError):
                reply = {
                    "ok": False,
                    "error_code": "command_request_invalid",
                    "error": "Command request is invalid.",
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": True,
                }
                raw_action: object = None
            else:
                raw_action = cmd.get("cmd")
                try:
                    reply = await self._run_handler(cmd)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(
                        "ZMQ command dispatch failed unexpectedly: action=%s exception=%s",
                        _bounded_action_label(raw_action),
                        type(exc).__name__,
                    )
                    reply = _post_dispatch_failure(
                        raw_action,
                        error_code="command_dispatch_failed",
                        error="Command dispatch failed; outcome may be unknown.",
                    )

            try:
                wire = self._encode_reply(reply)
            except Exception as exc:
                logger.error(
                    "ZMQ command reply serialization failed: action=%s exception=%s",
                    _bounded_action_label(raw_action),
                    type(exc).__name__,
                )
                try:
                    wire = self._encode_reply(
                        _post_dispatch_failure(
                            raw_action,
                            error_code="command_reply_serialization_failed",
                            error=("Command reply could not be serialized; outcome may be unknown."),
                        )
                    )
                except Exception:
                    wire = _SERIALIZATION_ERROR_WIRE

            try:
                await socket.send(wire)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "ZMQ command reply send failed: action=%s exception=%s",
                    _bounded_action_label(raw_action),
                    type(exc).__name__,
                )
                raise

    async def start(self) -> None:
        self._ctx = zmq.asyncio.Context()
        self._socket = await self._open_bound_socket()
        self._running = True
        self._shutdown_requested = False
        self._start_serve_task()
        logger.info("ZMQCommandServer запущен: %s", self._address)

    async def stop(self) -> None:
        self._shutdown_requested = True
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._restart_task:
            self._restart_task.cancel()
            try:
                await self._restart_task
            except asyncio.CancelledError:
                pass
            self._restart_task = None
        if self._socket:
            self._socket.close(linger=0)
            self._socket = None
        if self._ctx:
            self._ctx.term()
            self._ctx = None
        logger.info("ZMQCommandServer остановлен")
