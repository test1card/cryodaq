"""ZMQ bridge client for GUI — all ZMQ lives in a subprocess.

The GUI process never imports zmq. Communication with the subprocess
is via multiprocessing.Queue. If libzmq crashes (signaler.cpp assertion
on Windows), only the subprocess dies — GUI detects and restarts it.
"""

from __future__ import annotations

import contextlib
import logging
import math
import multiprocessing as mp
import queue
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot

from cryodaq.core.command_authority import (
    ASSISTANT_READ_ACTIONS,
    ENGINE_MUTATION_CAPABILITY,
    MUTATION_ENVELOPE_KEYS,
    MUTATION_PROTOCOL_MAJOR,
    MUTATION_RECEIPT_SCHEMA,
    REPLAY_MUTATION_CAPABILITY,
    CommandClass,
    SafeDirectionKind,
    classify_client_command,
    exact_safe_direction_kind,
    is_assistant_namespaced,
    is_exact_safe_direction_envelope,
    is_preemptive_safe_direction,
    strip_mutation_envelope,
)
from cryodaq.core.descriptor_transport import (
    DescriptorQualifiedReading,
    qualify_reading_descriptor,
)
from cryodaq.core.safe_command_ipc import (
    SafeIpcConstructionError,
    create_safe_command_ipc,
)
from cryodaq.core.zmq_endpoints import require_distinct_loopback_tcp_endpoints
from cryodaq.core.zmq_subprocess import (
    DEFAULT_ASSISTANT_CMD_ADDR,
    DEFAULT_CMD_ADDR,
    DEFAULT_PUB_ADDR,
    DEFAULT_SAFE_CMD_ADDR,
    READING_RECEIVED_MONOTONIC_KEY,
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
CLIENT_PROTOCOL_VERSION = 2
_COUNTER_LOCK_TIMEOUT_S = 0.01
_MUTATION_PROTOCOL_MAJOR = MUTATION_PROTOCOL_MAJOR
_MUTATION_CAPABILITY = ENGINE_MUTATION_CAPABILITY
_REPLAY_MUTATION_CAPABILITY = REPLAY_MUTATION_CAPABILITY
_MUTATION_RECEIPT_SCHEMA = MUTATION_RECEIPT_SCHEMA
_MUTATION_ENVELOPE_KEYS = MUTATION_ENVELOPE_KEYS

_MAX_UNRESOLVED_COMMANDS = 1024
_MAX_RESERVED_SAFE_COMMANDS = 16
_MAX_GLOBAL_OFF_COMMANDS = 1
_MAX_LAUNCHER_SHUTDOWN_COMMANDS = 1
_MAX_RETAINED_RESULTS_PER_LANE = 1024
_SAFE_COMMAND_QUEUE_CAPACITY = _MAX_RESERVED_SAFE_COMMANDS + _MAX_GLOBAL_OFF_COMMANDS + _MAX_LAUNCHER_SHUTDOWN_COMMANDS
_PUBLICATION_SETTLEMENT_TIMEOUT_S = 3.0
_MAX_PUBLIC_ERROR_CHARS = 256
_EMERGENCY_OFF_ACTION = "keithley_emergency_off"
_LAUNCHER_SHUTDOWN_ACTION = "launcher_shutdown"


def _bounded_public_error(value: object, fallback: str) -> str:
    """Return one bounded, single-line, printable GUI error string."""

    if type(value) is not str:
        return fallback
    cleaned = " ".join(value.split())
    cleaned = "".join(char for char in cleaned if char.isprintable())
    if not cleaned:
        return fallback
    return cleaned[:_MAX_PUBLIC_ERROR_CHARS]


def _sanitize_command_reply(reply: dict[str, Any]) -> dict[str, Any]:
    """Remove multiline/control-text injection at the subprocess boundary."""

    sanitized = dict(reply)
    if "error" in sanitized:
        sanitized["error"] = _bounded_public_error(
            sanitized["error"],
            "Command failed without a public error description.",
        )
    if "reason" in sanitized:
        sanitized["reason"] = _bounded_public_error(
            sanitized["reason"],
            "Command was refused.",
        )
    return sanitized


def _bounded_request_label(value: object) -> str:
    if type(value) is str and len(value) == 32 and all(char in "0123456789abcdef" for char in value):
        return value
    return "<invalid>"


def _bounded_exception_type(error: BaseException | None) -> str:
    """Return a log-safe bounded exception class label."""

    if error is None:
        return "UnexpectedReturn"
    label = type(error).__name__
    if not label or len(label) > 64 or not label.isascii() or not label.isidentifier():
        return "Exception"
    return label


def _is_exact_safe_direction_command(command: dict[str, Any]) -> bool:
    """Compatibility wrapper around the canonical transport classifier."""

    return is_exact_safe_direction_envelope(command)


def _safe_direction_rejection() -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": "safe_direction_envelope_invalid",
        "error": "Safe-direction command envelope is invalid; command was not dispatched",
        "dispatched": False,
        "delivery_state": "not_dispatched",
        "commit_state": "not_committed",
        "retry_safe": False,
    }


def _bridge_lifecycle_rejection() -> dict[str, Any]:
    return {
        "ok": False,
        "error_code": "bridge_lifecycle_retired",
        "error": "ZMQ bridge command admission is closed for this lifecycle",
        "dispatched": False,
        "delivery_state": "not_dispatched",
        "commit_state": "not_committed",
        "retry_safe": False,
    }


def _put_ipc_nowait(channel: Any, item: object) -> None:
    """Publish without ever blocking the shared lifecycle/admission lock."""

    channel.put_nowait(item)


@dataclass(frozen=True, slots=True)
class LateCommandResult:
    """Typed, generation-bound result retained after owner cancellation."""

    request_id: str
    generation: int
    reply: dict[str, Any]
    command_class: CommandClass = field(default=CommandClass.MUTATION, compare=False, repr=False)
    action: str = field(default="<unknown>", compare=False, repr=False)
    safe_scope: str | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True, slots=True)
class _RequestBinding:
    """Immutable authority identity for one tracked GUI request."""

    generation: int
    command_class: CommandClass
    action: str
    safe_scope: str | None = None


@dataclass(frozen=True, slots=True)
class _BridgeGenerationFatal:
    """Generation-bound proof that one mandatory reply lane was lost."""

    generation: int
    lane: str
    error_type: str


def _capacity_lane(
    command_class: CommandClass,
    action: str,
    safe_scope: str | None,
) -> str:
    if command_class is not CommandClass.SAFE_DIRECTION:
        return "ordinary"
    if action == _LAUNCHER_SHUTDOWN_ACTION:
        return "launcher_shutdown"
    if safe_scope == "channel":
        return "targeted_off"
    return "global_off"


def _uses_preemptive_transport_lane(
    command_class: CommandClass,
    safe_scope: str | None,
) -> bool:
    return command_class is CommandClass.SAFE_DIRECTION and safe_scope in {
        "channel",
        "global",
        "launcher",
    }


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


def _metadata_with_transport_age(d: dict[str, Any]) -> object:
    metadata = d.get("metadata", {})
    if type(metadata) is not dict or not str(d.get("channel", "")).startswith("analytics/"):
        return metadata

    public = dict(metadata)
    source_age_s = public.get("source_age_s")
    received_s = d.get(READING_RECEIVED_MONOTONIC_KEY)
    if type(source_age_s) not in (int, float) or type(received_s) not in (int, float):
        public.pop("source_age_s", None)
        return public

    queue_age_s = time.monotonic() - float(received_s)
    total_age_s = float(source_age_s) + queue_age_s
    if (
        not math.isfinite(float(source_age_s))
        or float(source_age_s) < 0
        or not math.isfinite(total_age_s)
        or total_age_s < 0
        or (queue_age_s is not None and (not math.isfinite(queue_age_s) or queue_age_s < 0))
    ):
        public.pop("source_age_s", None)
    else:
        public["source_age_s"] = total_age_s
    return public


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
        metadata=_metadata_with_transport_age(d),
    )


ReadingWithDescriptor = DescriptorQualifiedReading


def _join_mp_queue_feeder(ipc_queue: Any, *, label: str) -> None:
    """Require terminal proof for one closed multiprocessing queue feeder."""

    feeder = getattr(ipc_queue, "_thread", None)
    if feeder is not None:
        join = getattr(feeder, "join", None)
        is_alive = getattr(feeder, "is_alive", None)
        if not callable(join) or not callable(is_alive):
            raise TypeError(f"{label} feeder does not expose join/is_alive")
        join(timeout=2.0)
        if is_alive() is not False:
            raise RuntimeError(f"{label} feeder remained alive after bounded join")
    join_thread = getattr(ipc_queue, "join_thread", None)
    if not callable(join_thread):
        raise TypeError(f"{label} does not expose join_thread")
    join_thread()


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
        safe_cmd_addr: str = DEFAULT_SAFE_CMD_ADDR,
    ) -> None:
        require_distinct_loopback_tcp_endpoints(
            pub=pub_addr,
            ordinary_command=cmd_addr,
            assistant_command=assistant_cmd_addr,
            safe_command=safe_cmd_addr,
        )
        self._pub_addr = pub_addr
        self._cmd_addr = cmd_addr
        # B1: assistant.*/rag.* commands route here instead — see
        # core/zmq_subprocess.py's cmd_forward_loop. Defaulted so no
        # call site needs to change to pick this up.
        self._assistant_cmd_addr = assistant_cmd_addr
        self._safe_cmd_addr = safe_cmd_addr
        self._data_queue: mp.Queue = mp.Queue(maxsize=10_000)
        self._cmd_queue: mp.Queue = mp.Queue(maxsize=1_000)
        self._reply_queue: mp.Queue = mp.Queue(maxsize=1_000)
        safe_ipc = create_safe_command_ipc(_SAFE_COMMAND_QUEUE_CAPACITY)
        self._safe_cmd_queue = safe_ipc.parent_command_sender
        self._safe_cmd_child_receiver = safe_ipc.child_command_receiver
        self._safe_reply_queue = safe_ipc.parent_reply_receiver
        self._safe_reply_child_sender = safe_ipc.child_reply_sender
        self._safe_ipc_retired_closed = False
        # Closed child endpoint copies whose semaphores must outlive
        # Process.start(); see _close_child_safe_endpoint_copies_locked.
        self._child_endpoint_retention: list[Any] = []
        self._restart_queue_closure_proofs: set[str] = set()
        self._restart_queue_candidates: dict[str, Any] = {}
        self._restart_safe_ipc_candidate: Any | None = None
        self._restart_safe_ipc_construction_failure: SafeIpcConstructionError | None = None
        self._snapshot_queue = mp.JoinableQueue(maxsize=2)
        self._snapshot_malformed_count = mp.Value("Q", 0, lock=True)
        self._snapshot_drop_count = mp.Value("Q", 0, lock=True)
        self._snapshot_malformed_count_cached = 0
        self._snapshot_drop_count_cached = 0
        self._shutdown_event: mp.Event = mp.Event()
        self._process: mp.Process | None = None
        self._process_started = False
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
        self._request_bindings: dict[str, _RequestBinding] = {}
        self._late_results: dict[str, LateCommandResult] = {}
        self._lifecycle_lock = threading.RLock()
        self._pending_lock = threading.Lock()
        self._publication_condition = threading.Condition()
        self._publication_lane_locks = {
            "ordinary": threading.Lock(),
            "safe": threading.Lock(),
        }
        self._inflight_publications = {
            "ordinary": 0,
            "safe": 0,
        }
        self._command_admission_open = False
        self._mutation_lock = threading.Lock()
        self._mutation_receipt: dict[str, Any] | None = None
        self._verified_replay_scope: dict[str, Any] | None = None
        self._reply_stop = threading.Event()
        self._reply_consumer: threading.Thread | None = None
        self._safe_reply_consumer: threading.Thread | None = None
        self._reply_consumer_started = False
        self._safe_reply_consumer_started = False
        self._generation_fatal: _BridgeGenerationFatal | None = None
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
        self._terminal_closed = False
        self._terminal_shutdown_settled = False
        self._terminal_queues_closed: set[str] = set()
        self._terminal_queues_joined: set[str] = set()
        # A bridge restart is a new presentation authority.  The subprocess
        # wire data cannot choose this value: it is attached only after a
        # Reading has crossed into this GUI-side bridge instance.
        self._bridge_instance_id: str | None = None
        self._generation = 0

    def start(self) -> None:
        """Start the ZMQ bridge subprocess."""
        with self._lifecycle_lock:
            self._start_locked()

    def _raw_process_is_alive_locked(self) -> bool:
        """Inspect only an owner whose successful ``start`` is proven."""

        process = self._process
        if process is None or not self._process_started:
            return False
        try:
            return bool(process.is_alive())
        except Exception:
            return False

    def _reply_consumers_are_alive_locked(self) -> bool:
        owners = (
            (self._reply_consumer, self._reply_consumer_started),
            (self._safe_reply_consumer, self._safe_reply_consumer_started),
        )
        for consumer, started in owners:
            if consumer is None or not started:
                return False
            try:
                if not consumer.is_alive():
                    return False
            except Exception:
                return False
        return True

    def _record_generation_fatal(
        self,
        *,
        reply_queue: Any,
        lane: str,
        source_generation: int,
        error: BaseException | None,
    ) -> None:
        """Atomically retire a generation whose mandatory reply lane died."""

        expected_queue = {
            "ordinary": self._reply_queue,
            "safe": self._safe_reply_queue,
            "safe_command": self._safe_cmd_queue,
        }.get(lane)
        with self._pending_lock:
            if (
                expected_queue is None
                or source_generation != self._generation
                or reply_queue is not expected_queue
                or self._reply_stop.is_set()
            ):
                return
            if self._generation_fatal is None or self._generation_fatal.generation != source_generation:
                self._generation_fatal = _BridgeGenerationFatal(
                    source_generation,
                    lane,
                    _bounded_exception_type(error),
                )
            self._command_admission_open = False
            self._reply_stop.set()
            self._settle_pending_for_lifecycle_locked(
                error=f"ZMQ {lane} transport lane failed; outcome unknown",
                default_generation=source_generation,
            )
        self._last_snapshot_time = 0.0
        self._bridge_instance_id = None
        self._invalidate_mutation_compatibility()
        try:
            self._shutdown_event.set()
        except Exception as shutdown_error:
            logger.error(
                "ZMQ reply-lane fatal could not signal child: lane=%s exception=%s",
                lane,
                _bounded_exception_type(shutdown_error),
            )
        logger.error(
            "ZMQ transport lane retired bridge generation: lane=%s generation=%d exception=%s",
            lane,
            source_generation,
            _bounded_exception_type(error),
        )

    def _close_child_safe_endpoint_copies_locked(self) -> None:
        """Close child-only endpoint copies retained by the parent process.

        The pipe handles are released immediately: the parent must not keep
        the child's receiving end open, or the child never observes EOF when
        the parent dies.

        The closed endpoint object itself is *retained* until the generation
        is finalized, because it owns that endpoint's POSIX semaphores. Under
        the ``fork`` start method dropping it here was safe -- the child is a
        complete copy the instant ``Process.start()`` returns. Under ``spawn``
        and ``forkserver`` (the Linux default from Python 3.14, and what
        Windows always uses) ``start()`` only *writes* the pickle; the child
        rebuilds each semaphore later, by name. Releasing the last parent
        reference here runs the finalizer, ``sem_unlink`` removes the name,
        and the child's ``SemLock._rebuild`` raises FileNotFoundError before
        the bridge runs a single line. Windows never showed this: there the
        handle is duplicated into the child at pickle time, so the child
        performs no name lookup.
        """

        for attribute in (
            "_safe_cmd_child_receiver",
            "_safe_reply_child_sender",
        ):
            endpoint = getattr(self, attribute, None)
            if endpoint is None:
                continue
            endpoint.close()
            self._child_endpoint_retention.append(endpoint)
            setattr(self, attribute, None)

    def _release_child_endpoint_retention_locked(self) -> None:
        """Drop closed child endpoint copies once the generation is finalized.

        Sound only where the parent has stopped managing the child process: by
        then the child has either rebuilt its semaphores or died, so the names
        are no longer needed by anyone.
        """

        self._child_endpoint_retention.clear()

    def _close_safe_ipc_locked(self) -> None:
        """Close every endpoint of the retired parent-side channel bundle."""

        if self._safe_ipc_retired_closed:
            return
        self._close_child_safe_endpoint_copies_locked()
        for attribute in ("_safe_cmd_queue", "_safe_reply_queue"):
            endpoint = getattr(self, attribute, None)
            if endpoint is not None:
                # Preserve the exact owner and abort replacement if close
                # fails.  Directional endpoint close is retryable: it marks
                # itself closed only after the underlying handle settles.
                endpoint.close()
        self._safe_ipc_retired_closed = True

    def _install_safe_ipc_locked(self, safe_ipc: Any) -> None:
        """Install one complete candidate after the retired bundle settles."""

        self._safe_cmd_queue = safe_ipc.parent_command_sender
        self._safe_cmd_child_receiver = safe_ipc.child_command_receiver
        self._safe_reply_queue = safe_ipc.parent_reply_receiver
        self._safe_reply_child_sender = safe_ipc.child_reply_sender
        self._safe_ipc_retired_closed = False

    def _close_retired_mp_queue_locked(
        self,
        attribute: str,
        *,
        drain_before_close: bool,
        task_done: bool = False,
    ) -> None:
        """Prove one retired queue and its feeder terminal before replacement."""

        if attribute in self._restart_queue_closure_proofs:
            return
        old_queue = getattr(self, attribute)
        if drain_before_close:
            _drain(old_queue, task_done=task_done)
        old_queue.close()
        _join_mp_queue_feeder(old_queue, label=f"retired {attribute} queue")
        self._restart_queue_closure_proofs.add(attribute)

    def _settle_restart_candidates_locked(self) -> None:
        """Close every uninstalled candidate or retain each failed owner."""

        failures: list[str] = []
        first_error: BaseException | None = None

        def record(label: str, error: BaseException) -> None:
            nonlocal first_error
            failures.append(f"{label}:{type(error).__name__}")
            if first_error is None:
                first_error = error

        for attribute, candidate in tuple(self._restart_queue_candidates.items()):
            try:
                candidate.close()
                _join_mp_queue_feeder(candidate, label=f"candidate {attribute} queue")
            except BaseException as exc:
                record(attribute, exc)
            else:
                if self._restart_queue_candidates.get(attribute) is candidate:
                    self._restart_queue_candidates.pop(attribute, None)

        safe_candidate = self._restart_safe_ipc_candidate
        if safe_candidate is not None:
            safe_failed = False
            for label, endpoint in (
                ("safe_command_sender", safe_candidate.parent_command_sender),
                ("safe_command_receiver", safe_candidate.child_command_receiver),
                ("safe_reply_receiver", safe_candidate.parent_reply_receiver),
                ("safe_reply_sender", safe_candidate.child_reply_sender),
            ):
                try:
                    endpoint.close()
                except BaseException as exc:
                    safe_failed = True
                    record(label, exc)
            if not safe_failed and self._restart_safe_ipc_candidate is safe_candidate:
                self._restart_safe_ipc_candidate = None

        construction_failure = self._restart_safe_ipc_construction_failure
        if construction_failure is not None:
            try:
                construction_failure.settle_retained_endpoints()
            except BaseException as exc:
                record("safe_ipc_construction", exc)
            else:
                if self._restart_safe_ipc_construction_failure is construction_failure:
                    self._restart_safe_ipc_construction_failure = None

        if failures:
            error = RuntimeError("ZMQ bridge replacement candidate cleanup incomplete: " + "; ".join(failures))
            assert first_error is not None
            raise error from first_error

    def _construct_and_install_restart_bundle_locked(self) -> None:
        """Atomically construct and install one complete queue generation."""

        if (
            self._restart_queue_candidates
            or self._restart_safe_ipc_candidate is not None
            or self._restart_safe_ipc_construction_failure is not None
        ):
            raise RuntimeError("ZMQ bridge replacement candidates must settle before reconstruction")
        factories: tuple[tuple[str, Callable[[], Any]], ...] = (
            ("_snapshot_queue", lambda: mp.JoinableQueue(maxsize=2)),
            ("_data_queue", lambda: mp.Queue(maxsize=10_000)),
            ("_cmd_queue", lambda: mp.Queue(maxsize=1_000)),
            ("_reply_queue", lambda: mp.Queue(maxsize=1_000)),
        )
        try:
            for attribute, factory in factories:
                self._restart_queue_candidates[attribute] = factory()
            self._restart_safe_ipc_candidate = create_safe_command_ipc(_SAFE_COMMAND_QUEUE_CAPACITY)
        except BaseException as construction_error:
            if isinstance(construction_error, SafeIpcConstructionError):
                self._restart_safe_ipc_construction_failure = construction_error
            try:
                self._settle_restart_candidates_locked()
            except BaseException as cleanup_error:
                raise RuntimeError(
                    "ZMQ bridge replacement construction and cleanup failed: "
                    f"construction={type(construction_error).__name__}; "
                    f"cleanup={type(cleanup_error).__name__}"
                ) from cleanup_error
            raise

        for attribute, _factory in factories:
            setattr(self, attribute, self._restart_queue_candidates[attribute])
        self._restart_queue_candidates.clear()
        safe_candidate = self._restart_safe_ipc_candidate
        assert safe_candidate is not None
        self._install_safe_ipc_locked(safe_candidate)
        self._restart_safe_ipc_candidate = None
        self._restart_queue_closure_proofs.clear()

    def _claim_publication_locked(self, lane: str) -> Any:
        """Claim one generation publisher while admission is still locked."""

        lane_lock = self._publication_lane_locks.get(lane)
        if lane_lock is None:
            raise RuntimeError("unknown ZMQ publication lane")
        with self._publication_condition:
            self._inflight_publications[lane] += 1
        return lane_lock

    def _release_publication(self, lane: str) -> None:
        """Release one publisher only after queue and ledger disposition."""

        with self._publication_condition:
            count = self._inflight_publications.get(lane)
            if count is None or count <= 0:
                raise RuntimeError("ZMQ publication ownership underflow")
            self._inflight_publications[lane] = count - 1
            self._publication_condition.notify_all()

    def _wait_for_publications_to_settle_locked(self) -> None:
        """Wait boundedly for all admitted publishers before queue retirement."""

        deadline = time.monotonic() + _PUBLICATION_SETTLEMENT_TIMEOUT_S
        with self._publication_condition:
            while any(self._inflight_publications.values()):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    active = ", ".join(
                        f"{lane}={count}" for lane, count in self._inflight_publications.items() if count
                    )
                    raise RuntimeError(f"ZMQ publication settlement timed out: {active}")
                self._publication_condition.wait(remaining)

    def _settle_runtime_owners_locked(
        self,
        *,
        reason: str,
        finalize: bool = True,
    ) -> int | None:
        """Settle all started runtime owners or retain the complete owner set."""

        failures: list[str] = []
        first_error: BaseException | None = None

        def record_failure(message: str, error: BaseException | None = None) -> None:
            nonlocal first_error
            failures.append(message)
            if first_error is None and error is not None:
                first_error = error

        self._reply_stop.set()
        try:
            self._shutdown_event.set()
        except BaseException as exc:
            record_failure("shutdown signal could not be set", exc)

        consumers = (
            (
                "ordinary",
                self._reply_consumer,
                self._reply_consumer_started,
            ),
            (
                "safe",
                self._safe_reply_consumer,
                self._safe_reply_consumer_started,
            ),
        )
        for lane, consumer, started in consumers:
            if not started:
                continue
            if consumer is None:
                record_failure(f"{lane} reply consumer start proof has no owner")
                continue
            try:
                consumer.join(timeout=3.0)
                if consumer.is_alive():
                    record_failure(f"{lane} reply consumer remained alive after join")
            except BaseException as exc:
                record_failure(f"{lane} reply consumer settlement raised", exc)

        process = self._process
        if self._process_started:
            if process is None:
                record_failure("subprocess start proof has no owner")
            else:
                try:
                    process.join(timeout=3.0)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=2.0)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=2.0)
                    if process.is_alive():
                        record_failure("subprocess remained alive after kill and join")
                except BaseException as exc:
                    record_failure("subprocess settlement raised", exc)

        try:
            self._close_child_safe_endpoint_copies_locked()
        except BaseException as exc:
            record_failure("child-only safe IPC endpoint closure raised", exc)

        if not failures and finalize:
            try:
                with self._pending_lock:
                    if "_reply_queue" not in self._restart_queue_closure_proofs:
                        self._drain_replies_locked(
                            self._reply_queue,
                            source_generation=self._generation,
                            source_lane="ordinary",
                        )
                    if not self._safe_ipc_retired_closed:
                        self._drain_replies_locked(
                            self._safe_reply_queue,
                            source_generation=self._generation,
                            source_lane="safe",
                        )
            except BaseException as exc:
                record_failure("final reply queue drain raised", exc)

        if failures:
            detail = "; ".join(failures)
            incomplete = RuntimeError(f"{reason} incomplete: {detail}")
            if first_error is not None:
                raise incomplete from first_error
            raise incomplete

        exit_code: int | None = None
        if self._process_started and process is not None:
            with contextlib.suppress(Exception):
                candidate = process.exitcode
                if isinstance(candidate, int) and not isinstance(candidate, bool):
                    exit_code = candidate
        if not finalize:
            return exit_code
        self._reply_consumer = None
        self._safe_reply_consumer = None
        self._process = None
        self._reply_consumer_started = False
        self._safe_reply_consumer_started = False
        self._process_started = False
        # The parent has stopped managing this child; its semaphore names may
        # now be reclaimed.
        self._release_child_endpoint_retention_locked()
        return exit_code

    def _start_locked(self) -> None:
        """Start while holding the bridge lifecycle owner lock."""
        if self._terminal_closed:
            raise RuntimeError("ZMQ bridge was terminally closed and cannot restart")
        # A prior construction failure may retain uninstalled owners. Settle
        # them before touching either the retired or next live generation.
        self._settle_restart_candidates_locked()
        raw_process_alive = self._raw_process_is_alive_locked()
        consumers_alive = self._reply_consumers_are_alive_locked()
        with self._pending_lock:
            current_fatal = self._generation_fatal is not None and self._generation_fatal.generation == self._generation
            admission_open = self._command_admission_open
        if raw_process_alive and consumers_alive and admission_open and not current_fatal:
            return
        if raw_process_alive and not consumers_alive and not current_fatal:
            failed_lane = "safe"
            try:
                if (
                    self._reply_consumer is None
                    or not self._reply_consumer_started
                    or not self._reply_consumer.is_alive()
                ):
                    failed_lane = "ordinary"
            except Exception:
                failed_lane = "ordinary"
            self._record_generation_fatal(
                reply_queue=(self._reply_queue if failed_lane == "ordinary" else self._safe_reply_queue),
                lane=failed_lane,
                source_generation=self._generation,
                error=RuntimeError("reply consumer is not alive"),
            )
        retired_generation = self._generation
        with self._pending_lock:
            self._command_admission_open = False
        # Admission closure and publisher claims are ordered by the short
        # pending lock. Once closed, no new claim can appear; wait without
        # holding that lock so each lane can finish its exact disposition.
        self._wait_for_publications_to_settle_locked()
        with self._pending_lock:
            self._settle_pending_for_lifecycle_locked(
                error="bridge generation replaced; outcome unknown",
                default_generation=retired_generation,
            )
        self._invalidate_mutation_compatibility()
        self._last_snapshot_time = 0.0
        self._bridge_instance_id = None
        self._settle_runtime_owners_locked(
            reason="previous ZMQ runtime settlement",
            finalize=False,
        )
        self._close_retired_mp_queue_locked(
            "_snapshot_queue",
            drain_before_close=True,
            task_done=True,
        )
        for name in ("_data_queue", "_cmd_queue"):
            self._close_retired_mp_queue_locked(
                name,
                drain_before_close=True,
            )
        # Final reply routing must be the last retired-queue operation. A late
        # feeder delivery triggered while the other queues settle is therefore
        # observed before either reply queue can be replaced.
        self._settle_runtime_owners_locked(reason="previous ZMQ runtime final drain")
        self._close_retired_mp_queue_locked(
            "_reply_queue",
            drain_before_close=False,
        )
        self._close_safe_ipc_locked()
        self._construct_and_install_restart_bundle_locked()
        with self._pending_lock:
            self._generation += 1
            generation = self._generation
            self._command_admission_open = False
        self._shutdown_event.clear()
        self._reply_stop.clear()
        phase = "process construction"
        try:
            process = mp.Process(
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
                    self._safe_cmd_child_receiver,
                    self._safe_cmd_addr,
                    self._safe_reply_child_sender,
                    self._safe_cmd_queue,
                    self._safe_reply_queue,
                ),
                daemon=True,
                name="zmq_bridge",
            )
            reply_consumer = threading.Thread(
                target=self._consume_reply_queue,
                args=(self._reply_queue, "ordinary", generation),
                daemon=True,
                name="zmq-reply-consumer",
            )
            safe_reply_consumer = threading.Thread(
                target=self._consume_reply_queue,
                args=(self._safe_reply_queue, "safe", generation),
                daemon=True,
                name="zmq-safe-reply-consumer",
            )
            self._process = process
            self._reply_consumer = reply_consumer
            self._safe_reply_consumer = safe_reply_consumer
            self._process_started = False
            self._reply_consumer_started = False
            self._safe_reply_consumer_started = False

            phase = "process start"
            process.start()
            self._process_started = True
            self._close_child_safe_endpoint_copies_locked()
            if not self._raw_process_is_alive_locked():
                raise RuntimeError("ZMQ subprocess exited during startup")

            phase = "ordinary reply consumer start"
            reply_consumer.start()
            self._reply_consumer_started = True
            if not reply_consumer.is_alive():
                raise RuntimeError("ordinary reply consumer exited during startup")

            phase = "safe reply consumer start"
            safe_reply_consumer.start()
            self._safe_reply_consumer_started = True
            if not safe_reply_consumer.is_alive():
                raise RuntimeError("safe reply consumer exited during startup")

            with self._pending_lock:
                same_generation_fatal = (
                    self._generation_fatal is not None and self._generation_fatal.generation == generation
                )
                if (
                    generation != self._generation
                    or self._reply_stop.is_set()
                    or same_generation_fatal
                    or not self._process_started
                    or not self._reply_consumer_started
                    or not self._safe_reply_consumer_started
                    or not process.is_alive()
                    or not reply_consumer.is_alive()
                    or not safe_reply_consumer.is_alive()
                ):
                    raise RuntimeError("ZMQ runtime owners did not remain live through startup")
                self._generation_fatal = None
                self._bridge_instance_id = uuid.uuid4().hex
                self._last_heartbeat = time.monotonic()
                self._last_reading_time = 0.0
                self._command_admission_open = True
        except BaseException as start_error:
            with self._pending_lock:
                if self._generation_fatal is None or self._generation_fatal.generation != generation:
                    self._generation_fatal = _BridgeGenerationFatal(
                        generation,
                        phase,
                        _bounded_exception_type(start_error),
                    )
                self._command_admission_open = False
                self._settle_pending_for_lifecycle_locked(
                    error=f"ZMQ bridge startup failed during {phase}; outcome unknown",
                    default_generation=generation,
                )
            self._last_snapshot_time = 0.0
            self._bridge_instance_id = None
            self._reply_stop.set()
            try:
                self._settle_runtime_owners_locked(reason="ZMQ bridge startup rollback")
            except BaseException as rollback_error:
                raise RuntimeError(
                    "ZMQ bridge startup rollback incomplete: "
                    f"phase={phase}; start_error={_bounded_exception_type(start_error)}; "
                    f"rollback_error={_bounded_exception_type(rollback_error)}"
                ) from start_error
            raise RuntimeError(
                f"ZMQ bridge startup failed: phase={phase}; exception={_bounded_exception_type(start_error)}"
            ) from start_error

        self._restart_count += 1
        pid = process.pid
        logger.info(
            "ZMQ bridge subprocess started (PID=%d, restart_count=%d)",
            pid,
            self._restart_count,
        )

    def is_alive(self) -> bool:
        """Check if the subprocess is still running."""
        with self._pending_lock:
            if not self._command_admission_open or self._reply_stop.is_set():
                return False
            fatal = self._generation_fatal
            if fatal is not None and fatal.generation == self._generation:
                return False
            process = self._process
            process_started = self._process_started
            consumers = (
                (self._reply_consumer, self._reply_consumer_started),
                (self._safe_reply_consumer, self._safe_reply_consumer_started),
            )
        if process is None or not process_started:
            return False
        try:
            return bool(process.is_alive()) and all(
                consumer is not None and started and consumer.is_alive() for consumer, started in consumers
            )
        except Exception:
            return False

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
                    logger.warning("ZMQ bridge command timeout marker received")
                    continue
                if msg_type == "warning":
                    logger.warning("ZMQ bridge warning marker received")
                    continue
                reading = self._with_bridge_incarnation(_reading_from_dict(d))
                readings.append(reading)
                self._last_reading_time = time.monotonic()
            except (queue.Empty, EOFError):
                break
            except Exception as exc:
                logger.warning(
                    "poll_readings rejected one item: exception=%s",
                    type(exc).__name__,
                )
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
                    logger.warning("ZMQ bridge command timeout marker received")
                    continue
                if msg_type == "warning":
                    logger.warning("ZMQ bridge warning marker received")
                    continue
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
                self._last_reading_time = time.monotonic()
            except (queue.Empty, EOFError):
                break
            except Exception as exc:
                logger.warning(
                    "poll_readings_with_descriptor rejected one item: exception=%s",
                    type(exc).__name__,
                )
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
                if self._bridge_instance_id is None:
                    continue
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

        if not self.is_alive():
            return None
        process = self._process
        if process is None:
            return None
        pid = process.pid
        return pid if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 else None

    def _bindings_locked(self) -> dict[str, _RequestBinding]:
        bindings = getattr(self, "_request_bindings", None)
        if bindings is None:
            bindings = {}
            self._request_bindings = bindings
        return bindings

    def _binding_for_locked(
        self,
        request_id: str,
        *,
        default_generation: int | None = None,
    ) -> _RequestBinding:
        binding = self._bindings_locked().get(request_id)
        if binding is not None:
            return binding
        generation = self._request_generation.get(
            request_id,
            self._generation if default_generation is None else default_generation,
        )
        return _RequestBinding(generation, CommandClass.MUTATION, "<unknown>")

    def _release_request_identity_locked(self, request_id: str) -> None:
        self._request_generation.pop(request_id, None)
        self._bindings_locked().pop(request_id, None)

    def _has_request_capacity_locked(
        self,
        *,
        command_class: CommandClass,
        action: str,
        safe_scope: str | None,
    ) -> bool:
        requested_lane = _capacity_lane(command_class, action, safe_scope)
        active_count = 0
        retained_count = 0
        for request_id in set(self._pending) | set(self._outcome_unknown):
            binding = self._binding_for_locked(request_id)
            if _capacity_lane(binding.command_class, binding.action, binding.safe_scope) == requested_lane:
                active_count += 1
                retained_count += 1
        for result in self._late_results.values():
            if _capacity_lane(result.command_class, result.action, result.safe_scope) == requested_lane:
                retained_count += 1
        if retained_count >= _MAX_RETAINED_RESULTS_PER_LANE:
            return False
        active_limit = {
            "ordinary": _MAX_UNRESOLVED_COMMANDS,
            "targeted_off": _MAX_RESERVED_SAFE_COMMANDS,
            "global_off": _MAX_GLOBAL_OFF_COMMANDS,
            "launcher_shutdown": _MAX_LAUNCHER_SHUTDOWN_COMMANDS,
        }[requested_lane]
        return active_count < active_limit

    def _retire_read_owner_locked(self, request_id: str, future: Future) -> None:
        if self._pending.get(request_id) is future:
            self._pending.pop(request_id, None)
        if self._outcome_unknown.get(request_id) is future:
            self._outcome_unknown.pop(request_id, None)
        self._late_results.pop(request_id, None)
        self._release_request_identity_locked(request_id)

    def _retire_definitely_unsent_owner_locked(self, request_id: str, future: Future) -> bool:
        """Release only the exact owner proven never published to a queue."""

        removed = False
        if self._pending.get(request_id) is future:
            self._pending.pop(request_id, None)
            removed = True
        if self._outcome_unknown.get(request_id) is future:
            self._outcome_unknown.pop(request_id, None)
            removed = True
        if removed:
            self._release_request_identity_locked(request_id)
        return removed

    def _retain_unknown_owner_locked(self, request_id: str, future: Future) -> bool:
        if self._pending.get(request_id) is future:
            self._pending.pop(request_id, None)
            self._outcome_unknown[request_id] = future
            return True
        return self._outcome_unknown.get(request_id) is future

    def _abandon_dispatched_wait_locked(
        self,
        request_id: str,
        future: Future,
        command_class: CommandClass,
    ) -> dict[str, Any] | None:
        if future.done() and not future.cancelled() and future.exception() is None:
            return future.result()
        if command_class is CommandClass.READ:
            self._retire_read_owner_locked(request_id, future)
        else:
            self._retain_unknown_owner_locked(request_id, future)
        return None

    def _settle_pending_for_lifecycle_locked(
        self,
        *,
        error: str,
        default_generation: int,
    ) -> None:
        for request_id, future in tuple(self._pending.items()):
            binding = self._binding_for_locked(
                request_id,
                default_generation=default_generation,
            )
            if binding.command_class is CommandClass.READ:
                if not future.done():
                    future.set_result(
                        {
                            "ok": False,
                            "error": f"{error}; read owner retired",
                            "request_id": request_id,
                            "generation": binding.generation,
                            "dispatched": True,
                            "outcome_unknown": False,
                            "delivery_state": "unknown",
                            "commit_state": "not_applicable",
                            "retry_safe": True,
                        }
                    )
                self._retire_read_owner_locked(request_id, future)
                continue
            if not future.done():
                future.set_result(
                    {
                        "ok": False,
                        "error": error,
                        "request_id": request_id,
                        "generation": binding.generation,
                        "dispatched": True,
                        "outcome_unknown": True,
                        "delivery_state": "dispatched",
                        "commit_state": "unknown",
                    }
                )
            self._retain_unknown_owner_locked(request_id, future)
        for request_id, future in tuple(self._outcome_unknown.items()):
            binding = self._binding_for_locked(
                request_id,
                default_generation=default_generation,
            )
            if binding.command_class is not CommandClass.READ:
                continue
            if not future.done():
                future.set_result(
                    {
                        "ok": False,
                        "error": f"{error}; read owner retired",
                        "request_id": request_id,
                        "generation": binding.generation,
                        "dispatched": True,
                        "outcome_unknown": False,
                        "delivery_state": "unknown",
                        "commit_state": "not_applicable",
                        "retry_safe": True,
                    }
                )
            self._retire_read_owner_locked(request_id, future)

    def send_command(
        self,
        cmd: dict,
        *,
        cancellation_requested: threading.Event | None = None,
    ) -> dict:
        """Dispatch one command after fail-closed mutation negotiation.

        Discovery is single-flight across GUI worker threads.  A rotated token
        invalidates the cache, but the rejected mutation is never replayed
        automatically; the operator/client must explicitly submit it again.
        """
        if cancellation_requested is not None and cancellation_requested.is_set():
            return {
                "ok": False,
                "dispatched": False,
                "error": "ZMQ command cancelled before dispatch",
            }
        if type(cmd) is not dict:
            return {
                "ok": False,
                "error_code": "command_invalid",
                "error": "GUI command must be a plain mapping",
                "retry_safe": True,
            }
        action = cmd.get("cmd")
        if type(action) is not str or not action:
            return {
                "ok": False,
                "error_code": "command_invalid",
                "error": "GUI command requires a non-empty string cmd",
                "retry_safe": True,
            }
        if is_assistant_namespaced(action) and action not in ASSISTANT_READ_ACTIONS:
            return {
                "ok": False,
                "error_code": "assistant_read_only",
                "error": "Assistant accepts only the exact observational command allowlist",
                "delivery_state": "not_dispatched",
                "commit_state": "not_committed",
                "retry_safe": False,
            }
        command_class = classify_client_command(action)
        if command_class is CommandClass.SAFE_DIRECTION and not _is_exact_safe_direction_command(cmd):
            return _safe_direction_rejection()
        command = strip_mutation_envelope(cmd)
        if command_class in {CommandClass.READ, CommandClass.SAFE_DIRECTION}:
            return self._send_command_once(command, cancellation_requested=cancellation_requested)

        receipt, failure = self._ensure_mutation_compatibility(cancellation_requested=cancellation_requested)
        if failure is not None:
            return failure
        assert receipt is not None
        command.update(
            {
                "protocol_major": receipt["server_protocol_major"],
                "mutation_capability": receipt["required_capability"],
                "capability_token": receipt["capability_token"],
            }
        )
        result = self._send_command_once(command, cancellation_requested=cancellation_requested)
        if result.get("error_code") == "mutation_protocol_incompatible":
            self._invalidate_mutation_compatibility()
        return result

    def _send_command_once(
        self,
        cmd: dict[str, Any],
        *,
        cancellation_requested: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Thread-safe raw dispatch with Future-per-request correlation."""
        if cancellation_requested is not None and cancellation_requested.is_set():
            return {
                "ok": False,
                "dispatched": False,
                "error": "ZMQ command cancelled before dispatch",
            }
        action_value = cmd.get("cmd")
        action = action_value if type(action_value) is str else "<invalid>"
        command_class = classify_client_command(action_value)
        if command_class is CommandClass.SAFE_DIRECTION and not _is_exact_safe_direction_command(cmd):
            return _safe_direction_rejection()
        if not self.is_alive():
            return {"ok": False, "error": "ZMQ bridge subprocess not running"}

        future: Future = Future()
        rid: str | None = None
        safe_scope = None
        safe_kind = exact_safe_direction_kind(cmd)
        if command_class is CommandClass.SAFE_DIRECTION:
            if safe_kind is SafeDirectionKind.LAUNCHER_SHUTDOWN:
                safe_scope = "launcher"
            elif safe_kind is SafeDirectionKind.TARGETED_OFF:
                safe_scope = "channel"
            else:
                safe_scope = "global"
        enqueued = False
        enqueue_error: Exception | None = None
        safe_transport_failure: Exception | None = None
        publication_cancelled = False

        # Registration and publication ownership are one short admission
        # transaction. The potentially blocking queue call occurs only under
        # its lane lock; ordinary saturation therefore cannot hold the shared
        # generation ledger or the independent safe publisher.
        with self._pending_lock:
            fatal = self._generation_fatal
            if (
                not self._command_admission_open
                or self._reply_stop.is_set()
                or (fatal is not None and fatal.generation == self._generation)
            ):
                return _bridge_lifecycle_rejection()
            command_queue = self._safe_cmd_queue if is_preemptive_safe_direction(cmd) else self._cmd_queue
            using_safe_transport = command_queue is self._safe_cmd_queue
            publication_lane = "safe" if using_safe_transport else "ordinary"
            if not self._has_request_capacity_locked(
                command_class=command_class,
                action=action,
                safe_scope=safe_scope,
            ):
                return {
                    "ok": False,
                    "error_code": "command_capacity_exhausted",
                    "error": "ZMQ unresolved command capacity exhausted",
                    "dispatched": False,
                    "delivery_state": "not_dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            rid = uuid.uuid4().hex
            while rid in self._pending or rid in self._outcome_unknown or rid in self._late_results:
                rid = uuid.uuid4().hex
            self._pending[rid] = future
            self._request_generation[rid] = self._generation
            generation = self._generation
            self._bindings_locked()[rid] = _RequestBinding(
                generation,
                command_class,
                action,
                safe_scope,
            )
            cmd = {**cmd, "_rid": rid, "_bridge_generation": generation}
            if cancellation_requested is not None and cancellation_requested.is_set():
                self._retire_definitely_unsent_owner_locked(rid, future)
                return {
                    "ok": False,
                    "dispatched": False,
                    "error": "ZMQ command cancelled before dispatch",
                }
            publication_lock = self._claim_publication_locked(publication_lane)

        publication_error: Exception | None = None
        try:
            try:
                with publication_lock:
                    if cancellation_requested is not None and cancellation_requested.is_set():
                        publication_cancelled = True
                    else:
                        _put_ipc_nowait(command_queue, cmd)
            except Exception as exc:
                publication_error = exc

            with self._pending_lock:
                if publication_cancelled:
                    self._retire_definitely_unsent_owner_locked(rid, future)
                elif isinstance(publication_error, queue.Full):
                    enqueue_error = publication_error
                    self._retire_definitely_unsent_owner_locked(rid, future)
                elif publication_error is not None:
                    enqueue_error = publication_error
                    if using_safe_transport:
                        # A synchronous pipe failure may follow a partial frame.
                        # Retain the exact owner as outcome-unknown and retire this
                        # generation; never report a definitely-unsent OFF.
                        safe_transport_failure = publication_error
                        enqueued = True
                    else:
                        self._retire_definitely_unsent_owner_locked(rid, future)
                else:
                    enqueued = True

            if safe_transport_failure is not None:
                self._record_generation_fatal(
                    reply_queue=command_queue,
                    lane="safe_command",
                    source_generation=generation,
                    error=safe_transport_failure,
                )
        finally:
            self._release_publication(publication_lane)

        if publication_cancelled:
            return {
                "ok": False,
                "dispatched": False,
                "error": "ZMQ command cancelled before dispatch",
            }

        if safe_transport_failure is not None:
            with self._pending_lock:
                direct_result = self._abandon_dispatched_wait_locked(
                    rid,
                    future,
                    command_class,
                )
            if direct_result is not None:
                return direct_result
            return {
                "ok": False,
                "error_code": "safe_command_transport_failed",
                "error": "Safe command transport failed; outcome is unknown.",
                "request_id": rid,
                "generation": generation,
                "delivery_state": "unknown",
                "commit_state": "unknown",
                "dispatched": True,
                "outcome_unknown": True,
                "retry_safe": False,
            }

        if enqueue_error is not None:
            logger.warning(
                "ZMQ command forwarding failed before dispatch: exception=%s",
                type(enqueue_error).__name__,
            )
            return {
                "ok": False,
                "error_code": "engine_unavailable",
                "error": "Engine command transport is unavailable.",
                "delivery_state": "not_dispatched",
                "commit_state": "not_committed",
                "retry_safe": True,
            }

        try:
            deadline = time.monotonic() + _CMD_REPLY_TIMEOUT_S
            while True:
                if cancellation_requested is not None and cancellation_requested.is_set():
                    direct_result: dict[str, Any] | None = None
                    with self._pending_lock:
                        direct_result = self._abandon_dispatched_wait_locked(
                            rid,
                            future,
                            command_class,
                        )
                    if direct_result is not None:
                        return direct_result
                    if command_class is CommandClass.READ:
                        return {
                            "ok": False,
                            "error": "ZMQ read cancelled after dispatch",
                            "request_id": rid,
                            "generation": generation,
                            "dispatched": True,
                            "outcome_unknown": False,
                            "delivery_state": "unknown",
                            "commit_state": "not_applicable",
                            "retry_safe": True,
                        }
                    return {
                        "ok": False,
                        "error": "ZMQ command outcome unknown after cancellation",
                        "request_id": rid,
                        "generation": generation,
                        "dispatched": True,
                        "outcome_unknown": True,
                        "delivery_state": "dispatched",
                        "commit_state": "unknown",
                    }
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    direct_result = None
                    with self._pending_lock:
                        direct_result = self._abandon_dispatched_wait_locked(
                            rid,
                            future,
                            command_class,
                        )
                    if direct_result is not None:
                        return direct_result
                    if command_class is CommandClass.READ:
                        return {
                            "ok": False,
                            "error": "ZMQ read timed out after dispatch",
                            "request_id": rid,
                            "generation": generation,
                            "dispatched": True,
                            "outcome_unknown": False,
                            "delivery_state": "unknown",
                            "commit_state": "not_applicable",
                            "retry_safe": True,
                        }
                    return {
                        "ok": False,
                        "error": "ZMQ command outcome unknown after timeout",
                        "request_id": rid,
                        "generation": generation,
                        "dispatched": True,
                        "outcome_unknown": True,
                        "delivery_state": "dispatched",
                        "commit_state": "unknown",
                    }
                try:
                    return future.result(timeout=min(0.05, remaining))
                except TimeoutError:
                    continue
        except Exception as exc:
            direct_result = None
            if enqueued:
                with self._pending_lock:
                    direct_result = self._abandon_dispatched_wait_locked(
                        rid,
                        future,
                        command_class,
                    )
                if direct_result is not None:
                    return direct_result
                if command_class is CommandClass.READ:
                    logger.warning(
                        "ZMQ read forwarding failed after enqueue: exception=%s",
                        type(exc).__name__,
                    )
                    return {
                        "ok": False,
                        "error_code": "engine_unavailable",
                        "error": "Engine read transport is unavailable after dispatch.",
                        "request_id": rid,
                        "generation": generation,
                        "delivery_state": "unknown",
                        "commit_state": "not_applicable",
                        "dispatched": True,
                        "outcome_unknown": False,
                        "retry_safe": True,
                    }
                if command_class is not CommandClass.READ:
                    logger.warning(
                        "ZMQ command forwarding failed after enqueue: exception=%s",
                        type(exc).__name__,
                    )
                    return {
                        "ok": False,
                        "error_code": "engine_unavailable",
                        "error": "Engine command transport is unavailable after dispatch.",
                        "request_id": rid,
                        "generation": generation,
                        "delivery_state": "unknown",
                        "commit_state": "unknown",
                        "dispatched": True,
                        "outcome_unknown": True,
                        "retry_safe": False,
                    }
            logger.warning(
                "ZMQ command forwarding failed: exception=%s",
                type(exc).__name__,
            )
            return {
                "ok": False,
                "error_code": "engine_unavailable",
                "error": "Engine command transport is unavailable.",
                "delivery_state": "unknown" if enqueued else "not_dispatched",
                "commit_state": "unknown" if enqueued else "not_committed",
                "retry_safe": not enqueued,
            }
        finally:
            if not enqueued and rid is not None:
                with self._pending_lock:
                    self._retire_definitely_unsent_owner_locked(rid, future)

    def _ensure_mutation_compatibility(
        self,
        *,
        cancellation_requested: threading.Event | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        with self._mutation_lock:
            if self._mutation_receipt is not None:
                return dict(self._mutation_receipt), None
            discovery = self._send_command_once(
                {"cmd": "mutation_capabilities"},
                cancellation_requested=cancellation_requested,
            )
            if type(discovery) is dict and discovery.get("error_code") == "bridge_lifecycle_retired":
                return None, discovery
            if cancellation_requested is not None and cancellation_requested.is_set():
                return None, discovery
            receipt = discovery.get("compatibility_receipt") if type(discovery) is dict else None
            replay_scope = self._verified_replay_scope
            expected_capability = _REPLAY_MUTATION_CAPABILITY if replay_scope is not None else _MUTATION_CAPABILITY
            receipt_keys = {
                "schema",
                "accepted",
                "server_protocol_major",
                "required_capability",
                "capability_token",
            }
            if replay_scope is not None:
                receipt_keys.update({"mode", "session_id", "source", "speed"})
            valid = (
                type(discovery) is dict
                and set(discovery) == {"ok", "compatibility_receipt", "proto"}
                and discovery.get("ok") is True
                and type(discovery.get("proto")) is int
                and discovery.get("proto") == CLIENT_PROTOCOL_VERSION
                and type(receipt) is dict
                and set(receipt) == receipt_keys
                and receipt.get("schema") == _MUTATION_RECEIPT_SCHEMA
                and receipt.get("accepted") is True
                and type(receipt.get("server_protocol_major")) is int
                and receipt.get("server_protocol_major") == _MUTATION_PROTOCOL_MAJOR
                and receipt.get("required_capability") == expected_capability
                and type(receipt.get("capability_token")) is str
                and 16 <= len(receipt["capability_token"]) <= 512
                and receipt["capability_token"].isprintable()
                and (
                    replay_scope is None
                    or (
                        receipt.get("mode") == "replay"
                        and receipt.get("session_id") == replay_scope["session_id"]
                        and receipt.get("source") == replay_scope["source"]
                        and type(receipt.get("speed")) is float
                        and receipt.get("speed") == replay_scope["speed"]
                    )
                )
            )
            if not valid:
                self._mutation_receipt = None
                return None, {
                    "ok": False,
                    "error_code": "mutation_protocol_incompatible",
                    "error": "GUI mutation compatibility discovery failed; command was not dispatched",
                    "retry_safe": True,
                    "compatibility_receipt": {
                        "schema": _MUTATION_RECEIPT_SCHEMA,
                        "accepted": False,
                        "server_protocol_major": _MUTATION_PROTOCOL_MAJOR,
                        "required_capability": expected_capability,
                    },
                }
            self._mutation_receipt = {key: receipt[key] for key in receipt_keys}
            return dict(self._mutation_receipt), None

    def bind_verified_replay_session(self, *, session_id: str, source: str, speed: float) -> None:
        """Bind mutations to the replay child/session proven by the launcher."""

        if self.is_alive():
            raise RuntimeError("replay scope must be bound before bridge startup")
        if (
            type(session_id) is not str
            or len(session_id) != 32
            or any(character not in "0123456789abcdef" for character in session_id)
            or type(source) is not str
            or not source
            or not source.isprintable()
            or type(speed) is not float
            or not math.isfinite(speed)
            or speed < 0.0
        ):
            raise ValueError("verified replay scope is invalid")
        with self._mutation_lock:
            self._mutation_receipt = None
            self._verified_replay_scope = {
                "mode": "replay",
                "session_id": session_id,
                "source": source,
                "speed": speed,
            }

    def _invalidate_mutation_compatibility(self) -> None:
        with self._mutation_lock:
            self._mutation_receipt = None

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
        """Own and consume only the ordinary subprocess reply queue."""

        self._consume_reply_queue(self._reply_queue, "ordinary", self._generation)

    def _consume_safe_replies(self) -> None:
        """Own and consume only the preemptive subprocess reply queue."""

        self._consume_reply_queue(self._safe_reply_queue, "safe", self._generation)

    def _consume_reply_queue(
        self,
        reply_queue: Any,
        lane: str,
        source_generation: int,
    ) -> None:
        """Route one immutable queue/generation cut until lifecycle revocation."""

        failure: BaseException | None = None
        try:
            while not self._reply_stop.is_set():
                try:
                    reply = reply_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                except (EOFError, OSError, ValueError) as exc:
                    failure = exc
                    return

                try:
                    if not isinstance(reply, dict):
                        logger.warning(
                            "ZMQ %s reply consumer: non-dict reply: %r",
                            lane,
                            type(reply),
                        )
                        continue
                    self._check_proto(reply)
                    rid = reply.get("_rid")
                    with self._pending_lock:
                        if self._route_reply_locked(
                            reply,
                            source_generation=source_generation,
                            source_lane=lane,
                        ):
                            continue
                    logger.debug(
                        "Unmatched ZMQ %s reply (rid=%s)",
                        lane,
                        _bounded_request_label(rid),
                    )
                except Exception as exc:
                    logger.error(
                        "ZMQ %s reply consumer rejected one reply: exception=%s",
                        lane,
                        _bounded_exception_type(exc),
                    )
        except BaseException as exc:
            failure = exc
        finally:
            if not self._reply_stop.is_set():
                self._record_generation_fatal(
                    reply_queue=reply_queue,
                    lane=lane,
                    source_generation=source_generation,
                    error=failure,
                )

    def shutdown(self) -> None:
        """Settle the reply consumer and subprocess or raise with ownership intact."""
        with self._lifecycle_lock:
            self._shutdown_locked()

    def _shutdown_locked(self) -> None:
        """Settle one bridge lifecycle while holding its exclusive owner lock."""
        self._last_snapshot_time = 0.0
        self._bridge_instance_id = None
        with self._pending_lock:
            self._command_admission_open = False
            self._reply_stop.set()
        self._wait_for_publications_to_settle_locked()
        with self._pending_lock:
            self._settle_pending_for_lifecycle_locked(
                error="ZMQ bridge shutting down; outcome unknown",
                default_generation=self._generation,
            )
        self._invalidate_mutation_compatibility()
        exit_code = self._settle_runtime_owners_locked(reason="ZMQ bridge shutdown")
        if exit_code is not None:
            logger.info("ZMQ bridge subprocess stopped (exitcode=%s)", exit_code)
        else:
            logger.info("ZMQ bridge subprocess stopped")

    def close(self) -> None:
        """Terminally close parent-side IPC queues after a proven shutdown.

        ``shutdown()`` intentionally remains restartable for watchdog recovery.
        Launcher exit calls this terminal method only after the subprocess,
        reply consumer, and command workers have settled.
        """

        with self._lifecycle_lock:
            self._close_locked()

    def _close_locked(self) -> None:
        """Terminally close queues while holding the exclusive lifecycle lock."""

        if self._terminal_closed:
            return
        self._settle_restart_candidates_locked()
        if not self._terminal_shutdown_settled:
            # Record this phase only after shutdown proves every runtime owner
            # settled.  If a later queue close/join fails, retry only that
            # terminal phase instead of touching already-closed reply queues.
            self.shutdown()
        if self._process is not None or self._reply_consumer is not None or self._safe_reply_consumer is not None:
            raise RuntimeError("ZMQ bridge terminal close requires settled process and both reply consumers")
        self._terminal_shutdown_settled = True
        with self._pending_lock:
            if self._pending:
                raise RuntimeError("ZMQ bridge terminal close requires no pending command futures")
            unresolved = (
                set(self._outcome_unknown)
                | set(self._late_results)
                | set(self._request_generation)
                | set(self._bindings_locked())
            )
            if unresolved:
                raise RuntimeError("ZMQ bridge terminal close requires explicit unresolved mutation reconciliation")

        queues = (
            ("data", self._data_queue, False, True),
            ("command", self._cmd_queue, False, True),
            # A direction-owned sender has no receive surface and must never
            # be drained during terminal settlement.
            ("safe_command", self._safe_cmd_queue, False, False),
            ("reply", self._reply_queue, False, True),
            ("safe_reply", self._safe_reply_queue, False, True),
            ("snapshot", self._snapshot_queue, True, True),
        )
        for name, ipc_queue, task_done, drain_before_close in queues:
            if name not in self._terminal_queues_closed:
                if drain_before_close:
                    _drain(ipc_queue, task_done=task_done)
                ipc_queue.close()
                self._terminal_queues_closed.add(name)
            if name not in self._terminal_queues_joined:
                _join_mp_queue_feeder(ipc_queue, label=f"ZMQ bridge {name} queue")
                self._terminal_queues_joined.add(name)
        self._terminal_closed = True

    def reconcile_late_result(self, request_id: str, *, generation: int | None = None) -> LateCommandResult | None:
        """Consume one exact late result after the mutation owner reconciles it."""
        with self._pending_lock:
            result = self._late_results.get(request_id)
            if result is None or (generation is not None and result.generation != generation):
                return None
            self._late_results.pop(request_id, None)
            self._outcome_unknown.pop(request_id, None)
            self._release_request_identity_locked(request_id)
            return result

    def _route_reply_locked(
        self,
        reply: object,
        *,
        source_generation: int | None = None,
        source_lane: str | None = None,
    ) -> bool:
        """Route one reply; caller must hold ``_pending_lock``."""
        if source_lane not in {None, "ordinary", "safe"}:
            return False
        if not isinstance(reply, dict):
            return False
        rid = reply.get("_rid")
        if not isinstance(rid, str) or not rid:
            return False
        pending_owner = self._pending.get(rid)
        unknown_owner = self._outcome_unknown.get(rid)
        terminal_result = self._late_results.get(rid)
        if pending_owner is None and unknown_owner is None and terminal_result is not None:
            if source_lane is not None and (
                (source_lane == "safe")
                != _uses_preemptive_transport_lane(
                    terminal_result.command_class,
                    terminal_result.safe_scope,
                )
            ):
                return False
            wire_generation = reply.get("_bridge_generation")
            if wire_generation is not None:
                if type(wire_generation) is not int or wire_generation < 0:
                    return False
                if source_generation is not None and wire_generation != source_generation:
                    return False
                if wire_generation != terminal_result.generation:
                    return False
            elif source_generation is not None and source_generation != terminal_result.generation:
                return False
            logger.warning(
                "Ignoring duplicate late ZMQ reply for request %s",
                _bounded_request_label(rid),
            )
            return True
        if pending_owner is None and unknown_owner is None:
            return False
        binding = self._binding_for_locked(rid)
        if source_lane is not None and (
            (source_lane == "safe") != _uses_preemptive_transport_lane(binding.command_class, binding.safe_scope)
        ):
            return False
        wire_generation = reply.get("_bridge_generation")
        if wire_generation is not None:
            if type(wire_generation) is not int or wire_generation < 0:
                return False
            if source_generation is not None and wire_generation != source_generation:
                return False
            reply_generation = wire_generation
        elif source_generation is not None:
            reply_generation = source_generation
        elif rid not in self._bindings_locked():
            reply_generation = binding.generation
        else:
            return False
        if reply_generation != binding.generation:
            return False
        clean_reply = _sanitize_command_reply(
            {key: value for key, value in reply.items() if key not in {"_rid", "_bridge_generation"}}
        )
        if unknown_owner is not None:
            if rid in self._late_results:
                logger.warning(
                    "Ignoring duplicate late ZMQ reply for request %s",
                    _bounded_request_label(rid),
                )
                return True
            self._late_results[rid] = LateCommandResult(
                rid,
                binding.generation,
                clean_reply,
                binding.command_class,
                binding.action,
                binding.safe_scope,
            )
            self._outcome_unknown.pop(rid, None)
            self._release_request_identity_locked(rid)
            if not unknown_owner.done():
                unknown_owner.set_result(clean_reply)
            return True
        if pending_owner is None:
            return False
        if self._pending.get(rid) is not pending_owner:
            return False
        self._pending.pop(rid, None)
        self._release_request_identity_locked(rid)
        if not pending_owner.done():
            pending_owner.set_result(clean_reply)
        return True

    def _drain_replies_locked(
        self,
        reply_queue: Any,
        *,
        source_generation: int | None = None,
        source_lane: str | None = None,
    ) -> None:
        """Route all currently queued replies before retiring ``reply_queue``."""
        while True:
            try:
                reply = reply_queue.get_nowait()
            except (queue.Empty, EOFError, OSError):
                return
            self._route_reply_locked(
                reply,
                source_generation=source_generation,
                source_lane=source_lane,
            )


def _drain(q: Any, *, task_done: bool = False) -> None:
    """Drain a multiprocessing Queue, ignoring errors."""
    get_nowait = getattr(q, "get_nowait", None)
    if not callable(get_nowait):
        # Direction-owned send endpoints deliberately expose no receive API.
        return
    while True:
        try:
            get_nowait()
            if task_done:
                q.task_done()
        except (queue.Empty, EOFError, OSError, ValueError):
            break


# --- Backwards-compatible API used by keithley_panel and other GUI widgets ---

_bridge: ZmqBridge | None = None


def set_bridge(bridge: ZmqBridge | None) -> None:
    """Set or exactly release the process-global bridge instance."""
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


_GUI_WORKER_REGISTRY_LOCK = threading.RLock()
_GUI_WORKER_ADMISSION_OPEN = False
_GUI_WORKER_SESSION_EPOCH = 0


@dataclass(slots=True)
class _GuiWorkerOwnership:
    """Strongly retain one admitted QThread through callback disposition."""

    worker: QThread
    session_epoch: int
    disposition_recorded: bool = False


_GUI_WORKER_OWNERS: dict[int, _GuiWorkerOwnership] = {}


def open_gui_command_worker_admission() -> int:
    """Begin exactly one explicit root-owned GUI worker session."""

    global _GUI_WORKER_ADMISSION_OPEN, _GUI_WORKER_SESSION_EPOCH
    with _GUI_WORKER_REGISTRY_LOCK:
        _release_disposed_terminal_workers_locked()
        if _GUI_WORKER_ADMISSION_OPEN:
            raise RuntimeError("GUI command worker admission is already open")
        if _GUI_WORKER_OWNERS:
            raise RuntimeError("previous GUI command worker session remains unsettled")
        _GUI_WORKER_SESSION_EPOCH += 1
        _GUI_WORKER_ADMISSION_OPEN = True
        return _GUI_WORKER_SESSION_EPOCH


def revoke_gui_command_worker_admission(session_epoch: int) -> tuple[QThread, ...]:
    """Close only the root session identified by *session_epoch*."""

    global _GUI_WORKER_ADMISSION_OPEN
    with _GUI_WORKER_REGISTRY_LOCK:
        if session_epoch != _GUI_WORKER_SESSION_EPOCH:
            raise RuntimeError("GUI command worker session token is stale")
        _GUI_WORKER_ADMISSION_OPEN = False
        return _registered_gui_command_workers_locked()


def gui_command_worker_admission_open() -> bool:
    with _GUI_WORKER_REGISTRY_LOCK:
        return _GUI_WORKER_ADMISSION_OPEN


def capture_gui_worker_session_token() -> int:
    """Capture the current explicit root session or fail closed."""

    with _GUI_WORKER_REGISTRY_LOCK:
        if not _GUI_WORKER_ADMISSION_OPEN:
            raise RuntimeError("GUI command worker admission is closed")
        return _GUI_WORKER_SESSION_EPOCH


def gui_worker_delivery_is_current(session_epoch: int) -> bool:
    """Return whether a queued result still belongs to the live root session."""

    with _GUI_WORKER_REGISTRY_LOCK:
        return _GUI_WORKER_ADMISSION_OPEN and session_epoch == _GUI_WORKER_SESSION_EPOCH


def start_gui_worker_with_ownership(
    worker: QThread,
    session_epoch: int,
    priority: QThread.Priority = QThread.Priority.InheritPriority,
) -> None:
    """Atomically admit, strongly retain, and start an arbitrary GUI QThread."""

    identity = id(worker)
    with _GUI_WORKER_REGISTRY_LOCK:
        if not _GUI_WORKER_ADMISSION_OPEN:
            raise RuntimeError("GUI command worker admission is closed")
        if session_epoch != _GUI_WORKER_SESSION_EPOCH:
            raise RuntimeError("GUI command worker session token is stale")
        if identity in _GUI_WORKER_OWNERS:
            raise RuntimeError("GUI command worker is already registered")
        _GUI_WORKER_OWNERS[identity] = _GuiWorkerOwnership(
            worker=worker,
            session_epoch=session_epoch,
        )
        try:
            QThread.start(worker, priority)
        except BaseException:
            _GUI_WORKER_OWNERS.pop(identity, None)
            raise


def _worker_is_terminal(worker: QThread) -> bool:
    try:
        return not worker.isRunning()
    except RuntimeError:
        return True


def _release_disposed_terminal_workers_locked() -> None:
    releasable = [
        identity
        for identity, ownership in _GUI_WORKER_OWNERS.items()
        if ownership.disposition_recorded and _worker_is_terminal(ownership.worker)
    ]
    for identity in releasable:
        _GUI_WORKER_OWNERS.pop(identity, None)


def _release_gui_worker_when_terminal(identity: int) -> None:
    with _GUI_WORKER_REGISTRY_LOCK:
        ownership = _GUI_WORKER_OWNERS.get(identity)
        if ownership is None or not ownership.disposition_recorded:
            return
        if _worker_is_terminal(ownership.worker):
            _GUI_WORKER_OWNERS.pop(identity, None)
            return
    QTimer.singleShot(1, lambda: _release_gui_worker_when_terminal(identity))


def record_gui_worker_delivery_disposition(worker: QThread) -> None:
    """Record delivered/suppressed disposition; release only after terminal."""

    identity = id(worker)
    with _GUI_WORKER_REGISTRY_LOCK:
        ownership = _GUI_WORKER_OWNERS.get(identity)
        if ownership is None:
            return
        ownership.disposition_recorded = True
    _release_gui_worker_when_terminal(identity)


def _registered_gui_command_workers_locked() -> tuple[QThread, ...]:
    _release_disposed_terminal_workers_locked()
    return tuple(ownership.worker for ownership in _GUI_WORKER_OWNERS.values())


def registered_gui_command_workers() -> tuple[QThread, ...]:
    """Snapshot every strongly retained GUI worker, independent of parentage."""

    with _GUI_WORKER_REGISTRY_LOCK:
        return _registered_gui_command_workers_locked()


def settle_registered_gui_command_workers(*, timeout_ms: int = 1_500) -> bool:
    """Settle terminal threads and queued-result disposition after revocation."""

    with _GUI_WORKER_REGISTRY_LOCK:
        if _GUI_WORKER_ADMISSION_OPEN:
            return False
    for _inventory_pass in range(4):
        candidates = registered_gui_command_workers()
        if not candidates:
            return True
        for worker in candidates:
            try:
                if worker.isRunning():
                    worker.requestInterruption()
                    worker.quit()
                    worker.wait(timeout_ms)
            except RuntimeError:
                pass
            if _worker_is_terminal(worker):
                record_gui_worker_delivery_disposition(worker)
        if not registered_gui_command_workers():
            return True
    return False


class ZmqCommandWorker(QThread):
    """Background thread for non-blocking ZMQ commands (unchanged API)."""

    finished = Signal(dict)
    _result_ready = Signal(int, dict)

    def __init__(self, cmd: dict, parent=None) -> None:
        super().__init__(parent)
        self._cmd = cmd
        self._cancellation_requested = threading.Event()
        self._session_epoch: int | None = None
        self._result_ready.connect(
            self._deliver_result_if_current,
            Qt.ConnectionType.QueuedConnection,
        )

    def start(self, priority: QThread.Priority = QThread.Priority.InheritPriority) -> None:
        """Start only while the shared process-wide admission gate is open."""

        session_epoch = capture_gui_worker_session_token()
        self._session_epoch = session_epoch
        try:
            start_gui_worker_with_ownership(self, session_epoch, priority)
        except BaseException:
            self._session_epoch = None
            raise

    def requestInterruption(self) -> None:
        """Make an in-flight command wait observe controlled teardown."""
        self._cancellation_requested.set()
        super().requestInterruption()

    def run(self) -> None:
        try:
            result = send_command(self._cmd, cancellation_requested=self._cancellation_requested)
        except BaseException as exc:
            result = {
                "ok": False,
                "error": "GUI command worker execution failed",
                "error_type": type(exc).__name__,
            }
        session_epoch = self._session_epoch
        if session_epoch is not None:
            self._result_ready.emit(session_epoch, result)

    @Slot(int, dict)
    def _deliver_result_if_current(self, session_epoch: int, result: dict) -> None:
        """Drop a queued completion after revocation or session replacement."""

        try:
            if not self.isInterruptionRequested() and gui_worker_delivery_is_current(session_epoch):
                self.finished.emit(result)
        finally:
            record_gui_worker_delivery_disposition(self)
