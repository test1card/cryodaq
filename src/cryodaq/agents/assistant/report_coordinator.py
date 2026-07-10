"""Lightweight automatic experiment-report reconciliation.

Terminal experiment metadata is the durable work request.  The cursor only
accelerates a lexical sweep, and a persistent kernel lock elects the one
process allowed to schedule automatic render children.
"""

from __future__ import annotations

import asyncio
import bisect
import contextlib
import hashlib
import json
import logging
import math
import random
import secrets
import time
from collections import deque
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from cryodaq.core.atomic_write import atomic_write_text
from cryodaq.instance_lock import release_lock, try_acquire_lock
from cryodaq.report_process import ReportProcessError, ReportProcessRunner
from cryodaq.report_state import (
    ReportContractError,
    ReportIOError,
    automatic_report_eligible,
    compute_source_fingerprint,
    experiment_lock_name,
    load_active_experiment_id,
    load_current_manifest,
    load_report_state,
    new_pending_state,
    new_running_state,
    terminal_state,
    validate_experiment_id,
    write_report_state,
)

logger = logging.getLogger("cryodaq.assistant.report_coordinator")

_TERMINAL_EVENTS = frozenset(
    {"experiment_finalize", "experiment_stop", "experiment_abort"}
)
_CURSOR_SCHEMA = 1
_CURSOR_MAX_BYTES = 4_096
_CONFIG_MAX_BYTES = 64 * 1024
_FUTURE_SKEW_S = 300.0
_COORDINATOR_LOCK = ".report-locks/coordinator.lock"


def _number(value: object, *, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a number")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError(f"{field} is outside {minimum}..{maximum}")
    return result


def _integer(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} is outside {minimum}..{maximum}")
    return value


def _boolean(value: object, *, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a boolean")
    return value


@dataclass(frozen=True, slots=True)
class ReportCoordinatorConfig:
    automatic_enabled: bool = True
    batch_size: int = 32
    scan_interval_s: float = 30.0
    child_timeout_s: float = 180.0
    max_attempts: int = 5
    base_backoff_s: float = 30.0
    max_backoff_s: float = 3_600.0
    jitter_fraction: float = 0.2

    def __post_init__(self) -> None:
        _boolean(self.automatic_enabled, field="automatic_enabled")
        _integer(self.batch_size, field="scan_batch_size", minimum=1, maximum=256)
        _number(self.scan_interval_s, field="reconcile_interval_s", minimum=5, maximum=3_600)
        _number(self.child_timeout_s, field="automatic_timeout_s", minimum=5, maximum=3_600)
        _integer(self.max_attempts, field="max_attempts", minimum=1, maximum=20)
        base = _number(self.base_backoff_s, field="backoff_base_s", minimum=1, maximum=3_600)
        _number(self.max_backoff_s, field="backoff_cap_s", minimum=base, maximum=86_400)
        _number(self.jitter_fraction, field="jitter_fraction", minimum=0, maximum=1)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> ReportCoordinatorConfig:
        """Parse canonical config fields strictly, defaulting each invalid field."""
        raw = dict(payload or {})
        aliases = {
            "scan_batch_size": "batch_size",
            "reconcile_interval_s": "scan_interval_s",
            "automatic_timeout_s": "child_timeout_s",
            "backoff_base_s": "base_backoff_s",
            "backoff_cap_s": "max_backoff_s",
        }
        for source, target in aliases.items():
            if source in raw:
                raw[target] = raw[source]
        defaults = cls()
        values: dict[str, Any] = {}
        validators = {
            "automatic_enabled": lambda value: _boolean(value, field="automatic_enabled"),
            "batch_size": lambda value: _integer(
                value, field="scan_batch_size", minimum=1, maximum=256
            ),
            "scan_interval_s": lambda value: _number(
                value, field="reconcile_interval_s", minimum=5, maximum=3_600
            ),
            "child_timeout_s": lambda value: _number(
                value, field="automatic_timeout_s", minimum=5, maximum=3_600
            ),
            "max_attempts": lambda value: _integer(
                value, field="max_attempts", minimum=1, maximum=20
            ),
            "base_backoff_s": lambda value: _number(
                value, field="backoff_base_s", minimum=1, maximum=3_600
            ),
            "max_backoff_s": lambda value: _number(
                value, field="backoff_cap_s", minimum=1, maximum=86_400
            ),
            "jitter_fraction": lambda value: _number(
                value, field="jitter_fraction", minimum=0, maximum=1
            ),
        }
        for field, validator in validators.items():
            if field not in raw:
                continue
            try:
                values[field] = validator(raw[field])
            except ValueError as exc:
                logger.warning("Invalid reporting setting %s; using default: %s", field, exc)
                values[field] = getattr(defaults, field)
        if values.get("max_backoff_s", defaults.max_backoff_s) < values.get(
            "base_backoff_s", defaults.base_backoff_s
        ):
            logger.warning("backoff_cap_s is below backoff_base_s; using default cap")
            values["max_backoff_s"] = defaults.max_backoff_s
        return cls(**values)


def _read_yaml_mapping(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        stat = path.stat()
        if stat.st_size > _CONFIG_MAX_BYTES:
            raise ValueError("configuration file is oversized")
        if stat.st_mtime > time.time() + _FUTURE_SKEW_S:
            raise ValueError("configuration file timestamp is in the future")
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError("configuration root must be a mapping")
        return payload
    except Exception as exc:
        logger.warning("Ignoring invalid reporting config %s: %s", path, exc)
        return None


def load_report_coordinator_config(
    config_dir: Path,
    *,
    automatic_allowed: bool = True,
) -> ReportCoordinatorConfig:
    """Load reporting settings with normal-mode-on and replay-mode-off defaults."""
    merged: dict[str, Any] = {}
    for path in (Path(config_dir) / "agent.yaml", Path(config_dir) / "reporting.yaml"):
        payload = _read_yaml_mapping(path)
        if payload is None:
            continue
        section = payload.get("reporting", payload if path.name == "reporting.yaml" else {})
        if isinstance(section, dict):
            merged.update(section)
        elif section:
            logger.warning("Ignoring non-mapping reporting section in %s", path)
    config = ReportCoordinatorConfig.from_mapping(merged)
    return config if automatic_allowed else replace(config, automatic_enabled=False)


class ReportCoordinator:
    """Reconcile terminal experiments without blocking the assistant loop."""

    def __init__(
        self,
        data_dir: Path,
        *,
        config: ReportCoordinatorConfig | None = None,
        runner: Any | None = None,
        event_addr: str | None = None,
        random_fn=random.random,
    ) -> None:
        self._data_dir = Path(data_dir).resolve()
        self._config = config or ReportCoordinatorConfig()
        self._runner = runner or ReportProcessRunner(
            self._data_dir,
            timeout_s=self._config.child_timeout_s,
        )
        self._event_addr = event_addr
        self._random = random_fn
        self._priority_ids: deque[str] = deque()
        self._priority_set: set[str] = set()
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._semaphore = asyncio.Semaphore(1)
        self._task: asyncio.Task[None] | None = None
        self._subscriber: Any | None = None
        self._leadership_fd: int | None = None
        self._fallback_cursor: str | None = None
        self._cursor_disk_degraded = False

    @property
    def is_leader(self) -> bool:
        return self._leadership_fd is not None

    async def start(self) -> None:
        if not self._config.automatic_enabled or self._task is not None:
            return
        self._stop.clear()
        if self._event_addr is not None:
            from cryodaq.core.zmq_bridge import ZMQEventSubscriber

            self._subscriber = ZMQEventSubscriber(self._event_addr, callback=self._on_event)
            await self._subscriber.start()
        self._task = asyncio.create_task(self._run(), name="automatic_report_coordinator")

    async def wait(self) -> None:
        """Wait for the critical coordinator task and reject silent termination."""
        task = self._task
        if task is None:
            if self._config.automatic_enabled:
                raise RuntimeError("automatic report coordinator was not started")
            return
        await task
        if not self._stop.is_set():
            raise RuntimeError("automatic report coordinator stopped unexpectedly")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._subscriber is not None:
            await self._subscriber.stop()
            self._subscriber = None
        self._release_leadership()

    async def _on_event(self, event: dict[str, Any]) -> None:
        if str(event.get("event_type", "")) in _TERMINAL_EVENTS:
            self.notify_terminal(event.get("experiment_id"))

    def notify_terminal(self, experiment_id: object = None) -> None:
        """Treat PUB as a bounded wakeup only; durable metadata remains truth."""
        if isinstance(experiment_id, str):
            try:
                validated = validate_experiment_id(experiment_id)
            except ReportContractError:
                validated = ""
            if validated and validated not in self._priority_set:
                if len(self._priority_ids) >= 1_024:
                    removed = self._priority_ids.pop()
                    self._priority_set.discard(removed)
                self._priority_ids.appendleft(validated)
                self._priority_set.add(validated)
        self._wake.set()

    async def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                await self.reconcile_once()
            except Exception:
                logger.exception("Automatic report reconciliation pass failed")
            if self._wake.is_set():
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._config.scan_interval_s)
            except TimeoutError:
                pass

    def _ensure_leader(self) -> bool:
        if self._leadership_fd is not None:
            return True
        self._leadership_fd = try_acquire_lock(_COORDINATOR_LOCK, lock_dir=self._data_dir)
        return self._leadership_fd is not None

    def _release_leadership(self) -> None:
        if self._leadership_fd is None:
            return
        release_lock(
            self._leadership_fd,
            _COORDINATOR_LOCK,
            unlink=False,
            lock_dir=self._data_dir,
        )
        self._leadership_fd = None

    async def reconcile_once(self) -> None:
        if not await asyncio.to_thread(self._ensure_leader):
            return
        roots = await asyncio.to_thread(self._next_batch)
        for root in roots:
            await self._reconcile_experiment(root)

    @property
    def _cursor_path(self) -> Path:
        return self._data_dir / "reporting" / "reconcile_cursor.json"

    def _validated_cursor_path(self, *, create_parent: bool) -> Path:
        directory = self._data_dir / "reporting"
        if directory.is_symlink():
            raise ReportContractError("reporting state directory must not be a symlink")
        if create_parent:
            directory.mkdir(parents=False, exist_ok=True)
        if directory.exists() and (
            not directory.is_dir() or directory.resolve().parent != self._data_dir
        ):
            raise ReportContractError("reporting state directory escapes the data root")
        path = directory / "reconcile_cursor.json"
        if path.is_symlink():
            raise ReportContractError("reconciliation cursor must not be a symlink")
        return path

    def _load_cursor(self) -> str | None:
        if self._cursor_disk_degraded:
            return self._fallback_cursor
        path = self._cursor_path
        try:
            path = self._validated_cursor_path(create_parent=False)
            if not path.exists():
                return self._fallback_cursor
            if path.is_symlink() or not path.is_file():
                raise ValueError("cursor must be a regular file")
            stat = path.stat()
            if stat.st_size > _CURSOR_MAX_BYTES:
                raise ValueError("cursor is oversized")
            if stat.st_mtime > time.time() + _FUTURE_SKEW_S:
                raise ValueError("cursor timestamp is in the future")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != {
                "schema",
                "last_experiment_id",
                "updated_at",
            }:
                raise ValueError("cursor schema is invalid")
            if type(payload["schema"]) is not int or payload["schema"] != _CURSOR_SCHEMA:
                raise ValueError("cursor schema version is unsupported")
            updated_at = _number(
                payload["updated_at"], field="cursor.updated_at", minimum=0, maximum=time.time() + _FUTURE_SKEW_S
            )
            del updated_at
            last_id = payload["last_experiment_id"]
            if last_id is None:
                self._fallback_cursor = None
                return None
            self._fallback_cursor = validate_experiment_id(last_id)
            return self._fallback_cursor
        except Exception as exc:
            logger.warning("Ignoring unsafe reconciliation cursor %s: %s", path, exc)
            return self._fallback_cursor

    def _write_cursor(self, last_experiment_id: str | None) -> None:
        if last_experiment_id is not None:
            validate_experiment_id(last_experiment_id)
        self._fallback_cursor = last_experiment_id
        payload = {
            "schema": _CURSOR_SCHEMA,
            "last_experiment_id": last_experiment_id,
            "updated_at": time.time(),
        }
        try:
            atomic_write_text(
                self._validated_cursor_path(create_parent=True),
                json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
            )
            self._cursor_disk_degraded = False
        except (OSError, ReportContractError) as exc:
            self._cursor_disk_degraded = True
            logger.warning("Cursor persistence unavailable; using in-memory sweep: %s", exc)

    def _active_experiment_id(self) -> tuple[bool, str | None]:
        try:
            return True, load_active_experiment_id(self._data_dir)
        except Exception as exc:
            logger.error("Cannot safely read active experiment state: %s", exc)
            return False, None

    def _safe_experiment_names(self) -> list[str]:
        experiments = self._data_dir / "experiments"
        if experiments.is_symlink() or not experiments.is_dir():
            return []
        root = experiments.resolve()
        names: list[str] = []
        try:
            entries = list(experiments.iterdir())
        except OSError:
            return []
        for entry in entries:
            try:
                validate_experiment_id(entry.name)
                if entry.is_symlink() or not entry.is_dir() or entry.resolve().parent != root:
                    continue
                names.append(entry.name)
            except (OSError, ReportContractError):
                continue
        return sorted(names)

    def _eligible_root(self, experiment_id: str, active_id: str | None) -> Path | None:
        if experiment_id == active_id:
            return None
        root = self._data_dir / "experiments" / experiment_id
        try:
            validate_experiment_id(experiment_id)
            experiments = self._data_dir / "experiments"
            if experiments.is_symlink() or root.is_symlink() or not root.is_dir():
                return None
            resolved_experiments = experiments.resolve()
            resolved_root = root.resolve()
            if resolved_root.parent != resolved_experiments:
                return None
            if not automatic_report_eligible(
                resolved_root,
                active_experiment_id=active_id,
            ):
                return None
            return resolved_root
        except ReportIOError:
            logger.warning("Transiently unable to read experiment metadata for %s", experiment_id)
            return None
        except ReportContractError as exc:
            logger.warning("Ignoring invalid experiment metadata for %s", experiment_id)
            self._record_permanent_contract_failure(root, exc)
            return None
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            logger.warning("Transiently unable to inspect experiment metadata for %s", experiment_id)
            return None

    def _next_batch(self) -> list[Path]:
        """Process event IDs first while reserving a persistent lexical slot."""
        state_known, active_id = self._active_experiment_id()
        if not state_known:
            return []
        names = self._safe_experiment_names()
        if not names:
            self._write_cursor(None)
            return []

        batch: list[Path] = []
        priority_limit = max(0, self._config.batch_size - 1)
        while self._priority_ids and len(batch) < priority_limit:
            experiment_id = self._priority_ids.popleft()
            self._priority_set.discard(experiment_id)
            root = self._eligible_root(experiment_id, active_id)
            if root is not None and root not in batch:
                batch.append(root)

        cursor = self._load_cursor()
        start = bisect.bisect_right(names, cursor) if cursor is not None else 0
        if start >= len(names):
            start = 0
        remaining = max(1, self._config.batch_size - len(batch))
        visited = names[start : start + remaining]
        if not visited:
            visited = names[:remaining]
        reached_end = bool(visited) and names.index(visited[-1]) == len(names) - 1
        self._write_cursor(None if reached_end else visited[-1] if visited else cursor)
        for experiment_id in visited:
            root = self._eligible_root(experiment_id, active_id)
            if root is not None and root not in batch:
                batch.append(root)
        return batch[: self._config.batch_size]

    async def _reconcile_experiment(self, experiment_root: Path) -> None:
        fingerprint: str | None = None
        try:
            state_known, active_id = await asyncio.to_thread(self._active_experiment_id)
            if not state_known or experiment_root.name == active_id:
                return
            fingerprint = await asyncio.to_thread(compute_source_fingerprint, experiment_root)
            try:
                manifest = await asyncio.to_thread(load_current_manifest, experiment_root)
            except ReportIOError as exc:
                logger.warning("Current report manifest is temporarily unreadable: %s", exc)
                return
            except ReportContractError:
                logger.warning("Current report manifest is invalid: %s", experiment_root)
                manifest = None
            if manifest is not None and manifest["source_fingerprint"] == fingerprint:
                await asyncio.to_thread(
                    self._record_manifest_success, experiment_root, fingerprint, manifest
                )
                return
            if not await asyncio.to_thread(
                self._needs_render, experiment_root, fingerprint, time.time()
            ):
                return
            if not await asyncio.to_thread(self._prepare_pending, experiment_root, fingerprint):
                return
            async with self._semaphore:
                try:
                    await asyncio.to_thread(
                        self._runner.generate_experiment,
                        experiment_root.name,
                        automatic=True,
                    )
                except ReportProcessError as exc:
                    expected = str(exc).split(":", 1)[0] in {
                        "busy",
                        "poisoned",
                        "backoff",
                        "running",
                        "already_current",
                        "ineligible",
                    }
                    if not expected:
                        await asyncio.to_thread(
                            self._record_failure_backoff,
                            experiment_root,
                            fingerprint,
                            str(exc),
                        )
                    logger.warning(
                        "Automatic report attempt failed for %s: %s", experiment_root.name, exc
                    )
        except ReportIOError as exc:
            logger.warning("Automatic report state/source is temporarily unreadable: %s", exc)
        except ReportContractError as exc:
            logger.error("Automatic report contract failure for %s: %s", experiment_root, exc)
            await asyncio.to_thread(
                self._record_permanent_contract_failure,
                experiment_root,
                exc,
                fingerprint,
            )
        except Exception:
            logger.exception("Automatic report reconciliation failed for %s", experiment_root)

    def _needs_render(self, experiment_root: Path, fingerprint: str, now: float) -> bool:
        state = load_report_state(experiment_root)
        if state is None or state["source_fingerprint"] != fingerprint:
            return True
        if state["status"] == "RUNNING":
            return True
        if state["status"] == "FAILED":
            if int(state["attempt_count"]) >= min(
                int(state["max_attempts"]), self._config.max_attempts
            ):
                return False
            return now >= float(state["not_before"])
        if state["status"] == "PENDING":
            return now >= float(state["not_before"])
        return True

    def _record_permanent_contract_failure(
        self,
        experiment_root: Path,
        error: BaseException,
        source_fingerprint: str | None = None,
    ) -> None:
        """Persist one bounded poison record for a safe experiment directory."""
        try:
            experiment_id = validate_experiment_id(experiment_root.name)
            experiments = (self._data_dir / "experiments").resolve()
            root = Path(experiment_root).resolve()
            if root.parent != experiments or Path(experiment_root).is_symlink():
                return
            lock_name = experiment_lock_name(experiment_id)
            fd = try_acquire_lock(lock_name, lock_dir=self._data_dir)
            if fd is None:
                return
            try:
                text = f"{type(error).__name__}:{error}"[:2_048]
                fingerprint = source_fingerprint or (
                    "sha256:"
                    + hashlib.sha256(f"contract:{experiment_id}:{text}".encode()).hexdigest()
                )
                try:
                    state = load_report_state(root)
                except ReportContractError:
                    logger.error(
                        "Preserving invalid report_state.json for explicit operator repair: %s",
                        root,
                    )
                    return
                if (
                    state is not None
                    and state["status"] == "FAILED"
                    and state["source_fingerprint"] == fingerprint
                    and state["error_code"] == "permanent_contract_failure"
                ):
                    return
                owner = secrets.token_hex(16)
                running = new_running_state(
                    experiment_id,
                    fingerprint,
                    secrets.token_hex(16),
                    owner,
                    attempt_count=self._config.max_attempts,
                    max_attempts=self._config.max_attempts,
                )
                failed = terminal_state(
                    running,
                    owner_token=owner,
                    succeeded=False,
                    error_code="permanent_contract_failure",
                    error_text=text,
                )
                write_report_state(root, failed)
            finally:
                release_lock(fd, lock_name, unlink=False, lock_dir=self._data_dir)
        except Exception:
            logger.exception("Could not persist permanent report contract failure")

    def _prepare_pending(self, experiment_root: Path, fingerprint: str) -> bool:
        lock_name = experiment_lock_name(experiment_root.name)
        fd = try_acquire_lock(lock_name, lock_dir=self._data_dir)
        if fd is None:
            return False
        try:
            active_id = load_active_experiment_id(self._data_dir)
            if not automatic_report_eligible(
                experiment_root,
                active_experiment_id=active_id,
            ):
                return False
            if compute_source_fingerprint(experiment_root) != fingerprint:
                return False
            state = load_report_state(experiment_root)
            if state is not None and state["source_fingerprint"] == fingerprint:
                return True
            pending = new_pending_state(
                experiment_root.name,
                fingerprint,
                secrets.token_hex(16),
                secrets.token_hex(16),
                max_attempts=self._config.max_attempts,
            )
            write_report_state(experiment_root, pending)
            return True
        finally:
            release_lock(fd, lock_name, unlink=False, lock_dir=self._data_dir)

    def _record_manifest_success(
        self,
        experiment_root: Path,
        fingerprint: str,
        manifest: dict[str, Any],
    ) -> None:
        lock_name = experiment_lock_name(experiment_root.name)
        fd = try_acquire_lock(lock_name, lock_dir=self._data_dir)
        if fd is None:
            return
        try:
            fresh_fingerprint = compute_source_fingerprint(experiment_root)
            try:
                fresh_manifest = load_current_manifest(experiment_root)
            except ReportIOError as exc:
                logger.warning("Current report manifest is temporarily unreadable: %s", exc)
                return
            except ReportContractError:
                logger.warning(
                    "Current report manifest became invalid during locked repair: %s",
                    experiment_root,
                )
                return
            if (
                fresh_fingerprint != fingerprint
                or fresh_manifest is None
                or fresh_manifest["source_fingerprint"] != fresh_fingerprint
                or fresh_manifest["generation_id"] != manifest["generation_id"]
            ):
                return
            manifest = fresh_manifest
            state = load_report_state(experiment_root)
            generation_id = str(manifest["generation_id"])
            if (
                state is not None
                and state["status"] == "SUCCEEDED"
                and state["source_fingerprint"] == fingerprint
                and state["generation_id"] == generation_id
            ):
                return
            owner_token = secrets.token_hex(16)
            attempt_count = max(1, int(state["attempt_count"])) if state is not None else 1
            max_attempts = int(state["max_attempts"]) if state else self._config.max_attempts
            running = new_running_state(
                experiment_root.name,
                fingerprint,
                generation_id,
                owner_token,
                attempt_count=attempt_count,
                max_attempts=max_attempts,
            )
            succeeded = terminal_state(
                running,
                owner_token=owner_token,
                succeeded=True,
                artifacts={
                    "generation_id": generation_id,
                    "generation_dir": f"reports/generations/{generation_id}",
                    "current_manifest": "reports/current_report.json",
                },
            )
            write_report_state(experiment_root, succeeded)
        finally:
            release_lock(fd, lock_name, unlink=False, lock_dir=self._data_dir)

    def _record_failure_backoff(
        self,
        experiment_root: Path,
        fingerprint: str,
        error_text: str,
    ) -> None:
        lock_name = experiment_lock_name(experiment_root.name)
        fd = try_acquire_lock(lock_name, lock_dir=self._data_dir)
        if fd is None:
            return
        try:
            state = load_report_state(experiment_root)
            if state is None or state["source_fingerprint"] != fingerprint:
                return
            if state["status"] == "RUNNING":
                return
            persisted_status = state["status"]
            if state["status"] == "PENDING":
                state["attempt_count"] = 1
                state["status"] = "FAILED"
                state["finished_at"] = time.time()
            if state["status"] != "FAILED":
                return
            attempt = max(1, int(state["attempt_count"]))
            state["max_attempts"] = self._config.max_attempts
            delay = min(
                self._config.max_backoff_s,
                self._config.base_backoff_s * (2 ** (attempt - 1)),
            )
            jitter = 1 + self._config.jitter_fraction * (2 * self._random() - 1)
            now = time.time()
            state["not_before"] = now + max(0.0, delay * jitter)
            state["updated_at"] = now
            state["error_code"] = state.get("error_code") or "automatic_render_failed"
            state["error_text"] = (state.get("error_text") or error_text)[:2_048]
            write_report_state(
                experiment_root,
                state,
                expected_owner_token=state["owner_token"],
                expected_generation_id=state["generation_id"],
                expected_status=persisted_status,
            )
        finally:
            release_lock(fd, lock_name, unlink=False, lock_dir=self._data_dir)
