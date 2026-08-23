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
  ``tcp://127.0.0.1:*`` (``DEFAULT_PUB_ADDR`` / ``DEFAULT_CMD_ADDR`` /
  ``DEFAULT_SAFE_CMD_ADDR``), and
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
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version as _pkg_version
from typing import Any, Literal

import msgpack
import zmq
import zmq.asyncio

from cryodaq.channels.persistence import MAX_PERSISTED_ENVELOPE_BYTES
from cryodaq.core.broker import (
    PERSISTENCE_AUTHORITATIVE_METADATA_KEY,
    PublishedReading,
    RequiredPublication,
)
from cryodaq.core.command_authority import (
    CommandClass,
    classify_engine_command,
    is_quarantine_bypass_safe_direction,
)
from cryodaq.core.command_reply_contract import (
    COMMAND_REPLY_MAX_INTEGER_DIGITS,
    COMMAND_REPLY_MAX_JSON_DEPTH,
    COMMAND_REPLY_MAX_JSON_ITEMS,
    COMMAND_REPLY_MAX_JSON_KEY_CHARS,
    COMMAND_REPLY_MAX_WIRE_BYTES,
    validate_command_reply_structure,
)
from cryodaq.core.descriptor_transport import (
    DescriptorQualifiedReading,
    qualify_reading_descriptor,
)
from cryodaq.core.zmq_endpoints import require_distinct_loopback_tcp_endpoints
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
DEFAULT_SAFE_CMD_ADDR = "tcp://127.0.0.1:5558"
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

# THE TOPICS THAT CONSUME THE SHARED SEQUENCE, and the only ones allowed to.
#
# `_allocate_sequence` advances one counter for the whole socket, and the private
# subscriber validates that counter for continuity. A topic outside this set that
# allocated a sequence would therefore create a GAP for every subscriber that does
# not participate in it -- and a gap invalidates the whole live generation, which is
# the failure this file's fourth topic already caused once by a different route.
#
# A new topic joins this set only together with the subscribers that must follow it.
# Publishing outside the sequence is the ordinary case: `publish_operator_snapshot`
# does not allocate, which is why an operator snapshot never disturbed continuity.
_SEQUENCED_TOPICS: tuple[bytes, ...] = (DEFAULT_TOPIC, EVENTS_TOPIC, PERIODIC_BARRIER_TOPIC)
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
    if len(action) > 64 or any(not (char.isascii() and (char.isalnum() or char in "._-")) for char in action):
        return "<invalid>"
    return action


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


_HANDLER_SETTLEMENT_FIELDS = frozenset(
    {
        "commit_state",
        "delivery_state",
        "outcome_unknown",
    }
)


def _handler_reply_has_exact_terminal_settlement(reply: object) -> bool:
    """Return whether a dispatched handler supplied coherent terminal proof."""

    if type(reply) is not dict:
        return False
    try:
        return (
            reply.get("delivery_state") == "dispatched"
            and reply.get("commit_state") in {"committed", "not_committed"}
            and reply.get("outcome_unknown", False) is False
        )
    except Exception:
        return False


def _handler_reply_outcome_is_unknown(reply: object) -> bool:
    """Recognize incoherent post-dispatch settlement evidence, fail closed.

    Immediate handler completion remains backwards-compatible only when the
    reply contains no settlement vocabulary at all. Once a handler supplies
    any settlement field, it must prove the exact coherent tuple: dispatched,
    committed/not-committed, and no unknown marker. Partial or contradictory
    vocabulary cannot manufacture optimistic authority settlement.
    """

    if not isinstance(reply, dict):
        return True
    try:
        if not any(field in reply for field in _HANDLER_SETTLEMENT_FIELDS):
            return False
    except Exception:
        return True
    return not _handler_reply_has_exact_terminal_settlement(reply)


def _late_handler_reply_proves_terminal_settlement(reply: object) -> bool:
    """Require exact terminal evidence before releasing a detached mutation."""

    return _handler_reply_has_exact_terminal_settlement(reply)


class _HandlerDispatchTrace:
    """Task-local proof that the application handler actually started."""

    __slots__ = ("command_class", "task")

    def __init__(self) -> None:
        self.task: asyncio.Task[Any] | None = None
        self.command_class: CommandClass | None = None


_HANDLER_DISPATCH_TRACE: ContextVar[_HandlerDispatchTrace | None] = ContextVar(
    "cryodaq_handler_dispatch_trace",
    default=None,
)


def encode_command_reply(reply: dict[str, Any]) -> bytes:
    """Serialize the one authoritative REP envelope used on the wire."""
    if type(reply) is not dict:
        raise TypeError("command reply must be an exact dict")
    envelope = {**reply, "proto": PROTOCOL_VERSION}
    validate_command_reply_structure(
        envelope,
        max_wire_bytes=MAX_COMMAND_REPLY_SIZE,
        max_depth=COMMAND_REPLY_MAX_JSON_DEPTH,
        max_items=COMMAND_REPLY_MAX_JSON_ITEMS,
        max_key_chars=COMMAND_REPLY_MAX_JSON_KEY_CHARS,
        max_integer_digits=COMMAND_REPLY_MAX_INTEGER_DIGITS,
    )
    try:
        wire = json.dumps(
            envelope,
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
    validate_command_reply_structure(
        envelope,
        max_wire_bytes=MAX_COMMAND_REPLY_SIZE,
        max_depth=COMMAND_REPLY_MAX_JSON_DEPTH,
        max_items=COMMAND_REPLY_MAX_JSON_ITEMS,
        max_key_chars=COMMAND_REPLY_MAX_JSON_KEY_CHARS,
        max_integer_digits=COMMAND_REPLY_MAX_INTEGER_DIGITS,
    )
    wire = json.dumps(
        envelope,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    if len(wire) > MAX_COMMAND_REPLY_SIZE:
        raise ValueError("command reply exceeds maximum size")
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
MAX_COMMAND_REPLY_SIZE = COMMAND_REPLY_MAX_WIRE_BYTES
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
        "launcher_shutdown",
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

    def __init__(
        self,
        address: str = DEFAULT_PUB_ADDR,
        *,
        topic: bytes = DEFAULT_TOPIC,
        applied_cold_stage_channel: str | None = None,
    ) -> None:
        self._address = address
        if topic != DEFAULT_TOPIC:
            # AT CONSTRUCTION, WHERE IT IS LOUD. The queue-backed path sends msgpack
            # readings on ``self._topic``, so the only topic a queue-backed publisher may
            # take is DEFAULT_TOPIC -- the dedicated event and barrier methods select
            # their own sequenced topics, and a reading misrouted onto either would be
            # parsed as that frame type downstream, invalidating the live generation
            # while the send reports success.
            #
            # The per-send guard below is not enough, because reaching it costs data:
            # `_publish_loop` catches whatever `_publish_reading` raises and still calls
            # `queue.task_done()`, so a misrouted publisher would drain its queue while
            # sending nothing -- silent loss of every reading, with the publisher still
            # reporting itself alive.
            #
            # This is a wiring mistake, not an operator action, so there is nobody to guide
            # through it; the honest answer is to refuse the object rather than the data.
            raise ValueError("publisher topic must be the default reading topic this transport's subscribers follow")
        self._topic = topic
        self._ctx: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._total_sent: int = 0
        self._queue: asyncio.Queue[Any] | None = None
        self._session_id: str | None = None
        self._sequence = 0
        self._publish_failure_count = 0
        self._send_lock = asyncio.Lock()
        self._reading_drop_count: Callable[[], int] | None = None
        self._alarm_snapshot: Callable[[], Any] | None = None
        self._applied_cold_stage_channel: str | None = None
        if applied_cold_stage_channel is not None:
            self.configure_applied_cold_stage_channel(applied_cold_stage_channel)

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

    def configure_applied_cold_stage_channel(self, channel: str) -> None:
        """Bind the publisher to the cold-stage slot selected by its runtime."""
        if self._running or self._session_id is not None:
            raise RuntimeError("applied cold-stage channel must be configured before publisher start")
        if type(channel) is not str or not channel.strip():
            raise ValueError("applied cold-stage channel must be a non-empty string")
        self._applied_cold_stage_channel = channel.strip()

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
        if topic not in _SEQUENCED_TOPICS:
            # Refused BEFORE the counter moves, so a refusal costs nothing and leaves no
            # gap behind. See _SEQUENCED_TOPICS for why a gap is not a cosmetic problem.
            raise ValueError("only sequenced topics may consume the shared sequence")
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
        if self._applied_cold_stage_channel is not None:
            metadata["engine_applied"] = {"cooldown": {"channel_cold": self._applied_cold_stage_channel}}
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

    async def _publish_loop(self, queue: asyncio.Queue[Any]) -> None:
        while self._running:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            required = item if type(item) is RequiredPublication else None
            try:
                # F35 D4: the zmq_publisher subscription opts in to
                # DataBroker's descriptor-envelope companion, so this queue
                # carries PublishedReading pairs instead of bare Reading.
                if required is not None:
                    await self._publish_reading(required.claim())
                    required.acknowledge()
                elif type(item) is PublishedReading:
                    await self._publish_reading(item.reading, descriptor_envelope=item.descriptor_envelope)
                else:
                    await self._publish_reading(item)
            except asyncio.CancelledError:
                if required is not None:
                    required.reject()
                raise
            except Exception:
                if required is not None:
                    required.reject()
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
        queue: asyncio.Queue[Any],
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

    async def start(self, queue: asyncio.Queue[Any]) -> None:
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

        queue = self._queue
        if queue is not None:
            while True:
                try:
                    queued = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                try:
                    if type(queued) is RequiredPublication:
                        queued.reject()
                finally:
                    queue.task_done()

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


class CommandAuthorityRegistry:
    """Engine-scoped quarantine shared by every command REP endpoint.

    A second REP socket is an independent transport lane, not an independent
    mutation authority. Servers for one engine incarnation must therefore use
    the same registry so uncertainty on either endpoint quarantines both.
    """

    def __init__(self) -> None:
        self._uncertain_authority_tasks: set[asyncio.Task[Any]] = set()
        self._uncertain_authority_latched = False

    @property
    def uncertain_tasks(self) -> set[asyncio.Task[Any]]:
        return self._uncertain_authority_tasks

    @property
    def latched(self) -> bool:
        return self._uncertain_authority_latched

    @latched.setter
    def latched(self, value: bool) -> None:
        self._uncertain_authority_latched = bool(value)

    def has_uncertain_authority(self) -> bool:
        # A terminal task remains uncertain until its owning server observes
        # and removes it. This closes the callback-scheduling race between two
        # independent REP loops sharing the same engine authority.
        return self._uncertain_authority_latched or bool(self._uncertain_authority_tasks)


class ZMQCommandServerOwnershipConflict(RuntimeError):
    """A start attempt proved the runtime was already owned before mutation."""


@dataclass(frozen=True, slots=True)
class ZMQCommandServerTerminalFailure:
    """Sanitized proof that one REP owner cannot recover its serve loop."""

    stage: Literal["loop_closed", "recovery_task_create_failed", "recovery_exhausted"]
    failure_type: str


@dataclass(frozen=True, slots=True)
class ZMQCommandIngressTerminalFailure:
    """First terminal failure across the ordinary and safe REP owners."""

    endpoint: Literal["safe", "ordinary"]
    stage: Literal["loop_closed", "recovery_task_create_failed", "recovery_exhausted"]
    failure_type: str


class ZMQCommandIngressTerminalError(RuntimeError):
    """One command-ingress endpoint lost its terminal runtime authority."""

    def __init__(self, failure: ZMQCommandIngressTerminalFailure) -> None:
        self.failure = failure
        super().__init__(
            "ZMQ command ingress terminated: "
            f"endpoint={failure.endpoint}; stage={failure.stage}; failure={failure.failure_type}"
        )


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
        reply_sent_callback: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
        authority_registry: CommandAuthorityRegistry | None = None,
        accepted_actions: frozenset[str] | None = None,
        accepted_command_predicate: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        if not isinstance(server_label, str) or server_label not in _SERVER_LABELS:
            allowed = ", ".join(sorted(_SERVER_LABELS))
            raise ValueError(f"server_label must be one of: {allowed}")
        self._address = address
        self._handler = handler
        self._server_role = server_label
        self._reply_sent_callback = reply_sent_callback
        self._authority_registry = authority_registry if authority_registry is not None else CommandAuthorityRegistry()
        if accepted_actions is not None and (
            type(accepted_actions) is not frozenset
            or any(type(action) is not str or not action for action in accepted_actions)
        ):
            raise ValueError("accepted_actions must be an exact frozenset of non-empty strings")
        if accepted_command_predicate is not None and not callable(accepted_command_predicate):
            raise TypeError("accepted_command_predicate must be callable")
        self._accepted_actions = accepted_actions
        self._accepted_command_predicate = accepted_command_predicate
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
        self._handler_actions: dict[asyncio.Task[Any], str] = {}
        # Backwards-compatible inspection surface. The set is intentionally
        # shared when two servers receive the same authority registry.
        self._uncertain_authority_tasks = self._authority_registry.uncertain_tasks
        self._running = False
        self._shutdown_requested = False
        self._terminal_failure: ZMQCommandServerTerminalFailure | None = None
        self._terminal_failure_event = asyncio.Event()
        self._terminal_failure_notifier: Callable[[ZMQCommandServerTerminalFailure], None] | None = None

    @property
    def _uncertain_authority_latched(self) -> bool:
        return self._authority_registry.latched

    @_uncertain_authority_latched.setter
    def _uncertain_authority_latched(self, value: bool) -> None:
        self._authority_registry.latched = value

    def _command_is_accepted(self, cmd: dict[str, Any]) -> bool:
        actions = self._accepted_actions
        if actions is not None:
            action = cmd.get("cmd")
            if type(action) is not str or action not in actions:
                return False
        predicate = self._accepted_command_predicate
        if predicate is None:
            return True
        try:
            return predicate(cmd) is True
        except Exception:
            return False

    @property
    def terminal_failure(self) -> ZMQCommandServerTerminalFailure | None:
        """Return sticky sanitized terminal proof without consuming it."""

        return self._terminal_failure

    def terminal_failure_notifier_state_is_pristine(self) -> bool:
        """Prove notifier ownership without changing the notifier slot."""

        return self._terminal_failure_notifier is None

    def bind_terminal_failure_notifier(
        self,
        notifier: Callable[[ZMQCommandServerTerminalFailure], None],
    ) -> None:
        """Bind the one composite lifecycle owner before this server starts."""

        if not callable(notifier):
            raise TypeError("terminal failure notifier must be callable")
        if self._terminal_failure_notifier is not None and self._terminal_failure_notifier is not notifier:
            raise RuntimeError("terminal failure notifier is already bound")
        self._terminal_failure_notifier = notifier
        failure = self._terminal_failure
        if failure is not None:
            notifier(failure)

    def unbind_terminal_failure_notifier(
        self,
        notifier: Callable[[ZMQCommandServerTerminalFailure], None],
    ) -> None:
        """Undo an exact constructor-time binding without disturbing another owner."""

        if not callable(notifier):
            raise TypeError("terminal failure notifier must be callable")
        current = self._terminal_failure_notifier
        if current is notifier:
            self._terminal_failure_notifier = None
            return
        if current is None:
            return
        raise RuntimeError("terminal failure notifier changed before constructor rollback")

    async def wait_terminal_failure(self) -> ZMQCommandServerTerminalFailure:
        """Wait for sticky terminal proof; waiter cancellation never clears it."""

        failure = self._terminal_failure
        if failure is None:
            await self._terminal_failure_event.wait()
            failure = self._terminal_failure
        if failure is None:
            raise RuntimeError("terminal failure event was set without terminal proof")
        return failure

    def _latch_terminal_failure(
        self,
        *,
        stage: Literal["loop_closed", "recovery_task_create_failed", "recovery_exhausted"],
        failure_type: str,
    ) -> None:
        """Freeze admission and publish the first sanitized terminal proof."""

        if self._terminal_failure is not None:
            return
        sanitized_type = (
            failure_type
            if type(failure_type) is str
            and 0 < len(failure_type) <= 64
            and failure_type.isascii()
            and all(char.isalnum() or char == "_" for char in failure_type)
            else "Exception"
        )
        failure = ZMQCommandServerTerminalFailure(stage=stage, failure_type=sanitized_type)
        self._terminal_failure = failure
        # Close this endpoint even when it has no composite owner. The bound
        # pair notifier below performs the observable safe-then-ordinary freeze
        # exactly once, without a duplicate callback on the failed endpoint.
        self._shutdown_requested = True
        self._running = False
        try:
            notifier = self._terminal_failure_notifier
            if notifier is not None:
                notifier(failure)
        except BaseException as exc:
            logger.error(
                "ZMQCommandServer terminal notifier failed: exception=%s",
                type(exc).__name__,
            )
        finally:
            self._terminal_failure_event.set()

    def _start_serve_task(self) -> None:
        """Spawn the command loop exactly once while the server is running."""
        if not self._running or self._shutdown_requested or self._terminal_failure is not None:
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

        registered_action = self._handler_actions.get(task)
        if registered_action is None:
            return
        action = registered_action
        was_uncertain = task in self._uncertain_authority_tasks
        terminal_unknown = False
        terminal_result: object = None
        try:
            if task.cancelled():
                terminal_unknown = was_uncertain
            else:
                terminal_result = task.result()
                if was_uncertain:
                    terminal_unknown = not _late_handler_reply_proves_terminal_settlement(terminal_result)
                    if not terminal_unknown:
                        try:
                            wire = self._encode_reply(terminal_result)
                            decoded = json.loads(wire.decode("utf-8"))
                            terminal_unknown = type(decoded) is not dict
                        except Exception:
                            terminal_unknown = True
        except asyncio.CancelledError:
            terminal_unknown = was_uncertain
        except BaseException as exc:
            terminal_unknown = was_uncertain
            logger.error(
                "ZMQ detached command handler failed: action=%s exception=%s",
                action,
                type(exc).__name__,
            )
        if terminal_unknown:
            # Set the durable latch before releasing the task-set owner so the
            # two shared REP endpoints never observe an authority gap.
            self._uncertain_authority_latched = True
        self._handler_tasks.discard(task)
        self._uncertain_authority_tasks.discard(task)
        self._handler_actions.pop(task, None)
        if not terminal_unknown and terminal_result is not None:
            logger.warning(
                "ZMQ detached command handler settled after reply: action=%s",
                action,
            )

    def _prune_handler_tasks(self) -> None:
        """Drop terminal owners after consuming their outcome."""

        for task in tuple(self._handler_tasks):
            if not task.done():
                continue
            self._observe_handler_task(
                task,
                action=self._handler_actions.get(task, "unknown"),
            )

    def _has_uncertain_authority_owner(self) -> bool:
        """Return whether a prior non-read handler can still change state."""

        self._prune_handler_tasks()
        return self._authority_registry.has_uncertain_authority()

    def _record_dispatched_unknown(self, trace: _HandlerDispatchTrace) -> None:
        """Latch only a non-read application dispatch with no terminal proof."""

        task = trace.task
        if task is None or trace.command_class is CommandClass.READ:
            return
        if task in self._uncertain_authority_tasks:
            # A timed-out task is a resolvable owner. Its late terminal reply
            # decides whether quarantine can clear; do not make that temporary
            # task-set owner permanently sticky here.
            return
        self._uncertain_authority_latched = True

    @staticmethod
    def _is_exact_quarantine_safe_direction(cmd: dict[str, Any]) -> bool:
        """Recognize only exact safe-direction envelopes during quarantine."""

        return is_quarantine_bypass_safe_direction(cmd)

    def _detach_handler_task(
        self,
        task: asyncio.Task[Any],
        *,
        action: str,
        command_class: CommandClass,
    ) -> None:
        """Detach a timed-out owner without releasing mutation authority."""

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

    async def _settle_handler_tasks(self) -> None:
        """Cancel and terminally settle every detached command owner.

        A cancellation-resistant handler intentionally holds shutdown here.  The
        REP socket and its context remain owned until no handler can commit late.
        """

        current = asyncio.current_task()
        self._prune_handler_tasks()
        tasks = tuple(task for task in self._handler_tasks if task is not current)
        if current in self._handler_tasks:
            raise RuntimeError("ZMQ command handler cannot synchronously stop its own server")
        for task in tasks:
            if task not in self._uncertain_authority_tasks:
                task.cancel()
        if tasks:

            async def _settle() -> None:
                await asyncio.gather(*tasks, return_exceptions=True)

            settlement = asyncio.create_task(_settle(), name="zmq-command-handler-settlement")
            cancellation_seen = False
            while not settlement.done():
                try:
                    await asyncio.shield(settlement)
                except asyncio.CancelledError:
                    cancellation_seen = True
            settlement.result()
            self._prune_handler_tasks()
            if cancellation_seen:
                raise asyncio.CancelledError
        self._prune_handler_tasks()

    def _startup_state_is_pristine(self) -> bool:
        """Return whether ``start`` can acquire a fresh runtime ownership set."""

        self._prune_handler_tasks()
        return (
            not self._running
            and self._ctx is None
            and self._socket is None
            and self._task is None
            and self._restart_task is None
            and not self._handler_tasks
            and self._terminal_failure is None
        )

    def startup_state_is_pristine(self) -> bool:
        """Expose a read-only ownership proof to a composite lifecycle owner."""

        return self._startup_state_is_pristine()

    async def _cleanup_owned_runtime(self) -> None:
        """Settle owned resources, clearing only owners proven terminal."""

        first_error: BaseException | None = None

        def record(error: BaseException) -> None:
            nonlocal first_error
            if first_error is None:
                first_error = error

        for attribute in ("_task", "_restart_task"):
            task = getattr(self, attribute)
            if task is None:
                continue
            try:
                task.cancel()
                await task
            except asyncio.CancelledError:
                pass
            except BaseException as exc:
                record(exc)
            finally:
                if task.done() and getattr(self, attribute) is task:
                    setattr(self, attribute, None)

        handlers_settled = False
        try:
            await self._settle_handler_tasks()
        except BaseException as exc:
            record(exc)
        else:
            handlers_settled = True

        # A handler that has not settled can still commit through the bound REP
        # authority. Retain the complete transport owner set for an explicit
        # retry instead of manufacturing a clean-looking partial shutdown.
        if handlers_settled:
            socket = self._socket
            if socket is not None:
                try:
                    socket.close(linger=0)
                except BaseException as exc:
                    record(exc)
                else:
                    if self._socket is socket:
                        self._socket = None

            # ``Context.term`` may wait on a live socket. Only attempt it after
            # socket settlement is proven; otherwise retain both exact owners.
            context = self._ctx
            if self._socket is None and context is not None:
                try:
                    context.term()
                except BaseException as exc:
                    record(exc)
                else:
                    if self._ctx is context:
                        self._ctx = None

        if first_error is not None:
            raise first_error

    async def _run_cleanup_resisting_cancellation(
        self,
        *,
        task_name: str,
    ) -> tuple[asyncio.CancelledError | None, BaseException | None]:
        """Finish cleanup before returning caller cancellation or failure."""

        cleanup_task = asyncio.create_task(
            self._cleanup_owned_runtime(),
            name=task_name,
        )
        caller_cancellation: asyncio.CancelledError | None = None
        cleanup_error: BaseException | None = None
        while not cleanup_task.done():
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError as exc:
                caller_cancellation = exc
            except BaseException as exc:
                cleanup_error = exc
                break
        if cleanup_task.done() and cleanup_error is None:
            try:
                cleanup_task.result()
            except BaseException as exc:
                cleanup_error = exc
        return caller_cancellation, cleanup_error

    async def _open_bound_socket(self) -> zmq.asyncio.Socket:
        """Create and bind a fresh REP socket with the full boundary policy."""

        if self._ctx is None:
            raise RuntimeError("ZMQ command context is not available")
        if self._socket is not None:
            raise RuntimeError("ZMQ command socket ownership is not pristine")
        socket = self._ctx.socket(zmq.REP)
        self._socket = socket
        try:
            socket.setsockopt(zmq.LINGER, 0)
            socket.setsockopt(zmq.MAXMSGSIZE, MAX_CMD_MSG_SIZE)
            await _bind_with_retry(socket, self._address)
        except BaseException as acquisition_error:
            try:
                socket.close(linger=0)
            except BaseException as close_error:
                raise RuntimeError(
                    "ZMQ command socket acquisition rollback failed: "
                    f"acquisition={type(acquisition_error).__name__}; "
                    f"close={type(close_error).__name__}"
                ) from acquisition_error
            if self._socket is socket:
                self._socket = None
            raise
        return socket

    async def _restart_after_unexpected_exit(self) -> None:
        """Replace a possibly poisoned REP socket before restarting its loop."""

        current = asyncio.current_task()
        try:
            if self._terminal_failure is not None:
                return
            old_socket = self._socket
            if old_socket is not None:
                old_socket.close(linger=0)
                if self._socket is old_socket:
                    self._socket = None
            if self._shutdown_requested or not self._running:
                return
            await self._open_bound_socket()
            if self._shutdown_requested or not self._running:
                replacement = self._socket
                if replacement is not None:
                    replacement.close(linger=0)
                    if self._socket is replacement:
                        self._socket = None
                return
            # Release recovery ownership before the replacement task can run.
            # If that task exits immediately, its done callback must be able to
            # schedule a second socket replacement rather than observe this
            # almost-finished recovery task and leave the server ownerless.
            if self._restart_task is current:
                self._restart_task = None
            try:
                self._start_serve_task()
            except Exception as create_error:
                logger.error(
                    "ZMQCommandServer recovery serve-task creation failed: exception=%s",
                    type(create_error).__name__,
                )
                self._latch_terminal_failure(
                    stage="recovery_task_create_failed",
                    failure_type=type(create_error).__name__,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "ZMQCommandServer socket recovery failed: exception=%s",
                type(exc).__name__,
            )
            self._latch_terminal_failure(
                stage="recovery_exhausted",
                failure_type=type(exc).__name__,
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
        if self._shutdown_requested or not self._running or self._terminal_failure is not None:
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
            self._latch_terminal_failure(
                stage="loop_closed",
                failure_type="RuntimeError",
            )
            return
        if self._restart_task is None or self._restart_task.done():
            recovery = self._restart_after_unexpected_exit()
            try:
                self._restart_task = loop.create_task(
                    recovery,
                    name="zmq_cmd_server_recover",
                )
            except Exception as create_error:
                recovery.close()
                logger.error(
                    "ZMQCommandServer recovery task creation failed: exception=%s",
                    type(create_error).__name__,
                )
                self._latch_terminal_failure(
                    stage="recovery_task_create_failed",
                    failure_type=type(create_error).__name__,
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

        if not self._command_is_accepted(cmd):
            return {
                "ok": False,
                "error_code": "command_endpoint_action_rejected",
                "error": "Command is not admitted by this endpoint.",
                "delivery_state": "not_dispatched",
                "commit_state": "not_committed",
                "retry_safe": False,
            }

        # Answer discovery before application dispatch so it remains available
        # even if no command handler is configured, but only when this endpoint
        # explicitly admits the discovery action.
        if cmd.get("cmd") == "protocol_version":
            return {
                "ok": True,
                "proto": PROTOCOL_VERSION,
                "server": self._server_label(),
                "app_version": _APP_VERSION,
            }

        if self._handler is None:
            return {"ok": False, "error": "no handler"}

        raw_action = cmd.get("cmd")
        action = _bounded_action_label(raw_action)
        command_class = classify_engine_command(raw_action)
        if self._has_uncertain_authority_owner() and not (
            command_class is CommandClass.READ or self._is_exact_quarantine_safe_direction(cmd)
        ):
            return {
                "ok": False,
                "error_code": "command_authority_quarantined",
                "error": "A prior command outcome is still uncertain; mutation is quarantined.",
                "delivery_state": "not_dispatched",
                "commit_state": "not_committed",
                "retry_safe": False,
            }
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
        dispatch_trace = _HANDLER_DISPATCH_TRACE.get()
        if dispatch_trace is not None and dispatch_trace.task is None:
            dispatch_trace.task = handler_task
            dispatch_trace.command_class = command_class
        self._handler_tasks.add(handler_task)
        self._handler_actions[handler_task] = action
        try:
            done, _pending = await asyncio.wait({handler_task}, timeout=timeout)
        except asyncio.CancelledError:
            self._detach_handler_task(
                handler_task,
                action=action,
                command_class=command_class,
            )
            raise

        if not done:
            self._detach_handler_task(
                handler_task,
                action=action,
                command_class=command_class,
            )
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
        self._handler_actions.pop(handler_task, None)
        try:
            result = handler_task.result()
        except TimeoutError:
            if command_class is not CommandClass.READ:
                self._uncertain_authority_latched = True
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
            if command_class is not CommandClass.READ:
                self._uncertain_authority_latched = True
            logger.error("ZMQ command handler cancelled itself: action=%s", action)
            return _post_dispatch_failure(
                raw_action,
                error_code="command_handler_cancelled",
                error="Command handler was cancelled; outcome may be unknown.",
            )
        except Exception as exc:
            if command_class is not CommandClass.READ:
                self._uncertain_authority_latched = True
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
            if command_class is not CommandClass.READ and _handler_reply_outcome_is_unknown(result):
                self._uncertain_authority_latched = True
            return result
        if command_class is not CommandClass.READ:
            self._uncertain_authority_latched = True
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

            # ``freeze_admission`` is synchronous. It may run after poll/recv
            # became ready but before this task resumed; never dispatch that
            # already-received command after shutdown authority was frozen.
            if self._shutdown_requested or not self._running:
                return

            # Exactly one send attempt follows each successful recv. If that
            # attempt fails or is cancelled, the REP state is unknowable and
            # the task exits so its supervisor replaces the socket.
            cmd: Any = None
            dispatch_trace = _HandlerDispatchTrace()
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
                raw_action = cmd.get("cmd") if type(cmd) is dict else None
                trace_token = _HANDLER_DISPATCH_TRACE.set(dispatch_trace)
                try:
                    reply = await self._run_handler(cmd)
                except asyncio.CancelledError:
                    self._record_dispatched_unknown(dispatch_trace)
                    raise
                except Exception as exc:
                    self._record_dispatched_unknown(dispatch_trace)
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
                finally:
                    _HANDLER_DISPATCH_TRACE.reset(trace_token)

            try:
                wire = self._encode_reply(reply)
            except Exception as exc:
                self._record_dispatched_unknown(dispatch_trace)
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

            sent_reply: dict[str, Any] | None = None
            try:
                decoded_wire = json.loads(wire.decode("utf-8"))
                if type(decoded_wire) is dict:
                    sent_reply = decoded_wire
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                sent_reply = None
            if sent_reply is None:
                self._record_dispatched_unknown(dispatch_trace)

            try:
                await socket.send(wire)
            except asyncio.CancelledError:
                self._record_dispatched_unknown(dispatch_trace)
                raise
            except Exception as exc:
                self._record_dispatched_unknown(dispatch_trace)
                logger.error(
                    "ZMQ command reply send failed: action=%s exception=%s",
                    _bounded_action_label(raw_action),
                    type(exc).__name__,
                )
                raise
            callback = self._reply_sent_callback
            if callback is not None and isinstance(cmd, dict) and sent_reply is not None:
                try:
                    callback_result = callback(cmd, sent_reply)
                    if asyncio.iscoroutine(callback_result):
                        await callback_result
                except Exception as exc:
                    logger.error(
                        "ZMQ command post-reply callback failed: action=%s exception=%s",
                        _bounded_action_label(raw_action),
                        type(exc).__name__,
                    )
                    raise

    async def start(self) -> None:
        if not self._startup_state_is_pristine():
            raise ZMQCommandServerOwnershipConflict(
                "ZMQCommandServer start state is not pristine; stop or retry failed cleanup before starting again"
            )

        self._shutdown_requested = False
        try:
            context = zmq.asyncio.Context()
            self._ctx = context
            socket = await self._open_bound_socket()
            if self._socket is None:
                # Preserve compatibility with injected socket factories while
                # making the returned owner explicit before admission opens.
                self._socket = socket
            elif self._socket is not socket:
                raise RuntimeError("ZMQCommandServer socket owner changed during startup")
            self._running = True
            self._start_serve_task()
        except BaseException as start_error:
            self.freeze_admission()
            _caller_cancellation, cleanup_error = await self._run_cleanup_resisting_cancellation(
                task_name="zmq-command-server-startup-rollback",
            )
            if cleanup_error is not None:
                raise RuntimeError(
                    "ZMQCommandServer startup rollback incomplete: "
                    f"start={type(start_error).__name__}; "
                    f"cleanup={type(cleanup_error).__name__}"
                ) from cleanup_error
            raise
        logger.info("ZMQCommandServer запущен: %s", self._address)

    def freeze_admission(self) -> None:
        """Synchronously prevent any newly received command from dispatching."""

        self._shutdown_requested = True
        self._running = False

    async def stop(self) -> None:
        self.freeze_admission()
        caller_cancellation, cleanup_error = await self._run_cleanup_resisting_cancellation(
            task_name="zmq-command-server-cleanup",
        )
        if cleanup_error is not None:
            raise cleanup_error
        logger.info("ZMQCommandServer остановлен")
        if caller_cancellation is not None:
            raise caller_cancellation


class ZMQCommandIngressPair:
    """One lifecycle owner for ordinary and dedicated-safe REP endpoints."""

    _OWNER_ORDER = ("safe", "ordinary")

    def __init__(self, *, ordinary: Any, safe: Any) -> None:
        if ordinary is safe:
            raise ValueError("ordinary and safe command ingress owners must be distinct")
        missing = object()
        ordinary_registry = getattr(ordinary, "_authority_registry", missing)
        safe_registry = getattr(safe, "_authority_registry", missing)
        if (ordinary_registry is not missing or safe_registry is not missing) and (
            ordinary_registry is missing or safe_registry is missing or ordinary_registry is not safe_registry
        ):
            raise ValueError("ordinary and safe command ingress must share one authority registry")
        ordinary_address = getattr(ordinary, "_address", missing)
        safe_address = getattr(safe, "_address", missing)
        if ordinary_address is not missing or safe_address is not missing:
            if ordinary_address is missing or safe_address is missing:
                raise ValueError("ordinary and safe production ingress must both expose endpoint identity")
            require_distinct_loopback_tcp_endpoints(
                ordinary_command=ordinary_address,
                safe_command=safe_address,
            )

        self._ordinary = ordinary
        self._safe = safe
        self._owned_labels: set[str] = set()
        self._starting = False
        self._stop_task: asyncio.Task[None] | None = None
        self._terminal_failure: ZMQCommandIngressTerminalFailure | None = None
        self._terminal_failure_event = asyncio.Event()
        self._terminal_failure_notifiers: dict[
            str,
            Callable[[ZMQCommandServerTerminalFailure], None],
        ] = {
            "safe": lambda failure: self._on_child_terminal_failure("safe", failure),
            "ordinary": lambda failure: self._on_child_terminal_failure("ordinary", failure),
        }

        existing_failures = {
            label: getattr(self._owner(label), "terminal_failure", None) for label in self._OWNER_ORDER
        }
        failed_labels = [label for label in self._OWNER_ORDER if existing_failures[label] is not None]
        if failed_labels:
            raise ZMQCommandServerOwnershipConflict(
                "ZMQ command ingress child is terminal before pair ownership: " + ",".join(failed_labels)
            )

        binders = {
            label: getattr(self._owner(label), "bind_terminal_failure_notifier", None) for label in self._OWNER_ORDER
        }
        production_children = ordinary_registry is not missing
        if production_children:
            self._require_production_children_constructor_pristine()
        if any(binder is not None for binder in binders.values()):
            if any(not callable(binder) for binder in binders.values()):
                raise ValueError("ordinary and safe ingress must both expose terminal failure notification")
            pristine_probes = {
                label: getattr(
                    self._owner(label),
                    "terminal_failure_notifier_state_is_pristine",
                    None,
                )
                for label in self._OWNER_ORDER
            }
            if any(not callable(probe) for probe in pristine_probes.values()):
                raise RuntimeError("ordinary and safe ingress must both expose terminal notifier pristine-state proof")
            unbinders = {
                label: getattr(
                    self._owner(label),
                    "unbind_terminal_failure_notifier",
                    None,
                )
                for label in self._OWNER_ORDER
            }
            if any(not callable(unbinder) for unbinder in unbinders.values()):
                raise RuntimeError("ordinary and safe ingress must both expose exact terminal notifier rollback")
            self._require_notifier_slots_constructor_pristine(pristine_probes)
            attempted_labels: list[str] = []
            try:
                for label in self._OWNER_ORDER:
                    binder = binders[label]
                    assert callable(binder)
                    attempted_labels.append(label)
                    binder(self._terminal_failure_notifiers[label])
                newly_failed_labels = [
                    label
                    for label in self._OWNER_ORDER
                    if getattr(self._owner(label), "terminal_failure", None) is not None
                ]
                if newly_failed_labels or self._terminal_failure is not None:
                    raise ZMQCommandServerOwnershipConflict(
                        "ZMQ command ingress child became terminal during pair ownership: "
                        + ",".join(newly_failed_labels)
                    )
            except BaseException as bind_error:
                rollback_errors: list[tuple[str, BaseException]] = []
                for label in reversed(attempted_labels):
                    unbinder = unbinders[label]
                    assert callable(unbinder)
                    try:
                        unbind_result = unbinder(self._terminal_failure_notifiers[label])
                        if unbind_result is not None:
                            raise RuntimeError(f"ZMQ command ingress {label} terminal notifier unbind was not exact")
                    except BaseException as exc:
                        rollback_errors.append((label, exc))
                for label in attempted_labels:
                    probe = pristine_probes[label]
                    assert callable(probe)
                    try:
                        pristine = probe()
                    except BaseException as exc:
                        rollback_errors.append((label, exc))
                        continue
                    if pristine is not True:
                        rollback_errors.append(
                            (
                                label,
                                RuntimeError(f"ZMQ command ingress {label} terminal notifier remains owned"),
                            )
                        )
                if rollback_errors:
                    rollback_labels = ",".join(label for label, _error in rollback_errors)
                    first_rollback_error = rollback_errors[0][1]
                    raise RuntimeError(
                        "ZMQ command ingress notifier binding rollback incomplete; ownership remains in HOLD: "
                        f"bind={type(bind_error).__name__}; "
                        f"rollback={type(first_rollback_error).__name__}; "
                        f"owners={rollback_labels}"
                    ) from first_rollback_error
                raise

    def _owner(self, label: str) -> Any:
        return self._safe if label == "safe" else self._ordinary

    @property
    def terminal_failure(self) -> ZMQCommandIngressTerminalFailure | None:
        """Return the first sticky endpoint failure without consuming it."""

        return self._terminal_failure

    def _require_production_children_constructor_pristine(self) -> None:
        """Prove both production runtimes before binding either child."""

        for label in self._OWNER_ORDER:
            owner = self._owner(label)
            probe = getattr(owner, "startup_state_is_pristine", None)
            if not callable(probe):
                raise RuntimeError(f"ZMQ command ingress {label} startup_state_is_pristine proof is not callable")
            try:
                pristine = probe()
            except BaseException as exc:
                raise RuntimeError(f"ZMQ command ingress {label} startup_state_is_pristine proof failed") from exc
            if pristine is not True:
                raise ZMQCommandServerOwnershipConflict(
                    f"ZMQ command ingress {label} runtime is already owned outside this pair"
                )

    def _require_notifier_slots_constructor_pristine(
        self,
        probes: dict[str, Callable[[], Any]],
    ) -> None:
        """Preflight both notifier slots before either child is mutated."""

        proof_errors: list[tuple[str, BaseException]] = []
        conflicts: list[str] = []
        for label in self._OWNER_ORDER:
            probe = probes[label]
            try:
                pristine = probe()
            except BaseException as exc:
                proof_errors.append((label, exc))
                continue
            if pristine is not True:
                conflicts.append(label)
        if proof_errors:
            label, error = proof_errors[0]
            raise RuntimeError(f"ZMQ command ingress {label} terminal notifier pristine-state proof failed") from error
        if conflicts:
            raise ZMQCommandServerOwnershipConflict(
                "ZMQ command ingress terminal notifier is already owned outside this pair: " + ",".join(conflicts)
            )

    def _on_child_terminal_failure(
        self,
        label: str,
        failure: ZMQCommandServerTerminalFailure,
    ) -> None:
        """Synchronously close both admissions before waking runtime owners."""

        if self._terminal_failure is not None:
            return
        endpoint: Literal["safe", "ordinary"] = "safe" if label == "safe" else "ordinary"
        self._terminal_failure = ZMQCommandIngressTerminalFailure(
            endpoint=endpoint,
            stage=failure.stage,
            failure_type=failure.failure_type,
        )
        try:
            # Only pair-owned children may be frozen. During safe-first startup
            # this deliberately excludes the not-yet-owned ordinary endpoint;
            # require_healthy() prevents it from ever being started afterward.
            freeze_error = self._freeze_labels(set(self._owned_labels))
            if freeze_error is not None:
                logger.error(
                    "ZMQ command ingress terminal freeze failed: endpoint=%s exception=%s",
                    endpoint,
                    type(freeze_error).__name__,
                )
        finally:
            self._terminal_failure_event.set()

    async def wait_terminal_failure(self) -> ZMQCommandIngressTerminalFailure:
        """Wait for sticky pair failure; cancellation cannot consume the latch."""

        failure = self._terminal_failure
        if failure is None:
            await self._terminal_failure_event.wait()
            failure = self._terminal_failure
        if failure is None:
            raise RuntimeError("terminal failure event was set without terminal proof")
        return failure

    def require_healthy(self) -> None:
        """Reject readiness or restart after either endpoint became terminal."""

        failure = self._terminal_failure
        if failure is not None:
            raise ZMQCommandIngressTerminalError(failure)

    def _require_children_pristine(self) -> None:
        """Reject known foreign runtime owners before claiming either child."""

        for label in self._OWNER_ORDER:
            owner = self._owner(label)
            probe = getattr(owner, "startup_state_is_pristine", None)
            if probe is None:
                # Minimal injected owners use the typed start-conflict contract
                # below. Production ZMQCommandServer owners expose the proof.
                continue
            if not callable(probe):
                raise RuntimeError(f"ZMQ command ingress {label} pristine-state proof is not callable")
            try:
                pristine = probe()
            except BaseException as exc:
                raise RuntimeError(f"ZMQ command ingress {label} pristine-state proof failed") from exc
            if pristine is not True:
                raise ZMQCommandServerOwnershipConflict(
                    f"ZMQ command ingress {label} runtime is already owned outside this pair"
                )

    def _freeze_labels(self, labels: set[str]) -> BaseException | None:
        first_error: BaseException | None = None
        for label in self._OWNER_ORDER:
            if label not in labels:
                continue
            try:
                self._owner(label).freeze_admission()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        return first_error

    def freeze_admission(self) -> None:
        """Synchronously freeze safe and ordinary admission, in that order."""

        first_error = self._freeze_labels(set(self._OWNER_ORDER))
        if first_error is not None:
            raise first_error

    async def _stop_owned_once(self) -> None:
        labels = tuple(label for label in self._OWNER_ORDER if label in self._owned_labels)
        if not labels:
            return

        async def stop_one(label: str) -> None:
            await self._owner(label).stop()

        tasks = {
            label: asyncio.create_task(
                stop_one(label),
                name=f"zmq-command-ingress-{label}-stop",
            )
            for label in labels
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        first_error: BaseException | None = None
        for label, result in zip(tasks, results, strict=True):
            if isinstance(result, BaseException):
                if first_error is None:
                    first_error = result
                continue
            self._owned_labels.discard(label)
        if first_error is not None:
            raise first_error

    async def _settle_owned_resisting_cancellation(
        self,
    ) -> tuple[asyncio.CancelledError | None, BaseException | None]:
        stop_task = self._stop_task
        if stop_task is None:
            stop_task = asyncio.create_task(
                self._stop_owned_once(),
                name="zmq-command-ingress-pair-stop",
            )
            self._stop_task = stop_task

        caller_cancellation: asyncio.CancelledError | None = None
        cleanup_error: BaseException | None = None
        while not stop_task.done():
            try:
                await asyncio.shield(stop_task)
            except asyncio.CancelledError as exc:
                caller_cancellation = exc
            except BaseException as exc:
                cleanup_error = exc
                break
        if stop_task.done() and cleanup_error is None:
            try:
                stop_task.result()
            except BaseException as exc:
                cleanup_error = exc
        if self._stop_task is stop_task and stop_task.done():
            self._stop_task = None
        return caller_cancellation, cleanup_error

    async def start(self) -> None:
        """Start safe to completion before opening ordinary admission."""

        if self._starting or self._owned_labels or self._stop_task is not None or self._terminal_failure is not None:
            raise RuntimeError("ZMQ command ingress pair start requires pristine ownership")
        # Prove both production children are free before claiming either one;
        # otherwise rollback could stop a pre-existing foreign runtime.
        self._require_children_pristine()
        self._starting = True
        try:
            for label in self._OWNER_ORDER:
                # A start call that raises may still have acquired resources;
                # claim it before invocation so rollback cannot lose the owner.
                self._owned_labels.add(label)
                try:
                    await self._owner(label).start()
                except ZMQCommandServerOwnershipConflict:
                    # This typed failure is emitted before the owner's start
                    # mutates anything. It therefore proves the runtime is
                    # foreign; rollback must never freeze or stop it.
                    self._owned_labels.discard(label)
                    raise
                self.require_healthy()
        except BaseException as start_error:
            freeze_error = self._freeze_labels(set(self._owned_labels))
            _caller_cancellation, cleanup_error = await self._settle_owned_resisting_cancellation()
            if cleanup_error is not None or freeze_error is not None:
                rollback_error = cleanup_error if cleanup_error is not None else freeze_error
                assert rollback_error is not None
                raise RuntimeError(
                    "ZMQ command ingress pair startup rollback incomplete: "
                    f"start={type(start_error).__name__}; "
                    f"rollback={type(rollback_error).__name__}"
                ) from rollback_error
            raise
        finally:
            self._starting = False

    async def stop(self) -> None:
        """Freeze and concurrently settle both endpoints exactly once."""

        if self._starting:
            raise RuntimeError("ZMQ command ingress pair cannot stop during start")
        if not self._owned_labels and self._stop_task is None:
            return
        freeze_error = self._freeze_labels(set(self._owned_labels))
        caller_cancellation, cleanup_error = await self._settle_owned_resisting_cancellation()
        if cleanup_error is not None:
            raise cleanup_error
        if freeze_error is not None:
            raise freeze_error
        if caller_cancellation is not None:
            raise caller_cancellation
