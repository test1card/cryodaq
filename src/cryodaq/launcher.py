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
import functools
import json
import logging
import logging.handlers
import math
import os
import re
import secrets
import signal
import stat as stat_module
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import IO, Any

from PySide6.QtCore import QThread, QTimer, Signal, Slot
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
from cryodaq.drivers.contracts import parse_global_off_evidence
from cryodaq.drivers.transport.mock_instrument import MockInstrumentEndpoint
from cryodaq.engine import _resolve_mock_mode
from cryodaq.gui.shell.annunciation_controller import decode_projection
from cryodaq.gui.shell.main_window_v2 import MainWindowV2 as MainWindow
from cryodaq.gui.state.operator_snapshot_ingress import start_operator_snapshot_ingress
from cryodaq.gui.tray_status import TrayLevel, resolve_tray_status, tray_icon_for_level
from cryodaq.gui.zmq_client import (
    CLIENT_PROTOCOL_VERSION,
    LateCommandResult,
    ZmqBridge,
    ZmqCommandWorker,
    open_gui_command_worker_admission,
    revoke_gui_command_worker_admission,
    set_bridge,
    settle_registered_gui_command_workers,
)
from cryodaq.instance_lock import release_lock_exact, try_acquire_lock
from cryodaq.operator_snapshot import SnapshotMode

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
# Bound on how long _stop_engine will wait for the engine process to exit
# after a verified shutdown receipt, and the size of each non-blocking poll
# slice within that budget (see _stop_engine's process.poll()/wait() use).
# The shutdown worker's command carries its own timeout. Engine-exit handling polls its
# settlement instead of waiting here so a wedged worker cannot stall the Qt main thread.
_ENGINE_EXIT_WAIT_BUDGET_S = 60.0
_ENGINE_EXIT_POLL_SLICE_S = 1.0
# Bounded, synchronous grace period given to a freshly started
# _EngineShutdownWorker before _stop_engine gives up on this pass and defers
# to the shutdown-retry timer. A reply that lands within this window (the
# common case: the engine is alive and answers quickly) settles in the same
# _stop_engine call as before; a genuinely slow reply (the up-to-~65s
# real-world case Invariant #10 warns about) exceeds it, and control returns
# to the Qt event loop instead of blocking on it.
_ENGINE_SHUTDOWN_WORKER_GRACE_MS = 200
_ENGINE_READY_NONCE_ENV = "CRYODAQ_ENGINE_READY_NONCE"
_CHILD_READY_CHANNEL_ENV = "CRYODAQ_CHILD_READY_CHANNEL"
_ENGINE_READY_SCHEMA = "cryodaq.engine_ready.v2"
_ENGINE_READY_PREFIX = b"CRYODAQ_ENGINE_READY_V2 "
_MAX_ENGINE_READY_BYTES = 8192
_ENGINE_READY_RECEIPT_KEYS = frozenset(
    {"schema", "nonce", "engine_instance_id", "mode", "pid", "pub_addr", "cmd_addr", "safe_cmd_addr"}
)
_REPLAY_READY_NONCE_ENV = "CRYODAQ_REPLAY_READY_NONCE"
_REPLAY_SESSION_ID_ENV = "CRYODAQ_REPLAY_SESSION_ID"
_REPLAY_READY_SCHEMA = "cryodaq.replay_ready.v2"
_REPLAY_READY_PREFIX = b"CRYODAQ_REPLAY_READY_V2 "
_MAX_REPLAY_READY_BYTES = 8192
_REPLAY_READY_RECEIPT_KEYS = frozenset(
    {"schema", "nonce", "session_id", "mode", "source", "speed", "pid", "pub_addr", "cmd_addr", "safe_cmd_addr"}
)
_MAX_ENGINE_STDERR_LINE_BYTES = 4096
_LAUNCHER_SAFETY_STATES = frozenset(
    {"safe_off", "ready", "run_permitted", "running", "fault_latched", "manual_recovery"}
)
_LAUNCHER_SAFETY_STATUS_KEYS = frozenset(
    {
        "ok",
        "state",
        "fault_reason",
        "fault_revision",
        "fault_activated_at",
        "recovery_reason",
        "channels_tracked",
        "keithley_connected",
        "active_channels",
        "mock",
        "engine_instance_id",
        "proto",
    }
)


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate readiness key")
        result[key] = value
    return result


def _decode_engine_ready_receipt(
    raw_line: bytes,
    *,
    expected_nonce: str,
    expected_engine_instance_id: str,
    expected_pid: int,
    expected_pub_addr: str,
    expected_cmd_addr: str,
    expected_safe_cmd_addr: str,
) -> dict[str, Any]:
    """Decode one exact live-child receipt from its private one-shot pipe."""

    if (
        len(raw_line) > _MAX_ENGINE_READY_BYTES
        or not raw_line.startswith(_ENGINE_READY_PREFIX)
        or not raw_line.endswith(b"\n")
        or raw_line.endswith(b"\r\n")
    ):
        raise ValueError("invalid engine readiness frame")
    body = raw_line[len(_ENGINE_READY_PREFIX) : -1]
    payload = json.loads(
        body.decode("ascii", errors="strict"),
        object_pairs_hook=_reject_duplicate_json_pairs,
        parse_constant=lambda _token: (_ for _ in ()).throw(ValueError("non-finite engine readiness value")),
    )
    if (
        type(payload) is not dict
        or set(payload) != _ENGINE_READY_RECEIPT_KEYS
        or payload["schema"] != _ENGINE_READY_SCHEMA
        or type(payload["nonce"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", payload["nonce"]) is None
        or payload["nonce"] != expected_nonce
        or type(payload["engine_instance_id"]) is not str
        or re.fullmatch(r"[0-9a-f]{32}", payload["engine_instance_id"]) is None
        or payload["engine_instance_id"] != expected_engine_instance_id
        or payload["mode"] != "live"
        or type(payload["pid"]) is not int
        or payload["pid"] <= 0
        or payload["pid"] != expected_pid
        or payload["pub_addr"] != expected_pub_addr
        or payload["cmd_addr"] != expected_cmd_addr
        or payload["safe_cmd_addr"] != expected_safe_cmd_addr
    ):
        raise ValueError("mismatched engine readiness receipt")
    return payload


def _decode_replay_ready_receipt(
    raw_line: bytes,
    *,
    expected_nonce: str,
    expected_session_id: str,
    expected_source: str,
    expected_speed: float,
    expected_pid: int,
) -> dict[str, Any]:
    """Decode one exact, bounded child receipt from its private one-shot pipe."""

    if (
        len(raw_line) > _MAX_REPLAY_READY_BYTES
        or not raw_line.startswith(_REPLAY_READY_PREFIX)
        or not raw_line.endswith(b"\n")
        or raw_line.endswith(b"\r\n")
    ):
        raise ValueError("invalid replay readiness frame")
    body = raw_line[len(_REPLAY_READY_PREFIX) : -1]
    payload = json.loads(
        body.decode("ascii", errors="strict"),
        object_pairs_hook=_reject_duplicate_json_pairs,
        parse_constant=lambda _token: (_ for _ in ()).throw(ValueError("non-finite replay readiness value")),
    )
    if (
        type(payload) is not dict
        or set(payload) != _REPLAY_READY_RECEIPT_KEYS
        or payload["schema"] != _REPLAY_READY_SCHEMA
        or payload["nonce"] != expected_nonce
        or payload["session_id"] != expected_session_id
        or payload["mode"] != "replay"
        or payload["source"] != expected_source
        or type(payload["speed"]) is not float
        or payload["speed"] != expected_speed
        or type(payload["pid"]) is not int
        or payload["pid"] != expected_pid
        or payload["pub_addr"] != f"tcp://127.0.0.1:{_ZMQ_PORT}"
        or payload["cmd_addr"] != f"tcp://127.0.0.1:{_ZMQ_PORT + 1}"
        or payload["safe_cmd_addr"] != f"tcp://127.0.0.1:{_ZMQ_PORT + 3}"
    ):
        raise ValueError("mismatched replay readiness receipt")
    return payload


class _ShutdownPhase(Enum):
    """Monotonic launcher shutdown phases."""

    RUNNING = auto()
    QUIESCING = auto()
    SETTLING = auto()
    RETRY_WAIT = auto()
    FINALIZING = auto()
    COMPLETE = auto()


class _EngineShutdownWorker(ZmqCommandWorker):
    """Runs the blocking ``launcher_shutdown`` round-trip off the Qt main thread.

    An ordinary ``ZmqCommandWorker`` is admitted through the process-wide GUI
    command worker registry (``open_gui_command_worker_admission`` /
    ``start_gui_worker_with_ownership``), and that admission is deliberately
    revoked by ``_quiesce_for_shutdown`` before ``_stop_engine`` ever runs.
    Calling the inherited ``.start()`` here would therefore raise "admission
    is closed", and a reply that arrived after closure would be silently
    dropped by ``_deliver_result_if_current``'s admission check (``finished``
    never fires) — exactly the kind of loss the fail-closed HOLD contract
    cannot tolerate.

    This worker IS the shutdown mechanism, not an ordinary GUI command, so
    its lifecycle is instead owned directly by ``_stop_engine``'s own
    polling: it starts the plain ``QThread`` (bypassing the admission gate)
    and its result is read from a plain attribute once ``isFinished()`` is
    true, rather than delivered through the gated ``finished`` signal.

    It also calls the exact ``bridge`` instance ``_stop_engine`` already
    holds (``self._bridge``) rather than going through the module-level
    ``send_command()``/global bridge indirection that the rest of
    ``ZmqCommandWorker`` uses — there is exactly one shutdown bridge per
    launcher instance, captured at dispatch time, and calling it directly
    keeps that identity exact instead of relying on process-global state.
    """

    def __init__(self, cmd: dict, bridge: ZmqBridge, parent=None) -> None:
        super().__init__(cmd, parent=parent)
        self._shutdown_bridge = bridge
        self.result: dict | None = None

    def run(self) -> None:
        try:
            self.result = self._shutdown_bridge.send_command(self._cmd)
        except BaseException as exc:
            self.result = {
                "ok": False,
                "error": "engine shutdown worker execution failed",
                "error_type": type(exc).__name__,
            }


class _LauncherConstructionHold(RuntimeError):
    """Carry a partially constructed launcher that must retain process ownership."""

    def __init__(self, window: LauncherWindow, phase: str) -> None:
        super().__init__(f"launcher construction failed during {phase}; ownership remains in HOLD")
        self.window = window
        self.phase = phase


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


@dataclass(frozen=True, slots=True)
class _LauncherStatusAuthority:
    """Exact engine/bridge cut that owns one asynchronous tray query."""

    callback_epoch: int
    engine_instance_id: str
    bridge_pid: int
    bridge_restart_count: int
    request_generation: int


def _decode_launcher_safety_status(
    payload: object,
    *,
    expected_engine_instance_id: str,
) -> str | None:
    """Decode only the exact engine-bound safety status used by the tray."""

    if (
        type(expected_engine_instance_id) is not str
        or re.fullmatch(r"[0-9a-f]{32}", expected_engine_instance_id) is None
        or type(payload) is not dict
        or set(payload) != _LAUNCHER_SAFETY_STATUS_KEYS
        or payload.get("ok") is not True
        or type(payload.get("proto")) is not int
        or payload["proto"] != CLIENT_PROTOCOL_VERSION
        or payload.get("engine_instance_id") != expected_engine_instance_id
    ):
        return None
    state = payload.get("state")
    active_channels = payload.get("active_channels")
    if (
        state not in _LAUNCHER_SAFETY_STATES
        or type(payload.get("fault_reason")) is not str
        or type(payload.get("fault_revision")) is not int
        or payload["fault_revision"] < 0
        or type(payload.get("fault_activated_at")) is not float
        or not math.isfinite(payload["fault_activated_at"])
        or payload["fault_activated_at"] < 0.0
        or type(payload.get("recovery_reason")) is not str
        or type(payload.get("channels_tracked")) is not int
        or payload["channels_tracked"] < 0
        or type(payload.get("keithley_connected")) is not bool
        or type(payload.get("mock")) is not bool
        or type(active_channels) is not list
        or any(type(channel) is not str or not channel or not channel.isprintable() for channel in active_channels)
        or active_channels != sorted(set(active_channels))
    ):
        return None
    return state


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
        except Exception as exc:
            logger.warning(
                "Startup config parse failed; phase=agent_yaml error=%s",
                exc,
            )

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
        except Exception as exc:
            logger.warning(
                "Startup config parse failed; phase=reporting_yaml error=%s",
                exc,
            )
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
_ENGINE_INSTANCE_ID_ENV = "CRYODAQ_ENGINE_INSTANCE_ID"
_ENGINE_SHUTDOWN_CAPABILITY_ENV = "CRYODAQ_ENGINE_SHUTDOWN_CAPABILITY"
_ENGINE_SHUTDOWN_RECEIPT_SCHEMA = "cryodaq.engine_shutdown.v2"
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
_SOAK_BRIDGE_AT_FORK_REGISTERED = False


class _OwnerSettlementState(Enum):
    """Monotonic state for an OS owner whose close outcome may be ambiguous."""

    OPEN = auto()
    SETTLED = auto()
    POISONED = auto()


class _OwnedFileDescriptor(int):
    """An integer descriptor bound once to its immutable acquisition identity."""

    def __new__(cls, fd: int) -> _OwnedFileDescriptor:
        if type(fd) is not int or fd < 0:
            raise ValueError("owned descriptor must be one non-negative exact integer")
        owner = int.__new__(cls, fd)
        owner.identity = os.fstat(fd)
        owner.settlement_state = _OwnerSettlementState.OPEN
        return owner

    identity: os.stat_result
    settlement_state: _OwnerSettlementState


def _require_open_owned_fd(
    owner: _OwnedFileDescriptor,
    *,
    label: str,
) -> _OwnedFileDescriptor:
    """Prove that one descriptor still denotes its immutable acquisition."""

    if not isinstance(owner, _OwnedFileDescriptor):
        raise RuntimeError(f"{label} descriptor lacks immutable ownership identity")
    if owner.settlement_state is _OwnerSettlementState.POISONED:
        raise RuntimeError(f"{label} descriptor is poisoned; reuse is forbidden")
    if owner.settlement_state is _OwnerSettlementState.SETTLED:
        raise RuntimeError(f"{label} descriptor is already settled")
    try:
        current = os.fstat(owner)
    except OSError as exc:
        if exc.errno == errno.EBADF:
            owner.settlement_state = _OwnerSettlementState.SETTLED
            raise RuntimeError(f"{label} descriptor is already closed") from exc
        owner.settlement_state = _OwnerSettlementState.POISONED
        raise RuntimeError(f"{label} descriptor identity could not be proved") from exc
    if not os.path.samestat(owner.identity, current):
        owner.settlement_state = _OwnerSettlementState.POISONED
        raise RuntimeError(f"{label} descriptor identity changed; reuse is forbidden")
    return owner


def _set_owned_fd_inheritable_exact(
    owner: _OwnedFileDescriptor,
    inheritable: bool,
    *,
    label: str,
) -> None:
    """Change inheritance only for the still-live immutable descriptor."""

    _require_open_owned_fd(owner, label=label)
    os.set_inheritable(owner, inheritable)
    _require_open_owned_fd(owner, label=label)
    try:
        observed = os.get_inheritable(owner)
    except OSError as exc:
        raise RuntimeError(f"{label} inheritance state could not be proved") from exc
    if observed is not inheritable:
        raise RuntimeError(f"{label} inheritance state did not settle exactly")


def _close_owned_fd_exact(owner: _OwnedFileDescriptor, *, label: str) -> None:
    """Close one identity-bound descriptor without ever retrying ambiguity.

    A failed ``close(2)`` may have closed the descriptor even when it reports an
    error. Re-probing cannot distinguish every replacement object (notably
    anonymous Windows pipes), so any still-addressable post-error number is
    permanently poisoned. A later retry must never re-baseline that number.
    """

    if not isinstance(owner, _OwnedFileDescriptor):
        raise RuntimeError(f"{label} descriptor lacks immutable ownership identity")
    if owner.settlement_state is _OwnerSettlementState.SETTLED:
        return
    if owner.settlement_state is _OwnerSettlementState.POISONED:
        raise RuntimeError(f"{label} close outcome is poisoned; unsafe retry refused")

    try:
        current = os.fstat(owner)
    except OSError as exc:
        if exc.errno == errno.EBADF:
            owner.settlement_state = _OwnerSettlementState.SETTLED
            return
        raise RuntimeError(f"{label} descriptor identity could not be read") from exc
    if not os.path.samestat(owner.identity, current):
        owner.settlement_state = _OwnerSettlementState.POISONED
        raise RuntimeError(f"{label} descriptor identity changed; unsafe close refused")

    try:
        os.close(owner)
    except OSError as exc:
        try:
            os.fstat(owner)
        except OSError as probe_error:
            if probe_error.errno == errno.EBADF:
                owner.settlement_state = _OwnerSettlementState.SETTLED
                logger.warning(
                    "%s close reported failure after exact settlement; exception=%s",
                    label,
                    type(exc).__name__,
                )
                return
        owner.settlement_state = _OwnerSettlementState.POISONED
        raise RuntimeError(f"{label} close outcome is ambiguous and permanently poisoned") from exc
    owner.settlement_state = _OwnerSettlementState.SETTLED


class _OwnedFileDescriptorRegistry:
    """Set-compatible registry that retains exact descriptor identities."""

    def __init__(self) -> None:
        self._owners: dict[int, _OwnedFileDescriptor] = {}

    def __contains__(self, descriptor: object) -> bool:
        return isinstance(descriptor, int) and int(descriptor) in self._owners

    def __len__(self) -> int:
        return len(self._owners)

    def add(self, owner: _OwnedFileDescriptor) -> _OwnedFileDescriptor:
        if not isinstance(owner, _OwnedFileDescriptor):
            raise RuntimeError("fork-guard descriptor lacks immutable ownership identity")
        descriptor = int(owner)
        previous = self._owners.get(descriptor)
        if previous is owner:
            return owner
        if previous is not None:
            try:
                current = os.fstat(previous)
            except OSError as exc:
                previous.settlement_state = (
                    _OwnerSettlementState.SETTLED if exc.errno == errno.EBADF else _OwnerSettlementState.POISONED
                )
            else:
                if os.path.samestat(previous.identity, current):
                    raise RuntimeError("fork-guard descriptor already has one live exact owner")
                previous.settlement_state = _OwnerSettlementState.POISONED
        self._owners[descriptor] = owner
        return owner

    def discard(self, descriptor: int | _OwnedFileDescriptor) -> None:
        if not isinstance(descriptor, int):
            return
        current = self._owners.get(int(descriptor))
        if isinstance(descriptor, _OwnedFileDescriptor) and current is not descriptor:
            return
        self._owners.pop(int(descriptor), None)

    def take_all(self) -> tuple[_OwnedFileDescriptor, ...]:
        owners = tuple(self._owners.values())
        self._owners.clear()
        return owners


_SOAK_BRIDGE_ACTIVE_FDS = _OwnedFileDescriptorRegistry()


def _close_soak_bridge_fds_after_fork() -> None:
    """Remove launcher-only authority from a fork child exactly once."""

    for owner in _SOAK_BRIDGE_ACTIVE_FDS.take_all():
        if owner.settlement_state is not _OwnerSettlementState.OPEN:
            continue
        try:
            current = os.fstat(owner)
        except OSError as exc:
            if exc.errno == errno.EBADF:
                owner.settlement_state = _OwnerSettlementState.SETTLED
            else:
                owner.settlement_state = _OwnerSettlementState.POISONED
            continue
        if not os.path.samestat(owner.identity, current):
            owner.settlement_state = _OwnerSettlementState.POISONED
            continue
        try:
            _close_owned_fd_exact(owner, label="fork-child soak authority")
        except RuntimeError:
            # The child must never retry an ambiguous/reused descriptor number.
            # Its private registry was already drained before this attempt.
            continue


def _guard_soak_bridge_fd_from_descendants(
    descriptor: int | _OwnedFileDescriptor,
) -> _OwnedFileDescriptor:
    """Register one identity-bound launcher descriptor for fork-child closure."""

    global _SOAK_BRIDGE_AT_FORK_REGISTERED
    owner = descriptor if isinstance(descriptor, _OwnedFileDescriptor) else _OwnedFileDescriptor(descriptor)
    _set_owned_fd_inheritable_exact(
        owner,
        False,
        label="launcher-retained soak authority",
    )
    if hasattr(os, "register_at_fork") and not _SOAK_BRIDGE_AT_FORK_REGISTERED:
        os.register_at_fork(after_in_child=_close_soak_bridge_fds_after_fork)
        _SOAK_BRIDGE_AT_FORK_REGISTERED = True
    return _SOAK_BRIDGE_ACTIVE_FDS.add(owner)


@dataclass(slots=True)
class _ChildReadyStreamOwner:
    """Discoverable reader owner retained until close is exactly settled."""

    stream: IO[bytes]
    descriptor: _OwnedFileDescriptor | None = field(init=False, default=None)
    settlement_state: _OwnerSettlementState = field(
        init=False,
        default=_OwnerSettlementState.OPEN,
    )

    def __post_init__(self) -> None:
        try:
            fd = self.stream.fileno()
        except (AttributeError, OSError):
            return
        if type(fd) is int and fd >= 0:
            try:
                self.descriptor = _OwnedFileDescriptor(fd)
            except OSError:
                # The stable Python stream object remains discoverable. If its
                # close later fails without proving ``closed``, poison it.
                self.descriptor = None

    @property
    def closed(self) -> bool:
        return self.settlement_state is _OwnerSettlementState.SETTLED

    def read(self, size: int) -> bytes:
        if self.settlement_state is not _OwnerSettlementState.OPEN:
            raise RuntimeError("child readiness stream is not open")
        if self.descriptor is not None:
            _require_open_owned_fd(
                self.descriptor,
                label="child readiness stream",
            )
        return self.stream.read(size)

    def close(self) -> None:
        if self.settlement_state is _OwnerSettlementState.SETTLED:
            return
        if self.settlement_state is _OwnerSettlementState.POISONED:
            raise RuntimeError("child readiness stream close outcome is poisoned; unsafe retry refused")
        if self.descriptor is not None:
            try:
                _require_open_owned_fd(
                    self.descriptor,
                    label="child readiness stream",
                )
            except RuntimeError:
                self.settlement_state = self.descriptor.settlement_state
                raise
        try:
            self.stream.close()
        except Exception as exc:
            conclusively_closed = getattr(self.stream, "closed", False) is True
            descriptor = self.descriptor
            if descriptor is not None:
                try:
                    os.fstat(descriptor)
                except OSError as probe_error:
                    if probe_error.errno == errno.EBADF:
                        descriptor.settlement_state = _OwnerSettlementState.SETTLED
                        conclusively_closed = True
                    else:
                        descriptor.settlement_state = _OwnerSettlementState.POISONED
                else:
                    descriptor.settlement_state = _OwnerSettlementState.POISONED
            if conclusively_closed:
                self.settlement_state = _OwnerSettlementState.SETTLED
            else:
                self.settlement_state = _OwnerSettlementState.POISONED
            raise RuntimeError("child readiness stream close did not settle cleanly") from exc
        else:
            if self.descriptor is not None:
                self.descriptor.settlement_state = _OwnerSettlementState.SETTLED
            self.settlement_state = _OwnerSettlementState.SETTLED


@dataclass(slots=True)
class _SoakBridgeHandshake:
    """Runner-owned pathless evidence stream for an isolated POSIX mock launcher."""

    fd: int
    nonce: str
    _closed: bool = False
    _emitted: bool = False
    _data_sequence: int = 0
    _last_data_emit: float = 0.0
    _fd_owner: _OwnedFileDescriptor | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._fd_owner is None:
            self._fd_owner = _OwnedFileDescriptor(self.fd)
        elif int(self._fd_owner) != self.fd:
            raise RuntimeError("soak bridge owner does not match its descriptor")

    def close(self) -> None:
        if self._closed:
            return
        assert self._fd_owner is not None
        _close_owned_fd_exact(self._fd_owner, label="soak bridge")
        self._closed = True
        _SOAK_BRIDGE_ACTIVE_FDS.discard(self._fd_owner)

    def _quarantine_after_failure(self, primary_failure: BaseException) -> None:
        try:
            self.close()
        except BaseException:
            raise RuntimeError("soak bridge stream failure and quarantine both failed") from primary_failure

    def emit(self, *, bridge_pid: int | None, restart_count: int) -> None:
        if self._closed or self._emitted:
            raise RuntimeError("soak bridge handshake is already closed or emitted")
        assert self._fd_owner is not None
        owner = _require_open_owned_fd(
            self._fd_owner,
            label="soak bridge handshake",
        )
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
        try:
            written = os.write(owner, payload)
        except BaseException as primary_failure:
            self._quarantine_after_failure(primary_failure)
            raise
        if written != len(payload):
            primary_failure = RuntimeError("soak bridge handshake write did not complete atomically")
            self._quarantine_after_failure(primary_failure)
            raise primary_failure
        self._emitted = True

    def emit_data_observed(self, *, bridge_pid: int | None, restart_count: int) -> bool:
        """Best-effort bounded fact that the launcher consumed bridge data.

        The inherited pipe is nonblocking.  Backpressure drops this advisory
        fact instead of stalling the GUI thread; the runner requires a later
        sequence after fault injection before accepting recovery.
        """

        if self._closed or not self._emitted:
            return False
        assert self._fd_owner is not None
        owner = _require_open_owned_fd(
            self._fd_owner,
            label="soak bridge data stream",
        )
        if (
            not isinstance(bridge_pid, int)
            or isinstance(bridge_pid, bool)
            or bridge_pid <= 0
            or bridge_pid == os.getpid()
            or type(restart_count) is not int
            or restart_count != 1
        ):
            primary_failure = RuntimeError("bridge identity changed after positive handshake")
            self._quarantine_after_failure(primary_failure)
            raise primary_failure
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
            primary_failure = RuntimeError("soak bridge data fact exceeds its bound")
            self._quarantine_after_failure(primary_failure)
            raise primary_failure
        try:
            written = os.write(owner, payload)
        except BlockingIOError:
            return False
        except OSError as primary_failure:
            self._quarantine_after_failure(primary_failure)
            return False
        if written != len(payload):
            primary_failure = RuntimeError("soak bridge data fact write was partial")
            self._quarantine_after_failure(primary_failure)
            raise primary_failure
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
    _fd_owner: _OwnedFileDescriptor | None = field(default=None, repr=False)
    _pending_child_grants: dict[int, _OwnedFileDescriptor] = field(
        init=False,
        default_factory=dict,
        repr=False,
    )
    _pending_child_grant_slots: dict[int, _AcquiredDescriptorSlot] = field(
        init=False,
        default_factory=dict,
        repr=False,
    )
    _pending_raw_child_grants: dict[int, _OwnerSettlementState] = field(
        init=False,
        default_factory=dict,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self._fd_owner is None:
            self._fd_owner = _OwnedFileDescriptor(self.fd)
        elif int(self._fd_owner) != self.fd:
            raise RuntimeError("soak artifact owner does not match its descriptor")

    def _require_open_authority(self) -> _OwnedFileDescriptor:
        if self._closed:
            raise RuntimeError("soak artifact capability is closed")
        assert self._fd_owner is not None
        return _require_open_owned_fd(
            self._fd_owner,
            label="soak artifact capability",
        )

    def _settle_raw_child_grant(self, descriptor: int) -> None:
        state = self._pending_raw_child_grants.get(descriptor)
        if state is None or state is _OwnerSettlementState.SETTLED:
            return
        if state is _OwnerSettlementState.POISONED:
            raise RuntimeError("unbound assistant soak duplicate close is poisoned; unsafe retry refused")
        try:
            os.close(descriptor)
        except OSError as exc:
            try:
                os.fstat(descriptor)
            except OSError as probe_error:
                if probe_error.errno == errno.EBADF:
                    self._pending_raw_child_grants[descriptor] = _OwnerSettlementState.SETTLED
                    return
            self._pending_raw_child_grants[descriptor] = _OwnerSettlementState.POISONED
            raise RuntimeError("unbound assistant soak duplicate close remained ambiguous") from exc
        self._pending_raw_child_grants[descriptor] = _OwnerSettlementState.SETTLED

    def validate_child_grant(self, owner: _OwnedFileDescriptor) -> None:
        """Re-prove the retained capability and exact child duplicate."""

        self._require_open_authority()
        registered = self._pending_child_grants.get(int(owner))
        if registered is not owner:
            raise RuntimeError("assistant soak child grant ownership is mismatched")
        _require_open_owned_fd(owner, label="assistant soak child grant")
        try:
            inheritable = os.get_inheritable(owner)
        except OSError as exc:
            raise RuntimeError("assistant soak child grant inheritance could not be proved") from exc
        if inheritable:
            raise RuntimeError("assistant soak child grant became inheritable before spawn")

    def child_grant(self) -> tuple[_OwnedFileDescriptor, int, dict[str, str]]:
        authority = self._require_open_authority()
        candidate = self.generation + 1
        raw_duplicate = os.dup(authority)
        self._pending_raw_child_grants[raw_duplicate] = _OwnerSettlementState.OPEN
        try:
            grant_slot = _AcquiredDescriptorSlot(raw_duplicate)
        except BaseException as primary_error:
            try:
                self._settle_raw_child_grant(raw_duplicate)
            except BaseException:
                raise RuntimeError("unbound assistant soak duplicate could not be settled") from primary_error
            self._pending_raw_child_grants.pop(raw_duplicate, None)
            raise
        self._pending_child_grant_slots[raw_duplicate] = grant_slot
        try:
            duplicate = grant_slot.bind_identity()
        except BaseException as primary_error:
            try:
                grant_slot.settle(label="unbound assistant soak duplicate")
            except BaseException:
                self._pending_raw_child_grants[raw_duplicate] = grant_slot.settlement_state
                raise RuntimeError("unbound assistant soak duplicate could not be settled") from primary_error
            self._pending_child_grant_slots.pop(raw_duplicate, None)
            self._pending_raw_child_grants.pop(raw_duplicate, None)
            raise
        self._pending_raw_child_grants.pop(raw_duplicate, None)
        self._pending_child_grants[int(duplicate)] = duplicate
        try:
            _set_owned_fd_inheritable_exact(
                duplicate,
                False,
                label="assistant soak child grant",
            )
        except BaseException as primary_error:
            try:
                _close_owned_fd_exact(duplicate, label="assistant soak duplicate setup")
            except Exception:
                raise RuntimeError("assistant soak duplicate setup and exact cleanup both failed") from primary_error
            self._pending_child_grants.pop(int(duplicate), None)
            self._pending_child_grant_slots.pop(int(duplicate), None)
            raise
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
        self._require_open_authority()
        if type(candidate) is not int or candidate != self.generation + 1:
            raise RuntimeError("assistant generation commit is invalid")
        self.generation = candidate

    def settle_child_grant(self, owner: _OwnedFileDescriptor) -> None:
        """Settle one exact assistant grant without rebasing its integer."""

        registered = self._pending_child_grants.get(int(owner))
        if registered is not owner:
            raise RuntimeError("assistant soak child grant ownership is mismatched")
        _close_owned_fd_exact(owner, label="assistant soak duplicate")
        slot = self._pending_child_grant_slots.get(int(owner))
        if slot is not None:
            slot.settlement_state = owner.settlement_state
        self._pending_child_grants.pop(int(owner), None)
        self._pending_child_grant_slots.pop(int(owner), None)

    def close(self) -> None:
        if self._closed:
            return
        errors: list[Exception] = []
        for grant in tuple(self._pending_child_grants.values()):
            try:
                self.settle_child_grant(grant)
            except Exception as exc:
                errors.append(exc)
        for descriptor, slot in tuple(self._pending_child_grant_slots.items()):
            if descriptor in self._pending_child_grants:
                continue
            try:
                slot.settle(label="unbound assistant soak duplicate")
            except Exception as exc:
                errors.append(exc)
            else:
                self._pending_child_grant_slots.pop(descriptor, None)
                self._pending_raw_child_grants.pop(descriptor, None)
        for descriptor in tuple(self._pending_raw_child_grants):
            try:
                self._settle_raw_child_grant(descriptor)
            except Exception as exc:
                errors.append(exc)
            else:
                self._pending_raw_child_grants.pop(descriptor, None)
        assert self._fd_owner is not None
        try:
            _close_owned_fd_exact(self._fd_owner, label="soak artifact")
        except Exception as exc:
            errors.append(exc)
        if errors:
            if len(errors) == 1:
                raise errors[0]
            raise RuntimeError("soak artifact ownership settlement remained incomplete") from errors[0]
        self._closed = True
        _SOAK_BRIDGE_ACTIVE_FDS.discard(self._fd_owner)


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
    fd_owner: _OwnedFileDescriptor | None = None
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
        if fd < 3:
            raise RuntimeError("invalid soak artifact capability")
        fd_owner = _OwnedFileDescriptor(fd)
        _require_open_owned_fd(
            fd_owner,
            label="inherited soak artifact capability",
        )
        if not os.get_inheritable(fd_owner) or re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
            raise RuntimeError("invalid soak artifact capability")
        metadata = fd_owner.identity
        if not stat_module.S_ISSOCK(metadata.st_mode):
            raise RuntimeError("soak artifact descriptor is not a socket")
        import fcntl
        import socket

        if fcntl.fcntl(fd_owner, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDWR:
            raise RuntimeError("soak artifact descriptor is not read/write")
        endpoint = socket.socket(fileno=fd_owner)
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
        _guard_soak_bridge_fd_from_descendants(fd_owner)
        return _SoakArtifactCapability(fd, nonce, _fd_owner=fd_owner)
    except BaseException as primary_error:
        cleanup_error: BaseException | None = None
        if fd_owner is not None:
            _SOAK_BRIDGE_ACTIVE_FDS.discard(fd_owner)
            try:
                _close_owned_fd_exact(fd_owner, label="rejected soak artifact capability")
            except BaseException as exc:
                cleanup_error = exc
        elif fd >= 3:
            try:
                os.close(fd)
            except BaseException as exc:
                cleanup_error = exc
        if cleanup_error is not None:
            raise RuntimeError("rejected soak artifact capability cleanup remained ambiguous") from primary_error
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
    fd_owner: _OwnedFileDescriptor | None = None
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
        if fd < 3:
            raise RuntimeError("soak bridge handshake descriptor is not inherited")
        fd_owner = _OwnedFileDescriptor(fd)
        _require_open_owned_fd(
            fd_owner,
            label="inherited soak bridge handshake",
        )
        if re.fullmatch(r"[0-9a-f]{64}", nonce) is None:
            raise RuntimeError("invalid soak bridge handshake nonce")
        if not os.get_inheritable(fd_owner):
            raise RuntimeError("soak bridge handshake descriptor is not inherited")
        metadata = fd_owner.identity
        if not stat_module.S_ISFIFO(metadata.st_mode):
            raise RuntimeError("soak bridge handshake descriptor is not a pipe")
        import fcntl

        if fcntl.fcntl(fd_owner, fcntl.F_GETFL) & os.O_ACCMODE != os.O_WRONLY:
            raise RuntimeError("soak bridge handshake descriptor is not write-only")
        fcntl.fcntl(fd_owner, fcntl.F_SETFL, fcntl.fcntl(fd_owner, fcntl.F_GETFL) | os.O_NONBLOCK)
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
        _guard_soak_bridge_fd_from_descendants(fd_owner)
        return _SoakBridgeHandshake(fd=fd, nonce=nonce, _fd_owner=fd_owner)
    except BaseException as primary_error:
        cleanup_error: BaseException | None = None
        if fd_owner is not None:
            _SOAK_BRIDGE_ACTIVE_FDS.discard(fd_owner)
            try:
                _close_owned_fd_exact(fd_owner, label="rejected soak bridge handshake")
            except BaseException as exc:
                cleanup_error = exc
        elif fd >= 3:
            try:
                os.close(fd)
            except BaseException as exc:
                cleanup_error = exc
        if cleanup_error is not None:
            raise RuntimeError("rejected soak bridge handshake cleanup remained ambiguous") from primary_error
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


class _StrictEngineStderrHandler(logging.handlers.RotatingFileHandler):
    """A rotating handler that never converts persistence failure to green."""

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802
        del record
        failure = sys.exc_info()[1]
        if failure is None:
            raise RuntimeError("engine stderr persistence failed without exception evidence")
        raise failure


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
        failures: list[BaseException] = []
        try:
            prior.flush()
        except BaseException as exc:
            failures.append(exc)
        try:
            prior.close()
        except BaseException as exc:
            failures.append(exc)
        if failures:
            raise RuntimeError("prior engine stderr handler persistence/close was not proven") from failures[0]
        stderr_logger.removeHandler(prior)
    stderr_logger.setLevel(logging.ERROR)
    stderr_logger.propagate = False

    handler = _StrictEngineStderrHandler(
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


@dataclass(slots=True)
class _EngineStderrStreamOwner:
    """Exact child-stderr stream owner shared by launcher and pump thread."""

    stream: IO[bytes]
    descriptor: _OwnedFileDescriptor | None = field(init=False, default=None)
    settlement_state: _OwnerSettlementState = field(
        init=False,
        default=_OwnerSettlementState.OPEN,
    )
    pump_failure: BaseException | None = field(init=False, default=None)
    close_failure: BaseException | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        try:
            descriptor = self.stream.fileno()
        except Exception:
            return
        if type(descriptor) is int and descriptor >= 0:
            try:
                self.descriptor = _OwnedFileDescriptor(descriptor)
            except Exception:
                self.descriptor = None

    def readline(self, size: int) -> bytes:
        if self.settlement_state is not _OwnerSettlementState.OPEN:
            raise RuntimeError("engine stderr stream is not open")
        if self.descriptor is not None:
            _require_open_owned_fd(
                self.descriptor,
                label="engine stderr stream",
            )
        return self.stream.readline(size)

    def settle(self) -> None:
        if self.settlement_state is _OwnerSettlementState.SETTLED:
            return
        if self.settlement_state is _OwnerSettlementState.POISONED:
            raise RuntimeError("engine stderr close outcome is poisoned; unsafe retry refused")
        if self.descriptor is not None:
            try:
                _require_open_owned_fd(
                    self.descriptor,
                    label="engine stderr stream",
                )
            except RuntimeError:
                self.settlement_state = self.descriptor.settlement_state
                raise
        try:
            self.stream.close()
        except BaseException as exc:
            conclusively_closed = getattr(self.stream, "closed", False) is True
            if self.descriptor is not None:
                try:
                    os.fstat(self.descriptor)
                except OSError as probe_error:
                    if probe_error.errno == errno.EBADF:
                        self.descriptor.settlement_state = _OwnerSettlementState.SETTLED
                        conclusively_closed = True
                    else:
                        self.descriptor.settlement_state = _OwnerSettlementState.POISONED
                else:
                    self.descriptor.settlement_state = _OwnerSettlementState.POISONED
            self.settlement_state = (
                _OwnerSettlementState.SETTLED if conclusively_closed else _OwnerSettlementState.POISONED
            )
            raise RuntimeError("engine stderr stream close did not settle cleanly") from exc
        if self.descriptor is not None:
            self.descriptor.settlement_state = _OwnerSettlementState.SETTLED
        self.settlement_state = _OwnerSettlementState.SETTLED


@dataclass(slots=True)
class _EngineStderrAcquisitionOwner:
    """Publish the raw Popen stderr stream before exact wrapping can fail."""

    stream: IO[bytes] | None
    stream_owner: _EngineStderrStreamOwner | None = None
    settlement_state: _OwnerSettlementState = _OwnerSettlementState.OPEN
    binding_failure: BaseException | None = None

    def bind_exact(self) -> _EngineStderrStreamOwner:
        if self.settlement_state is _OwnerSettlementState.POISONED:
            raise RuntimeError("engine stderr acquisition is poisoned")
        if self.settlement_state is _OwnerSettlementState.SETTLED:
            raise RuntimeError("engine stderr acquisition is already settled")
        if self.stream is None:
            failure = RuntimeError("spawned engine did not expose its required stderr pipe")
            self.binding_failure = failure
            raise failure
        if self.stream_owner is None:
            try:
                owner = _EngineStderrStreamOwner(self.stream)
                if owner.descriptor is None:
                    raise RuntimeError("engine stderr pipe lacks an exact raw descriptor owner")
            except BaseException as exc:
                self.binding_failure = exc
                raise
            self.stream_owner = owner
        return self.stream_owner

    def settle(self) -> None:
        if self.settlement_state is _OwnerSettlementState.SETTLED:
            return
        if self.settlement_state is _OwnerSettlementState.POISONED:
            raise RuntimeError("engine stderr acquisition close is poisoned; unsafe retry refused")
        if self.stream_owner is not None:
            try:
                self.stream_owner.settle()
            finally:
                self.settlement_state = self.stream_owner.settlement_state
            return
        if self.stream is None or getattr(self.stream, "closed", False) is True:
            self.settlement_state = _OwnerSettlementState.SETTLED
            return
        try:
            self.stream.close()
        except BaseException as exc:
            self.settlement_state = (
                _OwnerSettlementState.SETTLED
                if getattr(self.stream, "closed", False) is True
                else _OwnerSettlementState.POISONED
            )
            raise RuntimeError("raw engine stderr stream close did not settle cleanly") from exc
        self.settlement_state = _OwnerSettlementState.SETTLED


def _pump_engine_stderr(
    pipe: IO[bytes] | _EngineStderrStreamOwner,
    stderr_logger: logging.Logger,
) -> None:
    """Forward bounded child stderr while retaining exact close evidence."""

    owner = pipe if isinstance(pipe, _EngineStderrStreamOwner) else _EngineStderrStreamOwner(pipe)
    try:
        while True:
            raw_line = owner.readline(_MAX_ENGINE_STDERR_LINE_BYTES + 1)
            if not raw_line:
                break
            if len(raw_line) > _MAX_ENGINE_STDERR_LINE_BYTES or not raw_line.endswith(b"\n"):
                while raw_line and not raw_line.endswith(b"\n"):
                    raw_line = owner.readline(_MAX_ENGINE_STDERR_LINE_BYTES + 1)
                stderr_logger.error("engine stderr line exceeded the forwarding bound")
                continue
            if raw_line.strip():
                stderr_logger.error("engine child stderr record received; phase=runtime")
    except BaseException as exc:
        owner.pump_failure = exc
    finally:
        try:
            owner.settle()
        except BaseException as exc:
            owner.close_failure = exc


@dataclass(slots=True)
class _AcquiredDescriptorSlot:
    """Own one just-acquired integer until identity or transfer is explicit."""

    descriptor: int
    exact_owner: _OwnedFileDescriptor | None = None
    settlement_state: _OwnerSettlementState = _OwnerSettlementState.OPEN
    transferred: bool = False

    def bind_identity(self) -> _OwnedFileDescriptor:
        if self.settlement_state is not _OwnerSettlementState.OPEN or self.transferred:
            raise RuntimeError("descriptor slot is not available for identity binding")
        if self.exact_owner is None:
            self.exact_owner = _OwnedFileDescriptor(self.descriptor)
        return self.exact_owner

    def transfer_to_stream(self) -> None:
        if self.exact_owner is None or self.settlement_state is not _OwnerSettlementState.OPEN:
            raise RuntimeError("descriptor slot cannot transfer without an exact owner")
        self.transferred = True
        self.exact_owner = None
        self.settlement_state = _OwnerSettlementState.SETTLED

    def settle(self, *, label: str) -> None:
        if self.transferred or self.settlement_state is _OwnerSettlementState.SETTLED:
            return
        if self.settlement_state is _OwnerSettlementState.POISONED:
            raise RuntimeError(f"{label} raw descriptor close is poisoned; unsafe retry refused")
        if self.exact_owner is not None:
            try:
                _close_owned_fd_exact(self.exact_owner, label=label)
            finally:
                self.settlement_state = self.exact_owner.settlement_state
            return
        try:
            os.close(self.descriptor)
        except OSError as exc:
            try:
                os.fstat(self.descriptor)
            except OSError as probe_error:
                if probe_error.errno == errno.EBADF:
                    self.settlement_state = _OwnerSettlementState.SETTLED
                    return
            self.settlement_state = _OwnerSettlementState.POISONED
            raise RuntimeError(f"{label} raw descriptor close remained ambiguous") from exc
        self.settlement_state = _OwnerSettlementState.SETTLED


class _ChildReadyPipeAcquisitionError(RuntimeError):
    """Preserve both setup failure and every independent cleanup failure."""

    def __init__(self, primary_failure: BaseException, cleanup_failures: tuple[BaseException, ...]) -> None:
        super().__init__(
            "child readiness pipe acquisition failed and cleanup remained incomplete; "
            f"primary={type(primary_failure).__name__} cleanup="
            + ",".join(type(failure).__name__ for failure in cleanup_failures)
        )
        self.primary_failure = primary_failure
        self.cleanup_failures = cleanup_failures


class _EngineSpawnCleanupError(RuntimeError):
    """Retain the spawn failure and every independent owner cleanup failure."""

    def __init__(self, primary_failure: BaseException, cleanup_failures: tuple[BaseException, ...]) -> None:
        super().__init__(
            "engine spawn failed and owner cleanup remained incomplete; "
            f"primary={type(primary_failure).__name__} cleanup="
            + ",".join(type(failure).__name__ for failure in cleanup_failures)
        )
        self.primary_failure = primary_failure
        self.cleanup_failures = cleanup_failures


@dataclass(slots=True)
class _ChildReadyPipeOwner:
    """Aggregate owner published before any readiness-pipe setup can fail."""

    raw_read_descriptor: int | None = None
    raw_write_descriptor: int | None = None
    raw_read_settlement_state: _OwnerSettlementState = _OwnerSettlementState.SETTLED
    raw_write_settlement_state: _OwnerSettlementState = _OwnerSettlementState.SETTLED
    read_slot: _AcquiredDescriptorSlot | None = None
    write_slot: _AcquiredDescriptorSlot | None = None
    stream_owner: _ChildReadyStreamOwner | None = None
    primary_failure: BaseException | None = None
    cleanup_failures: tuple[BaseException, ...] = ()

    def publish_raw_pair(self, read_descriptor: int, write_descriptor: int) -> None:
        """Publish both pipe integers before any fallible wrapper exists."""

        self.raw_read_descriptor = read_descriptor
        self.raw_write_descriptor = write_descriptor
        self.raw_read_settlement_state = _OwnerSettlementState.OPEN
        self.raw_write_settlement_state = _OwnerSettlementState.OPEN
        if type(read_descriptor) is not int or read_descriptor < 0:
            raise RuntimeError("child readiness raw reader is invalid")
        if type(write_descriptor) is not int or write_descriptor < 0:
            raise RuntimeError("child readiness raw writer is invalid")

    def _settle_raw_descriptor(self, *, reader: bool) -> None:
        descriptor = self.raw_read_descriptor if reader else self.raw_write_descriptor
        state_name = "raw_read_settlement_state" if reader else "raw_write_settlement_state"
        state = getattr(self, state_name)
        label = "child readiness reader" if reader else "child readiness writer"
        if descriptor is None or state is _OwnerSettlementState.SETTLED:
            return
        if state is _OwnerSettlementState.POISONED:
            raise RuntimeError(f"{label} raw descriptor close is poisoned; unsafe retry refused")
        try:
            os.close(descriptor)
        except OSError as exc:
            try:
                os.fstat(descriptor)
            except OSError as probe_error:
                if probe_error.errno == errno.EBADF:
                    setattr(self, state_name, _OwnerSettlementState.SETTLED)
                    return
            setattr(self, state_name, _OwnerSettlementState.POISONED)
            raise RuntimeError(f"{label} raw descriptor close remained ambiguous") from exc
        setattr(self, state_name, _OwnerSettlementState.SETTLED)

    def settle_writer(self) -> None:
        if self.write_slot is not None:
            try:
                self.write_slot.settle(label="child readiness writer")
            finally:
                self.raw_write_settlement_state = self.write_slot.settlement_state
        else:
            self._settle_raw_descriptor(reader=False)

    def settle_stream(self) -> None:
        if self.stream_owner is not None:
            try:
                self.stream_owner.close()
            finally:
                self.raw_read_settlement_state = self.stream_owner.settlement_state
        elif self.read_slot is not None:
            try:
                self.read_slot.settle(label="child readiness reader")
            finally:
                self.raw_read_settlement_state = self.read_slot.settlement_state
        else:
            self._settle_raw_descriptor(reader=True)

    def settle_all_after_failed_acquisition(self, primary_failure: BaseException) -> None:
        self.primary_failure = primary_failure
        failures: list[BaseException] = []
        # Reader cleanup may fail, but writer cleanup remains independently
        # mandatory so the child-facing endpoint is never silently leaked.
        for action in (self.settle_stream, self.settle_writer):
            try:
                action()
            except BaseException as exc:
                failures.append(exc)
        self.cleanup_failures = tuple(failures)
        if failures:
            raise _ChildReadyPipeAcquisitionError(primary_failure, tuple(failures)) from primary_failure

    @property
    def fully_settled(self) -> bool:
        read_settled = (
            self.raw_read_settlement_state is _OwnerSettlementState.SETTLED
            and (self.stream_owner is None or self.stream_owner.settlement_state is _OwnerSettlementState.SETTLED)
            and (
                self.read_slot is None
                or self.read_slot.transferred
                or self.read_slot.settlement_state is _OwnerSettlementState.SETTLED
            )
        )
        write_settled = self.raw_write_settlement_state is _OwnerSettlementState.SETTLED and (
            self.write_slot is None or self.write_slot.settlement_state is _OwnerSettlementState.SETTLED
        )
        return read_settled and write_settled


_CHILD_READY_PIPE_OWNER_CONTEXT = threading.local()


def _open_child_ready_pipe() -> tuple[IO[bytes], _OwnedFileDescriptor, str, dict[str, Any]]:
    """Create a one-child pipe and the exact Popen inheritance controls."""

    capsule = getattr(_CHILD_READY_PIPE_OWNER_CONTEXT, "owner", None)
    if not isinstance(capsule, _ChildReadyPipeOwner):
        capsule = _ChildReadyPipeOwner()
    try:
        read_fd, write_fd = os.pipe()
        # Publish both acquired integers into the aggregate before fstat,
        # inheritance, fdopen, or platform-handle setup can fail.
        capsule.publish_raw_pair(read_fd, write_fd)
        capsule.read_slot = _AcquiredDescriptorSlot(read_fd)
        capsule.write_slot = _AcquiredDescriptorSlot(write_fd)
        read_owner = capsule.read_slot.bind_identity()
        write_owner = capsule.write_slot.bind_identity()
        if not stat_module.S_ISFIFO(read_owner.identity.st_mode) or not stat_module.S_ISFIFO(
            write_owner.identity.st_mode
        ):
            raise OSError("readiness descriptors are not one pipe")
        _set_owned_fd_inheritable_exact(
            read_owner,
            False,
            label="child readiness reader",
        )
        _set_owned_fd_inheritable_exact(
            write_owner,
            False,
            label="child readiness writer",
        )
        read_stream = os.fdopen(read_owner, "rb", buffering=0)
        capsule.stream_owner = _ChildReadyStreamOwner(read_stream)
        capsule.read_slot.transfer_to_stream()
        if sys.platform == "win32":
            import msvcrt

            handle = msvcrt.get_osfhandle(write_owner)
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.lpAttributeList = {"handle_list": [handle]}
            return (
                read_stream,
                write_owner,
                f"handle:{handle}",
                {
                    "close_fds": True,
                    "startupinfo": startupinfo,
                },
            )
        return read_stream, write_owner, f"fd:{write_owner}", {"pass_fds": (write_owner,)}
    except BaseException as primary_failure:
        capsule.settle_all_after_failed_acquisition(primary_failure)
        raise


def _read_engine_ready_receipt(
    pipe: IO[bytes],
    engine_ready: threading.Event,
    engine_state: dict[str, Any],
    engine_state_lock: threading.Lock,
    *,
    expected_nonce: str,
    expected_engine_instance_id: str,
    expected_pid: int,
    expected_pub_addr: str,
    expected_cmd_addr: str,
    expected_safe_cmd_addr: str,
) -> None:
    """Read one bounded live-child frame through EOF from its private pipe."""

    receipt: dict[str, Any] | None = None
    error: str | None = None
    try:
        raw_buffer = bytearray()
        while True:
            remaining = (_MAX_ENGINE_READY_BYTES + 1) - len(raw_buffer)
            if remaining <= 0:
                error = "invalid"
                break
            chunk = pipe.read(min(4096, remaining))
            if type(chunk) is not bytes:
                error = "invalid"
                break
            if not chunk:
                break
            raw_buffer.extend(chunk)
            if len(raw_buffer) > _MAX_ENGINE_READY_BYTES:
                error = "invalid"
                break
        raw = bytes(raw_buffer)
        if error is not None:
            receipt = None
        elif len(raw) > _MAX_ENGINE_READY_BYTES or raw.count(b"\n") != 1 or b"\r" in raw or not raw.endswith(b"\n"):
            error = "invalid"
        else:
            receipt = _decode_engine_ready_receipt(
                raw,
                expected_nonce=expected_nonce,
                expected_engine_instance_id=expected_engine_instance_id,
                expected_pid=expected_pid,
                expected_pub_addr=expected_pub_addr,
                expected_cmd_addr=expected_cmd_addr,
                expected_safe_cmd_addr=expected_safe_cmd_addr,
            )
    except (UnicodeDecodeError, json.JSONDecodeError, OSError, RuntimeError, TypeError, ValueError):
        error = "invalid"
    finally:
        try:
            pipe.close()
        except Exception:
            error = "close"
        with engine_state_lock:
            engine_state["receipt"] = receipt if error is None else None
            engine_state["error"] = error
        engine_ready.set()


def _read_replay_ready_receipt(
    pipe: IO[bytes],
    replay_ready: threading.Event,
    replay_state: dict[str, Any],
    replay_state_lock: threading.Lock,
    *,
    expected_replay_nonce: str,
    expected_replay_session_id: str,
    expected_replay_source: str,
    expected_replay_speed: float,
    expected_replay_pid: int,
) -> None:
    """Read one bounded frame through EOF from the dedicated child channel."""

    receipt: dict[str, Any] | None = None
    error: str | None = None
    try:
        raw_buffer = bytearray()
        while True:
            remaining = (_MAX_REPLAY_READY_BYTES + 1) - len(raw_buffer)
            if remaining <= 0:
                error = "invalid"
                break
            chunk = pipe.read(min(4096, remaining))
            if type(chunk) is not bytes:
                error = "invalid"
                break
            if not chunk:
                break
            raw_buffer.extend(chunk)
            if len(raw_buffer) > _MAX_REPLAY_READY_BYTES:
                error = "invalid"
                break
        raw = bytes(raw_buffer)
        if error is not None:
            receipt = None
        elif len(raw) > _MAX_REPLAY_READY_BYTES or raw.count(b"\n") != 1 or b"\r" in raw or not raw.endswith(b"\n"):
            error = "invalid"
        else:
            receipt = _decode_replay_ready_receipt(
                raw,
                expected_nonce=expected_replay_nonce,
                expected_session_id=expected_replay_session_id,
                expected_source=expected_replay_source,
                expected_speed=expected_replay_speed,
                expected_pid=expected_replay_pid,
            )
    except (UnicodeDecodeError, json.JSONDecodeError, OSError, RuntimeError, TypeError, ValueError):
        error = "invalid"
    finally:
        try:
            pipe.close()
        except Exception:
            error = "close"
        with replay_state_lock:
            replay_state["receipt"] = receipt if error is None else None
            replay_state["error"] = error
        replay_ready.set()


def _is_port_busy(port: int) -> bool:
    """Check whether any live/replay transport endpoint is occupied."""
    import socket

    for p in (port, port + 1, port + 3):  # PUB=5555, ordinary CMD=5556, safe CMD=5558
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


def _request_engine_ready_reply(command: dict[str, Any], *, address: str | None = None) -> object:
    """Send one bounded read-only engine-incarnation challenge."""

    import zmq

    context = zmq.Context()
    socket = None
    try:
        socket = context.socket(zmq.REQ)
        socket.setsockopt(zmq.RCVTIMEO, 500)
        socket.setsockopt(zmq.SNDTIMEO, 500)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.MAXMSGSIZE, _MAX_ENGINE_READY_BYTES)
        socket.connect(address or f"tcp://127.0.0.1:{_ZMQ_PORT + 1}")
        socket.send_json(command)
        raw = socket.recv()
        if type(raw) is not bytes or len(raw) > _MAX_ENGINE_READY_BYTES or b"\r" in raw or b"\n" in raw:
            raise ValueError("invalid engine readiness reply frame")
        return json.loads(
            raw.decode("ascii", errors="strict"),
            object_pairs_hook=_reject_duplicate_json_pairs,
            parse_constant=lambda _token: (_ for _ in ()).throw(ValueError("non-finite engine readiness reply value")),
        )
    finally:
        if socket is not None:
            socket.close(linger=0)
        context.term()


class LauncherWindow(QMainWindow):
    """Главное окно лаунчера — встраивает MainWindow и управляет engine."""

    _reading_received = Signal(object)

    def __init__(
        self,
        app: QApplication,
        *,
        mock: bool = False,
        mock_thermal_simulator: str | None = None,
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
        self._mock_thermal_simulator = mock_thermal_simulator
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
        self._engine_instance_id: str | None = None
        self._engine_shutdown_capability: str | None = None
        self._engine_shutdown_request_id: str | None = None
        self._engine_shutdown_transport_identity: tuple[str, int] | None = None
        self._engine_shutdown_receipt: dict[str, Any] | None = None
        self._engine_unsettled_incarnation: tuple[str, int | None] | None = None
        self._engine_stderr_handler: logging.Handler | None = None
        self._engine_stderr_logger: logging.Logger | None = None
        self._engine_stderr_thread: threading.Thread | None = None
        self._engine_stderr_acquisition_owner: _EngineStderrAcquisitionOwner | None = None
        self._engine_stderr_stream_owner: _EngineStderrStreamOwner | None = None
        self._engine_stderr_persistence_failure: BaseException | None = None
        self._engine_ready_thread: threading.Thread | None = None
        self._child_ready_pipe_owner: _ChildReadyPipeOwner | None = None
        self._child_ready_stream_owner: _ChildReadyStreamOwner | None = None
        self._child_ready_write_fd_owner: _OwnedFileDescriptor | None = None
        self._engine_ready = threading.Event()
        self._engine_ready_state: dict[str, Any] = {"receipt": None, "error": None}
        self._engine_ready_lock = threading.Lock()
        self._engine_ready_nonce: str | None = None
        self._external_engine_ready_receipt: dict[str, Any] | None = None
        self._replay_ready_thread: threading.Thread | None = None
        self._replay_ready = threading.Event()
        self._replay_ready_state: dict[str, Any] = {"receipt": None, "error": None}
        self._replay_ready_lock = threading.Lock()
        self._replay_ready_nonce: str | None = None
        self._replay_session_id: str | None = None
        self._replay_session_verified: bool = False
        self._engine_external = False  # True если engine запущен кем-то другим
        # A4: exponential backoff for engine restart attempts. Retry FOREVER —
        # a dead overnight acquisition with nobody told is worse than any
        # restart storm. Backoff caps at the last slot (120s) and never gives
        # up. Reset after a 5-min healthy run. Only exit code 2 (config error)
        # latches no-auto-restart.
        self._restart_attempts: int = 0
        self._last_restart_time: float = 0.0
        self._restart_backoff_s: list[int] = [3, 10, 30, 60, 120]
        # Latched for config errors or any restart owner that cannot be
        # settled exactly; neither condition may silently re-enter backoff.
        self._restart_giving_up: bool = False
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
        self._restart_generation: int = 0
        self._bridge_watchdog_generation: int = 0
        self._bridge_restart_fault: bool = False
        self._bridge_restart_hold: bool = False
        self._shutdown_requested: bool = False
        self._shutdown_phase = _ShutdownPhase.RUNNING
        self._shutdown_attempt_active = False
        self._shutdown_retry_pending = False
        self._shutdown_retry_index = 0
        self._shutdown_quiesced = False
        self._shutdown_settled: set[str] = set()
        self._shutdown_last_errors: dict[str, Exception] = {}
        self._shutdown_failure_notified = False
        self._shutdown_hold_audible = False
        self._shutdown_hold_timer: QTimer | None = None
        self._runtime_callbacks_open = True
        self._runtime_callback_epoch = 1
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
        self._annunciation_worker: ZmqCommandWorker | None = None
        self._engine_shutdown_worker: ZmqCommandWorker | None = None
        self._engine_shutdown_wait_deadline: float | None = None
        self._safety_status_generation = 0
        self._annunciation_status_generation = 0
        self._main_window: MainWindow | None = None
        self._snapshot_ingress: Any | None = None
        self._tray: QSystemTrayIcon | None = None
        self._data_timer: QTimer | None = None
        self._health_timer: QTimer | None = None
        self._status_timer: QTimer | None = None
        self._async_timer: QTimer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bridge: ZmqBridge | None = None
        self._gui_worker_session_epoch: int | None = None
        self._construction_failure_phase: str | None = None

        # cryodaq-assistant (Гемма + RAG + automatic report reconciliation)
        # remains the existing third supervised child. It is
        # spawned when either optional LLM or automatic reporting needs it.
        # Restart/backoff mirrors the engine child, but its death is NON-safety:
        # log + tray note only — no alarm, no banner, no giving-up latch.
        self._assistant_proc: subprocess.Popen | None = None
        self._assistant_shutdown_path: Path | None = None
        self._assistant_shutdown_authority: _AssistantShutdownAuthority | None = None
        self._assistant_soak_duplicate_owner: _OwnedFileDescriptor | None = None
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
        self._periodic_reporting_fault: bool | None = None if self._assistant_periodic_requested else False
        self._assistant_restart_attempts: int = 0
        self._assistant_last_restart_time: float = 0.0
        self._assistant_restart_pending: bool = False
        self._assistant_restart_generation: int = 0
        self._assistant_unsettled_start_failure: BaseException | None = None

        if replay_source is not None:
            self.setWindowTitle(f"CryoDAQ — REPLAY: {replay_source.name}")
        else:
            self.setWindowTitle("CryoDAQ — Криогенная лаборатория АКЦ ФИАН")
        self.setMinimumSize(1360, 860)

        # This composition root alone begins the process-wide GUI worker
        # session. A second/partial window cannot reopen or replace it.
        self._gui_worker_session_epoch = open_gui_command_worker_admission()

        # --- Asyncio ---
        # pyzmq requires a SelectorEventLoop on Windows (not the default
        # Proactor). Build it explicitly instead of the deprecated
        # WindowsSelectorEventLoopPolicy (policy system deprecated in Python
        # 3.14+). On other platforms the selector loop is already the default.
        self._run_construction_step("async_runtime", self._construct_async_runtime)

        # --- ZMQ Bridge subprocess ---
        self._run_construction_step("bridge_bootstrap", self._construct_bridge_runtime)

        # Acquisition needs the command path for exact shutdown settlement, so
        # establish it first. Replay has no hazardous shutdown authority and
        # must not start a bridge until its own engine wins the port race.
        if self._replay_source is None:
            self._run_construction_step("bridge", self._bridge.start)
            self._run_construction_step("engine", self._start_engine)
        else:
            self._run_construction_step("engine", self._start_engine)

        # --- Assistant (B1) ---
        if self._assistant_enabled:
            self._run_construction_step("assistant", self._start_assistant)

        # Start ZMQ bridge subprocess — skip if replay engine failed to start
        # so the bridge doesn't silently attach to a live engine.
        if self._replay_engine_failed:
            QTimer.singleShot(200, self._show_replay_engine_failure)
        else:
            if self._replay_source is not None:
                self._run_construction_step("bridge", self._bridge.start)
            if self._soak_bridge_handshake is not None:
                self._run_construction_step(
                    "soak_bridge_handshake",
                    lambda: self._soak_bridge_handshake.emit(
                        bridge_pid=self._bridge.process_pid(),
                        restart_count=self._bridge.restart_count(),
                    ),
                )

        if tray_only:
            self._main_window = None
            self._run_construction_step("tray", self._build_tray)
        else:
            self._run_construction_step("ui", self._build_ui)
            self._run_construction_step("tray", self._build_tray)

        # --- Таймеры ---
        # Data polling from ZMQ bridge subprocess
        self._run_construction_step(
            "data_timer",
            lambda: self._start_runtime_timer(
                "_data_timer",
                interval_ms=10,
                callback=self._poll_bridge_data,
            ),
        )
        self._run_construction_step(
            "health_timer",
            lambda: self._start_runtime_timer(
                "_health_timer",
                interval_ms=3000,
                callback=self._check_engine_health,
            ),
        )

        if not tray_only:
            self._run_construction_step(
                "status_timer",
                lambda: self._start_runtime_timer(
                    "_status_timer",
                    interval_ms=1000,
                    callback=self._update_status,
                ),
            )

    # ------------------------------------------------------------------
    # Engine management
    # ------------------------------------------------------------------

    def _construct_async_runtime(self) -> None:
        """Anchor the loop and timer before any fallible setup can escape."""

        if sys.platform == "win32":
            loop = asyncio.SelectorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        timer = QTimer(self)
        self._async_timer = timer
        timer.setInterval(10)
        timer.timeout.connect(self._tick_async)
        timer.start()

    def _construct_bridge_runtime(self) -> None:
        """Anchor bridge ownership before registration and signal wiring."""

        bridge = ZmqBridge()
        self._bridge = bridge
        set_bridge(bridge)
        self._reading_received.connect(self._on_reading_qt)

    def _runtime_callback_is_current(self, epoch: int | None = None) -> bool:
        return (
            getattr(self, "_runtime_callbacks_open", True)
            and not getattr(self, "_shutdown_requested", False)
            and (epoch is None or epoch == getattr(self, "_runtime_callback_epoch", -1))
        )

    def _revoke_runtime_callbacks(self) -> None:
        if getattr(self, "_runtime_callbacks_open", True):
            self._runtime_callback_epoch = getattr(self, "_runtime_callback_epoch", 0) + 1
        self._runtime_callbacks_open = False

    def _start_runtime_timer(
        self,
        attribute: str,
        *,
        interval_ms: int,
        callback: Callable[[], Any],
    ) -> None:
        timer = QTimer(self)
        setattr(self, attribute, timer)
        timer.setInterval(interval_ms)
        timer.timeout.connect(callback)
        timer.start()

    def _run_construction_step(
        self,
        phase: str,
        action: Callable[[], Any],
    ) -> Any:
        """Run one constructor phase or transfer the live owner into HOLD."""

        try:
            return action()
        except _LauncherConstructionHold:
            raise
        except BaseException as exc:
            self._construction_failure_phase = phase
            logger.critical(
                "Launcher construction failed; phase=%s exception=%s",
                phase,
                type(exc).__name__,
            )
            if LauncherWindow._do_shutdown(self):
                raise
            try:
                self.setWindowTitle("CryoDAQ — HOLD: incomplete startup settlement")
                self.show()
            except RuntimeError:
                logger.critical("Construction HOLD could not render a window")
            raise _LauncherConstructionHold(self, phase) from None

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

    def _settle_retained_child_ready_write_fd(self) -> None:
        """Close only the exact parent readiness writer still owned here."""

        write_fd = getattr(self, "_child_ready_write_fd_owner", None)
        capsule = getattr(self, "_child_ready_pipe_owner", None)
        if write_fd is not None:
            if not isinstance(write_fd, _OwnedFileDescriptor):
                raise RuntimeError("retained child readiness writer identity is invalid")
            if (
                isinstance(capsule, _ChildReadyPipeOwner)
                and capsule.write_slot is not None
                and capsule.write_slot.exact_owner is not write_fd
            ):
                raise RuntimeError("retained child readiness writer disagrees with its aggregate owner")
            _close_owned_fd_exact(write_fd, label="child readiness writer")
            self._child_ready_write_fd_owner = None
            if isinstance(capsule, _ChildReadyPipeOwner) and capsule.write_slot is not None:
                capsule.write_slot.settlement_state = write_fd.settlement_state
                capsule.raw_write_settlement_state = write_fd.settlement_state
        elif isinstance(capsule, _ChildReadyPipeOwner):
            capsule.settle_writer()
        if isinstance(capsule, _ChildReadyPipeOwner) and capsule.fully_settled:
            self._child_ready_pipe_owner = None

    def _settle_retained_child_ready_stream(self) -> None:
        """Close only the modeled readiness stream whose reader is terminal."""

        ready_stream = getattr(self, "_child_ready_stream_owner", None)
        capsule = getattr(self, "_child_ready_pipe_owner", None)
        if ready_stream is not None:
            if not isinstance(ready_stream, _ChildReadyStreamOwner):
                raise RuntimeError("retained child readiness stream identity is invalid")
            if isinstance(capsule, _ChildReadyPipeOwner) and capsule.stream_owner is not ready_stream:
                raise RuntimeError("retained child readiness stream disagrees with its aggregate owner")
            ready_stream.close()
            self._child_ready_stream_owner = None
            if isinstance(capsule, _ChildReadyPipeOwner):
                capsule.raw_read_settlement_state = ready_stream.settlement_state
        elif isinstance(capsule, _ChildReadyPipeOwner):
            capsule.settle_stream()
        if isinstance(capsule, _ChildReadyPipeOwner) and capsule.fully_settled:
            self._child_ready_pipe_owner = None

    def _settle_retained_child_readiness_owners(self) -> None:
        """Settle pre-transfer readiness owners without dropping failed ones."""

        errors: list[Exception] = []
        try:
            LauncherWindow._settle_retained_child_ready_write_fd(self)
        except Exception as exc:
            errors.append(exc)

        try:
            LauncherWindow._settle_retained_child_ready_stream(self)
        except Exception as exc:
            errors.append(exc)

        if errors:
            raise RuntimeError("child readiness owner settlement remained incomplete") from errors[0]

    def _mark_failed_engine_startup_owner_hold(
        self,
        *,
        phase: str,
        failure: BaseException,
    ) -> None:
        """Keep a spawned child and its authority visible until exact stop."""

        self._restart_giving_up = True
        if getattr(self, "_replay_source", None) is not None:
            self._replay_session_verified = False
        logger.critical(
            "Spawned engine startup remains in HOLD; phase=%s pid=%s failure=%s",
            phase,
            getattr(getattr(self, "_engine_proc", None), "pid", None),
            type(failure).__name__,
        )

    def _start_engine(self) -> None:
        """Запустить engine как подпроцесс (или подключиться к существующему)."""
        unsettled = getattr(self, "_engine_unsettled_incarnation", None)
        if unsettled is not None:
            raise RuntimeError("prior engine incarnation lacks exact shutdown settlement; restart remains in HOLD")
        if getattr(self, "_engine_proc", None) is not None or any(
            value is not None
            for value in (
                getattr(self, "_engine_instance_id", None),
                getattr(self, "_engine_shutdown_capability", None),
                getattr(self, "_engine_shutdown_request_id", None),
                getattr(self, "_engine_shutdown_transport_identity", None),
                getattr(self, "_engine_shutdown_receipt", None),
                getattr(self, "_engine_ready_nonce", None),
                getattr(self, "_child_ready_stream_owner", None),
                getattr(self, "_child_ready_write_fd_owner", None),
                getattr(self, "_child_ready_pipe_owner", None),
                getattr(self, "_engine_ready_thread", None),
                getattr(self, "_replay_ready_thread", None),
                getattr(self, "_engine_stderr_acquisition_owner", None),
                getattr(self, "_engine_stderr_stream_owner", None),
                getattr(self, "_engine_stderr_thread", None),
                getattr(self, "_engine_stderr_logger", None),
                getattr(self, "_engine_stderr_handler", None),
                getattr(self, "_engine_stderr_persistence_failure", None),
                getattr(self, "_replay_ready_nonce", None),
                getattr(self, "_replay_session_id", None),
            )
        ):
            raise RuntimeError("prior launcher-owned engine authority remains live")
        if (
            getattr(self, "_engine_external", False)
            or getattr(self, "_external_engine_ready_receipt", None) is not None
        ):
            raise RuntimeError("prior external engine incarnation observation remains live")
        if self._replay_source is not None:
            replay_verified = vars(self).get("_replay_session_verified", False)
            if type(replay_verified) is not bool or replay_verified:
                raise RuntimeError("prior verified replay child authority remains live")
            self._replay_session_verified = False
            self._replay_engine_failed = False
        if self._replay_source is None:
            self._check_predictor_bootstrap_hint()

        # Existing engine processes are never adopted.  A writable PID file
        # plus a self-consistent REP response is self-attestation, not an
        # independently rooted ownership proof.  A held lock therefore fails
        # closed before this launcher creates any child or bridge authority.
        from cryodaq.paths import get_data_dir

        lock_path = get_data_dir() / ".engine.lock"
        if os.path.lexists(lock_path):
            probe_fd: int | None = None
            try:
                probe_fd = os.open(str(lock_path), os.O_RDWR)
                if not _opened_real_regular_file_matches(lock_path, probe_fd):
                    raise RuntimeError("engine lock path is not one exact regular object")
                lock_held = False
                try:
                    if sys.platform == "win32":
                        import msvcrt

                        os.lseek(probe_fd, 0, os.SEEK_SET)
                        msvcrt.locking(probe_fd, msvcrt.LK_NBLCK, 1)
                        msvcrt.locking(probe_fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(probe_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(probe_fd, fcntl.LOCK_UN)
                except OSError:
                    lock_held = True

                if not _opened_real_regular_file_matches(lock_path, probe_fd):
                    raise RuntimeError("engine lock object changed during ownership probe")
                if lock_held:
                    raise RuntimeError("engine lock is held; unauthenticated external adoption is refused")
                logger.info("Stale engine lock object is free; proceeding with child start")
            except RuntimeError:
                raise
            except OSError as exc:
                raise RuntimeError("engine lock could not be inspected exactly") from exc
            finally:
                if probe_fd is not None:
                    try:
                        os.close(probe_fd)
                    except OSError:
                        pass

        if _is_port_busy(_ZMQ_PORT):
            raise RuntimeError("engine ports are occupied without an adoptable exact lock-bound incarnation")

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
            cmd.extend(["--safe-cmd-addr", f"tcp://127.0.0.1:{_ZMQ_PORT + 3}"])
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
        engine_instance_id: str | None = None
        engine_shutdown_capability: str | None = None
        engine_ready_nonce: str | None = None
        replay_ready_nonce: str | None = None
        replay_session_id: str | None = None
        if self._replay_source is None:
            engine_instance_id = uuid.uuid4().hex
            engine_shutdown_capability = secrets.token_hex(32)
            engine_ready_nonce = secrets.token_hex(32)
            env[_ENGINE_INSTANCE_ID_ENV] = engine_instance_id
            env[_ENGINE_SHUTDOWN_CAPABILITY_ENV] = engine_shutdown_capability
            env[_ENGINE_READY_NONCE_ENV] = engine_ready_nonce
            env.pop(_REPLAY_READY_NONCE_ENV, None)
            env.pop(_REPLAY_SESSION_ID_ENV, None)
        else:
            env.pop(_ENGINE_INSTANCE_ID_ENV, None)
            env.pop(_ENGINE_SHUTDOWN_CAPABILITY_ENV, None)
            env.pop(_ENGINE_READY_NONCE_ENV, None)
            replay_ready_nonce = secrets.token_hex(32)
            replay_session_id = secrets.token_hex(16)
            env[_REPLAY_READY_NONCE_ENV] = replay_ready_nonce
            env[_REPLAY_SESSION_ID_ENV] = replay_session_id
        if self._replay_source is None:
            env["CRYODAQ_MOCK"] = "1" if self._mock else "0"
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
        mock_thermal_simulator = getattr(self, "_mock_thermal_simulator", None)
        if mock_thermal_simulator is not None and self._replay_source is None:
            cmd.extend(["--mock-thermal-simulator", mock_thermal_simulator])

        stderr_logger, stderr_handler, stderr_path = _create_engine_stderr_logger()
        self._engine_stderr_logger = stderr_logger
        self._engine_stderr_handler = stderr_handler
        if self._replay_source is None:
            if not isinstance(getattr(self, "_engine_ready", None), threading.Event):
                self._engine_ready = threading.Event()
            if not isinstance(getattr(self, "_engine_ready_lock", None), type(threading.Lock())):
                self._engine_ready_lock = threading.Lock()
            self._engine_ready.clear()
            with self._engine_ready_lock:
                self._engine_ready_state = {"receipt": None, "error": None}
        else:
            if not isinstance(getattr(self, "_replay_ready", None), threading.Event):
                self._replay_ready = threading.Event()
            if not isinstance(getattr(self, "_replay_ready_lock", None), type(threading.Lock())):
                self._replay_ready_lock = threading.Lock()
            self._replay_ready.clear()
            with self._replay_ready_lock:
                self._replay_ready_state = {"receipt": None, "error": None}
        ready_pipe_owner = _ChildReadyPipeOwner()
        self._child_ready_pipe_owner = ready_pipe_owner
        previous_ready_pipe_owner = getattr(_CHILD_READY_PIPE_OWNER_CONTEXT, "owner", None)
        _CHILD_READY_PIPE_OWNER_CONTEXT.owner = ready_pipe_owner
        try:
            ready_stream, ready_write_fd, ready_channel, popen_readiness = _open_child_ready_pipe()
        except BaseException as primary_failure:
            cleanup_failure: BaseException | None = None
            try:
                LauncherWindow._close_engine_stderr_stream(self)
            except BaseException as exc:
                cleanup_failure = exc
            if ready_pipe_owner.fully_settled:
                self._child_ready_pipe_owner = None
            if cleanup_failure is not None:
                raise RuntimeError(
                    "child readiness acquisition and launcher owner cleanup both failed"
                ) from primary_failure
            raise
        finally:
            if previous_ready_pipe_owner is None:
                try:
                    del _CHILD_READY_PIPE_OWNER_CONTEXT.owner
                except AttributeError:
                    pass
            else:
                _CHILD_READY_PIPE_OWNER_CONTEXT.owner = previous_ready_pipe_owner
        if ready_pipe_owner.stream_owner is None:
            # Compatibility for injected test factories: production always
            # publishes through the aggregate before returning.
            ready_pipe_owner.stream_owner = _ChildReadyStreamOwner(ready_stream)
        if ready_pipe_owner.write_slot is None:
            if not isinstance(ready_write_fd, _OwnedFileDescriptor):
                ready_write_fd = _OwnedFileDescriptor(ready_write_fd)
            ready_pipe_owner.write_slot = _AcquiredDescriptorSlot(
                int(ready_write_fd),
                exact_owner=ready_write_fd,
            )
        ready_stream_owner = ready_pipe_owner.stream_owner
        self._child_ready_stream_owner = ready_stream_owner
        self._child_ready_write_fd_owner = ready_write_fd
        env[_CHILD_READY_CHANNEL_ENV] = ready_channel
        try:
            if sys.platform == "win32":
                _set_owned_fd_inheritable_exact(
                    ready_write_fd,
                    True,
                    label="child readiness writer for engine spawn",
                )
            process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
                **popen_readiness,
            )
        except BaseException as primary_failure:
            cleanup_failures: list[BaseException] = []
            if sys.platform == "win32":
                try:
                    _set_owned_fd_inheritable_exact(
                        ready_write_fd,
                        False,
                        label="failed-spawn child readiness writer",
                    )
                except BaseException as exc:
                    cleanup_failures.append(exc)
            try:
                LauncherWindow._settle_retained_child_readiness_owners(self)
            except BaseException as exc:
                cleanup_failures.append(exc)
            try:
                LauncherWindow._close_engine_stderr_stream(self)
            except BaseException as exc:
                cleanup_failures.append(exc)
            self._engine_instance_id = None
            self._engine_shutdown_capability = None
            self._engine_shutdown_request_id = None
            self._engine_shutdown_transport_identity = None
            self._engine_shutdown_receipt = None
            self._engine_unsettled_incarnation = None
            self._engine_shutdown_worker = None
            self._engine_shutdown_wait_deadline = None
            if cleanup_failures:
                raise _EngineSpawnCleanupError(
                    primary_failure,
                    tuple(cleanup_failures),
                ) from primary_failure
            raise

        # Publish the successful child and its exact incarnation before any
        # descriptor cleanup or reader construction can fail. Rollback/stop
        # can therefore always see and settle the spawned process.
        self._engine_proc = process
        self._engine_instance_id = engine_instance_id
        self._engine_shutdown_capability = engine_shutdown_capability
        self._engine_shutdown_request_id = None
        self._engine_shutdown_transport_identity = None
        self._engine_shutdown_receipt = None
        self._engine_unsettled_incarnation = None
        self._engine_shutdown_worker = None
        self._engine_shutdown_wait_deadline = None
        self._engine_ready_nonce = engine_ready_nonce
        self._replay_ready_nonce = replay_ready_nonce
        self._replay_session_id = replay_session_id
        self._engine_external = False
        self._external_engine_ready_receipt = None
        # Popen is the raw stderr acquisition boundary. Publish even a missing
        # or malformed stream before wrapping so rollback can never lose the
        # exact object returned by the child constructor.
        stderr_acquisition_owner = _EngineStderrAcquisitionOwner(process.stderr)
        self._engine_stderr_acquisition_owner = stderr_acquisition_owner

        inheritable_reset_error: BaseException | None = None
        if sys.platform == "win32":
            try:
                _set_owned_fd_inheritable_exact(
                    ready_write_fd,
                    False,
                    label="parent child readiness writer",
                )
            except BaseException as exc:
                inheritable_reset_error = exc
        try:
            LauncherWindow._settle_retained_child_ready_write_fd(self)
        except Exception as exc:
            LauncherWindow._mark_failed_engine_startup_owner_hold(
                self,
                phase="parent-ready-writer-close",
                failure=exc,
            )
            raise
        if inheritable_reset_error is not None:
            logger.warning(
                "Child readiness writer inheritance reset failed before exact close; exception=%s",
                type(inheritable_reset_error).__name__,
            )

        try:
            self._engine_stderr_stream_owner = stderr_acquisition_owner.bind_exact()
        except BaseException as exc:
            LauncherWindow._mark_failed_engine_startup_owner_hold(
                self,
                phase="stderr-acquisition",
                failure=exc,
            )
            raise

        ready_thread: threading.Thread | None = None
        try:
            if self._replay_source is None:
                if engine_ready_nonce is None or engine_instance_id is None:
                    raise RuntimeError("live engine readiness authority was not constructed")
                ready_thread = threading.Thread(
                    target=_read_engine_ready_receipt,
                    args=(
                        ready_stream_owner,
                        self._engine_ready,
                        self._engine_ready_state,
                        self._engine_ready_lock,
                    ),
                    kwargs={
                        "expected_nonce": engine_ready_nonce,
                        "expected_engine_instance_id": engine_instance_id,
                        "expected_pid": process.pid,
                        "expected_pub_addr": f"tcp://127.0.0.1:{_ZMQ_PORT}",
                        "expected_cmd_addr": f"tcp://127.0.0.1:{_ZMQ_PORT + 1}",
                        "expected_safe_cmd_addr": f"tcp://127.0.0.1:{_ZMQ_PORT + 3}",
                    },
                    name="engine-ready-reader",
                    daemon=True,
                )
                self._engine_ready_thread = ready_thread
            else:
                ready_thread = threading.Thread(
                    target=_read_replay_ready_receipt,
                    args=(
                        ready_stream_owner,
                        self._replay_ready,
                        self._replay_ready_state,
                        self._replay_ready_lock,
                    ),
                    kwargs={
                        "expected_replay_nonce": replay_ready_nonce,
                        "expected_replay_session_id": replay_session_id,
                        "expected_replay_source": str(self._replay_source),
                        "expected_replay_speed": float(self._replay_speed),
                        "expected_replay_pid": process.pid,
                    },
                    name="replay-ready-reader",
                    daemon=True,
                )
                self._replay_ready_thread = ready_thread
            ready_thread.start()
        except BaseException as exc:
            LauncherWindow._mark_failed_engine_startup_owner_hold(
                self,
                phase="readiness-reader-start",
                failure=exc,
            )
            raise
        stderr_stream_owner = self._engine_stderr_stream_owner
        try:
            stderr_thread = threading.Thread(
                target=_pump_engine_stderr,
                args=(stderr_stream_owner, stderr_logger),
                name="engine-stderr-pump",
                daemon=True,
            )
            self._engine_stderr_thread = stderr_thread
            stderr_thread.start()
        except BaseException as exc:
            LauncherWindow._mark_failed_engine_startup_owner_hold(
                self,
                phase="stderr-pump-start",
                failure=exc,
            )
            raise
        logger.info("Engine запущен, PID=%d; stderr capture active", process.pid)

        # Every owned child must prove its exact private/public incarnation
        # before the caller may attach the bridge.  There is intentionally no
        # construction-only or compatibility bypass for this safety gate.
        self._wait_engine_ready()
        if self._replay_source is not None:
            session_id = self._replay_session_id
            if type(session_id) is not str:
                raise RuntimeError("verified replay session identity is unavailable")
            self._bridge.bind_verified_replay_session(
                session_id=session_id,
                source=str(self._replay_source),
                speed=float(self._replay_speed),
            )
            self._replay_session_verified = True

    def _close_engine_stderr_stream(self) -> None:
        errors: list[Exception] = []
        try:
            LauncherWindow._settle_retained_child_ready_write_fd(self)
        except Exception as exc:
            errors.append(exc)

        readiness_threads_settled = True
        for attribute, label in (
            ("_engine_ready_thread", "engine readiness reader"),
            ("_replay_ready_thread", "replay readiness reader"),
        ):
            ready_thread = getattr(self, attribute, None)
            if ready_thread is None:
                continue
            try:
                if ready_thread.is_alive():
                    ready_thread.join(timeout=2.0)
                if ready_thread.is_alive():
                    raise RuntimeError(f"{label} remained alive after bounded join")
            except Exception as exc:
                readiness_threads_settled = False
                errors.append(exc)
            else:
                setattr(self, attribute, None)

        # The child is already terminal when this method is called. Never
        # close a reader-owned stream concurrently: first prove its thread is
        # dead, then settle the exact retained stream object or keep it in HOLD.
        if readiness_threads_settled:
            try:
                LauncherWindow._settle_retained_child_ready_stream(self)
            except Exception as exc:
                errors.append(exc)

        stderr_thread_settled = True
        thread = getattr(self, "_engine_stderr_thread", None)
        if thread is not None:
            try:
                if thread.is_alive():
                    thread.join(timeout=2.0)
                if thread.is_alive():
                    raise RuntimeError("engine stderr pump remained alive after bounded join")
            except Exception as exc:
                stderr_thread_settled = False
                errors.append(exc)
            else:
                self._engine_stderr_thread = None

        stderr_stream_settled = stderr_thread_settled
        stderr_acquisition_owner = getattr(self, "_engine_stderr_acquisition_owner", None)
        stderr_stream_owner = getattr(self, "_engine_stderr_stream_owner", None)
        if stderr_acquisition_owner is not None and not isinstance(
            stderr_acquisition_owner,
            _EngineStderrAcquisitionOwner,
        ):
            stderr_stream_settled = False
            errors.append(RuntimeError("raw engine stderr acquisition ownership is invalid"))
        if (
            isinstance(stderr_acquisition_owner, _EngineStderrAcquisitionOwner)
            and stderr_stream_owner is not None
            and stderr_acquisition_owner.stream_owner is not stderr_stream_owner
        ):
            stderr_stream_settled = False
            errors.append(RuntimeError("raw and exact engine stderr owners disagree"))
        if stderr_thread_settled and stderr_stream_settled and stderr_stream_owner is not None:
            if not isinstance(stderr_stream_owner, _EngineStderrStreamOwner):
                stderr_stream_settled = False
                errors.append(RuntimeError("engine stderr stream ownership is invalid"))
            else:
                try:
                    if stderr_stream_owner.settlement_state is _OwnerSettlementState.OPEN:
                        stderr_stream_owner.settle()
                except Exception as exc:
                    stderr_stream_settled = False
                    errors.append(exc)
                if stderr_stream_owner.pump_failure is not None:
                    stderr_stream_settled = False
                    pump_error = RuntimeError("engine stderr pump terminated with a recorded read failure")
                    pump_error.__cause__ = stderr_stream_owner.pump_failure
                    errors.append(pump_error)
                if stderr_stream_owner.close_failure is not None:
                    stderr_stream_settled = False
                    close_error = RuntimeError("engine stderr pump recorded an incomplete close")
                    close_error.__cause__ = stderr_stream_owner.close_failure
                    errors.append(close_error)
                if stderr_stream_owner.settlement_state is not _OwnerSettlementState.SETTLED:
                    stderr_stream_settled = False
                    errors.append(RuntimeError("engine stderr stream did not reach exact settlement"))
        if (
            stderr_thread_settled
            and isinstance(stderr_acquisition_owner, _EngineStderrAcquisitionOwner)
            and (
                stderr_acquisition_owner.stream_owner is None
                or (
                    stderr_acquisition_owner.stream_owner is stderr_stream_owner
                    and isinstance(stderr_stream_owner, _EngineStderrStreamOwner)
                    and stderr_stream_owner.settlement_state is _OwnerSettlementState.SETTLED
                )
            )
        ):
            try:
                stderr_acquisition_owner.settle()
                if stderr_acquisition_owner.settlement_state is not _OwnerSettlementState.SETTLED:
                    raise RuntimeError("raw engine stderr acquisition did not reach exact settlement")
            except Exception as exc:
                stderr_stream_settled = False
                errors.append(exc)
        if stderr_thread_settled and stderr_stream_settled:
            self._engine_stderr_stream_owner = None
            self._engine_stderr_acquisition_owner = None

        stderr_logger = getattr(self, "_engine_stderr_logger", None)
        stderr_handler = getattr(self, "_engine_stderr_handler", None)
        prior_persistence_failure = getattr(self, "_engine_stderr_persistence_failure", None)
        if prior_persistence_failure is not None:
            persistence_error = RuntimeError("engine stderr persistence has a retained terminal failure")
            persistence_error.__cause__ = prior_persistence_failure
            errors.append(persistence_error)
        if not stderr_thread_settled:
            pass
        elif stderr_logger is None and stderr_handler is None:
            pass
        elif stderr_logger is None or stderr_handler is None:
            ownership_error = RuntimeError("engine stderr logger ownership is inconsistent")
            if getattr(self, "_engine_stderr_persistence_failure", None) is None:
                self._engine_stderr_persistence_failure = ownership_error
            errors.append(ownership_error)
        elif prior_persistence_failure is not None:
            pass
        else:
            handler_failures: list[BaseException] = []
            try:
                stderr_handler.flush()
            except BaseException as exc:
                handler_failures.append(exc)
            try:
                stderr_handler.close()
            except BaseException as exc:
                handler_failures.append(exc)
            if handler_failures:
                self._engine_stderr_persistence_failure = handler_failures[0]
                for failure in handler_failures:
                    if isinstance(failure, Exception):
                        errors.append(failure)
                    else:
                        wrapped = RuntimeError("engine stderr handler settlement raised a base exception")
                        wrapped.__cause__ = failure
                        errors.append(wrapped)
            else:
                try:
                    stderr_logger.removeHandler(stderr_handler)
                except Exception as exc:
                    self._engine_stderr_persistence_failure = exc
                    errors.append(exc)
                else:
                    self._engine_stderr_handler = None
                    self._engine_stderr_logger = None

        if errors:
            raise errors[0]

    def _settle_crashed_engine_readers_or_hold(
        self,
        *,
        owner_id: str,
        returncode: int | None,
        phase: str,
    ) -> bool:
        """Settle crashed-child readers after HOLD is already operator-visible."""

        try:
            self._close_engine_stderr_stream()
        except Exception as exc:
            self._engine_unsettled_incarnation = (owner_id, returncode)
            self._restart_giving_up = True
            logger.critical(
                "Engine reader settlement failed in HOLD; phase=%s owner=%s exception=%s",
                phase,
                owner_id,
                type(exc).__name__,
            )
            self._show_engine_down_banner(
                "HOLD: engine process ended but its readiness/stderr readers remain unsettled. "
                "Restart and launcher exit are blocked."
            )
            return False
        return True

    def _probe_exact_live_engine_session(self) -> bool:
        """Bind the private child receipt to one exact REP incarnation."""

        process = self._engine_proc
        instance_id = self._engine_instance_id
        ready_nonce = getattr(self, "_engine_ready_nonce", None)
        with self._engine_ready_lock:
            receipt = self._engine_ready_state.get("receipt")
            receipt_error = self._engine_ready_state.get("error")
        if (
            getattr(self, "_replay_source", None) is not None
            or process is None
            or process.poll() is not None
            or type(instance_id) is not str
            or type(ready_nonce) is not str
            or not self._engine_ready.is_set()
            or receipt_error is not None
            or type(receipt) is not dict
            or set(receipt) != _ENGINE_READY_RECEIPT_KEYS
            or receipt.get("nonce") != ready_nonce
            or receipt.get("engine_instance_id") != instance_id
            or receipt.get("pid") != process.pid
        ):
            return False
        challenge = {
            "cmd": "engine_ready",
            "nonce": receipt["nonce"],
            "engine_instance_id": instance_id,
            "pid": process.pid,
            "pub_addr": receipt["pub_addr"],
            "cmd_addr": receipt["cmd_addr"],
            "safe_cmd_addr": receipt["safe_cmd_addr"],
        }
        for address in (receipt["cmd_addr"], receipt["safe_cmd_addr"]):
            try:
                reply = _request_engine_ready_reply(challenge, address=address)
            except Exception:
                return False
            if not (
                type(reply) is dict
                and set(reply) == (_ENGINE_READY_RECEIPT_KEYS | {"ok", "proto"})
                and reply == {"ok": True, **receipt, "proto": CLIENT_PROTOCOL_VERSION}
                and process.poll() is None
            ):
                return False
        return process.poll() is None

    def _probe_external_engine_incarnation(self, expected_pid: int) -> dict[str, Any] | None:
        """External engine adoption has no independently rooted authority."""

        _ = expected_pid
        return None

    def _probe_exact_replay_session(self) -> bool:
        """Prove the private child-ready observation matches the REP session."""

        process = self._engine_proc
        with self._replay_ready_lock:
            receipt = self._replay_ready_state.get("receipt")
            receipt_error = self._replay_ready_state.get("error")
        if (
            self._replay_source is None
            or process is None
            or process.poll() is not None
            or not self._replay_ready.is_set()
            or receipt_error is not None
            or type(receipt) is not dict
            or set(receipt) != _REPLAY_READY_RECEIPT_KEYS
            or receipt.get("nonce") != self._replay_ready_nonce
            or receipt.get("session_id") != self._replay_session_id
            or receipt.get("pid") != process.pid
        ):
            return False
        challenge = {"cmd": "replay_ready", **receipt}
        encoded_challenge = json.dumps(
            challenge,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        if len(encoded_challenge) > _MAX_REPLAY_READY_BYTES:
            return False
        context = None
        socket = None
        try:
            import zmq

            context = zmq.Context()
            for address in (receipt["cmd_addr"], receipt["safe_cmd_addr"]):
                socket = context.socket(zmq.REQ)
                try:
                    socket.setsockopt(zmq.RCVTIMEO, 500)
                    socket.setsockopt(zmq.SNDTIMEO, 500)
                    socket.setsockopt(zmq.LINGER, 0)
                    socket.setsockopt(zmq.MAXMSGSIZE, _MAX_REPLAY_READY_BYTES)
                    socket.connect(address)
                    if process.poll() is not None:
                        return False
                    socket.send(encoded_challenge)
                    raw = socket.recv()
                    if (
                        type(raw) is not bytes
                        or not raw
                        or len(raw) > _MAX_REPLAY_READY_BYTES
                        or b"\r" in raw
                        or b"\n" in raw
                    ):
                        return False
                    reply = json.loads(
                        raw.decode("ascii", errors="strict"),
                        object_pairs_hook=_reject_duplicate_json_pairs,
                        parse_constant=lambda _token: (_ for _ in ()).throw(
                            ValueError("non-finite replay readiness reply value")
                        ),
                    )
                    if not (
                        type(reply) is dict
                        and set(reply) == (_REPLAY_READY_RECEIPT_KEYS | {"ok", "proto"})
                        and reply == {"ok": True, **receipt, "proto": CLIENT_PROTOCOL_VERSION}
                        and process.poll() is None
                    ):
                        return False
                finally:
                    socket.close(linger=0)
                    socket = None
            return process.poll() is None
        except Exception:  # noqa: BLE001 - every malformed/unavailable proof fails closed
            return False
        finally:
            if socket is not None:
                socket.close(linger=0)
            if context is not None:
                context.term()

    def _wait_engine_ready(self, max_attempts: int = 10, interval_s: float = 0.5) -> None:
        """Wait for exact child/session readiness, never port occupancy alone."""
        for attempt in range(max_attempts):
            time.sleep(interval_s)
            if self._replay_source is not None:
                process = self._engine_proc
                if process is None or process.poll() is not None:
                    self._replay_engine_failed = True
                    raise RuntimeError("replay child exited before exact readiness")
                if self._replay_ready.is_set():
                    with self._replay_ready_lock:
                        if self._replay_ready_state.get("error") is not None:
                            self._replay_engine_failed = True
                            raise RuntimeError("replay child emitted an invalid readiness receipt")
                if self._probe_exact_replay_session():
                    logger.info(
                        "Replay engine exact child/session readiness established (attempt %d/%d, pid=%d)",
                        attempt + 1,
                        max_attempts,
                        process.pid,
                    )
                    return
                continue
            process = self._engine_proc
            if process is None or process.poll() is not None:
                raise RuntimeError("live engine child exited before exact readiness")
            if self._engine_ready.is_set():
                with self._engine_ready_lock:
                    if self._engine_ready_state.get("error") is not None:
                        raise RuntimeError("live engine child emitted an invalid readiness receipt")
            if self._probe_exact_live_engine_session():
                logger.info(
                    "Live engine exact child/incarnation readiness established (attempt %d/%d, pid=%d)",
                    attempt + 1,
                    max_attempts,
                    process.pid,
                )
                return
        if self._replay_source is not None:
            self._replay_engine_failed = True
            raise RuntimeError("replay child did not establish exact session readiness")
        raise RuntimeError("live engine child did not establish exact live engine readiness")

    def _show_replay_engine_failure(self) -> None:
        """Show error and close when the replay engine could not start."""
        if not LauncherWindow._runtime_callback_is_current(self):
            return
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(
            self,
            "Replay Engine Failed",
            "The replay engine could not start.\n\n"
            "The newly started replay child did not establish its exact command session.\n"
            "No bridge was attached. Check the replay source and engine logs.",
        )
        self.close()

    def _settle_observed_engine_exit(self, *, owner_id: str, returncode: int | None, phase: str) -> bool:
        """Finish with an incarnation whose exit was observed. True if it settled.

        Three steps that must not drift apart, and did: settle the crashed child's readers
        or HOLD, release the handle, then retire the identity. Two callers need exactly
        this -- the crash handler, and the recovery path for a REPLACEMENT that died before
        readiness -- so they share it rather than each keeping their own copy.
        """

        if not LauncherWindow._settle_crashed_engine_readers_or_hold(
            self,
            owner_id=owner_id,
            returncode=returncode,
            phase=phase,
        ):
            return False
        if getattr(self, "_replay_source", None) is not None:
            self._engine_proc = None
            LauncherWindow._reset_replay_readiness_authority(self)
            return True
        if not LauncherWindow._retire_observed_engine_incarnation(self):
            self._show_engine_down_banner(
                "HOLD: the engine shutdown worker is still running, so this incarnation "
                "cannot be retired. Restart remains blocked."
            )
            return False
        self._engine_proc = None
        return True

    def _settle_engine_shutdown_worker(self) -> bool:
        """Poll the shutdown worker. False means it is still running.

        The worker is a QThread whose run() is blocked inside send_command on the very
        bridge the recovery path is about to shut down. Dropping the only reference to it
        while it runs is how Qt gets to destroy a live thread -- and that stops the
        launcher rather than recovering it, which is the opposite of the point.

        Its command carries its own timeout. If it is still running the reference is KEPT
        and the next health tick polls again; an owner that cannot be settled is the one
        thing that must still hold.
        """

        worker = getattr(self, "_engine_shutdown_worker", None)
        if worker is None:
            return True
        try:
            settled = worker.isFinished() is True
        except Exception as exc:
            logger.critical(
                "Engine shutdown worker could not be observed; phase=retire exception=%s",
                type(exc).__name__,
            )
            return False
        if not settled:
            logger.critical("Engine shutdown worker is still running; its owner cannot be retired")
            return False
        self._engine_shutdown_worker = None
        return True

    def _retire_observed_engine_incarnation(self) -> bool:
        """Release the identity of an incarnation whose exit was observed.

        The sibling of _reset_replay_readiness_authority, for the live child.

        Clearing the process handle is not enough. _start_engine refuses to spawn while
        ANY of the previous incarnation's identity is still published -- instance id,
        shutdown capability, request id, transport identity, receipt, ready nonce -- and
        that refusal is right: two engines sharing one identity is two writers on one
        database. But an incarnation we watched exit is over, and leaving its identity
        published turned the scheduled restart into a refusal, then a _stop_engine call
        with no handle and retained authority, which is exactly the lost-handle HOLD this
        crash path exists to avoid. The crash would have been converted back into the
        stop it was meant to replace.

        These are the same fields the clean-shutdown path releases on its own success.
        The readers are settled before this runs, not by this.

        Returns False when the shutdown worker is still running, because that owner cannot
        be dropped while it is inside a command on a bridge that is about to close.
        """

        if not LauncherWindow._settle_engine_shutdown_worker(self):
            return False
        self._engine_instance_id = None
        self._engine_shutdown_capability = None
        self._engine_shutdown_request_id = None
        self._engine_shutdown_transport_identity = None
        self._engine_shutdown_receipt = None
        self._engine_shutdown_wait_deadline = None
        self._engine_ready_nonce = None
        if not isinstance(getattr(self, "_engine_ready", None), threading.Event):
            self._engine_ready = threading.Event()
        if not isinstance(getattr(self, "_engine_ready_lock", None), type(threading.Lock())):
            self._engine_ready_lock = threading.Lock()
        self._engine_ready.clear()
        with self._engine_ready_lock:
            self._engine_ready_state = {"receipt": None, "error": None}
        return True

    def _reset_replay_readiness_authority(self) -> None:
        """Retire every in-process proof tied to one replay child session."""

        self._replay_session_verified = False
        self._replay_ready_nonce = None
        self._replay_session_id = None
        if not isinstance(getattr(self, "_replay_ready", None), threading.Event):
            self._replay_ready = threading.Event()
        if not isinstance(getattr(self, "_replay_ready_lock", None), type(threading.Lock())):
            self._replay_ready_lock = threading.Lock()
        self._replay_ready.clear()
        with self._replay_ready_lock:
            self._replay_ready_state = {"receipt": None, "error": None}

    def _stop_engine(self) -> None:
        """Остановить engine подпроцесс."""
        if getattr(self, "_replay_source", None) is not None:
            # Liveness is not readiness. Revoke the verified-session fact
            # before any fallible child or reader settlement begins.
            self._replay_session_verified = False
        process = self._engine_proc
        unsettled = getattr(self, "_engine_unsettled_incarnation", None)
        if unsettled is not None:
            owner_id = unsettled[0] if type(unsettled) is tuple and unsettled else "<unknown>"
            if process is not None:
                try:
                    LauncherWindow._reap_unsettled_engine_process(
                        self,
                        owner_id=owner_id,
                    )
                except Exception as exc:
                    raise RuntimeError(
                        "engine incarnation lacks exact shutdown settlement and process reaping remains in HOLD"
                    ) from exc
            raise RuntimeError("engine incarnation lacks exact shutdown settlement; launcher remains in permanent HOLD")
        if process is None:
            if getattr(self, "_engine_external", False):
                self._external_engine_ready_receipt = None
                self._engine_external = False
            elif getattr(self, "_replay_source", None) is None:
                instance_id = getattr(self, "_engine_instance_id", None)
                capability = getattr(self, "_engine_shutdown_capability", None)
                request_id = getattr(self, "_engine_shutdown_request_id", None)
                transport_identity = getattr(self, "_engine_shutdown_transport_identity", None)
                receipt = getattr(self, "_engine_shutdown_receipt", None)
                if any(
                    value is not None for value in (instance_id, capability, request_id, transport_identity, receipt)
                ):
                    preserved_id = instance_id if type(instance_id) is str else "<unknown>"
                    self._engine_unsettled_incarnation = (preserved_id, None)
                    raise RuntimeError(
                        "engine process handle was lost before exact shutdown settlement; launcher remains in HOLD"
                    )
            self._close_engine_stderr_stream()
            if getattr(self, "_replay_source", None) is not None:
                LauncherWindow._reset_replay_readiness_authority(self)
            return

        if self._engine_external:
            if process.poll() is None:
                raise RuntimeError("external engine unexpectedly has a live launcher-owned process handle")
            self._engine_proc = None
            self._close_engine_stderr_stream()
            return

        if getattr(self, "_replay_source", None) is None:
            instance_id = getattr(self, "_engine_instance_id", None)
            capability = getattr(self, "_engine_shutdown_capability", None)
            request_id = getattr(self, "_engine_shutdown_request_id", None)
            if not (
                type(instance_id) is str
                and len(instance_id) == 32
                and type(capability) is str
                and len(capability) == 64
            ):
                raise RuntimeError("engine shutdown authority is unavailable; launcher remains in HOLD")
            if request_id is None:
                request_id = uuid.uuid4().hex
                self._engine_shutdown_request_id = request_id
            receipt = getattr(self, "_engine_shutdown_receipt", None)
            transport_identity = getattr(self, "_engine_shutdown_transport_identity", None)
            if receipt is None and transport_identity is not None:
                if not (
                    type(transport_identity) is tuple
                    and len(transport_identity) == 2
                    and type(transport_identity[0]) is str
                    and len(transport_identity[0]) == 32
                    and all(character in "0123456789abcdef" for character in transport_identity[0])
                    and type(transport_identity[1]) is int
                    and transport_identity[1] >= 0
                ):
                    self._engine_unsettled_incarnation = (instance_id, process.poll())
                    raise RuntimeError(
                        "engine shutdown transport identity is malformed; launcher remains in permanent HOLD"
                    )
                transport_request_id, transport_generation = transport_identity
                late_result = self._bridge.reconcile_late_result(
                    transport_request_id,
                    generation=transport_generation,
                )
                if late_result is None:
                    raise RuntimeError(
                        "engine shutdown transport outcome remains unknown; launcher retains exact reconciliation "
                        "identity in HOLD"
                    )
                if not (
                    type(late_result) is LateCommandResult
                    and late_result.request_id == transport_request_id
                    and late_result.generation == transport_generation
                    and type(late_result.reply) is dict
                ):
                    self._engine_unsettled_incarnation = (instance_id, process.poll())
                    raise RuntimeError("engine shutdown late result is mismatched; launcher remains in permanent HOLD")
                receipt = late_result.reply
            if receipt is None:
                worker = getattr(self, "_engine_shutdown_worker", None)
                # Engine liveness gates *dispatch* only: launcher_shutdown
                # asks the engine to tear itself down, so it commonly exits
                # shortly after replying (see _request_teardown_after_
                # shutdown_receipt) — the process can legitimately die
                # between this call and the one that collects the worker's
                # result. A live-process precondition on collection would
                # make an already-computed, already-valid receipt
                # permanently unreachable the moment the engine exits,
                # which is not a "died without a receipt" HOLD, it is a
                # bookkeeping bug. So: dispatch only while the process is
                # still alive and nothing is in flight; but once a worker
                # exists, drain and validate it unconditionally, regardless
                # of whether the process has since exited.
                if worker is None and process.poll() is None:
                    # self._bridge.send_command() blocks the calling thread
                    # for up to ~65s (Invariant #10; zmq_client.send_command's
                    # documented contract). Calling it here, synchronously on
                    # the Qt main thread, would silence the HOLD alarm and
                    # freeze the tray for the whole wait — the exact scenario
                    # _start_shutdown_hold_alarm exists to signal. Dispatch it
                    # on a background worker instead.
                    worker = _EngineShutdownWorker(
                        {
                            "cmd": "launcher_shutdown",
                            "engine_instance_id": instance_id,
                            "request_id": request_id,
                            "shutdown_capability": capability,
                        },
                        self._bridge,
                    )
                    self._engine_shutdown_worker = worker
                    QThread.start(worker)
                    # A reply that lands within this short, bounded grace
                    # period settles in this same _stop_engine call, exactly
                    # as the previous synchronous call did. A genuinely slow
                    # reply exceeds it; control then returns to the Qt event
                    # loop and the existing shutdown-retry timer
                    # (_schedule_shutdown_retry) re-enters _stop_engine once
                    # the worker's reply actually lands.
                    worker.wait(_ENGINE_SHUTDOWN_WORKER_GRACE_MS)
                if worker is not None:
                    if not worker.isFinished():
                        raise RuntimeError(
                            "engine shutdown command is dispatched on a background worker awaiting its reply; "
                            "launcher remains in HOLD"
                        )
                    receipt = worker.result
                    self._engine_shutdown_worker = None
                    if receipt is None:
                        raise RuntimeError("engine shutdown worker settled without a result; launcher remains in HOLD")
            if receipt is not None:
                expected_unknown_keys = {
                    "ok",
                    "error",
                    "request_id",
                    "generation",
                    "dispatched",
                    "outcome_unknown",
                }
                if (
                    type(receipt) is dict
                    and set(receipt) == expected_unknown_keys
                    and receipt["ok"] is False
                    and type(receipt["error"]) is str
                    and type(receipt["request_id"]) is str
                    and len(receipt["request_id"]) == 32
                    and all(character in "0123456789abcdef" for character in receipt["request_id"])
                    and type(receipt["generation"]) is int
                    and receipt["generation"] >= 0
                    and receipt["dispatched"] is True
                    and receipt["outcome_unknown"] is True
                ):
                    self._engine_shutdown_transport_identity = (
                        receipt["request_id"],
                        receipt["generation"],
                    )
                    raise RuntimeError(
                        "engine shutdown transport outcome remains unknown; launcher retains exact reconciliation "
                        "identity in HOLD"
                    )
            if receipt is not None:
                expected_receipt_keys = {
                    "ok",
                    "schema",
                    "engine_instance_id",
                    "request_id",
                    "off_evidence",
                    "teardown_requested",
                    "delivery_state",
                    "commit_state",
                    "proto",
                }
                if not (
                    type(receipt) is dict
                    and set(receipt) == expected_receipt_keys
                    and receipt["ok"] is True
                    and type(receipt["schema"]) is str
                    and receipt["schema"] == _ENGINE_SHUTDOWN_RECEIPT_SCHEMA
                    and type(receipt["engine_instance_id"]) is str
                    and receipt["engine_instance_id"] == instance_id
                    and type(receipt["request_id"]) is str
                    and receipt["request_id"] == request_id
                    and parse_global_off_evidence(receipt["off_evidence"]) is not None
                    and parse_global_off_evidence(receipt["off_evidence"]).verified_off
                    and receipt["teardown_requested"] is True
                    and type(receipt["delivery_state"]) is str
                    and receipt["delivery_state"] == "dispatched"
                    and type(receipt["commit_state"]) is str
                    and receipt["commit_state"] == "committed"
                    and type(receipt["proto"]) is int
                    and receipt["proto"] == CLIENT_PROTOCOL_VERSION
                ):
                    raise RuntimeError("engine shutdown receipt is missing or mismatched; launcher remains in HOLD")
                self._engine_shutdown_receipt = dict(receipt)
                self._engine_shutdown_transport_identity = None
            if self._engine_shutdown_receipt is None:
                raise RuntimeError("engine child died without an exact shutdown receipt; launcher remains in HOLD")
            if process.poll() is None:
                deadline = getattr(self, "_engine_shutdown_wait_deadline", None)
                if deadline is None:
                    deadline = time.monotonic() + _ENGINE_EXIT_WAIT_BUDGET_S
                    self._engine_shutdown_wait_deadline = deadline
                remaining = deadline - time.monotonic()
                # A single process.wait(timeout=60) would hold the Qt main
                # thread for up to 60s straight, same freeze as the ZMQ
                # round-trip above. Poll in slices of at most
                # _ENGINE_EXIT_POLL_SLICE_S instead: each call blocks briefly
                # (or not at all, once the budget is spent) and then returns
                # control to the caller, which — on "not settled yet" — hands
                # control back to the Qt event loop so the HOLD alarm and
                # tray keep updating between slices. The shutdown-retry timer
                # re-enters for the next slice; the overall budget is tracked
                # in _engine_shutdown_wait_deadline across those calls.
                if remaining > 0:
                    try:
                        process.wait(timeout=min(_ENGINE_EXIT_POLL_SLICE_S, remaining))
                    except subprocess.TimeoutExpired:
                        pass
                if process.poll() is None:
                    if time.monotonic() < deadline:
                        raise RuntimeError(
                            "engine process has not yet exited after a verified shutdown receipt; launcher "
                            "remains in HOLD pending exact process exit"
                        )
                    # A forced death is never exact settlement, even if the
                    # child later reports zero. Latch before terminate() so a
                    # second stop cannot release retained authority evidence.
                    self._engine_shutdown_wait_deadline = None
                    self._engine_unsettled_incarnation = (instance_id, process.poll())
                    self._restart_giving_up = True
                    try:
                        LauncherWindow._reap_unsettled_engine_process(
                            self,
                            owner_id=instance_id,
                        )
                    except Exception as reaping_error:
                        raise RuntimeError(
                            "engine teardown exceeded its bound and forced process reaping remains incomplete"
                        ) from reaping_error
                    raise RuntimeError(
                        "engine teardown exceeded its bound; forced death was reaped but is not exact settlement"
                    )
                self._engine_shutdown_wait_deadline = None
            if process.poll() != 0:
                raise RuntimeError("engine exited without a clean teardown receipt; launcher remains in HOLD")
            self._close_engine_stderr_stream()
            self._engine_proc = None
            self._engine_instance_id = None
            self._engine_shutdown_capability = None
            self._engine_shutdown_request_id = None
            self._engine_shutdown_transport_identity = None
            self._engine_shutdown_receipt = None
            self._engine_unsettled_incarnation = None
            self._engine_shutdown_worker = None
            self._engine_shutdown_wait_deadline = None
            self._engine_ready_nonce = None
            if not isinstance(getattr(self, "_engine_ready", None), threading.Event):
                self._engine_ready = threading.Event()
            if not isinstance(getattr(self, "_engine_ready_lock", None), type(threading.Lock())):
                self._engine_ready_lock = threading.Lock()
            self._engine_ready.clear()
            with self._engine_ready_lock:
                self._engine_ready_state = {"receipt": None, "error": None}
            logger.info("Engine stopped after exact shutdown settlement")
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
        self._close_engine_stderr_stream()
        self._engine_proc = None
        LauncherWindow._reset_replay_readiness_authority(self)
        logger.info("Engine остановлен")

    def _reap_unsettled_engine_process(self, *, owner_id: str) -> int:
        """Terminally reap a HOLD child without upgrading its safety evidence."""

        process = self._engine_proc
        if process is None:
            raise RuntimeError("unsettled engine process handle is unavailable")
        if process.poll() is None:
            try:
                process.terminate()
            except Exception:
                if process.poll() is None:
                    raise
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:
                        process.kill()
                    except Exception:
                        if process.poll() is None:
                            raise
                    process.wait(timeout=5)
        returncode = process.poll()
        if returncode is None:
            raise RuntimeError("unsettled engine remained alive after bounded reaping")

        self._engine_unsettled_incarnation = (owner_id, returncode)
        self._close_engine_stderr_stream()
        self._engine_proc = None
        return returncode

    def _advance_restart_generation(self) -> int:
        """Issue one monotonic identity for a manual or scheduled restart."""

        current = vars(self).get("_restart_generation", 0)
        if type(current) is not int or current < 0:
            raise RuntimeError("launcher restart generation is invalid")
        current += 1
        self._restart_generation = current
        return current

    def _advance_assistant_restart_generation(self) -> int:
        """Issue one monotonic identity for an assistant restart slot."""

        current = vars(self).get("_assistant_restart_generation", 0)
        if type(current) is not int or current < 0:
            raise RuntimeError("assistant restart generation is invalid")
        current += 1
        self._assistant_restart_generation = current
        return current

    def _latch_engine_restart_hold(
        self,
        *,
        phase: str,
        failure: Exception,
        unsettled: tuple[str, ...] = (),
    ) -> None:
        """Keep a failed restart visible when exact ownership cannot settle."""

        self._restart_pending = False
        self._restart_giving_up = True
        if getattr(self, "_replay_source", None) is not None:
            self._replay_session_verified = False
        logger.critical(
            "Engine restart remains in HOLD; phase=%s failure=%s unsettled=%s",
            phase,
            type(failure).__name__,
            ",".join(unsettled) if unsettled else "phase-owner",
        )
        self._show_engine_down_banner(
            f"HOLD: engine restart ownership did not settle exactly during {phase}. Automatic replacement is blocked."
        )
        self._data_timer.start()
        self._health_timer.start()

    def _settle_replacement_child(self, *, phase: str) -> tuple[bool, int | None, Exception | None]:
        """Finish with the replacement child. Returns (settled, observed exit code, error).

        The exit code comes back because the caller has to know whether this was a
        configuration error: that one code must keep its reviewed refusal instead of being
        rescheduled into the same bad files forever.
        """

        owner = (
            getattr(self, "_replay_session_id", None)
            if getattr(self, "_replay_source", None) is not None
            else getattr(self, "_engine_instance_id", None)
        )
        if type(owner) is not str:
            owner = "<unknown>"

        def _settle(returncode: int) -> tuple[bool, int | None, Exception | None]:
            try:
                if LauncherWindow._settle_observed_engine_exit(
                    self,
                    owner_id=owner,
                    returncode=returncode,
                    phase=f"{phase}-replacement-exit",
                ):
                    return True, returncode, None
            except Exception as exc:
                return False, returncode, exc
            return False, returncode, RuntimeError("replacement engine readers did not settle")

        replacement = getattr(self, "_engine_proc", None)
        observed = None if replacement is None else replacement.poll()
        if replacement is not None and observed is not None:
            replacement_id = getattr(self, "_engine_instance_id", None)
            logger.error(
                "Engine replacement exited before readiness; phase=%s incarnation=%s code=%s.",
                phase,
                replacement_id if type(replacement_id) is str else "<unknown>",
                observed,
            )
            return _settle(observed)

        try:
            self._stop_engine()
        except Exception as exc:
            # It may have died during the handoff. Re-read before deciding: a child that is
            # terminal NOW is an observed exit, whatever it was a moment ago.
            late = getattr(self, "_engine_proc", None)
            late_code = None if late is None else late.poll()
            if late is not None and late_code is not None:
                replacement_id = getattr(self, "_engine_instance_id", None)
                logger.error(
                    "Engine replacement exited before readiness; phase=%s incarnation=%s code=%s.",
                    phase,
                    replacement_id if type(replacement_id) is str else "<unknown>",
                    late_code,
                )
                return _settle(late_code)
            return False, None, exc
        return True, None, None

    def _recover_failed_engine_restart(
        self,
        *,
        phase: str,
        failure: Exception,
        child_start_attempted: bool,
        settle_bridge: bool,
        raise_on_hold: bool,
    ) -> bool:
        """Settle partial restart ownership, then re-enter bounded backoff."""

        self._restart_pending = False
        if getattr(self, "_replay_source", None) is not None:
            self._replay_session_verified = False
        settlement_errors: dict[str, Exception] = {}
        replacement_exit_code: int | None = None
        if child_start_attempted:
            # A REPLACEMENT that exited before readiness is a child we watched die, not one
            # we have to ask to stop. _stop_engine cannot get a shutdown receipt out of a
            # terminal child, so it raised, and that raise latched a permanent HOLD -- which
            # meant a recurring startup crash still stopped an unattended run after exactly
            # one retry. Owner, 2026-08-20: "программа ВЕРНЕТСЯ". So an observed exit takes
            # the observed-exit route here too, and only a LIVE child is asked to stop.
            #
            # A child can also die BETWEEN this poll and the dispatch inside _stop_engine.
            # Deciding once on a stale reading would put the same permanent HOLD back for a
            # narrower window, so the live branch re-reads after a failed stop and settles
            # the exit if one has since happened.
            settled, replacement_exit_code, settlement_error = LauncherWindow._settle_replacement_child(
                self,
                phase=phase,
            )
            if not settled:
                # The retained worker is still executing its shutdown command on this
                # bridge. Leave both intact; the next health tick re-enters the observed
                # exit path and retires the owner only after the worker finishes.
                if getattr(self, "_engine_shutdown_worker", None) is not None:
                    return False
                settlement_errors["engine_child"] = settlement_error or RuntimeError(
                    "replacement engine child did not settle"
                )
        if settle_bridge:
            try:
                self._bridge.shutdown()
            except Exception as exc:
                settlement_errors["bridge"] = exc
        if settlement_errors:
            LauncherWindow._latch_engine_restart_hold(
                self,
                phase=phase,
                failure=failure,
                unsettled=tuple(sorted(settlement_errors)),
            )
            if raise_on_hold:
                raise RuntimeError(f"{phase} failed and ownership remains unsettled") from failure
            return False

        from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE

        if replacement_exit_code == ENGINE_CONFIG_ERROR_EXIT_CODE:
            # The reviewed refusal for this one code must survive the replacement path too.
            # Rescheduling here would retry the same invalid files forever and never show
            # the operator which ones to fix. The handle and identity are already settled.
            logger.critical(
                "Engine replacement exited with CONFIG ERROR (code %d). NOT auto-restarting.",
                replacement_exit_code,
            )
            self._restart_giving_up = True
            if not self._config_error_modal_shown:
                self._config_error_modal_shown = True
            self._show_engine_down_banner(
                "ОШИБКА КОНФИГУРАЦИИ: Engine не запускается. Автоперезапуск отключён.\n"
                "Исправьте config/*.yaml (см. logs/engine.log), затем нажмите "
                "«Перезапустить Engine»."
            )
            return False

        logger.error(
            "Engine restart phase failed after exact cleanup; phase=%s failure=%s; scheduling bounded retry",
            phase,
            type(failure).__name__,
        )
        self._restart_giving_up = False
        try:
            LauncherWindow._handle_engine_exit(self)
        except Exception as exc:
            LauncherWindow._latch_engine_restart_hold(
                self,
                phase=f"{phase}-reschedule",
                failure=exc,
                unsettled=("restart-supervision",),
            )
            if raise_on_hold:
                raise RuntimeError(f"{phase} failed and retry supervision remains unsettled") from failure
            return False
        if self._restart_pending is not True and not getattr(self, "_shutdown_requested", False):
            LauncherWindow._latch_engine_restart_hold(
                self,
                phase=f"{phase}-reschedule",
                failure=failure,
                unsettled=("restart-supervision",),
            )
            if raise_on_hold:
                raise RuntimeError(f"{phase} failed and retry supervision remains unsettled") from failure
            return False
        return True

    def _restart_engine(self) -> None:
        """Restart engine AND bridge for clean ZMQ connections."""
        if getattr(self, "_shutdown_requested", False):
            logger.warning("Engine restart refused while launcher shutdown is pending")
            return
        if getattr(self, "_engine_unsettled_incarnation", None) is not None:
            raise RuntimeError(
                "prior engine incarnation lacks exact shutdown settlement; manual restart remains in HOLD"
            )
        # A4: manual restart is the operator's recovery lever — clear the
        # config-error latch, reset backoff, and silence the alarm/banner so
        # a fixed config (or a manual retry) starts from a clean slate.
        self._restart_giving_up = False
        self._restart_attempts = 0
        self._config_error_modal_shown = False
        LauncherWindow._advance_restart_generation(self)
        self._restart_pending = False
        try:
            self._invalidate_engine_producer()
        except Exception as exc:
            LauncherWindow._latch_engine_restart_hold(
                self,
                phase="producer-invalidation",
                failure=exc,
            )
            return
        self._data_timer.stop()
        self._health_timer.stop()
        try:
            self._stop_engine()
        except Exception as exc:
            LauncherWindow._latch_engine_restart_hold(
                self,
                phase="old-engine-settlement",
                failure=exc,
                unsettled=("engine_child",),
            )
            return
        try:
            self._bridge.shutdown()
        except Exception as exc:
            LauncherWindow._recover_failed_engine_restart(
                self,
                phase="old-bridge-settlement",
                failure=exc,
                child_start_attempted=False,
                settle_bridge=True,
                raise_on_hold=False,
            )
            return
        time.sleep(1)
        self._engine_external = False
        try:
            self._start_engine()
        except Exception as exc:
            LauncherWindow._recover_failed_engine_restart(
                self,
                phase="readiness",
                failure=exc,
                child_start_attempted=True,
                settle_bridge=True,
                raise_on_hold=False,
            )
            return
        try:
            self._bridge.start()
            LauncherWindow._publish_replay_ui_authority(self)
        except Exception as exc:
            LauncherWindow._recover_failed_engine_restart(
                self,
                phase="bridge-attach",
                failure=exc,
                child_start_attempted=True,
                settle_bridge=True,
                raise_on_hold=False,
            )
            return
        self._restart_giving_up = False
        self._clear_engine_down_banner()
        self._data_timer.start()
        self._health_timer.start()

    def _is_engine_alive(self) -> bool:
        """Проверить, жив ли engine."""
        if self._engine_external:
            receipt = getattr(self, "_external_engine_ready_receipt", None)
            if type(receipt) is not dict or type(receipt.get("pid")) is not int:
                return False
            observed = self._probe_external_engine_incarnation(receipt["pid"])
            return observed == receipt
        if self._engine_proc is None:
            return False
        if (
            getattr(self, "_replay_source", None) is not None
            and vars(self).get("_replay_session_verified", False) is not True
        ):
            return False
        return self._engine_proc.poll() is None

    # ------------------------------------------------------------------
    # Assistant management (B1) — non-safety third child, see the wiring
    # comment on ``self._assistant_enabled`` in __init__.
    # ------------------------------------------------------------------

    def _settle_assistant_soak_duplicate_owner(self) -> None:
        """Settle the exact parent copy retained across assistant setup."""

        owner = getattr(self, "_assistant_soak_duplicate_owner", None)
        if owner is None:
            return
        if not isinstance(owner, _OwnedFileDescriptor):
            raise RuntimeError("assistant soak duplicate ownership is invalid")
        capability = getattr(self, "_soak_artifact_capability", None)
        if isinstance(capability, _SoakArtifactCapability):
            capability.settle_child_grant(owner)
        else:
            _close_owned_fd_exact(owner, label="assistant soak duplicate")
        self._assistant_soak_duplicate_owner = None

    def _assert_assistant_start_slot_pristine(self) -> None:
        restart_pending = getattr(self, "_assistant_restart_pending", False)
        if type(restart_pending) is not bool or restart_pending:
            raise RuntimeError("assistant restart slot is already reserved")
        residual = (
            getattr(self, "_assistant_proc", None),
            getattr(self, "_assistant_shutdown_path", None),
            getattr(self, "_assistant_shutdown_authority", None),
            getattr(self, "_assistant_soak_duplicate_owner", None),
            getattr(self, "_assistant_unsettled_start_failure", None),
        )
        if any(value is not None for value in residual):
            raise RuntimeError("prior launcher-owned assistant authority remains live")
        capability = getattr(self, "_soak_artifact_capability", None)
        if capability is None:
            return
        if not isinstance(capability, _SoakArtifactCapability):
            raise RuntimeError("assistant soak capability ownership is invalid")
        if (
            capability._pending_child_grants
            or capability._pending_child_grant_slots
            or capability._pending_raw_child_grants
        ):
            raise RuntimeError("prior launcher-owned assistant soak grant remains live")
        capability._require_open_authority()

    def _start_assistant(self) -> None:
        """Spawn the cryodaq-assistant subprocess (Гемма + RAG)."""
        LauncherWindow._assert_assistant_start_slot_pristine(self)
        if self._assistant_experiment_mode and self._assistant_periodic_requested:
            self._assistant_periodic_health = _PeriodicHealthObservation(started_at=time.monotonic())
            LauncherWindow._reset_periodic_reporting_unknown(self)
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
        soak_duplicate: _OwnedFileDescriptor | None = None
        soak_generation: int | None = None
        soak_capability = getattr(self, "_soak_artifact_capability", None)
        process: subprocess.Popen[Any] | None = None
        primary_failure: BaseException | None = None
        try:
            if sys.platform == "win32":
                from cryodaq.paths import get_data_dir

                shutdown_authority = _new_assistant_shutdown_authority(get_data_dir())
                env[_ASSISTANT_SHUTDOWN_ENV] = str(shutdown_authority.path)
            pass_fds: tuple[int, ...] = ()
            if soak_capability is not None:
                granted_duplicate, soak_generation, grant = soak_capability.child_grant()
                soak_duplicate = (
                    granted_duplicate
                    if isinstance(granted_duplicate, _OwnedFileDescriptor)
                    else _OwnedFileDescriptor(granted_duplicate)
                )
                self._assistant_soak_duplicate_owner = soak_duplicate
                env.update(grant)
                pass_fds = (soak_duplicate,)
            popen_kwargs: dict[str, Any] = {}
            if pass_fds:
                popen_kwargs.update({"close_fds": True, "pass_fds": pass_fds})
                assert isinstance(soak_capability, _SoakArtifactCapability)
                assert soak_duplicate is not None
                soak_capability.validate_child_grant(soak_duplicate)
            process = subprocess.Popen(
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
            self._assistant_proc = process
            self._assistant_shutdown_path = None if shutdown_authority is None else shutdown_authority.path
            self._assistant_shutdown_authority = shutdown_authority
            if soak_capability is not None and soak_generation is not None:
                soak_capability.commit_generation(soak_generation)
            logger.info("cryodaq-assistant запущен, PID=%d", process.pid)
        except BaseException as exc:
            primary_failure = exc

        cleanup_failure: BaseException | None = None
        if soak_duplicate is not None:
            try:
                LauncherWindow._settle_assistant_soak_duplicate_owner(self)
            except BaseException as exc:
                cleanup_failure = exc

        if cleanup_failure is not None:
            self._assistant_unsettled_start_failure = cleanup_failure
            logger.error(
                "Assistant construction retained an unsettled soak duplicate; primary=%s cleanup=%s",
                "none" if primary_failure is None else type(primary_failure).__name__,
                type(cleanup_failure).__name__,
            )
            raise RuntimeError("assistant soak duplicate settlement remained incomplete") from (
                primary_failure if primary_failure is not None else cleanup_failure
            )

        if primary_failure is not None:
            logger.error(
                "Assistant construction failed; owner=assistant exception=%s",
                type(primary_failure).__name__,
            )
            if process is not None:
                self._assistant_unsettled_start_failure = primary_failure
                raise RuntimeError("assistant post-spawn construction failed") from primary_failure
            if isinstance(soak_capability, _SoakArtifactCapability) and (
                soak_capability._pending_child_grants
                or soak_capability._pending_child_grant_slots
                or soak_capability._pending_raw_child_grants
            ):
                raise RuntimeError(
                    "assistant pre-spawn construction retained an unsettled soak grant"
                ) from primary_failure
            if not isinstance(primary_failure, Exception):
                raise primary_failure
            self._assistant_proc = None
            self._assistant_shutdown_path = None
            self._assistant_shutdown_authority = None

    def _stop_assistant(self) -> None:
        """Остановить cryodaq-assistant подпроцесс, если он запущен."""
        if self._assistant_proc is None:
            LauncherWindow._settle_assistant_soak_duplicate_owner(self)
            self._assistant_shutdown_path = None
            self._assistant_shutdown_authority = None
            self._assistant_unsettled_start_failure = None
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
                    except OSError as exc:
                        logger.error(
                            "Assistant shutdown request failed; owner=assistant exception=%s",
                            type(exc).__name__,
                        )
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
        LauncherWindow._settle_assistant_soak_duplicate_owner(self)
        self._assistant_proc = None
        # Do not unlink by pathname: Windows has no portable atomic
        # checked-unlink operation. Per-launch UUID names make the retained
        # empty sentinel inert. Authority is released only after process death.
        self._assistant_shutdown_path = None
        self._assistant_shutdown_authority = None
        self._assistant_unsettled_start_failure = None
        logger.info("cryodaq-assistant остановлен")

    def _check_assistant_health(self) -> None:
        """Restart cryodaq-assistant with backoff if it died. NON-safety:
        the assistant is Гемма chat/RAG, not instrument control — its
        death gets a log line + tray note, never the alarm/banner path
        the engine child uses.
        """
        if not LauncherWindow._runtime_callback_is_current(self) or not self._assistant_enabled:
            return
        if (
            self._assistant_proc is not None
            and self._assistant_proc.poll() is None
            and getattr(self, "_assistant_unsettled_start_failure", None) is None
        ):
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

        if any(
            value is not None
            for value in (
                self._assistant_proc,
                getattr(self, "_assistant_shutdown_path", None),
                getattr(self, "_assistant_shutdown_authority", None),
                getattr(self, "_assistant_soak_duplicate_owner", None),
                getattr(self, "_assistant_unsettled_start_failure", None),
            )
        ):
            LauncherWindow._stop_assistant(self)
        LauncherWindow._assert_assistant_start_slot_pristine(self)
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
        restart_generation = LauncherWindow._advance_assistant_restart_generation(self)
        self._assistant_restart_pending = True
        restart_epoch = self._runtime_callback_epoch

        def _do_restart() -> None:
            if vars(self).get("_assistant_restart_generation", 0) != restart_generation:
                return
            if self._assistant_restart_pending is not True:
                return
            if not LauncherWindow._runtime_callback_is_current(self, restart_epoch):
                self._assistant_restart_pending = False
                return
            self._assistant_restart_pending = False
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
        if self._periodic_reporting_fault is True:
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
        previous = self._periodic_reporting_fault
        if previous is False:
            return
        self._periodic_reporting_fault = False
        logger.info(
            "Periodic PNG runtime %s",
            "recovered" if previous is True else "authority established",
        )
        if self._periodic_status_banner is not None:
            self._periodic_status_banner.hide()

    def _reset_periodic_reporting_unknown(self) -> None:
        """Retire stale H3 evidence until a newer ready heartbeat is proven."""

        if not getattr(self, "_assistant_periodic_requested", False):
            self._periodic_reporting_fault = False
            return
        self._periodic_reporting_fault = None
        banner = getattr(self, "_periodic_status_banner", None)
        if banner is not None:
            banner.hide()

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
        MainWindow(
            bridge=self._bridge,
            embedded=True,
            replay_mode=self._replay_source is not None,
            owner_anchor=lambda owner: setattr(self, "_main_window", owner),
            shutdown_request=self._do_shutdown,
        )
        main_window = self._main_window
        LauncherWindow._publish_replay_ui_authority(self)
        start_operator_snapshot_ingress(
            self._bridge,
            main_window,
            expected_mode=SnapshotMode.REPLAY if self._replay_source is not None else SnapshotMode.LIVE,
            anchor=lambda owner: setattr(self, "_snapshot_ingress", owner),
        )
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
        if not LauncherWindow._runtime_callback_is_current(self):
            return
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
        if not LauncherWindow._runtime_callback_is_current(self):
            return
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
        except Exception as exc:
            logger.error(
                "Theme persistence failed; phase=theme_selection exception=%s",
                type(exc).__name__,
            )
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

    def _latch_bridge_watchdog_hold(self, *, phase: str, failure: Exception) -> None:
        """Retain bridge ownership and visible HOLD after failed settlement."""

        self._bridge_restart_fault = True
        self._bridge_restart_hold = True
        LauncherWindow._latch_engine_restart_hold(
            self,
            phase=f"bridge-watchdog-{phase}",
            failure=failure,
            unsettled=("bridge",),
        )

    def _replace_bridge_from_watchdog(self, *, reason: str) -> bool:
        """Replace one exact bridge generation or fail visible and closed."""

        if vars(self).get("_bridge_restart_hold", False) is True:
            return False
        current_generation = vars(self).get("_bridge_watchdog_generation", 0)
        if type(current_generation) is not int or current_generation < 0:
            LauncherWindow._latch_bridge_watchdog_hold(
                self,
                phase="generation",
                failure=RuntimeError("bridge watchdog generation is invalid"),
            )
            return False
        bridge = self._bridge
        try:
            retired_restart_count = bridge.restart_count()
        except Exception as exc:
            LauncherWindow._latch_bridge_watchdog_hold(self, phase="retired-identity", failure=exc)
            return False
        if type(retired_restart_count) is not int or retired_restart_count < 0:
            LauncherWindow._latch_bridge_watchdog_hold(
                self,
                phase="retired-identity",
                failure=RuntimeError("retired bridge restart count is invalid"),
            )
            return False

        replacement_generation = current_generation + 1
        self._bridge_watchdog_generation = replacement_generation
        try:
            self._invalidate_descriptor_transport()
        except Exception as exc:
            LauncherWindow._latch_bridge_watchdog_hold(self, phase="authority-invalidation", failure=exc)
            return False
        try:
            bridge.shutdown()
            retired_alive = bridge.is_alive()
            if type(retired_alive) is not bool or retired_alive:
                raise RuntimeError("retired bridge remained alive after shutdown")
        except Exception as exc:
            LauncherWindow._latch_bridge_watchdog_hold(self, phase="old-settlement", failure=exc)
            return False

        start_error: Exception | None = None
        try:
            bridge.start()
            replacement_alive = bridge.is_alive()
            replacement_healthy = bridge.is_healthy()
            replacement_restart_count = bridge.restart_count()
            replacement_pid = bridge.process_pid()
            if (
                vars(self).get("_bridge_watchdog_generation", -1) != replacement_generation
                or type(replacement_alive) is not bool
                or not replacement_alive
                or type(replacement_healthy) is not bool
                or not replacement_healthy
                or type(replacement_restart_count) is not int
                or replacement_restart_count != retired_restart_count + 1
                or type(replacement_pid) is not int
                or replacement_pid <= 0
            ):
                raise RuntimeError("replacement bridge failed exact generation validation")
            LauncherWindow._publish_replay_ui_authority(self)
        except Exception as exc:
            start_error = exc

        if start_error is not None:
            cleanup_error: Exception | None = None
            try:
                bridge.shutdown()
                replacement_alive = bridge.is_alive()
                if type(replacement_alive) is not bool or replacement_alive:
                    raise RuntimeError("failed replacement bridge remained alive after cleanup")
            except Exception as exc:
                cleanup_error = exc
            if cleanup_error is not None:
                LauncherWindow._latch_bridge_watchdog_hold(
                    self,
                    phase="replacement-cleanup",
                    failure=cleanup_error,
                )
                return False
            self._bridge_restart_fault = True
            logger.error(
                "Bridge watchdog replacement failed after exact cleanup; reason=%s failure=%s",
                reason,
                type(start_error).__name__,
            )
            self._show_engine_down_banner(
                "ZMQ bridge replacement failed after exact cleanup; bounded watchdog retry remains pending."
            )
            return False

        self._bridge_restart_fault = False
        self._bridge_restart_hold = False
        logger.info(
            "ZMQ bridge replacement committed; reason=%s generation=%d restart_count=%d pid=%d",
            reason,
            replacement_generation,
            retired_restart_count + 1,
            replacement_pid,
        )
        return True

    @Slot()
    def _poll_bridge_data(self) -> None:
        """Poll readings from ZMQ bridge subprocess and dispatch to GUI."""
        if not LauncherWindow._runtime_callback_is_current(self):
            return
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
            if unhealthy:
                if self._bridge.is_alive():
                    logger.warning("ZMQ bridge not healthy (no heartbeat), restarting...")
                else:
                    logger.warning("ZMQ bridge died, restarting...")
            else:
                logger.warning("ZMQ bridge not healthy (no readings), restarting...")
            LauncherWindow._replace_bridge_from_watchdog(
                self,
                reason="heartbeat" if unhealthy else "data-flow",
            )
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
                LauncherWindow._replace_bridge_from_watchdog(self, reason="command-channel")
                return

    @Slot(object)
    def _on_reading_qt(self, qualified: object) -> None:
        if not LauncherWindow._runtime_callback_is_current(self):
            return
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
        """Invalidate bridge transport without retiring backend producer identity."""
        self._invalidate_launcher_status_authority()
        if self._main_window is not None:
            self._main_window.invalidate_descriptor_transport()
        snapshot_ingress = getattr(self, "_snapshot_ingress", None)
        if snapshot_ingress is not None:
            snapshot_ingress.invalidate_transport()

    def _invalidate_engine_producer(self) -> None:
        """Retire descriptor and snapshot authority for one engine turnover."""
        self._invalidate_launcher_status_authority()
        self._reset_periodic_reporting_unknown()
        if self._main_window is not None:
            self._main_window.invalidate_engine_producer()
        snapshot_ingress = getattr(self, "_snapshot_ingress", None)
        if snapshot_ingress is not None:
            snapshot_ingress.invalidate_producer()

    def _publish_replay_ui_authority(self) -> None:
        """Bind TopWatch to the exact verified replay and bridge generation."""

        if getattr(self, "_replay_source", None) is None:
            return
        main_window = vars(self).get("_main_window")
        if main_window is None:
            return
        session_id = getattr(self, "_replay_session_id", None)
        speed = getattr(self, "_replay_speed", None)
        launcher_generation = vars(self).get("_restart_generation", 0)
        bridge_generation = self._bridge.restart_count()
        if (
            vars(self).get("_replay_session_verified", False) is not True
            or type(session_id) is not str
            or re.fullmatch(r"[0-9a-f]{32}", session_id) is None
            or type(speed) is not float
            or not math.isfinite(speed)
            or speed < 0.0
            or type(launcher_generation) is not int
            or launcher_generation < 0
            or type(bridge_generation) is not int
            or bridge_generation < 0
            or self._bridge.is_alive() is not True
        ):
            raise RuntimeError("verified replay UI authority is unavailable")
        main_window.bind_replay_authority(
            source=str(self._replay_source),
            speed=speed,
            session_id=session_id,
            launcher_generation=launcher_generation,
            bridge_generation=bridge_generation,
        )

    def _invalidate_launcher_status_authority(self) -> None:
        """Synchronously retire every tray input tied to an old runtime cut."""

        self._last_reading_time = 0.0
        self._last_safety_state = None
        self._last_alarm_count = None
        self._safety_status_generation = getattr(self, "_safety_status_generation", 0) + 1
        self._annunciation_status_generation = getattr(self, "_annunciation_status_generation", 0) + 1
        for name in ("_safety_worker", "_annunciation_worker"):
            worker = getattr(self, name, None)
            if worker is None:
                continue
            try:
                if not worker.isFinished():
                    worker.requestInterruption()
            except RuntimeError:
                continue

    def _capture_launcher_status_authority(
        self,
        *,
        request_generation: int,
    ) -> _LauncherStatusAuthority | None:
        """Capture one exact callback, engine, and bridge identity cut."""

        engine_instance_id = getattr(self, "_engine_instance_id", None)
        bridge = getattr(self, "_bridge", None)
        if (
            not LauncherWindow._runtime_callback_is_current(self)
            or type(engine_instance_id) is not str
            or re.fullmatch(r"[0-9a-f]{32}", engine_instance_id) is None
            or bridge is None
            or not bridge.is_alive()
        ):
            return None
        bridge_pid = bridge.process_pid()
        bridge_restart_count = bridge.restart_count()
        if (
            type(bridge_pid) is not int
            or bridge_pid <= 0
            or type(bridge_restart_count) is not int
            or bridge_restart_count < 0
        ):
            return None
        return _LauncherStatusAuthority(
            callback_epoch=self._runtime_callback_epoch,
            engine_instance_id=engine_instance_id,
            bridge_pid=bridge_pid,
            bridge_restart_count=bridge_restart_count,
            request_generation=request_generation,
        )

    def _launcher_status_authority_is_current(
        self,
        authority: object,
        *,
        generation_attribute: str,
    ) -> bool:
        if type(authority) is not _LauncherStatusAuthority:
            return False
        bridge = getattr(self, "_bridge", None)
        if bridge is None:
            return False
        try:
            bridge_alive = bridge.is_alive()
            bridge_pid = bridge.process_pid()
            bridge_restart_count = bridge.restart_count()
            if (
                type(bridge_alive) is not bool
                or type(bridge_pid) is not int
                or bridge_pid <= 0
                or type(bridge_restart_count) is not int
                or bridge_restart_count < 0
            ):
                return False
            return (
                LauncherWindow._runtime_callback_is_current(self, authority.callback_epoch)
                and getattr(self, "_engine_instance_id", None) == authority.engine_instance_id
                and getattr(self, generation_attribute, -1) == authority.request_generation
                and bridge_alive is True
                and bridge_pid == authority.bridge_pid
                and bridge_restart_count == authority.bridge_restart_count
            )
        except RuntimeError:
            return False

    @Slot()
    def _on_open_web(self) -> None:
        if not LauncherWindow._runtime_callback_is_current(self):
            return
        webbrowser.open(f"http://127.0.0.1:{_WEB_PORT}")

    def _on_restart_engine_from_shell(self) -> None:
        """Entry point for shell v2 ⋯ menu — restart without re-prompting."""
        if not LauncherWindow._runtime_callback_is_current(self):
            return
        if not self._tray_only:
            self._engine_label.setText("Engine: перезапуск...")
        self._restart_engine()

    @Slot()
    def _on_restart_engine(self) -> None:
        if not LauncherWindow._runtime_callback_is_current(self):
            return
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
        if not LauncherWindow._runtime_callback_is_current(self):
            return
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
        if not LauncherWindow._runtime_callback_is_current(self):
            return
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
            ("_shutdown_hold_audible", False),
        ):
            if not isinstance(getattr(self, name, None), type(default)):
                setattr(self, name, default)
        if not hasattr(self, "_shutdown_hold_timer"):
            self._shutdown_hold_timer = None

    def _beep_shutdown_hold_alarm(self) -> None:
        """Sound independently of the revoked runtime callback epoch."""

        if self._shutdown_hold_audible and self._shutdown_phase is not _ShutdownPhase.COMPLETE:
            QApplication.beep()

    def _start_shutdown_hold_alarm(self) -> None:
        """Enter or re-arm audible HOLD until the launcher root is terminal."""

        if self._shutdown_phase is _ShutdownPhase.COMPLETE:
            raise RuntimeError("cannot enter shutdown HOLD after terminal completion")
        self._shutdown_hold_audible = True
        # Narrow ownership-test hosts do not own a Qt application. A real
        # LauncherWindow is always constructed with QApplication; never call
        # into Qt's audio/timer backend against a synthetic or torn-down host.
        if not isinstance(getattr(self, "_app", None), QApplication):
            return
        if self._shutdown_hold_timer is None:
            timer = QTimer()
            timer.setInterval(2_000)
            timer.timeout.connect(functools.partial(LauncherWindow._beep_shutdown_hold_alarm, self))
            self._shutdown_hold_timer = timer
        if not self._shutdown_hold_timer.isActive():
            QApplication.beep()
            self._shutdown_hold_timer.start()

    def _stop_shutdown_hold_alarm(self) -> None:
        """Release audible HOLD only after exact launcher completion."""

        required = {
            "assistant",
            "engine",
            "main_window_workers",
            "bridge_shutdown",
            "safety_worker",
            "bridge_terminal",
            "bridge_registration",
            "soak_artifact",
            "soak_bridge",
            "annunciation_terminal",
        }
        if self._shutdown_phase is not _ShutdownPhase.FINALIZING or not required.issubset(self._shutdown_settled):
            raise RuntimeError("shutdown HOLD release requires exact root settlement")
        self._shutdown_hold_audible = False
        timer = self._shutdown_hold_timer
        if timer is not None:
            timer.stop()

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
        retained_errors = dict(errors)
        self._shutdown_settled.discard("main_window_workers")
        self._shutdown_phase = _ShutdownPhase.RETRY_WAIT
        try:
            LauncherWindow._start_shutdown_hold_alarm(self)
        except Exception as exc:
            retained_errors["shutdown_hold_alarm"] = exc
        self._shutdown_last_errors = retained_errors
        for label, error in retained_errors.items():
            logger.error(
                "Launcher shutdown owner remains unsettled: %s (%s)",
                label,
                type(error).__name__,
            )
        LauncherWindow._set_shutdown_tray_state(self, failed=True)
        LauncherWindow._schedule_shutdown_retry(self)
        return False

    def _quiesce_for_shutdown(self) -> dict[str, Exception]:
        errors: dict[str, Exception] = {}
        self._shutdown_phase = _ShutdownPhase.QUIESCING
        try:
            LauncherWindow._start_shutdown_hold_alarm(self)
        except Exception as exc:
            errors["shutdown_hold_alarm"] = exc
        LauncherWindow._set_shutdown_tray_state(self, failed=False)
        LauncherWindow._revoke_runtime_callbacks(self)
        worker_session_epoch = getattr(self, "_gui_worker_session_epoch", None)
        if worker_session_epoch is not None:
            try:
                revoke_gui_command_worker_admission(worker_session_epoch)
            except Exception as exc:
                errors["gui_worker_admission"] = exc
        try:
            LauncherWindow._advance_restart_generation(self)
        except Exception as exc:
            errors["restart_generation"] = exc
        try:
            LauncherWindow._advance_assistant_restart_generation(self)
        except Exception as exc:
            errors["assistant_restart_generation"] = exc
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
            self._invalidate_engine_producer()
        except Exception as exc:
            errors["engine_producer"] = exc

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
        unsettled: list[str] = []
        for attribute, label in (
            ("_safety_worker", "safety-status"),
            ("_annunciation_worker", "annunciation-status"),
        ):
            worker = getattr(self, attribute, None)
            if worker is None:
                continue
            try:
                if not worker.isFinished():
                    request = getattr(worker, "requestInterruption", None)
                    if callable(request):
                        request()
                    quit_worker = getattr(worker, "quit", None)
                    if callable(quit_worker):
                        quit_worker()
                    wait = getattr(worker, "wait", None)
                    if not callable(wait):
                        unsettled.append(label)
                        continue
                    wait(3_000)
                if not worker.isFinished():
                    unsettled.append(label)
                else:
                    setattr(self, attribute, None)
            except (AttributeError, RuntimeError):
                unsettled.append(label)
        if unsettled:
            raise RuntimeError(f"launcher status workers remained alive after bridge shutdown: {','.join(unsettled)}")

    def _close_event_loop_exact(self) -> None:
        loop = getattr(self, "_loop", None)
        if loop is None:
            return
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

            main_window = getattr(self, "_main_window", None)
            self._shutdown_settled.discard("main_window_workers")
            if main_window is None:
                if settle_registered_gui_command_workers():
                    self._shutdown_settled.add("main_window_workers")
                else:
                    errors["main_window_workers"] = RuntimeError("GUI command workers remain alive")
            else:

                def settle_main_window_workers() -> None:
                    if not main_window.settle_owned_workers():
                        raise RuntimeError("GUI descendant workers remain alive")

                attempt("main_window_workers", settle_main_window_workers)
            if "main_window_workers" not in self._shutdown_settled:
                return LauncherWindow._shutdown_incomplete(self, errors)

            attempt("assistant", self._stop_assistant)
            attempt("engine", self._stop_engine)
            if "engine" in self._shutdown_settled:
                bridge = getattr(self, "_bridge", None)
                if bridge is None:
                    self._shutdown_settled.update({"bridge_shutdown", "bridge_terminal", "bridge_registration"})
                    attempt("safety_worker", lambda: LauncherWindow._settle_safety_worker(self))
                else:
                    attempt("bridge_shutdown", bridge.shutdown)
                    attempt("safety_worker", lambda: LauncherWindow._settle_safety_worker(self))
                    if "bridge_shutdown" in self._shutdown_settled:
                        attempt("bridge_terminal", bridge.close)
                    if "bridge_terminal" in self._shutdown_settled:

                        def release_bridge_registration() -> None:
                            set_bridge(None)
                            self._bridge = None

                        attempt("bridge_registration", release_bridge_registration)
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
            self._shutdown_settled.discard("main_window_workers")
            try:
                if not settle_registered_gui_command_workers():
                    raise RuntimeError("GUI command worker inventory changed before exit")
            except Exception as exc:
                errors["main_window_workers"] = exc
            else:
                self._shutdown_settled.add("main_window_workers")
            if errors:
                return LauncherWindow._shutdown_incomplete(self, errors)
            if main_window is None:
                self._shutdown_settled.add("annunciation_terminal")
            else:
                attempt("annunciation_terminal", main_window.complete_root_shutdown)
            if errors:
                return LauncherWindow._shutdown_incomplete(self, errors)
            try:
                LauncherWindow._stop_shutdown_hold_alarm(self)
            except Exception as exc:
                errors["shutdown_hold_alarm"] = exc
            else:
                self._shutdown_settled.add("shutdown_hold_alarm")
            if errors:
                return LauncherWindow._shutdown_incomplete(self, errors)
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
        if not LauncherWindow._runtime_callback_is_current(self):
            return
        self.showNormal()
        self.activateWindow()

    def _tray_minimize(self) -> None:
        if not LauncherWindow._runtime_callback_is_current(self):
            return
        self.hide()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if not LauncherWindow._runtime_callback_is_current(self):
            return
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
        """Restart after an observed exit; HOLD only when the handle is lost.

        Two different things were treated as one. An engine that EXITED, whose
        handle we still hold and whose exit code we have just read, is provably
        gone: nothing of that incarnation can still be writing. An engine whose
        handle is LOST, with shutdown authority published, is not provably gone
        at all -- a second engine started beside it would write the same
        database, which is the data loss this whole path exists to prevent.

        Only the second case holds. The first settles its readers and takes the
        reviewed crash path below: the code is logged, and the restart backs off
        and retries forever, exactly as it already does for replay and unowned
        children.

        This matters for the safe state of the hardware as well as for uptime.
        The launcher cannot command the source off; only an engine can. A HOLD
        therefore leaves a possibly live heater with no authority able to reach
        it, while a restart re-establishes one: the SMU driver commands OFF on
        every channel inside connect() before anything else (see
        ``drivers/instruments/keithley_2604b.py``, ``_attempt_owned_off(...,
        context="connect")``).

        Owner direction, 2026-08-20, on what a week-long unattended run must do
        when the engine falls over: "программа ВЕРНЕТСЯ и просто сохранит в
        логе что упала и почему".

        A configuration-error exit still refuses to restart -- retrying into the
        identical failure is a busy loop, not a recovery -- and still records
        the reason and tells the operator which files to fix.
        """
        if not LauncherWindow._runtime_callback_is_current(self):
            return
        if self._restart_pending:
            return
        if self._shutdown_requested:
            return
        if getattr(self, "_engine_unsettled_incarnation", None) is not None:
            return

        from cryodaq.engine import ENGINE_CONFIG_ERROR_EXIT_CODE

        returncode: int | None = None
        process = self._engine_proc
        if process is not None:
            returncode = process.poll()
        observed_owner_id = (
            getattr(self, "_replay_session_id", None)
            if getattr(self, "_replay_source", None) is not None
            else getattr(self, "_engine_instance_id", None)
        )
        if type(observed_owner_id) is not str:
            observed_owner_id = "<unknown>"
        if process is not None and returncode is not None:
            logger.warning(
                "Engine exit observed before producer invalidation; incarnation=%s code=%s.",
                observed_owner_id,
                returncode,
            )
        if getattr(self, "_replay_source", None) is not None and (process is None or returncode is not None):
            self._replay_session_verified = False

        owned_acquisition = getattr(self, "_replay_source", None) is None and not getattr(
            self, "_engine_external", False
        )
        authority_evidence = (
            getattr(self, "_engine_instance_id", None),
            getattr(self, "_engine_shutdown_capability", None),
            getattr(self, "_engine_shutdown_request_id", None),
            getattr(self, "_engine_shutdown_transport_identity", None),
            getattr(self, "_engine_shutdown_receipt", None),
        )

        # Latch ownership before invalidation can raise and before any restart
        # can be scheduled. A lost handle is not settlement evidence; an
        # observed exit code, read from a handle we still hold, is.
        if owned_acquisition and process is None and any(value is not None for value in authority_evidence):
            instance_id = authority_evidence[0]
            preserved_id = instance_id if type(instance_id) is str else "<unknown>"
            self._engine_unsettled_incarnation = (preserved_id, returncode)
            self._restart_giving_up = True
            try:
                self._invalidate_engine_producer()
            except Exception as exc:
                logger.error(
                    "Engine producer invalidation failed; phase=restart_hold exception=%s",
                    type(exc).__name__,
                )
            logger.critical(
                "Engine incarnation %s lost exact shutdown settlement "
                "(code=%s, handle_present=%s); restart and launcher exit remain in HOLD.",
                preserved_id,
                returncode,
                process is not None,
            )
            self._show_engine_down_banner(
                "HOLD: engine ownership cannot be proven settled. "
                "Automatic restart and launcher exit are blocked pending separate recovery proof."
            )
            if process is not None:
                try:
                    LauncherWindow._reap_unsettled_engine_process(
                        self,
                        owner_id=preserved_id,
                    )
                except Exception as exc:
                    logger.critical(
                        "Engine process reaping failed in HOLD; phase=owned-exit owner=%s exception=%s",
                        preserved_id,
                        type(exc).__name__,
                    )
                    self._show_engine_down_banner(
                        "HOLD: engine ownership is unsafe and its process/readers remain unsettled. "
                        "Restart and launcher exit are blocked."
                    )
            return

        try:
            self._invalidate_engine_producer()
        except Exception as exc:
            LauncherWindow._latch_engine_restart_hold(
                self,
                phase="producer-invalidation",
                failure=exc,
                unsettled=("producer-authority",),
            )
            owner_id = (
                getattr(self, "_replay_session_id", None)
                if getattr(self, "_replay_source", None) is not None
                else getattr(self, "_engine_instance_id", None)
            )
            if type(owner_id) is not str:
                owner_id = "<unknown>"
            if process is not None and returncode is not None:
                LauncherWindow._settle_crashed_engine_readers_or_hold(
                    self,
                    owner_id=owner_id,
                    returncode=returncode,
                    phase="producer-invalidation",
                )
            return

        if returncode == ENGINE_CONFIG_ERROR_EXIT_CODE:
            logger.critical(
                "Engine exited with CONFIG ERROR (code %d). NOT auto-restarting.",
                returncode,
            )
            self._restart_giving_up = True
            self._show_engine_down_banner(
                "CONFIG ERROR: engine restart is disabled; settling crashed-child readers in HOLD."
            )
            owner_id = (
                getattr(self, "_replay_session_id", None)
                if getattr(self, "_replay_source", None) is not None
                else getattr(self, "_engine_instance_id", None)
            )
            if type(owner_id) is not str:
                owner_id = "<unknown>"
            # No restart is scheduled here, but the operator is told to fix the files and
            # press the restart button, and that button reaches the same spawn preflight.
            if not LauncherWindow._settle_observed_engine_exit(
                self,
                owner_id=owner_id,
                returncode=returncode,
                phase="config-error",
            ):
                return
            if not self._config_error_modal_shown:
                self._config_error_modal_shown = True
            self._show_engine_down_banner(
                "ОШИБКА КОНФИГУРАЦИИ: Engine не запускается. Автоперезапуск отключён.\n"
                "Исправьте config/*.yaml (см. logs/engine.log), затем нажмите "
                "«Перезапустить Engine»."
            )
            return

        shutdown_worker_pending = getattr(self, "_engine_shutdown_worker", None) is not None
        owner_id = (
            getattr(self, "_replay_session_id", None)
            if getattr(self, "_replay_source", None) is not None
            else getattr(self, "_engine_instance_id", None)
        )
        if type(owner_id) is not str:
            owner_id = "<unknown>"
        # A shutdown worker still owns a command on the bridge. It must settle before
        # this crash consumes a backoff slot or announces a restart attempt. The no-worker
        # path retains its existing fail-closed reader-settlement ordering below.
        if shutdown_worker_pending and not LauncherWindow._settle_observed_engine_exit(
            self,
            owner_id=owner_id,
            returncode=returncode,
            phase="retryable-exit",
        ):
            return

        # Retry forever: backoff caps at the last slot (120s), no give-up.
        backoff_idx = min(self._restart_attempts, len(self._restart_backoff_s) - 1)
        delay_s = self._restart_backoff_s[backoff_idx]
        # Name the incarnation that fell. Without it a week of log lines cannot
        # be told apart, and "which run died" is the first question asked.
        crashed_id = (
            getattr(self, "_replay_session_id", None)
            if getattr(self, "_replay_source", None) is not None
            else getattr(self, "_engine_instance_id", None)
        )
        logger.warning(
            "Engine crashed (incarnation=%s, code=%s). Restart attempt %d in %ds (retrying forever).",
            crashed_id if type(crashed_id) is str else "<unknown>",
            returncode,
            self._restart_attempts + 1,
            delay_s,
        )
        self._restart_attempts += 1
        self._last_restart_time = time.monotonic()
        self._show_engine_down_banner(
            f"Engine остановлен — перезапуск через {delay_s} с "
            f"(попытка {self._restart_attempts}). Запись данных приостановлена."
        )
        if not shutdown_worker_pending and not LauncherWindow._settle_observed_engine_exit(
            self,
            owner_id=owner_id,
            returncode=returncode,
            phase="retryable-exit",
        ):
            return

        tray = getattr(self, "_tray", None)
        if tray is not None and tray.isVisible():
            tray.showMessage(
                "CryoDAQ",
                f"Engine остановлен — перезапуск через {delay_s}с (попытка {self._restart_attempts})",
                QSystemTrayIcon.MessageIcon.Warning,
                3000,
            )

        restart_generation = LauncherWindow._advance_restart_generation(self)
        self._restart_pending = True
        restart_epoch = self._runtime_callback_epoch

        def _do_restart() -> None:
            # F2 (Phase A gate, HIGH): this singleShot is not cancelable. If
            # the operator manually restarted meanwhile, _restart_pending was
            # already reset to False — a stale fire here would call
            # _start_engine(), so it must remain bound to the current runtime
            # epoch and establish the exact child/incarnation proof before any
            # bridge restart. No-op unless this shot is still the live one.
            if vars(self).get("_restart_generation", 0) != restart_generation:
                return
            if self._restart_pending is not True:
                return
            if not LauncherWindow._runtime_callback_is_current(self, restart_epoch):
                self._restart_pending = False
                return
            restart_bridge = True
            phase = "producer-invalidation"
            child_start_attempted = False
            try:
                self._invalidate_engine_producer()
                # Every scheduled child replacement owns its bridge turnover;
                # live and replay children must not inherit an old transport.
                phase = "old-bridge-settlement"
                self._bridge.shutdown()
                phase = "readiness"
                child_start_attempted = True
                self._start_engine()
                phase = "bridge-attach"
                self._bridge.start()
                phase = "ui-authority-bind"
                LauncherWindow._publish_replay_ui_authority(self)
            except Exception as restart_error:
                LauncherWindow._recover_failed_engine_restart(
                    self,
                    phase=phase,
                    failure=restart_error,
                    child_start_attempted=child_start_attempted,
                    settle_bridge=restart_bridge,
                    raise_on_hold=True,
                )
                return
            self._restart_pending = False
            self._restart_giving_up = False
            self._clear_engine_down_banner()
            self._data_timer.start()
            self._health_timer.start()

        QTimer.singleShot(delay_s * 1000, _do_restart)

    def _start_engine_down_alarm(self) -> None:
        """Begin a repeating audible alarm while the engine is down.

        Uses QApplication.beep() on a 2s timer — the codebase has no sound
        asset pipeline, and the system bell needs no bundled file and works
        headless. ponytail: system bell, swap for a WAV via QSoundEffect if
        a louder/branded alarm is ever required.
        """
        if not LauncherWindow._runtime_callback_is_current(self):
            return
        if self._alarm_timer is None:
            self._alarm_timer = QTimer(self)
            self._alarm_timer.setInterval(2000)
            self._alarm_timer.timeout.connect(self._beep_if_runtime_current)
        if not self._alarm_timer.isActive():
            QApplication.beep()  # sound immediately, don't wait 2s
            self._alarm_timer.start()

    def _beep_if_runtime_current(self) -> None:
        if LauncherWindow._runtime_callback_is_current(self):
            QApplication.beep()

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
        if not LauncherWindow._runtime_callback_is_current(self):
            return
        if self._assistant_enabled:
            self._check_assistant_health()
        alive = self._is_engine_alive()
        stderr_failure: BaseException | None = getattr(self, "_engine_stderr_persistence_failure", None)
        stderr_owner = getattr(self, "_engine_stderr_stream_owner", None)
        if isinstance(stderr_owner, _EngineStderrStreamOwner):
            stderr_failure = stderr_failure or stderr_owner.pump_failure or stderr_owner.close_failure
            if stderr_failure is None and alive and stderr_owner.settlement_state is not _OwnerSettlementState.OPEN:
                stderr_failure = RuntimeError("engine stderr stream terminated while its child remained alive")
        if stderr_failure is not None:
            if getattr(self, "_engine_stderr_persistence_failure", None) is None:
                self._engine_stderr_persistence_failure = stderr_failure
            if vars(self).get("_restart_giving_up", False) is not True:
                failure = (
                    stderr_failure
                    if isinstance(stderr_failure, Exception)
                    else RuntimeError("engine stderr persistence raised a base exception")
                )
                LauncherWindow._latch_engine_restart_hold(
                    self,
                    phase="engine-stderr-persistence",
                    failure=failure,
                    unsettled=("stderr-evidence",),
                )
        if (
            vars(self).get("_restart_giving_up", False) is True
            or getattr(self, "_engine_unsettled_incarnation", None) is not None
            or vars(self).get("_bridge_restart_fault", False) is True
            or vars(self).get("_bridge_restart_hold", False) is True
        ):
            # Process liveness cannot discharge an ownership or transport
            # HOLD. Keep the operator surface and downstream authority closed.
            alive = False

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
        bridge_alive = self._bridge.is_alive()
        if self._replay_source is not None:
            self._last_safety_state = None
            self._last_alarm_count = None
        if alive and bridge_alive and self._replay_source is None:
            if self._safety_worker is None or self._safety_worker.isFinished():
                self._safety_status_generation += 1
                authority = self._capture_launcher_status_authority(
                    request_generation=self._safety_status_generation,
                )
                if authority is None:
                    self._last_safety_state = None
                else:
                    worker = ZmqCommandWorker({"cmd": "safety_status"}, parent=self)
                    worker.finished.connect(lambda result, expected=authority: self._on_safety_result(result, expected))
                    self._safety_worker = worker
                    worker.start()
            if self._annunciation_worker is None or self._annunciation_worker.isFinished():
                self._annunciation_status_generation += 1
                authority = self._capture_launcher_status_authority(
                    request_generation=self._annunciation_status_generation,
                )
                if authority is None:
                    self._last_alarm_count = None
                else:
                    worker = ZmqCommandWorker({"cmd": "annunciation_status"}, parent=self)
                    worker.finished.connect(
                        lambda result, expected=authority: self._on_annunciation_result(result, expected)
                    )
                    self._annunciation_worker = worker
                    worker.start()
        elif not alive or not bridge_alive:
            self._invalidate_launcher_status_authority()

        # Tray icon color + tooltip — coarse only. Green requires affirmative
        # connection, safety, and alarm truth; unknown alarm authority must
        # remain caution instead of being inferred as zero.
        data_flowing = self._last_reading_time > 0.0 and (time.monotonic() - self._last_reading_time) < 5.0
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

    def _on_safety_result(self, result: object, authority: object = None) -> None:
        """Accept only an exact safety reply from the captured runtime cut."""

        if getattr(self, "_replay_source", None) is not None:
            self._last_safety_state = None
            return
        if not self._launcher_status_authority_is_current(
            authority,
            generation_attribute="_safety_status_generation",
        ):
            return
        assert type(authority) is _LauncherStatusAuthority
        self._last_safety_state = _decode_launcher_safety_status(
            result,
            expected_engine_instance_id=authority.engine_instance_id,
        )

    def _on_annunciation_result(self, result: object, authority: object = None) -> None:
        """Accept only exact alarm truth bound to the captured engine cut."""

        if getattr(self, "_replay_source", None) is not None:
            self._last_alarm_count = None
            return
        if not self._launcher_status_authority_is_current(
            authority,
            generation_attribute="_annunciation_status_generation",
        ):
            return
        assert type(authority) is _LauncherStatusAuthority
        projection = decode_projection(result)
        if projection is None or projection.engine_instance_id != authority.engine_instance_id:
            self._last_alarm_count = None
            return
        self._last_alarm_count = sum(
            1
            for activation in projection.activations
            if activation.source == "alarm_v2" and not activation.acknowledged
        )

    @Slot()
    def _update_status(self) -> None:
        """Обновить статусную строку."""
        if not LauncherWindow._runtime_callback_is_current(self):
            return
        data_flowing = (time.monotonic() - self._last_reading_time) < 5.0
        if data_flowing:
            self._status_conn.setText("⬤ Подключено")
            self._status_conn.setStyleSheet("color: #2ECC40; font-weight: bold;")
        else:
            self._status_conn.setText("⬤ Ожидание данных")
            self._status_conn.setStyleSheet("color: #FFDC00; font-weight: bold;")

    def _tick_async(self) -> None:
        """Прокрутить asyncio event loop."""
        if not LauncherWindow._runtime_callback_is_current(self):
            return
        loop = getattr(self, "_loop", None)
        if loop is None:
            return
        try:
            loop.run_until_complete(_tick_coro())
        except Exception as exc:
            # Pump runs every 10 ms; a persistent fault (e.g. the loop closed
            # mid-shutdown) would otherwise be completely invisible. Log once at
            # DEBUG so it is diagnosable without spamming the log every tick.
            if not getattr(self, "_tick_async_warned", False):
                self._tick_async_warned = True
                logger.debug(
                    "Asyncio pump failed; phase=runtime_tick exception=%s",
                    type(exc).__name__,
                )

    # ------------------------------------------------------------------
    # Window events
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: ANN001
        """Перехватить закрытие окна — свернуть в трей вместо выхода."""
        event.ignore()
        tray = getattr(self, "_tray", None)
        if tray is None:
            # UI construction precedes tray construction. If construction
            # entered HOLD in that interval, this window is the only visible
            # owner of the failure and retry state.
            return
        self.hide()
        if tray.isVisible():
            tray.showMessage(
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
        "--mock-thermal-simulator",
        metavar="HOST:PORT",
        help="Подключить внешний тепловой симулятор. Доступно только в mock-режиме.",
    )
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

    try:
        mock = _resolve_mock_mode(cli_mock=args.mock)
    except ValueError as exc:
        parser.error(str(exc))

    if args.mock_thermal_simulator is not None:
        if not mock:
            parser.error("--mock-thermal-simulator требует mock-режим")
        try:
            endpoint = MockInstrumentEndpoint.parse(args.mock_thermal_simulator)
        except ValueError as exc:
            parser.error(str(exc))
        args.mock_thermal_simulator = f"{endpoint.host}:{endpoint.port}"

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

    construction_hold = False
    try:
        window = LauncherWindow(
            app,
            mock=mock,
            mock_thermal_simulator=args.mock_thermal_simulator,
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
    except _LauncherConstructionHold as hold:
        # HOLD owns the partially constructed window, all acquired children,
        # the soak owners, and the process-wide instance lock. Keep the Qt
        # loop alive so bounded settlement retries can finish.
        construction_hold = True
        window = hold.window
        logger.critical(
            "Launcher retained all construction owners in HOLD after phase %s.",
            hold.phase,
        )
    except BaseException:
        if soak_bridge_handshake is not None:
            soak_bridge_handshake.close()
        if soak_artifact_capability is not None:
            soak_artifact_capability.close()
        raise
    if not args.tray:
        window.show()
        if replay_source is not None and not construction_hold:
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
