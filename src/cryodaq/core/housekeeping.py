from __future__ import annotations

import asyncio
import gzip
import json
import logging
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from cryodaq.core.shutdown_settlement import CancelledTaskSettlement, cancel_and_settle_tasks
from cryodaq.drivers.base import ChannelStatus, Reading

logger = logging.getLogger(__name__)


async def _settle_without_cancelling(
    owners: tuple[asyncio.Future[Any], ...],
) -> CancelledTaskSettlement:
    """Observe retained executor work without abandoning it on caller cancellation."""

    unique_owners = tuple(dict.fromkeys(owners))
    if not unique_owners:
        return CancelledTaskSettlement()

    async def collect() -> list[object]:
        return await asyncio.gather(*unique_owners, return_exceptions=True)

    drain = asyncio.create_task(collect(), name="housekeeping-executor-terminal-settlement")
    cancellation: asyncio.CancelledError | None = None
    while not drain.done():
        try:
            await asyncio.shield(drain)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
    failures = tuple(
        result
        for result in drain.result()
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError)
    )
    return CancelledTaskSettlement(failures=failures, cancellation=cancellation)


async def _settle_executor_operation[ExecutorResult](
    operation: asyncio.Future[ExecutorResult],
) -> ExecutorResult:
    """Retain the real executor wrapper until its worker thread is terminal.

    Direct cancellation of this owner is remembered but never forwarded to
    ``operation``.  A terminal worker failure outranks that cancellation so a
    caller cannot turn a failed mutation into an apparently harmless cancel.
    """

    cancellation: asyncio.CancelledError | None = None
    while not operation.done():
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
        except BaseException:
            break
    try:
        result = operation.result()
    except BaseException as operation_error:
        if cancellation is not None and not isinstance(operation_error, asyncio.CancelledError):
            raise operation_error from cancellation
        raise
    if cancellation is not None:
        raise cancellation
    return result


async def _await_executor_owner[ExecutorResult](
    owner: asyncio.Task[ExecutorResult],
) -> ExecutorResult:
    """Await an executor owner without caller cancellation abandoning it."""

    cancellation: asyncio.CancelledError | None = None
    while not owner.done():
        try:
            await asyncio.shield(owner)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
            if owner.done():
                break
        except BaseException:
            break
    try:
        result = owner.result()
    except BaseException as owner_error:
        if cancellation is not None and not isinstance(owner_error, asyncio.CancelledError):
            raise owner_error from cancellation
        raise
    if cancellation is not None:
        raise cancellation
    return result


def _combine_settlements(*settlements: CancelledTaskSettlement) -> CancelledTaskSettlement:
    failures: list[BaseException] = []
    cancellation: asyncio.CancelledError | None = None
    for settlement in settlements:
        for failure in settlement.failures:
            if all(failure is not retained for retained in failures):
                failures.append(failure)
        if cancellation is None and settlement.cancellation is not None:
            cancellation = settlement.cancellation
    return CancelledTaskSettlement(failures=tuple(failures), cancellation=cancellation)


class HousekeepingConfigError(RuntimeError):
    """Raised when housekeeping.yaml cannot be loaded in a fail-closed manner."""


def load_housekeeping_config(config_path: Path) -> dict[str, Any]:
    """Load housekeeping.yaml. Raises HousekeepingConfigError on failure."""
    if not config_path.exists():
        raise HousekeepingConfigError(
            f"housekeeping.yaml not found at {config_path} — refusing to start without housekeeping configuration"
        )
    try:
        with config_path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise HousekeepingConfigError(f"housekeeping.yaml at {config_path}: YAML parse error — {exc}") from exc
    if not isinstance(raw, dict):
        raise HousekeepingConfigError(f"housekeeping.yaml at {config_path}: expected mapping, got {type(raw).__name__}")
    return raw


def load_protected_channel_patterns(*config_paths: Path) -> list[str]:
    patterns: list[str] = []
    for path in config_paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        for key in ("alarms", "interlocks"):
            for item in raw.get(key, []):
                pattern = str(item.get("channel_pattern", "")).strip()
                if pattern:
                    patterns.append(pattern)
    return patterns


# --------------------------------------------------------------------------
# Phase 2b H.1: alarms_v3.yaml integration
# --------------------------------------------------------------------------
#
# The legacy ``load_protected_channel_patterns`` only knows the old top-level
# ``alarms`` / ``interlocks`` schema (with explicit ``channel_pattern`` fields).
# Production now uses ``alarms_v3.yaml`` with a richer schema:
#
#     channel_groups:
#       calibrated: [Т11, Т12]
#     global_alarms:
#       <name>:
#         alarm_type: threshold|composite|stale|rate
#         channel: P1                      # OR
#         channels: [Т11, Т12]             # OR
#         conditions: [{channel/channels/channel_group: ...}, ...]   # composite
#         level: CRITICAL|WARNING|...
#     phase_alarms: { same shape }
#     interlocks:
#       <name>:
#         channel|channels|channel_group: ...
#         action: emergency_off|stop_source
#
# Without reading this file, the throttle silently thins critical channels
# even though the operator has marked them in alarms_v3.yaml.
#
# This loader is intentionally tolerant: missing file → empty set, parse
# errors → empty set + ERROR log, unknown fields ignored.

_CRITICAL_LEVELS = frozenset({"critical", "high"})


def _extract_channel_refs(node: Any) -> list[str]:
    """Recursively pull every channel/channels/channel_group string from a node.

    Walks any nested dicts and lists. This catches:

    - top-level ``channel`` / ``channels`` / ``channel_group``
    - composite ``conditions: [{channel/channels/channel_group: ...}, ...]``
    - rate ``additional_condition: {channel: ..., ...}`` (Phase 2b P2)
    - any future nested form added to alarms_v3 schema
    """
    refs: list[str] = []
    if isinstance(node, dict):
        ch = node.get("channel")
        if isinstance(ch, str) and ch.strip():
            refs.append(ch.strip())

        chs = node.get("channels")
        if isinstance(chs, list):
            for c in chs:
                if isinstance(c, str) and c.strip():
                    refs.append(c.strip())

        group = node.get("channel_group")
        if isinstance(group, str) and group.strip():
            refs.append("__group__:" + group.strip())

        # Walk every nested dict / list value to catch additional_condition,
        # conditions, and any future container fields. We've already pulled
        # the leaf channel/channels/channel_group above; the recursive walk
        # only re-enters containers, so leaf strings are not double-counted
        # (the recursion handles dicts/lists, not bare strings).
        for key, value in node.items():
            if key in ("channel", "channels", "channel_group"):
                continue
            if isinstance(value, (dict, list)):
                refs.extend(_extract_channel_refs(value))

    elif isinstance(node, list):
        for item in node:
            refs.extend(_extract_channel_refs(item))

    return refs


def load_critical_channels_from_alarms_v3(config_path: Path) -> set[str]:
    """Extract channel patterns of critical alarms + all interlocks from alarms_v3.yaml.

    Returns a set of regex pattern strings (each one re.escape'd so it
    matches the short ID as a substring of the full reading channel name).
    Empty set on missing file / parse error.
    """
    if not config_path.exists():
        return set()

    try:
        with config_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except Exception as exc:
        logger.error("Failed to load alarms_v3 for throttle protection: %s", exc)
        return set()

    if not isinstance(data, dict):
        return set()

    # Build the channel_group → [channels] map first.
    raw_groups = data.get("channel_groups") or {}
    groups: dict[str, list[str]] = {}
    if isinstance(raw_groups, dict):
        for name, channels in raw_groups.items():
            if isinstance(channels, list):
                groups[str(name)] = [str(c) for c in channels if isinstance(c, str)]

    refs: list[str] = []

    # Critical/high alarms in global_alarms (flat: alarm_id → alarm)
    global_alarms = data.get("global_alarms") or {}
    if isinstance(global_alarms, dict):
        for _alarm_name, alarm in global_alarms.items():
            if not isinstance(alarm, dict):
                continue
            level = str(alarm.get("level", "")).strip().lower()
            if level not in _CRITICAL_LEVELS:
                continue
            refs.extend(_extract_channel_refs(alarm))

    # Critical/high alarms in phase_alarms (nested: phase → alarm_id → alarm).
    # Phase 2b Block D P1: previous code treated phase_alarms as flat
    # and silently skipped every entry.
    phase_alarms = data.get("phase_alarms") or {}
    if isinstance(phase_alarms, dict):
        for _phase_name, phase_section in phase_alarms.items():
            if not isinstance(phase_section, dict):
                continue
            for _alarm_name, alarm in phase_section.items():
                if not isinstance(alarm, dict):
                    continue
                level = str(alarm.get("level", "")).strip().lower()
                if level not in _CRITICAL_LEVELS:
                    continue
                refs.extend(_extract_channel_refs(alarm))

    # ALL interlocks — every interlock is by definition worth protecting,
    # regardless of action (emergency_off / stop_source).
    interlocks = data.get("interlocks") or {}
    if isinstance(interlocks, dict):
        for _name, interlock in interlocks.items():
            if isinstance(interlock, dict):
                refs.extend(_extract_channel_refs(interlock))

    # Resolve channel_group references and re.escape short IDs so they
    # match as substrings of the full reading channel name.
    patterns: set[str] = set()
    for ref in refs:
        if ref.startswith("__group__:"):
            group_name = ref.removeprefix("__group__:")
            channels = groups.get(group_name)
            if not channels:
                logger.warning(
                    "alarms_v3 references unknown channel_group %r — no channels protected for this reference",
                    group_name,
                )
                continue
            for ch in channels:
                patterns.add(re.escape(ch))
        else:
            patterns.add(re.escape(ref))

    return patterns


def resolve_canonical_temperature_bindings(descriptor_catalog: Any, canonical_ids: set[str]) -> set[str]:
    """Reverse-map canonical temperature identities to exact raw labels.

    ``AdaptiveThrottle`` observes pre-bind readings, so canonical IDs and
    broad regexes are unsafe there.  Each requested identity must have exactly
    one non-observational raw emitted binding; the returned expressions are
    full-string escaped labels suitable for ``fullmatch``.
    """
    bindings = descriptor_catalog._bindings
    resolved: set[str] = set()
    for canonical_id in canonical_ids:
        candidates = sorted(
            emitted
            for (_instrument, emitted), bound_id in bindings.items()
            if bound_id == canonical_id and not bound_id.endswith(".raw") and not emitted.endswith("_raw")
        )
        if len(candidates) != 1:
            raise HousekeepingConfigError(
                f"canonical safety identity {canonical_id!r} must resolve to exactly one emitted label; "
                f"got {candidates!r}"
            )
        resolved.add(rf"^{re.escape(candidates[0])}$")
    return resolved


@dataclass
class _ThrottleState:
    last_seen_value: float
    last_emitted_value: float
    last_emitted_at: datetime
    stable_since: datetime


class AdaptiveThrottle:
    def __init__(self, config: dict[str, Any] | None = None, *, protected_patterns: list[str] | None = None) -> None:
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", False))
        self._include = [re.compile(str(item)) for item in cfg.get("include_patterns", [])]
        self._exclude = [re.compile(str(item)) for item in cfg.get("exclude_patterns", [])]
        self._protected = [re.compile(str(item)) for item in (protected_patterns or [])]
        self._stable_duration_s = float(cfg.get("stable_duration_s", 120.0))
        self._max_interval_s = float(cfg.get("max_interval_s", 30.0))
        self._transition_holdoff_s = float(cfg.get("transition_holdoff_s", 30.0))
        delta_cfg = cfg.get("absolute_delta", {})
        self._default_delta = float(delta_cfg.get("default", 0.05))
        self._delta_by_unit = {str(key): float(value) for key, value in delta_cfg.items() if key != "default"}
        self._state: dict[str, _ThrottleState] = {}
        self._active_alarm_count = 0
        self._transition_until: datetime | None = None
        self._suppressed_count = 0

    @property
    def suppressed_count(self) -> int:
        return self._suppressed_count

    def observe_runtime_signal(self, reading: Reading) -> None:
        channel = reading.channel
        if channel == "analytics/alarm_count":
            self._active_alarm_count = max(0, int(round(reading.value)))
            return
        if channel.startswith("analytics/keithley_channel_state/"):
            self._transition_until = reading.timestamp + timedelta(seconds=self._transition_holdoff_s)
            return
        if channel == "analytics/safety_state":
            state = str(reading.metadata.get("state", "")).lower()
            if state != "running":
                self._transition_until = reading.timestamp + timedelta(seconds=self._transition_holdoff_s)

    def filter_for_archive(self, readings: list[Reading]) -> list[Reading]:
        if not self.enabled:
            return list(readings)
        filtered: list[Reading] = []
        for reading in readings:
            if self._should_emit(reading):
                filtered.append(reading)
            else:
                self._suppressed_count += 1
        return filtered

    def _should_emit(self, reading: Reading) -> bool:
        if self._active_alarm_count > 0:
            return True
        if reading.status is not ChannelStatus.OK:
            return True
        if self._transition_until is not None and reading.timestamp <= self._transition_until:
            return True
        if self._matches_any(reading.channel, self._protected):
            return True
        if self._matches_any(reading.channel, self._exclude):
            return True
        if self._include and not self._matches_any(reading.channel, self._include):
            return True

        state = self._state.get(reading.channel)
        if state is None:
            self._state[reading.channel] = _ThrottleState(
                last_seen_value=reading.value,
                last_emitted_value=reading.value,
                last_emitted_at=reading.timestamp,
                stable_since=reading.timestamp,
            )
            return True

        delta = abs(reading.value - state.last_seen_value)
        threshold = self._delta_by_unit.get(reading.unit, self._default_delta)
        now = reading.timestamp
        state.last_seen_value = reading.value

        if delta > threshold:
            state.last_emitted_value = reading.value
            state.last_emitted_at = now
            state.stable_since = now
            return True

        stable_for = (now - state.stable_since).total_seconds()
        since_emit = (now - state.last_emitted_at).total_seconds()
        if stable_for < self._stable_duration_s:
            state.last_emitted_value = reading.value
            state.last_emitted_at = now
            return True
        if since_emit >= self._max_interval_s:
            state.last_emitted_value = reading.value
            state.last_emitted_at = now
            return True
        return False

    @staticmethod
    def _matches_any(channel: str, patterns: list[re.Pattern[str]]) -> bool:
        return any(pattern.search(channel) for pattern in patterns)


@dataclass(frozen=True, slots=True)
class HousekeepingAction:
    action: str
    source: Path
    target: Path | None = None


class HousekeepingService:
    def __init__(
        self,
        data_dir: Path,
        experiment_artifacts_dir: Path,
        *,
        config: dict[str, Any] | None = None,
        skip_daily_db_compression: bool = False,
    ) -> None:
        cfg = config or {}
        self._data_dir = data_dir
        self._artifacts_dir = experiment_artifacts_dir
        self._enabled = bool(cfg.get("enabled", False))
        self._interval_s = float(cfg.get("interval_s", 3600.0))
        self._compress_after_days = int(cfg.get("compress_after_days", 14))
        self._delete_after_days = int(cfg.get("delete_compressed_after_days", 90))
        self._dry_run = bool(cfg.get("dry_run", False))
        # F1: when cold rotation is enabled it owns the daily-DB lifecycle
        # (hot .db → zstd Parquet after age_days). Retention must then NOT gzip
        # daily readings DBs: a data_YYYY-MM-DD.db.gz is invisible to every
        # reader AND rotation historically globbed only .db, so a compressed
        # day died without ever reaching cold storage. Wired at build time from
        # cold_rotation.enabled; default False keeps legacy compress behaviour.
        self._skip_daily_db_compression = bool(skip_daily_db_compression)
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._stopping = False
        self._lifecycle_lock = asyncio.Lock()
        self._executor_admission_open = True
        self._executor_futures: set[asyncio.Task[Any]] = set()

    def _lifecycle_transition_lock(self) -> asyncio.Lock:
        """Return the single owner that serializes start/stop generations."""

        lock = getattr(self, "_lifecycle_lock", None)
        if lock is None:
            # Compatibility for partially constructed owners used by terminal
            # settlement and recovery paths.  Creation is atomic on one loop.
            lock = asyncio.Lock()
            self._lifecycle_lock = lock
        return lock

    async def start(self) -> None:
        if not self._enabled:
            return
        async with self._lifecycle_transition_lock():
            if self._stopping:
                raise RuntimeError("housekeeping cannot start while shutdown is settling")
            retained = self._task
            if self._running and retained is not None and not retained.done():
                return
            self._running = False
            if retained is not None:
                settlement = await cancel_and_settle_tasks((retained,))
                self._task = None
                settlement.raise_if_unsuccessful()
            retained_executors = tuple(self._executor_futures)
            executor_settlement = await _settle_without_cancelling(retained_executors)
            self._executor_futures.clear()
            executor_settlement.raise_if_unsuccessful()
            self._executor_admission_open = True
            self._running = True
            self._task = asyncio.create_task(self._loop(), name="housekeeping_service")

    async def stop(self) -> None:
        async with self._lifecycle_transition_lock():
            self._stopping = True
            self._executor_admission_open = False
            self._running = False
            combined: CancelledTaskSettlement | None = None
            try:
                task = self._task
                executor_futures = tuple(getattr(self, "_executor_futures", ()))
                task_settlement = await cancel_and_settle_tasks(() if task is None else (task,))
                executor_settlement = await _settle_without_cancelling(executor_futures)
                self._task = None
                if hasattr(self, "_executor_futures"):
                    self._executor_futures.clear()
                combined = _combine_settlements(task_settlement, executor_settlement)
            finally:
                self._stopping = False
            assert combined is not None
            combined.raise_if_unsuccessful()

    async def _loop(self) -> None:
        try:
            while self._running:
                await self.run_once()
                await asyncio.sleep(self._interval_s)
        except asyncio.CancelledError:
            return

    async def run_once(self, *, now: datetime | None = None) -> list[HousekeepingAction]:
        actions = self.plan_actions(now=now)
        if self._dry_run:
            return actions
        for index, action in enumerate(actions):
            await self._run_owned_executor(self._apply, action)
            if not self._executor_admission_open and index + 1 < len(actions):
                raise RuntimeError("housekeeping stopped before all planned actions were applied")
        return actions

    async def _run_owned_executor[ExecutorResult](
        self,
        function: Callable[..., ExecutorResult],
        /,
        *args: Any,
    ) -> ExecutorResult:
        if not self._executor_admission_open:
            raise RuntimeError("housekeeping is stopping; new executor work is rejected")
        loop = asyncio.get_running_loop()
        operation = loop.run_in_executor(None, function, *args)
        owner = asyncio.create_task(
            _settle_executor_operation(operation),
            name="housekeeping-executor-owner",
        )
        self._executor_futures.add(owner)
        try:
            return await _await_executor_owner(owner)
        finally:
            if owner.done():
                self._executor_futures.discard(owner)

    def plan_actions(self, *, now: datetime | None = None) -> list[HousekeepingAction]:
        current = now or datetime.now(UTC)
        protected_db_names = self._linked_db_names()
        actions: list[HousekeepingAction] = []

        # F1a: skip daily-DB compression entirely when cold rotation owns the
        # lifecycle — otherwise the .gz starves rotation. The delete-compressed
        # sweep below still runs (cleans legacy .gz by its own age).
        if not self._skip_daily_db_compression:
            for db_path in sorted(self._data_dir.glob("data_????-??-??.db")):
                if db_path.name in protected_db_names:
                    continue
                age_days = (current - datetime.fromtimestamp(db_path.stat().st_mtime, tz=UTC)).days
                if age_days >= self._compress_after_days:
                    target = db_path.with_suffix(db_path.suffix + ".gz")
                    if not target.exists():
                        actions.append(HousekeepingAction("compress_db", db_path, target))

        for gz_path in sorted(self._data_dir.glob("data_????-??-??.db.gz")):
            original_name = gz_path.name.removesuffix(".gz")
            if original_name in protected_db_names:
                continue
            age_days = (current - datetime.fromtimestamp(gz_path.stat().st_mtime, tz=UTC)).days
            if age_days >= self._delete_after_days:
                actions.append(HousekeepingAction("delete_compressed_db", gz_path))

        return actions

    def _linked_db_names(self) -> set[str]:
        names: set[str] = set()
        if not self._artifacts_dir.exists():
            return names
        for metadata_path in self._artifacts_dir.glob("*/metadata.json"):
            try:
                payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for item in payload.get("data_range", {}).get("daily_db_files", []):
                names.add(str(item))
        return names

    @staticmethod
    def _apply(action: HousekeepingAction) -> None:
        if action.action == "compress_db":
            assert action.target is not None
            with action.source.open("rb") as src, gzip.open(action.target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            action.source.unlink()
            return
        if action.action == "delete_compressed_db":
            action.source.unlink(missing_ok=True)
            return
        raise ValueError(f"Unsupported housekeeping action '{action.action}'")
