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
  allocated in user space (audit C.2 / Codex D6).
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
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import msgpack
import zmq
import zmq.asyncio

from cryodaq.drivers.base import ChannelStatus, Reading

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


def _decode_command(raw: bytes | str) -> dict:
    """Decode a command frame, rejecting non-finite numeric values.

    Python's ``json`` accepts the non-standard ``NaN``/``Infinity``/``-Infinity``
    tokens by default, and a large literal like ``1e999`` parses to ``inf``; a
    non-finite setpoint would then defeat the downstream ``> max`` / ``<= 0``
    limit guards (IEEE-754 makes those comparisons False) and reach the
    hardware. Rejecting both forms at this trust boundary keeps the whole
    command surface finite-clean. A rejected value surfaces as a ``ValueError``,
    handled identically to malformed JSON by the caller.
    """
    return json.loads(
        raw, parse_constant=_reject_nonfinite, parse_float=_parse_finite_float
    )


DEFAULT_PUB_ADDR = "tcp://127.0.0.1:5555"
DEFAULT_CMD_ADDR = "tcp://127.0.0.1:5556"
DEFAULT_TOPIC = b"readings"

# Audit C.2 / Codex D6: socket-level size caps on the unauthenticated
# loopback command/data path. libzmq (ZMQ_MAXMSGSIZE) drops an oversize
# frame before it is allocated in user space — this is the trust-boundary
# guard, not the post-recv len() check. Commands are small JSON; data
# frames are single msgpack Readings. Both caps are deliberately generous
# vs. real traffic so legitimate payloads are never clipped.
MAX_CMD_MSG_SIZE = 256 * 1024  # 256 KiB — commands are tiny JSON objects
MAX_DATA_MSG_SIZE = 2 * 1024 * 1024  # 2 MiB — one msgpack Reading, generous

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
                    "ZMQ bind FAILED after %d attempts: %s still in use. "
                    "Check for stale sockets via lsof/netstat.",
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


def _pack_reading(reading: Reading) -> bytes:
    """Сериализовать Reading в msgpack."""
    data = {
        "ts": reading.timestamp.timestamp(),
        "iid": reading.instrument_id,
        "ch": reading.channel,
        "v": reading.value,
        "u": reading.unit,
        "st": reading.status.value,
        "raw": reading.raw,
        "meta": reading.metadata,
    }
    return msgpack.packb(data, use_bin_type=True)


def _unpack_reading(payload: bytes) -> Reading:
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
    return Reading(
        timestamp=datetime.fromtimestamp(data["ts"], tz=UTC),
        instrument_id=data.get("iid", ""),
        channel=data["ch"],
        value=data["v"],
        unit=data["u"],
        status=ChannelStatus(data["st"]),
        raw=data.get("raw"),
        metadata=data.get("meta", {}),
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

    async def _publish_loop(self, queue: asyncio.Queue[Reading]) -> None:
        while self._running:
            try:
                reading = await asyncio.wait_for(queue.get(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                payload = _pack_reading(reading)
                await self._socket.send_multipart([self._topic, payload])
                self._total_sent += 1
            except Exception:
                logger.exception("Ошибка отправки ZMQ")

    async def start(self, queue: asyncio.Queue[Reading]) -> None:
        self._ctx = zmq.asyncio.Context()
        self._socket = self._ctx.socket(zmq.PUB)
        # Phase 2b H.4: LINGER=0 so the socket doesn't hold the port open
        # after close — relevant on Windows where TIME_WAIT can keep
        # 5555 occupied for 240s after a SIGKILL'd engine.
        self._socket.setsockopt(zmq.LINGER, 0)
        # IV.6: TCP_KEEPALIVE previously added here on the idle-reap
        # hypothesis (commit f5f9039). Codex revised analysis disproved
        # that — Ubuntu 120 s deterministic failure with default
        # tcp_keepalive_time=7200 s rules out kernel reaping. Keepalive
        # reverted on the command path (REQ + REP); retained on the
        # SUB drain path in zmq_subprocess.sub_drain_loop as an
        # orthogonal safeguard for long between-experiment pauses.
        await _bind_with_retry(self._socket, self._address)
        self._running = True
        self._task = asyncio.create_task(self._publish_loop(queue), name="zmq_publisher")
        logger.info("ZMQPublisher запущен: %s", self._address)

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
        logger.info("ZMQPublisher остановлен (отправлено: %d)", self._total_sent)


class ZMQSubscriber:
    """SUB-сокет: GUI-процесс подписывается на поток данных от engine.

    Использование::

        async def on_reading(r: Reading):
            print(r.channel, r.value)

        sub = ZMQSubscriber("tcp://127.0.0.1:5555", callback=on_reading)
        await sub.start()
        ...
        await sub.stop()
    """

    def __init__(
        self,
        address: str = DEFAULT_PUB_ADDR,
        *,
        topic: bytes = DEFAULT_TOPIC,
        callback: Callable[[Reading], object] | None = None,
    ) -> None:
        self._address = address
        self._topic = topic
        self._callback = callback
        self._ctx: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._total_received: int = 0

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
                reading = _unpack_reading(parts[1])
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

    async def start(self) -> None:
        self._ctx = zmq.asyncio.Context()
        self._socket = self._ctx.socket(zmq.SUB)
        self._socket.setsockopt(zmq.LINGER, 0)
        # Audit C.2 / Codex D6: drop oversize inbound frames at the socket
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
    ) -> None:
        self._address = address
        self._handler = handler
        # IV.3 Finding 7: honour an explicit override (tests supply one
        # to exercise the timeout path without sleeping for 2 s), but
        # the production path uses the tiered ``_timeout_for(cmd)``
        # helper so slow commands get 30 s and fast commands 2 s.
        self._handler_timeout_override_s = handler_timeout_s
        self._ctx: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._task: asyncio.Task[None] | None = None
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
                "ZMQCommandServer serve loop crashed; restarting",
                exc_info=(type(exc), exc, exc.__traceback__),
            )
        else:
            logger.error("ZMQCommandServer serve loop exited unexpectedly; restarting")

        loop = task.get_loop()
        if loop.is_closed():
            logger.error("ZMQCommandServer loop is closed; cannot restart serve loop")
            return
        loop.call_soon(self._start_serve_task)

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

        action = str(cmd.get("cmd", ""))
        timeout = (
            self._handler_timeout_override_s
            if self._handler_timeout_override_s is not None
            else _timeout_for(cmd)
        )

        async def _invoke() -> Any:
            result = self._handler(cmd)
            if asyncio.iscoroutine(result):
                result = await result
            return result

        try:
            result = await asyncio.wait_for(_invoke(), timeout=timeout)
        except TimeoutError as exc:
            # Preserve inner wrapper message when present (e.g.
            # "log_get timeout (1.5s)"). Falls back to the generic
            # envelope message when the timeout fired at the outer
            # asyncio.wait_for layer.
            inner_message = str(exc).strip()
            error_message = (
                inner_message
                if inner_message
                else f"handler timeout ({timeout:g}s); operation may still be running."
            )
            logger.error(
                "ZMQ command handler timeout: action=%s error=%s payload=%r",
                action,
                error_message,
                cmd,
            )
            return {
                "ok": False,
                "error": error_message,
                "_handler_timeout": True,
            }
        except asyncio.CancelledError:
            # Cancellation is not a handler failure — propagate so the
            # serve loop can still try to send its own short error
            # reply before the task itself tears down.
            raise
        except Exception as exc:
            # Belt-and-suspenders: the outer serve loop already catches
            # exceptions and sends an error reply, but pushing the
            # dict back through the normal return path keeps the REP
            # state-machine handling uniform with the timeout branch.
            logger.exception(
                "ZMQ command handler failed: action=%s payload=%r",
                action,
                cmd,
            )
            return {"ok": False, "error": str(exc) or type(exc).__name__}

        return result if isinstance(result, dict) else {"ok": True}

    async def _serve_loop(self) -> None:
        while self._running:
            try:
                events = await self._socket.poll(timeout=1000)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка poll команды ZMQ")
                continue
            if not (events & zmq.POLLIN):
                continue
            try:
                raw = await self._socket.recv()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ошибка приёма команды ZMQ")
                continue

            # Once recv() succeeds, the REP socket is in "awaiting send" state.
            # We MUST send a reply — otherwise the socket is stuck forever.
            try:
                cmd = _decode_command(raw)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
                await self._socket.send(json.dumps({"ok": False, "error": "invalid JSON"}).encode())
                continue

            try:
                reply = await self._run_handler(cmd)
            except asyncio.CancelledError:
                # CancelledError during handler — must still send reply
                # to avoid leaving REP socket in stuck state.
                try:
                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
                except Exception:
                    pass
                raise
            except Exception as exc:
                logger.exception("Ошибка обработки команды: %s", cmd)
                reply = {"ok": False, "error": str(exc)}

            try:
                await self._socket.send(json.dumps(reply, default=str).encode())
            except asyncio.CancelledError:
                # Shutting down — try best-effort send
                try:
                    await self._socket.send(json.dumps({"ok": False, "error": "internal"}).encode())
                except Exception:
                    pass
                raise
            except Exception:
                logger.exception("Ошибка отправки ответа ZMQ")
                # Serialization or send failure — must still send a reply
                # to avoid leaving the REP socket in stuck state.
                try:
                    await self._socket.send(
                        json.dumps({"ok": False, "error": "serialization error"}).encode()
                    )
                except Exception:
                    pass

    async def start(self) -> None:
        self._ctx = zmq.asyncio.Context()
        self._socket = self._ctx.socket(zmq.REP)
        # Phase 2b H.4: LINGER=0 + EADDRINUSE retry (see _bind_with_retry).
        self._socket.setsockopt(zmq.LINGER, 0)
        # Audit C.2 / Codex D6: cap inbound command frames at the socket
        # level so libzmq drops an oversize command before allocation
        # (set before bind()).
        self._socket.setsockopt(zmq.MAXMSGSIZE, MAX_CMD_MSG_SIZE)
        # IV.6: TCP_KEEPALIVE previously added on the idle-reap
        # hypothesis (commit f5f9039). Reverted — the actual fix is
        # an ephemeral per-command REQ socket on the GUI subprocess
        # side (zmq_subprocess.cmd_forward_loop). With a fresh TCP
        # connection per command, loopback kernel reaping is moot.
        await _bind_with_retry(self._socket, self._address)
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
        if self._socket:
            self._socket.close(linger=0)
            self._socket = None
        if self._ctx:
            self._ctx.term()
            self._ctx = None
        logger.info("ZMQCommandServer остановлен")
