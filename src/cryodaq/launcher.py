"""Единая точка входа CryoDAQ для оператора.

Запуск:
    cryodaq                     # через entry point
    pythonw -m cryodaq.launcher # без окна терминала

Автоматически запускает engine как подпроцесс, показывает GUI,
управляет жизненным циклом системы. Оператору достаточно
дважды кликнуть по ярлыку на рабочем столе.
"""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import logging.handlers
import math
import os
import re
import signal
import stat as stat_module
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import IO, Any

from PySide6.QtCore import QTimer, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.descriptor_transport import DescriptorQualifiedReading
from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2 as MainWindow
from cryodaq.gui.state.operator_snapshot_ingress import start_operator_snapshot_ingress
from cryodaq.gui.tray_status import TrayLevel, resolve_tray_status, tray_icon_for_level
from cryodaq.gui.zmq_client import ZmqBridge, ZmqCommandWorker, set_bridge
from cryodaq.instance_lock import release_lock_exact, try_acquire_lock

logger = logging.getLogger("cryodaq.launcher")

# Порт ZMQ — для проверки, запущен ли уже engine
_ZMQ_PORT = 5555
_WEB_PORT = 8080
_PERIODIC_HEALTH_DEADLINE_S = 90.0
_PERIODIC_HEALTH_FUTURE_SKEW_S = 300.0
_PERIODIC_CONFIG_REJECTED_CODE = "H3_CONFIG_REJECTED"
_PERIODIC_HEALTH_READ_FAILED_CODE = "H3_HEALTH_READ_FAILED"
_PERIODIC_RUNTIME_UNAVAILABLE_CODE = "H3_RUNTIME_UNAVAILABLE"
_SHUTDOWN_RETRY_DELAYS_MS = (1_000, 3_000, 10_000, 30_000)


class _ShutdownPhase(Enum):
    """Monotonic launcher shutdown phases."""

    RUNNING = auto()
    QUIESCING = auto()
    SETTLING = auto()
    RETRY_WAIT = auto()
    FINALIZING = auto()
    COMPLETE = auto()


@dataclass(slots=True)
class _PeriodicHealthObservation:
    """Local observation clock for the domain-wide H3 health heartbeat."""

    started_at: float
    baseline_observed: bool = False
    high_water_updated_at: float | None = None
    last_observed_updated_at: float | None = None
    last_ready_observed_at: float | None = None

    def observe(
        self,
        *,
        status: str | None,
        updated_at: float | None,
        monotonic_now: float,
        wall_now: float,
    ) -> bool:
        observable_timestamp = isinstance(updated_at, float) and math.isfinite(updated_at) and updated_at >= 0.0
        unchanged_timestamp = bool(
            observable_timestamp
            and self.last_observed_updated_at is not None
            and updated_at == self.last_observed_updated_at
        )
        if observable_timestamp:
            self.last_observed_updated_at = updated_at
        valid = (
            isinstance(status, str) and observable_timestamp and updated_at <= wall_now + _PERIODIC_HEALTH_FUTURE_SKEW_S
        )
        if unchanged_timestamp:
            return False
        if not self.baseline_observed:
            if valid:
                self.baseline_observed = True
                self.high_water_updated_at = updated_at
            return False
        if not valid:
            return False
        if self.high_water_updated_at is not None and updated_at <= self.high_water_updated_at:
            return False
        self.high_water_updated_at = updated_at
        if status != "ready":
            return False
        self.last_ready_observed_at = monotonic_now
        return True

    def deadline_expired(self, monotonic_now: float) -> bool:
        anchor = self.started_at if self.last_ready_observed_at is None else self.last_ready_observed_at
        return monotonic_now - anchor >= _PERIODIC_HEALTH_DEADLINE_S


def _assistant_runtime_decision(*, experiment_mode: bool = True) -> tuple[bool, bool]:
    """Return ``(assistant_required, periodic_requested)`` without secrets."""

    import yaml

    from cryodaq.paths import get_config_dir

    config_dir = get_config_dir()
    llm_enabled = False
    automatic_enabled = bool(experiment_mode)
    agent_cfg_path = config_dir / "agent.yaml"
    if agent_cfg_path.is_file() and not agent_cfg_path.is_symlink():
        try:
            stat = agent_cfg_path.stat()
            if stat.st_size > 64 * 1024 or stat.st_mtime > time.time() + 300:
                raise ValueError("agent config is oversized or future-dated")
            raw = yaml.safe_load(agent_cfg_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError("agent config root must be a mapping")
            section = raw.get("agent", raw.get("gemma", {}))
            if isinstance(section, dict):
                enabled = section.get("enabled", True)
                if type(enabled) is bool:
                    llm_enabled = enabled
                else:
                    logger.warning("agent.enabled must be a boolean; disabling optional LLM")
            reporting = raw.get("reporting", {})
            if experiment_mode and isinstance(reporting, dict) and "automatic_enabled" in reporting:
                enabled = reporting["automatic_enabled"]
                if type(enabled) is bool:
                    automatic_enabled = enabled
                else:
                    logger.warning("reporting.automatic_enabled must be a boolean; using normal-mode default")
        except Exception:
            logger.warning("agent.yaml parse failed; preserving automatic reporting", exc_info=True)

    reporting_path = config_dir / "reporting.yaml"
    if experiment_mode and reporting_path.is_file() and not reporting_path.is_symlink():
        try:
            stat = reporting_path.stat()
            if stat.st_size > 64 * 1024 or stat.st_mtime > time.time() + 300:
                raise ValueError("reporting config is oversized or future-dated")
            raw = yaml.safe_load(reporting_path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError("reporting config root must be a mapping")
            reporting = raw.get("reporting", raw)
            if isinstance(reporting, dict) and "automatic_enabled" in reporting:
                enabled = reporting["automatic_enabled"]
                if type(enabled) is bool:
                    automatic_enabled = enabled
                else:
                    logger.warning("reporting.automatic_enabled must be a boolean; preserving current default")
        except Exception:
            logger.warning("reporting.yaml parse failed; preserving automatic reporting", exc_info=True)
    periodic_requested = False
    if experiment_mode:
        from cryodaq.periodic_config import probe_periodic_png

        try:
            probe = probe_periodic_png(config_dir)
            periodic_requested = probe.requested
            rejected = probe.error_code is not None
        except Exception:
            rejected = True
        if rejected:
            logger.warning("Periodic PNG request ignored: %s", _PERIODIC_CONFIG_REJECTED_CODE)
    return llm_enabled or automatic_enabled or periodic_requested, periodic_requested


def _assistant_runtime_required(*, experiment_mode: bool = True) -> bool:
    """Whether LLM, H2, or requested live H3 needs the assistant child."""

    return _assistant_runtime_decision(experiment_mode=experiment_mode)[0]


# Settings → Тема menu: curated display order. Dark group first, then
# a visual separator, then light group. Packs not listed here fall
# through to a trailing alphabetical extras block — keeps the menu
# forward-compatible with locally-dropped dev packs without a code
# edit. See docs/design-system/HANDOFF_THEMES_V2.md for the rationale.
#
# Classification is empirical (BACKGROUND luminance > 0.5 → light) —
# the handoff doc groups warm_stone / ochre_bloom / taupe_quiet /
# rose_dusk as "light" but their BG hexes are all dark. Only
# gost / xcode / braun are actual light substrates.
_THEME_DISPLAY_ORDER: tuple[str, ...] = (
    # Dark
    "default_cool",
    "warm_stone",
    "anthropic_mono",
    "ochre_bloom",
    "taupe_quiet",
    "rose_dusk",
    "signal",
    "instrument",
    "amber",
    # Light (ADR 001 shifted-L STATUS set)
    "gost",
    "xcode",
    "braun",
)
_LIGHT_THEME_IDS: frozenset[str] = frozenset({"gost", "xcode", "braun"})

# Флаги создания процесса без окна (Windows)
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0
_WINDOWS_CREATE_NO_WINDOW = 0x08000000
_ASSISTANT_SHUTDOWN_ENV = "CRYODAQ_ASSISTANT_SHUTDOWN_FILE"
_ASSISTANT_SHUTDOWN_PREFIX = "assistant-shutdown-"
_SOAK_BRIDGE_FD_ENV = "CRYODAQ_SOAK_BRIDGE_FD"
_SOAK_BRIDGE_NONCE_ENV = "CRYODAQ_SOAK_BRIDGE_NONCE"
_SOAK_ARTIFACT_FD_ENV = "CRYODAQ_SOAK_ARTIFACT_FD"
_SOAK_ARTIFACT_NONCE_ENV = "CRYODAQ_SOAK_ARTIFACT_NONCE"
_SOAK_ASSISTANT_GENERATION_ENV = "CRYODAQ_SOAK_ASSISTANT_GENERATION"
_SOAK_BRIDGE_SCHEMA = "cryodaq.soak.bridge-identity"
_SOAK_BRIDGE_VERSION = 1
_SOAK_BRIDGE_MAX_BYTES = 512
_SOAK_BRIDGE_DATA_SCHEMA = "cryodaq.soak.bridge-data"
_SOAK_BRIDGE_DATA_MIN_INTERVAL_S = 1.0
_SOAK_BRIDGE_ACTIVE_FDS: set[int] = set()
_SOAK_BRIDGE_AT_FORK_REGISTERED = False


def _close_soak_bridge_fds_after_fork() -> None:
    """Remove launcher-only pipe authority from every forked descendant."""

    for fd in tuple(_SOAK_BRIDGE_ACTIVE_FDS):
        try:
            os.close(fd)
        except OSError:
            pass
    _SOAK_BRIDGE_ACTIVE_FDS.clear()


def _guard_soak_bridge_fd_from_descendants(fd: int) -> None:
    """Make *fd* close-on-exec and close it in children of a real fork."""

    global _SOAK_BRIDGE_AT_FORK_REGISTERED
    os.set_inheritable(fd, False)
    if hasattr(os, "register_at_fork") and not _SOAK_BRIDGE_AT_FORK_REGISTERED:
        os.register_at_fork(after_in_child=_close_soak_bridge_fds_after_fork)
        _SOAK_BRIDGE_AT_FORK_REGISTERED = True
    _SOAK_BRIDGE_ACTIVE_FDS.add(fd)


def _close_owned_fd_exact(fd: int, *, label: str) -> None:
    """Close one retained descriptor without ever closing a reused number.

    Python cannot assume that a failed ``close(2)`` left the descriptor open.
    Re-probe its identity: the same object is safe to retry later, ``EBADF``
    proves it is already gone, and a different object must never be touched.
    """

    try:
        before = os.fstat(fd)
    except OSError as exc:
        if exc.errno == errno.EBADF:
            return
        raise RuntimeError(f"{label} descriptor identity could not be read") from exc
    try:
        os.close(fd)
    except OSError as exc:
        try:
            after = os.fstat(fd)
        except OSError as probe_error:
            if probe_error.errno == errno.EBADF:
                logger.warning("%s close reported %s but the descriptor is closed", label, exc)
                return
            raise RuntimeError(f"{label} close outcome is ambiguous") from probe_error
        if os.path.samestat(before, after):
            raise RuntimeError(f"{label} descriptor remained open after close failure") from exc
        logger.critical("%s descriptor number was reused during close; replacement left untouched", label)


@dataclass(slots=True)
class _SoakBridgeHandshake:
    """Runner-owned pathless evidence stream for an isolated POSIX mock launcher."""

    fd: int
    nonce: str
    _closed: bool = False
    _emitted: bool = False
    _data_sequence: int = 0
    _last_data_emit: float = 0.0

    def close(self) -> None:
        if self._closed:
            return
        _close_owned_fd_exact(self.fd, label="soak bridge")
        self._closed = True
        _SOAK_BRIDGE_ACTIVE_FDS.discard(self.fd)

    def emit(self, *, bridge_pid: int | None, restart_count: int) -> None:
        if self._closed or self._emitted:
            raise RuntimeError("soak bridge handshake is already closed or emitted")
        if (
            not isinstance(bridge_pid, int)
            or isinstance(bridge_pid, bool)
            or bridge_pid <= 0
            or bridge_pid == os.getpid()
        ):
            raise RuntimeError("bridge PID unavailable for positive handshake")
        if type(restart_count) is not int or restart_count != 1:
            raise RuntimeError("bridge restarted before positive handshake")
        record = {
            "schema": _SOAK_BRIDGE_SCHEMA,
            "version": _SOAK_BRIDGE_VERSION,
            "nonce": self.nonce,
            "launcher_pid": os.getpid(),
            "bridge_pid": bridge_pid,
            "restart_count": restart_count,
        }
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
        if len(payload) > _SOAK_BRIDGE_MAX_BYTES:
            raise RuntimeError("soak bridge handshake exceeds its bound")
        written = os.write(self.fd, payload)
        if written != len(payload):
            raise RuntimeError("soak bridge handshake write did not complete atomically")
        self._emitted = True

    def emit_data_observed(self, *, bridge_pid: int | None, restart_count: int) -> bool:
        """Best-effort bounded fact that the launcher consumed bridge data.

        The inherited pipe is nonblocking.  Backpressure drops this advisory
        fact instead of stalling the GUI thread; the runner requires a later
        sequence after fault injection before accepting recovery.
        """

        if self._closed or not self._emitted:
            return False
        if (
            not isinstance(bridge_pid, int)
            or isinstance(bridge_pid, bool)
            or bridge_pid <= 0
            or bridge_pid == os.getpid()
            or type(restart_count) is not int
            or restart_count != 1
        ):
            self.close()
            raise RuntimeError("bridge identity changed after positive handshake")
        now = time.monotonic()
        if now - self._last_data_emit < _SOAK_BRIDGE_DATA_MIN_INTERVAL_S:
            return False
        sequence = self._data_sequence + 1
        record = {
            "schema": _SOAK_BRIDGE_DATA_SCHEMA,
            "version": _SOAK_BRIDGE_VERSION,
            "nonce": self.nonce,
            "launcher_pid": os.getpid(),
            "bridge_pid": bridge_pid,
            "restart_count": restart_count,
            "sequence": sequence,
        }
        payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"
        if len(payload) > _SOAK_BRIDGE_MAX_BYTES:
            self.close()
            raise RuntimeError("soak bridge data fact exceeds its bound")
        try:
            written = os.write(self.fd, payload)
        except BlockingIOError:
            return False
        except OSError:
            self.close()
            return False
        if written != len(payload):
            self.close()
            raise RuntimeError("soak bridge data fact write was partial")
        self._data_sequence = sequence
        self._last_data_emit = now
        return True


def _without_soak_bridge_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Strip launcher-only descriptor authority from every child environment."""

    result = dict(environment)
    result.pop(_SOAK_BRIDGE_FD_ENV, None)
    result.pop(_SOAK_BRIDGE_NONCE_ENV, None)
    result.pop(_SOAK_ARTIFACT_FD_ENV, None)
    result.pop(_SOAK_ARTIFACT_NONCE_ENV, None)
    result.pop(_SOAK_ASSISTANT_GENERATION_ENV, None)
    return result


@dataclass(slots=True)
class _SoakArtifactCapability:
    """Launcher-retained endpoint duplicated only into assistant execs."""

    fd: int
    nonce: str
    generation: int = 0
    _closed: bool = False

    def child_grant(self) -> tuple[int, int, dict[str, str]]:
        if self._closed:
            raise RuntimeError("soak artifact capability is closed")
        candidate = self.generation + 1
        duplicate = os.dup(self.fd)
        os.set_inheritable(duplicate, False)
        return (
            duplicate,
            candidate,
            {
                _SOAK_ARTIFACT_FD_ENV: str(duplicate),
                _SOAK_ARTIFACT_NONCE_ENV: self.nonce,
                _SOAK_ASSISTANT_GENERATION_ENV: str(candidate),
            },
        )

    def commit_generation(self, candidate: int) -> None:
        if type(candidate) is not int or candidate != self.generation + 1:
            raise RuntimeError("assistant generation commit is invalid")
        self.generation = candidate

    def close(self) -> None:
        if self._closed:
            return
        _close_owned_fd_exact(self.fd, label="soak artifact")
        self._closed = True
        _SOAK_BRIDGE_ACTIVE_FDS.discard(self.fd)


def _consume_soak_artifact_capability(
    *,
    bridge_handshake: _SoakBridgeHandshake | None,
    cli_mock: bool,
    tray_only: bool,
    replay_requested: bool,
    setup_wizard: bool,
) -> _SoakArtifactCapability | None:
    raw_fd = os.environ.pop(_SOAK_ARTIFACT_FD_ENV, None)
    nonce = os.environ.pop(_SOAK_ARTIFACT_NONCE_ENV, None)
    hostile_generation = os.environ.pop(_SOAK_ASSISTANT_GENERATION_ENV, None)
    if raw_fd is None and nonce is None and hostile_generation is None:
        return None
    fd = -1
    try:
        if raw_fd is None or nonce is None or hostile_generation is not None:
            raise RuntimeError("partial soak artifact capability environment")
        fd = int(raw_fd, 10)
        if (
            raw_fd != str(fd)
            or bridge_handshake is None
            or os.name != "posix"
            or sys.platform == "win32"
            or getattr(sys, "frozen", False)
            or not cli_mock
            or not tray_only
            or replay_requested
            or setup_wizard
        ):
            raise RuntimeError("soak artifact capability requires the isolated POSIX bridge launch")
        if fd < 3 or not os.get_inheritable(fd) or re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
            raise RuntimeError("invalid soak artifact capability")
        metadata = os.fstat(fd)
        if not stat_module.S_ISSOCK(metadata.st_mode):
            raise RuntimeError("soak artifact descriptor is not a socket")
        import fcntl
        import socket

        if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR:
            raise RuntimeError("soak artifact descriptor is not read/write")
        endpoint = socket.socket(fileno=fd)
        try:
            if (
                endpoint.family != socket.AF_UNIX
                or (endpoint.type & socket.SOCK_STREAM) != socket.SOCK_STREAM
                or endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
            ):
                raise RuntimeError("soak artifact descriptor is not an AF_UNIX stream")
            endpoint.getpeername()
            endpoint.detach()
        finally:
            if endpoint.fileno() >= 0:
                endpoint.close()
        _guard_soak_bridge_fd_from_descendants(fd)
        return _SoakArtifactCapability(fd, nonce)
    except BaseException:
        if fd >= 3:
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def _consume_soak_bridge_handshake(
    *,
    cli_mock: bool,
    tray_only: bool,
    replay_requested: bool,
    setup_wizard: bool,
) -> _SoakBridgeHandshake | None:
    """Consume and validate the private one-shot launcher environment."""

    raw_fd = os.environ.pop(_SOAK_BRIDGE_FD_ENV, None)
    nonce = os.environ.pop(_SOAK_BRIDGE_NONCE_ENV, None)
    if raw_fd is None and nonce is None:
        return None
    if raw_fd is None:
        raise RuntimeError("partial soak bridge handshake environment")
    try:
        fd = int(raw_fd, 10)
    except ValueError as exc:
        raise RuntimeError("invalid soak bridge handshake descriptor") from exc
    try:
        if nonce is None:
            raise RuntimeError("partial soak bridge handshake environment")
        if (
            os.name != "posix"
            or sys.platform == "win32"
            or getattr(sys, "frozen", False)
            or not cli_mock
            or not tray_only
            or replay_requested
            or setup_wizard
        ):
            raise RuntimeError("soak bridge handshake is restricted to POSIX source --mock --tray")
        if re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
            raise RuntimeError("invalid soak bridge handshake nonce")
        if fd < 3 or not os.get_inheritable(fd):
            raise RuntimeError("soak bridge handshake descriptor is not inherited")
        metadata = os.fstat(fd)
        if not stat_module.S_ISFIFO(metadata.st_mode):
            raise RuntimeError("soak bridge handshake descriptor is not a pipe")
        import fcntl

        if fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_WRONLY:
            raise RuntimeError("soak bridge handshake descriptor is not write-only")
        fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) | os.O_NONBLOCK)
        root_text = os.environ.get("CRYODAQ_ROOT")
        if not root_text:
            raise RuntimeError("soak bridge handshake requires isolated CRYODAQ_ROOT")
        root = Path(root_text)
        root_observed = _real_directory_stat(root)
        if not root.is_absolute() or root_observed is None:
            raise RuntimeError("soak bridge handshake root is unsafe")
        resolved_root = root.resolve(strict=True)
        repository_root = Path(__file__).resolve().parents[2]
        if resolved_root == repository_root or resolved_root.is_relative_to(repository_root):
            raise RuntimeError("soak bridge handshake root is not isolated")
        root_stat = resolved_root.stat()
        if (root_observed.st_dev, root_observed.st_ino) != (root_stat.st_dev, root_stat.st_ino):
            raise RuntimeError("soak bridge handshake root identity changed")
        if root_stat.st_uid != os.getuid() or stat_module.S_IMODE(root_stat.st_mode) != 0o700:
            raise RuntimeError("soak bridge handshake root ownership/mode is unsafe")
        _guard_soak_bridge_fd_from_descendants(fd)
        return _SoakBridgeHandshake(fd=fd, nonce=nonce)
    except BaseException:
        if fd >= 3:
            try:
                os.close(fd)
            except OSError:
                pass
        raise


def _real_directory_stat(path: Path) -> os.stat_result | None:
    """Return lstat identity only for a non-link, non-reparse directory."""
    try:
        metadata = path.lstat()
    except OSError:
        return None
    reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    if not (
        stat_module.S_ISDIR(metadata.st_mode)
        and not stat_module.S_ISLNK(metadata.st_mode)
        and not (reparse_flag and file_attributes & reparse_flag)
    ):
        return None
    return metadata


def _is_real_regular_file(path: Path) -> bool:
    """Check the observed path object without following a link/reparse point."""

    try:
        metadata = path.lstat()
    except OSError:
        return False
    return _is_real_single_link_regular_metadata(metadata)


def _is_real_single_link_regular_metadata(metadata: os.stat_result) -> bool:
    """Accept only one ordinary, single-link, non-reparse filesystem object."""

    reparse_flag = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    return bool(
        stat_module.S_ISREG(metadata.st_mode)
        and not stat_module.S_ISLNK(metadata.st_mode)
        and not (reparse_flag and file_attributes & reparse_flag)
        and metadata.st_nlink == 1
    )


def _opened_real_regular_file_matches(path: Path, descriptor: int) -> bool:
    """Bind an opened sentinel descriptor to the exact safe path object."""

    try:
        path_metadata = path.lstat()
        descriptor_metadata = os.fstat(descriptor)
    except OSError:
        return False
    return bool(
        _is_real_single_link_regular_metadata(path_metadata)
        and stat_module.S_ISREG(descriptor_metadata.st_mode)
        and descriptor_metadata.st_nlink == 1
        and os.path.samestat(path_metadata, descriptor_metadata)
    )


@dataclass(frozen=True, slots=True)
class _AssistantShutdownAuthority:
    path: Path
    data_dir: Path
    runtime_dir: Path
    data_identity: os.stat_result
    runtime_identity: os.stat_result

    def directories_match(self) -> bool:
        """Recheck identities; this is not a directory-handle atomic guarantee."""

        data_now = _real_directory_stat(self.data_dir)
        runtime_now = _real_directory_stat(self.runtime_dir)
        if data_now is None or runtime_now is None:
            return False
        return bool(
            self.runtime_dir.parent == self.data_dir
            and self.path.parent == self.runtime_dir
            and os.path.samestat(self.data_identity, data_now)
            and os.path.samestat(self.runtime_identity, runtime_now)
        )


def _new_assistant_shutdown_authority(data_dir: Path) -> _AssistantShutdownAuthority:
    """Return a token path bound to current data/runtime identities.

    Python exposes no portable Windows directory-relative exclusive create, so
    identities are checked around later operations without claiming that every
    rename between individual system calls is eliminated.
    """

    data_root = Path(data_dir)
    if _real_directory_stat(data_root) is None:
        raise RuntimeError("unsafe assistant data directory")
    resolved_data = data_root.resolve(strict=True)
    runtime_dir = data_root / "runtime"
    try:
        runtime_dir.mkdir(mode=0o700)
    except FileExistsError:
        pass
    if _real_directory_stat(runtime_dir) is None:
        raise RuntimeError("unsafe assistant runtime directory")
    resolved_runtime = runtime_dir.resolve(strict=True)
    if resolved_runtime.parent != resolved_data:
        raise RuntimeError("assistant runtime directory escapes data root")
    data_identity = _real_directory_stat(resolved_data)
    runtime_identity = _real_directory_stat(resolved_runtime)
    if data_identity is None or runtime_identity is None:
        raise RuntimeError("unsafe assistant shutdown directory identity")
    shutdown_path = resolved_runtime / f"{_ASSISTANT_SHUTDOWN_PREFIX}{uuid.uuid4().hex}.signal"
    if os.path.lexists(shutdown_path):
        raise RuntimeError("assistant shutdown sentinel already exists")
    authority = _AssistantShutdownAuthority(
        path=shutdown_path,
        data_dir=resolved_data,
        runtime_dir=resolved_runtime,
        data_identity=data_identity,
        runtime_identity=runtime_identity,
    )
    if not authority.directories_match():
        raise RuntimeError("unsafe assistant shutdown directory identity")
    return authority


_ENGINE_STDERR_LOG_NAME = "engine.stderr.log"
_ENGINE_STDERR_MAX_BYTES = 50 * 1024 * 1024
_ENGINE_STDERR_BACKUP_COUNT = 3
_ENGINE_STDERR_LOGGER_NAME = "cryodaq.launcher.engine_stderr"

_REPLAY_LIST_SENTINEL = "__list__"


def _print_replay_sources() -> None:
    """List available replay sources — curves and SQLite files — then return."""
    import json
    from datetime import datetime

    from cryodaq.paths import get_data_dir
    from cryodaq.storage._sqlite import sqlite3

    data_dir = get_data_dir()
    cooldown_dir = data_dir.parent / "cooldown_v5"

    print("\nДоступные источники replay:\n")

    print("Кривые охлаждения (cooldown_v5/):")
    curve_count = 0
    if cooldown_dir.is_dir():
        for json_path in sorted(cooldown_dir.glob("*.json")):
            if json_path.name == "predictor_model.json":
                continue
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                duration = data.get("duration_hours", "?")
                t_cold = data.get("T_cold_final", "?")
                dur_str = f"{duration:.1f}h" if isinstance(duration, (int, float)) else str(duration)
                t_str = f"{t_cold:.1f}K" if isinstance(t_cold, (int, float)) else str(t_cold)
                print(f"  {json_path.name} — длительность {dur_str}, T_cold_final {t_str}")
            except Exception:
                print(f"  {json_path.name} — ошибка чтения")
            curve_count += 1
    if curve_count == 0:
        print("  (нет файлов)")

    print()

    print("Записи SQLite (data/):")
    db_count = 0
    if data_dir.is_dir():
        for db_path in sorted(data_dir.glob("data_*.db")):
            try:
                con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0)
                row = con.execute("SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM readings").fetchone()
                con.close()
                count, ts_min, ts_max = row
                if ts_min and ts_max:
                    fmt = "%Y-%m-%d %H:%M"
                    range_str = (
                        f"{datetime.fromtimestamp(ts_min).strftime(fmt)}"
                        f" — {datetime.fromtimestamp(ts_max).strftime(fmt)}"
                    )
                else:
                    range_str = "нет данных"
                print(f"  {db_path.name} — {count} записей, {range_str}")
            except Exception:
                print(f"  {db_path.name} — ошибка чтения")
            db_count += 1
    if db_count == 0:
        print("  (нет файлов)")

    print("\nУкажите путь:  cryodaq --replay <путь-к-источнику>\n")


def _create_engine_stderr_logger() -> tuple[logging.Logger, logging.Handler, Path]:
    """Build a dedicated rotating logger for forwarded engine stderr lines."""
    from cryodaq.paths import get_logs_dir

    log_path = get_logs_dir() / _ENGINE_STDERR_LOG_NAME
    stderr_logger = logging.getLogger(_ENGINE_STDERR_LOGGER_NAME)
    # Explicitly close and detach any handlers from a prior _start_engine() call
    # so the previous RotatingFileHandler releases its file lock. Plain
    # `handlers = []` relies on GC and breaks on Windows where the file stays
    # locked, blocking rotation across engine restarts.
    for prior in list(stderr_logger.handlers):
        try:
            prior.close()
        except Exception:
            pass
        stderr_logger.removeHandler(prior)
    stderr_logger.setLevel(logging.ERROR)
    stderr_logger.propagate = False

    handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=_ENGINE_STDERR_MAX_BYTES,
        backupCount=_ENGINE_STDERR_BACKUP_COUNT,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s │ %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    stderr_logger.addHandler(handler)
    return stderr_logger, handler, log_path


def _pump_engine_stderr(pipe: IO[bytes], stderr_logger: logging.Logger) -> None:
    """Forward engine stderr bytes into the rotating launcher-managed log."""
    try:
        for raw_line in iter(pipe.readline, b""):
            text = raw_line.decode("utf-8", errors="replace").rstrip()
            if text:
                stderr_logger.error(text)
    finally:
        try:
            pipe.close()
        except Exception:
            pass


def _is_port_busy(port: int) -> bool:
    """Check if engine is listening by probing BOTH PUB and CMD ports."""
    import socket

    for p in (port, port + 1):  # PUB=5555, CMD=5556
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.0)
            result = s.connect_ex(("127.0.0.1", p))
            s.close()
            if result == 0:
                return True
        except OSError:
            pass
    return False


def _ping_engine() -> bool:
    """Check if a CryoDAQ engine is actually running on the command port."""
    try:
        import json

        import zmq

        ctx = zmq.Context()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.RCVTIMEO, 2000)
        sock.setsockopt(zmq.SNDTIMEO, 2000)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(f"tcp://127.0.0.1:{_ZMQ_PORT + 1}")
        sock.send_string(json.dumps({"cmd": "safety_status"}))
        reply = json.loads(sock.recv_string())
        sock.close()
        ctx.term()
        return reply.get("ok", False)
    except Exception:
        return False


class LauncherWindow(QMainWindow):
    """Главное окно лаунчера — встраивает MainWindow и управляет engine."""

    _reading_received = Signal(object)

    def __init__(
        self,
        app: QApplication,
        *,
        mock: bool = False,
        tray_only: bool = False,
        replay_source: Path | None = None,
        replay_speed: float = 5.0,
        replay_phase: str = "cooldown",
        replay_loop: bool = False,
        force_replay: bool = False,
        legacy_channel_era: str | None = None,
        soak_bridge_handshake: _SoakBridgeHandshake | None = None,
        soak_artifact_capability: _SoakArtifactCapability | None = None,
    ) -> None:
        super().__init__()
        self._app = app
        self._mock = mock
        self._tray_only = tray_only
        self._replay_source = replay_source
        self._replay_speed = replay_speed
        self._replay_phase = replay_phase
        self._replay_loop = replay_loop
        self._force_replay = force_replay
        self._legacy_channel_era = legacy_channel_era
        self._soak_bridge_handshake = soak_bridge_handshake
        self._soak_artifact_capability = soak_artifact_capability
        self._engine_proc: subprocess.Popen | None = None
        self._engine_stderr_handler: logging.Handler | None = None
        self._engine_stderr_logger: logging.Logger | None = None
        self._engine_stderr_thread: threading.Thread | None = None
        self._engine_external = False  # True если engine запущен кем-то другим
        # A4: exponential backoff for engine restart attempts. Retry FOREVER —
        # a dead overnight acquisition with nobody told is worse than any
        # restart storm. Backoff caps at the last slot (120s) and never gives
        # up. Reset after a 5-min healthy run. Only exit code 2 (config error)
        # latches no-auto-restart.
        self._restart_attempts: int = 0
        self._last_restart_time: float = 0.0
        self._restart_backoff_s: list[int] = [3, 10, 30, 60, 120]
        self._restart_giving_up: bool = False  # latched only on config-error exit
        self._config_error_modal_shown: bool = False
        # A4: persistent non-modal "engine down" banner + repeating audible
        # alarm. Built lazily; None until first use / in tray-only mode.
        self._engine_down_banner: QLabel | None = None
        self._periodic_status_banner: QLabel | None = None
        self._alarm_timer: QTimer | None = None
        # Guards against multiple QTimer.singleShot restarts piling up while
        # _check_engine_health keeps firing every 3s during the backoff
        # window. Set when we schedule a restart, cleared when _start_engine
        # actually runs.
        self._restart_pending: bool = False
        self._shutdown_requested: bool = False
        self._shutdown_phase = _ShutdownPhase.RUNNING
        self._shutdown_attempt_active = False
        self._shutdown_retry_pending = False
        self._shutdown_retry_index = 0
        self._shutdown_quiesced = False
        self._shutdown_settled: set[str] = set()
        self._shutdown_last_errors: dict[str, Exception] = {}
        self._shutdown_failure_notified = False
        self._replay_engine_failed: bool = False
        self._reading_count = 0
        self._has_errors = False
        self._last_reading_time = 0.0
        self._last_safety_state: str | None = None
        # Alarm authority is not wired into this coarse launcher surface yet.
        # Unknown must remain unknown: seeding zero could authorize a green
        # tray despite an unavailable alarm feed.
        self._last_alarm_count: int | None = None
        self._safety_worker: ZmqCommandWorker | None = None

        # cryodaq-assistant (Гемма + RAG + automatic report reconciliation)
        # remains the existing third supervised child. It is
        # spawned when either optional LLM or automatic reporting needs it.
        # Restart/backoff mirrors the engine child, but its death is NON-safety:
        # log + tray note only — no alarm, no banner, no giving-up latch.
        self._assistant_proc: subprocess.Popen | None = None
        self._assistant_shutdown_path: Path | None = None
        self._assistant_shutdown_authority: _AssistantShutdownAuthority | None = None
        self._assistant_experiment_mode = replay_source is None
        self._assistant_enabled, self._assistant_periodic_requested = _assistant_runtime_decision(
            experiment_mode=self._assistant_experiment_mode
        )
        self._assistant_periodic_data_dir: Path | None = None
        self._assistant_periodic_health: _PeriodicHealthObservation | None = None
        if self._assistant_periodic_requested:
            from cryodaq.paths import get_data_dir

            self._assistant_periodic_data_dir = get_data_dir()
        self._periodic_health_read_failed_logged = False
        self._periodic_reporting_fault = False
        self._assistant_restart_attempts: int = 0
        self._assistant_last_restart_time: float = 0.0
        self._assistant_restart_pending: bool = False

        if replay_source is not None:
            self.setWindowTitle(f"CryoDAQ — REPLAY: {replay_source.name}")
        else:
            self.setWindowTitle("CryoDAQ — Криогенная лаборатория АКЦ ФИАН")
        self.setMinimumSize(1360, 860)

        # --- Asyncio ---
        # pyzmq requires a SelectorEventLoop on Windows (not the default
        # Proactor). Build it explicitly instead of the deprecated
        # WindowsSelectorEventLoopPolicy (policy system deprecated in Python
        # 3.14+). On other platforms the selector loop is already the default.
        if sys.platform == "win32":
            self._loop = asyncio.SelectorEventLoop()
        else:
            self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        self._async_timer = QTimer(self)
        self._async_timer.setInterval(10)
        self._async_timer.timeout.connect(self._tick_async)
        self._async_timer.start()

        # --- ZMQ Bridge subprocess ---
        self._bridge = ZmqBridge()
        set_bridge(self._bridge)
        self._reading_received.connect(self._on_reading_qt)

        # --- Engine ---
        self._start_engine()

        # --- Assistant (B1) ---
        if self._assistant_enabled:
            self._start_assistant()

        # Start ZMQ bridge subprocess — skip if replay engine failed to start
        # so the bridge doesn't silently attach to a live engine.
        if self._replay_engine_failed:
            QTimer.singleShot(200, self._show_replay_engine_failure)
        else:
            self._bridge.start()
            if self._soak_bridge_handshake is not None:
                try:
                    self._soak_bridge_handshake.emit(
                        bridge_pid=self._bridge.process_pid(),
                        restart_count=self._bridge.restart_count(),
                    )
                except Exception:
                    self._soak_bridge_handshake.close()
                    self._bridge.shutdown()
                    self._stop_assistant()
                    self._stop_engine()
                    raise

        if tray_only:
            self._main_window = None
            self._build_tray()
        else:
            self._build_ui()
            self._build_tray()

        # --- Таймеры ---
        # Data polling from ZMQ bridge subprocess
        self._data_timer = QTimer(self)
        self._data_timer.setInterval(10)  # 100 Hz
        self._data_timer.timeout.connect(self._poll_bridge_data)
        self._data_timer.start()

        self._health_timer = QTimer(self)
        self._health_timer.setInterval(3000)
        self._health_timer.timeout.connect(self._check_engine_health)
        self._health_timer.start()

        if not tray_only:
            self._status_timer = QTimer(self)
            self._status_timer.setInterval(1000)
            self._status_timer.timeout.connect(self._update_status)
            self._status_timer.start()

    # ------------------------------------------------------------------
    # Engine management
    # ------------------------------------------------------------------

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        import os

        try:
            if sys.platform == "win32":
                import ctypes

                handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                os.kill(pid, 0)
                return True
        except (OSError, ProcessLookupError):
            return False

    def _check_predictor_bootstrap_hint(self) -> None:
        """Log a one-line INFO suggesting bootstrap when model is missing
        but canonical source is present. Operator-explicit only — no auto-copy.
        """
        from cryodaq.paths import get_project_root

        root = get_project_root()
        deployed = root / "data" / "cooldown_model" / "predictor_model.json"
        canonical = root / "cooldown_v5" / "predictor_model.json"
        if not deployed.exists() and canonical.exists():
            logger.info(
                "Cooldown predictor model not deployed. Run `make bootstrap-predictor` to copy from cooldown_v5/."
            )

    def _start_engine(self, *, wait: bool = True) -> None:
        """Запустить engine как подпроцесс (или подключиться к существующему)."""
        if self._replay_source is None:
            self._check_predictor_bootstrap_hint()
        if _is_port_busy(_ZMQ_PORT):
            if _ping_engine():
                if self._replay_source is None:
                    logger.info("Engine уже запущен (порт %d, ping OK) — подключаемся", _ZMQ_PORT)
                    self._engine_external = True
                    return
                # Replay mode: don't hijack the live engine. The replay engine
                # subprocess will raise on port collision unless --force-replay is set.
            else:
                logger.warning(
                    "Порт %d занят, но CryoDAQ engine не отвечает — запускаем новый",
                    _ZMQ_PORT,
                )

        # Probe lock file via flock — OS-agnostic, no read_text on Windows
        from cryodaq.paths import get_data_dir

        lock_path = get_data_dir() / ".engine.lock"
        if lock_path.exists():
            probe_fd = None
            try:
                probe_fd = os.open(str(lock_path), os.O_RDWR)
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(probe_fd, msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(probe_fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(probe_fd, fcntl.LOCK_UN)
                # Lock was free → stale file, proceed
                logger.info("Stale lock file — proceeding with engine start")
            except OSError:
                # Lock held → engine alive but port not ready yet
                if probe_fd is not None:
                    try:
                        os.close(probe_fd)
                    except OSError:
                        pass
                    probe_fd = None
                logger.warning("Engine lock held. Waiting for port...")
                for _ in range(30):
                    time.sleep(0.5)
                    if _is_port_busy(_ZMQ_PORT):
                        if self._replay_source is None:
                            logger.info("Engine ready — connecting")
                            self._engine_external = True
                            return
                        break  # replay mode: don't hijack live engine
                else:
                    logger.error("Engine holds lock but port not ready. Run: cryodaq-engine --force")
                    return
            finally:
                if probe_fd is not None:
                    try:
                        os.close(probe_fd)
                    except OSError:
                        pass

        logger.info("Запуск engine как подпроцесса...")
        if self._replay_source is not None:
            if getattr(sys, "frozen", False):
                cmd = [
                    sys.executable,
                    "--mode=replay-engine",
                    "--source",
                    str(self._replay_source),
                    "--speed",
                    str(self._replay_speed),
                    "--phase",
                    self._replay_phase,
                ]
            else:
                python = sys.executable
                if sys.platform == "win32":
                    pythonw = Path(python).parent / "pythonw.exe"
                    if pythonw.exists():
                        python = str(pythonw)
                cmd = [
                    python,
                    "-m",
                    "cryodaq.replay_engine",
                    "--source",
                    str(self._replay_source),
                    "--speed",
                    str(self._replay_speed),
                    "--phase",
                    self._replay_phase,
                ]
            if self._replay_loop:
                cmd.append("--loop")
            if self._force_replay:
                cmd.append("--force-replay")
            if self._legacy_channel_era:
                cmd.extend(["--legacy-channel-era", self._legacy_channel_era])
        else:
            # In a PyInstaller frozen build, sys.executable IS the bundled exe
            # (not a Python interpreter). Re-invoke ourselves with --mode=engine
            # which _frozen_main._dispatch() routes to cryodaq.engine.main().
            # In dev mode, fall back to "python -m cryodaq.engine".
            if getattr(sys, "frozen", False):
                python = sys.executable
                cmd = [python, "--mode=engine"]
            else:
                python = sys.executable
                if sys.platform == "win32":
                    pythonw = Path(python).parent / "pythonw.exe"
                    if pythonw.exists():
                        python = str(pythonw)
                cmd = [python, "-m", "cryodaq.engine"]

        env = _without_soak_bridge_environment(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        if self._mock and self._replay_source is None:
            env["CRYODAQ_MOCK"] = "1"
        # IV.4 F2: propagate the GUI-persisted debug-mode flag to the
        # engine subprocess so the engine uses DEBUG logging without
        # having to re-read QSettings from its own process. Env var is
        # the same one honoured by ``cryodaq.logging_setup.resolve_log_level``.
        from cryodaq.logging_setup import read_debug_mode_from_qsettings

        if read_debug_mode_from_qsettings():
            env["CRYODAQ_LOG_LEVEL"] = "DEBUG"

        creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0

        if self._mock and self._replay_source is None:
            cmd.append("--mock")

        stderr_logger, stderr_handler, stderr_path = _create_engine_stderr_logger()
        self._engine_stderr_logger = stderr_logger
        self._engine_stderr_handler = stderr_handler
        try:
            self._engine_proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except Exception:
            try:
                stderr_logger.removeHandler(stderr_handler)
            except Exception:
                pass
            stderr_handler.close()
            self._engine_stderr_handler = None
            self._engine_stderr_logger = None
            raise
        if self._engine_proc.stderr is not None:
            self._engine_stderr_thread = threading.Thread(
                target=_pump_engine_stderr,
                args=(self._engine_proc.stderr, stderr_logger),
                name="engine-stderr-pump",
                daemon=True,
            )
            self._engine_stderr_thread.start()
        self._engine_external = False
        logger.info(
            "Engine запущен, PID=%d (stderr → %s)",
            self._engine_proc.pid,
            stderr_path,
        )

        # Ожидание готовности engine — ping command port
        if wait:
            self._wait_engine_ready()

    def _close_engine_stderr_stream(self) -> None:
        thread = self._engine_stderr_thread
        if thread is not None:
            if thread.is_alive():
                thread.join(timeout=2.0)
            if thread.is_alive():
                raise RuntimeError("engine stderr pump remained alive after bounded join")
            self._engine_stderr_thread = None

        stderr_logger = self._engine_stderr_logger
        stderr_handler = self._engine_stderr_handler
        if stderr_logger is None and stderr_handler is None:
            return
        if stderr_logger is None or stderr_handler is None:
            raise RuntimeError("engine stderr logger ownership is inconsistent")
        stderr_logger.removeHandler(stderr_handler)
        stderr_handler.close()
        self._engine_stderr_handler = None
        self._engine_stderr_logger = None

    def _wait_engine_ready(self, max_attempts: int = 10, interval_s: float = 0.5) -> None:
        """Wait for engine to start listening on ZMQ port."""
        for attempt in range(max_attempts):
            time.sleep(interval_s)
            if _is_port_busy(_ZMQ_PORT):
                # In replay mode, verify our subprocess bound the port rather than a
                # pre-existing live engine. If the subprocess already exited it lost
                # the port race — treat this as a startup failure, not "ready".
                if (
                    self._replay_source is not None
                    and self._engine_proc is not None
                    and self._engine_proc.poll() is not None
                ):
                    logger.error(
                        "Replay engine exited before port was ready "
                        "(port collision with a live engine?). "
                        "Stop the real engine first, or use --force-replay."
                    )
                    self._replay_engine_failed = True
                    return
                logger.info("Engine ready (attempt %d/%d)", attempt + 1, max_attempts)
                return
        logger.warning("Engine did not respond after %d attempts, proceeding anyway", max_attempts)

    def _show_replay_engine_failure(self) -> None:
        """Show error and close when the replay engine could not start."""
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(
            self,
            "Replay Engine Failed",
            "The replay engine could not start.\n\n"
            "Port 5555 is already in use by a live engine.\n"
            "Stop the real engine first, or use --force-replay to override.",
        )
        self.close()

    def _stop_engine(self) -> None:
        """Остановить engine подпроцесс."""
        process = self._engine_proc
        if process is None:
            self._close_engine_stderr_stream()
            return

        if self._engine_external:
            if process.poll() is None:
                raise RuntimeError("external engine unexpectedly has a live launcher-owned process handle")
            self._engine_proc = None
            self._close_engine_stderr_stream()
            return

        logger.info("Остановка engine (PID=%d)...", process.pid)
        if process.poll() is None:
            try:
                process.terminate()
            except Exception:
                if process.poll() is None:
                    raise
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning("Engine не завершился за 10с, принудительное завершение")
                    try:
                        process.kill()
                    except Exception:
                        if process.poll() is None:
                            raise
                    if process.poll() is None:
                        process.wait(timeout=5)
        if process.poll() is None:
            raise RuntimeError("engine process remained alive after bounded shutdown")
        self._engine_proc = None
        self._close_engine_stderr_stream()
        logger.info("Engine остановлен")

    def _restart_engine(self) -> None:
        """Restart engine AND bridge for clean ZMQ connections."""
        if getattr(self, "_shutdown_requested", False):
            logger.warning("Engine restart refused while launcher shutdown is pending")
            return
        # A4: manual restart is the operator's recovery lever — clear the
        # config-error latch, reset backoff, and silence the alarm/banner so
        # a fixed config (or a manual retry) starts from a clean slate.
        self._restart_giving_up = False
        self._restart_attempts = 0
        self._config_error_modal_shown = False
        self._restart_pending = False
        self._clear_engine_down_banner()
        self._invalidate_descriptor_transport()
        self._data_timer.stop()
        self._health_timer.stop()
        self._bridge.shutdown()
        self._stop_engine()
        time.sleep(1)
        self._engine_external = False
        self._start_engine()
        self._bridge.start()
        self._data_timer.start()
        self._health_timer.start()

    def _is_engine_alive(self) -> bool:
        """Проверить, жив ли engine."""
        if self._engine_external:
            return _is_port_busy(_ZMQ_PORT)
        if self._engine_proc is None:
            return False
        return self._engine_proc.poll() is None

    # ------------------------------------------------------------------
    # Assistant management (B1) — non-safety third child, see the wiring
    # comment on ``self._assistant_enabled`` in __init__.
    # ------------------------------------------------------------------

    def _start_assistant(self) -> None:
        """Spawn the cryodaq-assistant subprocess (Гемма + RAG)."""
        if (
            self._assistant_experiment_mode
            and self._assistant_periodic_requested
            and getattr(self, "_assistant_periodic_health", None) is None
        ):
            self._assistant_periodic_health = _PeriodicHealthObservation(started_at=time.monotonic())
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--mode=assistant"]
        else:
            python = sys.executable
            if sys.platform == "win32":
                pythonw = Path(python).parent / "pythonw.exe"
                if pythonw.exists():
                    python = str(pythonw)
            cmd = [python, "-m", "cryodaq.agents.assistant_bootstrap"]

        env = _without_soak_bridge_environment(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["CRYODAQ_ASSISTANT_EXPERIMENT_MODE"] = "1" if self._assistant_experiment_mode else "0"
        env["CRYODAQ_ASSISTANT_PERIODIC_MODE"] = (
            "1" if self._assistant_experiment_mode and self._assistant_periodic_requested else "0"
        )
        # CREATE_NO_WINDOW children do not have a console on which
        # GenerateConsoleCtrlEvent can be relied upon.  Use a private file
        # sentinel for the production graceful path; SIGBREAK remains useful
        # for the console-enabled frozen smoke harness.
        creationflags = _WINDOWS_CREATE_NO_WINDOW if sys.platform == "win32" else 0
        shutdown_authority: _AssistantShutdownAuthority | None = None
        soak_duplicate: int | None = None
        soak_generation: int | None = None
        soak_capability = getattr(self, "_soak_artifact_capability", None)
        try:
            if sys.platform == "win32":
                from cryodaq.paths import get_data_dir

                shutdown_authority = _new_assistant_shutdown_authority(get_data_dir())
                env[_ASSISTANT_SHUTDOWN_ENV] = str(shutdown_authority.path)
            pass_fds: tuple[int, ...] = ()
            if soak_capability is not None:
                soak_duplicate, soak_generation, grant = soak_capability.child_grant()
                env.update(grant)
                pass_fds = (soak_duplicate,)
            popen_kwargs: dict[str, Any] = {}
            if pass_fds:
                popen_kwargs.update({"close_fds": True, "pass_fds": pass_fds})
            self._assistant_proc = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                # setup_logging("assistant", ...) writes logs/assistant.log —
                # no need to pipe+pump stderr through the launcher like the
                # engine child (that machinery exists for the safety-alarm
                # banner; the assistant has no such path).
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                **popen_kwargs,
            )
            if soak_capability is not None and soak_generation is not None:
                soak_capability.commit_generation(soak_generation)
            self._assistant_shutdown_path = None if shutdown_authority is None else shutdown_authority.path
            self._assistant_shutdown_authority = shutdown_authority
            logger.info("cryodaq-assistant запущен, PID=%d", self._assistant_proc.pid)
        except Exception:
            logger.exception("Не удалось запустить cryodaq-assistant")
            self._assistant_proc = None
            self._assistant_shutdown_path = None
            self._assistant_shutdown_authority = None
        finally:
            if soak_duplicate is not None:
                try:
                    os.close(soak_duplicate)
                except OSError:
                    pass

    def _stop_assistant(self) -> None:
        """Остановить cryodaq-assistant подпроцесс, если он запущен."""
        if self._assistant_proc is None:
            self._assistant_shutdown_path = None
            self._assistant_shutdown_authority = None
            return
        process = self._assistant_proc
        logger.info("Остановка cryodaq-assistant (PID=%d)...", process.pid)
        shutdown_path = getattr(self, "_assistant_shutdown_path", None)
        shutdown_authority = getattr(self, "_assistant_shutdown_authority", None)
        if process.poll() is None:
            if (
                sys.platform == "win32"
                and shutdown_path is not None
                and isinstance(shutdown_authority, _AssistantShutdownAuthority)
                and shutdown_authority.path == shutdown_path
                and shutdown_authority.directories_match()
            ):
                sentinel_ready = False
                if os.path.lexists(shutdown_path):
                    # Accept an earlier request only if the exact observed
                    # object is still an ordinary file, never a link/reparse.
                    sentinel_ready = shutdown_authority.directories_match() and _is_real_regular_file(shutdown_path)
                else:
                    try:
                        descriptor = os.open(shutdown_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    except FileExistsError:
                        # A concurrent creator won the race. Revalidate the
                        # exact observed object instead of opening it again.
                        sentinel_ready = shutdown_authority.directories_match() and _is_real_regular_file(shutdown_path)
                    except OSError:
                        logger.exception("Не удалось запросить мягкую остановку cryodaq-assistant")
                    else:
                        try:
                            sentinel_ready = (
                                shutdown_authority.directories_match()
                                and _opened_real_regular_file_matches(shutdown_path, descriptor)
                            )
                        finally:
                            os.close(descriptor)
                if sentinel_ready:
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        logger.warning("cryodaq-assistant не завершился мягко за 10с")

            if process.poll() is None:
                try:
                    process.terminate()
                except Exception:
                    if process.poll() is None:
                        raise
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    logger.warning("cryodaq-assistant не завершился за 10с, принудительное завершение")
                    try:
                        process.kill()
                    except Exception:
                        if process.poll() is None:
                            raise
                    if process.poll() is None:
                        process.wait(timeout=5)
        if process.poll() is None:
            raise RuntimeError("assistant process remained alive after bounded shutdown")
        self._assistant_proc = None
        # Do not unlink by pathname: Windows has no portable atomic
        # checked-unlink operation. Per-launch UUID names make the retained
        # empty sentinel inert. Authority is released only after process death.
        self._assistant_shutdown_path = None
        self._assistant_shutdown_authority = None
        logger.info("cryodaq-assistant остановлен")

    def _check_assistant_health(self) -> None:
        """Restart cryodaq-assistant with backoff if it died. NON-safety:
        the assistant is Гемма chat/RAG, not instrument control — its
        death gets a log line + tray note, never the alarm/banner path
        the engine child uses.
        """
        if not self._assistant_enabled or self._shutdown_requested:
            return
        if self._assistant_proc is not None and self._assistant_proc.poll() is None:
            if self._assistant_periodic_requested:
                self._check_periodic_health()
            # Alive — reset backoff after a healthy run window.
            if self._assistant_restart_attempts > 0 and time.monotonic() - self._assistant_last_restart_time > 300.0:
                self._assistant_restart_attempts = 0
            return
        if self._assistant_periodic_requested:
            self._set_periodic_reporting_fault()
        if self._assistant_restart_pending:
            return

        self._assistant_proc = None
        delay_idx = min(self._assistant_restart_attempts, len(self._restart_backoff_s) - 1)
        delay_s = self._restart_backoff_s[delay_idx]
        logger.warning(
            "cryodaq-assistant недоступен, перезапуск через %ds (попытка %d)",
            delay_s,
            self._assistant_restart_attempts + 1,
        )
        if hasattr(self, "_tray") and self._tray is not None:
            self._tray.showMessage(
                "CryoDAQ",
                "Ассистент (Гемма) перезапускается — чат временно недоступен.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
        self._assistant_restart_attempts += 1
        self._assistant_last_restart_time = time.monotonic()
        self._assistant_restart_pending = True

        def _do_restart() -> None:
            self._assistant_restart_pending = False
            if not self._shutdown_requested:
                self._start_assistant()

        QTimer.singleShot(delay_s * 1000, _do_restart)

    def _check_periodic_health(self, *, monotonic_now: float | None = None) -> None:
        """Observe H3 health without using its wall timestamp as an age clock."""
        if not self._assistant_periodic_requested:
            return
        observation = self._assistant_periodic_health
        data_dir = self._assistant_periodic_data_dir
        if observation is None or data_dir is None:
            return
        now = time.monotonic() if monotonic_now is None else monotonic_now
        status: str | None = None
        updated_at: float | None = None
        try:
            from cryodaq.periodic_state import load_periodic_state

            state = load_periodic_state(data_dir)
            health = state.payload.get("health")
            if isinstance(health, Mapping):
                raw_status = health.get("status")
                raw_updated_at = health.get("updated_at")
                if isinstance(raw_status, str):
                    status = raw_status
                if type(raw_updated_at) is float:
                    updated_at = raw_updated_at
            self._periodic_health_read_failed_logged = False
        except Exception:
            if not self._periodic_health_read_failed_logged:
                logger.warning(
                    "Periodic PNG health unavailable: %s",
                    _PERIODIC_HEALTH_READ_FAILED_CODE,
                )
                self._periodic_health_read_failed_logged = True

        refreshed = observation.observe(
            status=status,
            updated_at=updated_at,
            monotonic_now=now,
            wall_now=time.time(),
        )
        if refreshed:
            self._clear_periodic_reporting_fault()
        elif observation.deadline_expired(now):
            self._set_periodic_reporting_fault()

    def _set_periodic_reporting_fault(self) -> None:
        """Show one persistent non-safety H3 operator status."""
        if self._periodic_reporting_fault:
            return
        self._periodic_reporting_fault = True
        logger.error("Periodic PNG runtime unavailable: %s", _PERIODIC_RUNTIME_UNAVAILABLE_CODE)
        if self._periodic_status_banner is not None:
            self._periodic_status_banner.show()
        if hasattr(self, "_tray") and self._tray is not None:
            self._tray.showMessage(
                "CryoDAQ",
                "Периодические PNG-отчёты недоступны. Управление оборудованием не затронуто.",
                QSystemTrayIcon.MessageIcon.Warning,
                5000,
            )

    def _clear_periodic_reporting_fault(self) -> None:
        """Clear H3 status only after a strictly newer ready heartbeat."""
        if not self._periodic_reporting_fault:
            return
        self._periodic_reporting_fault = False
        logger.info("Periodic PNG runtime recovered")
        if self._periodic_status_banner is not None:
            self._periodic_status_banner.hide()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # A4: persistent NON-MODAL banner shown while the engine is down and
        # retrying. Never blocks the operator — the restart button stays live.
        self._engine_down_banner = QLabel()
        self._engine_down_banner.setWordWrap(True)
        self._engine_down_banner.setStyleSheet(
            "background-color: #FF4136; color: #ffffff; font-weight: bold; padding: 8px 12px;"
        )
        self._engine_down_banner.hide()
        root.addWidget(self._engine_down_banner)

        self._periodic_status_banner = QLabel(
            "Периодические PNG-отчёты недоступны "
            f"({_PERIODIC_RUNTIME_UNAVAILABLE_CODE}). "
            "Управление оборудованием не затронуто."
        )
        self._periodic_status_banner.setWordWrap(True)
        self._periodic_status_banner.setStyleSheet(
            "background-color: #FFB000; color: #161616; font-weight: bold; padding: 8px 12px;"
        )
        self._periodic_status_banner.hide()
        root.addWidget(self._periodic_status_banner)

        # --- Верхняя панель статуса engine ---
        # Phase UI-1 v2: this top bar is hidden because shell v2's
        # TopWatchBar replaces it. The widgets remain constructed because
        # other launcher methods (_check_engine_health, _on_restart_engine)
        # still write to self._engine_indicator and self._engine_label.
        top_bar = QWidget()
        self._top_bar = top_bar
        top_bar.setFixedHeight(40)
        top_bar.setStyleSheet("background-color: #161b22; border-bottom: 1px solid #30363d;")
        tbl = QHBoxLayout(top_bar)
        tbl.setContentsMargins(12, 0, 12, 0)

        self._engine_indicator = QLabel("⬤")
        self._engine_indicator.setFont(QFont("", 12))
        tbl.addWidget(self._engine_indicator)

        self._engine_label = QLabel("Engine: запуск...")
        self._engine_label.setStyleSheet("color: #c9d1d9; font-weight: bold;")
        tbl.addWidget(self._engine_label)

        tbl.addStretch()

        # Кнопка «Открыть Web-панель»
        web_btn = QPushButton("Открыть Web-панель")
        web_btn.setStyleSheet(
            "QPushButton { background: #21262d; color: #58a6ff; border: 1px solid #30363d; "
            "border-radius: 4px; padding: 4px 12px; }"
            "QPushButton:hover { background: #30363d; }"
        )
        web_btn.clicked.connect(self._on_open_web)
        tbl.addWidget(web_btn)

        # Кнопка «Перезапустить Engine»
        restart_btn = QPushButton("Перезапустить Engine")
        restart_btn.setStyleSheet(
            "QPushButton { background: #21262d; color: #f0883e; border: 1px solid #30363d; "
            "border-radius: 4px; padding: 4px 12px; }"
            "QPushButton:hover { background: #30363d; }"
        )
        restart_btn.clicked.connect(self._on_restart_engine)
        tbl.addWidget(restart_btn)

        root.addWidget(top_bar)
        # Phase UI-1 v2: shell v2 provides TopWatchBar; hide launcher's
        # own engine bar to avoid duplicated chrome.
        top_bar.hide()

        # --- Встроенное главное окно ---
        self._main_window = MainWindow(
            bridge=self._bridge,
            embedded=True,
            replay_mode=self._replay_source is not None,
        )
        self._snapshot_ingress = start_operator_snapshot_ingress(self._bridge, self._main_window)
        # Phase UI-1 v2: shell v2 has its own BottomStatusBar; hide
        # launcher's status bar entirely.
        self.statusBar().setVisible(False)
        # MainWindowV2 has no menu actions, so this is a no-op for v2.
        self._merge_main_window_menus()
        # Own menu (Настройки → Тема) lives on the launcher, not on
        # MainWindowV2 which has no menuBar of its own.
        self._build_settings_menu()
        root.addWidget(self._main_window, stretch=1)

        # Phase UI-1 v2: status bar widgets retained as orphaned
        # attributes because other launcher methods read/write them.
        self._status_conn = QLabel("⬤ Отключено")
        self._status_rate = QLabel("0 изм/с")
        self._status_uptime = QLabel("")

    def _build_tray(self) -> None:
        """Создать иконку в системном трее."""
        self._tray_icon_green = tray_icon_for_level(TrayLevel.HEALTHY)
        self._tray_icon_yellow = tray_icon_for_level(TrayLevel.CAUTION)
        self._tray_icon_red = tray_icon_for_level(TrayLevel.FAULT)

        # Начальная иконка: если engine уже работает — жёлтый (ожидание данных),
        # иначе красный (engine не запущен).
        initial_status = resolve_tray_status(
            connected=None,
            safety_state=None,
            alarm_count=None,
            data_fresh=None,
            reporting_fault=None,
        )
        self._tray = QSystemTrayIcon(self._tray_icon_yellow, self)

        menu = QMenu()
        if self._tray_only:
            open_gui_action = menu.addAction("Открыть GUI")
            open_gui_action.triggered.connect(self._on_open_full_gui)
        else:
            open_action = menu.addAction("Открыть")
            open_action.triggered.connect(self._tray_open)
            minimize_action = menu.addAction("Свернуть")
            minimize_action.triggered.connect(self._tray_minimize)
        menu.addSeparator()
        restart_action = menu.addAction("Перезапустить Engine")
        restart_action.triggered.connect(self._on_restart_engine)
        menu.addSeparator()
        exit_action = menu.addAction("Выход")
        exit_action.triggered.connect(self._on_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.setToolTip(initial_status.tooltip)
        self._tray.show()

    def _merge_main_window_menus(self) -> None:
        """Перенести меню MainWindow в menuBar лаунчера."""
        source_bar = self._main_window.menuBar()
        dest_bar = self.menuBar()
        for action in source_bar.actions():
            dest_bar.addAction(action)
        source_bar.setVisible(False)

    def _build_settings_menu(self) -> None:
        """Построить меню «Настройки → Тема» на menuBar лаунчера.

        Order: dark group (with a visual separator), then light group.
        Within each group the order is fixed by ``_THEME_DISPLAY_ORDER``
        below rather than alphabetical filename sort — the display order
        is curated, not data-driven, so that related palettes (e.g.
        Сигнал / Приборный / Янтарь) sit together regardless of their
        filename spelling.
        """
        from cryodaq.gui import theme as gui_theme
        from cryodaq.gui._theme_loader import _selected_theme_name, available_themes

        # Renamed «Настройки» → «Вид»: the ToolRail already owns the canonical
        # «Настройки» (channel editor / connection params). This launcher menu
        # holds display/app preferences (Тема + Подробные логи), so the word
        # «Настройки» was showing twice in the same window. «Вид» de-collides.
        settings_menu = self.menuBar().addMenu("Вид")
        theme_menu = settings_menu.addMenu("Тема")

        current = gui_theme.ACTIVE_THEME_ID
        selected = _selected_theme_name()
        packs_by_id = {pack["id"]: pack for pack in available_themes()}
        ordered_ids = [pid for pid in _THEME_DISPLAY_ORDER if pid in packs_by_id]
        # Any pack not in the curated order (e.g. local dev pack dropped
        # in config/themes/) appears at the end, alphabetical. Keeps
        # the menu forward-compatible without requiring a code edit.
        extras = sorted(pid for pid in packs_by_id if pid not in _THEME_DISPLAY_ORDER)

        group = QActionGroup(self)
        group.setExclusive(True)
        self._theme_active_id = current
        self._theme_actions: dict[str, QAction] = {}

        def _add_entry(pid: str) -> None:
            pack = packs_by_id[pid]
            action = QAction(pack["name"], self, checkable=True)
            if pack.get("description"):
                action.setToolTip(pack["description"])
            action.setChecked(pack["id"] == current)
            action.triggered.connect(lambda _checked=False, p=pack["id"]: self._on_theme_selected(p))
            group.addAction(action)
            theme_menu.addAction(action)
            self._theme_actions[pid] = action

        added_any_dark = False
        for pid in ordered_ids:
            if pid in _LIGHT_THEME_IDS and added_any_dark:
                theme_menu.addSeparator()
                added_any_dark = False
            elif pid not in _LIGHT_THEME_IDS:
                added_any_dark = True
            _add_entry(pid)

        if extras:
            theme_menu.addSeparator()
            for pid in extras:
                _add_entry(pid)

        theme_menu.addSeparator()
        self._theme_pending_action = QAction(self)
        self._theme_pending_action.setEnabled(False)
        theme_menu.addAction(self._theme_pending_action)
        pending_id = selected if selected != current and selected in packs_by_id else None
        self._update_theme_pending_indicator(pending_id)

        # IV.4 F2: operator-level debug-logging toggle. Sits directly
        # under «Настройки» alongside «Тема» so it shares the same
        # menu location; state is persisted in QSettings and read by
        # ``logging_setup.resolve_log_level`` on next startup. Launcher
        # propagates the flag to the engine subprocess via
        # CRYODAQ_LOG_LEVEL env var (see _start_engine).
        settings_menu.addSeparator()
        from cryodaq.logging_setup import read_debug_mode_from_qsettings

        self._debug_logging_action = QAction(
            "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0435 \u043b\u043e\u0433\u0438",
            self,
            checkable=True,
        )
        self._debug_logging_action.setChecked(read_debug_mode_from_qsettings())
        self._debug_logging_action.setStatusTip(
            "\u0417\u0430\u043f\u0438\u0441\u044c DEBUG \u043b\u043e\u0433\u043e\u0432"
            " \u0432 launcher / gui / engine \u0444\u0430\u0439\u043b\u044b."
        )
        self._debug_logging_action.triggered.connect(self._on_debug_logging_toggled)
        settings_menu.addAction(self._debug_logging_action)

    @Slot(bool)
    def _on_debug_logging_toggled(self, checked: bool) -> None:
        """Persist the debug-mode flag to QSettings and inform operator.

        IV.4 F2: the flag is read on every launcher / gui / engine
        start-up via ``resolve_log_level``. Applying the change requires
        a launcher restart — existing root-logger handlers keep their
        previously-configured level until a fresh ``setup_logging``
        call fires. Dialog text is explicit about that.
        """
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QMessageBox

        settings = QSettings("FIAN", "CryoDAQ")
        settings.setValue("logging/debug_mode", bool(checked))
        state_ru = (
            "\u0432\u043a\u043b\u044e\u0447\u0435\u043d\u044b"
            if checked
            else "\u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d\u044b"
        )  # noqa: E501
        # IV.4 F2 amend: when the launcher attached to an already-running
        # external engine (e.g. `cryodaq-engine` started separately in
        # headless mode), restarting the launcher alone does NOT rebuild
        # the engine's logging handlers — the env-var propagation only
        # fires when the launcher spawns its own engine child. Make the
        # two cases explicit so the operator doesn't assume a silent fix
        # for the engine logs in the external-engine deployment.
        engine_external = bool(getattr(self, "_engine_external", False))
        # Default: embedded engine — launcher restart picks up both
        # sides automatically because _start_engine spawns a fresh
        # engine child with CRYODAQ_LOG_LEVEL set from the new value.
        body_embedded = (
            f"\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0435 \u043b\u043e\u0433\u0438 {state_ru}.\n"
            "\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u044f \u043f\u0440\u0438\u043c\u0435"
            "\u043d\u044f\u0442\u0441\u044f \u043a launcher / gui / engine \u043f\u043e\u0441\u043b"
            "\u0435 \u043f\u0435\u0440\u0435\u0437\u0430\u043f\u0443\u0441\u043a\u0430 "
            "\u041b\u0430\u0443\u043d\u0447\u0435\u0440\u0430 (engine \u043f\u0435\u0440\u0435"
            "\u0437\u0430\u043f\u0443\u0441\u043a\u0430\u0435\u0442\u0441\u044f \u0432\u043c\u0435\u0441"
            "\u0442\u0435 \u0441 \u043d\u0438\u043c)."
        )
        if engine_external and checked:
            # External engine + enabling DEBUG: launcher restart only
            # affects launcher/gui; the already-running engine keeps
            # INFO until operator relaunches it (or exports
            # CRYODAQ_LOG_LEVEL=DEBUG before doing so).
            body = (
                f"\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0435 \u043b\u043e\u0433\u0438 {state_ru}.\n"
                "\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u044f \u041b\u0430\u0443\u043d\u0447"
                "\u0435\u0440\u0430 \u0438 GUI \u043f\u0440\u0438\u043c\u0435\u043d\u044f\u0442\u0441"
                "\u044f \u043f\u043e\u0441\u043b\u0435 \u0438\u0445 \u043f\u0435\u0440\u0435\u0437"
                "\u0430\u043f\u0443\u0441\u043a\u0430. Engine \u0437\u0430\u043f\u0443\u0449\u0435\u043d "
                "\u0432\u043d\u0435\u0448\u043d\u0435 \u2014 \u043f\u0435\u0440\u0435\u0437\u0430\u043f"
                "\u0443\u0441\u0442\u0438\u0442\u0435 \u0435\u0433\u043e \u043e\u0442\u0434\u0435\u043b"
                "\u044c\u043d\u043e \u0441 CRYODAQ_LOG_LEVEL=DEBUG, \u0447\u0442\u043e\u0431\u044b "
                "DEBUG \u043b\u043e\u0433\u0438 \u043f\u043e\u043f\u0430\u043b\u0438 \u0438 \u0432 "
                "engine.log."
            )
        elif engine_external and not checked:
            # External engine + disabling DEBUG: same restart-gap, but
            # the guidance is the inverse — unset the env var or set
            # it to INFO so the engine actually returns to INFO.
            body = (
                f"\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0435 \u043b\u043e\u0433\u0438 {state_ru}.\n"
                "\u0418\u0437\u043c\u0435\u043d\u0435\u043d\u0438\u044f \u041b\u0430\u0443\u043d\u0447"
                "\u0435\u0440\u0430 \u0438 GUI \u043f\u0440\u0438\u043c\u0435\u043d\u044f\u0442\u0441"
                "\u044f \u043f\u043e\u0441\u043b\u0435 \u0438\u0445 \u043f\u0435\u0440\u0435\u0437"
                "\u0430\u043f\u0443\u0441\u043a\u0430. Engine \u0437\u0430\u043f\u0443\u0449\u0435\u043d "
                "\u0432\u043d\u0435\u0448\u043d\u0435 \u2014 \u043f\u0435\u0440\u0435\u0437\u0430\u043f"
                "\u0443\u0441\u0442\u0438\u0442\u0435 \u0435\u0433\u043e \u0431\u0435\u0437 "
                "CRYODAQ_LOG_LEVEL (\u0438\u043b\u0438 CRYODAQ_LOG_LEVEL=INFO), \u0447\u0442\u043e\u0431\u044b "
                "engine.log \u0432\u0435\u0440\u043d\u0443\u043b\u0441\u044f \u043a INFO."
            )
        else:
            body = body_embedded
        QMessageBox.information(
            self,
            "\u041f\u043e\u0434\u0440\u043e\u0431\u043d\u044b\u0435 \u043b\u043e\u0433\u0438",
            body,
        )

    @Slot(str)
    def _on_theme_selected(self, theme_id: str) -> None:
        """Persist a validated theme for the next ordinary launcher start."""
        return self._defer_theme_selection(theme_id)

    def _defer_theme_selection(self, theme_id: str) -> None:
        """Persist a validated pack without touching the running process tree."""
        from cryodaq.gui import theme as gui_theme
        from cryodaq.gui._theme_loader import (
            _selected_theme_name,
            available_themes,
            write_theme_selection,
        )

        pack_name = next(
            (item["name"] for item in available_themes() if item["id"] == theme_id),
            theme_id,
        )
        try:
            write_theme_selection(theme_id)
        except Exception:
            logger.exception("theme: failed to persist selection")
            selected = _selected_theme_name()
            pending_id = (
                selected
                if selected != gui_theme.ACTIVE_THEME_ID and selected in getattr(self, "_theme_actions", {})
                else None
            )
            self._update_theme_pending_indicator(pending_id)
            QMessageBox.critical(
                self,
                "Не удалось сохранить тему",
                "Выбор темы не изменён. Проверьте локальные настройки и журнал launcher.",
            )
            return

        pending_id = None if theme_id == gui_theme.ACTIVE_THEME_ID else theme_id
        self._update_theme_pending_indicator(pending_id)
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.showMessage(
                "Тема сохранена",
                f"Тема «{pack_name}» будет применена при следующем обычном запуске.",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )

    def _update_theme_pending_indicator(self, pending_id: str | None) -> None:
        """Keep the checked action truthful to this process's loaded theme."""
        active_id = getattr(self, "_theme_active_id", None)
        actions = getattr(self, "_theme_actions", {})
        active_action = actions.get(active_id)
        if active_action is not None:
            active_action.setChecked(True)

        pending_action = getattr(self, "_theme_pending_action", None)
        if pending_action is None:
            return
        if pending_id is None or pending_id == active_id:
            pending_action.setText("Следующий запуск: текущая тема")
            return

        from cryodaq.gui._theme_loader import available_themes

        name = next(
            (item["name"] for item in available_themes() if item["id"] == pending_id),
            pending_id,
        )
        pending_action.setText(f"Следующий запуск: {name}")

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @Slot()
    def _poll_bridge_data(self) -> None:
        """Poll readings from ZMQ bridge subprocess and dispatch to GUI."""
        for qualified in self._bridge.poll_readings_with_descriptor():
            self._on_reading_qt(qualified)
        snapshot_ingress = getattr(self, "_snapshot_ingress", None)
        if snapshot_ingress is not None:
            snapshot_ingress.pump()

        unhealthy = not self._bridge.is_healthy()
        # data_flow_stalled only matters when heartbeats are otherwise healthy
        # (mirrors the original ordering — the not-healthy branch returns first).
        stalled = self._bridge.data_flow_stalled() if not unhealthy else False
        if unhealthy or stalled:
            # 60s cooldown prevents a restart storm: a freshly restarted bridge
            # needs time to (re)establish its heartbeat, during which is_healthy()
            # is transiently False — without the cooldown every poll would
            # restart it again. Same hardening as the command-channel watchdog.
            now = time.monotonic()
            last_restart = getattr(self, "_last_health_watchdog_restart", 0.0)
            if now - last_restart < 60.0:
                return
            self._last_health_watchdog_restart = now
            self._invalidate_descriptor_transport()
            if unhealthy:
                if self._bridge.is_alive():
                    logger.warning("ZMQ bridge not healthy (no heartbeat), restarting...")
                    self._bridge.shutdown()
                else:
                    logger.warning("ZMQ bridge died, restarting...")
            else:
                logger.warning("ZMQ bridge not healthy (no readings), restarting...")
                self._bridge.shutdown()
            self._bridge.start()
            return
        # IV.6 B1 fix: command-channel watchdog. Detects the case where
        # the subprocess is alive, heartbeats flow, readings flow, but
        # a recent REQ/REP timeout indicates the command plane has
        # entered a bad state. Restart bridge to cycle the ephemeral
        # REQ / REP connection and recover command path.
        if self._bridge.command_channel_stalled(timeout_s=10.0):
            # Hardening 2026-04-21: 60s cooldown prevents restart storm
            # when fresh subprocess immediately sees stale cmd_timeout.
            now = time.monotonic()
            last_cmd_restart = getattr(self, "_last_cmd_watchdog_restart", 0.0)
            if now - last_cmd_restart >= 60.0:
                logger.warning("ZMQ bridge: command channel unhealthy (recent command timeout). Restarting bridge.")
                self._last_cmd_watchdog_restart = now
                self._invalidate_descriptor_transport()
                self._bridge.shutdown()
                self._bridge.start()
                return

    @Slot(object)
    def _on_reading_qt(self, qualified: object) -> None:
        if type(qualified) is not DescriptorQualifiedReading or type(qualified.reading) is not Reading:
            logger.warning(
                "_on_reading_qt received malformed qualified reading of type %s; dropped",
                type(qualified).__name__,
            )
            return
        self._reading_count += 1
        self._last_reading_time = time.monotonic()
        soak_bridge = self._soak_bridge_handshake
        if soak_bridge is not None:
            soak_bridge.emit_data_observed(
                bridge_pid=self._bridge.process_pid(),
                restart_count=self._bridge.restart_count(),
            )
        # Route to embedded MainWindow (if not tray-only)
        if self._main_window is not None:
            self._main_window.dispatch_qualified_reading(qualified)

    def _invalidate_descriptor_transport(self) -> None:
        """Invalidate descriptor authority before transport or engine turnover."""
        if self._main_window is not None:
            self._main_window.invalidate_descriptor_transport()
        snapshot_ingress = getattr(self, "_snapshot_ingress", None)
        if snapshot_ingress is not None:
            snapshot_ingress.invalidate_transport()

    @Slot()
    def _on_open_web(self) -> None:
        webbrowser.open(f"http://127.0.0.1:{_WEB_PORT}")

    def _on_restart_engine_from_shell(self) -> None:
        """Entry point for shell v2 ⋯ menu — restart without re-prompting."""
        if not self._tray_only:
            self._engine_label.setText("Engine: перезапуск...")
        self._restart_engine()

    @Slot()
    def _on_restart_engine(self) -> None:
        reply = QMessageBox.question(
            self,
            "Перезапуск Engine",
            "Перезапустить Engine?\n\n"
            "Запись данных будет прервана на несколько секунд.\n"
            "Используйте только при проблемах с системой.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            if not self._tray_only:
                self._engine_label.setText("Engine: перезапуск...")
            self._restart_engine()

    @Slot()
    def _on_quit(self) -> None:
        """Выход с подтверждением."""
        reply = QMessageBox.question(
            self,
            "Выход из CryoDAQ",
            "Вы уверены?\n\nЗапись данных будет остановлена.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._do_shutdown()

    def _on_open_full_gui(self) -> None:
        """Launch standalone GUI window (connects to existing engine, no second launcher)."""
        # Frozen build: re-invoke our own exe with --mode=gui (handled by
        # _frozen_main._dispatch). Dev build: python -m cryodaq.gui.
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--mode=gui"]
        else:
            cmd = [sys.executable, "-m", "cryodaq.gui"]
        env = _without_soak_bridge_environment(os.environ)
        if self._mock:
            env["CRYODAQ_MOCK"] = "1"
        creationflags = _CREATE_NO_WINDOW if sys.platform == "win32" else 0
        if self._mock:
            cmd.append("--mock")
        subprocess.Popen(cmd, env=env, creationflags=creationflags)

    def _ensure_shutdown_state(self) -> None:
        """Initialize lifecycle fields for real instances and narrow test hosts."""

        if not isinstance(getattr(self, "_shutdown_phase", None), _ShutdownPhase):
            self._shutdown_phase = _ShutdownPhase.RUNNING
        if not isinstance(getattr(self, "_shutdown_settled", None), set):
            self._shutdown_settled = set()
        if not isinstance(getattr(self, "_shutdown_last_errors", None), dict):
            self._shutdown_last_errors = {}
        for name, default in (
            ("_shutdown_attempt_active", False),
            ("_shutdown_retry_pending", False),
            ("_shutdown_retry_index", 0),
            ("_shutdown_quiesced", False),
            ("_shutdown_failure_notified", False),
        ):
            if not isinstance(getattr(self, name, None), type(default)):
                setattr(self, name, default)

    def _set_shutdown_tray_state(self, *, failed: bool) -> None:
        """Keep incomplete shutdown visible without claiming safety truth."""

        tray = getattr(self, "_tray", None)
        if tray is None:
            return
        icon = getattr(self, "_tray_icon_red" if failed else "_tray_icon_yellow", None)
        if icon is not None:
            tray.setIcon(icon)
        tray.setToolTip(
            "CryoDAQ: завершение не окончено; ресурсы ещё завершаются."
            if failed
            else "CryoDAQ: выполняется контролируемое завершение."
        )
        tray.show()
        if failed and not self._shutdown_failure_notified:
            tray.showMessage(
                "CryoDAQ — завершение не окончено",
                "Один или несколько ресурсов ещё работают. "
                "Экземпляр остаётся заблокирован; выполняется повторная попытка.",
                QSystemTrayIcon.MessageIcon.Critical,
                8_000,
            )
            self._shutdown_failure_notified = True

    def _schedule_shutdown_retry(self) -> None:
        if self._shutdown_retry_pending or self._shutdown_phase is _ShutdownPhase.COMPLETE:
            return
        index = min(self._shutdown_retry_index, len(_SHUTDOWN_RETRY_DELAYS_MS) - 1)
        delay_ms = _SHUTDOWN_RETRY_DELAYS_MS[index]
        self._shutdown_retry_index = min(index + 1, len(_SHUTDOWN_RETRY_DELAYS_MS) - 1)
        self._shutdown_retry_pending = True

        def retry() -> None:
            self._shutdown_retry_pending = False
            LauncherWindow._do_shutdown(self)

        QTimer.singleShot(delay_ms, retry)

    def _shutdown_incomplete(self, errors: dict[str, Exception]) -> bool:
        self._shutdown_last_errors = dict(errors)
        self._shutdown_phase = _ShutdownPhase.RETRY_WAIT
        for label, error in errors.items():
            logger.error(
                "Launcher shutdown owner remains unsettled: %s (%s)",
                label,
                type(error).__name__,
                exc_info=(type(error), error, error.__traceback__),
            )
        LauncherWindow._set_shutdown_tray_state(self, failed=True)
        LauncherWindow._schedule_shutdown_retry(self)
        return False

    def _quiesce_for_shutdown(self) -> dict[str, Exception]:
        errors: dict[str, Exception] = {}
        self._shutdown_phase = _ShutdownPhase.QUIESCING
        LauncherWindow._set_shutdown_tray_state(self, failed=False)
        self._restart_pending = False
        self._assistant_restart_pending = False

        for name in ("_health_timer", "_data_timer", "_status_timer", "_async_timer"):
            timer = getattr(self, name, None)
            if timer is None:
                continue
            try:
                timer.stop()
            except Exception as exc:
                errors[name] = exc
        try:
            self._stop_engine_down_alarm()
        except Exception as exc:
            errors["engine_down_alarm"] = exc
        try:
            self._invalidate_descriptor_transport()
        except Exception as exc:
            errors["descriptor_transport"] = exc

        snapshot_ingress = getattr(self, "_snapshot_ingress", None)
        if snapshot_ingress is not None:
            try:
                snapshot_ingress.stop()
                if getattr(snapshot_ingress, "active", False):
                    raise RuntimeError("operator snapshot ingress remained active")
            except Exception as exc:
                errors["operator_snapshot_ingress"] = exc
        if not errors:
            self._shutdown_quiesced = True
            self._shutdown_settled.add("operator_snapshot_ingress")
        return errors

    def _settle_safety_worker(self) -> None:
        worker = getattr(self, "_safety_worker", None)
        if worker is None:
            return
        if not worker.isFinished():
            worker.wait(3_000)
        if not worker.isFinished():
            raise RuntimeError("launcher safety-status worker remained alive after bridge shutdown")
        self._safety_worker = None

    def _close_event_loop_exact(self) -> None:
        loop = self._loop
        if loop.is_closed():
            return
        loop.close()
        if not loop.is_closed():
            raise RuntimeError("launcher asyncio loop did not report closed")
        asyncio.set_event_loop(None)

    def _do_shutdown(self) -> bool:
        """Settle every launcher owner before quitting; retry incomplete work."""

        LauncherWindow._ensure_shutdown_state(self)
        if self._shutdown_phase is _ShutdownPhase.COMPLETE:
            return True
        if self._shutdown_attempt_active:
            return False

        self._shutdown_requested = True
        self._shutdown_attempt_active = True
        try:
            if not self._shutdown_quiesced:
                errors = LauncherWindow._quiesce_for_shutdown(self)
                if errors:
                    return LauncherWindow._shutdown_incomplete(self, errors)

            self._shutdown_phase = _ShutdownPhase.SETTLING
            errors: dict[str, Exception] = {}

            def attempt(label: str, action: Callable[[], Any]) -> None:
                if label in self._shutdown_settled:
                    return
                try:
                    action()
                except Exception as exc:
                    errors[label] = exc
                else:
                    self._shutdown_settled.add(label)

            attempt("assistant", self._stop_assistant)
            attempt("bridge_shutdown", self._bridge.shutdown)
            attempt("safety_worker", lambda: LauncherWindow._settle_safety_worker(self))
            if "bridge_shutdown" in self._shutdown_settled:
                attempt("bridge_terminal", self._bridge.close)
            attempt("engine", self._stop_engine)
            soak_capability = getattr(self, "_soak_artifact_capability", None)
            if soak_capability is None:
                self._shutdown_settled.add("soak_artifact")
            else:
                attempt("soak_artifact", soak_capability.close)
            soak_bridge = getattr(self, "_soak_bridge_handshake", None)
            if soak_bridge is None:
                self._shutdown_settled.add("soak_bridge")
            else:
                attempt("soak_bridge", soak_bridge.close)
            if errors:
                return LauncherWindow._shutdown_incomplete(self, errors)

            self._shutdown_phase = _ShutdownPhase.FINALIZING
            attempt("event_loop", lambda: LauncherWindow._close_event_loop_exact(self))
            attempt("application", self._app.quit)
            if errors:
                return LauncherWindow._shutdown_incomplete(self, errors)

            self._shutdown_phase = _ShutdownPhase.COMPLETE
            self._shutdown_last_errors = {}
            self._shutdown_retry_index = 0
            tray = getattr(self, "_tray", None)
            if tray is not None:
                tray.hide()
            return True
        finally:
            self._shutdown_attempt_active = False

    def _tray_open(self) -> None:
        self.showNormal()
        self.activateWindow()

    def _tray_minimize(self) -> None:
        self.hide()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self._tray_only:
                self._on_open_full_gui()
            else:
                self._tray_open()

    # ------------------------------------------------------------------
    # Периодические проверки
    # ------------------------------------------------------------------

    @Slot()
    def _handle_engine_exit(self) -> None:
        """Inspect exit code and decide whether to restart with backoff.

        A4:
        - Exit code 2 (ENGINE_CONFIG_ERROR_EXIT_CODE) → no auto-restart, but
          raise the audible alarm + persistent non-modal banner. Operator
          recovers manually via the always-live «Перезапустить Engine» button.
        - Any other crash → exponential backoff capped at 120s, retry FOREVER.
          Never surrender: unattended acquisition dying silently is the real
          hazard. Alarm + banner stay up the whole time the engine is down.

        Idempotent — guarded by _restart_pending so the 3s health timer can't
        burn through every backoff slot in 15 seconds.
        """
        if self._restart_pending:
            return
        if self._shutdown_requested:
            return

        self._invalidate_descriptor_transport()

        from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE

        returncode: int | None = None
        if self._engine_proc is not None:
            returncode = self._engine_proc.poll()

        if returncode == ENGINE_CONFIG_ERROR_EXIT_CODE:
            logger.critical(
                "Engine exited with CONFIG ERROR (code %d). NOT auto-restarting.",
                returncode,
            )
            self._restart_giving_up = True
            self._engine_proc = None
            self._close_engine_stderr_stream()
            if not self._config_error_modal_shown:
                self._config_error_modal_shown = True
            self._show_engine_down_banner(
                "ОШИБКА КОНФИГУРАЦИИ: Engine не запускается. Автоперезапуск отключён.\n"
                "Исправьте config/*.yaml (см. logs/engine.log), затем нажмите "
                "«Перезапустить Engine»."
            )
            return

        # Retry forever: backoff caps at the last slot (120s), no give-up.
        backoff_idx = min(self._restart_attempts, len(self._restart_backoff_s) - 1)
        delay_s = self._restart_backoff_s[backoff_idx]
        logger.warning(
            "Engine crashed (code=%s). Restart attempt %d in %ds (retrying forever).",
            returncode,
            self._restart_attempts + 1,
            delay_s,
        )
        self._restart_attempts += 1
        self._last_restart_time = time.monotonic()
        self._engine_proc = None
        self._close_engine_stderr_stream()

        self._show_engine_down_banner(
            f"Engine остановлен — перезапуск через {delay_s} с "
            f"(попытка {self._restart_attempts}). Запись данных приостановлена."
        )
        if self._tray.isVisible():
            self._tray.showMessage(
                "CryoDAQ",
                f"Engine остановлен — перезапуск через {delay_s}с (попытка {self._restart_attempts})",
                QSystemTrayIcon.MessageIcon.Warning,
                3000,
            )

        self._restart_pending = True

        def _do_restart() -> None:
            # F2 (Phase A gate, HIGH): this singleShot is not cancelable. If
            # the operator manually restarted meanwhile, _restart_pending was
            # already reset to False — a stale fire here would call
            # _start_engine(wait=False), see the FRESH engine on the command
            # port, misclassify it as external (_engine_external=True), and
            # then _stop_engine() would no-op at shutdown, leaving that engine
            # running. No-op unless this shot is still the live one.
            if self._shutdown_requested or not self._restart_pending:
                self._restart_pending = False
                return
            self._restart_pending = False
            self._invalidate_descriptor_transport()
            self._start_engine(wait=False)

        QTimer.singleShot(delay_s * 1000, _do_restart)

    def _start_engine_down_alarm(self) -> None:
        """Begin a repeating audible alarm while the engine is down.

        Uses QApplication.beep() on a 2s timer — the codebase has no sound
        asset pipeline, and the system bell needs no bundled file and works
        headless. ponytail: system bell, swap for a WAV via QSoundEffect if
        a louder/branded alarm is ever required.
        """
        if self._alarm_timer is None:
            self._alarm_timer = QTimer(self)
            self._alarm_timer.setInterval(2000)
            self._alarm_timer.timeout.connect(QApplication.beep)
        if not self._alarm_timer.isActive():
            QApplication.beep()  # sound immediately, don't wait 2s
            self._alarm_timer.start()

    def _stop_engine_down_alarm(self) -> None:
        if self._alarm_timer is not None:
            self._alarm_timer.stop()

    def _show_engine_down_banner(self, text: str) -> None:
        """Raise the audible alarm and show the persistent non-modal banner."""
        self._start_engine_down_alarm()
        if self._engine_down_banner is not None:
            self._engine_down_banner.setText(text)
            self._engine_down_banner.show()

    def _clear_engine_down_banner(self) -> None:
        """Silence the alarm and hide the banner (engine recovered)."""
        self._stop_engine_down_alarm()
        if self._engine_down_banner is not None:
            self._engine_down_banner.hide()

    def _check_engine_health(self) -> None:
        """Проверить состояние engine, перезапустить при падении."""
        if self._assistant_enabled:
            self._check_assistant_health()
        alive = self._is_engine_alive()

        if alive:
            if not self._tray_only:
                self._engine_indicator.setStyleSheet("color: #2ECC40;")
                self._engine_label.setText("Engine: работает")
            # A4: engine is back — silence alarm and hide the down-banner.
            self._clear_engine_down_banner()
            # Reset the backoff counter after a healthy run window.
            if self._restart_attempts > 0 and time.monotonic() - self._last_restart_time > 300.0:
                logger.info(
                    "Engine healthy for >5min, resetting restart counter (was %d)",
                    self._restart_attempts,
                )
                self._restart_attempts = 0
        else:
            if not self._tray_only:
                self._engine_indicator.setStyleSheet("color: #FF4136;")
                self._engine_label.setText("Engine: остановлен")

            if not self._engine_external and not self._restart_giving_up:
                self._handle_engine_exit()

        # Poll safety state — non-blocking via worker thread
        if alive and self._bridge.is_alive():
            if self._safety_worker is None or self._safety_worker.isFinished():
                worker = ZmqCommandWorker({"cmd": "safety_status"}, parent=self)
                worker.finished.connect(self._on_safety_result)
                self._safety_worker = worker
                worker.start()

        # Tray icon color + tooltip — coarse only. Green requires affirmative
        # connection, safety, and alarm truth; unknown alarm authority must
        # remain caution instead of being inferred as zero.
        data_flowing = self._last_reading_time > 0.0 and (time.monotonic() - self._last_reading_time) < 5.0
        bridge_alive = self._bridge.is_alive()
        tray_truth = resolve_tray_status(
            connected=alive and bridge_alive,
            safety_state=self._last_safety_state,
            alarm_count=self._last_alarm_count,
            data_fresh=data_flowing,
            reporting_fault=self._periodic_reporting_fault,
        )
        icon = {
            TrayLevel.HEALTHY: self._tray_icon_green,
            TrayLevel.CAUTION: self._tray_icon_yellow,
            TrayLevel.FAULT: self._tray_icon_red,
        }[tray_truth.level]
        self._tray.setIcon(icon)
        self._tray.setToolTip(tray_truth.tooltip)

    @Slot(dict)
    def _on_safety_result(self, result: dict) -> None:
        """Handle async safety_status reply."""
        if result.get("ok"):
            self._last_safety_state = result.get("state")

    @Slot()
    def _update_status(self) -> None:
        """Обновить статусную строку."""
        data_flowing = (time.monotonic() - self._last_reading_time) < 5.0
        if data_flowing:
            self._status_conn.setText("⬤ Подключено")
            self._status_conn.setStyleSheet("color: #2ECC40; font-weight: bold;")
        else:
            self._status_conn.setText("⬤ Ожидание данных")
            self._status_conn.setStyleSheet("color: #FFDC00; font-weight: bold;")

    def _tick_async(self) -> None:
        """Прокрутить asyncio event loop."""
        try:
            self._loop.run_until_complete(_tick_coro())
        except Exception as exc:
            # Pump runs every 10 ms; a persistent fault (e.g. the loop closed
            # mid-shutdown) would otherwise be completely invisible. Log once at
            # DEBUG so it is diagnosable without spamming the log every tick.
            if not getattr(self, "_tick_async_warned", False):
                self._tick_async_warned = True
                logger.debug("asyncio pump tick failed (logged once): %s", exc)

    # ------------------------------------------------------------------
    # Window events
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: ANN001
        """Перехватить закрытие окна — свернуть в трей вместо выхода."""
        event.ignore()
        self.hide()
        if self._tray.isVisible():
            self._tray.showMessage(
                "CryoDAQ",
                "Система продолжает работать в фоне.\nДля выхода используйте меню в трее → Выход.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )


async def _tick_coro() -> None:
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Точка входа cryodaq (лаунчер).

    Флаги:
        --mock   Запустить engine в mock-режиме
        --tray   Только иконка в трее (без полного GUI). Полезно для автозагрузки
                 Windows, чтобы оператор видел статус engine без открытия GUI.
    """
    import argparse
    # NOTE: multiprocessing.freeze_support() is called in
    # cryodaq._frozen_main.main_launcher() BEFORE importing this module.
    # Do not add it here — would be too late for the Windows spawn bootloader,
    # because PySide6 is already imported at module load time above.

    parser = argparse.ArgumentParser(description="CryoDAQ Launcher")
    parser.add_argument("--mock", action="store_true", help="Запустить engine в mock-режиме")
    parser.add_argument(
        "--tray",
        action="store_true",
        help="Только иконка в трее — без полного GUI (для автозагрузки)",
    )
    parser.add_argument(
        "--replay",
        nargs="?",
        const=_REPLAY_LIST_SENTINEL,
        default=None,
        metavar="PATH",
        help="Replay mode: путь к SQLite или curve JSON. Без пути — показать доступные источники.",
    )
    parser.add_argument(
        "--replay-speed",
        type=float,
        default=5.0,
        metavar="N",
        help="Коэффициент ускорения replay (default: 5).",
    )
    parser.add_argument(
        "--replay-phase",
        type=str,
        default="cooldown",
        metavar="PHASE",
        help="Зафиксировать фазу для analytics (cooldown/measurement/heating). Default: cooldown.",
    )
    parser.add_argument(
        "--replay-loop",
        action="store_true",
        help="Зациклить replay после конца файла.",
    )
    parser.add_argument(
        "--force-replay",
        action="store_true",
        help="Пропустить проверку занятости ZMQ-портов (override port-collision check).",
    )
    parser.add_argument(
        "--legacy-channel-era",
        type=str,
        default=None,
        metavar="ERA",
        help="Использовать карту переименования каналов для указанной эпохи "
        "(например, 'pre-2025-02'). Применяется только к SQLite/Directory replay.",
    )
    parser.add_argument(
        "--setup-wizard",
        action="store_true",
        help="Показать мастер первого запуска повторно (приборы, обзор безопасности, Telegram).",
    )
    args, remaining = parser.parse_known_args()

    from cryodaq.logging_setup import resolve_log_level, setup_logging

    setup_logging("launcher", level=resolve_log_level())

    mock = args.mock or os.environ.get("CRYODAQ_MOCK") == "1"

    soak_bridge_handshake = _consume_soak_bridge_handshake(
        cli_mock=args.mock,
        tray_only=args.tray,
        replay_requested=args.replay is not None,
        setup_wizard=args.setup_wizard,
    )
    try:
        soak_artifact_capability = _consume_soak_artifact_capability(
            bridge_handshake=soak_bridge_handshake,
            cli_mock=args.mock,
            tray_only=args.tray,
            replay_requested=args.replay is not None,
            setup_wizard=args.setup_wizard,
        )
    except BaseException:
        if soak_bridge_handshake is not None:
            soak_bridge_handshake.close()
        raise

    replay_source: Path | None = None
    if args.replay is not None:
        if args.replay == _REPLAY_LIST_SENTINEL:
            _print_replay_sources()
            sys.exit(0)
        replay_source = Path(args.replay)

    if mock and replay_source is not None:
        print("Ошибка: --mock и --replay взаимно исключают друг друга.", file=sys.stderr)
        sys.exit(1)

    app = QApplication(remaining)
    app.setApplicationName("CryoDAQ")
    app.setOrganizationName("АКЦ ФИАН")
    app.setQuitOnLastWindowClosed(False)  # Не выходить при закрытии окна (трей)

    # B.5.7.3: load bundled fonts BEFORE any widget construction.
    # Must be here (launcher process), not only in gui/app.py (cryodaq-gui
    # entry), because `cryodaq` launcher creates QApplication + MainWindow
    # directly without going through gui/app.py.
    from cryodaq.gui.app import _load_bundled_fonts, apply_fusion_dark_palette

    _load_bundled_fonts()
    # Force Fusion style + theme-token dark palette BEFORE any widget
    # is constructed. Same helper as cryodaq-gui; launcher does not
    # run qdarktheme, so this is the only theme-application on this
    # entry path — critical for Linux systems where system-level
    # GTK themes leak light defaults without it.
    apply_fusion_dark_palette(app)

    # Acquire the process-wide guard before any modal setup UI or config
    # mutation. A second launcher must never race the live process's config.
    lock_fd = try_acquire_lock(".launcher.lock")
    if lock_fd is None:
        QMessageBox.critical(
            None,
            "CryoDAQ",
            "CryoDAQ Launcher уже запущен.\n\n"
            "Используйте уже открытый экземпляр\n"
            "или завершите его через иконку в трее → Выход.",
        )
        sys.exit(0)

    from cryodaq.gui.first_run_config import recover_pending_setup
    from cryodaq.paths import get_config_dir

    try:
        recover_pending_setup(get_config_dir())
    except Exception as exc:
        logger.error("First-run transaction recovery failed (%s)", type(exc).__name__)
        QMessageBox.critical(
            None,
            "CryoDAQ — требуется восстановление настройки",
            "Не удалось безопасно восстановить незавершённую настройку. "
            "Запуск остановлен, чтобы не использовать частично обновлённую "
            "конфигурацию. Проверьте права и свободное место в папке config.",
        )
        sys.exit(1)

    # Normal tray/autostart must remain unattended and nonblocking. An
    # operator can still request the wizard explicitly with --setup-wizard.
    if args.setup_wizard or not args.tray:
        from cryodaq.gui.first_run_wizard import maybe_show_first_run_wizard

        maybe_show_first_run_wizard(force=args.setup_wizard)
    else:
        logger.info("Первичная настройка отложена: launcher запущен в --tray режиме")

    try:
        window = LauncherWindow(
            app,
            mock=mock,
            tray_only=args.tray,
            replay_source=replay_source,
            replay_speed=args.replay_speed,
            replay_phase=args.replay_phase,
            replay_loop=args.replay_loop,
            force_replay=args.force_replay,
            legacy_channel_era=args.legacy_channel_era,
            soak_bridge_handshake=soak_bridge_handshake,
            soak_artifact_capability=soak_artifact_capability,
        )
    except BaseException:
        if soak_bridge_handshake is not None:
            soak_bridge_handshake.close()
        if soak_artifact_capability is not None:
            soak_artifact_capability.close()
        raise
    if not args.tray:
        window.show()
        if replay_source is not None:
            window.setWindowTitle(f"CryoDAQ — REPLAY: {replay_source.name}")

    # Register OS-level signal handlers so SIGTERM (systemd stop, OOM kill)
    # and SIGINT (Ctrl+C) cleanly shut down the engine subprocess rather than
    # orphaning it. The handler is idempotent via _shutdown_requested flag;
    # QTimer.singleShot dispatches _do_shutdown onto the Qt main thread.
    def _signal_handler(signum: int, frame: object) -> None:
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        logger.info("Получен %s, инициирую корректное завершение", sig_name)
        QTimer.singleShot(0, window._do_shutdown)

    signal.signal(signal.SIGINT, _signal_handler)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _signal_handler)

    try:
        exit_code = app.exec()
    finally:
        # The event-loop owner, not LauncherWindow, retains the single-instance
        # lock until Qt has actually returned. Keep the inode stable so another
        # process cannot acquire a replacement path while this process is live.
        release_lock_exact(lock_fd, ".launcher.lock")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
