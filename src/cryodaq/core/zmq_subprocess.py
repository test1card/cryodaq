"""ZMQ bridge running in a separate process.

This process owns ALL ZMQ sockets. If libzmq crashes (signaler.cpp
assertion on Windows), only this subprocess dies. The GUI detects
the death via is_alive() and restarts it.

The GUI process never imports zmq.

Threading model (see fix(gui): split bridge subprocess ...):
- sub_drain owns the SUB socket, receives readings, emits heartbeats.
  Heartbeat comes from this thread so it proves the *data* path is alive.
- cmd_forward owns ephemeral ordinary REQ sockets.
- safe_cmd_forward independently owns ephemeral targeted-OFF/global-OFF/
  launcher-shutdown REQ sockets. A blocked ordinary request cannot consume
  this lane.
- Main thread starts and terminally joins every owned thread.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import multiprocessing as mp
import queue
import threading
import time
from typing import Any

from cryodaq.channels.persistence import MAX_PERSISTED_ENVELOPE_BYTES
from cryodaq.core.command_authority import (
    SAFE_DIRECTION_ACTIONS,
    exact_safe_direction_kind,
    is_preemptive_safe_direction,
)
from cryodaq.core.command_reply_contract import (
    COMMAND_REPLY_MAX_INTEGER_DIGITS,
    COMMAND_REPLY_MAX_JSON_DEPTH,
    COMMAND_REPLY_MAX_JSON_ITEMS,
    COMMAND_REPLY_MAX_JSON_KEY_CHARS,
    COMMAND_REPLY_MAX_WIRE_BYTES,
    validate_command_reply_structure,
)
from cryodaq.core.operator_snapshot_ingress import (
    OperatorSnapshotQueueIngress,
    SnapshotIngressOrderingError,
    SnapshotIngressQueueError,
)
from cryodaq.core.safe_command_ipc import DirectionalPipeReceiver, DirectionalPipeSender
from cryodaq.core.zmq_endpoints import require_distinct_loopback_tcp_endpoints
from cryodaq.operator_snapshot import SnapshotMode
from cryodaq.operator_snapshot_transport import OperatorSnapshotTransportError

logger = logging.getLogger(__name__)

# Re-export constants so GUI code doesn't need to import zmq_bridge
DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
DEFAULT_CMD_ADDR = "tcp://127.0.0.1:5556"
DEFAULT_SAFE_CMD_ADDR = "tcp://127.0.0.1:5558"
# B1 (2026-07): cryodaq-assistant's own REP (Гемма + RAG, see
# agents/assistant_main.py). ``assistant.*`` / ``rag.*`` commands route
# here instead of the engine's DEFAULT_CMD_ADDR — additive, no change to
# any other command's routing.
DEFAULT_ASSISTANT_CMD_ADDR = "tcp://127.0.0.1:5557"
# Command name prefixes routed to DEFAULT_ASSISTANT_CMD_ADDR instead of
# the engine's cmd_addr.
_ASSISTANT_CMD_PREFIXES = ("assistant.", "rag.")
_ASSISTANT_PROTOCOL_VERSION_CMD = "assistant.protocol_version"
_BRIDGE_INGRESS_MONOTONIC_KEY = "__bridge_ingress_monotonic"
_ASSISTANT_READ_ACTIONS = frozenset(
    {
        _ASSISTANT_PROTOCOL_VERSION_CMD,
        "assistant.query",
        "rag.search",
    }
)
_MUTATION_ENVELOPE_KEYS = frozenset({"protocol_major", "mutation_capability", "capability_token"})
_INTERNAL_COMMAND_FIELDS = frozenset({"_rid", "_bridge_generation"})
# Mirror of zmq_bridge.DEFAULT_TOPIC. Duplicated (not imported) because this
# module is loaded in the GUI process, which must not import zmq/zmq_bridge
# at module scope. Keep in sync with cryodaq.core.zmq_bridge.DEFAULT_TOPIC.
DEFAULT_TOPIC = b"readings"
OPERATOR_SNAPSHOT_TOPIC = b"operator.snapshot"
READING_MAX_WIRE_BYTES = 2 * 1024 * 1024
OPERATOR_SNAPSHOT_MAX_WIRE_BYTES = 8 * 1024 * 1024
_COUNTER_LOCK_TIMEOUT_S = 0.01

# IV.3 Finding 7 / H7: subprocess REQ-socket RCVTIMEO/SNDTIMEO. This MUST sit
# strictly above the server slow handler cap (HANDLER_TIMEOUT_SLOW_S = 55 s in
# core/zmq_bridge.py) and strictly below the GUI client future
# (_CMD_REPLY_TIMEOUT_S = 65 s in gui/zmq_client.py), so command-path timeouts
# nest predictably: server (55) < subprocess REQ (60) < GUI (65). The previous
# 35 s value sat *below* the 55 s server cap (the cap was bumped 30→55 for
# Ollama cold-start without raising this), so a 35–55 s command tripped the
# REQ timeout first and surfaced a false ``cmd_timeout`` while the engine was
# still working. Named (not an inline literal) so tests assert the ordering on
# the live constant rather than grepping source text.
SUBPROCESS_REQ_TIMEOUT_S = 60.0


def _bounded_command_label(action: object) -> str:
    """Return only a short command identifier safe for public control data."""

    if type(action) is not str or not action or len(action) > 64:
        return "<invalid>"
    if any(not (char.isascii() and (char.isalnum() or char in "._-")) for char in action):
        return "<invalid>"
    return action


def _reject_reply_nonfinite(token: str) -> float:
    raise ValueError("non-finite command reply number")


def _parse_reply_float(token: str) -> float:
    value = float(token)
    if not math.isfinite(value):
        raise ValueError("non-finite command reply number")
    return value


def _parse_reply_int(token: str) -> int:
    if len(token.removeprefix("-")) > COMMAND_REPLY_MAX_INTEGER_DIGITS:
        raise ValueError("command reply integer is too large")
    return int(token)


def _reject_reply_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate command reply key")
        result[key] = value
    return result


def _decode_command_reply(raw: str) -> dict[str, Any]:
    """Decode one bounded finite JSON-object reply without leaking its payload."""

    if len(raw.encode("utf-8")) > COMMAND_REPLY_MAX_WIRE_BYTES:
        raise ValueError("command reply exceeds maximum size")
    try:
        decoded = json.loads(
            raw,
            parse_constant=_reject_reply_nonfinite,
            parse_float=_parse_reply_float,
            parse_int=_parse_reply_int,
            object_pairs_hook=_reject_reply_duplicate_pairs,
        )
    except (RecursionError, OverflowError) as exc:
        raise ValueError("command reply JSON structure is invalid") from exc
    return validate_command_reply_structure(
        decoded,
        max_wire_bytes=COMMAND_REPLY_MAX_WIRE_BYTES,
        max_depth=COMMAND_REPLY_MAX_JSON_DEPTH,
        max_items=COMMAND_REPLY_MAX_JSON_ITEMS,
        max_key_chars=COMMAND_REPLY_MAX_JSON_KEY_CHARS,
        max_integer_digits=COMMAND_REPLY_MAX_INTEGER_DIGITS,
    )


def _invalid_command_reply() -> dict[str, object]:
    return {
        "ok": False,
        "error_code": "command_reply_invalid",
        "error": "Engine command reply is invalid.",
        "delivery_state": "unknown",
        "commit_state": "unknown",
        "retry_safe": False,
    }


def _increment_shared_counter(counter: Any | None, amount: int = 1) -> bool:
    """Update optional evidence without trusting a possibly orphaned lock."""

    if counter is None or amount <= 0:
        return False
    lock = counter.get_lock()
    if not lock.acquire(timeout=_COUNTER_LOCK_TIMEOUT_S):
        return False
    try:
        counter.value = min((1 << 64) - 1, int(counter.value) + amount)
        return True
    finally:
        lock.release()


def _unpack_reading_dict(payload: bytes) -> dict[str, Any]:
    """Unpack msgpack Reading into a plain dict (picklable for mp.Queue).

    F35 D4: the optional ``"desc"`` descriptor envelope crosses as
    ``descriptor_envelope`` (bytes | None). Bound-checked defensively here
    (mirrors ``READING_MAX_WIRE_BYTES`` above it) — malformed type or
    oversize bytes are dropped to ``None``, never crossing the mp.Queue
    boundary and never raising.  The exact bool
    ``descriptor_envelope_malformed`` distinguishes a present-but-rejected
    descriptor from an absent legacy descriptor without carrying attacker
    bytes across the process boundary.
    """
    import msgpack

    data = msgpack.unpackb(payload, raw=False)
    envelope_present = "desc" in data
    envelope = data.get("desc")
    envelope_malformed = envelope_present and (
        type(envelope) is not bytes or len(envelope) > MAX_PERSISTED_ENVELOPE_BYTES
    )
    if envelope_malformed:
        envelope = None
    return {
        "timestamp": data["ts"],
        "instrument_id": data.get("iid", ""),
        "channel": data["ch"],
        "value": data["v"],
        "unit": data["u"],
        "status": data["st"],
        "raw": data.get("raw"),
        "metadata": data.get("meta", {}),
        "descriptor_envelope": envelope,
        "descriptor_envelope_malformed": envelope_malformed,
    }


class ReadingFrameError(ValueError):
    """A reading multipart message failed the exact public boundary."""


def _decode_reading_frames(frames: object) -> dict[str, Any]:
    """Reject prefix-topic and malformed frames before msgpack decoding."""
    if type(frames) not in (list, tuple) or len(frames) != 2:
        raise ReadingFrameError("invalid reading frame shape")
    topic, payload = frames
    if type(topic) is not bytes or type(payload) is not bytes:
        raise ReadingFrameError("invalid reading frame type")
    if topic != DEFAULT_TOPIC:
        raise ReadingFrameError("wrong reading topic")
    if len(payload) > READING_MAX_WIRE_BYTES:
        raise ReadingFrameError("reading payload too large")
    return _unpack_reading_dict(payload)


def _new_sub_socket(
    context: Any,
    zmq_module: Any,
    pub_addr: str,
    *,
    topic: bytes,
    max_wire_bytes: int,
) -> Any:
    """Create one independently capped SUB socket; called only in subprocess."""
    sub = context.socket(zmq_module.SUB)
    sub.setsockopt(zmq_module.LINGER, 0)
    sub.setsockopt(zmq_module.RCVTIMEO, 100)
    sub.setsockopt(zmq_module.MAXMSGSIZE, max_wire_bytes)
    sub.setsockopt(zmq_module.TCP_KEEPALIVE, 1)
    sub.setsockopt(zmq_module.TCP_KEEPALIVE_IDLE, 10)
    sub.setsockopt(zmq_module.TCP_KEEPALIVE_INTVL, 5)
    sub.setsockopt(zmq_module.TCP_KEEPALIVE_CNT, 3)
    sub.connect(pub_addr)
    sub.subscribe(topic)
    return sub


def zmq_bridge_main(
    pub_addr: str,
    cmd_addr: str,
    data_queue: mp.Queue,
    cmd_queue: mp.Queue,
    reply_queue: mp.Queue,
    shutdown_event: mp.Event,
    assistant_cmd_addr: str = DEFAULT_ASSISTANT_CMD_ADDR,
    snapshot_queue: Any | None = None,
    snapshot_malformed_count: Any | None = None,
    snapshot_drop_count: Any | None = None,
    safe_cmd_queue: Any | None = None,
    safe_cmd_addr: str = DEFAULT_SAFE_CMD_ADDR,
    safe_reply_queue: Any | None = None,
    safe_cmd_parent_endpoint_to_close: Any | None = None,
    safe_reply_parent_endpoint_to_close: Any | None = None,
) -> None:
    """Entry point for ZMQ bridge subprocess.

    Parameters
    ----------
    pub_addr:
        Engine PUB address, e.g. "tcp://127.0.0.1:5555".
    cmd_addr:
        Engine REP address, e.g. "tcp://127.0.0.1:5556".
    data_queue:
        Subprocess → GUI: Reading dicts plus control messages
        (``__type`` in {"heartbeat", "warning"}).
    cmd_queue:
        GUI → subprocess: command dicts to send via REQ.
    safe_cmd_queue:
        Optional bounded queue owned only by the preemptive forwarder.
    safe_cmd_addr:
        Dedicated live-engine REP address for exact targeted/global OFF and
        launcher shutdown envelopes.
    safe_reply_queue:
        Dedicated subprocess-to-GUI reply queue for the preemptive lane.
    reply_queue:
        Subprocess → GUI: command reply dicts.
    shutdown_event:
        Set by GUI to signal clean shutdown.
    assistant_cmd_addr:
        B1: cryodaq-assistant's own REP address, e.g.
        "tcp://127.0.0.1:5557". ``assistant.*`` / ``rag.*`` commands are
        routed here instead of ``cmd_addr`` — see ``_ASSISTANT_CMD_PREFIXES``.
        If the assistant process isn't running, the REQ simply times out
        the same way it would against a dead engine — same graceful
        ``{"ok": False, ...}`` path, nothing new to handle.
    """
    require_distinct_loopback_tcp_endpoints(
        pub=pub_addr,
        ordinary_command=cmd_addr,
        assistant_command=assistant_cmd_addr,
        safe_command=safe_cmd_addr,
    )
    import zmq

    HEARTBEAT_INTERVAL = 5.0  # seconds — keep generous vs is_healthy() threshold

    if (safe_cmd_queue is None) is not (safe_reply_queue is None):
        raise ValueError("safe command and reply queues must be configured together")
    # On ``fork`` every descriptor is inherited; on ``spawn`` every endpoint
    # explicitly present in the process arguments is duplicated. Close the
    # parent-only directions before any child thread starts so EOF/BrokenPipe
    # remains meaningful and each process owns exactly one end per direction.
    for endpoint in (
        safe_cmd_parent_endpoint_to_close,
        safe_reply_parent_endpoint_to_close,
    ):
        if endpoint is not None:
            endpoint.close()

    ctx = zmq.Context()

    dropped_counter = {"n": 0}

    def sub_drain_loop() -> None:
        """Own SUB socket; drain readings and emit periodic heartbeats.

        Heartbeat comes from this thread (not the command thread) so
        the GUI's heartbeat freshness check proves the *data* path is
        alive, not just that the subprocess exists.
        """
        # Order matters: connect() BEFORE subscribe(). The inverse pattern
        # (subscribe-before-connect with setsockopt_string(SUBSCRIBE, "")) produced
        # zero received messages on macOS Python 3.14 pyzmq 25+.
        sub = _new_sub_socket(
            ctx,
            zmq,
            pub_addr,
            topic=DEFAULT_TOPIC,
            max_wire_bytes=READING_MAX_WIRE_BYTES,
        )
        # 2026-04-20 idle-death fix: same keepalive as REQ side to
        # survive macOS kernel idle reaping. SUB normally gets a
        # stream of readings so idle is rare, but between-experiment
        # quiet periods exist (scheduler paused, no active polls).
        last_heartbeat = time.monotonic()
        try:
            while not shutdown_event.is_set():
                # SUB: blocking receive with 100ms RCVTIMEO. Keeps the loop
                # responsive for shutdown and heartbeat emission.
                try:
                    parts = sub.recv_multipart()
                    try:
                        reading_dict = _decode_reading_frames(parts)
                    except Exception:
                        reading_dict = None
                    if reading_dict is not None:
                        reading_dict[_BRIDGE_INGRESS_MONOTONIC_KEY] = time.monotonic()
                        try:
                            data_queue.put_nowait(reading_dict)
                        except queue.Full:
                            dropped_counter["n"] += 1
                            if dropped_counter["n"] % 100 == 1:
                                with contextlib.suppress(queue.Full):
                                    data_queue.put_nowait(
                                        {
                                            "__type": "warning",
                                            "message": (f"Queue overflow: {dropped_counter['n']} readings dropped"),
                                        }
                                    )
                except zmq.Again:
                    pass
                except zmq.ZMQError:
                    if shutdown_event.is_set():
                        break
                    # Unexpected socket error — swallow and continue.
                    time.sleep(0.01)

                now = time.monotonic()
                if now - last_heartbeat >= HEARTBEAT_INTERVAL:
                    with contextlib.suppress(queue.Full):
                        data_queue.put_nowait({"__type": "heartbeat", "ts": now})
                    last_heartbeat = now
        finally:
            sub.close(linger=0)

    def snapshot_drain_loop() -> None:
        """Own the dedicated snapshot SUB socket and strict decode boundary."""
        if snapshot_queue is None:
            return
        sub = _new_sub_socket(
            ctx,
            zmq,
            pub_addr,
            topic=OPERATOR_SNAPSHOT_TOPIC,
            max_wire_bytes=OPERATOR_SNAPSHOT_MAX_WIRE_BYTES,
        )
        ingress = OperatorSnapshotQueueIngress(
            snapshot_queue,
            expected_mode=SnapshotMode.LIVE,
        )
        try:
            while not shutdown_event.is_set():
                try:
                    frames = sub.recv_multipart()
                    receipt = ingress.accept_frames(frames)
                except zmq.Again:
                    continue
                except zmq.ZMQError:
                    if shutdown_event.is_set():
                        break
                    time.sleep(0.01)
                except (
                    OperatorSnapshotTransportError,
                    SnapshotIngressOrderingError,
                    SnapshotIngressQueueError,
                    TypeError,
                    ValueError,
                ):
                    _increment_shared_counter(snapshot_malformed_count)
                else:
                    _increment_shared_counter(snapshot_drop_count, receipt.dropped_oldest)
        finally:
            sub.close(linger=0)

    def command_forward_loop(
        source_queue: Any,
        target_reply_queue: Any,
        *,
        preemptive_lane: bool,
    ) -> None:
        """Forward one independent command lane via ephemeral REQ sockets.

        IV.6 B1 fix: each command creates, uses, and closes its own REQ
        socket. Shared long-lived REQ accumulated state across commands
        and became permanently unrecoverable after a platform-specific
        trigger (macOS sparse cadence within ~minutes, Ubuntu 120 s
        deterministic). Ephemeral REQ per command matches ZeroMQ Guide
        ch.4 canonical "poll / timeout / close / reopen" reliable
        request-reply pattern.

        An ordinary request cannot block the separately owned preemptive
        forwarder. Each lane has its own source queue, socket sequence, and
        reply queue; there is no polling or fallback between them.
        A timed-out REQ emits a structured ``cmd_timeout`` control
        message via data_queue so the launcher watchdog can detect
        command-channel-only failures and restart the bridge.
        """

        def _new_req_socket(addr: str):
            """Build a fresh per-command REQ socket connected to ``addr``.

            IV.6: REQ_RELAXED / REQ_CORRELATE dropped — they were only
            useful for stateful recovery on a shared socket, which the
            ephemeral model has eliminated. TCP_KEEPALIVE dropped from
            the command path (reverting the f5f9039 partial fix) —
            revised analysis confirmed idle-reap was not the
            actual cause; keepalive is a no-op here and clutters
            debugging of the real socket state.
            """
            req = ctx.socket(zmq.REQ)
            req.setsockopt(zmq.LINGER, 0)
            # Reject oversize inbound frames in libzmq before decoder allocation.
            # This policy must be installed before connect().
            req.setsockopt(zmq.MAXMSGSIZE, COMMAND_REPLY_MAX_WIRE_BYTES)
            # IV.3 Finding 7 / H7: REQ timeout = SUBPROCESS_REQ_TIMEOUT_S
            # (60 s) — strictly above the server slow handler cap (55 s,
            # HANDLER_TIMEOUT_SLOW_S) and strictly below the GUI client
            # future (65 s, _CMD_REPLY_TIMEOUT_S). A slow server-side
            # handler (experiment_finalize / report generation / Ollama
            # cold-start, capped at 55 s) has room to reply before the REQ
            # side gives up, so timeouts at each layer fire in predictable
            # order: server → subprocess REQ → GUI future.
            _req_timeout_ms = int(SUBPROCESS_REQ_TIMEOUT_S * 1000)
            req.setsockopt(zmq.RCVTIMEO, _req_timeout_ms)
            req.setsockopt(zmq.SNDTIMEO, _req_timeout_ms)
            req.connect(addr)
            return req

        class _ForwarderStopping(Exception):
            pass

        def _recv_reply(req: Any) -> str:
            """Wait for a reply while retaining bounded shutdown ownership."""

            poll = getattr(req, "poll", None)
            if not callable(poll):
                # Minimal fake sockets used by isolated guards expose only the
                # blocking API. Production pyzmq sockets always provide poll.
                return req.recv_string()
            deadline = time.monotonic() + SUBPROCESS_REQ_TIMEOUT_S
            while True:
                if shutdown_event.is_set():
                    raise _ForwarderStopping
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("command endpoint reply timed out")
                if poll(timeout=max(1, min(100, int(remaining * 1000)))):
                    return req.recv_string()

        def _publish_reply(reply: dict[str, object]) -> None:
            """Publish one lane reply; safe-lane loss is process-fatal."""

            try:
                target_reply_queue.put(reply, timeout=2.0)
            except Exception as exc:
                if preemptive_lane:
                    raise RuntimeError("safe reply publication failed") from exc
                with contextlib.suppress(queue.Full):
                    data_queue.put_nowait({"__type": "warning", "message": "Reply queue overflow"})

        while not shutdown_event.is_set():
            try:
                cmd = source_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            rid = cmd.get("_rid") if isinstance(cmd, dict) else None
            bridge_generation = cmd.get("_bridge_generation") if isinstance(cmd, dict) else None
            wire_cmd = (
                {key: value for key, value in cmd.items() if key not in _INTERNAL_COMMAND_FIELDS}
                if isinstance(cmd, dict)
                else cmd
            )
            cmd_type = wire_cmd.get("cmd", "?") if isinstance(wire_cmd, dict) else "?"
            assistant_namespaced = isinstance(cmd_type, str) and cmd_type.startswith(_ASSISTANT_CMD_PREFIXES)
            rejection: dict[str, object] | None = None
            internal_fields = (
                {key for key in cmd if isinstance(key, str) and key.startswith("_")} if isinstance(cmd, dict) else set()
            )
            if internal_fields - _INTERNAL_COMMAND_FIELDS:
                rejection = {
                    "ok": False,
                    "error_code": "command_internal_metadata_invalid",
                    "error": "command contains an unknown internal correlation field",
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            elif rid is not None and (type(rid) is not str or not rid):
                rejection = {
                    "ok": False,
                    "error_code": "command_internal_metadata_invalid",
                    "error": "command request correlation is malformed",
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            elif bridge_generation is not None and (type(bridge_generation) is not int or bridge_generation < 0):
                rejection = {
                    "ok": False,
                    "error_code": "command_internal_metadata_invalid",
                    "error": "command bridge generation is malformed",
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            elif type(wire_cmd) is not dict:
                rejection = {
                    "ok": False,
                    "error_code": "command_request_invalid",
                    "error": "command payload must be an exact object",
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            elif type(cmd_type) is not str or not cmd_type:
                rejection = {
                    "ok": False,
                    "error_code": "command_request_invalid",
                    "error": "command requires a non-empty exact string action",
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            elif preemptive_lane and not is_preemptive_safe_direction(wire_cmd):
                rejection = {
                    "ok": False,
                    "error_code": "safe_direction_endpoint_rejected",
                    "error": "Dedicated safe endpoint admits only exact OFF or launcher shutdown",
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            elif not preemptive_lane and is_preemptive_safe_direction(wire_cmd):
                rejection = {
                    "ok": False,
                    "error_code": "preemptive_safe_direction_lane_required",
                    "error": "Exact OFF and launcher shutdown require the dedicated safe endpoint",
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            elif cmd_type in SAFE_DIRECTION_ACTIONS and exact_safe_direction_kind(wire_cmd) is None:
                rejection = {
                    "ok": False,
                    "error_code": "safe_direction_envelope_invalid",
                    "error": "Safe-direction command envelope is invalid",
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            elif not preemptive_lane and assistant_namespaced and cmd_type not in _ASSISTANT_READ_ACTIONS:
                rejection = {
                    "ok": False,
                    "error_code": "assistant_read_only",
                    "error": "Помощник работает только для чтения; команда не отправлена",
                    "cause": "Команда не входит в точный список разрешённых запросов помощника",
                    "next_step": "Используйте отдельно утверждённую офлайн-процедуру",
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            elif (
                not preemptive_lane and assistant_namespaced and any(key in wire_cmd for key in _MUTATION_ENVELOPE_KEYS)
            ):
                rejection = {
                    "ok": False,
                    "error_code": "assistant_mutation_envelope_forbidden",
                    "error": "Помощник не принимает полномочия изменения; команда не отправлена",
                    "cause": "Запрос содержит поля полномочий изменения",
                    "next_step": "Удалите поля полномочий и повторите только разрешённый запрос чтения",
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            if rejection is not None:
                if rid is not None:
                    rejection["_rid"] = rid
                if type(bridge_generation) is int and bridge_generation >= 0:
                    rejection["_bridge_generation"] = bridge_generation
                _publish_reply(rejection)
                continue

            # Only exact observational assistant actions reach its REP.
            target_addr = (
                safe_cmd_addr
                if preemptive_lane
                else (assistant_cmd_addr if cmd_type in _ASSISTANT_READ_ACTIONS else cmd_addr)
            )
            # The GUI-facing name is namespaced so the existing router can
            # select assistant REP. The wire command remains the standard,
            # server-independent discovery command handled by ZMQCommandServer.
            if not preemptive_lane and cmd_type == _ASSISTANT_PROTOCOL_VERSION_CMD:
                wire_cmd = {**wire_cmd, "cmd": "protocol_version"}

            # Fresh socket per command — no shared state across commands.
            req = _new_req_socket(target_addr)
            try:
                try:
                    req.send_string(json.dumps(wire_cmd))
                    reply_raw = _recv_reply(req)
                    try:
                        reply = _decode_command_reply(reply_raw)
                    except (json.JSONDecodeError, UnicodeError, ValueError, TypeError):
                        reply = _invalid_command_reply()
                except _ForwarderStopping:
                    return
                except (zmq.ZMQError, TimeoutError):
                    public_action = _bounded_command_label(cmd_type)
                    reply = {
                        "ok": False,
                        "error_code": "command_endpoint_unavailable",
                        "error": "Engine command endpoint is unavailable.",
                        "delivery_state": "unknown",
                        "commit_state": "unknown",
                        "retry_safe": False,
                    }
                    with contextlib.suppress(queue.Full):
                        data_queue.put_nowait(
                            {
                                "__type": "cmd_timeout",
                                "cmd": public_action,
                                "ts": time.monotonic(),
                                "message": f"REP timeout on {public_action}.",
                            }
                        )
                except Exception:  # noqa: BLE001
                    reply = {
                        "ok": False,
                        "error_code": "command_forward_failed",
                        "error": "Engine command forwarding failed.",
                        "delivery_state": "unknown",
                        "commit_state": "unknown",
                        "retry_safe": False,
                    }
            finally:
                req.close(linger=0)

            if rid is not None:
                reply["_rid"] = rid
            if type(bridge_generation) is int and bridge_generation >= 0:
                reply["_bridge_generation"] = bridge_generation
            _publish_reply(reply)

    def cmd_forward_loop() -> None:
        command_forward_loop(
            cmd_queue,
            reply_queue,
            preemptive_lane=False,
        )

    def safe_cmd_forward_loop() -> None:
        assert safe_cmd_queue is not None and safe_reply_queue is not None
        command_forward_loop(
            safe_cmd_queue,
            safe_reply_queue,
            preemptive_lane=True,
        )

    failure_lock = threading.Lock()
    failure_state: dict[str, object] = {}

    def _record_thread_failure(
        lane: str,
        error: BaseException,
        *,
        force: bool = False,
    ) -> None:
        with failure_lock:
            if failure_state:
                return
            if shutdown_event.is_set() and not force:
                return
            error_type = _bounded_command_label(type(error).__name__)
            failure_state.update(
                lane=lane,
                error_type=error_type,
                cause=error,
            )
            shutdown_event.set()

    def _supervised_target(lane: str, target: Any) -> Any:
        def _run() -> None:
            try:
                target()
            except BaseException as exc:
                _record_thread_failure(lane, exc)
                return
            if not shutdown_event.is_set():
                _record_thread_failure(
                    lane,
                    RuntimeError("owned thread returned before shutdown"),
                )

        return _run

    sub_thread = threading.Thread(
        target=_supervised_target("sub", sub_drain_loop),
        name="zmq-sub-drain",
        daemon=True,
    )
    snapshot_thread = (
        threading.Thread(
            target=_supervised_target("snapshot", snapshot_drain_loop),
            name="zmq-snapshot-drain",
            daemon=True,
        )
        if snapshot_queue is not None
        else None
    )
    cmd_thread = threading.Thread(
        target=_supervised_target("ordinary_command", cmd_forward_loop),
        name="zmq-cmd-forward",
        daemon=True,
    )
    safe_cmd_thread = (
        threading.Thread(
            target=_supervised_target("safe_command", safe_cmd_forward_loop),
            name="zmq-safe-cmd-forward",
            daemon=True,
        )
        if safe_cmd_queue is not None
        else None
    )

    owned_threads = tuple(
        thread for thread in (sub_thread, snapshot_thread, cmd_thread, safe_cmd_thread) if thread is not None
    )
    started_threads: list[threading.Thread] = []
    try:
        for thread in owned_threads:
            try:
                thread.start()
            except BaseException as exc:
                _record_thread_failure(f"thread_start:{thread.name}", exc, force=True)
                break
            started_threads.append(thread)
            if shutdown_event.is_set():
                break
        while not shutdown_event.is_set() and not failure_state:
            shutdown_event.wait(timeout=0.5)
    except KeyboardInterrupt:
        shutdown_event.set()
    except BaseException as exc:
        _record_thread_failure("main", exc, force=True)
    finally:
        shutdown_event.set()
        for thread in started_threads:
            thread.join(timeout=4.0)
        still_unsettled = tuple(thread.name for thread in started_threads if thread.is_alive())
        for endpoint in (safe_cmd_queue, safe_reply_queue):
            if isinstance(endpoint, (DirectionalPipeReceiver, DirectionalPipeSender)):
                with contextlib.suppress(Exception):
                    endpoint.close()
        if still_unsettled:
            _record_thread_failure(
                "thread_settlement",
                RuntimeError("owned threads remained alive after bounded join"),
                force=True,
            )
            # Context.term() waits for every socket and can block forever when
            # an owning thread is still alive. A fatal child exit lets the OS
            # reclaim this process-local context without hiding lane death.
        else:
            try:
                ctx.term()
            except BaseException as exc:
                _record_thread_failure("context_term", exc, force=True)

    if failure_state:
        lane = str(failure_state["lane"])
        error_type = str(failure_state["error_type"])
        cause = failure_state["cause"]
        error = RuntimeError(f"ZMQ bridge owned lane failed: lane={lane} error_type={error_type}")
        if isinstance(cause, BaseException):
            raise error from cause
        raise error
