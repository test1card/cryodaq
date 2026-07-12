"""Pure, production-unwired coordinator for durable periodic PNG reports.

Every external authority is injected.  This module deliberately has no engine
address, ZMQ implementation, archive implementation, Telegram construction, or
runtime call site; H3.6 supplies those adapters atomically with the cutover.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import os
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from cryodaq.agents.assistant.periodic_delivery import (
    PeriodicDelivery,
    PeriodicDeliveryContext,
    PeriodicDeliveryOutcome,
    PeriodicDeliveryReceipt,
    PeriodicDeliveryResult,
)
from cryodaq.agents.assistant.periodic_projection import (
    AlarmProjection,
    BoundedReadingProjection,
    ProjectionSnapshot,
)
from cryodaq.instance_lock import release_lock, try_acquire_lock
from cryodaq.periodic_config import (
    PeriodicPngConfig,
    PeriodicPngConfigLoad,
    load_periodic_png_config,
)
from cryodaq.periodic_state import (
    MAX_UNRESOLVED_DELIVERIES,
    PERIODIC_LEADER_LOCK,
    PERIODIC_RENDER_LOCK,
    PeriodicArtifact,
    PeriodicContractError,
    PeriodicSlot,
    PeriodicStateDocument,
    PeriodicStatus,
    allocate_pending,
    latest_completed_slot,
    load_periodic_state,
    mark_delivering,
    mark_delivery_unknown,
    mark_ready,
    mark_rendering,
    mark_retryable_failure,
    mark_succeeded,
    mark_terminal_failure,
    periodic_input_path,
    rotate_terminal_active,
    set_periodic_health,
    supersede_active,
    write_periodic_state,
)
from cryodaq.report_process import (
    PeriodicRenderResult,
    ReportProcessError,
    read_periodic_artifact_bytes,
    write_periodic_input_file,
)
from cryodaq.reporting.periodic_input import (
    PeriodicInputError,
    read_periodic_input_file,
)

_TOKEN = re.compile(r"[0-9a-f]{32}")
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_MAX_TRANSITIONS_PER_PASS = 12
_ALARM_SEAL_ATTEMPTS = 3
_CONFIG_POLL_S = 5.0
_ELECTION_BACKOFF = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
_MAX_RESTART_RETRY_S = 86_400.0
_HEALTH_HEARTBEAT_S = 30.0
_ALARM_REFRESH_S = 240.0
_KNOWN_RENDER_OUTCOMES = frozenset(
    {
        "deadline",
        "process_error",
        "protocol_failed",
        "periodic_protocol_failure",
        "render_failed",
    }
)


def _known_render_outcome(error_code: str) -> bool:
    return error_code in _KNOWN_RENDER_OUTCOMES or bool(re.fullmatch(r"exit_(?:unknown|-?[0-9]+)", error_code))


def _known_input_failure(exc: Exception) -> bool:
    return isinstance(exc, PeriodicInputError) or (
        isinstance(exc, ReportProcessError) and exc.error_code in {"unsafe_periodic_input", "unsafe_periodic_path"}
    )


async def _settle_cancelled_task(
    task: asyncio.Task[Any],
) -> tuple[Any | None, BaseException | None]:
    """Wait through repeated outer cancellation and capture the inner result."""

    current = asyncio.current_task()
    if current is not None:
        current.uncancel()
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            if current is not None:
                current.uncancel()
    try:
        return task.result(), None
    except BaseException as exc:
        return None, exc


async def _acquire_lock_cancellation_safe(
    run_blocking: RunBlocking,
    lock_name: str,
    *,
    lock_dir: Path,
) -> int | None:
    """Do not leak a kernel lock acquired after its waiter is cancelled."""

    task = asyncio.create_task(run_blocking(try_acquire_lock, lock_name, lock_dir=lock_dir))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancelled:
        value, settlement_error = await _settle_cancelled_task(task)
        if isinstance(value, int):
            try:
                release_lock(
                    value,
                    lock_name,
                    unlink=False,
                    lock_dir=lock_dir,
                )
            except BaseException as exc:
                if settlement_error is None:
                    settlement_error = exc
        if settlement_error is not None:
            raise cancelled from settlement_error
        raise cancelled


def _exact_nonnegative(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _finite_nonnegative(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be finite and nonnegative")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field} must be finite and nonnegative")
    return result


@dataclass(frozen=True, slots=True)
class LiveSourceCut:
    """One repeatable subscriber barrier and its engine-side evidence."""

    session_id: str
    generation: int
    sequence: int
    published_at: float
    reading_drop_count: int
    publish_failure_count: int
    alarm_state_revision: int
    alarm_state_token: str

    def __post_init__(self) -> None:
        if not isinstance(self.session_id, str) or _TOKEN.fullmatch(self.session_id) is None:
            raise ValueError("session_id is invalid")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("generation must be a positive integer")
        _exact_nonnegative(self.sequence, "sequence")
        _finite_nonnegative(self.published_at, "published_at")
        _exact_nonnegative(self.reading_drop_count, "reading_drop_count")
        _exact_nonnegative(self.publish_failure_count, "publish_failure_count")
        _exact_nonnegative(self.alarm_state_revision, "alarm_state_revision")
        if not isinstance(self.alarm_state_token, str) or _HASH.fullmatch(self.alarm_state_token) is None:
            raise ValueError("alarm_state_token is invalid")


@dataclass(frozen=True, slots=True)
class AlarmQueryResult:
    """Closed result of the injected bounded active-alarm authority."""

    ok: bool
    payload: Mapping[str, object] | None
    state_token: str | None
    state_revision: int | None
    error_code: str | None

    def __post_init__(self) -> None:
        if type(self.ok) is not bool:
            raise TypeError("ok must be a boolean")
        if self.ok:
            if not isinstance(self.payload, Mapping) or self.payload.get("ok") is not True:
                raise ValueError("successful alarm result requires a successful mapping")
            if not isinstance(self.state_token, str) or _HASH.fullmatch(self.state_token) is None:
                raise ValueError("successful alarm result requires a state token")
            _exact_nonnegative(self.state_revision, "state_revision")
            if self.error_code is not None:
                raise ValueError("successful alarm result cannot contain an error")
        elif (
            self.payload is not None
            or self.state_token is not None
            or self.state_revision is not None
            or not isinstance(self.error_code, str)
            or not self.error_code
        ):
            raise ValueError("failed alarm result fields are inconsistent")


class Clock(Protocol):
    def wall_time(self) -> float: ...

    def monotonic(self) -> float: ...

    def display_time(self, epoch: int) -> str: ...

    async def sleep(self, seconds: float) -> None: ...


class PeriodicSourceUnavailable(RuntimeError):
    """Initial live authority is absent, rather than the H3 runtime failing."""


class PeriodicLiveSources(Protocol):
    async def start(
        self,
        on_reading: Callable[[Any], object],
        on_event: Callable[[Mapping[str, object]], object],
    ) -> None: ...

    async def ready(self) -> LiveSourceCut: ...

    def complete_since(self, cut: LiveSourceCut) -> bool: ...

    async def wait(self) -> None: ...

    async def stop(self) -> None: ...


class PeriodicAlarmQuery(Protocol):
    async def snapshot(self) -> AlarmQueryResult: ...

    async def close(self) -> None: ...


class PeriodicArchiveQuery(Protocol):
    def __call__(self, **kwargs: object) -> object: ...


class PeriodicRunner(Protocol):
    def generate_periodic(
        self,
        generation_id: str,
        *,
        expected_slot_id: str,
        expected_owner_token: str,
        max_input_bytes: int,
    ) -> PeriodicRenderResult: ...

    def recover_periodic(
        self,
        generation_id: str,
        *,
        expected_slot_id: str,
        expected_owner_token: str,
    ) -> PeriodicRenderResult | None: ...


class RunBlocking(Protocol):
    async def __call__(self, function: Callable[..., Any], /, *args: object, **kwargs: object) -> Any: ...


class _SystemClock:
    def wall_time(self) -> float:
        import time

        return time.time()

    def monotonic(self) -> float:
        import time

        return time.monotonic()

    def display_time(self, epoch: int) -> str:
        return datetime.fromtimestamp(epoch).strftime("%d.%m.%Y %H:%M")

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


async def _to_thread(function: Callable[..., Any], /, *args: object, **kwargs: object) -> Any:
    return await asyncio.to_thread(function, *args, **kwargs)


def retry_delay(base_s: float, cap_s: float, attempt_count: int) -> float:
    """Return the exact deterministic retry delay for an already-used attempt."""

    base = _finite_nonnegative(base_s, "base_s")
    cap = _finite_nonnegative(cap_s, "cap_s")
    if base <= 0 or cap < base or type(attempt_count) is not int or attempt_count <= 0:
        raise ValueError("retry delay arguments are invalid")
    exponent = min(attempt_count - 1, 62)
    return min(cap, base * (2**exponent))


def _artifact_from_active(active: Mapping[str, object]) -> PeriodicArtifact:
    raw = active.get("artifact")
    if not isinstance(raw, Mapping):
        raise PeriodicContractError("active slot has no artifact")
    return PeriodicArtifact(
        path=str(raw["path"]),
        sha256=str(raw["sha256"]),
        size=int(raw["size"]),
        width=int(raw["width"]),
        height=int(raw["height"]),
        mime=raw["mime"],  # type: ignore[arg-type]
    )


def _active(state: PeriodicStateDocument) -> dict[str, Any] | None:
    value = state.payload["active"]
    return value if isinstance(value, dict) else None


class PeriodicPngCoordinator:
    """One leader's pure-DI projection, render, and delivery state machine."""

    def __init__(
        self,
        *,
        data_dir: Path,
        config: PeriodicPngConfig,
        live_sources: PeriodicLiveSources,
        alarm_query: PeriodicAlarmQuery,
        archive_query: PeriodicArchiveQuery,
        runner: PeriodicRunner,
        delivery: PeriodicDelivery,
        destination_fingerprint: str,
        expected_delivery_kind: str,
        artifact_reader: Callable[[Path, PeriodicArtifact], bytes] = read_periodic_artifact_bytes,
        clock: Clock | None = None,
        generation_factory: Callable[[], str] | None = None,
        owner_factory: Callable[[], str] | None = None,
        run_blocking: RunBlocking | None = None,
    ) -> None:
        if not isinstance(config, PeriodicPngConfig) or not config.enabled:
            raise ValueError("config must be a runnable PeriodicPngConfig")
        required = {
            "live_sources": live_sources,
            "alarm_query": alarm_query,
            "archive_query": archive_query,
            "runner": runner,
            "delivery": delivery,
            "artifact_reader": artifact_reader,
        }
        if any(value is None for value in required.values()):
            raise TypeError("all periodic authorities are required")
        self._data_dir = Path(data_dir)
        self._config = config
        self._live = live_sources
        self._alarm_query = alarm_query
        self._archive_query = archive_query
        self._runner = runner
        self._delivery = delivery
        if type(destination_fingerprint) is not str or _HASH.fullmatch(destination_fingerprint) is None:
            raise ValueError("destination_fingerprint is invalid")
        self._destination_fingerprint = destination_fingerprint
        if type(expected_delivery_kind) is not str or expected_delivery_kind not in {
            "telegram",
            "soak_local",
        }:
            raise ValueError("expected_delivery_kind is invalid")
        self._expected_delivery_kind = expected_delivery_kind
        self._artifact_reader = artifact_reader
        self._clock = clock or _SystemClock()
        self._generation_factory = generation_factory or (lambda: secrets.token_hex(16))
        self._owner_factory = owner_factory or (lambda: secrets.token_hex(16))
        self._run_blocking: RunBlocking = run_blocking or _to_thread

        self._started = False
        self._stopping = False
        self._closed = False
        self._stop_event: asyncio.Event | None = None
        self._wake: asyncio.Event | None = None
        self._reconcile_lock: asyncio.Lock | None = None
        self._delivery_settlement_lock: asyncio.Lock | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._loop_task: asyncio.Task[None] | None = None
        self._live_task: asyncio.Task[None] | None = None
        self._readings: BoundedReadingProjection | None = None
        self._alarms: AlarmProjection | None = None
        self._startup_cut: LiveSourceCut | None = None
        self._hydration_seal: LiveSourceCut | None = None
        self._last_seal: LiveSourceCut | None = None
        self._last_alarm_complete = False
        self._retry_deadlines: dict[tuple[str, str, float], float] = {}
        self._next_callback_wake = 0.0
        self._next_health_heartbeat = 0.0
        self._next_alarm_refresh = 0.0
        self._live_source_failed = False

    @property
    def config(self) -> PeriodicPngConfig:
        return self._config

    async def start(self) -> None:
        if self._started:
            raise RuntimeError("periodic PNG coordinator is already started")
        if self._closed:
            raise RuntimeError("periodic PNG coordinator is closed")
        self._started = True
        self._stop_event = asyncio.Event()
        self._wake = asyncio.Event()
        self._reconcile_lock = asyncio.Lock()
        self._delivery_settlement_lock = asyncio.Lock()
        self._readings = BoundedReadingProjection(self._config)
        self._alarms = AlarmProjection()
        try:
            await self._live.start(self._on_reading, self._on_event)
            self._startup_cut = await self._live.ready()
            await self._hydrate(self._startup_cut)
            self._hydration_seal = await self._live.ready()
            if not self._cuts_complete(self._startup_cut, self._hydration_seal):
                self._readings.mark_history_incomplete("live_hydration_seal_incomplete")
            await self._refresh_alarm_and_seal()
            startup_snapshot = self.projection_snapshot(
                window_start=(self._startup_cut.published_at - self._config.chart_window_s),
                window_end=self._startup_cut.published_at,
            )
            await self._set_projection_health(startup_snapshot)
            monotonic_now = self._clock.monotonic()
            self._next_health_heartbeat = monotonic_now + _HEALTH_HEARTBEAT_S
            self._next_alarm_refresh = monotonic_now + _ALARM_REFRESH_S
            self._loop_task = asyncio.create_task(self._run_loop(), name="periodic_png_coordinator")
            self._live_task = asyncio.create_task(self._watch_live(), name="periodic_png_live_source")
        except asyncio.CancelledError as exc:
            await self._settle_start_cleanup(exc)
        except Exception as exc:
            await self._settle_start_cleanup(exc)

    async def _settle_start_cleanup(self, primary: BaseException) -> None:
        cleanup_task = asyncio.create_task(self._close_external())
        cleanup_error: BaseException | None = None
        try:
            cleanup_error = await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            value, settlement_error = await _settle_cancelled_task(cleanup_task)
            if settlement_error is not None:
                cleanup_error = settlement_error
            elif isinstance(value, BaseException):
                cleanup_error = value
        except BaseException as exc:
            cleanup_error = exc
        self._closed = True
        if cleanup_error is not None:
            raise primary from cleanup_error
        raise primary

    def _on_reading(self, reading: Any) -> None:
        if self._readings is not None:
            self._readings.append_live(reading)
        now = self._clock.monotonic()
        if self._wake is not None and now >= self._next_callback_wake:
            self._next_callback_wake = now + 5.0
            self._wake.set()

    def _on_event(self, event: Mapping[str, object]) -> None:
        if self._alarms is not None:
            self._alarms.buffer_event(event)
        now = self._clock.monotonic()
        if self._wake is not None and now >= self._next_callback_wake:
            self._next_callback_wake = now + 5.0
            self._wake.set()

    async def _hydrate(self, cut: LiveSourceCut) -> None:
        assert self._readings is not None
        deadline = self._clock.monotonic() + min(self._config.render_timeout_s, 60.0)
        try:
            result = await self._run_blocking(
                self._archive_query,
                start=datetime.fromtimestamp(cut.published_at - self._config.chart_window_s, UTC),
                end=datetime.fromtimestamp(cut.published_at, UTC),
                channels=self._config.include_channels,
                max_channels=64,
                max_points_per_channel=self._config.max_points_per_channel,
                max_total_points=self._config.max_total_points,
                max_retained_bytes=max(32_768, self._config.max_input_bytes * 3 // 4),
                deadline_monotonic=deadline,
                batch_rows=2_048,
                max_arrow_batch_bytes=4 * 1024 * 1024,
            )
            self._readings.merge_hydration(result, cut=cut.published_at)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._readings.mark_history_incomplete("archive_hydration_failed")

    def _cuts_complete(self, *cuts: LiveSourceCut | None) -> bool:
        return all(cut is not None and self._live.complete_since(cut) for cut in cuts)

    async def _refresh_alarm_and_seal(self) -> LiveSourceCut:
        assert self._alarms is not None
        last_seal: LiveSourceCut | None = None
        for _attempt in range(_ALARM_SEAL_ATTEMPTS):
            receive_cut = self._alarms.capture_receive_cut()
            try:
                result = await self._alarm_query.snapshot()
            except asyncio.CancelledError:
                raise
            except Exception:
                result = AlarmQueryResult(False, None, None, None, "alarm_snapshot_unavailable")
            payload: Mapping[str, object]
            if result.ok and result.payload is not None:
                payload = result.payload
            else:
                payload = {"ok": False, "active": {}}
            self._alarms.install_snapshot(
                payload,
                captured_at=self._clock.wall_time(),
                receive_cut=receive_cut,
            )
            last_seal = await self._live.ready()
            tokens_match = (
                result.ok
                and result.state_revision is not None
                and result.state_revision <= last_seal.alarm_state_revision
                and result.state_token == last_seal.alarm_state_token
            )
            _items, projection_complete = self._alarms.freeze(now=self._clock.wall_time())
            cuts_complete = self._cuts_complete(self._startup_cut, self._hydration_seal, last_seal)
            self._last_alarm_complete = bool(tokens_match and projection_complete and cuts_complete)
            self._last_seal = last_seal
            if self._last_alarm_complete:
                return last_seal
            if not result.ok:
                break
            await self._clock.sleep(0.01)
        if last_seal is None:
            last_seal = await self._live.ready()
            self._last_seal = last_seal
        self._last_alarm_complete = False
        return last_seal

    def projection_snapshot(self, *, window_start: float, window_end: float) -> ProjectionSnapshot:
        """Expose an immutable diagnostic snapshot; it performs no I/O or sealing."""

        if self._readings is None or self._alarms is None:
            raise RuntimeError("periodic projections are not started")
        alarms, alarm_projection_complete = self._alarms.freeze(now=self._clock.wall_time())
        alarm_complete = self._last_alarm_complete and alarm_projection_complete
        return self._readings.snapshot(
            window_start=window_start,
            window_end=window_end,
            alarms=alarms,
            alarm_state_complete=alarm_complete,
        )

    async def _sealed_snapshot(self, *, window_start: float, window_end: float) -> ProjectionSnapshot:
        assert self._readings is not None and self._alarms is not None
        seal = await self._refresh_alarm_and_seal()
        cuts_complete = self._cuts_complete(self._startup_cut, self._hydration_seal, seal)
        if not cuts_complete:
            self._readings.mark_history_incomplete("live_source_incomplete")
        alarms, alarm_projection_complete = self._alarms.freeze(now=self._clock.wall_time())
        snapshot = self._readings.snapshot(
            window_start=window_start,
            window_end=window_end,
            alarms=alarms,
            alarm_state_complete=(self._last_alarm_complete and alarm_projection_complete and cuts_complete),
        )
        await self._set_projection_health(snapshot)
        monotonic_now = self._clock.monotonic()
        self._next_health_heartbeat = monotonic_now + _HEALTH_HEARTBEAT_S
        self._next_alarm_refresh = monotonic_now + _ALARM_REFRESH_S
        return snapshot

    async def _set_projection_health(self, snapshot: ProjectionSnapshot) -> None:
        cuts_complete = self._cuts_complete(self._startup_cut, self._hydration_seal, self._last_seal)
        if self._live_source_failed:
            await self._set_health(
                "degraded_source",
                "periodic_live_source_stopped",
                "periodic live source stopped unexpectedly",
            )
        elif not (snapshot.history_complete and snapshot.alarm_state_complete and cuts_complete):
            await self._set_health(
                "degraded_projection",
                "periodic_projection_incomplete",
                "periodic projection evidence is incomplete",
            )
        elif not self._config.telegram_verify_ssl:
            await self._set_health(
                "degraded_tls",
                "periodic_tls_verification_disabled",
                "periodic Telegram TLS verification is disabled",
            )
        else:
            await self._set_health("ready", None, "")

    async def wait(self) -> None:
        if not self._started:
            raise RuntimeError("periodic PNG coordinator was not started")
        tasks = {task for task in (self._loop_task, self._live_task) if task is not None}
        if not tasks:
            if self._stopping:
                return
            raise RuntimeError("periodic PNG coordinator has no critical tasks")
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            try:
                await task
            except asyncio.CancelledError:
                if not self._stopping:
                    raise RuntimeError("periodic PNG critical task was cancelled") from None
        if not self._stopping:
            raise RuntimeError("periodic PNG critical task stopped unexpectedly")

    async def _watch_live(self) -> None:
        try:
            await self._live.wait()
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self._stopping:
                await self._set_live_source_failed_health()
            raise
        if not self._stopping:
            await self._set_live_source_failed_health()
            raise RuntimeError("periodic live source stopped unexpectedly")

    async def _set_live_source_failed_health(self) -> None:
        self._live_source_failed = True
        if self._reconcile_lock is None:
            return
        async with self._reconcile_lock:
            await self._set_health(
                "degraded_source",
                "periodic_live_source_stopped",
                "periodic live source stopped unexpectedly",
            )

    async def _run_loop(self) -> None:
        assert self._stop_event is not None and self._wake is not None
        while not self._stop_event.is_set():
            self._wake.clear()
            await self.reconcile_once()
            if self._stop_event.is_set() or self._wake.is_set():
                continue
            await self._wait_interruptible(5.0)

    async def _wait_interruptible(self, seconds: float) -> None:
        assert self._stop_event is not None and self._wake is not None
        sleep_task = asyncio.create_task(self._clock.sleep(max(0.0, seconds)))
        wake_task = asyncio.create_task(self._wake.wait())
        stop_task = asyncio.create_task(self._stop_event.wait())
        tasks = {sleep_task, wake_task, stop_task}
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self) -> None:
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop_impl())
        try:
            await asyncio.shield(self._stop_task)
        except asyncio.CancelledError as cancelled:
            _value, cleanup_error = await _settle_cancelled_task(self._stop_task)
            if cleanup_error is not None:
                raise cancelled from cleanup_error
            raise

    async def _stop_impl(self) -> None:
        if self._closed:
            return
        self._stopping = True
        if self._stop_event is not None:
            self._stop_event.set()
        if self._wake is not None:
            self._wake.set()
        first_error: BaseException | None = None

        async def attempt(awaitable: Awaitable[Any], *, record: bool = True) -> None:
            nonlocal first_error
            try:
                await awaitable
            except BaseException as exc:
                if record and first_error is None:
                    first_error = exc

        # Reconciliation owns any shielded render/delivery transaction.  Let
        # it cross its durable boundary before dismantling the source/query
        # graph; otherwise shutdown itself could fabricate a projection fault.
        if self._loop_task is not None:
            await attempt(self._loop_task, record=False)
        await attempt(self._live.stop())
        if self._live_task is not None:
            await attempt(self._live_task, record=False)
        self._loop_task = None
        self._live_task = None
        await attempt(self._alarm_query.close())
        await attempt(self._delivery.close())
        try:
            if self._readings is not None:
                self._readings.clear()
            if self._alarms is not None:
                self._alarms.clear()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
        self._closed = True
        if first_error is not None:
            raise first_error

    async def _close_external(self) -> BaseException | None:
        first_error: BaseException | None = None
        for operation in (
            self._live.stop,
            self._alarm_query.close,
            self._delivery.close,
        ):
            try:
                await operation()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        return first_error

    async def reconcile_once(self) -> None:
        if not self._started or self._reconcile_lock is None:
            raise RuntimeError("periodic PNG coordinator is not started")
        async with self._reconcile_lock:
            for _transition in range(_MAX_TRANSITIONS_PER_PASS):
                if self._stopping:
                    return
                if not await self._reconcile_step():
                    return
            if self._wake is not None:
                self._wake.set()

    async def _load_state(self) -> PeriodicStateDocument:
        return await self._run_blocking(load_periodic_state, self._data_dir)

    async def _persist(self, before: PeriodicStateDocument, candidate: PeriodicStateDocument) -> None:
        current = _active(before)
        kwargs: dict[str, object] = {}
        if current is not None:
            kwargs = {
                "expected_slot_id": current["slot_id"],
                "expected_owner_token": current["owner_token"],
                "expected_status": PeriodicStatus(current["status"]),
            }
        await self._run_blocking(write_periodic_state, self._data_dir, candidate, **kwargs)

    def _logical_now(self, state: PeriodicStateDocument, *, floor: float | None = None) -> float:
        value = max(self._clock.wall_time(), float(state.payload["updated_at"]))
        if floor is not None:
            value = max(value, floor)
        return value

    async def _set_health(self, status: str, code: str | None, text: str) -> None:
        state = await self._load_state()
        if status in {"ready", "degraded_projection", "degraded_tls"}:
            if self._live_source_failed:
                status = "degraded_source"
                code = "periodic_live_source_stopped"
                text = "periodic live source stopped unexpectedly"
            elif not self._cuts_complete(self._startup_cut, self._hydration_seal, self._last_seal):
                status = "degraded_projection"
                code = "periodic_projection_incomplete"
                text = "periodic projection evidence is incomplete"
        existing_health = state.payload["health"]
        if status in {
            "ready",
            "degraded_projection",
            "degraded_tls",
        } and existing_health["status"] in {
            "paused_unknown_capacity",
            "delivery_paused_unknown_capacity",
        }:
            status = str(existing_health["status"])
            code = existing_health["error_code"]
            text = str(existing_health["error_text"])
        previous = float(state.payload["updated_at"])
        wall_now = self._clock.wall_time()
        health_now = wall_now if wall_now > previous else math.nextafter(previous, math.inf)
        candidate = set_periodic_health(
            state,
            status=status,
            code=code,
            text=text,
            now=health_now,
        )
        if candidate.payload != state.payload:
            await self._persist(state, candidate)

    async def _reconcile_step(self) -> bool:
        await self._refresh_periodic_authority_if_due()
        state = await self._load_state()
        active = _active(state)
        raw_wall = self._clock.wall_time()
        latest = latest_completed_slot(raw_wall, self._config.interval_s)
        now = self._logical_now(state)

        if active is None:
            high_water = state.payload["high_water_slot_end"]
            if high_water is not None and latest.slot_end <= int(high_water):
                return False
            preflight = self.projection_snapshot(
                window_start=latest.slot_end - self._config.chart_window_s,
                window_end=latest.slot_end,
            )
            if not any(row.value is not None for row in preflight.readings):
                return False
            snapshot = await self._sealed_snapshot(
                window_start=latest.slot_end - self._config.chart_window_s,
                window_end=latest.slot_end,
            )
            if self._stopping:
                return False
            if not any(row.value is not None for row in snapshot.readings):
                return False
            # The projection health heartbeat is a fenced durable write.  Do
            # not allocate from the state document captured before it.
            state = await self._load_state()
            if _active(state) is not None:
                return False
            refreshed_latest = latest_completed_slot(self._clock.wall_time(), self._config.interval_s)
            if refreshed_latest != latest:
                return True
            high_water = state.payload["high_water_slot_end"]
            if high_water is not None and latest.slot_end <= int(high_water):
                return False
            now = self._logical_now(state)
            pending = allocate_pending(
                state,
                latest,
                self._config,
                generation_id=self._generation_factory(),
                owner_token=self._owner_factory(),
                display_time=self._clock.display_time(latest.slot_end),
                now=now,
                destination_fingerprint=self._destination_fingerprint,
            )
            await self._persist(state, pending)
            return True

        status = PeriodicStatus(active["status"])
        terminal_failed = status is PeriodicStatus.FAILED and active["retryable"] is False
        if status in {PeriodicStatus.SUCCEEDED, PeriodicStatus.DELIVERY_UNKNOWN} or terminal_failed:
            rotated = rotate_terminal_active(state, now=now)
            await self._persist(state, rotated)
            return True

        if status is PeriodicStatus.DELIVERING:
            unknown = mark_delivery_unknown(
                state,
                code="coordinator_recovered_delivering",
                text="delivery outcome was unresolved when the coordinator recovered",
                slot_id=active["slot_id"],
                owner_token=active["owner_token"],
                now=now,
            )
            await self._persist(state, unknown)
            # Preserve the ambiguity-bearing active state for at least one
            # complete reconciliation boundary.  A later pass may rotate it,
            # but this recovery pass performs no further slot work.
            return False

        if (
            active["config_fingerprint"] != self._config.config_fingerprint
            or active["destination_fingerprint"] != self._destination_fingerprint
        ):
            failure_phase = "config"
            certainty = "not_applicable"
            if status is PeriodicStatus.FAILED:
                # The H3.1 transition graph deliberately forbids rewriting a
                # retryable FAILED phase.  Preserve that durable evidence while
                # terminalizing it with the fixed config-change cause.
                failure_phase = str(active["failure_phase"])
                certainty = str(active["certainty"])
            failed = mark_terminal_failure(
                state,
                phase=failure_phase,
                certainty=certainty,
                code="periodic_config_changed",
                text="periodic configuration changed before completion",
                slot_id=active["slot_id"],
                owner_token=active["owner_token"],
                now=now,
            )
            await self._persist(state, failed)
            return True

        if latest.slot_end > int(active["slot_end"]):
            superseded = supersede_active(state, newer_slot_end=latest.slot_end, now=now)
            await self._persist(state, superseded)
            return True

        if status is PeriodicStatus.RENDERING:
            return await self._recover_rendering(state, active)

        if status is PeriodicStatus.FAILED:
            if active["retryable"] is not True or not self._retry_due(active):
                return False
            due_now = self._logical_now(state, floor=float(active["not_before"]))
            if active["failure_phase"] == "render":
                slot = PeriodicSlot(
                    active["slot_id"],
                    int(active["slot_start"]),
                    int(active["slot_end"]),
                    int(active["interval_s"]),
                )
                pending = allocate_pending(
                    state,
                    slot,
                    self._config,
                    generation_id=self._generation_factory(),
                    owner_token=self._owner_factory(),
                    display_time=active["display_time"],
                    now=due_now,
                    destination_fingerprint=self._destination_fingerprint,
                )
                await self._persist(state, pending)
                return True
            if active["failure_phase"] == "delivery":
                return await self._deliver(state, active, due_now)
            return False

        if status is PeriodicStatus.PENDING:
            return await self._render_pending(state, active)

        if status is PeriodicStatus.READY:
            if (
                len(state.payload["unresolved_delivery"]) >= MAX_UNRESOLVED_DELIVERIES
                and state.payload["health"]["status"] == "paused_unknown_capacity"
            ):
                return False
            return await self._deliver(state, active, now)

        return False

    async def _refresh_periodic_authority_if_due(self) -> None:
        monotonic_now = self._clock.monotonic()
        alarm_due = monotonic_now >= self._next_alarm_refresh
        health_due = monotonic_now >= self._next_health_heartbeat
        if not (alarm_due or health_due):
            return
        if alarm_due:
            await self._refresh_alarm_and_seal()
            self._next_alarm_refresh = monotonic_now + _ALARM_REFRESH_S
        wall_now = self._clock.wall_time()
        snapshot = self.projection_snapshot(
            window_start=wall_now - self._config.chart_window_s,
            window_end=wall_now,
        )
        await self._set_projection_health(snapshot)
        self._next_health_heartbeat = monotonic_now + _HEALTH_HEARTBEAT_S

    def _retry_due(self, active: Mapping[str, object]) -> bool:
        key = (
            str(active["slot_id"]),
            str(active["status"]),
            float(active["not_before"]),
        )
        deadline = self._retry_deadlines.get(key)
        if deadline is None:
            self._retry_deadlines.clear()
            remaining = max(
                0.0,
                min(
                    _MAX_RESTART_RETRY_S,
                    float(active["not_before"]) - self._clock.wall_time(),
                ),
            )
            deadline = self._clock.monotonic() + remaining
            self._retry_deadlines[key] = deadline
        return self._clock.monotonic() >= deadline

    async def _recover_rendering(self, state: PeriodicStateDocument, active: dict[str, Any]) -> bool:
        try:
            result = await self._run_blocking(
                self._runner.recover_periodic,
                active["generation_id"],
                expected_slot_id=active["slot_id"],
                expected_owner_token=active["owner_token"],
            )
        except Exception:
            # Recovery reads only immutable final/state authority.  It has no
            # child-attempt outcome to classify; any failure is supervisory.
            raise
        if result is not None:
            await self._adopt_render_result(state, active, result)
            return True
        fd = await _acquire_lock_cancellation_safe(self._run_blocking, PERIODIC_RENDER_LOCK, lock_dir=self._data_dir)
        if fd is None:
            return False
        release_lock(
            fd,
            PERIODIC_RENDER_LOCK,
            unlink=False,
            lock_dir=self._data_dir,
        )
        await self._record_render_failure(
            state,
            active,
            code="orphaned_rendering",
            text="rendering owner disappeared without an immutable final",
        )
        return True

    async def _render_pending(self, state: PeriodicStateDocument, active: dict[str, Any]) -> bool:
        try:
            await self._ensure_input(active)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not _known_input_failure(exc):
                # Live sealing and state/fence failures are supervisory.
                raise
            current = await self._load_state()
            current_active = _active(current)
            if self._same_active(active, current_active, expected_status=PeriodicStatus.PENDING):
                await self._record_render_failure(
                    current,
                    current_active,
                    code="periodic_input_unavailable",
                    text="periodic input could not be authorized",
                )
                return True
            return False

        if self._stopping:
            return False

        fresh = await self._load_state()
        if self._stopping:
            return False
        fresh_active = _active(fresh)
        if not self._same_active(active, fresh_active, expected_status=PeriodicStatus.PENDING):
            return False
        rendering = mark_rendering(
            fresh,
            slot_id=active["slot_id"],
            owner_token=active["owner_token"],
            now=self._logical_now(fresh),
        )
        await self._persist(fresh, rendering)
        rendering_active = _active(rendering)
        assert rendering_active is not None

        try:
            operation = self._run_blocking(
                self._runner.generate_periodic,
                rendering_active["generation_id"],
                expected_slot_id=rendering_active["slot_id"],
                expected_owner_token=rendering_active["owner_token"],
                max_input_bytes=self._config.max_input_bytes,
            )
            result = await self._await_shielded(operation, heartbeat=True)
        except ReportProcessError as exc:
            if exc.error_code == "busy":
                return False
            if not _known_render_outcome(exc.error_code):
                raise
            return await self._settle_generate_failure(rendering_active, code=exc.error_code)
        except asyncio.CancelledError:
            raise
        except Exception:
            return await self._settle_generate_failure(rendering_active, code="render_failed")

        current = await self._load_state()
        current_active = _active(current)
        if not self._same_active(rendering_active, current_active, expected_status=PeriodicStatus.RENDERING):
            return False
        await self._adopt_render_result(current, current_active, result)
        return True

    async def _settle_generate_failure(self, rendering_active: dict[str, Any], *, code: str) -> bool:
        # Even an ordinary process-launch/runtime failure may have raced a
        # successfully promoted immutable final.  Recovery is authoritative.
        recovered = await self._run_blocking(
            self._runner.recover_periodic,
            rendering_active["generation_id"],
            expected_slot_id=rendering_active["slot_id"],
            expected_owner_token=rendering_active["owner_token"],
        )
        current = await self._load_state()
        current_active = _active(current)
        if not self._same_active(rendering_active, current_active, expected_status=PeriodicStatus.RENDERING):
            return False
        if recovered is not None:
            await self._adopt_render_result(current, current_active, recovered)
            return True
        await self._record_render_failure(
            current,
            current_active,
            code=(code if re.fullmatch(r"[a-z0-9_]{1,128}", code) else "render_failed"),
            text="periodic render failed",
        )
        return True

    async def _ensure_input(self, active: dict[str, Any]) -> None:
        path = await self._run_blocking(periodic_input_path, self._data_dir, active["generation_id"])
        exists = await self._run_blocking(os.path.lexists, path)
        if exists:
            frozen = await self._run_blocking(
                read_periodic_input_file,
                path,
                expected_max_input_bytes=self._config.max_input_bytes,
            )
            if not (
                frozen.generation_id == active["generation_id"]
                and frozen.owner_token == active["owner_token"]
                and frozen.slot.slot_id == active["slot_id"]
                and frozen.slot.slot_start == active["slot_start"]
                and frozen.slot.slot_end == active["slot_end"]
                and frozen.slot.window_start == active["window_start"]
                and frozen.slot.window_end == active["window_end"]
                and frozen.slot.config_fingerprint == active["config_fingerprint"]
                and frozen.render.display_time == active["display_time"]
                and frozen.render.include_channels == self._config.include_channels
                and frozen.render.max_points_per_channel == self._config.max_points_per_channel
                and frozen.render.max_total_points == self._config.max_total_points
                and frozen.render.max_input_bytes == self._config.max_input_bytes
            ):
                raise PeriodicInputError("existing periodic input fence does not match")
            return
        snapshot = await self._sealed_snapshot(
            window_start=float(active["window_start"]),
            window_end=float(active["window_end"]),
        )
        payload = self._input_payload(active, snapshot)
        await self._run_blocking(
            write_periodic_input_file,
            self._data_dir,
            payload,
            expected_max_input_bytes=self._config.max_input_bytes,
        )

    def _input_payload(self, active: Mapping[str, object], snapshot: ProjectionSnapshot) -> dict[str, object]:
        return {
            "schema": 1,
            "generation_id": active["generation_id"],
            "owner_token": active["owner_token"],
            "slot": {
                "slot_id": active["slot_id"],
                "slot_start": active["slot_start"],
                "slot_end": active["slot_end"],
                "window_start": active["window_start"],
                "window_end": active["window_end"],
                "config_fingerprint": active["config_fingerprint"],
            },
            "render": {
                "display_time": active["display_time"],
                "include_channels": (
                    None if self._config.include_channels is None else list(self._config.include_channels)
                ),
                "max_points_per_channel": self._config.max_points_per_channel,
                "max_total_points": self._config.max_total_points,
                "max_input_bytes": self._config.max_input_bytes,
                "history_complete": snapshot.history_complete,
                "alarm_state_complete": snapshot.alarm_state_complete,
                "dropped_points": snapshot.dropped_points,
                "bad_points": snapshot.bad_points,
                "source_errors": list(snapshot.source_errors),
            },
            "readings": [
                {
                    "ts": row.timestamp,
                    "iid": row.instrument_id,
                    "ch": row.channel,
                    "v": row.value,
                    "u": row.unit,
                    "st": row.status,
                }
                for row in snapshot.readings
            ],
            "alarms": [
                {
                    "id": alarm.alarm_id,
                    "level": alarm.level,
                    "channels": list(alarm.channels),
                    "triggered_at": alarm.triggered_at,
                    "acknowledged": alarm.acknowledged,
                }
                for alarm in snapshot.active_alarms
            ],
        }

    async def _adopt_render_result(
        self,
        state: PeriodicStateDocument,
        active: dict[str, Any],
        result: PeriodicRenderResult,
    ) -> None:
        if not isinstance(result, PeriodicRenderResult) or (
            result.generation_id != active["generation_id"]
            or result.owner_token != active["owner_token"]
            or result.slot_id != active["slot_id"]
            or result.config_fingerprint != active["config_fingerprint"]
        ):
            raise PeriodicContractError("periodic render result fence does not match")
        ready = mark_ready(
            state,
            result.artifact,
            result.caption,
            slot_id=active["slot_id"],
            owner_token=active["owner_token"],
            now=self._logical_now(state),
        )
        await self._persist(state, ready)

    async def _record_render_failure(
        self,
        state: PeriodicStateDocument,
        active: dict[str, Any],
        *,
        code: str,
        text: str,
    ) -> None:
        count = int(active["render_attempt_count"])
        if active["status"] == PeriodicStatus.PENDING.value:
            count += 1
        now = self._logical_now(state)
        if count < int(active["max_render_attempts"]):
            delay = retry_delay(self._config.backoff_base_s, self._config.backoff_cap_s, count)
            failed = mark_retryable_failure(
                state,
                phase="render",
                certainty="not_applicable",
                code=code,
                text=text,
                not_before=now + delay,
                slot_id=active["slot_id"],
                owner_token=active["owner_token"],
                now=now,
            )
        else:
            failed = mark_terminal_failure(
                state,
                phase="render",
                certainty="not_applicable",
                code=code,
                text=text,
                slot_id=active["slot_id"],
                owner_token=active["owner_token"],
                now=now,
            )
        await self._persist(state, failed)

    async def _deliver(self, state: PeriodicStateDocument, active: dict[str, Any], now: float) -> bool:
        artifact = _artifact_from_active(active)
        try:
            photo = await self._run_blocking(self._artifact_reader, self._data_dir, artifact)
            if type(photo) is not bytes:
                raise TypeError("artifact reader must return immutable bytes")
        except asyncio.CancelledError:
            raise
        except Exception:
            failed_phase = "scheduler"
            failed_certainty = "not_applicable"
            if active["status"] == PeriodicStatus.FAILED.value:
                failed_phase = str(active["failure_phase"])
                failed_certainty = str(active["certainty"])
            failed = mark_terminal_failure(
                state,
                phase=failed_phase,
                certainty=failed_certainty,
                code="periodic_artifact_unavailable",
                text="periodic artifact could not be re-authorized",
                slot_id=active["slot_id"],
                owner_token=active["owner_token"],
                now=now,
            )
            await self._persist(state, failed)
            return True

        if self._stopping:
            return False

        fresh = await self._load_state()
        if self._stopping:
            return False
        fresh_active = _active(fresh)
        expected_status = PeriodicStatus(active["status"])
        if not self._same_active(active, fresh_active, expected_status=expected_status):
            return False
        if (
            fresh_active["artifact"] != active["artifact"]
            or fresh_active["caption"] != active["caption"]
            or fresh_active["config_fingerprint"] != self._config.config_fingerprint
            or fresh_active["destination_fingerprint"] != self._destination_fingerprint
        ):
            return False
        delivering = mark_delivering(
            fresh,
            slot_id=active["slot_id"],
            owner_token=active["owner_token"],
            now=self._logical_now(
                fresh,
                floor=(float(active["not_before"]) if expected_status is PeriodicStatus.FAILED else None),
            ),
        )
        await self._persist(fresh, delivering)
        successor = _active(delivering)
        if successor is None or successor["status"] != PeriodicStatus.DELIVERING.value:
            return False
        await self._await_shielded(
            self._delivery_transaction(successor, photo, str(successor["caption"])),
            heartbeat=True,
            settlement_lock=self._delivery_settlement_lock,
        )
        return True

    async def _delivery_transaction(self, active: dict[str, Any], photo: bytes, caption: str) -> None:
        try:
            artifact = active.get("artifact")
            if not isinstance(artifact, Mapping):
                raise PeriodicContractError("delivery lacks fenced artifact context")
            caption_bytes = caption.encode("utf-8", errors="strict")
            context = PeriodicDeliveryContext(
                slot_id=str(active["slot_id"]),
                generation_id=str(active["generation_id"]),
                owner_token=str(active["owner_token"]),
                artifact_sha256=str(artifact["sha256"]),
                artifact_size=int(artifact["size"]),
                caption_sha256="sha256:" + hashlib.sha256(caption_bytes).hexdigest(),
                caption_size=len(caption_bytes),
            )
            result = await self._delivery.send_artifact(photo, caption, context)
            if not isinstance(result, PeriodicDeliveryResult):
                raise TypeError("delivery returned an invalid result")
            receipt = result.receipt
            if receipt is not None:
                receipt = PeriodicDeliveryReceipt(
                    kind=receipt.kind,
                    receipt_id=receipt.receipt_id,
                    acknowledgement_sha256=receipt.acknowledgement_sha256,
                )
            result = PeriodicDeliveryResult(
                outcome=result.outcome,
                receipt=receipt,
                retryable=result.retryable,
                retry_after_s=result.retry_after_s,
                error_code=result.error_code,
                error_text=result.error_text,
            )
        except asyncio.CancelledError:
            await self._persist_unknown(
                active,
                "delivery_cancelled_unknown",
                "delivery was cancelled after invocation",
            )
            raise
        except Exception:
            await self._persist_unknown(active, "delivery_internal_unknown", "delivery outcome is unknown")
            return
        assert self._delivery_settlement_lock is not None
        async with self._delivery_settlement_lock:
            current = await self._load_state()
            current_active = _active(current)
            if not self._same_active(active, current_active, expected_status=PeriodicStatus.DELIVERING):
                raise PeriodicContractError("delivery state changed before result persistence")
            now = self._logical_now(current)
            if result.outcome is PeriodicDeliveryOutcome.ACCEPTED:
                if result.receipt is None or result.receipt.kind != self._expected_delivery_kind:
                    candidate = mark_delivery_unknown(
                        current,
                        code="delivery_receipt_kind_mismatch",
                        text="accepted delivery receipt kind does not match destination authority",
                        slot_id=active["slot_id"],
                        owner_token=active["owner_token"],
                        now=now,
                    )
                else:
                    candidate = mark_succeeded(
                        current,
                        receipt=result.receipt,
                        slot_id=active["slot_id"],
                        owner_token=active["owner_token"],
                        now=now,
                    )
            elif result.outcome is PeriodicDeliveryOutcome.UNKNOWN:
                candidate = mark_delivery_unknown(
                    current,
                    code=result.error_code or "delivery_internal_unknown",
                    text=result.error_text or "delivery outcome is unknown",
                    slot_id=active["slot_id"],
                    owner_token=active["owner_token"],
                    now=now,
                )
            else:
                retryable = result.retryable
                certainty = "rejected" if result.outcome is PeriodicDeliveryOutcome.REJECTED else "not_sent"
                count = int(active["delivery_attempt_count"])
                if retryable and count < int(active["max_delivery_attempts"]):
                    delay = (
                        result.retry_after_s
                        if result.retry_after_s is not None
                        else retry_delay(
                            self._config.backoff_base_s,
                            self._config.backoff_cap_s,
                            count,
                        )
                    )
                    candidate = mark_retryable_failure(
                        current,
                        phase="delivery",
                        certainty=certainty,
                        code=result.error_code or "telegram_connect_failed",
                        text=result.error_text or "Telegram delivery failed",
                        not_before=now + delay,
                        slot_id=active["slot_id"],
                        owner_token=active["owner_token"],
                        now=now,
                    )
                else:
                    candidate = mark_terminal_failure(
                        current,
                        phase="delivery",
                        certainty=certainty,
                        code=result.error_code or "telegram_permanent_rejection",
                        text=result.error_text or "Telegram delivery failed",
                        slot_id=active["slot_id"],
                        owner_token=active["owner_token"],
                        now=now,
                    )
            await self._persist(current, candidate)

    async def _persist_unknown(self, active: dict[str, Any], code: str, text: str) -> None:
        assert self._delivery_settlement_lock is not None
        async with self._delivery_settlement_lock:
            current = await self._load_state()
            current_active = _active(current)
            if not self._same_active(active, current_active, expected_status=PeriodicStatus.DELIVERING):
                return
            candidate = mark_delivery_unknown(
                current,
                code=code,
                text=text,
                slot_id=active["slot_id"],
                owner_token=active["owner_token"],
                now=self._logical_now(current),
            )
            await self._persist(current, candidate)

    async def _await_shielded(
        self,
        awaitable: Awaitable[Any],
        *,
        heartbeat: bool = False,
        settlement_lock: asyncio.Lock | None = None,
    ) -> Any:
        task = asyncio.ensure_future(awaitable)
        if heartbeat:
            return await self._await_transaction_with_heartbeat(task, settlement_lock=settlement_lock)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as cancelled:
            _value, settlement_error = await _settle_cancelled_task(task)
            if settlement_error is not None:
                raise cancelled from settlement_error
            raise cancelled

    async def _await_transaction_with_heartbeat(
        self,
        task: asyncio.Task[Any],
        *,
        settlement_lock: asyncio.Lock | None,
    ) -> Any:
        timer: asyncio.Task[None] | None = None
        while not task.done():
            monotonic_now = self._clock.monotonic()
            deadline = min(
                self._next_health_heartbeat,
                self._next_alarm_refresh,
            )
            delay = max(0.001, deadline - monotonic_now)
            timer = asyncio.create_task(self._clock.sleep(delay))
            try:
                done, _pending = await asyncio.wait({task, timer}, return_when=asyncio.FIRST_COMPLETED)
            except asyncio.CancelledError as cancelled:
                timer.cancel()
                await asyncio.gather(timer, return_exceptions=True)
                _value, settlement_error = await _settle_cancelled_task(task)
                if settlement_error is not None:
                    raise cancelled from settlement_error
                raise
            if task in done:
                timer.cancel()
                await asyncio.gather(timer, return_exceptions=True)
                return task.result()
            try:
                timer.result()
                if settlement_lock is None:
                    await self._refresh_periodic_authority_if_due()
                else:
                    async with settlement_lock:
                        if task.done():
                            return task.result()
                        await self._refresh_periodic_authority_if_due()
            except asyncio.CancelledError as cancelled:
                _value, settlement_error = await _settle_cancelled_task(task)
                if settlement_error is not None:
                    raise cancelled from settlement_error
                raise
            except BaseException as heartbeat_error:
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError as cancelled:
                    _value, settlement_error = await _settle_cancelled_task(task)
                    if settlement_error is not None:
                        raise cancelled from settlement_error
                    raise cancelled from heartbeat_error
                except BaseException as settlement_error:
                    raise heartbeat_error from settlement_error
                raise
            finally:
                timer = None
        return task.result()

    @staticmethod
    def _same_active(
        expected: Mapping[str, object],
        observed: dict[str, Any] | None,
        *,
        expected_status: PeriodicStatus,
    ) -> bool:
        return bool(
            observed is not None
            and observed["slot_id"] == expected["slot_id"]
            and observed["owner_token"] == expected["owner_token"]
            and observed["generation_id"] == expected["generation_id"]
            and observed["status"] == expected_status.value
        )


CoordinatorFactory = Callable[[PeriodicPngConfig], PeriodicPngCoordinator]
ConfigLoader = Callable[[Path], PeriodicPngConfigLoad]


class PeriodicPngSupervisor:
    """Separate H3 election, strict config reload, and coordinator ownership."""

    def __init__(
        self,
        *,
        data_dir: Path,
        config_dir: Path,
        periodic_allowed: bool,
        coordinator_factory: CoordinatorFactory,
        config_loader: ConfigLoader = load_periodic_png_config,
        clock: Clock | None = None,
        run_blocking: RunBlocking | None = None,
    ) -> None:
        if type(periodic_allowed) is not bool:
            raise TypeError("periodic_allowed must be a boolean")
        if coordinator_factory is None:
            raise TypeError("coordinator_factory is required")
        self._data_dir = Path(data_dir)
        self._config_dir = Path(config_dir)
        self._allowed = periodic_allowed
        self._factory = coordinator_factory
        self._loader = config_loader
        self._clock = clock or _SystemClock()
        self._run_blocking: RunBlocking = run_blocking or _to_thread
        self._stop_event: asyncio.Event | None = None
        self._stop_requested = False
        self._leader_fd: int | None = None
        self._coordinator: PeriodicPngCoordinator | None = None
        self._run_task: asyncio.Task[None] | None = None
        self._published_health_record: PeriodicStateDocument | None = None

    async def run(self) -> None:
        if self._run_task is not None and self._run_task is not asyncio.current_task():
            raise RuntimeError("periodic PNG supervisor is already running")
        if not self._allowed or self._stop_requested:
            return
        self._stop_event = asyncio.Event()
        self._run_task = asyncio.current_task()
        backoff_index = 0
        try:
            while not self._stop_requested:
                try:
                    load = await self._run_blocking(self._loader, self._config_dir)
                except Exception:
                    backoff_index = await self._handle_config_loader_failure(backoff_index)
                    continue
                if not load.requested:
                    if self._leader_fd is not None:
                        await self._stop_then_write_orderly(disabled=True)
                        self._release_leader()
                    backoff_index = 0
                    await self._sleep_or_stop(_CONFIG_POLL_S)
                    continue

                if self._leader_fd is None:
                    self._leader_fd = await _acquire_lock_cancellation_safe(
                        self._run_blocking,
                        PERIODIC_LEADER_LOCK,
                        lock_dir=self._data_dir,
                    )
                    if self._leader_fd is None:
                        await self._sleep_or_stop(_ELECTION_BACKOFF[min(backoff_index, 5)])
                        backoff_index = min(backoff_index + 1, 5)
                        continue
                    backoff_index = 0

                try:
                    load = await self._run_blocking(self._loader, self._config_dir)
                except Exception:
                    backoff_index = await self._handle_config_loader_failure(backoff_index)
                    continue
                if not load.requested:
                    await self._stop_then_write_orderly(disabled=True)
                    self._release_leader()
                    backoff_index = 0
                    await self._sleep_or_stop(_CONFIG_POLL_S)
                    continue
                if not load.runnable or load.config is None:
                    if await self._stop_then_write_degraded_config(load):
                        await self._sleep_or_stop(_CONFIG_POLL_S)
                    else:
                        self._release_leader()
                        await self._sleep_or_stop(_ELECTION_BACKOFF[min(backoff_index, 5)])
                        backoff_index = min(backoff_index + 1, 5)
                    continue

                if self._coordinator is None:
                    if not await self._try_construct_and_start(load.config):
                        self._release_leader()
                        if self._stop_requested:
                            return
                        await self._sleep_or_stop(_ELECTION_BACKOFF[min(backoff_index, 5)])
                        backoff_index = min(backoff_index + 1, 5)
                        continue

                if self._stop_requested:
                    await self._stop_then_write_orderly(disabled=False)
                    self._release_leader()
                    return
                if self._coordinator is None:
                    await self._stop_then_mark_runtime_failed()
                    self._release_leader()
                    await self._sleep_or_stop(_ELECTION_BACKOFF[min(backoff_index, 5)])
                    backoff_index = min(backoff_index + 1, 5)
                    continue
                outcome = await self._monitor_iteration()
                if outcome == "stop":
                    await self._stop_then_write_orderly(disabled=False)
                    self._release_leader()
                    return
                if outcome == "failed":
                    await self._stop_then_mark_runtime_failed()
                    self._release_leader()
                    await self._sleep_or_stop(_ELECTION_BACKOFF[min(backoff_index, 5)])
                    backoff_index = min(backoff_index + 1, 5)
                    continue

                try:
                    refreshed = await self._run_blocking(self._loader, self._config_dir)
                except Exception:
                    backoff_index = await self._handle_config_loader_failure(backoff_index)
                    continue
                if not refreshed.requested:
                    await self._stop_then_write_orderly(disabled=True)
                    self._release_leader()
                    backoff_index = 0
                    await self._sleep_or_stop(_CONFIG_POLL_S)
                    continue
                if not refreshed.runnable or refreshed.config is None:
                    if await self._stop_then_write_degraded_config(refreshed):
                        await self._sleep_or_stop(_CONFIG_POLL_S)
                    else:
                        self._release_leader()
                        await self._sleep_or_stop(_ELECTION_BACKOFF[min(backoff_index, 5)])
                        backoff_index = min(backoff_index + 1, 5)
                    continue
                if self._stop_requested:
                    await self._stop_then_write_orderly(disabled=False)
                    self._release_leader()
                    return
                if self._coordinator is None:
                    await self._stop_then_mark_runtime_failed()
                    self._release_leader()
                    await self._sleep_or_stop(_ELECTION_BACKOFF[min(backoff_index, 5)])
                    backoff_index = min(backoff_index + 1, 5)
                    continue
                if refreshed.config != self._coordinator.config:
                    await self._stop_then_mark_runtime_failed()
                    if not await self._try_construct_and_start(refreshed.config):
                        self._release_leader()
                        if self._stop_requested:
                            return
                        await self._sleep_or_stop(_ELECTION_BACKOFF[min(backoff_index, 5)])
                        backoff_index = min(backoff_index + 1, 5)
            if self._leader_fd is not None:
                await self._stop_then_write_orderly(disabled=False)
                self._release_leader()
        except asyncio.CancelledError as cancelled:

            async def cancelled_cleanup() -> None:
                if self._leader_fd is not None:
                    await self._stop_then_write_orderly(disabled=False)
                else:
                    await self._stop_coordinator()

            cleanup_task = asyncio.create_task(cancelled_cleanup())
            cleanup_error: BaseException | None = None
            try:
                await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                _value, cleanup_error = await _settle_cancelled_task(cleanup_task)
            except BaseException as exc:
                cleanup_error = exc
            self._release_leader()
            if cleanup_error is not None:
                raise cancelled from cleanup_error
            raise
        finally:
            try:
                await self._stop_coordinator()
            finally:
                if self._stop_requested and self._leader_fd is None and self._published_health_record is not None:
                    await self._write_stopped_if_unowned()
                self._release_leader()
                self._run_task = None

    async def _write_stopped_if_unowned(self) -> None:
        """Publish terminal health only while holding otherwise-free authority."""

        try:
            leader_fd = await _acquire_lock_cancellation_safe(
                self._run_blocking,
                PERIODIC_LEADER_LOCK,
                lock_dir=self._data_dir,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return
        if leader_fd is None:
            # Another supervisor is authoritative.  Its health must win.
            return
        self._leader_fd = leader_fd
        try:
            published = self._published_health_record
            if published is None:
                return
            try:
                current = await self._run_blocking(load_periodic_state, self._data_dir)
            except Exception:
                return
            if _active(current) is not None or current.payload != published.payload:
                # Leadership may have changed hands and become free again
                # before this old idle supervisor stopped.  Exact durable
                # provenance, not merely a familiar health status, is the
                # authority to replace that record with terminal health.
                return
            await self._write_orderly_health(disabled=False)
        finally:
            self._release_leader()

    async def _handle_config_loader_failure(self, backoff_index: int) -> int:
        if self._leader_fd is not None:
            await self._stop_then_mark_runtime_failed()
            self._release_leader()
        await self._sleep_or_stop(_ELECTION_BACKOFF[min(backoff_index, 5)])
        return min(backoff_index + 1, 5)

    async def _try_construct_and_start(self, config: PeriodicPngConfig) -> bool:
        try:
            coordinator = self._factory(config)
            self._coordinator = coordinator
            await coordinator.start()
            return True
        except asyncio.CancelledError as cancelled:
            try:
                await self._stop_then_mark_runtime_failed()
            except BaseException as cleanup_error:
                raise cancelled from cleanup_error
            raise
        except PeriodicSourceUnavailable:
            await self._stop_then_mark_engine_unavailable()
            return False
        except Exception:
            await self._stop_then_mark_runtime_failed()
            return False

    async def _stop_then_mark_engine_unavailable(self) -> None:
        cleanup_error: BaseException | None = None
        try:
            await self._stop_coordinator()
        except BaseException as exc:
            cleanup_error = exc
        await self._write_engine_unavailable_health()
        if cleanup_error is not None:
            raise cleanup_error

    async def _stop_then_mark_runtime_failed(self) -> None:
        cleanup_error: BaseException | None = None
        try:
            await self._stop_coordinator()
        except BaseException as exc:
            cleanup_error = exc
        await self._write_runtime_failed_health()
        if cleanup_error is not None:
            raise cleanup_error

    async def _stop_then_write_orderly(self, *, disabled: bool) -> None:
        cleanup_error: BaseException | None = None
        try:
            await self._stop_coordinator()
        except BaseException as exc:
            cleanup_error = exc
        await self._write_orderly_health(disabled=disabled)
        if cleanup_error is not None:
            raise cleanup_error

    async def _stop_then_write_degraded_config(self, load: PeriodicPngConfigLoad) -> bool:
        cleanup_error: BaseException | None = None
        try:
            await self._stop_coordinator()
        except BaseException as exc:
            cleanup_error = exc
        wrote = await self._write_degraded_config(load)
        if cleanup_error is not None:
            raise cleanup_error
        return wrote

    async def _monitor_iteration(self) -> str:
        assert self._coordinator is not None and self._stop_event is not None
        wait_task = asyncio.create_task(self._coordinator.wait())
        poll_task = asyncio.create_task(self._clock.sleep(_CONFIG_POLL_S))
        stop_task = asyncio.create_task(self._stop_event.wait())
        tasks = {wait_task, poll_task, stop_task}
        try:
            done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if stop_task in done:
                return "stop"
            if wait_task in done:
                try:
                    await wait_task
                except asyncio.CancelledError:
                    return "stop" if self._stop_requested else "failed"
                except Exception:
                    return "failed"
                return "failed"
            return "poll"
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _write_degraded_config(self, load: PeriodicPngConfigLoad) -> bool:
        try:
            state = await self._run_blocking(load_periodic_state, self._data_dir)
            previous = float(state.payload["updated_at"])
            wall_now = self._clock.wall_time()
            now = wall_now if wall_now > previous else math.nextafter(previous, math.inf)
            candidate = set_periodic_health(
                state,
                status="degraded_config",
                code=load.error_code or "periodic_config_invalid",
                text="periodic configuration is invalid",
                now=now,
            )
            active = _active(state)
            kwargs: dict[str, object] = {}
            if active is not None:
                kwargs = {
                    "expected_slot_id": active["slot_id"],
                    "expected_owner_token": active["owner_token"],
                    "expected_status": PeriodicStatus(active["status"]),
                }
            await self._run_blocking(write_periodic_state, self._data_dir, candidate, **kwargs)
            self._published_health_record = candidate
            return True
        except Exception:
            return False

    async def _write_orderly_health(self, *, disabled: bool) -> None:
        try:
            state = await self._run_blocking(load_periodic_state, self._data_dir)
            previous = float(state.payload["updated_at"])
            wall_now = self._clock.wall_time()
            now = wall_now if wall_now > previous else math.nextafter(previous, math.inf)
            candidate = set_periodic_health(
                state,
                status="disabled" if disabled else "stopped",
                code="periodic_disabled" if disabled else "periodic_stopped",
                text=("periodic reporting is disabled" if disabled else "periodic runtime is stopped"),
                now=now,
            )
            active = _active(state)
            kwargs: dict[str, object] = {}
            if active is not None:
                kwargs = {
                    "expected_slot_id": active["slot_id"],
                    "expected_owner_token": active["owner_token"],
                    "expected_status": PeriodicStatus(active["status"]),
                }
            await self._run_blocking(write_periodic_state, self._data_dir, candidate, **kwargs)
            self._published_health_record = candidate
        except Exception:
            return

    async def _write_runtime_failed_health(self) -> None:
        try:
            state = await self._run_blocking(load_periodic_state, self._data_dir)
            previous = float(state.payload["updated_at"])
            wall_now = self._clock.wall_time()
            now = wall_now if wall_now > previous else math.nextafter(previous, math.inf)
            candidate = set_periodic_health(
                state,
                status="degraded_runtime",
                code="periodic_runtime_failed",
                text="periodic runtime is unavailable",
                now=now,
            )
            active = _active(state)
            kwargs: dict[str, object] = {}
            if active is not None:
                kwargs = {
                    "expected_slot_id": active["slot_id"],
                    "expected_owner_token": active["owner_token"],
                    "expected_status": PeriodicStatus(active["status"]),
                }
            await self._run_blocking(write_periodic_state, self._data_dir, candidate, **kwargs)
            self._published_health_record = candidate
        except Exception:
            return

    async def _write_engine_unavailable_health(self) -> None:
        try:
            state = await self._run_blocking(load_periodic_state, self._data_dir)
            previous = float(state.payload["updated_at"])
            wall_now = self._clock.wall_time()
            now = wall_now if wall_now > previous else math.nextafter(previous, math.inf)
            candidate = set_periodic_health(
                state,
                status="degraded_source",
                code="periodic_engine_unavailable",
                text="periodic engine authority is unavailable",
                now=now,
            )
            active = _active(state)
            kwargs: dict[str, object] = {}
            if active is not None:
                kwargs = {
                    "expected_slot_id": active["slot_id"],
                    "expected_owner_token": active["owner_token"],
                    "expected_status": PeriodicStatus(active["status"]),
                }
            await self._run_blocking(write_periodic_state, self._data_dir, candidate, **kwargs)
            self._published_health_record = candidate
        except Exception:
            return

    async def _sleep_or_stop(self, seconds: float) -> None:
        if self._stop_event is None:
            return
        sleep_task = asyncio.create_task(self._clock.sleep(seconds))
        stop_task = asyncio.create_task(self._stop_event.wait())
        try:
            await asyncio.wait({sleep_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (sleep_task, stop_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(sleep_task, stop_task, return_exceptions=True)

    async def stop(self) -> None:
        self._stop_requested = True
        if self._stop_event is not None:
            self._stop_event.set()
        await self._stop_coordinator()
        task = self._run_task
        if task is not None and task is not asyncio.current_task():
            await asyncio.shield(task)

    async def _stop_coordinator(self) -> None:
        coordinator = self._coordinator
        if coordinator is None:
            return
        task = asyncio.create_task(coordinator.stop())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as cancelled:
            _value, settlement_error = await _settle_cancelled_task(task)
            if self._coordinator is coordinator:
                self._coordinator = None
            if settlement_error is not None:
                raise cancelled from settlement_error
            raise
        finally:
            if task.done() and self._coordinator is coordinator:
                self._coordinator = None

    def _release_leader(self) -> None:
        if self._leader_fd is None:
            return
        release_lock(
            self._leader_fd,
            PERIODIC_LEADER_LOCK,
            unlink=False,
            lock_dir=self._data_dir,
        )
        self._leader_fd = None


__all__ = [
    "AlarmQueryResult",
    "Clock",
    "LiveSourceCut",
    "PeriodicAlarmQuery",
    "PeriodicArchiveQuery",
    "PeriodicLiveSources",
    "PeriodicPngCoordinator",
    "PeriodicPngSupervisor",
    "retry_delay",
]
