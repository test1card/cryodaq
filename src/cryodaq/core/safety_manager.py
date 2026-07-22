"""SafetyManager for CryoDAQ."""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.smu_channel import SMU_CHANNELS, SmuChannel, normalize_smu_channel
from cryodaq.drivers.base import Reading
from cryodaq.drivers.contracts import (
    DriverRuntimeBinding,
    DriverTrustClass,
    is_issued_runtime_binding,
)
from cryodaq.engine_wiring.operator_safety_snapshot import (
    OperatorSafetySnapshot,
    PlantHealthFact,
    SafetyBlocker,
    SafetyLifecycle,
)
from cryodaq.operator_snapshot import OperatorPresentationState, ReadinessTruth

logger = logging.getLogger(__name__)

_MAX_EVENTS = 500
_CHECK_INTERVAL_S = 1.0
_CHILD_FAULT_SETTLEMENT_DEADLINE_S = 15.0


class SafetyConfigError(RuntimeError):
    """Raised when safety.yaml cannot be loaded in a fail-closed manner.

    Distinct class so engine startup and launcher can recognise it as a
    config error (clean exit code, no auto-restart) rather than a generic
    runtime crash (retryable).
    """


class SafetyShutdownUnverifiedError(RuntimeError):
    """Raised while shutdown must HOLD because safety settlement is incomplete."""


class SafetyState(Enum):
    SAFE_OFF = "safe_off"
    READY = "ready"
    RUN_PERMITTED = "run_permitted"
    RUNNING = "running"
    FAULT_LATCHED = "fault_latched"
    MANUAL_RECOVERY = "manual_recovery"


@dataclass(frozen=True, slots=True)
class SafetyEvent:
    timestamp: datetime
    from_state: SafetyState
    to_state: SafetyState
    reason: str
    channel: str = ""
    value: float = 0.0


@dataclass
class SafetyConfig:
    critical_channels: list[re.Pattern[str]] = field(default_factory=list)
    stale_timeout_s: float = 10.0
    heartbeat_timeout_s: float = 15.0
    max_safety_backlog: int = 100
    require_keithley_for_run: bool = True
    max_dT_dt_K_per_min: float = 5.0
    require_reason: bool = True
    cooldown_before_rearm_s: float = 60.0
    max_power_w: float = 5.0
    max_voltage_v: float = 40.0
    max_current_a: float = 1.0
    keithley_channel_patterns: list[str] = field(default_factory=lambda: [".*/smu.*"])
    scheduler_drain_timeout_s: float = 5.0


class _ReviewedSourceGeneration:
    """Opaque SafetyManager-owned identity for one source connection attempt."""

    __slots__ = ()


async def _settle_shielded_hardware_task(
    task: asyncio.Task[Any],
    *,
    cancel_owned_on_caller_cancel: bool = False,
) -> tuple[Any | None, BaseException | None, asyncio.CancelledError | None]:
    """Settle an owned hardware task despite repeated caller cancellation.

    Most safety operations must finish even when their caller disappears.  A
    target-scoped OFF proof is different: cancellation invalidates that proof,
    so its task must become terminal before the caller escalates to one full
    global OFF.  The opt-in flag provides that exact handoff without changing
    cancellation ownership for any other hardware operation.
    """
    caller_cancelled: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            if asyncio.current_task().cancelling():
                caller_cancelled = caller_cancelled or exc
                if cancel_owned_on_caller_cancel and not task.done():
                    task.cancel()
            if task.done():
                break
            continue
        except Exception:
            # The owned task has reached a normal exceptional terminal state;
            # classify it below instead of leaking through asyncio.shield.
            break
    try:
        return task.result(), None, caller_cancelled
    except asyncio.CancelledError as exc:
        return None, exc, caller_cancelled
    except Exception as exc:
        return None, exc, caller_cancelled


class SafetyManager:
    """Single safety state machine with channel-aware Keithley control."""

    def __init__(
        self,
        safety_broker: SafetyBroker,
        *,
        keithley_driver: Any | None = None,
        reviewed_source_runtime_binding: DriverRuntimeBinding | None = None,
        mock: bool = False,
        data_broker: Any | None = None,
        fault_log_callback: Any | None = None,
    ) -> None:
        self._broker = safety_broker
        self._keithley = keithley_driver
        self._mock = mock
        self._reviewed_source_runtime_binding = reviewed_source_runtime_binding
        self._reviewed_source_identity_qualified = bool(
            keithley_driver is not None
            and reviewed_source_runtime_binding is not None
            and is_issued_runtime_binding(reviewed_source_runtime_binding)
            and reviewed_source_runtime_binding.driver is keithley_driver
            and reviewed_source_runtime_binding.trust_class is DriverTrustClass.REVIEWED_SOURCE
        )
        self._reviewed_source_generation: _ReviewedSourceGeneration | None = None
        self._data_broker = data_broker
        self._fault_log_callback = fault_log_callback
        self._state = SafetyState.SAFE_OFF
        self._config = SafetyConfig()
        self._events: deque[SafetyEvent] = deque(maxlen=_MAX_EVENTS)
        self._fault_reason = ""
        self._fault_time = 0.0
        self._fault_activated_at = 0.0
        # Presentation identity only; no recovery or output authority.
        self._fault_revision = 0
        self._recovery_reason = ""
        self._active_sources: set[SmuChannel] = set()
        self._run_permitted_since: float = 0.0  # monotonic timestamp of RUN_PERMITTED entry

        self._latest: dict[str, tuple[float, float, str]] = {}
        # HI-1: the gate is the elapsed data SPAN (min_span_s=30), not a raw
        # point count. The deployed LakeShore poll is 2.0 s
        # (config/instruments.yaml), so the 120 s window holds only ~61
        # points; the old min_points=60 gate meant the 5 K/min rate fault
        # could not arm until a full ~120 s of continuous data accumulated
        # (dead-window at every RUNNING entry and after any gap) and sat on a
        # 60/61 knife-edge where two missed polls silently disarmed the check.
        # Span-based gating arms after ~30 s of data regardless of poll rate
        # (~15 pts at 2 s, ~60 at 0.5 s) and tolerates missed/late polls:
        # 30 s of OLS averaging still suppresses LS218 ±0.01 K noise well
        # below the 5 K/min threshold. min_points=8 is only a small
        # OLS-stability floor.
        self._rate_estimator = RateEstimator(window_s=120.0, min_points=8, min_span_s=30.0)

        self._queue: asyncio.Queue[Reading] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._collect_task: asyncio.Task[None] | None = None
        self._child_generation = 0
        self._stopping_child_generation: int | None = None
        self._failed_child_role: str | None = None
        self._failed_child_reason: str | None = None
        self._pending_child_fault_settlements: set[asyncio.Task[Any]] = set()
        self._shutdown_hold_fault_settlement: asyncio.Task[Any] | None = None
        self._consumed_child_tasks: set[asyncio.Task[Any]] = set()

        # F36 owner-native operator cut.  This cache is replaced only on the
        # SafetyManager event-loop thread and its getter performs no sampling,
        # driver access, I/O, or recomputation.  Driver existence and a
        # SAFE_OFF state name are deliberately not OFF proof.
        observed = time.monotonic()
        self._reviewed_source_connected = False
        self._reviewed_source_verified_off = False
        self._safety_monitor_active = False
        self._persistence_fault_active = False
        self._operator_safety_snapshot = OperatorSafetySnapshot(
            revision=1,
            observed_monotonic_s=observed,
            lifecycle=SafetyLifecycle.UNKNOWN,
            readiness=ReadinessTruth.UNKNOWN,
            verified_off=False,
            blockers=(
                SafetyBlocker(
                    "safety_authority_unavailable",
                    OperatorPresentationState.DISCONNECTED,
                    "Safety authority is not yet available",
                    "Start SafetyManager and collect explicit OFF evidence",
                ),
            ),
            plant_health=(
                PlantHealthFact(
                    "safety_manager",
                    "Safety manager",
                    OperatorPresentationState.DISCONNECTED,
                    "safety_manager_not_started",
                ),
            ),
        )

        # Strong-ref set for fire-and-forget _publish_state tasks scheduled
        # from synchronous _transition. Without this the event loop only
        # weak-refs the task and GC can silently drop a fault-state broadcast.
        # See DEEP_AUDIT_CC.md A.2/I.2.
        self._pending_publishes: set[asyncio.Task[None]] = set()

        # Hook called from acknowledge_fault to clear external persistence
        # flags (Phase 2a H.1). Engine wires this to writer.clear_disk_full
        # so operator acknowledgment, not auto-recovery, resumes polling.
        self._persistence_failure_clear: Callable[[], None] | None = None

        # Lock that serializes _active_sources mutations across await points.
        # Multiple REQ clients (GUI subprocess + web dashboard + future
        # operator CLI) can race on request_run / request_stop / emergency_off.
        # See DEEP_AUDIT_CC.md I.1.
        self._cmd_lock = asyncio.Lock()

        # Monotonic abort intent. Each abort increments before contending for
        # _cmd_lock. An in-flight request_run captures its entry generation and
        # cannot commit if it changes, even when the abort caller times out or
        # is cancelled while waiting. Future runs capture the new generation,
        # so a settled historical abort does not permanently inhibit RUN.
        self._abort_generation = 0
        self._full_abort_generation = 0

        # A global OFF is one physical operation for one exact driver/source
        # generation and abort epoch. Concurrent callers share this retained
        # owner instead of issuing competing bus writes. Caller cancellation
        # never cancels the owner; the task is cleared only after settlement.
        self._global_off_owner_task: asyncio.Task[Any] | None = None
        self._global_off_owner_driver: object | None = None
        self._global_off_owner_generation: _ReviewedSourceGeneration | None = None
        self._global_off_owner_abort_generation = -1

        self._keithley_patterns = [re.compile(p) for p in self._config.keithley_channel_patterns]
        self._on_state_change: list[Callable[[SafetyState, SafetyState, str], Any]] = []
        self._broker.set_overflow_callback(lambda: self._fault("SafetyBroker overflow - data lost"))

    def load_config(self, path: Path) -> None:
        if not path.exists():
            raise SafetyConfigError(
                f"safety.yaml not found at {path} — refusing to start SafetyManager without safety configuration"
            )

        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        if not isinstance(raw, dict):
            raise SafetyConfigError(f"safety.yaml at {path} is malformed (expected mapping, got {type(raw).__name__})")

        raw_patterns = raw.get("critical_channels", [])
        if not isinstance(raw_patterns, list):
            raise SafetyConfigError(
                f"safety.yaml at {path}: critical_channels must be a list, got {type(raw_patterns).__name__}"
            )
        if not raw_patterns:
            raise SafetyConfigError(
                f"safety.yaml at {path} has no critical_channels defined — "
                f"refusing to start SafetyManager without critical channel monitoring"
            )

        patterns: list[re.Pattern[str]] = []
        errors: list[str] = []
        for pattern in raw_patterns:
            if not isinstance(pattern, str):
                errors.append(f"  - {pattern!r}: expected string, got {type(pattern).__name__}")
                continue
            try:
                patterns.append(re.compile(pattern))
            except re.error as exc:
                errors.append(f"  - {pattern!r}: {exc}")

        if errors:
            raise SafetyConfigError(f"safety.yaml at {path} has invalid critical_channels regex:\n" + "\n".join(errors))

        if not patterns:
            raise SafetyConfigError(f"safety.yaml at {path} produced no valid critical_channels")

        logger.info(
            "SafetyManager config: %d critical channel patterns from %s",
            len(patterns),
            path,
        )

        try:
            src_limits = raw.get("source_limits", {})
            self._config = SafetyConfig(
                critical_channels=patterns,
                stale_timeout_s=float(raw.get("stale_timeout_s", 10.0)),
                heartbeat_timeout_s=float(raw.get("heartbeat_timeout_s", 15.0)),
                max_safety_backlog=int(raw.get("max_safety_backlog", 100)),
                require_keithley_for_run=bool(raw.get("require_keithley_for_run", True)),
                max_dT_dt_K_per_min=float(raw.get("rate_limits", {}).get("max_dT_dt_K_per_min", 5.0)),
                require_reason=bool(raw.get("recovery", {}).get("require_reason", True)),
                cooldown_before_rearm_s=float(raw.get("recovery", {}).get("cooldown_before_rearm_s", 60.0)),
                max_power_w=float(src_limits.get("max_power_w", 5.0)),
                max_voltage_v=float(src_limits.get("max_voltage_v", 40.0)),
                max_current_a=float(src_limits.get("max_current_a", 1.0)),
                scheduler_drain_timeout_s=float(raw.get("scheduler_drain_timeout_s", 5.0)),
            )
            self._keithley_patterns = [re.compile(pattern) for pattern in raw.get("keithley_channels", [".*/smu.*"])]
            # Liveness validation resolves these canonical patterns against
            # the selected descriptor authority.  A config reload must start
            # from the newly loaded canonical source rather than retaining a
            # previous raw-label resolution.
            self._canonical_critical_patterns = list(patterns)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise SafetyConfigError(
                f"safety.yaml at {path}: invalid config value — {type(exc).__name__}: {exc}"
            ) from exc
        self._refresh_operator_safety_snapshot()

    async def start(self) -> None:
        if self._pending_child_fault_settlements:
            raise RuntimeError("SafetyManager child fault settlement is still in progress")
        if self._stopping_child_generation is not None:
            raise RuntimeError("SafetyManager stop is still in progress")
        if self._collect_task is not None or self._monitor_task is not None:
            self._observe_terminal_safety_children()
            raise RuntimeError("SafetyManager child lifecycle is already owned")
        if self._queue is None:
            self._queue = self._broker.subscribe(
                "safety_manager",
                maxsize=self._config.max_safety_backlog,
            )
            self._broker.freeze()
        self._child_generation += 1
        generation = self._child_generation
        self._stopping_child_generation = None
        self._failed_child_role = None
        self._failed_child_reason = None
        self._consumed_child_tasks.clear()
        self._collect_task = asyncio.create_task(self._collect_loop(), name="safety_collect")
        self._monitor_task = asyncio.create_task(self._monitor_loop(), name="safety_monitor")
        self._collect_task.add_done_callback(
            lambda task, generation=generation: self._operator_child_done(
                task,
                role="collect",
                generation=generation,
            )
        )
        self._monitor_task.add_done_callback(
            lambda task, generation=generation: self._operator_child_done(
                task,
                role="monitor",
                generation=generation,
            )
        )
        self._safety_monitor_active = True
        if self._mock:
            # Explicit simulator evidence, never hardware evidence.  This
            # preserves deterministic mock operation without inspecting a
            # driver cache or weakening the real reviewed-source gate.
            self.record_reviewed_source_connected(verified_off=True)
        else:
            self._refresh_operator_safety_snapshot()
        await self._publish_state("initial")
        await self._publish_keithley_channel_states("initial")
        self._observe_terminal_safety_children()
        if not self._safety_children_authoritative():
            raise RuntimeError("SafetyManager children did not establish live authority")

    async def stop(self) -> None:
        if self._stopping_child_generation is not None:
            raise RuntimeError("SafetyManager stop is already in progress")

        # Consume a child that was already terminal before this stop call. Its
        # asyncio done callback may still be queued; establishing the stop cut
        # first would misclassify that pre-existing authority loss as an
        # expected shutdown exit and discard its fault/OFF/audit evidence.
        self._observe_terminal_safety_children()
        generation = self._child_generation
        collect_task = self._collect_task
        monitor_task = self._monitor_task
        previous_failed_role = self._failed_child_role
        previous_failed_reason = self._failed_child_reason
        consumed_before_stop = frozenset(
            task for task in (collect_task, monitor_task) if task is not None and task in self._consumed_child_tasks
        )

        def _restore_shutdown_owner_cut() -> None:
            """Roll a failed tentative stop back to retained owner truth."""

            self._stopping_child_generation = None
            self._failed_child_role = previous_failed_role
            self._failed_child_reason = previous_failed_reason
            self._safety_monitor_active = bool(
                self._failed_child_role is None
                and collect_task is not None
                and monitor_task is not None
                and collect_task is not monitor_task
                and not collect_task.done()
                and not monitor_task.done()
            )
            for task in (collect_task, monitor_task):
                if task is not None and task.done() and task not in consumed_before_stop:
                    self._consumed_child_tasks.discard(task)
            self._observe_terminal_safety_children()
            self._refresh_operator_safety_snapshot()

        hold_reason = "SafetyManager shutdown HOLD: global OFF could not be verified"

        def _begin_shutdown_hold(error: BaseException | None) -> None:
            logger.critical(
                "SafetyManager shutdown HOLD: global OFF could not be verified: %s",
                error or "driver returned non-True confirmation",
            )
            self._begin_fault_latch(
                hold_reason,
                source="safety_shutdown",
            )
            hold_settlement = self._shutdown_hold_fault_settlement
            if hold_settlement is None or hold_settlement.done():
                hold_settlement = asyncio.create_task(
                    self._settle_latched_fault(hold_reason, source="safety_shutdown"),
                    name="safety_shutdown_hold_fault_settlement",
                )
                self._shutdown_hold_fault_settlement = hold_settlement
                self._retain_child_fault_settlement(hold_settlement, reason=hold_reason)

                def _clear_exact_shutdown_hold(completed: asyncio.Task[Any]) -> None:
                    if self._shutdown_hold_fault_settlement is completed:
                        self._shutdown_hold_fault_settlement = None

                hold_settlement.add_done_callback(_clear_exact_shutdown_hold)
            _restore_shutdown_owner_cut()

        # Establish the synchronous mutation/lifecycle cut before the first
        # hardware await. A child that exits while stop_source() is blocked is
        # an expected member of this exact stopping generation, never a fresh
        # fault which can erase or race the shutdown result.
        self._stopping_child_generation = generation
        self._register_abort_intent(full=True)
        self._safety_monitor_active = False
        if self._failed_child_role is None:
            self._failed_child_reason = "safety_manager_stopping"
        self._reviewed_source_generation = None
        self._reviewed_source_connected = False
        self._reviewed_source_verified_off = False
        self._refresh_operator_safety_snapshot()

        cancelled: asyncio.CancelledError | None = None
        safe_off_error: BaseException | None = None
        if self._active_sources:
            safe_off_task = asyncio.create_task(
                self._safe_off("system stop", channels=set(self._active_sources)),
                name="safety_manager_stop_sources",
            )
            _result, safe_off_error, safe_off_cancelled = await _settle_shielded_hardware_task(safe_off_task)
            cancelled = safe_off_cancelled

        # Per-channel stop is not the terminal shutdown receipt. Demand an
        # exact global OFF confirmation before relinquishing either safety
        # child, including pre-latched and stale-cache paths.
        pending_before_global_proof = tuple(self._pending_child_fault_settlements)
        global_off_task = asyncio.create_task(
            self._ensure_output_off(),
            name="safety_manager_global_off_proof",
        )
        global_off_result, global_off_error, global_off_cancelled = await _settle_shielded_hardware_task(
            global_off_task
        )
        cancelled = cancelled or global_off_cancelled
        global_off_verified = global_off_error is None and global_off_result is True
        if global_off_verified:
            self._active_sources.clear()
        else:
            # Keep the process and exact safety children alive. A later stop()
            # retry may close the HOLD only after true OFF evidence; caller
            # cancellation never converts uncertainty into success.
            _begin_shutdown_hold(global_off_error)
            if cancelled is not None:
                raise cancelled
            raise SafetyShutdownUnverifiedError(hold_reason) from global_off_error

        # A retained older fault settlement can finish after the proof above
        # and publish an inconclusive result. Settle every such owner while the
        # safety children remain owned, then demand a new proof ordered after
        # all of them. No older result may be the last writer before shutdown.
        pending_faults = tuple(dict.fromkeys((*pending_before_global_proof, *self._pending_child_fault_settlements)))
        if pending_faults:
            bounded_drain = asyncio.create_task(
                asyncio.wait(
                    pending_faults,
                    timeout=_CHILD_FAULT_SETTLEMENT_DEADLINE_S,
                ),
                name="safety_child_fault_pre_stop_drain",
            )
            drain_result, drain_error, drain_cancelled = await _settle_shielded_hardware_task(bounded_drain)
            cancelled = cancelled or drain_cancelled
            if drain_error is not None:
                logger.critical("Safety child fault pre-stop drain failed: %s", drain_error)
                still_pending = set(pending_faults)
            else:
                assert drain_result is not None
                _done, still_pending = drain_result
            if still_pending:
                logger.critical(
                    "Safety child fault settlement remained live after %.1fs during stop; ownership is retained",
                    _CHILD_FAULT_SETTLEMENT_DEADLINE_S,
                )
                _restore_shutdown_owner_cut()
                if cancelled is not None:
                    raise cancelled
                raise SafetyShutdownUnverifiedError(
                    "SafetyManager shutdown HOLD: child fault settlement is still in progress"
                )

            ordered_proof_task = asyncio.create_task(
                self._ensure_output_off(),
                name="safety_manager_ordered_global_off_proof",
            )
            ordered_result, ordered_error, ordered_cancelled = await _settle_shielded_hardware_task(ordered_proof_task)
            cancelled = cancelled or ordered_cancelled
            if ordered_error is not None or ordered_result is not True:
                _begin_shutdown_hold(ordered_error)
                if cancelled is not None:
                    raise cancelled
                raise SafetyShutdownUnverifiedError(hold_reason) from ordered_error
            self._active_sources.clear()

        tasks = tuple(task for task in (collect_task, monitor_task) if task is not None)
        for task in tasks:
            if not task.done():
                task.cancel()

        async def _settle_children() -> None:
            await asyncio.gather(*tasks, return_exceptions=True)

        settlement = asyncio.create_task(
            _settle_children(),
            name="safety_manager_child_stop_settlement",
        )
        _result, settlement_error, settlement_cancelled = await _settle_shielded_hardware_task(settlement)
        cancelled = cancelled or settlement_cancelled
        if settlement_error is not None:
            logger.critical("Safety child stop settlement failed: %s", settlement_error)

        if self._child_generation == generation:
            if self._collect_task is collect_task:
                self._collect_task = None
            if self._monitor_task is monitor_task:
                self._monitor_task = None
        for task in tasks:
            self._forget_consumed_child_if_unowned(task)
        self._complete_stopping_generation_if_settled(generation)
        if cancelled is not None:
            raise cancelled
        if safe_off_error is not None:
            raise safe_off_error

    def _safety_children_authoritative(self) -> bool:
        """Return whether this exact manager lifetime owns both live children."""

        if (
            self._mock
            and self._child_generation == 0
            and self._stopping_child_generation is None
            and self._failed_child_role is None
        ):
            # Focused simulator tests historically exercise command logic
            # without starting background loops. No real manager receives this
            # exception, and a mock loses it permanently after its first start.
            return True
        collect = self._collect_task
        monitor = self._monitor_task
        return bool(
            self._child_generation > 0
            and self._stopping_child_generation != self._child_generation
            and self._failed_child_role is None
            and self._safety_monitor_active
            and collect is not None
            and monitor is not None
            and collect is not monitor
            and not collect.done()
            and not monitor.done()
        )

    def _complete_stopping_generation_if_settled(self, generation: int | None = None) -> None:
        """Release the stop cut only after every owned async tail is terminal."""

        stopping = self._stopping_child_generation
        if stopping is None or (generation is not None and stopping != generation):
            return
        if self._collect_task is not None or self._monitor_task is not None:
            return
        if self._pending_child_fault_settlements:
            return
        self._stopping_child_generation = None

    def _retain_child_fault_settlement(
        self,
        task: asyncio.Task[Any],
        *,
        reason: str,
    ) -> None:
        """Retain a child-death OFF owner and make a missed deadline visible."""

        self._pending_child_fault_settlements.add(task)
        loop = asyncio.get_running_loop()

        def _deadline() -> None:
            if not task.done():
                logger.critical(
                    "Safety child fault/OFF settlement exceeded %.1fs (%s); the live task remains strongly owned",
                    _CHILD_FAULT_SETTLEMENT_DEADLINE_S,
                    reason,
                )

        deadline = loop.call_later(_CHILD_FAULT_SETTLEMENT_DEADLINE_S, _deadline)

        def _settled(completed: asyncio.Task[Any]) -> None:
            deadline.cancel()
            self._pending_child_fault_settlements.discard(completed)
            self._complete_stopping_generation_if_settled()
            try:
                completed.result()
            except asyncio.CancelledError:
                logger.critical("Safety child fault/OFF settlement was cancelled (%s)", reason)
            except BaseException:
                logger.exception("Safety child fault/OFF settlement failed (%s)", reason)

        task.add_done_callback(_settled)

    def _observe_terminal_safety_children(self) -> None:
        """Synchronously consume exact owned children already known terminal."""

        generation = self._child_generation
        for role, task in (("collect", self._collect_task), ("monitor", self._monitor_task)):
            if task is not None and task.done():
                self._operator_child_done(task, role=role, generation=generation)

    def _forget_consumed_child_if_unowned(self, task: asyncio.Task[Any]) -> None:
        """Forget de-dup state only after this manager releases exact ownership."""

        if task is not self._collect_task and task is not self._monitor_task:
            self._consumed_child_tasks.discard(task)

    def _operator_child_done(
        self,
        task: asyncio.Task[None],
        *,
        role: str,
        generation: int,
    ) -> None:
        """Consume one exact child outcome and invalidate its owner cut.

        This callback runs on the owning event-loop thread.  It performs no
        await, logging, driver access, or I/O; exception retrieval prevents an
        unobserved-task warning.  Generation plus task identity prevents a
        delayed callback from a settled lifetime invalidating a restart.
        """
        if role not in {"collect", "monitor"}:
            raise ValueError("unknown SafetyManager child role")
        if task in self._consumed_child_tasks:
            return
        if task.cancelled():
            outcome = "cancelled"
        else:
            exception = task.exception()
            outcome = "completed" if exception is None else "failed"

        current = self._collect_task if role == "collect" else self._monitor_task
        if generation != self._child_generation or task is not current:
            return
        self._consumed_child_tasks.add(task)
        if self._stopping_child_generation == generation:
            return

        self._reviewed_source_generation = None
        self._reviewed_source_connected = False
        self._reviewed_source_verified_off = False
        self._safety_monitor_active = False
        self._failed_child_role = role
        self._failed_child_reason = f"safety_{role}_{outcome}"
        reason = f"Safety {role} child exited unexpectedly ({outcome})"
        self._begin_fault_latch(reason, source=f"safety_{role}")
        # Publish the revoked cut before any OFF/logging await. Even if another
        # fault was already latched, child-authority loss still owns a distinct
        # OFF attempt and audit record.
        self._refresh_operator_safety_snapshot()
        settlement = asyncio.create_task(
            self._settle_latched_fault(reason, source=f"safety_{role}"),
            name=f"safety_{role}_{outcome}_fault_settlement",
        )
        self._retain_child_fault_settlement(settlement, reason=reason)

    def replace_operator_child(self, role: str, task: asyncio.Task[Any]) -> None:
        """Adopt one supervisor replacement without restoring safety authority."""

        if role not in {"collect", "monitor"}:
            raise ValueError("unknown SafetyManager child role")
        if not isinstance(task, asyncio.Task):
            raise TypeError("SafetyManager replacement child must be an asyncio.Task")
        attr = "_collect_task" if role == "collect" else "_monitor_task"
        other_attr = "_monitor_task" if role == "collect" else "_collect_task"
        current = getattr(self, attr)
        if task is getattr(self, other_attr):
            raise RuntimeError("SafetyManager collect and monitor children must have distinct task identities")
        if current is None:
            raise RuntimeError(f"cannot replace live or unowned SafetyManager {role} child")
        owner_loop = asyncio.get_running_loop()
        if current.get_loop() is not owner_loop or task.get_loop() is not owner_loop:
            raise RuntimeError("SafetyManager replacement child must belong to the owner event loop")
        if current is task:
            # Initial TaskSupervisor registration: SafetyManager.start()
            # already installed the exact owner callback.
            return
        if self._stopping_child_generation == self._child_generation:
            raise RuntimeError("cannot replace SafetyManager child while stopping")
        if not current.done():
            raise RuntimeError(f"cannot replace live or unowned SafetyManager {role} child")
        # A supervisor may offer the replacement before asyncio has delivered
        # the completed owner's queued done callback. Consume that exact
        # terminal identity synchronously while it is still the authoritative
        # role pointer; swapping first would make the delayed callback fail its
        # identity check and silently discard terminal safety evidence.
        self._operator_child_done(
            current,
            role=role,
            generation=self._child_generation,
        )
        setattr(self, attr, task)
        self._forget_consumed_child_if_unowned(current)
        generation = self._child_generation
        task.add_done_callback(
            lambda completed, generation=generation: self._operator_child_done(
                completed,
                role=role,
                generation=generation,
            )
        )

    @property
    def state(self) -> SafetyState:
        return self._state

    @property
    def fault_reason(self) -> str:
        return self._fault_reason

    def snapshot_operator_safety(self) -> OperatorSafetySnapshot:
        """Return the owner cache after consuming already-terminal children.

        This boundary performs no await or driver I/O. It may synchronously
        revoke a stale authority cut and schedule the separately-owned OFF
        settlement for an exact task whose terminal state is already known.
        """
        self._observe_terminal_safety_children()
        return self._operator_safety_snapshot

    def record_reviewed_source_connected(self, *, verified_off: bool) -> None:
        """Commit explicit simulator-only connection evidence.

        Production authority must flow through the exact begin/complete
        lifecycle; a bare boolean must never synthesize a generation.
        """
        if type(verified_off) is not bool:
            raise TypeError("verified_off must be an exact bool")
        if not self._mock:
            raise RuntimeError("manual reviewed-source connection evidence is simulator-only")
        if not self._safety_children_authoritative():
            raise RuntimeError("safety child authority is unavailable")
        if verified_off and (self._active_sources or self._state in {SafetyState.RUN_PERMITTED, SafetyState.RUNNING}):
            raise ValueError("cannot accept verified-OFF evidence while a source lifecycle is active")
        if self._reviewed_source_generation is None:
            self._reviewed_source_generation = _ReviewedSourceGeneration()
        self._reviewed_source_connected = True
        self._reviewed_source_verified_off = verified_off
        self._refresh_operator_safety_snapshot()

    def record_reviewed_source_unavailable(self) -> None:
        """Invalidate connection and OFF authority without probing a driver."""
        self._reviewed_source_generation = None
        self._reviewed_source_connected = False
        self._reviewed_source_verified_off = False
        self._refresh_operator_safety_snapshot()

    def _require_reviewed_source_identity(
        self,
        driver: object,
        runtime_binding: DriverRuntimeBinding,
    ) -> None:
        if (
            not self._reviewed_source_identity_qualified
            or driver is not self._keithley
            or runtime_binding is not self._reviewed_source_runtime_binding
            or not is_issued_runtime_binding(runtime_binding)
            or runtime_binding.driver is not driver
            or runtime_binding.trust_class is not DriverTrustClass.REVIEWED_SOURCE
        ):
            raise ValueError("reviewed-source sealed runtime binding identity mismatch")

    def _has_current_reviewed_connection_generation(self) -> bool:
        if self._mock:
            return self._safety_children_authoritative()
        return bool(
            self._safety_children_authoritative()
            and self._reviewed_source_identity_qualified
            and self._reviewed_source_generation is not None
            and self._reviewed_source_connected
            and self._keithley is not None
            and getattr(self._keithley, "connected", None) is True
        )

    async def begin_reviewed_source_connect(
        self,
        driver: object,
        runtime_binding: DriverRuntimeBinding,
        context: str,
    ) -> object:
        """Revoke old authority before one scheduler-owned connect attempt."""
        self._require_reviewed_source_identity(driver, runtime_binding)
        self._register_abort_intent(full=True)
        async with self._cmd_lock:
            self._require_reviewed_source_identity(driver, runtime_binding)
            had_active_source = bool(self._active_sources)
            self._reviewed_source_generation = None
            self._reviewed_source_connected = False
            self._reviewed_source_verified_off = False
            self._refresh_operator_safety_snapshot()
            if not self._safety_children_authoritative():
                raise RuntimeError("cannot grant reviewed-source generation without live safety children")
            if had_active_source:
                await self._fault(f"reviewed source connection changed while active ({context})")
                # The caller may still complete a diagnostic reconnect, but
                # this unrecorded token can never qualify RUN after ACK.
                return _ReviewedSourceGeneration()
            generation = _ReviewedSourceGeneration()
            self._reviewed_source_generation = generation
            return generation

    async def complete_reviewed_source_connect(
        self,
        driver: object,
        runtime_binding: DriverRuntimeBinding,
        generation: object,
        context: str,
    ) -> bool:
        """Commit current-generation both-channel OFF cache after connect."""
        del context
        async with self._cmd_lock:
            self._require_reviewed_source_identity(driver, runtime_binding)
            if not self._safety_children_authoritative():
                return False
            if generation is not self._reviewed_source_generation:
                return False
            connected = getattr(driver, "connected", None) is True
            verified_off = connected and getattr(driver, "output_state_unverified", None) is False
            self._reviewed_source_connected = connected
            self._reviewed_source_verified_off = verified_off
            if verified_off:
                self._active_sources.clear()
            self._refresh_operator_safety_snapshot()
            return verified_off

    async def mark_reviewed_source_uncertain(
        self,
        driver: object,
        runtime_binding: DriverRuntimeBinding,
        generation: object,
        context: str,
    ) -> None:
        """Revoke one exact connection generation before uncertain recovery."""
        self._require_reviewed_source_identity(driver, runtime_binding)
        if generation is not self._reviewed_source_generation:
            return
        self._register_abort_intent(full=True)
        async with self._cmd_lock:
            self._require_reviewed_source_identity(driver, runtime_binding)
            if generation is not self._reviewed_source_generation:
                return
            self._reviewed_source_generation = None
            self._reviewed_source_connected = False
            self._reviewed_source_verified_off = False
            self._refresh_operator_safety_snapshot()
            if self._active_sources:
                await self._fault(f"reviewed source connection uncertain ({context})")

    def abandon_reviewed_source_connect(
        self,
        driver: object,
        runtime_binding: DriverRuntimeBinding,
        generation: object,
        context: str,
    ) -> None:
        """Synchronously revoke RUN authority at a caller deadline/cancel cut."""
        del context
        self._require_reviewed_source_identity(driver, runtime_binding)
        if generation is not self._reviewed_source_generation:
            return
        # This synchronous cut is deliberately lock-independent, like the
        # operator abort generation: it must outrun a command that yielded
        # while holding _cmd_lock.  The retained owner subsequently performs
        # the locked uncertainty transition and exact disconnect.
        self._register_abort_intent(full=True)
        if generation is not self._reviewed_source_generation:
            return
        self._reviewed_source_generation = None
        self._reviewed_source_connected = False
        self._reviewed_source_verified_off = False
        self._refresh_operator_safety_snapshot()

    async def request_run(
        self,
        p_target: float,
        v_comp: float,
        i_comp: float,
        *,
        channel: str | None = None,
    ) -> dict[str, Any]:
        start_abort_generation = self._abort_generation
        async with self._cmd_lock:
            smu_channel = normalize_smu_channel(channel)

            if self._state == SafetyState.FAULT_LATCHED:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"FAULT: {self._fault_reason}",
                }

            if self._state not in (SafetyState.SAFE_OFF, SafetyState.READY, SafetyState.RUNNING):
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"Start not allowed from {self._state.value}",
                }

            if smu_channel in self._active_sources:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"Channel {smu_channel} already active",
                }

            ok, reason = self._check_preconditions()
            if not ok:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": reason,
                }

            # Non-finite setpoints defeat every ``> max`` / ``<= 0`` guard below
            # (IEEE-754: ``nan > x`` and ``nan <= 0`` are both False), so a NaN
            # would otherwise transition the FSM and reach the hardware. Reject
            # before any limit comparison or state transition. SafetyManager is
            # the single authority, so this guard must not be bypassable.
            if not (math.isfinite(p_target) and math.isfinite(v_comp) and math.isfinite(i_comp)):
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": (f"Non-finite setpoint rejected: P={p_target} V={v_comp} I={i_comp}"),
                }

            if p_target > self._config.max_power_w:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"P={p_target}W exceeds limit {self._config.max_power_w}W",
                }
            if v_comp > self._config.max_voltage_v:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"V={v_comp}V exceeds limit {self._config.max_voltage_v}V",
                }
            if i_comp > self._config.max_current_a:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": f"I={i_comp}A exceeds limit {self._config.max_current_a}A",
                }

            # A global OFF receipt cannot remain true while another channel is
            # intentionally sourcing. Before adding a second channel, obtain
            # fresh, target-scoped OFF authority from the already-reviewed
            # source capability. This happens under _cmd_lock and immediately
            # before start_source, so no competing source command can consume
            # or invalidate the proof. Never promote it to global OFF truth.
            if not self._mock and self._active_sources:
                assert self._keithley is not None
                target_off_error = f"Target {smu_channel} OFF state is UNVERIFIED before RUN"
                if (
                    not self._reviewed_source_identity_qualified
                    or self._reviewed_source_generation is None
                    or not self._reviewed_source_connected
                ):
                    return {
                        "ok": False,
                        "state": self._state.value,
                        "channel": smu_channel,
                        "error": target_off_error,
                    }
                target_off_task = asyncio.create_task(self._keithley.emergency_off(smu_channel))
                target_result, target_error, target_cancelled = await _settle_shielded_hardware_task(
                    target_off_task,
                    cancel_owned_on_caller_cancel=True,
                )
                target_off_confirmed = target_cancelled is None and target_error is None and target_result is True
                if target_error is not None:
                    logger.critical("%s: %s", target_off_error, target_error)
                if not target_off_confirmed:
                    await self._fault(target_off_error, channel=smu_channel)
                    if target_cancelled is not None:
                        raise target_cancelled
                    return {
                        "ok": False,
                        "state": self._state.value,
                        "channel": smu_channel,
                        "error": target_off_error,
                    }
                if target_cancelled is not None:
                    raise target_cancelled

                # The target proof is only evidence that this not-yet-started
                # channel is OFF. A child death or competing abort can land
                # while that proof is in flight; consume it before any state
                # transition or source mutation and preserve an existing
                # FAULT_LATCHED state exactly.
                self._observe_terminal_safety_children()
                authority_changed = (
                    self._abort_generation != start_abort_generation
                    or self._state == SafetyState.FAULT_LATCHED
                    or not self._safety_children_authoritative()
                )
                if authority_changed:
                    full_shutdown = (
                        self._state == SafetyState.FAULT_LATCHED or self._full_abort_generation > start_abort_generation
                    )
                    if full_shutdown:
                        off_task = asyncio.create_task(self._ensure_output_off())
                        off_result, off_error, off_cancelled = await _settle_shielded_hardware_task(off_task)
                        confirmed_off = off_error is None and off_result is True
                        if confirmed_off:
                            self._active_sources.clear()
                            self._refresh_operator_safety_snapshot()
                        else:
                            await self._fault(
                                f"Safety authority changed during target OFF proof for {smu_channel}",
                                channel=smu_channel,
                            )
                        if off_cancelled is not None:
                            raise off_cancelled
                    return {
                        "ok": False,
                        "state": self._state.value,
                        "channel": smu_channel,
                        "applied": {"output_off_confirmed": [smu_channel]},
                        "error": "Safety authority changed before source start",
                    }

            # Connection authority is committed only by the exact reviewed
            # lifecycle generation. Mere object presence is never authority.
            if self._mock:
                self._reviewed_source_connected = True
            self._reviewed_source_verified_off = False
            self._refresh_operator_safety_snapshot()
            if self._state != SafetyState.RUNNING:
                self._run_permitted_since = time.monotonic()
                self._transition(
                    SafetyState.RUN_PERMITTED,
                    f"Start requested for {smu_channel}: P={p_target}W",
                    channel=smu_channel,
                    value=p_target,
                )

            if self._keithley is None:
                if self._config.require_keithley_for_run and not self._mock:
                    self._transition(SafetyState.SAFE_OFF, "Keithley not connected")
                    return {
                        "ok": False,
                        "state": self._state.value,
                        "channel": smu_channel,
                        "error": "Keithley not connected",
                    }
            else:
                start_task = asyncio.create_task(
                    self._keithley.start_source(smu_channel, p_target, v_comp, i_comp),
                    name=f"safety_start_source_{smu_channel}",
                )
                _start_result, start_error, caller_cancelled = await _settle_shielded_hardware_task(start_task)

                if caller_cancelled is not None:
                    # The retained start owner has settled before this full
                    # OFF begins, so no late OUTPUT_ON can land after OFF.
                    self._register_abort_intent(full=True)
                    off_task = asyncio.create_task(
                        self._emergency_off_locked(None),
                        name=f"cancelled_start_full_off_{smu_channel}",
                    )
                    _off_result, off_error, off_cancelled = await _settle_shielded_hardware_task(off_task)
                    caller_cancelled = caller_cancelled or off_cancelled
                    if off_error is not None:
                        logger.critical(
                            "Cancelled start on %s could not settle full emergency OFF: %s",
                            smu_channel,
                            off_error,
                        )
                        fault_task = asyncio.create_task(
                            self._fault(
                                f"cancelled start on {smu_channel} could not settle full OFF",
                                channel=smu_channel,
                            )
                        )
                        _fault_result, fault_error, fault_cancelled = await _settle_shielded_hardware_task(fault_task)
                        caller_cancelled = caller_cancelled or fault_cancelled
                        if fault_error is not None:
                            logger.critical(
                                "Cancelled start fault settlement failed on %s: %s",
                                smu_channel,
                                fault_error,
                            )
                    raise caller_cancelled

                if start_error is not None:
                    await self._fault(
                        f"Source start failed on {smu_channel}: {start_error}",
                        channel=smu_channel,
                    )
                    return {
                        "ok": False,
                        "state": self._state.value,
                        "channel": smu_channel,
                        "error": str(start_error),
                    }

                # A child can already be terminal while its done callback is
                # still queued behind this resumed request. Observe exact task
                # liveness here, advance the same full-abort generation, and
                # let the established rollback path settle OFF.
                if not self._safety_children_authoritative():
                    self._observe_terminal_safety_children()
                    if self._abort_generation == start_abort_generation:
                        self._register_abort_intent(full=True)

                # CRITICAL safety reconciliation (Phase 1 review P0-2):
                # _fault() runs OUTSIDE _cmd_lock — a fail-on-silence /
                # rate-limit / interlock fault can fire while we are awaiting
                # start_source(). When that happens, _fault has already issued
                # emergency_off and latched FAULT_LATCHED. We must NOT add the
                # channel to _active_sources, and as defense-in-depth we
                # re-issue emergency_off in case start_source's last write
                # interleaved after the fault's OUTPUT_OFF.
                if self._state == SafetyState.FAULT_LATCHED:
                    off_task = asyncio.create_task(self._ensure_output_off())
                    _off_result, off_error, off_cancelled = await _settle_shielded_hardware_task(off_task)
                    if off_error is not None:
                        logger.critical("FAULT after start_source: emergency_off failed: %s", off_error)
                    if off_cancelled is not None:
                        raise off_cancelled
                    return {
                        "ok": False,
                        "state": self._state.value,
                        "channel": smu_channel,
                        "error": f"Fault during start: {self._fault_reason}",
                    }

            # F4 liveness: a soft interlock trip OR an operator emergency_off
            # (A10) may have raised the pending-abort flag while we were
            # awaiting start_source (which holds _cmd_lock through slow SCPI
            # I/O). If so, do NOT commit this source — revert the just-started
            # output OFF and abort. The abort handler (blocked on _cmd_lock
            # behind us) then completes its own shutdown/bookkeeping. No await
            # sits between this check and the commit below, so the decision is
            # atomic.
            if self._abort_generation != start_abort_generation and self._keithley is not None:
                full_shutdown = self._full_abort_generation > start_abort_generation
                logger.warning(
                    "request_run(%s) aborted: abort signal (interlock trip or "
                    "operator emergency_off) arrived during start — reverting "
                    "output OFF, not committing source",
                    smu_channel,
                )
                off_task = asyncio.create_task(self._ensure_output_off(None if full_shutdown else smu_channel))
                off_result, off_error, abort_caller_cancelled = await _settle_shielded_hardware_task(off_task)
                confirmed_off = off_error is None and off_result is True
                if off_error is not None:
                    logger.critical(
                        "request_run abort emergency_off(%s) failed: %s",
                        smu_channel,
                        off_error,
                    )
                if not confirmed_off:
                    await self._fault(
                        f"request_run({smu_channel}) abort could not confirm OFF",
                        channel=smu_channel,
                    )
                elif self._state != SafetyState.FAULT_LATCHED:
                    if full_shutdown:
                        self._active_sources.clear()
                    if self._active_sources:
                        self._transition(
                            SafetyState.RUNNING,
                            f"Start aborted for {smu_channel}; existing sources remain",
                            channel=smu_channel,
                        )
                    else:
                        self._transition(
                            SafetyState.SAFE_OFF,
                            f"Start aborted before commit for {smu_channel}",
                            channel=smu_channel,
                        )
                    await self._publish_keithley_channel_states(f"start_aborted:{smu_channel}")
                if abort_caller_cancelled is not None:
                    raise abort_caller_cancelled
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channel": smu_channel,
                    "error": "Interlock trip during start — source not activated",
                }

            self._active_sources.add(smu_channel)
            if self._state != SafetyState.RUNNING:
                self._transition(
                    SafetyState.RUNNING,
                    f"Source {smu_channel} enabled: P={p_target}W",
                    channel=smu_channel,
                    value=p_target,
                )
            else:
                self._refresh_operator_safety_snapshot()
            publish_task = asyncio.create_task(
                self._publish_keithley_channel_states(f"run:{smu_channel}"),
                name=f"publish_run_{smu_channel}",
            )
            _publish_result, publish_error, publish_cancelled = await _settle_shielded_hardware_task(publish_task)
            if publish_error is not None or publish_cancelled is not None:
                # The caller has not received an activation receipt.  Never
                # expose cancellation/exception while leaving that ambiguous
                # source ON: settle a full exact OFF first.
                self._register_abort_intent(full=True)
                off_task = asyncio.create_task(
                    self._emergency_off_locked(None),
                    name=f"unacknowledged_run_full_off_{smu_channel}",
                )
                _off_result, off_error, off_cancelled = await _settle_shielded_hardware_task(off_task)
                if off_error is not None:
                    logger.critical(
                        "Unacknowledged RUN on %s could not settle full OFF: %s",
                        smu_channel,
                        off_error,
                    )
                    fault_task = asyncio.create_task(
                        self._fault(
                            f"unacknowledged RUN on {smu_channel} could not settle full OFF",
                            channel=smu_channel,
                        )
                    )
                    _fault_result, fault_error, fault_cancelled = await _settle_shielded_hardware_task(fault_task)
                    off_cancelled = off_cancelled or fault_cancelled
                    if fault_error is not None:
                        logger.critical(
                            "Unacknowledged RUN fault settlement failed on %s: %s",
                            smu_channel,
                            fault_error,
                        )
                cancellation = publish_cancelled or off_cancelled
                if cancellation is not None:
                    raise cancellation
                assert publish_error is not None
                raise publish_error
            return {
                "ok": True,
                "state": self._state.value,
                "channel": smu_channel,
                "active_channels": sorted(self._active_sources),
            }

    async def request_stop(self, *, channel: str | None = None) -> dict[str, Any]:
        """Own stop intent and the complete lock-to-publication settlement."""
        stop_abort_generation = self._register_abort_intent(full=channel is None)
        operation = asyncio.create_task(
            self._request_stop_owned(
                channel=channel,
                expected_abort_generation=stop_abort_generation,
            ),
            name="safety_request_stop",
        )
        result, error, caller_cancelled = await _settle_shielded_hardware_task(operation)
        if error is not None:
            raise error
        if caller_cancelled is not None:
            raise caller_cancelled
        assert isinstance(result, dict)
        return result

    async def _request_stop_owned(
        self,
        *,
        channel: str | None = None,
        expected_abort_generation: int,
    ) -> dict[str, Any]:
        async with self._cmd_lock:
            channels = self._resolve_channels(channel)
            if self._state == SafetyState.FAULT_LATCHED:
                await self._ensure_output_off(channel)
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channels": sorted(channels),
                    "error": "System is fault-latched - acknowledge_fault required",
                }

            applied_off, interrupted = await self._safe_off(
                "Operator stop",
                channels=channels,
                expected_abort_generation=expected_abort_generation,
            )
            await self._publish_keithley_channel_states("stop")
            self._observe_terminal_safety_children()
            interrupted = interrupted or (
                self._abort_generation != expected_abort_generation
                or self._state == SafetyState.FAULT_LATCHED
                or not self._safety_children_authoritative()
            )
            if self._state == SafetyState.FAULT_LATCHED or interrupted:
                # _safe_off fail-closed: the turn-off failed and latched a fault.
                # Report that honestly rather than a successful stop.
                return {
                    "ok": False,
                    "state": self._state.value,
                    "channels": sorted(channels),
                    "active_channels": sorted(self._active_sources),
                    "applied_off_channels": sorted(applied_off),
                    "error": (
                        f"Stop failed, fault latched: {self._fault_reason}"
                        if self._state == SafetyState.FAULT_LATCHED
                        else "Stop interrupted by a competing safety-authority change"
                    ),
                }
            return {
                "ok": True,
                "state": self._state.value,
                "channels": sorted(channels),
                "active_channels": sorted(self._active_sources),
            }

    async def emergency_off(self, *, channel: str | None = None) -> dict[str, Any]:
        # A10 operator fast-abort: advance the F4 abort generation BEFORE
        # contending for _cmd_lock. An in-flight request_run holding the lock
        # through slow start_source SCPI I/O then aborts at its next F4
        # checkpoint (see request_run) instead of this operator emergency
        # queuing behind that round-trip. Statements before ``async with`` run
        # synchronously when the coroutine is first stepped — strictly before
        # it awaits the lock. Same generation + semantics as the interlock
        # stop_source path: the abort lands at the NEXT checkpoint, NOT
        # mid-wire — an in-flight SCPI write completes first (blast radius ≈
        # one round-trip, tens of ms). It does NOT preempt a write already on
        # the wire. Later runs capture the settled generation, while any run
        # already in flight must observe the change and abort.
        self._register_abort_intent(full=channel is None)
        operation = asyncio.create_task(
            self._emergency_off_with_lock(channel),
            name="safety_emergency_off",
        )
        result, error, caller_cancelled = await _settle_shielded_hardware_task(operation)
        if error is not None:
            raise error
        if caller_cancelled is not None:
            raise caller_cancelled
        assert isinstance(result, dict)
        return result

    async def _emergency_off_with_lock(self, channel: str | None) -> dict[str, Any]:
        """Own lock acquisition and the full OFF bookkeeping as one task."""
        async with self._cmd_lock:
            return await self._emergency_off_locked(channel)

    async def disconnect_reviewed_source(
        self,
        driver: Any,
        runtime_binding: DriverRuntimeBinding,
        generation: object | None,
        context: str,
    ) -> bool:
        """Prove the exact reviewed source OFF before scheduler disconnect."""
        del generation  # Full fail-closed OFF remains available after revocation.
        self._require_reviewed_source_identity(driver, runtime_binding)
        self._register_abort_intent(full=True)
        cancelled: asyncio.CancelledError | None = None
        async with self._cmd_lock:
            self._require_reviewed_source_identity(driver, runtime_binding)
            self._reviewed_source_generation = None
            self._reviewed_source_connected = False
            self._reviewed_source_verified_off = False
            self._refresh_operator_safety_snapshot()

            proof_task = asyncio.create_task(driver.emergency_off())
            proof_result, proof_error, proof_cancelled = await _settle_shielded_hardware_task(proof_task)
            cancelled = proof_cancelled
            confirmed = proof_error is None and proof_result is True
            if proof_error is not None and not isinstance(proof_error, asyncio.CancelledError):
                logger.exception(
                    "Reviewed-source OFF proof failed during scheduler disconnect (%s)",
                    context,
                    exc_info=proof_error,
                )

            if not confirmed:
                self._reviewed_source_verified_off = False
                self._refresh_operator_safety_snapshot()
                await self._fault(f"reviewed source disconnect lacked verified OFF ({context})")
                if cancelled is not None:
                    raise cancelled
                return False

            disconnect_task = asyncio.create_task(driver.disconnect())
            _result, disconnect_error, disconnect_cancelled = await _settle_shielded_hardware_task(disconnect_task)
            cancelled = cancelled or disconnect_cancelled
            disconnected = getattr(driver, "connected", None) is False
            if disconnect_error is not None or not disconnected:
                if disconnect_error is not None:
                    logger.critical("Reviewed-source disconnect failed after verified OFF: %s", disconnect_error)
                else:
                    logger.critical("Reviewed-source disconnect returned normally without connected=False")
                await self._fault(f"reviewed source disconnect failed after OFF proof ({context})")
                if cancelled is not None:
                    raise cancelled
                return False

            self._active_sources.clear()
            self._reviewed_source_connected = False
            self._reviewed_source_verified_off = False
            self._refresh_operator_safety_snapshot()
            if self._state != SafetyState.FAULT_LATCHED:
                self._transition(
                    SafetyState.SAFE_OFF,
                    f"Reviewed source disconnected: {context}",
                )
            publish_task = asyncio.create_task(self._publish_keithley_channel_states("reviewed_source_disconnected"))
            _result, publish_error, publish_cancelled = await _settle_shielded_hardware_task(publish_task)
            cancelled = cancelled or publish_cancelled
            if publish_error is not None:
                logger.warning(
                    "Reviewed-source disconnected-state publish failed: %s",
                    publish_error,
                )
            if cancelled is not None:
                raise cancelled
            return True

    def _register_abort_intent(self, *, full: bool) -> int:
        """Register cancellation-proof abort scope for competing starts."""
        self._abort_generation += 1
        if full:
            self._full_abort_generation = self._abort_generation
        return self._abort_generation

    async def _emergency_off_locked(self, channel: str | None) -> dict[str, Any]:
        """emergency_off body; MUST be called holding ``_cmd_lock``."""
        channels = self._resolve_channels(channel)
        confirmed = await self._ensure_output_off(channel)
        if not confirmed:
            # FAIL CLOSED (CR-2). The driver could not confirm output OFF
            # (write raised or readback still reports ON) — the SMU may
            # still be sourcing. Reporting ok=True and dropping to
            # SAFE_OFF would silently stop ALL stale/heartbeat/rate
            # monitoring while power is live. Latch a fault instead —
            # _fault() clears _active_sources, re-fires the shielded
            # emergency_off (retry OUTPUT_OFF + verify) and publishes
            # channel states. _fault is lock-free and idempotent, so
            # calling it here under _cmd_lock is safe (same discipline
            # as the stop_source failure path in _safe_off).
            reason = "emergency_off could not confirm output OFF"
            logger.critical(
                "%s (channels=%s) — latching fault (fail-closed)",
                reason,
                sorted(channels),
            )
            await self._fault(reason, channel=channel or "")
            return {
                "ok": False,
                "state": self._state.value,
                "channels": sorted(channels),
                "active_channels": sorted(self._active_sources),
                "error": reason,
            }
        self._active_sources.difference_update(channels)
        self._refresh_operator_safety_snapshot()

        if self._state == SafetyState.FAULT_LATCHED:
            result = {
                "ok": True,
                "state": self._state.value,
                "channels": sorted(channels),
                "active_channels": sorted(self._active_sources),
                "latched": True,
                "warning": "Outputs disabled but fault remains latched",
            }
        else:
            if not self._active_sources:
                self._transition(SafetyState.SAFE_OFF, "Operator emergency off")
            result = {
                "ok": True,
                "state": self._state.value,
                "channels": sorted(channels),
                "active_channels": sorted(self._active_sources),
            }
        publish_task = asyncio.create_task(self._publish_keithley_channel_states("emergency_off"))
        _result, publish_error, publish_cancelled = await _settle_shielded_hardware_task(publish_task)
        if publish_error is not None:
            logger.warning("Emergency-OFF state publish failed: %s", publish_error)
        if publish_cancelled is not None:
            raise publish_cancelled
        return result

    async def update_target(self, p_target: float, *, channel: str | None = None) -> dict[str, Any]:
        """Live-update P_target on an active channel. Validates against config limits.

        Updates ``runtime.p_target`` in-memory. The hardware voltage is NOT
        changed here directly — the P=const regulation loop in
        ``Keithley2604B.read_channels()`` reads ``runtime.p_target`` on every
        poll cycle and recomputes ``target_v = sqrt(p_target * R)``.

        Convergence time depends on the size of the p_target step. For small
        steps (delta_v ≤ MAX_DELTA_V_PER_STEP = 0.5 V), convergence completes
        in one poll interval (typically ≤1 s). For larger steps, the
        slew-rate limiter caps voltage change at 0.5 V per poll cycle, so
        full convergence may take multiple seconds (e.g., a 0.5W → 5W jump
        on 100Ω can require ~15 polls = ~7-15 s depending on poll interval).

        This is intentional: slew-rate limiting and compliance checks live in
        the regulation loop and must not be bypassed by direct SCPI writes.
        """
        async with self._cmd_lock:
            smu_channel = normalize_smu_channel(channel)

            if not self._safety_children_authoritative():
                return {"ok": False, "error": "Safety child authority is unavailable"}

            if self._state == SafetyState.FAULT_LATCHED:
                return {"ok": False, "error": f"FAULT: {self._fault_reason}"}

            if smu_channel not in self._active_sources:
                return {"ok": False, "error": f"Channel {smu_channel} not active"}

            if not math.isfinite(p_target):
                return {"ok": False, "error": f"Non-finite p_target rejected: {p_target}"}

            if p_target <= 0:
                return {"ok": False, "error": "p_target must be > 0"}

            if p_target > self._config.max_power_w:
                return {
                    "ok": False,
                    "error": f"P={p_target}W exceeds limit {self._config.max_power_w}W",
                }

            if self._keithley is None:
                return {"ok": False, "error": "Keithley not connected"}

            runtime = self._keithley._channels.get(smu_channel)
            if runtime is None or not runtime.active:
                return {"ok": False, "error": f"Channel {smu_channel} not active on instrument"}

            old_p = runtime.p_target
            runtime.p_target = p_target
            logger.info("SAFETY: P_target update %s: %.4f → %.4f W", smu_channel, old_p, p_target)

            return {"ok": True, "channel": smu_channel, "p_target": p_target}

    async def update_limits(
        self,
        *,
        channel: str | None = None,
        v_comp: float | None = None,
        i_comp: float | None = None,
    ) -> dict[str, Any]:
        """Live-update V/I compliance limits. Validates against config limits."""
        async with self._cmd_lock:
            smu_channel = normalize_smu_channel(channel)
            update_abort_generation = self._abort_generation

            if not self._safety_children_authoritative():
                return {"ok": False, "error": "Safety child authority is unavailable"}

            if self._state == SafetyState.FAULT_LATCHED:
                return {"ok": False, "error": f"FAULT: {self._fault_reason}"}

            if smu_channel not in self._active_sources:
                return {"ok": False, "error": f"Channel {smu_channel} not active"}

            if self._keithley is None:
                return {"ok": False, "error": "Keithley not connected"}

            runtime = self._keithley._channels.get(smu_channel)
            if runtime is None or not runtime.active:
                return {"ok": False, "error": f"Channel {smu_channel} not active on instrument"}

            # Validate BOTH provided fields before any SCPI write or runtime
            # mutation. Otherwise update_limits(v_comp=valid, i_comp=nan) would
            # write a valid voltage limit and only then reject the current —
            # leaving the hardware in a partially-applied state.
            if v_comp is not None:
                if not math.isfinite(v_comp):
                    return {"ok": False, "error": f"Non-finite v_comp rejected: {v_comp}"}
                if v_comp <= 0:
                    return {"ok": False, "error": "v_comp must be > 0"}
                if v_comp > self._config.max_voltage_v:
                    return {
                        "ok": False,
                        "error": f"V={v_comp}V exceeds limit {self._config.max_voltage_v}V",
                    }

            if i_comp is not None:
                if not math.isfinite(i_comp):
                    return {"ok": False, "error": f"Non-finite i_comp rejected: {i_comp}"}
                if i_comp <= 0:
                    return {"ok": False, "error": "i_comp must be > 0"}
                if i_comp > self._config.max_current_a:
                    return {
                        "ok": False,
                        "error": f"I={i_comp}A exceeds limit {self._config.max_current_a}A",
                    }

            # All provided values validated — now apply.
            applied: dict[str, float] = {}
            if v_comp is not None:
                if not self._keithley.mock:
                    write_task = asyncio.create_task(
                        self._keithley._transport.write(f"{smu_channel}.source.limitv = {v_comp}"),
                        name=f"safety_limitv_write_{smu_channel}",
                    )
                    _result, write_error, write_cancelled = await _settle_shielded_hardware_task(write_task)
                    if write_error is not None:
                        reason = (
                            f"Voltage-limit write outcome is uncertain on {smu_channel}: {type(write_error).__name__}"
                        )
                        logger.critical("%s: %s", reason, write_error)
                        await self._fault(reason, channel=smu_channel, source="safety_limit_update")
                        if write_cancelled is not None:
                            raise write_cancelled
                        return {
                            "ok": False,
                            "error": reason,
                            "applied": applied,
                            "uncertain": ["v_comp"],
                        }
                    # The SCPI write may already have reached hardware. Record
                    # that fact before checking whether authority was lost
                    # during the await; retaining the old cache would invent a
                    # hardware/software agreement that no longer exists.
                    runtime.v_comp = v_comp
                    applied["v_comp"] = v_comp
                    if write_cancelled is not None:
                        await self._fault(
                            f"Voltage-limit write completed after caller cancellation on {smu_channel}",
                            channel=smu_channel,
                            source="safety_limit_update",
                        )
                        raise write_cancelled
                    self._observe_terminal_safety_children()
                    if (
                        self._abort_generation != update_abort_generation
                        or self._state == SafetyState.FAULT_LATCHED
                        or not self._safety_children_authoritative()
                    ):
                        return {
                            "ok": False,
                            "error": "Safety authority was lost after a limit write reached hardware",
                            "applied": applied,
                        }
                else:
                    runtime.v_comp = v_comp
                    applied["v_comp"] = v_comp

            if i_comp is not None:
                if not self._keithley.mock:
                    write_task = asyncio.create_task(
                        self._keithley._transport.write(f"{smu_channel}.source.limiti = {i_comp}"),
                        name=f"safety_limiti_write_{smu_channel}",
                    )
                    _result, write_error, write_cancelled = await _settle_shielded_hardware_task(write_task)
                    if write_error is not None:
                        reason = (
                            f"Current-limit write outcome is uncertain on {smu_channel}: {type(write_error).__name__}"
                        )
                        logger.critical("%s: %s", reason, write_error)
                        await self._fault(reason, channel=smu_channel, source="safety_limit_update")
                        if write_cancelled is not None:
                            raise write_cancelled
                        return {
                            "ok": False,
                            "error": reason,
                            "applied": applied,
                            "uncertain": ["i_comp"],
                        }
                    runtime.i_comp = i_comp
                    applied["i_comp"] = i_comp
                    if write_cancelled is not None:
                        await self._fault(
                            f"Current-limit write completed after caller cancellation on {smu_channel}",
                            channel=smu_channel,
                            source="safety_limit_update",
                        )
                        raise write_cancelled
                    self._observe_terminal_safety_children()
                    if (
                        self._abort_generation != update_abort_generation
                        or self._state == SafetyState.FAULT_LATCHED
                        or not self._safety_children_authoritative()
                    ):
                        return {
                            "ok": False,
                            "error": "Safety authority was lost after a limit write reached hardware",
                            "applied": applied,
                        }
                else:
                    runtime.i_comp = i_comp
                    applied["i_comp"] = i_comp

            logger.info(
                "SAFETY: limits update %s: V_comp=%.1f I_comp=%.3f",
                smu_channel,
                runtime.v_comp,
                runtime.i_comp,
            )
            return {
                "ok": True,
                "channel": smu_channel,
                "v_comp": runtime.v_comp,
                "i_comp": runtime.i_comp,
            }

    async def acknowledge_fault(self, reason: str) -> dict[str, Any]:
        async with self._cmd_lock:
            if self._state != SafetyState.FAULT_LATCHED:
                return {
                    "ok": False,
                    "state": self._state.value,
                    "error": "Нет активной аварии для подтверждения",
                }
            if self._config.require_reason and not reason.strip():
                return {"ok": False, "state": self._state.value, "error": "Укажите причину аварии"}

            elapsed = time.monotonic() - self._fault_time
            if elapsed < self._config.cooldown_before_rearm_s:
                remaining = self._config.cooldown_before_rearm_s - elapsed
                return {
                    "ok": False,
                    "state": self._state.value,
                    "error": f"Ожидание: ещё {remaining:.0f}с до разрешения восстановления",
                }

            self._recovery_reason = reason.strip()
            # Watchdog trip evidence is consumed only by this explicit
            # operator-authorized recovery path. The driver first re-verifies
            # both outputs OFF, then atomically clears the TSP latch and
            # reactivates late-pet checking. Any readback/transport ambiguity
            # keeps FAULT_LATCHED and returns an actionable error; reconnect is
            # explicit operator work, never a hidden monitor-loop side effect.
            wdog_ack = getattr(self._keithley, "acknowledge_wdog_trip", None)
            if callable(wdog_ack):
                try:
                    ack_result = wdog_ack()
                    wdog_ok = bool(await ack_result) if inspect.isawaitable(ack_result) else bool(ack_result)
                except Exception as exc:
                    logger.critical("Watchdog trip acknowledgment failed: %s", exc)
                    wdog_ok = False
                if not wdog_ok:
                    return {
                        "ok": False,
                        "state": self._state.value,
                        "error": (
                            "Watchdog trip evidence could not be acknowledged "
                            "after verified OFF; fault remains latched. Retry "
                            "emergency OFF, then acknowledge, or explicitly "
                            "disconnect/reconnect the Keithley. With "
                            "watchdog.mode=required and non-autonomous v3, "
                            "explicitly select best_effort first (off only "
                            "intentionally disables the TSP path)."
                        ),
                    }
            # Phase 2a H.1: clear persistence-failure latch on the writer
            # via the engine-wired callback. This is what unblocks scheduler
            # polling — DiskMonitor only logs recovery, it does not clear.
            if self._persistence_failure_clear is not None:
                try:
                    self._persistence_failure_clear()
                except Exception as exc:
                    logger.error("persistence_failure_clear callback failed: %s", exc)
            self._persistence_fault_active = False
            self._transition(SafetyState.MANUAL_RECOVERY, f"Fault acknowledged: {reason}")
            await self._publish_keithley_channel_states("fault_acknowledged")
            return {"ok": True, "state": self._state.value}

    def set_persistence_failure_clear(self, callback: Callable[[], None]) -> None:
        """Register a sync callback that clears external persistence-failure
        flags (Phase 2a H.1). Called from acknowledge_fault."""
        self._persistence_failure_clear = callback

    def _critical_input_snapshot_fact(self, now: float) -> tuple[PlantHealthFact, SafetyBlocker | None]:
        for pattern in self._config.critical_channels:
            matches = [(channel, sample) for channel, sample in self._latest.items() if pattern.match(channel)]
            if not matches and not self._mock:
                return (
                    PlantHealthFact(
                        "critical_inputs",
                        "Critical inputs",
                        OperatorPresentationState.DISCONNECTED,
                        "critical_input_missing",
                    ),
                    SafetyBlocker(
                        "critical_input_missing",
                        OperatorPresentationState.DISCONNECTED,
                        "A required critical input is unavailable",
                        "Restore a current valid critical-channel reading",
                    ),
                )
            for _channel, (observed, value, status) in matches:
                if now - observed > self._config.stale_timeout_s:
                    return (
                        PlantHealthFact(
                            "critical_inputs",
                            "Critical inputs",
                            OperatorPresentationState.STALE,
                            "critical_input_stale",
                        ),
                        SafetyBlocker(
                            "critical_input_stale",
                            OperatorPresentationState.STALE,
                            "A required critical input is stale",
                            "Restore fresh critical-channel readings",
                        ),
                    )
                if status != "ok" or not math.isfinite(value):
                    return (
                        PlantHealthFact(
                            "critical_inputs",
                            "Critical inputs",
                            OperatorPresentationState.FAULT,
                            "critical_input_invalid",
                        ),
                        SafetyBlocker(
                            "critical_input_invalid",
                            OperatorPresentationState.FAULT,
                            "A required critical input is invalid",
                            "Restore valid critical-channel readings",
                        ),
                    )
        return (
            PlantHealthFact(
                "critical_inputs",
                "Critical inputs",
                OperatorPresentationState.OK,
                "critical_inputs_current",
            ),
            None,
        )

    def _refresh_operator_safety_snapshot(self) -> None:
        """Replace the owner cut synchronously from already-owned facts only."""
        previous = self._operator_safety_snapshot
        observed = max(time.monotonic(), previous.observed_monotonic_s)
        lifecycle = SafetyLifecycle(self._state.value)
        children_authoritative = self._safety_children_authoritative()
        verified_off = (
            children_authoritative
            and self._reviewed_source_verified_off
            and not self._active_sources
            and lifecycle not in {SafetyLifecycle.RUN_PERMITTED, SafetyLifecycle.RUNNING}
        )
        blockers: list[SafetyBlocker] = []
        plant: list[PlantHealthFact] = []

        if children_authoritative:
            plant.append(
                PlantHealthFact(
                    "safety_monitor",
                    "Safety monitor and collector",
                    OperatorPresentationState.OK,
                    "safety_children_active",
                )
            )
        else:
            failed_role = self._failed_child_role or "monitor"
            failed_reason = self._failed_child_reason or "safety_monitor_inactive"
            display_name = "Safety reading collector" if failed_role == "collect" else "Safety monitor"
            plant.append(
                PlantHealthFact(
                    f"safety_{failed_role}",
                    display_name,
                    OperatorPresentationState.DISCONNECTED,
                    failed_reason,
                )
            )
            blockers.append(
                SafetyBlocker(
                    failed_reason,
                    OperatorPresentationState.DISCONNECTED,
                    f"The {display_name.lower()} is not active",
                    "Restart the SafetyManager and verify both child tasks remain live",
                )
            )

        if not self._reviewed_source_connected:
            plant.append(
                PlantHealthFact(
                    "reviewed_source",
                    "Reviewed source",
                    OperatorPresentationState.DISCONNECTED,
                    "reviewed_source_disconnected",
                )
            )
            blockers.append(
                SafetyBlocker(
                    "reviewed_source_disconnected",
                    OperatorPresentationState.DISCONNECTED,
                    "The reviewed source is disconnected or unqualified",
                    "Connect it through reviewed wiring and submit current evidence",
                )
            )
        elif not verified_off:
            source_state = (
                OperatorPresentationState.WARNING if self._active_sources else OperatorPresentationState.CAUTION
            )
            plant.append(
                PlantHealthFact(
                    "reviewed_source",
                    "Reviewed source",
                    source_state,
                    "reviewed_source_off_unverified",
                )
            )
            blockers.append(
                SafetyBlocker(
                    "reviewed_source_off_unverified",
                    source_state,
                    "The reviewed source lacks current verified-OFF evidence",
                    "Obtain exact final-element OFF readback for this connection",
                )
            )
        else:
            plant.append(
                PlantHealthFact(
                    "reviewed_source",
                    "Reviewed source",
                    OperatorPresentationState.OK,
                    "reviewed_source_verified_off",
                )
            )

        critical_fact, critical_blocker = self._critical_input_snapshot_fact(observed)
        plant.append(critical_fact)
        if critical_blocker is not None:
            blockers.append(critical_blocker)

        if self._persistence_fault_active:
            plant.append(
                PlantHealthFact(
                    "persistence",
                    "Persistence",
                    OperatorPresentationState.FAULT,
                    "persistence_fault_active",
                )
            )
            blockers.append(
                SafetyBlocker(
                    "persistence_fault_active",
                    OperatorPresentationState.FAULT,
                    "Persistence has an unacknowledged failure",
                    "Restore persistence and complete explicit fault recovery",
                )
            )
        else:
            plant.append(
                PlantHealthFact(
                    "persistence",
                    "Persistence",
                    OperatorPresentationState.OK,
                    "persistence_fault_absent",
                )
            )

        fsm_state = OperatorPresentationState.OK
        fsm_reason = f"safety_state_{self._state.value}"
        if lifecycle in {SafetyLifecycle.FAULT_LATCHED, SafetyLifecycle.MANUAL_RECOVERY}:
            fsm_state = OperatorPresentationState.FAULT
            blockers.append(
                SafetyBlocker(
                    fsm_reason,
                    OperatorPresentationState.FAULT,
                    "Safety fault recovery is incomplete",
                    "Complete the explicit acknowledged recovery procedure",
                )
            )
        elif lifecycle in {SafetyLifecycle.RUN_PERMITTED, SafetyLifecycle.RUNNING}:
            fsm_state = OperatorPresentationState.WARNING
            blockers.append(
                SafetyBlocker(
                    "source_operation_active",
                    OperatorPresentationState.WARNING,
                    "A source operation is active or being enabled",
                    "Reach a readback-verified OFF state before readiness",
                )
            )
        elif lifecycle is SafetyLifecycle.SAFE_OFF:
            fsm_state = OperatorPresentationState.CAUTION
            blockers.append(
                SafetyBlocker(
                    "safety_state_safe_off",
                    OperatorPresentationState.CAUTION,
                    "Safety is OFF but readiness has not been committed",
                    "Wait for the safety monitor to commit READY preconditions",
                )
            )
        plant.insert(0, PlantHealthFact("safety_fsm", "Safety state", fsm_state, fsm_reason))

        if lifecycle is SafetyLifecycle.READY and not blockers:
            readiness = ReadinessTruth.READY
        elif lifecycle is SafetyLifecycle.READY:
            # The raw legacy FSM has no representation for READY-but-unproved.
            # Never publish that contradiction as READY; authority remains
            # explicitly UNKNOWN until reviewed evidence catches up.
            lifecycle = SafetyLifecycle.UNKNOWN
            readiness = ReadinessTruth.UNKNOWN
            verified_off = False
            plant[0] = PlantHealthFact(
                "safety_fsm",
                "Safety state",
                OperatorPresentationState.CAUTION,
                "ready_state_unqualified",
            )
        else:
            readiness = ReadinessTruth.BLOCKED

        snapshot = OperatorSafetySnapshot(
            revision=previous.revision + 1,
            observed_monotonic_s=observed,
            lifecycle=lifecycle,
            readiness=readiness,
            verified_off=verified_off,
            blockers=tuple(blockers),
            plant_health=tuple(plant),
        )
        if type(snapshot) is not OperatorSafetySnapshot:
            raise TypeError("operator safety cache requires exact OperatorSafetySnapshot")
        if snapshot.revision != previous.revision + 1:
            raise ValueError("operator safety revision must advance by exactly one")
        if snapshot.observed_monotonic_s < previous.observed_monotonic_s:
            raise ValueError("operator safety observed time regressed")
        self._operator_safety_snapshot = snapshot

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "fault_reason": self._fault_reason,
            "fault_revision": self._fault_revision,
            "fault_activated_at": self._fault_activated_at,
            "recovery_reason": self._recovery_reason,
            "channels_tracked": len(self._latest),
            "keithley_connected": self._keithley is not None and getattr(self._keithley, "connected", False),
            "active_channels": sorted(self._active_sources),
            "mock": self._mock,
        }

    def get_events(self) -> list[SafetyEvent]:
        return list(self._events)

    def on_state_change(self, callback: Callable[[SafetyState, SafetyState, str], Any]) -> None:
        self._on_state_change.append(callback)

    async def _publish_state(self, reason: str = "") -> None:
        if self._data_broker is None:
            return
        reading = Reading.now(
            channel="analytics/safety_state",
            value=0.0,
            unit="",
            instrument_id="safety_manager",
            metadata={"state": self._state.value, "reason": reason},
        )
        try:
            await self._data_broker.publish(reading)
        except Exception as exc:
            logger.warning("Failed to publish safety state: %s", exc)

    async def _publish_keithley_channel_states(
        self,
        reason: str = "",
        *,
        fault_channel: str | None = None,
    ) -> None:
        if self._data_broker is None:
            return

        for smu_channel in ("smua", "smub"):
            if fault_channel == smu_channel:
                state = "fault"
                value = -1.0
            elif smu_channel in self._active_sources:
                state = "on"
                value = 1.0
            else:
                state = "off"
                value = 0.0

            reading = Reading.now(
                channel=f"analytics/keithley_channel_state/{smu_channel}",
                value=value,
                unit="",
                instrument_id="safety_manager",
                metadata={"state": state, "channel": smu_channel, "reason": reason},
            )
            try:
                await self._data_broker.publish(reading)
            except Exception as exc:
                logger.warning("Failed to publish Keithley channel state for %s: %s", smu_channel, exc)

    def _transition(
        self,
        new_state: SafetyState,
        reason: str,
        *,
        channel: str = "",
        value: float = 0.0,
    ) -> None:
        old_state = self._state
        self._state = new_state
        self._events.append(
            SafetyEvent(
                timestamp=datetime.now(UTC),
                from_state=old_state,
                to_state=new_state,
                reason=reason,
                channel=channel,
                value=value,
            )
        )

        level = logging.CRITICAL if new_state == SafetyState.FAULT_LATCHED else logging.INFO
        logger.log(level, "SAFETY: %s -> %s | %s", old_state.value, new_state.value, reason)

        # Commit the owner cut before notifying observers so callbacks cannot
        # see the new FSM state paired with the previous safety receipt.
        self._refresh_operator_safety_snapshot()

        for callback in self._on_state_change:
            try:
                callback(old_state, new_state, reason)
            except Exception:
                logger.exception("State change callback failed")

        try:
            task = asyncio.get_running_loop().create_task(
                self._publish_state(reason),
                name=f"safety_publish_{new_state.value}",
            )
            self._pending_publishes.add(task)
            task.add_done_callback(self._pending_publishes.discard)
        except RuntimeError:
            # No running loop (sync caller during tests). Publish skipped.
            pass

    async def latch_fault(
        self,
        reason: str,
        source: str,
        *,
        channel: str = "",
        value: float = 0.0,
    ) -> None:
        """Public entry point to latch FAULT_LATCHED.

        Triggers ``emergency_off``, latches the safety FSM in
        ``FAULT_LATCHED``, blocks future ``request_run()`` until the
        operator acknowledges. Use ТОЛЬКО for verified safety events
        (sensor disconnect, threshold breach, alarm CRITICAL).

        Args:
            reason: Human-readable description for audit log + Telegram
                + operator panel.
            source: Originating subsystem identifier
                (e.g. ``"cooldown_alarm"``, ``"interlock"``,
                ``"manual_emergency"``). Recorded in the operator-log
                ``author`` field for traceability.
            channel: Optional hardware channel involved in the fault
                (forwarded to Keithley channel-state publishing when it
                names ``smua`` / ``smub``).
            value: Optional reading value at fault time, included in
                the operator-log entry.

        Idempotent under FAULT_LATCHED: a second call while already
        latched is logged once and ignored — duplicate fault events
        do not stack.
        """
        await self._fault(reason=reason, channel=channel, value=value, source=source)

    def _begin_fault_latch(
        self,
        reason: str,
        *,
        channel: str = "",
        value: float = 0.0,
        source: str = "safety_manager",
    ) -> bool:
        del source
        # Early-return guard: ignore concurrent re-entries while already latched.
        # Multiple call sites (SafetyBroker overflow, monitoring loop, channel
        # faults, start_source failure) can fire in the same tick. Without
        # this guard, a second call would overwrite _fault_reason, emit
        # duplicate events + log entries, and queue a redundant emergency_off.
        # The check is safe under asyncio single-threaded semantics: state is
        # mutated synchronously below before any await, so a later call sees
        # FAULT_LATCHED and exits.
        if self._state == SafetyState.FAULT_LATCHED:
            logger.info(
                "_fault() re-entry ignored (already latched); new reason=%s channel=%s",
                reason,
                channel or "-",
            )
            return False

        # Every newly latched fault owns the same synchronous full-abort cut.
        # This prevents a mutation that resumes from an await from committing
        # after monitor/rate/persistence faults that do not originate in an
        # operator command.
        self._register_abort_intent(full=True)
        self._fault_revision += 1
        # 1. Latch fault state IMMEDIATELY — no awaits before this.
        #    _transition is synchronous, so request_run() will see
        #    FAULT_LATCHED and reject before any yield point.
        self._fault_reason = reason
        self._fault_time = time.monotonic()
        self._fault_activated_at = time.time()
        self._transition(SafetyState.FAULT_LATCHED, reason, channel=channel, value=value)
        return True

    async def _fault(
        self,
        reason: str,
        *,
        channel: str = "",
        value: float = 0.0,
        source: str = "safety_manager",
    ) -> None:
        if not self._begin_fault_latch(
            reason,
            channel=channel,
            value=value,
            source=source,
        ):
            return
        await self._settle_latched_fault(
            reason,
            channel=channel,
            value=value,
            source=source,
        )

    async def _settle_latched_fault(
        self,
        reason: str,
        *,
        channel: str = "",
        value: float = 0.0,
        source: str = "safety_manager",
    ) -> None:
        """Settle OFF, durable logging, and publication for a latched cut."""

        # 2. Now safe to do async cleanup — state already protects us.
        #    Re-entrancy is guarded by the FAULT_LATCHED early-return above (set
        #    synchronously before any await), NOT by clearing _active_sources —
        #    so the clear can be deferred until AFTER emergency_off and made
        #    conditional on a CONFIRMED off (F3).
        outputs_confirmed_off = True
        caller_cancelled: asyncio.CancelledError | None = None

        if self._keithley is not None:
            shutdown_task = asyncio.create_task(self._keithley.emergency_off())
            result, error, cancelled = await _settle_shielded_hardware_task(shutdown_task)
            caller_cancelled = cancelled
            outputs_confirmed_off = error is None and result is True
            if error is not None:
                logger.critical("FAULT: emergency_off failed: %s", error)

        # F3: only drop the sources whose OFF the driver CONFIRMED. On an
        # unconfirmed OFF (emergency_off returned False, per the CR-2 driver
        # contract, or raised) keep them in _active_sources so the published
        # safety-state payload still shows them ON — the SMU may still be
        # sourcing. The fault stays latched either way.
        if outputs_confirmed_off:
            self._active_sources.clear()
        elif self._active_sources:
            logger.critical(
                "FAULT: emergency_off could NOT confirm outputs OFF — output "
                "state UNVERIFIED on %s; keeping them tracked as active "
                "(SMU may still be sourcing)",
                sorted(self._active_sources),
            )
        if self._keithley is not None:
            retained_generation = self._has_current_reviewed_connection_generation()
            self._reviewed_source_connected = retained_generation
            self._reviewed_source_verified_off = retained_generation and outputs_confirmed_off
        self._refresh_operator_safety_snapshot()

        # 4. Post-mortem log emission — shielded — MUST happen after hardware
        #    shutdown but BEFORE optional broker publish. Previously this came
        #    after publish, creating an escape path if publish was cancelled
        #    (Jules Round 2 Q1).
        if self._fault_log_callback is not None:
            log_task = asyncio.create_task(
                self._fault_log_callback(
                    source=source,
                    message=f"Safety fault: {reason}",
                    channel=channel,
                    value=value,
                )
            )
            _result, error, cancelled = await _settle_shielded_hardware_task(log_task)
            caller_cancelled = caller_cancelled or cancelled
            if error is not None:
                logger.error("Failed to write safety fault to operator_log: %s", error)

        # 5. Broadcast Keithley channel states — best-effort, non-critical.
        #    Publish failure does NOT prevent fault latching or post-mortem
        #    logging because those already completed above.
        fault_channel = channel if channel in {"smua", "smub"} else None
        publish_task = asyncio.create_task(self._publish_keithley_channel_states(reason, fault_channel=fault_channel))
        _result, error, cancelled = await _settle_shielded_hardware_task(publish_task)
        caller_cancelled = caller_cancelled or cancelled
        if error is not None:
            logger.warning("Failed to publish Keithley channel states: %s", error)
        if caller_cancelled is not None:
            raise caller_cancelled

    async def _run_global_output_off(self) -> Any:
        """Execute one complete driver-compatible global-OFF operation."""
        try:
            return await self._keithley.emergency_off(None)
        except TypeError:
            # Keep the legacy fallback inside the retained owner so
            # concurrent waiters cannot fan out into duplicate operations.
            return await self._keithley.emergency_off()

    def _global_output_off_owner(self) -> asyncio.Task[Any]:
        """Return the retained owner for this exact source/abort generation."""
        task = self._global_off_owner_task
        if (
            task is not None
            and not task.done()
            and self._global_off_owner_driver is self._keithley
            and self._global_off_owner_generation is self._reviewed_source_generation
            and self._global_off_owner_abort_generation == self._abort_generation
        ):
            return task

        task = asyncio.create_task(
            self._run_global_output_off(),
            name="safety_manager_global_off_owner",
        )
        self._global_off_owner_task = task
        self._global_off_owner_driver = self._keithley
        self._global_off_owner_generation = self._reviewed_source_generation
        self._global_off_owner_abort_generation = self._abort_generation
        return task

    def _release_global_output_off_owner(self, task: asyncio.Task[Any]) -> None:
        """Release only the exact retained owner after it is terminal."""
        if self._global_off_owner_task is task and task.done():
            self._global_off_owner_task = None
            self._global_off_owner_driver = None
            self._global_off_owner_generation = None
            self._global_off_owner_abort_generation = -1

    async def _ensure_output_off(self, channel: str | None = None) -> bool:
        """Force Keithley output OFF. True iff the driver CONFIRMED it.

        CR-2: propagates the driver's confirmation bool so callers can fail
        closed. False means the SMU may still be sourcing. True when there is
        no Keithley to shut down.
        """
        if self._keithley is None:
            return True
        caller_cancelled: asyncio.CancelledError | None = None
        off_task = (
            self._global_output_off_owner()
            if channel is None
            else asyncio.create_task(self._keithley.emergency_off(channel))
        )
        confirmed, error, cancelled = await _settle_shielded_hardware_task(off_task)
        caller_cancelled = cancelled
        if channel is None:
            self._release_global_output_off_owner(off_task)
        if error is not None:
            logger.critical("_ensure_output_off failed: %s", error)
            confirmed = False
        exact_confirmed = error is None and confirmed is True
        retained_generation = self._has_current_reviewed_connection_generation()
        self._reviewed_source_connected = retained_generation
        if channel is None and retained_generation:
            self._reviewed_source_verified_off = exact_confirmed
        elif not exact_confirmed or not retained_generation:
            self._reviewed_source_verified_off = False
        self._refresh_operator_safety_snapshot()
        if caller_cancelled is not None:
            raise caller_cancelled
        return exact_confirmed

    async def _safe_off(
        self,
        reason: str,
        *,
        channels: set[SmuChannel],
        expected_abort_generation: int | None = None,
    ) -> tuple[frozenset[SmuChannel], bool]:
        applied_off: set[SmuChannel] = set()
        if self._state == SafetyState.FAULT_LATCHED:
            # Jules review: shield emergency_off in fault-latched cleanup path
            # so cancellation cannot interrupt the defensive hardware shutdown.
            off_task = asyncio.create_task(self._ensure_output_off())
            _result, error, caller_cancelled = await _settle_shielded_hardware_task(off_task)
            if error is not None:
                logger.error("_ensure_output_off in _safe_off failed: %s", error)
            logger.warning("_safe_off rejected while fault latched")
            if caller_cancelled is not None:
                raise caller_cancelled
            return frozenset(), True

        interrupted = False
        caller_cancelled: asyncio.CancelledError | None = None
        if self._keithley is not None:
            for smu_channel in sorted(channels):
                stop_task = asyncio.create_task(self._keithley.stop_source(smu_channel))
                result, error, cancelled = await _settle_shielded_hardware_task(stop_task)
                caller_cancelled = caller_cancelled or cancelled
                if error is not None or result is False:
                    exc = error if error is not None else RuntimeError("driver returned explicit False")
                    # FAIL CLOSED. A stop that throws may have left the channel
                    # still active in the driver (``runtime.active`` is only
                    # cleared AFTER OUTPUT_OFF + verify succeed), so the host-side
                    # P=const regulation can keep driving voltage. We must NOT
                    # clear _active_sources and report SAFE_OFF as if the source
                    # were off. Latch a fault — _fault() clears _active_sources
                    # and fires the shielded emergency_off (re-attempting
                    # OUTPUT_OFF + verify). _fault is lock-free and idempotent,
                    # so calling it here under _cmd_lock is safe.
                    logger.critical(
                        "stop_source(%s) failed: %s — latching fault (fail-closed)",
                        smu_channel,
                        exc,
                    )
                    await self._fault(
                        f"stop_source({smu_channel}) failed: {exc}",
                        channel=str(smu_channel),
                    )
                    if caller_cancelled is not None:
                        raise caller_cancelled
                    return frozenset(applied_off), True
                applied_off.add(smu_channel)
                self._active_sources.discard(smu_channel)
                self._refresh_operator_safety_snapshot()
                self._observe_terminal_safety_children()
                if self._state == SafetyState.FAULT_LATCHED:
                    interrupted = True
                elif expected_abort_generation is not None and (
                    self._abort_generation != expected_abort_generation or not self._safety_children_authoritative()
                ):
                    interrupted = True
        else:
            applied_off.update(channels)
            self._active_sources.difference_update(channels)

        if interrupted:
            self._refresh_operator_safety_snapshot()
            if caller_cancelled is not None:
                raise caller_cancelled
            return frozenset(applied_off), True

        if self._active_sources:
            self._transition(
                SafetyState.RUNNING,
                f"Partial stop: {sorted(channels)}, still active: {sorted(self._active_sources)}",
            )
            return frozenset(applied_off), False

        retained_generation = self._has_current_reviewed_connection_generation()
        self._reviewed_source_connected = retained_generation
        self._reviewed_source_verified_off = retained_generation
        self._transition(SafetyState.SAFE_OFF, reason)
        if caller_cancelled is not None:
            raise caller_cancelled
        return frozenset(applied_off), False

    def _resolve_channels(self, channel: str | None) -> set[SmuChannel]:
        if channel is not None:
            return {normalize_smu_channel(channel)}
        # Omitted channel is an explicit global emergency-OFF scope.  It must
        # never collapse to the currently active subset or normalize to smua;
        # both physical outputs require independent OFF verification.
        return set(SMU_CHANNELS)

    def _check_preconditions(self) -> tuple[bool, str]:
        now = time.monotonic()

        if not self._safety_children_authoritative():
            return False, "Safety monitor/collector authority is unavailable"

        if self._keithley is not None and getattr(self._keithley, "watchdog_trip_pending", False) is True:
            return False, (
                "Keithley watchdog has unconsumed prior-trip evidence — "
                "verified OFF and explicit fault acknowledgment required before RUN"
            )

        for pattern in self._config.critical_channels:
            matched = False
            for ch, (ts, value, status) in self._latest.items():
                if not pattern.match(ch):
                    continue
                matched = True
                age = now - ts
                if age > self._config.stale_timeout_s:
                    return False, f"Stale data: {ch} ({age:.1f}s)"
                if status != "ok":
                    return False, f"Channel {ch} status={status}"
                if math.isnan(value) or math.isinf(value):
                    return False, f"Channel {ch} invalid value {value}"
            if not matched and not self._mock:
                return False, f"No data for critical channel: {pattern.pattern}"

        if self._config.require_keithley_for_run and not self._mock:
            if self._keithley is None:
                return False, "Keithley not connected"
            if not getattr(self._keithley, "connected", False):
                return False, "Keithley connected=False"

        if not self._mock and not self._reviewed_source_identity_qualified:
            return False, "Reviewed source lacks exact sealed runtime binding authority"

        # The driver's absence of an ``output_state_unverified`` flag is not
        # affirmative OFF evidence.  RUN authority comes only from the
        # reviewed-source owner after an exact, current-generation OFF
        # confirmation. Explicit mock mode retains its established simulator
        # authority, including focused tests that exercise commands without
        # starting the background monitor. Keep the real-hardware gate
        # independent of the FSM name: READY may outlive invalidated
        # connection/OFF evidence.
        if not self._mock and (self._reviewed_source_generation is None or not self._reviewed_source_connected):
            return False, "Reviewed source connection generation is UNAVAILABLE"

        if not self._mock and not self._active_sources and self._reviewed_source_verified_off is not True:
            return False, ("Reviewed source OFF state is UNVERIFIED - confirm exact OFF before RUN")

        # F2: a connected Keithley whose crash-recovery force-OFF could not be
        # readback-verified may still be sourcing. Block RUN (only RUN — this is
        # a precondition, so measurement/diagnostics/manual retry stay available)
        # until a later verified OFF clears the flag. Fail-closed, no lockout.
        if (
            self._keithley is not None
            and not self._active_sources
            and getattr(self._keithley, "output_state_unverified", False)
        ):
            return False, (
                "Keithley output state UNVERIFIED after connect (crash-recovery "
                "force-OFF unconfirmed) — issue emergency off before RUN"
            )

        if self._state == SafetyState.FAULT_LATCHED:
            return False, f"Active fault: {self._fault_reason}"

        return True, ""

    async def _collect_loop(self) -> None:
        assert self._queue is not None
        try:
            while True:
                reading = await self._queue.get()
                now = time.monotonic()
                self._latest[reading.channel] = (now, reading.value, reading.status.value)
                self._refresh_operator_safety_snapshot()
                if reading.unit == "K" and reading.is_usable():
                    # S3: gate the rate estimator on the doctrine predicate. A
                    # NaN/±inf or error-status reading poisons the OLS buffer —
                    # _ols_slope_per_min() returns None until the bad point ages
                    # out of the 120 s window, silently blinding the 5 K/min
                    # protection. Non-usable readings are already caught by the
                    # status/NaN checks in _run_checks; they must not enter dT/dt.
                    # F23: use measurement timestamp, not queue dequeue time.
                    # Under backlog, monotonic() clusters; reading.timestamp reflects
                    # actual instrument measurement time, giving correct dT/dt.
                    self._rate_estimator.push(reading.channel, reading.timestamp.timestamp(), reading.value)
        except asyncio.CancelledError:
            raise

    async def _monitor_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(_CHECK_INTERVAL_S)
                await self._run_checks()
        except asyncio.CancelledError:
            raise

    async def _run_checks(self) -> None:
        now = time.monotonic()
        self._refresh_operator_safety_snapshot()

        # A pre-upload trip latch found during connect is preserved by the
        # driver without re-uploading the script. Surface that evidence even
        # while SAFE_OFF/READY so RUN cannot bypass operator acknowledgment.
        if (
            self._keithley is not None
            and not self._mock
            and getattr(self._keithley, "watchdog_trip_pending", False) is True
            and self._state != SafetyState.FAULT_LATCHED
        ):
            await self._fault(
                "Keithley watchdog has unconsumed prior-trip evidence; "
                "outputs require verified OFF and explicit acknowledgment"
            )
            return

        if self._state == SafetyState.MANUAL_RECOVERY:
            ok, _ = self._check_preconditions()
            if ok:
                self._transition(SafetyState.READY, "Recovery preconditions restored")
            return

        if self._state == SafetyState.SAFE_OFF:
            ok, _ = self._check_preconditions()
            if ok and self._latest:
                self._transition(SafetyState.READY, "All preconditions satisfied")
            return

        # Active monitoring states: RUN_PERMITTED (source starting) and
        # RUNNING (source on). Both need stale/rate/heartbeat checks because
        # a stuck start_source() call must not silently disable monitoring.
        if self._state not in (SafetyState.RUN_PERMITTED, SafetyState.RUNNING):
            return

        for pattern in self._config.critical_channels:
            for ch, (ts, _value, _status) in self._latest.items():
                if pattern.match(ch) and now - ts > self._config.stale_timeout_s:
                    await self._fault(f"Устаревшие данные канала {ch}", channel=ch)
                    return

        for ch, (_ts, value, status) in self._latest.items():
            if any(pattern.match(ch) for pattern in self._config.critical_channels):
                if status != "ok":
                    await self._fault(f"Channel {ch} status={status}", channel=ch, value=value)
                    return
                if math.isnan(value) or math.isinf(value):
                    await self._fault(f"Channel {ch}: NaN/Inf", channel=ch, value=value)
                    return

        if self._keithley is not None and not self._mock:
            # Watchdog reconcile: if the TSP late-pet check latched after its
            # OFF commands, latch FAULT. This is not independent proof of
            # terminal de-energization or any action during complete host death.
            # Silently re-arming
            # over a tripped watchdog is worse than having no watchdog. Inert
            # unless the driver's watchdog is enabled+armed (wdog_tripped()
            # returns False, no bus I/O, under the default-OFF flag). getattr +
            # isawaitable keep it safe against drivers/test doubles lacking the
            # method (returns a non-awaitable → skipped, no false fault).
            wdog_check = getattr(self._keithley, "wdog_tripped", None)
            if callable(wdog_check):
                try:
                    result = wdog_check()
                    tripped = await result if inspect.isawaitable(result) else False
                except Exception as exc:
                    await self._fault(f"Keithley watchdog state readback invalid/unavailable: {exc}")
                    return
                if tripped:
                    await self._fault(
                        "Keithley late-pet watchdog tripped — TSP issued "
                        "both-output OFF when host polling resumed after the deadline"
                    )
                    return

            if self._active_sources:
                for smu_channel in sorted(self._active_sources):
                    if not self._has_fresh_keithley_data(now, smu_channel):
                        await self._fault(
                            f"Keithley heartbeat timeout {smu_channel}: no data {self._config.heartbeat_timeout_s}s",  # noqa: E501
                            channel=smu_channel,
                        )
                        return
            elif (
                self._state == SafetyState.RUN_PERMITTED
                and self._run_permitted_since > 0
                and now - self._run_permitted_since > self._config.heartbeat_timeout_s
            ):
                # Stuck start_source(): sitting in RUN_PERMITTED longer than
                # heartbeat timeout without _active_sources being populated.
                await self._fault(
                    f"start_source() stuck: RUN_PERMITTED for "
                    f">{self._config.heartbeat_timeout_s:.0f}s without source activation",
                )
                return

        for ch in self._rate_estimator.channels():
            if not any(pattern.match(ch) for pattern in self._config.critical_channels):
                continue
            rate = self._rate_estimator.get_rate(ch)
            if rate is None:
                continue
            abs_rate = abs(rate)
            if abs_rate > self._config.max_dT_dt_K_per_min:
                await self._fault(
                    f"Rate limit exceeded {ch}: {abs_rate:.2f} K/min > {self._config.max_dT_dt_K_per_min}",  # noqa: E501
                    channel=ch,
                    value=abs_rate,
                )
                return

    def _has_fresh_keithley_data(self, now: float, smu_channel: SmuChannel) -> bool:
        aliases = {smu_channel, smu_channel.replace("smu", "smu_")}
        for channel, (ts, _value, status) in self._latest.items():
            if status != "ok":
                continue
            if not any(pattern.match(channel) for pattern in self._keithley_patterns):
                continue
            if any(f"/{alias}/" in channel for alias in aliases) and now - ts < self._config.heartbeat_timeout_s:
                return True
        return False

    async def on_interlock_trip(
        self,
        interlock_name: str,
        channel: str,
        value: float,
        *,
        action: str = "emergency_off",
    ) -> None:
        """Own the complete interlock action through truthful publication."""
        if action == "stop_source":
            # This synchronous cut reaches an in-flight request_run before the
            # owned interlock task can acquire _cmd_lock.
            self._register_abort_intent(full=True)
        operation = asyncio.create_task(
            self._on_interlock_trip_owned(
                interlock_name,
                channel,
                value,
                action=action,
            ),
            name=f"safety_interlock_{interlock_name}",
        )
        _result, error, caller_cancelled = await _settle_shielded_hardware_task(operation)
        if error is not None:
            raise error
        if caller_cancelled is not None:
            raise caller_cancelled

    async def _on_interlock_trip_owned(
        self,
        interlock_name: str,
        channel: str,
        value: float,
        *,
        action: str = "emergency_off",
    ) -> None:
        """Handle an interlock trip from InterlockEngine.

        ``action="emergency_off"`` (default, backwards-compatible):
            Full fault latch — outputs off, FAULT_LATCHED, operator must
            acknowledge_fault to recover.

        ``action="stop_source"``:
            Soft stop — outputs off, transition to SAFE_OFF, no fault latch.
            Operator can call ``request_run`` again as soon as the underlying
            condition (e.g. detector_warmup) clears.

        Any other action escalates to a full fault as the safe default.

        See DEEP_AUDIT_CODEX.md I.1.
        """
        reason = f"Interlock '{interlock_name}' tripped: channel={channel}, value={value:.4g}"

        if action == "emergency_off":
            logger.critical("INTERLOCK emergency_off: %s", reason)
            await self._fault(reason, channel=channel, value=value)
            return

        if action == "stop_source":
            logger.warning("INTERLOCK stop_source: %s", reason)
            # Soft stop: outputs off, no fault latch.
            # F4 liveness: advance the abort generation BEFORE contending for
            # _cmd_lock so an in-flight request_run (holding the lock through
            # slow start_source I/O) aborts its start instead of committing a
            # source we are about to shut down. Monotonic ownership means
            # caller timeout/cancellation cannot withdraw this intent.
            self._register_abort_intent(full=True)
            caller_cancelled: asyncio.CancelledError | None = None
            async with self._cmd_lock:
                if self._keithley is not None:
                    try:
                        off_task = asyncio.create_task(
                            self._keithley.emergency_off(),
                            name=f"interlock_full_off_{interlock_name}",
                        )
                        ok, off_error, off_cancelled = await _settle_shielded_hardware_task(off_task)
                        caller_cancelled = caller_cancelled or off_cancelled
                        if off_error is not None:
                            raise RuntimeError("interlock full OFF ended without a usable result") from off_error
                    except Exception as exc:
                        logger.error(
                            "stop_source interlock: emergency_off failed: %s — escalating to full fault",
                            exc,
                        )
                        await self._fault(
                            f"{reason} (emergency_off failed: {exc})",
                            channel=channel,
                            value=value,
                        )
                        if caller_cancelled is not None:
                            raise caller_cancelled
                        return
                    # A final-element OFF proof is deliberately nominal, not
                    # truthy: driver bugs and un-awaited/mock-shaped values
                    # must fault closed instead of becoming safety evidence.
                    if ok is not True:
                        await self._fault(
                            f"{reason} (emergency_off could not confirm OFF)",
                            channel=channel,
                            value=value,
                        )
                        if caller_cancelled is not None:
                            raise caller_cancelled
                        return
                self._active_sources.clear()
                retained_generation = self._has_current_reviewed_connection_generation()
                self._reviewed_source_connected = retained_generation
                self._reviewed_source_verified_off = retained_generation
                self._refresh_operator_safety_snapshot()
                if self._state not in (
                    SafetyState.FAULT_LATCHED,
                    SafetyState.MANUAL_RECOVERY,
                ):
                    self._transition(
                        SafetyState.SAFE_OFF,
                        f"Interlock stop_source: {interlock_name}",
                        channel=channel,
                        value=value,
                    )
                publish_task = asyncio.create_task(
                    self._publish_keithley_channel_states(f"interlock_stop:{interlock_name}")
                )
                _result, publish_error, publish_cancelled = await _settle_shielded_hardware_task(publish_task)
                caller_cancelled = caller_cancelled or publish_cancelled
                if publish_error is not None:
                    logger.warning(
                        "stop_source interlock state publish failed: %s",
                        publish_error,
                    )
            if caller_cancelled is not None:
                raise caller_cancelled
            return

        # Unknown action — fail-safe to a full fault rather than ignore.
        logger.critical(
            "Unknown interlock action %r for '%s' — escalating to full fault",
            action,
            interlock_name,
        )
        await self._fault(
            f"Unknown interlock action {action!r}: {reason}",
            channel=channel,
            value=value,
        )

    async def on_interlock_dead_channel(
        self,
        interlock_name: str,
        channel: str,
        *,
        value: float = float("nan"),
    ) -> bool:
        """Escalation for a PERSISTENTLY non-usable interlock channel (P2-5).

        Called by InterlockEngine once a channel it protects has been
        non-usable (NaN / error-status) for ``nonusable_escalation`` long
        enough. SafetyManager is the sole authority for the RUNNING gate:

        - state == RUNNING (actively sourcing): latch FAULT_LATCHED +
          emergency_off. Т1–Т10 are protected ONLY by interlocks
          (critical_channels covers just Т11/Т12), so a heated, sourcing zone
          with a persistently dead sensor is fail-open without this.
        - outside RUNNING: log only, never fault — a stale/dead sensor while
          idle must not block readiness recovery paths (preconditions already
          gate readiness on channel health).

        Returns
        -------
        bool
            ``True`` iff a fault is now latched (this call latched it, or the
            state was already FAULT_LATCHED). ``False`` iff escalation was
            declined because the state is not RUNNING. S1 fail-closed contract:
            InterlockEngine marks the debounce window ``escalated`` ONLY on
            ``True``. A ``False`` leaves the window un-escalated so the next
            non-usable sample retries — the first sample after RUNNING begins
            then faults, instead of the dead channel leaking through forever.
        """
        if self._state == SafetyState.FAULT_LATCHED:
            # Already latched (possibly by this very escalation on a prior
            # sample) — the window is correctly escalated, do not retry.
            return True
        if self._state != SafetyState.RUNNING:
            logger.critical(
                "Интерлок-канал %s устойчиво непригоден, но состояние %s "
                "(источник неактивен) — fault не латчится (P2-5).",
                channel,
                self._state.value,
            )
            return False
        await self._fault(
            f"Интерлок-канал {channel} ('{interlock_name}'): показания устойчиво непригодны при активном источнике",
            channel=channel,
            value=value,
        )
        return True

    async def on_persistence_failure(self, reason: str) -> None:
        """Called by SQLiteWriter when persistent storage fails (disk full etc).

        Immediately triggers ``_fault`` with a persistence-failure reason.
        ``_fault`` is intentionally NOT wrapped in ``_cmd_lock`` so this can
        be called from any context (including the writer thread via
        :func:`asyncio.run_coroutine_threadsafe`). The fault path itself
        latches the state synchronously before any await, so concurrent
        ``request_run`` callers will see ``FAULT_LATCHED`` and abort.
        """
        logger.critical("PERSISTENCE FAILURE: %s — triggering safety fault", reason)
        self._persistence_fault_active = True
        self._refresh_operator_safety_snapshot()
        await self._fault(
            f"Persistence failure: {reason}",
            channel="",
            value=0.0,
        )
