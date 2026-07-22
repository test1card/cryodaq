"""ZMQ bridge client for GUI — all ZMQ lives in a subprocess.

The GUI process never imports zmq. Communication with the subprocess
is via multiprocessing.Queue. If libzmq crashes (signaler.cpp assertion
on Windows), only the subprocess dies — GUI detects and restarts it.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing as mp
import queue
import threading
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QThread, Signal

from cryodaq.channels.descriptors import ChannelDescriptorV1
from cryodaq.core.descriptor_transport import (
    DescriptorQualifiedReading,
    qualify_reading_descriptor,
)
from cryodaq.core.zmq_subprocess import (
    DEFAULT_ASSISTANT_CMD_ADDR,
    DEFAULT_CMD_ADDR,
    DEFAULT_PUB_ADDR,
    zmq_bridge_main,
)
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.operator_snapshot import OperatorSnapshot

logger = logging.getLogger(__name__)

_CMD_REPLY_TIMEOUT_S = 65.0  # H7: outermost command tier — server 55s < REQ 60s < GUI 65s

# Mirror of core.zmq_bridge.PROTOCOL_VERSION. Duplicated (not imported) —
# this module must not import zmq/core.zmq_bridge at module scope (the GUI
# process never imports zmq; see module docstring). Keep in sync with
# cryodaq.core.zmq_bridge.PROTOCOL_VERSION. Used only to warn once if a
# server ever reports a newer proto than this client knows — see
# docs/protocol.md.
CLIENT_PROTOCOL_VERSION = 1
_COUNTER_LOCK_TIMEOUT_S = 0.01
_MAX_UNRESOLVED_COMMANDS = 1024


@dataclass(frozen=True, slots=True)
class LateCommandResult:
    """Typed, generation-bound result retained after owner cancellation."""

    request_id: str
    generation: int
    reply: dict[str, Any]


def _read_shared_counter(counter: Any, fallback: int) -> int:
    """Read presentation evidence without blocking on an orphaned lock."""

    lock = counter.get_lock()
    if not lock.acquire(timeout=_COUNTER_LOCK_TIMEOUT_S):
        return fallback
    try:
        return int(counter.value)
    finally:
        lock.release()


def _increment_shared_counter(counter: Any) -> int | None:
    """Best-effort evidence increment; presentation must never block."""

    lock = counter.get_lock()
    if not lock.acquire(timeout=_COUNTER_LOCK_TIMEOUT_S):
        return None
    try:
        counter.value = min((1 << 64) - 1, int(counter.value) + 1)
        return int(counter.value)
    finally:
        lock.release()


def _reading_from_dict(d: dict[str, Any]) -> Reading:
    """Reconstruct a Reading from a plain dict (received via mp.Queue)."""
    return Reading(
        timestamp=datetime.fromtimestamp(d["timestamp"], tz=UTC),
        instrument_id=d.get("instrument_id", ""),
        channel=d["channel"],
        value=d["value"],
        unit=d["unit"],
        status=ChannelStatus(d["status"]),
        raw=d.get("raw"),
        metadata=d.get("metadata", {}),
    )


ReadingWithDescriptor = DescriptorQualifiedReading


def _descriptor_from_envelope(
    payload: object,
    *,
    expected_channel_id: str,
    expected_instrument_id: str,
    expected_unit: str,
) -> ChannelDescriptorV1 | None:
    """Decode fail-closed: absent/malformed/oversize/mismatched -> None, never raise.

    Reuses ``decode_persisted_channel_envelope``'s own strict/duplicate-key/
    size adversarial contract rather than re-implementing it here. A present
    envelope whose channel, instrument, or unit disagrees with the exact
    Reading tuple is treated like a malformed one.  A descriptor can never be
    attached by channel identity alone.
    """
    identity_reading = Reading(
        timestamp=datetime.fromtimestamp(0, tz=UTC),
        instrument_id=expected_instrument_id,
        channel=expected_channel_id,
        value=0.0,
        unit=expected_unit,
        status=ChannelStatus.OK,
    )
    return qualify_reading_descriptor(identity_reading, payload).descriptor


class ZmqBridge:
    """GUI-side ZMQ bridge. No zmq import — all ZMQ lives in subprocess.

    Usage::

        bridge = ZmqBridge()
        bridge.start()
        # In QTimer tick:
        for reading in bridge.poll_readings():
            handle(reading)
        # Commands:
        reply = bridge.send_command({"cmd": "safety_status"})
        # Shutdown:
        bridge.shutdown()
    """

    def __init__(
        self,
        pub_addr: str = DEFAULT_PUB_ADDR,
        cmd_addr: str = DEFAULT_CMD_ADDR,
        assistant_cmd_addr: str = DEFAULT_ASSISTANT_CMD_ADDR,
    ) -> None:
        self._pub_addr = pub_addr
        self._cmd_addr = cmd_addr
        # B1: assistant.*/rag.* commands route here instead — see
        # core/zmq_subprocess.py's cmd_forward_loop. Defaulted so no
        # call site needs to change to pick this up.
        self._assistant_cmd_addr = assistant_cmd_addr
        self._data_queue: mp.Queue = mp.Queue(maxsize=10_000)
        self._cmd_queue: mp.Queue = mp.Queue(maxsize=1_000)
        self._reply_queue: mp.Queue = mp.Queue(maxsize=1_000)
        self._snapshot_queue = mp.JoinableQueue(maxsize=2)
        self._snapshot_malformed_count = mp.Value("Q", 0, lock=True)
        self._snapshot_drop_count = mp.Value("Q", 0, lock=True)
        self._snapshot_malformed_count_cached = 0
        self._snapshot_drop_count_cached = 0
        self._shutdown_event: mp.Event = mp.Event()
        self._process: mp.Process | None = None
        self._last_heartbeat: float = 0.0
        # Data-flow watchdog: timestamp of the most recently drained
        # actual reading (not heartbeat, not warning). Stays 0.0 until
        # the first reading arrives so startup and between-experiment
        # pauses don't trigger false-positive restarts.
        self._last_reading_time: float = 0.0
        self._last_snapshot_time: float = 0.0
        # IV.6 B1 fix: timestamp of the most recent cmd_timeout control
        # message emitted by the subprocess. Launcher watchdog uses
        # ``command_channel_stalled()`` to detect command-channel-only
        # failures where the data plane is still healthy but REQ/REP
        # has entered a bad state.
        self._last_cmd_timeout: float = 0.0
        # Future-per-request command routing
        self._pending: dict[str, Future] = {}
        self._outcome_unknown: dict[str, Future] = {}
        self._request_generation: dict[str, int] = {}
        self._late_results: dict[str, LateCommandResult] = {}
        self._pending_lock = threading.Lock()
        self._reply_stop = threading.Event()
        self._reply_consumer: threading.Thread | None = None
        # Hardening 2026-04-21: restart counter for B1 diagnostic correlation
        self._restart_count: int = 0
        # Warn at most once for this ZmqBridge instance. Subprocess restarts do
        # not re-arm the warning and therefore cannot create operator log spam.
        self._proto_warned: bool = False
        # F35 D4: count of readings whose descriptor envelope was present but
        # failed to decode/verify (fail-closed to None, never raised). Decoded
        # entirely in-process here (GUI process, not the subprocess), so a
        # plain instance counter is enough — no cross-process mp.Value needed.
        self._descriptor_malformed_count: int = 0
        # A bridge restart is a new presentation authority.  The subprocess
        # wire data cannot choose this value: it is attached only after a
        # Reading has crossed into this GUI-side bridge instance.
        self._bridge_instance_id: str | None = uuid.uuid4().hex
        self._generation = 0

    def start(self) -> None:
        """Start the ZMQ bridge subprocess."""
        if self._process is not None and self._process.is_alive():
            return
        # Invalidate presentation freshness before any restart cleanup or
        # spawn operation that may raise.  Failure must remain unavailable.
        self._last_snapshot_time = 0.0
        # A dead or partially started subprocess may still have feeder-
        # buffered cuts.  A fresh queue on every spawn attempt makes restart
        # invalidation atomic even when later cleanup or Process.start fails.
        old_snapshot_queue = self._snapshot_queue
        _drain(old_snapshot_queue, task_done=True)
        with contextlib.suppress(Exception):
            old_snapshot_queue.cancel_join_thread()
        with contextlib.suppress(Exception):
            old_snapshot_queue.close()
        self._snapshot_queue = mp.JoinableQueue(maxsize=2)
        self._bridge_instance_id = uuid.uuid4().hex
        self._generation += 1
        if self._reply_consumer is not None and self._reply_consumer.is_alive():
            self._reply_stop.set()
            self._reply_consumer.join(timeout=1.0)
            self._reply_consumer = None
        with self._pending_lock:
            for future in (*self._pending.values(), *self._outcome_unknown.values()):
                if not future.done():
                    future.set_result({"ok": False, "error": "bridge generation replaced; outcome unknown"})
            self._pending.clear()
            # Outcome-unknown owners remain addressable until explicit
            # reconciliation; generation replacement must not erase them.
        # Every child generation owns fresh IPC queues.  Old-child messages
        # remain attached to the retired queue object and cannot be relabelled
        # with this GUI incarnation after a restart.
        for name, factory in (
            ("_data_queue", lambda: mp.Queue(maxsize=10_000)),
            ("_cmd_queue", lambda: mp.Queue(maxsize=1_000)),
            ("_reply_queue", lambda: mp.Queue(maxsize=1_000)),
        ):
            old_queue = getattr(self, name)
            _drain(old_queue)
            with contextlib.suppress(Exception):
                old_queue.cancel_join_thread()
            with contextlib.suppress(Exception):
                old_queue.close()
            setattr(self, name, factory())
        self._shutdown_event.clear()
        self._process = mp.Process(
            target=zmq_bridge_main,
            args=(
                self._pub_addr,
                self._cmd_addr,
                self._data_queue,
                self._cmd_queue,
                self._reply_queue,
                self._shutdown_event,
                self._assistant_cmd_addr,
                self._snapshot_queue,
                self._snapshot_malformed_count,
                self._snapshot_drop_count,
            ),
            daemon=True,
            name="zmq_bridge",
        )
        self._process.start()
        self._last_heartbeat = time.monotonic()
        self._last_reading_time = 0.0
        # Start dedicated reply consumer thread
        self._reply_stop.clear()
        self._reply_consumer = threading.Thread(
            target=self._consume_replies,
            daemon=True,
            name="zmq-reply-consumer",
        )
        self._reply_consumer.start()
        self._restart_count += 1
        logger.info(
            "ZMQ bridge subprocess started (PID=%d, restart_count=%d)",
            self._process.pid,
            self._restart_count,
        )

    def is_alive(self) -> bool:
        """Check if the subprocess is still running."""
        return self._process is not None and self._process.is_alive()

    def poll_readings(self) -> list[Reading]:
        """Drain all available readings from the data queue. Non-blocking."""
        readings: list[Reading] = []
        while True:
            try:
                d = self._data_queue.get_nowait()
                # Handle internal control messages from subprocess
                msg_type = d.get("__type")
                if msg_type == "heartbeat":
                    self._last_heartbeat = time.monotonic()
                    continue
                if msg_type == "cmd_timeout":
                    # IV.6 B1 fix: structured timeout marker used by the
                    # launcher's command-channel watchdog. Separate from
                    # "warning" because the launcher must restart the
                    # bridge on this specific failure shape, not on
                    # generic queue-overflow warnings.
                    self._last_cmd_timeout = time.monotonic()
                    logger.warning(
                        "ZMQ bridge: %s",
                        d.get("message", "command timeout"),
                    )
                    continue
                if msg_type == "warning":
                    logger.warning("ZMQ bridge: %s", d.get("message", ""))
                    continue
                self._last_reading_time = time.monotonic()
                readings.append(self._with_bridge_incarnation(_reading_from_dict(d)))
            except (queue.Empty, EOFError):
                break
            except Exception as exc:
                logger.warning("poll_readings: error processing item: %s", exc)
                continue
        return readings

    def poll_readings_with_descriptor(self) -> list[ReadingWithDescriptor]:
        """Drain all available readings, pairing each with its decoded descriptor.

        Additive alongside ``poll_readings()``, which stays byte-for-byte
        unchanged — every current call site keeps compiling and behaving
        exactly as today. Both methods drain the same underlying
        ``mp.Queue``; a caller should use one or the other for a given
        consumer, not both, or items will be split between the two drains.

        ``descriptor`` is ``None`` for legacy/non-authoritative readings (no
        envelope on the wire) and for a present-but-malformed/oversize/
        identity-mismatched envelope — decode is fail-closed, never raises
        into the caller, never synthesizes a descriptor.
        """
        paired: list[ReadingWithDescriptor] = []
        while True:
            try:
                d = self._data_queue.get_nowait()
                msg_type = d.get("__type")
                if msg_type == "heartbeat":
                    self._last_heartbeat = time.monotonic()
                    continue
                if msg_type == "cmd_timeout":
                    self._last_cmd_timeout = time.monotonic()
                    logger.warning(
                        "ZMQ bridge: %s",
                        d.get("message", "command timeout"),
                    )
                    continue
                if msg_type == "warning":
                    logger.warning("ZMQ bridge: %s", d.get("message", ""))
                    continue
                self._last_reading_time = time.monotonic()
                reading = self._with_bridge_incarnation(_reading_from_dict(d))
                envelope_payload = d.get("descriptor_envelope")
                qualified = qualify_reading_descriptor(
                    reading,
                    envelope_payload,
                    envelope_present=(envelope_payload is not None or d.get("descriptor_envelope_malformed") is True),
                    malformed_at_boundary=d.get("descriptor_envelope_malformed") is True,
                )
                if qualified.descriptor_issue is not None:
                    self._descriptor_malformed_count += 1
                paired.append(qualified)
            except (queue.Empty, EOFError):
                break
            except Exception as exc:
                logger.warning("poll_readings_with_descriptor: error processing item: %s", exc)
                continue
        return paired

    @property
    def descriptor_malformed_count(self) -> int:
        """Count of readings whose descriptor envelope failed to decode/verify."""
        return self._descriptor_malformed_count

    @property
    def bridge_instance_id(self) -> str | None:
        """Exact GUI-side bridge incarnation, or ``None`` after shutdown."""
        return self._bridge_instance_id

    def _with_bridge_incarnation(self, reading: Reading) -> Reading:
        bridge_instance_id = self._bridge_instance_id
        if bridge_instance_id is None:
            raise RuntimeError("received Reading before bridge incarnation was established")
        metadata = {**reading.metadata, "bridge_instance_id": bridge_instance_id}
        return Reading(
            timestamp=reading.timestamp,
            instrument_id=reading.instrument_id,
            channel=reading.channel,
            value=reading.value,
            unit=reading.unit,
            status=reading.status,
            raw=reading.raw,
            metadata=metadata,
        )

    def heartbeat_stale(self, *, timeout_s: float = 30.0) -> bool:
        """Return True if the bridge heartbeat is older than ``timeout_s``."""
        return self._last_heartbeat != 0.0 and (time.monotonic() - self._last_heartbeat) >= timeout_s

    def poll_operator_snapshots(self) -> list[OperatorSnapshot]:
        """Drain complete snapshots decoded in the subprocess; never synthesize."""
        snapshots: list[OperatorSnapshot] = []
        while True:
            try:
                snapshot = self._snapshot_queue.get_nowait()
            except (queue.Empty, EOFError, OSError):
                break
            try:
                if type(snapshot) is not OperatorSnapshot:
                    observed = _increment_shared_counter(self._snapshot_malformed_count)
                    if observed is not None:
                        self._snapshot_malformed_count_cached = observed
                    continue
                snapshots.append(snapshot)
                self._last_snapshot_time = time.monotonic()
            finally:
                self._snapshot_queue.task_done()
        return snapshots

    def snapshot_flow_age_s(self) -> float | None:
        """Monotonic age of the last valid cut, or None before first receipt."""
        if self._last_snapshot_time == 0.0:
            return None
        return max(0.0, time.monotonic() - self._last_snapshot_time)

    def snapshot_flow_stalled(self, *, timeout_s: float = 30.0) -> bool:
        """Snapshot presentation is stale after first flow; never a restart signal."""
        age = self.snapshot_flow_age_s()
        return age is not None and age >= timeout_s

    def snapshot_flow_healthy(self, *, timeout_s: float = 30.0) -> bool:
        """Independent presentation-flow health; intentionally not bridge health."""
        age = self.snapshot_flow_age_s()
        return self.is_alive() and age is not None and age < timeout_s

    @property
    def snapshot_malformed_count(self) -> int:
        observed = _read_shared_counter(
            self._snapshot_malformed_count,
            self._snapshot_malformed_count_cached,
        )
        self._snapshot_malformed_count_cached = observed
        return observed

    @property
    def snapshot_drop_count(self) -> int:
        observed = _read_shared_counter(
            self._snapshot_drop_count,
            self._snapshot_drop_count_cached,
        )
        self._snapshot_drop_count_cached = observed
        return observed

    def data_flow_stalled(self, *, timeout_s: float = 30.0) -> bool:
        """Return True if readings previously flowed but are now stale."""
        return self._last_reading_time != 0.0 and (time.monotonic() - self._last_reading_time) >= timeout_s

    def command_channel_stalled(self, *, timeout_s: float = 10.0) -> bool:
        """Return True if a command timeout occurred within the last
        ``timeout_s`` seconds.

        IV.6 B1 fix: used by launcher watchdog to detect command-channel-
        only failures (data plane still healthy but commands fail). Single
        recent timeout is enough to trigger — streak-count threshold may
        be introduced later if field testing shows false positives.
        """
        if self._last_cmd_timeout == 0.0:
            return False
        return (time.monotonic() - self._last_cmd_timeout) < timeout_s

    def is_healthy(self) -> bool:
        """True if subprocess is alive and bridge heartbeats are fresh."""
        return self.is_alive() and not self.heartbeat_stale()

    def restart_count(self) -> int:
        """Return the number of bridge restarts since launcher start."""
        return self._restart_count

    def process_pid(self) -> int | None:
        """Return the current bridge PID as a read-only identity hint.

        PID alone is never signal authority; the soak observer must combine it
        with an independently re-resolved OS start identity.
        """

        if self._process is None or not self._process.is_alive():
            return None
        pid = self._process.pid
        return pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None

    def send_command(
        self,
        cmd: dict,
        *,
        cancellation_requested: threading.Event | None = None,
    ) -> dict:
        """Thread-safe command dispatch with cancellation-aware settlement.

        A GUI worker may abandon its own wait during controlled shutdown.  Its
        correlation entry is then removed, so a late reply cannot be delivered
        to a new owner or treated as current command truth.
        """
        if not self.is_alive():
            return {"ok": False, "error": "ZMQ bridge subprocess not running"}

        future: Future = Future()

        with self._pending_lock:
            if len(self._outcome_unknown) >= _MAX_UNRESOLVED_COMMANDS:
                return {
                    "ok": False,
                    "error": "ZMQ unresolved command capacity exhausted",
                }
            rid = uuid.uuid4().hex
            while rid in self._pending or rid in self._outcome_unknown or rid in self._late_results:
                rid = uuid.uuid4().hex
            self._pending[rid] = future
            self._request_generation[rid] = self._generation
            generation = self._generation
        cmd = {**cmd, "_rid": rid, "_bridge_generation": generation}

        enqueued = False
        try:
            self._cmd_queue.put(cmd, timeout=2.0)
            enqueued = True
            deadline = time.monotonic() + _CMD_REPLY_TIMEOUT_S
            while True:
                if cancellation_requested is not None and cancellation_requested.is_set():
                    with self._pending_lock:
                        self._pending.pop(rid, None)
                        self._outcome_unknown[rid] = future
                    return {
                        "ok": False,
                        "error": "ZMQ command outcome unknown after cancellation",
                        "request_id": rid,
                    }
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    with self._pending_lock:
                        self._pending.pop(rid, None)
                        self._outcome_unknown[rid] = future
                    return {
                        "ok": False,
                        "error": "ZMQ command outcome unknown after timeout",
                        "request_id": rid,
                    }
                try:
                    return future.result(timeout=min(0.05, remaining))
                except TimeoutError:
                    continue
        except Exception as exc:
            return {"ok": False, "error": f"Engine не отвечает ({type(exc).__name__}: {exc})"}
        finally:
            if not enqueued:
                with self._pending_lock:
                    self._pending.pop(rid, None)
                    self._request_generation.pop(rid, None)

    def _check_proto(self, reply: dict[str, Any]) -> None:
        """Warn once if a server's ``proto`` is newer than this client knows.

        Never blocks and never drops the reply — an operator-facing command
        path must not stall on a version check (see docs/protocol.md). A
        missing/non-int ``proto`` from an older server is silently fine —
        this is a forward-compat check only.
        """
        if self._proto_warned:
            return
        proto = reply.get("proto")
        if isinstance(proto, int) and proto > CLIENT_PROTOCOL_VERSION:
            self._proto_warned = True
            logger.warning(
                "ZMQ server proto %d is newer than this client's %d — "
                "some newer reply fields may be ignored; see docs/protocol.md.",
                proto,
                CLIENT_PROTOCOL_VERSION,
            )

    def _consume_replies(self) -> None:
        """Dedicated thread: reads replies from subprocess, routes to correct Future."""
        while not self._reply_stop.is_set():
            try:
                reply = self._reply_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                break

            try:
                if not isinstance(reply, dict):
                    logger.warning("ZMQ reply consumer: non-dict reply: %r", type(reply))
                    continue
                self._check_proto(reply)
                rid = reply.get("_rid")
                if rid:
                    with self._pending_lock:
                        pending_owner = self._pending.pop(rid, None)
                        unknown_owner = self._outcome_unknown.get(rid)
                        future = pending_owner or unknown_owner
                        generation = self._request_generation.get(rid, self._generation)
                        clean_reply = {key: value for key, value in reply.items() if key != "_rid"}
                        if unknown_owner is not None:
                            self._late_results[rid] = LateCommandResult(rid, generation, clean_reply)
                        else:
                            self._request_generation.pop(rid, None)
                    if future and not future.done():
                        future.set_result(clean_reply)
                        continue
                logger.debug("Unmatched ZMQ reply (rid=%s)", rid)
            except Exception:
                logger.exception("ZMQ reply consumer: error processing reply")

    def shutdown(self) -> None:
        """Signal subprocess to stop, cancel pending futures, wait for exit."""
        with self._pending_lock:
            for rid, future in tuple(self._pending.items()):
                if not future.done():
                    future.set_result({"ok": False, "error": "ZMQ bridge shutting down"})
                self._outcome_unknown[rid] = future
            self._pending.clear()
            while True:
                try:
                    reply = self._reply_queue.get_nowait()
                except (queue.Empty, EOFError, OSError):
                    break
                if isinstance(reply, dict):
                    rid = reply.get("_rid")
                    if isinstance(rid, str) and rid in self._outcome_unknown:
                        generation = self._request_generation.get(rid, self._generation)
                        self._late_results[rid] = LateCommandResult(
                            rid,
                            generation,
                            {key: value for key, value in reply.items() if key != "_rid"},
                        )
        # Stop reply consumer thread after queued replies are retained.
        self._reply_stop.set()
        if self._reply_consumer is not None and self._reply_consumer.is_alive():
            self._reply_consumer.join(timeout=3.0)

        # Stop subprocess
        self._shutdown_event.set()
        if self._process is not None:
            self._process.join(timeout=3)
            if self._process.is_alive():
                logger.warning("ZMQ bridge subprocess did not exit, killing")
                self._process.kill()
                self._process.join(timeout=2)
            # Hardening 2026-04-21: log exit code for B1 diagnostic
            exit_code = self._process.exitcode
            if exit_code is not None:
                logger.info("ZMQ bridge subprocess stopped (exitcode=%s)", exit_code)
            else:
                logger.warning("ZMQ bridge subprocess stopped (exitcode=None after kill)")
            self._process = None
        else:
            logger.info("ZMQ bridge subprocess stopped")
        self._last_snapshot_time = 0.0
        self._bridge_instance_id = None

    def reconcile_late_result(self, request_id: str, *, generation: int | None = None) -> LateCommandResult | None:
        """Consume one exact late result after the mutation owner reconciles it."""
        with self._pending_lock:
            result = self._late_results.get(request_id)
            if result is None or (generation is not None and result.generation != generation):
                return None
            self._late_results.pop(request_id, None)
            self._outcome_unknown.pop(request_id, None)
            self._request_generation.pop(request_id, None)
            return result


def _drain(q: Any, *, task_done: bool = False) -> None:
    """Drain a multiprocessing Queue, ignoring errors."""
    while True:
        try:
            q.get_nowait()
            if task_done:
                q.task_done()
        except (queue.Empty, EOFError, OSError):
            break


# --- Backwards-compatible API used by keithley_panel and other GUI widgets ---

_bridge: ZmqBridge | None = None


def set_bridge(bridge: ZmqBridge) -> None:
    """Set the global bridge instance. Called once at GUI startup."""
    global _bridge
    _bridge = bridge


def _on_qt_main_thread() -> bool:
    """True if running on the Qt GUI thread (best-effort; False if Qt is absent)."""
    try:
        from PySide6.QtCore import QCoreApplication, QThread

        app = QCoreApplication.instance()
        return app is not None and QThread.currentThread() is app.thread()
    except Exception:
        return False


def send_command(
    cmd: dict,
    *,
    cancellation_requested: threading.Event | None = None,
) -> dict:
    """Send a command via the global bridge. BLOCKING — may take up to ~65 s
    (the outer REQ reply timeout).

    Contract: GUI code MUST call this from a background ``ZmqCommandWorker``,
    NEVER the Qt main thread — a main-thread call freezes the UI for the whole
    timeout. The guard below logs if that contract is ever violated so the
    misuse is caught in development rather than as a frozen UI in the field.
    """
    if _on_qt_main_thread():
        logger.warning(
            "send_command() called on the Qt main thread — it blocks up to ~65s "
            "and will freeze the UI; route it through a ZmqCommandWorker."
        )
    if _bridge is None:
        return {"ok": False, "error": "ZMQ bridge not initialized"}
    return _bridge.send_command(cmd, cancellation_requested=cancellation_requested)


def shutdown() -> None:
    """Shutdown the global bridge."""
    if _bridge is not None:
        _bridge.shutdown()


class ZmqCommandWorker(QThread):
    """Background thread for non-blocking ZMQ commands (unchanged API)."""

    finished = Signal(dict)

    def __init__(self, cmd: dict, parent=None) -> None:
        super().__init__(parent)
        self._cmd = cmd
        self._cancellation_requested = threading.Event()

    def requestInterruption(self) -> None:
        """Make an in-flight command wait observe controlled teardown."""
        self._cancellation_requested.set()
        super().requestInterruption()

    def run(self) -> None:
        result = send_command(self._cmd, cancellation_requested=self._cancellation_requested)
        if not self.isInterruptionRequested():
            self.finished.emit(result)
