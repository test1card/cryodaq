"""Головной процесс CryoDAQ Engine (безголовый).

Запуск:
    cryodaq-engine          # через entry point
    python -m cryodaq.engine  # напрямую

Загружает конфигурации, создаёт и связывает все подсистемы:
    drivers → DataBroker →
    [SQLiteWriter, ZMQPublisher, AlarmEngineV2, InterlockEngine, PluginPipeline]

Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
"""

from __future__ import annotations

import asyncio
import copy
import functools
import hashlib
import inspect
import json
import logging
import math
import os
import secrets
import signal
import stat
import sys
import time
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from cryodaq.analytics.calibration import CalibrationStore
from cryodaq.analytics.leak_rate import LeakRateEstimator
from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor
from cryodaq.core.alarm_ack_codec import (
    ALARM_ACK_ABORT_TERMINAL_CODES as _ALARM_ACK_ABORT_TERMINAL_CODES,
)
from cryodaq.core.alarm_ack_codec import (
    ALARM_ACK_COMMIT_KEYS as _ALARM_ACK_COMMIT_KEYS,
)
from cryodaq.core.alarm_ack_codec import (
    ALARM_ACK_COMMIT_SCHEMA as _ALARM_ACK_COMMIT_SCHEMA,
)
from cryodaq.core.alarm_ack_codec import (
    ALARM_ACK_EVENT_KEYS as _ALARM_ACK_EVENT_KEYS,
)
from cryodaq.core.alarm_ack_codec import (
    ALARM_ACK_EVENT_SCHEMA as _ALARM_ACK_EVENT_SCHEMA,
)
from cryodaq.core.alarm_ack_codec import (
    alarm_ack_request_fingerprint,
    deterministic_safety_audio_ack_request_id,
    is_canonical_engine_instance_id,
    is_canonical_source_activation_id,
    safety_audio_ack_request_fingerprint,
)
from cryodaq.core.alarm_config import AlarmConfig, AlarmConfigError, load_alarm_config
from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmStateManager
from cryodaq.core.annunciation import AnnunciationProjectionUnavailable, AnnunciationRegistry
from cryodaq.core.broker import DataBroker
from cryodaq.core.calibration_acquisition import (
    CalibrationAcquisitionService,
    CalibrationCommandError,
)
from cryodaq.core.channel_manager import ChannelConfigError, get_channel_manager
from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.core.command_authority import (
    ENGINE_MUTATION_CAPABILITY,
    MUTATION_ENVELOPE_KEYS,
    MUTATION_PROTOCOL_MAJOR,
    MUTATION_RECEIPT_SCHEMA,
    is_exact_safe_direction_envelope,
    is_mutation,
    is_ordinary_command_endpoint_admitted,
    requires_compatibility,
    strip_mutation_envelope,
    valid_capability_token,
)
from cryodaq.core.cooldown_alarm import CooldownAlarm
from cryodaq.core.disk_monitor import DiskMonitor
from cryodaq.core.event_bus import EngineEvent, EventBus
from cryodaq.core.event_logger import EventLogger
from cryodaq.core.experiment import ExperimentIdentityMismatchError, ExperimentManager, ExperimentStatus
from cryodaq.core.housekeeping import (
    AdaptiveThrottle,
    HousekeepingConfigError,
    HousekeepingService,
    load_critical_channels_from_alarms_v3,
    load_housekeeping_config,
    load_protected_channel_patterns,
)
from cryodaq.core.interlock import InterlockConfigError, InterlockEngine
from cryodaq.core.operator_log import (
    OperatorLogCommitResult,
    OperatorLogEntry,
    OperatorLogIdempotencyConflictError,
    OperatorLogIdempotencyUnavailableError,
)
from cryodaq.core.path_jail import resolve_within
from cryodaq.core.physical_alarms_config import (
    load_production_physical_alarms_config,
)
from cryodaq.core.physical_policy import PhysicalPolicyReceipt, receipt_for_applied_policy
from cryodaq.core.qualification import (
    QualificationReceiptError,
    source_checkout_qualification_context,
    verify_qualification_receipt,
)
from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager
from cryodaq.core.safety_pattern_liveness import validate_safety_pattern_liveness
from cryodaq.core.scheduler import (
    InstrumentConfig,
    ReviewedSourceSettlementIncomplete,
    Scheduler,
)
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine
from cryodaq.core.shutdown_settlement import ShutdownOwnerSettledError, await_executor_owner
from cryodaq.core.smu_channel import normalize_smu_channel
from cryodaq.core.vacuum_guard import VacuumGuard
from cryodaq.core.zmq_bridge import (
    DEFAULT_CMD_ADDR,
    DEFAULT_PUB_ADDR,
    DEFAULT_SAFE_CMD_ADDR,
    PERIODIC_BARRIER_SCHEMA,
    PERIODIC_QUERY_SCHEMA,
    PROTOCOL_VERSION,
    CommandAuthorityRegistry,
    ZMQCommandIngressPair,
    ZMQCommandIngressTerminalError,
    ZMQCommandIngressTerminalFailure,
    ZMQCommandServer,
    ZMQPublisher,
    _bounded_action_label,
    encode_periodic_command_reply,
)
from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.drivers.contracts import (
    ControlledSource,
    DriverTrustClass,
    VerifiedOffSource,
    is_issued_runtime_binding,
    parse_global_off_evidence,
)
from cryodaq.drivers.registry import (
    DriverConstructionContext,
    DriverRegistryError,
    ReviewedSourceBinding,
    ValidatedInstrumentConfig,
    construct_driver,
    is_reviewed_source_binding,
    validate_instrument_entries,
)
from cryodaq.engine_wiring.operator_snapshot_production import build_operator_snapshot_publication_service
from cryodaq.engine_wiring.recording_lifecycle_feed import RecordingLifecycleFeed
from cryodaq.engine_wiring.runtime_tasks import (
    _alarm_ring_buffer_loop,
    _alarm_v2_feed_loop,
    _AlarmRingBuffer,
    _format_diag_telegram_messages,
    alarm_ring_feed,
    alarm_v2_feed_readings,
    alarm_v2_tick,
    assistant_event_relay_loop,
    cold_rotation_scheduler,
    cooldown_alarm_tick_loop,
    leak_rate_feed,
    sensor_diag_feed,
    sensor_diag_tick,
    track_runtime_signals,
    vacuum_guard_tick_loop,
    vacuum_trend_feed,
    vacuum_trend_tick,
)
from cryodaq.engine_wiring.supervision import (
    _SAFETY_TASK_MAX_RESTARTS,
    _SUPERVISE_BACKOFF_BASE_S,
    _SUPERVISE_BACKOFF_MAX_S,
    _SUPERVISE_RESET_WINDOW_S,
    TaskSupervisor,
    _handle_supervised_task_exit,
    install_loop_exception_backstop,
    stop_safety_manager_with_hold,
)
from cryodaq.instance_lock import try_acquire_lock
from cryodaq.notifications.composition_photo_handler import CompositionPhotoHandler
from cryodaq.notifications.escalation import EscalationService
from cryodaq.notifications.telegram_commands import TelegramCommandBot
from cryodaq.paths import get_archive_dir, get_config_dir, get_data_dir, get_project_root
from cryodaq.report_process import ReportProcessError, ReportProcessRunner
from cryodaq.storage.channel_descriptors import (
    ChannelDescriptorStorageError,
    load_live_channel_descriptor_catalog,
)
from cryodaq.storage.cold_rotation import build_cold_rotation_service, normalize_schedule_time
from cryodaq.storage.sqlite_writer import (
    AlarmAckOutboxAbortDisposition,
    AlarmAckOutboxRecord,
    OperatorLogCommitOutcomeUnknownError,
    OperatorLogPublicationOutboxRecord,
    SQLiteWriter,
)

logger = logging.getLogger("cryodaq.engine")

# Compatibility re-exports for tests and callers that import moved helpers
# from ``cryodaq.engine``. Referenced here so linters keep the imports.
_ = (
    _alarm_ring_buffer_loop,
    _alarm_v2_feed_loop,
    _format_diag_telegram_messages,
    _SAFETY_TASK_MAX_RESTARTS,
    _SUPERVISE_BACKOFF_BASE_S,
    _SUPERVISE_BACKOFF_MAX_S,
    _SUPERVISE_RESET_WINDOW_S,
    _handle_supervised_task_exit,
)

# ---------------------------------------------------------------------------
# Пути по умолчанию (относительно корня проекта)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = get_project_root()
_CONFIG_DIR = get_config_dir()
_PLUGINS_DIR = _PROJECT_ROOT / "plugins"
_DATA_DIR = get_data_dir()

# Интервал самодиагностики (секунды)
_WATCHDOG_INTERVAL_S = 30.0
_LOG_GET_TIMEOUT_S = 5.0
_EXPERIMENT_STATUS_TIMEOUT_S = 5.0
_ENGINE_INSTANCE_ID_ENV = "CRYODAQ_ENGINE_INSTANCE_ID"
_ENGINE_SHUTDOWN_CAPABILITY_ENV = "CRYODAQ_ENGINE_SHUTDOWN_CAPABILITY"
_ENGINE_READY_NONCE_ENV = "CRYODAQ_ENGINE_READY_NONCE"
_CHILD_READY_CHANNEL_ENV = "CRYODAQ_CHILD_READY_CHANNEL"
_ENGINE_READY_SCHEMA = "cryodaq.engine_ready.v2"
_ENGINE_READY_WIRE_PREFIX = b"CRYODAQ_ENGINE_READY_V2 "
_ENGINE_SHUTDOWN_RECEIPT_SCHEMA = "cryodaq.engine_shutdown.v2"
_OPERATOR_LOG_COMMIT_SCHEMA = "operator_log_commit_v1"
_OPERATOR_LOG_SUCCESS_KEYS = frozenset(
    {"ok", "committed", "retry_safe", "publication_state", "entry", "commit_receipt"}
)
_OPERATOR_LOG_COMMAND_REQUIRED_KEYS = frozenset({"cmd", "request_id", "message", "author", "source"})
_OPERATOR_LOG_COMMAND_ALLOWED_KEYS = _OPERATOR_LOG_COMMAND_REQUIRED_KEYS | {
    "tags",
    "experiment_id",
    "experiment_unbound",
}
_OPERATOR_LOG_UNTRUSTED_SOURCES = frozenset({"dashboard", "gui", "rest", "telegram", "zmq"})
_OPERATOR_LOG_RESERVED_ACTORS = frozenset({"system", "auto", "machine"})
_OPERATOR_LOG_RESERVED_TAGS = frozenset(
    {
        "ai",
        "auto",
        "alarm",
        "alarm_ack",
        "safety_fault",
        "phase",
        "phase_transition",
        "experiment",
        "calibration",
        "system",
        "machine",
    }
)


def _consume_engine_shutdown_authority(
    environment: MutableMapping[str, str] | None = None,
) -> tuple[str, str]:
    """Remove inherited shutdown secrets before any engine child can spawn."""

    target = os.environ if environment is None else environment
    absent = object()
    instance_id = target.pop(_ENGINE_INSTANCE_ID_ENV, absent)
    capability = target.pop(_ENGINE_SHUTDOWN_CAPABILITY_ENV, absent)
    if instance_id is absent and capability is absent:
        return "", ""
    valid = (
        type(instance_id) is str
        and len(instance_id) == 32
        and all(ch in "0123456789abcdef" for ch in instance_id)
        and type(capability) is str
        and len(capability) == 64
        and all(ch in "0123456789abcdef" for ch in capability)
    )
    if not valid:
        raise RuntimeError("launcher shutdown authority is invalid")
    return instance_id, capability


def _canonical_engine_instance_id(supplied: object) -> str:
    """Validate launcher identity or generate exactly once for direct mode."""

    if type(supplied) is str and supplied == "":
        return secrets.token_hex(16)
    if type(supplied) is not str or len(supplied) != 32 or any(char not in "0123456789abcdef" for char in supplied):
        raise ValueError("engine_instance_id must be exactly 32 lowercase hexadecimal characters")
    return supplied


def _consume_engine_ready_nonce(environment: MutableMapping[str, str] | None = None) -> str:
    """Consume the launcher's one-use readiness challenge before child spawn."""

    target = os.environ if environment is None else environment
    absent = object()
    nonce = target.pop(_ENGINE_READY_NONCE_ENV, absent)
    if nonce is absent:
        return ""
    if type(nonce) is str and len(nonce) == 64 and all(char in "0123456789abcdef" for char in nonce):
        return nonce
    raise RuntimeError("launcher readiness nonce is invalid")


def _consume_child_ready_channel(environment: MutableMapping[str, str] | None = None) -> int | None:
    """Consume and de-inherit the launcher's one-child readiness pipe.

    The launcher passes only the write end.  It is converted to a CRT file
    descriptor on Windows, verified as a pipe, and made non-inheritable before
    any engine-owned subprocess can be constructed.
    """

    target = os.environ if environment is None else environment
    absent = object()
    encoded = target.pop(_CHILD_READY_CHANNEL_ENV, absent)
    if encoded is absent:
        return None
    descriptor: int | None = None
    try:
        if type(encoded) is not str:
            raise ValueError("readiness channel descriptor is not text")
        if sys.platform == "win32":
            import msvcrt

            prefix = "handle:"
            suffix = encoded[len(prefix) :] if encoded.startswith(prefix) else ""
            if not (1 <= len(suffix) <= 20 and suffix.isascii() and suffix.isdecimal()):
                raise ValueError("invalid readiness channel handle")
            handle = int(suffix)
            if handle <= 0:
                raise ValueError("invalid readiness channel handle")
            standard_handles: set[int] = set()
            for standard_descriptor in (0, 1, 2):
                try:
                    standard_handle = msvcrt.get_osfhandle(standard_descriptor)
                except OSError:
                    continue
                if standard_handle > 0:
                    standard_handles.add(standard_handle)
            if handle in standard_handles:
                raise ValueError("unsafe readiness channel handle")
            descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY | getattr(os, "O_BINARY", 0))
            if not stat.S_ISFIFO(os.fstat(descriptor).st_mode):
                raise ValueError("readiness channel is not a pipe")
        else:
            prefix = "fd:"
            suffix = encoded[len(prefix) :] if encoded.startswith(prefix) else ""
            if not (1 <= len(suffix) <= 20 and suffix.isascii() and suffix.isdecimal()):
                raise ValueError("invalid readiness channel descriptor")
            candidate = int(suffix)
            if candidate <= 2:
                raise ValueError("unsafe readiness channel descriptor")
            if not stat.S_ISFIFO(os.fstat(candidate).st_mode):
                raise ValueError("readiness channel is not a pipe")
            descriptor = candidate
        os.set_inheritable(descriptor, False)
        return descriptor
    except (OSError, ValueError) as exc:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise RuntimeError("launcher readiness channel is invalid") from exc


def _consume_engine_launch_authority(
    environment: MutableMapping[str, str] | None = None,
) -> tuple[str, str, str, int | None]:
    """Consume exactly one complete launcher envelope or direct-mode absence."""

    target = os.environ if environment is None else environment
    absent = object()
    raw_channel = target.pop(_CHILD_READY_CHANNEL_ENV, absent)
    raw_nonce = target.pop(_ENGINE_READY_NONCE_ENV, absent)
    raw_instance_id = target.pop(_ENGINE_INSTANCE_ID_ENV, absent)
    raw_shutdown_capability = target.pop(_ENGINE_SHUTDOWN_CAPABILITY_ENV, absent)
    channel_environment = {} if raw_channel is absent else {_CHILD_READY_CHANNEL_ENV: raw_channel}
    nonce_environment = {} if raw_nonce is absent else {_ENGINE_READY_NONCE_ENV: raw_nonce}
    shutdown_environment = {}
    if raw_instance_id is not absent:
        shutdown_environment[_ENGINE_INSTANCE_ID_ENV] = raw_instance_id
    if raw_shutdown_capability is not absent:
        shutdown_environment[_ENGINE_SHUTDOWN_CAPABILITY_ENV] = raw_shutdown_capability

    ready_channel_fd: int | None = None
    try:
        # Acquire the descriptor first so every later envelope rejection can
        # settle the one-use handle rather than leaking launcher authority.
        ready_channel_fd = _consume_child_ready_channel(channel_environment)
        ready_nonce = _consume_engine_ready_nonce(nonce_environment)
        instance_id, shutdown_capability = _consume_engine_shutdown_authority(shutdown_environment)
        components_present = (
            bool(instance_id),
            bool(shutdown_capability),
            bool(ready_nonce),
            ready_channel_fd is not None,
        )
        if all(components_present):
            return instance_id, shutdown_capability, ready_nonce, ready_channel_fd
        if not any(components_present):
            return "", "", "", None
        raise RuntimeError("launcher engine authority envelope is incomplete")
    except BaseException:
        if ready_channel_fd is not None:
            try:
                os.close(ready_channel_fd)
            except OSError:
                pass
        raise


def _coerce_finite_setpoint(raw: Any, name: str) -> float:
    """Coerce a command setpoint to ``float`` and reject non-finite values.

    Raises ``ValueError`` for non-numeric or non-finite (NaN/Inf) input so the
    command handler returns a clean error instead of letting a NaN slip toward
    SafetyManager and the hardware (where ``nan > max`` / ``nan <= 0`` guards do
    not catch it). Defense in depth — SafetyManager re-checks independently.
    """
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"Non-finite setpoint {name}={raw!r} rejected")
    return value


async def _run_keithley_command(
    action: str,
    cmd: dict[str, Any],
    safety_manager: SafetyManager,
) -> dict[str, Any]:
    """Dispatch channel-scoped Keithley commands to SafetyManager."""
    channel = cmd.get("channel")

    if action == "keithley_start":
        smu_channel = normalize_smu_channel(channel)
        try:
            p = _coerce_finite_setpoint(cmd.get("p_target", 0), "p_target")
            v = _coerce_finite_setpoint(cmd.get("v_comp", 40), "v_comp")
            i = _coerce_finite_setpoint(cmd.get("i_comp", 1.0), "i_comp")
        except (TypeError, ValueError, OverflowError):
            return {
                "ok": False,
                "channel": smu_channel,
                "error_code": "keithley_parameters_invalid",
                "error": "Keithley command parameters are invalid.",
            }
        return await safety_manager.request_run(p, v, i, channel=smu_channel)

    if action == "keithley_stop":
        smu_channel = normalize_smu_channel(channel)
        return await safety_manager.request_stop(channel=smu_channel)

    if action == "keithley_emergency_off":
        # Preserve omitted channel as the literal global scope.  Normalizing
        # None would silently turn a global OFF request into smua-only.
        if channel is None:
            return await safety_manager.emergency_off(channel=None)
        smu_channel = normalize_smu_channel(channel)
        return await safety_manager.emergency_off(channel=smu_channel)

    if action == "keithley_set_target":
        smu_channel = normalize_smu_channel(cmd.get("channel"))
        try:
            p = _coerce_finite_setpoint(cmd.get("p_target", 0), "p_target")
        except (TypeError, ValueError, OverflowError):
            return {
                "ok": False,
                "channel": smu_channel,
                "error_code": "keithley_parameters_invalid",
                "error": "Keithley command parameters are invalid.",
            }
        return await safety_manager.update_target(p, channel=smu_channel)

    if action == "keithley_set_limits":
        smu_channel = normalize_smu_channel(cmd.get("channel"))
        try:
            v = _coerce_finite_setpoint(cmd["v_comp"], "v_comp") if cmd.get("v_comp") is not None else None
            i = _coerce_finite_setpoint(cmd["i_comp"], "i_comp") if cmd.get("i_comp") is not None else None
        except (TypeError, ValueError, OverflowError):
            return {
                "ok": False,
                "channel": smu_channel,
                "error_code": "keithley_parameters_invalid",
                "error": "Keithley command parameters are invalid.",
            }
        return await safety_manager.update_limits(channel=smu_channel, v_comp=v, i_comp=i)

    raise ValueError(f"Unsupported Keithley command: {action}")


def _parse_log_time(raw: Any) -> datetime | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=UTC)
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = f"{value[:-1]}+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    raise ValueError("Invalid log time filter.")


def _parse_experiment_time(raw: Any) -> datetime | None:
    return _parse_log_time(raw)


def _load_experiment_metadata_sync(meta_path: Path) -> dict:
    """H2: sync helper for F31 metadata read — wrap in asyncio.to_thread
    at the call site to avoid blocking the engine event loop."""
    if not meta_path.exists():
        return {}
    try:
        import json as _json

        return _json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning(
            "Engine metadata read failed: phase=f31_metadata exception=%s",
            type(exc).__name__,
        )
        return {}


async def _publish_operator_log_entry(
    broker: DataBroker | None,
    entry: OperatorLogEntry,
) -> None:
    if broker is None:
        return
    await broker.publish(
        Reading(
            timestamp=entry.timestamp,
            instrument_id="operator_log",
            channel="analytics/operator_log_entry",
            value=float(entry.id),
            unit="",
            metadata=entry.to_payload(),
        )
    )


async def _publish_operator_log_publication(
    writer: SQLiteWriter,
    broker: DataBroker | None,
    *,
    request_id: str,
    request_fingerprint: str,
    event: dict[str, Any],
    receipt: dict[str, Any],
) -> OperatorLogPublicationOutboxRecord:
    """Publish one durable intent at least once, then mark that exact intent."""

    if broker is None:
        raise RuntimeError("operator-log publication broker is unavailable")
    event_copy, _receipt_copy = SQLiteWriter.validate_operator_log_publication(
        request_id=request_id,
        event=event,
        receipt=receipt,
    )
    entry = event_copy["entry"]
    metadata = {
        **entry,
        "request_id": request_id,
        "publication_schema": event_copy["schema"],
    }
    publish_required = getattr(broker, "publish_required", None)
    validates_required = getattr(broker, "validates_required_publication", None)
    if not callable(publish_required) or not callable(validates_required):
        raise RuntimeError("operator-log required publisher is unavailable")
    publication_receipt = await publish_required(
        Reading(
            timestamp=datetime.fromisoformat(entry["timestamp"]),
            instrument_id="operator_log",
            channel="analytics/operator_log_entry",
            value=float(entry["id"]),
            unit="",
            metadata=metadata,
        ),
        request_id=request_id,
        request_fingerprint=request_fingerprint,
    )
    if (
        validates_required(
            publication_receipt,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
        )
        is not True
    ):
        raise RuntimeError("operator-log required publisher receipt is invalid")
    published = await writer.publish_operator_log_publication_outbox(
        request_id=request_id,
        request_fingerprint=request_fingerprint,
    )
    state = _validated_operator_log_publication_record(
        published,
        request_id=request_id,
        request_fingerprint=request_fingerprint,
        event=event,
        receipt=receipt,
    )
    if state != "published":
        raise RuntimeError("operator-log publication settlement is incomplete")
    return published


async def _reconcile_operator_log_publication_outbox(
    writer: SQLiteWriter,
    broker: DataBroker | None,
) -> None:
    """Reconstruct crash-stranded intents and replay them with stable keys."""

    if broker is None:
        raise RuntimeError("operator-log publication broker is unavailable")
    pending = await writer.reconcile_missing_operator_log_publication_outbox()
    for publication in pending:
        await _publish_operator_log_publication(
            writer,
            broker,
            request_id=publication.request_id,
            request_fingerprint=publication.request_fingerprint,
            event=publication.event,
            receipt=publication.receipt,
        )


@dataclass(frozen=True, slots=True)
class _CommandIngressRecoveryProof:
    """Exact retained-state settlement completed before REP admission."""

    engine_instance_id: str
    operator_log_initialized: bool
    operator_log_reconciled: bool
    alarm_ack_dispositions: tuple[AlarmAckOutboxAbortDisposition, ...]
    _authority_capability: object | None = field(default=None, repr=False, compare=False)


class _CommandIngressRecoveryAuthority:
    """One-use owner that makes retained recovery a prerequisite for REP."""

    def __init__(
        self,
        *,
        writer: SQLiteWriter,
        broker: DataBroker | None,
        engine_instance_id: str,
    ) -> None:
        if not is_canonical_engine_instance_id(engine_instance_id):
            raise ValueError("engine_instance_id must be exactly 32 lowercase hexadecimal characters")
        self._writer = writer
        self._broker = broker
        self._engine_instance_id = engine_instance_id
        self.__capability = object()
        self.__issued_proof: _CommandIngressRecoveryProof | None = None
        self._settlement_attempted = False
        self._start_attempted = False
        self._proof: _CommandIngressRecoveryProof | None = None

    @property
    def proof(self) -> _CommandIngressRecoveryProof | None:
        return self._proof

    async def settle(self) -> _CommandIngressRecoveryProof:
        """Initialize, reconcile, abort stale ACKs, then replay committed ACKs."""

        if self._settlement_attempted:
            raise RuntimeError("command ingress recovery settlement is one-use")
        self._settlement_attempted = True
        await self._writer.initialize_operator_log_idempotency()
        await _reconcile_operator_log_publication_outbox(self._writer, self._broker)
        dispositions = await _settle_alarm_ack_outbox_startup(
            self._writer,
            self._broker,
            self._engine_instance_id,
        )
        proof = _CommandIngressRecoveryProof(
            engine_instance_id=self._engine_instance_id,
            operator_log_initialized=True,
            operator_log_reconciled=True,
            alarm_ack_dispositions=dispositions,
            _authority_capability=self.__capability,
        )
        self.__issued_proof = proof
        self._proof = proof
        return proof

    async def start(self, command_server: ZMQCommandIngressPair) -> None:
        """Open REP exactly once and only after this owner retained its proof."""

        if self._start_attempted:
            raise RuntimeError("command ingress start is one-use")
        self._start_attempted = True
        proof = self._proof
        if (
            type(proof) is not _CommandIngressRecoveryProof
            or proof is not self.__issued_proof
            or proof._authority_capability is not self.__capability
            or proof.engine_instance_id != self._engine_instance_id
            or proof.operator_log_initialized is not True
            or proof.operator_log_reconciled is not True
            or type(proof.alarm_ack_dispositions) is not tuple
        ):
            raise RuntimeError("command ingress recovery proof is unavailable")
        await command_server.start()


async def _run_operator_log_command(
    action: str,
    cmd: dict[str, Any],
    writer: SQLiteWriter,
    experiment_manager: ExperimentManager,
    broker: DataBroker | None = None,
) -> dict[str, Any]:
    if action == "log_get":
        experiment_id = cmd.get("experiment_id")
        if experiment_id is None and cmd.get("current_experiment", False):
            experiment_id = experiment_manager.active_experiment_id
            if experiment_id is None:
                return {"ok": True, "entries": []}

        try:
            entries = await asyncio.wait_for(
                writer.get_operator_log(
                    experiment_id=str(experiment_id) if experiment_id is not None else None,
                    start_time=_parse_log_time(cmd.get("start_time", cmd.get("start_ts"))),
                    end_time=_parse_log_time(cmd.get("end_time", cmd.get("end_ts"))),
                    limit=int(cmd.get("limit", 100)),
                ),
                timeout=_LOG_GET_TIMEOUT_S,
            )
        except TimeoutError as exc:
            raise TimeoutError(f"log_get timeout ({_LOG_GET_TIMEOUT_S:g}s)") from exc
        return {"ok": True, "entries": [entry.to_payload() for entry in entries]}

    raise ValueError(f"Unsupported operator log command: {action}")


class _RemoteAssistantQueryProxy:
    """Forwards Telegram free-text chat to the cryodaq-assistant process.

    B1: ``TelegramCommandBot._handle_text`` (notifications/telegram_commands.py)
    calls ``self._query_agent.handle_query(text, chat_id=chat_id)`` for any
    non-command message. That used to be the in-process
    ``AssistantQueryAgent``; now it's this proxy, which sends the exact
    same request to the assistant process's own REP socket
    (``tcp://127.0.0.1:5557``, ``{"cmd": "assistant.query", ...}``) and
    returns its answer. This is the engine calling OUT to the assistant
    for a read-only answer — the opposite direction from (and unrelated
    to) the no-write-path-into-the-engine constraint on the assistant
    process itself.
    """

    def __init__(
        self,
        address: str = "tcp://127.0.0.1:5557",
        *,
        timeout_s: float = 55.0,
    ) -> None:
        self._address = address
        self._timeout_ms = int(timeout_s * 1000)

    async def handle_query(self, query: str, *, chat_id: Any) -> str:
        import json as _json  # noqa: PLC0415

        import zmq  # noqa: PLC0415
        import zmq.asyncio  # noqa: PLC0415

        ctx = zmq.asyncio.Context.instance()
        sock = ctx.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, self._timeout_ms)
        sock.setsockopt(zmq.SNDTIMEO, self._timeout_ms)
        try:
            sock.connect(self._address)
            await sock.send_string(_json.dumps({"cmd": "assistant.query", "query": query, "chat_id": chat_id}))
            reply = _json.loads(await sock.recv_string())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Assistant query transport failed: exception=%s",
                type(exc).__name__,
            )
            return "🤖 Гемма: ассистент недоступен."
        finally:
            sock.close(linger=0)
        if reply.get("ok"):
            return str(reply.get("response", ""))
        return str(reply.get("error", "Ассистент вернул ошибку."))


def _leak_rate_volume_warning(chamber_cfg: dict[str, Any]) -> str | None:
    """Boot-time config check for leak-rate estimation.

    With ``leak_rate.enabled: true`` but ``chamber.volume_l: 0.0``, finalize()
    raises ValueError at experiment end (fail-closed — kept). Surface it at boot
    so the operator fixes ``chamber.volume_l`` now, not hours later at finalize.
    Returns the operator warning, or None when the config is fine.
    """
    leak_cfg = chamber_cfg.get("leak_rate", {}) or {}
    if leak_cfg.get("enabled") and float(chamber_cfg.get("volume_l", 0.0) or 0.0) == 0.0:
        return (
            "config: leak_rate.enabled=true, но chamber.volume_l=0.0 — оценка "
            "утечки завершится ошибкой при финализации эксперимента. Задайте "
            "chamber.volume_l в config/instruments.local.yaml."
        )
    return None


async def _handle_leak_rate_command(
    action: str,
    cmd: dict[str, Any],
    leak_rate_estimator: LeakRateEstimator,
    leak_cfg: dict[str, Any],
    event_logger: Any,
) -> dict[str, Any] | None:
    """Dispatch ``leak_rate_start`` / ``leak_rate_stop`` GUI commands.

    F13: extracted as a module-level helper (mirrors
    ``_handle_assistant_query_command``) so the leak-rate command path is
    unit-testable without spinning up the full engine. Returns ``None`` when
    *action* is not a leak-rate command, so the caller falls through to the
    remaining handlers; otherwise returns the response dict. Behaviour is
    identical to the inline dispatch it replaces.
    """
    if action == "leak_rate_start":
        if not leak_cfg.get("enabled", True):
            return {"ok": False, "error": "leak rate measurement disabled in config"}
        _raw_dur = cmd.get("duration_s")
        window_s: float | None = None
        if _raw_dur is not None:
            try:
                window_s = float(_raw_dur)
            except (TypeError, ValueError):
                return {"ok": False, "error": f"duration_s not numeric: {_raw_dur!r}"}
            if not (0 < window_s < float("inf")):
                return {
                    "ok": False,
                    "error": f"duration_s must be positive and finite, got {window_s}",
                }
        try:
            leak_rate_estimator.start_measurement(window_s=window_s)
            return {"ok": True, "action": "leak_rate_start"}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Leak-rate start failed: exception=%s",
                type(exc).__name__,
            )
            return {
                "ok": False,
                "error_code": "leak_rate_start_failed",
                "error": "Leak-rate measurement could not be started.",
            }
    if action == "leak_rate_stop":
        try:
            from dataclasses import asdict as _asdict  # noqa: PLC0415

            result = leak_rate_estimator.finalize()
            await event_logger.log_event(
                "leak_rate",
                f"Leak rate: {result.leak_rate_mbar_l_per_s:.3e} mbar·L/s",
            )
            return {"ok": True, "action": "leak_rate_stop", "measurement": _asdict(result)}
        except ValueError:
            return {
                "ok": False,
                "error_code": "leak_rate_stop_invalid",
                "error": "Leak-rate measurement is not ready to stop.",
            }
    return None


async def _drain_dispatch_tasks(
    tasks: set[asyncio.Task[Any]],
    logger_: logging.Logger,
    timeout: float = 10.0,  # noqa: ASYNC109 — internal drain helper, not a public coroutine API
) -> None:
    """Await in-flight fire-and-forget sink dispatch tasks before teardown.

    F31 H3: extracted as an importable module-level helper so the drain
    semantics — await to completion, cap at *timeout*, cancel any stragglers —
    are unit-testable without bringing up the full engine. This is now the
    single source of the shutdown drain logic. Behaviour-preserving: same
    gather/wait_for/cancel sequence the inline shutdown block ran, with the
    timeout (previously the hardcoded 10 s) surfaced as a parameter so the
    warning text reports the actual cap.
    """
    if not tasks:
        return
    owners = tuple(tasks)

    async def settle() -> BaseException | None:
        logger_.info(
            "Draining %d in-flight dispatch task(s) before shutdown",
            len(owners),
        )
        _done, pending = await asyncio.wait(owners, timeout=timeout)
        if pending:
            logger_.warning(
                "Sink drain timed out (%ss); cancelling %d remaining",
                timeout,
                len(pending),
            )
            for task in pending:
                task.cancel()
        results = await asyncio.gather(*owners, return_exceptions=True)
        return next(
            (
                result
                for result in results
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError)
            ),
            None,
        )

    settlement = asyncio.create_task(settle(), name="engine-dispatch-task-settlement")
    cancellation_seen = False
    while not settlement.done():
        try:
            await asyncio.shield(settlement)
        except asyncio.CancelledError:
            cancellation_seen = True
    failure = settlement.result()
    if failure is not None:
        raise _EngineShutdownSettledFailure(failure)
    if cancellation_seen:
        raise asyncio.CancelledError


# ───────────────────────── Task supervision (A2) ──────────────────────────
# Политика надзора (TaskSupervisor + решающее ядро
# _handle_supervised_task_exit + константы бэкоффа) вынесена в
# engine_wiring.supervision и импортируется выше. Тихая смерть долгоживущей
# задачи — риск №1 в ночную смену; ядро тестируется в изоляции.


# ─────────────────────────── Audible faults (A3) ──────────────────────────
# Safety faults and a dead-sensor decline outside the active source lifecycle
# used to be log-only — an operator had to be staring at the log to notice.
# The helpers below reuse
# the SAME alarm_fired/Telegram dispatch channel alarm-v2, cooldown-alarm,
# vacuum-guard and the task supervisor already use (no new channel
# invented), extracted as importable module-level functions so they are
# unit-testable without bringing up the full engine (same rationale as
# ``_drain_dispatch_tasks``).


async def _dispatch_alarm_notification(
    event_bus: EventBus,
    alarm_dispatch_tasks: set[asyncio.Task[Any]],
    *,
    alarm_id: str,
    level: str,
    message: str,
    experiment_id: str | None,
    telegram_bot: Any | None = None,
    channel: str = "",
    value: float = 0.0,
) -> None:
    """Publish ``alarm_fired`` (sound/GUI) and, if a notifier is configured,
    dispatch the same message to Telegram — fire-and-forget, tracked in
    *alarm_dispatch_tasks* so it survives GC and drains cleanly on shutdown
    (see ``_drain_dispatch_tasks``).
    """
    if telegram_bot is not None:
        t = asyncio.create_task(
            telegram_bot._send_to_all(f"⚠ [{level}] {alarm_id}\n{message}"),
            name=f"{alarm_id}_tg",
        )
        alarm_dispatch_tasks.add(t)
        t.add_done_callback(alarm_dispatch_tasks.discard)
    await event_bus.publish(
        EngineEvent(
            event_type="alarm_fired",
            timestamp=datetime.now(UTC),
            payload={
                "alarm_id": alarm_id,
                "level": level,
                "message": message,
                "channels": [channel] if channel else [],
                "values": [value] if channel else [],
            },
            experiment_id=experiment_id,
        )
    )


def _should_dispatch_dead_channel_alarm(key: str, escalated: bool, already_sent: set[str]) -> bool:
    """Once-per-episode edge-trigger for an inactive-source dead-channel alert.

    ``on_interlock_dead_channel`` stays log-only outside RUN_PERMITTED/RUNNING
    by design and is retried on every subsequent non-usable sample so the
    fault still latches when an active source lifecycle begins (see
    interlock.py's ``_NonUsableWindow.escalated`` docstring). Dispatching
    sound on every retry would beep on every poll; fire at most once per
    continuous decline episode, and clear once escalation succeeds (active
    lifecycle began / fault latched — that path gets its own CRITICAL alarm
    via ``_safety_fault_log_callback``) so a later distinct episode alerts.
    """
    if escalated:
        already_sent.discard(key)
        return False
    if key in already_sent:
        return False
    already_sent.add(key)
    return True


def _build_experiment_export(
    exp_info: dict[str, Any],
    metadata: dict[str, Any],
) -> Any:
    """Construct the F31 sink ``ExperimentExport`` from experiment info plus
    the loaded ``metadata.json`` dict.

    F31 H1: extracted so the export construction is unit-testable without
    finalizing a real experiment — in particular that ``summary`` is read from
    the canonical ``summary_metadata`` metadata key (the bare ``summary`` key
    is empty and would yield vault notes with empty ## Summary sections). This
    is now the single source of the dispatch-export shape; behaviour-preserving.
    """
    from cryodaq.sinks import ExperimentExport

    exp_id = exp_info.get("experiment_id") or ""
    started = _parse_experiment_time(exp_info.get("start_time"))
    ended = _parse_experiment_time(exp_info.get("end_time"))
    duration_h: float | None = None
    if started is not None and ended is not None:
        duration_h = (ended - started).total_seconds() / 3600.0
    return ExperimentExport(
        experiment_id=exp_id,
        title=str(exp_info.get("title") or ""),
        sample=str(exp_info.get("sample") or ""),
        operator=str(exp_info.get("operator") or ""),
        status=str(exp_info.get("status") or ""),
        started_at=started or datetime.now(UTC),
        ended_at=ended,
        duration_h=duration_h,
        template_id=str(exp_info.get("template_id") or "custom"),
        phases=list(metadata.get("phases", []) or []),
        artifact_index=list(metadata.get("artifact_index", []) or []),
        summary=dict(metadata.get("summary_metadata", {}) or {}),
        notes=str(exp_info.get("notes") or ""),
        description=str(exp_info.get("description") or ""),
        custom_fields=dict(exp_info.get("custom_fields") or {}),
    )


async def _handle_multiline_set_channels_command(
    cmd: dict[str, Any],
    *,
    drivers_by_name: dict[str, Any],
    config_dir: Path,
) -> dict[str, Any]:
    """v0.55.16.0.1 (smoke hotfix) — runtime channel-set update for
    a MultiLine driver.

    Validates the operator-supplied list, calls
    ``driver.reconfigure_channels()``, and persists the change to
    ``config/instruments.local.yaml`` (existing override pattern,
    machine-specific) so the selection survives engine restart. The
    write is best-effort: a failed persist still keeps the runtime
    change live and is reported back to the operator so they can
    re-select after the next restart.

    Module-level so unit tests exercise the lifecycle without
    spinning up the full engine.
    """
    raw_channels = cmd.get("channels")
    if not isinstance(raw_channels, list):
        return {"ok": False, "error": "channels must be a list of integers"}
    try:
        channels = sorted({int(c) for c in raw_channels})
    except (TypeError, ValueError):
        return {"ok": False, "error": "channels must be integers"}
    if not channels:
        return {"ok": False, "error": "at least one channel must be selected"}
    if any(c < 1 or c > 32 for c in channels):
        return {"ok": False, "error": "channel ids must be in 1..32"}

    name = str(cmd.get("name", "")).strip()
    if not name:
        ml_names = [n for n, d in drivers_by_name.items() if d.__class__.__name__ == "MultiLineDriver"]
        if len(ml_names) == 1:
            name = ml_names[0]
        else:
            return {
                "ok": False,
                "error": ("MultiLine instance not specified and multiple drivers are configured"),
            }

    driver = drivers_by_name.get(name)
    if driver is None or driver.__class__.__name__ != "MultiLineDriver":
        return {
            "ok": False,
            "error_code": "multiline_driver_unavailable",
            "error": "The requested MultiLine driver is unavailable.",
        }

    try:
        applied = await driver.reconfigure_channels(channels)
    except ValueError:
        return {
            "ok": False,
            "error_code": "multiline_channels_invalid",
            "error": "The requested MultiLine channel set is invalid.",
        }
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "multiline.set_channels reconfigure failed: driver=%s exception=%s",
            _bounded_action_label(name),
            type(exc).__name__,
        )
        return {
            "ok": False,
            "error_code": "multiline_reconfigure_failed",
            "error": "MultiLine channel reconfiguration failed.",
        }

    persist_warning: str | None = None
    try:
        # Offload the synchronous YAML read+write off the engine event loop —
        # no blocking I/O on the loop (repo invariant).
        await asyncio.to_thread(
            _persist_multiline_channels_to_local_yaml,
            config_dir=config_dir,
            instrument_name=name,
            channels=applied,
        )
    except Exception as exc:  # noqa: BLE001 — non-fatal; runtime change stuck
        logger.warning(
            "multiline.set_channels persistence failed: driver=%s exception=%s; "
            "the runtime change will revert on engine restart",
            _bounded_action_label(name),
            type(exc).__name__,
        )
        persist_warning = "Channel selection persistence failed; the change is runtime-only."

    return {
        "ok": True,
        "name": name,
        "current_channels": applied,
        "persist_warning": persist_warning,
    }


def _persist_multiline_channels_to_local_yaml(
    *,
    config_dir: Path,
    instrument_name: str,
    channels: list[int],
) -> None:
    """Merge the new channel set into ``config/instruments.local.yaml``.

    Builds the merged instrument list from base + local so the result
    is always a complete superset (engine reads local wholesale; an
    incomplete local would silently drop base-only entries on restart).
    Updates the matching ``etalon_multiline`` entry's ``channels``
    field and writes back.

    The original helper
    appended a minimal stub when the local file lacked the MultiLine
    entry, which would have lost base-only fields like host/port/mode
    on engine restart. The merged build below copies the full base
    entry when the local doesn't already have it, so persistence
    never strips required fields.
    """
    import yaml as _yaml

    local_path = config_dir / "instruments.local.yaml"
    base_path = config_dir / "instruments.yaml"

    base_raw: dict[str, Any] = {}
    if base_path.exists():
        base_raw = _yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    local_raw: dict[str, Any] = {}
    if local_path.exists():
        local_raw = _yaml.safe_load(local_path.read_text(encoding="utf-8")) or {}

    base_instruments = [e for e in (base_raw.get("instruments") or []) if isinstance(e, dict)]
    local_instruments = [e for e in (local_raw.get("instruments") or []) if isinstance(e, dict)]

    # Merge by (type, name) — local entries override base entries with
    # the same identity. Order: local first (preserves operator
    # ordering), then base entries that local didn't shadow.
    def _key(entry: dict) -> tuple[str, str]:
        return (str(entry.get("type", "")), str(entry.get("name", "")))

    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for entry in local_instruments:
        merged.append(dict(entry))
        seen.add(_key(entry))
    for entry in base_instruments:
        if _key(entry) not in seen:
            merged.append(dict(entry))
            seen.add(_key(entry))

    matched = False
    for entry in merged:
        if str(entry.get("type")) == "etalon_multiline" and str(entry.get("name")) == instrument_name:
            entry["channels"] = list(channels)
            matched = True
            break
    if not matched:
        # No matching entry in either base or local — append a minimal
        # stub. Operator gets the persist_warning reflecting that the
        # engine may still need a config edit for host/port.
        merged.append(
            {
                "type": "etalon_multiline",
                "name": instrument_name,
                "channels": list(channels),
            }
        )

    # Engine loads instruments.local.yaml
    # WHOLESALE (the _cfg() helper at engine startup picks local over
    # base if local exists). Top-level keys outside `instruments` —
    # e.g. `chamber` (leak-rate config) — must therefore be copied from
    # base too, otherwise persisting a MultiLine channel change silently
    # drops chamber config on the next restart and leak-rate falls back
    # to defaults.
    out_raw: dict[str, Any] = {}
    for key, value in base_raw.items():
        if key == "instruments":
            continue
        out_raw[key] = value
    for key, value in local_raw.items():
        if key == "instruments":
            continue
        out_raw[key] = value
    out_raw["instruments"] = merged

    config_dir.mkdir(parents=True, exist_ok=True)
    with local_path.open("w", encoding="utf-8") as fh:
        _yaml.safe_dump(
            out_raw,
            fh,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )


async def _handle_multiline_burst_command(
    action: str,
    cmd: dict[str, Any],
    *,
    drivers_by_name: dict[str, Any],
    experiment_manager: Any | None,
    experiments_root: Any | None,
    auto_stop_tasks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch ``multiline.burst_*`` GUI commands to a MultiLine driver.

    Module-level helper mirrors the F34/RAG dispatch pattern so the
    unit tests can exercise the burst lifecycle without spinning up
    the full engine. Returns Russian error string-shaped dicts on every
    failure path so the GUI surfaces a stable shape.

    ``auto_stop_tasks`` (when supplied) is a dict the engine uses to
    track auto-stop timers per driver; tests pass an empty dict so the
    timer scheduling path is observable.
    """
    name = str(cmd.get("name", "")).strip()
    if not name:
        # Default to the first MultiLine driver if exactly one is
        # configured — keeps the GUI single-instrument case ergonomic.
        ml_names = [n for n, d in drivers_by_name.items() if d.__class__.__name__ == "MultiLineDriver"]
        if len(ml_names) == 1:
            name = ml_names[0]
        else:
            return {
                "ok": False,
                "error": (f"MultiLine instance not specified and {len(ml_names)} configured — pass `name` explicitly."),
            }
    driver = drivers_by_name.get(name)
    if driver is None or driver.__class__.__name__ != "MultiLineDriver":
        return {
            "ok": False,
            "error_code": "multiline_driver_unavailable",
            "error": "The requested MultiLine driver is unavailable.",
        }

    if action == "multiline.burst_status":
        try:
            return {"ok": True, **driver.burst_status()}
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "multiline.burst_status failed: driver=%s exception=%s",
                _bounded_action_label(name),
                type(exc).__name__,
            )
            return {
                "ok": False,
                "error_code": "multiline_burst_status_failed",
                "error": "MultiLine burst status is unavailable.",
            }

    if action == "multiline.burst_start":
        duration_s = cmd.get("duration_s")
        try:
            duration = float(duration_s) if duration_s is not None else None
        except (TypeError, ValueError):
            return {"ok": False, "error": "duration_s must be a number"}
        if duration is not None and (duration <= 0 or duration > 600):
            return {
                "ok": False,
                "error": "duration_s must be in (0, 600]",
            }
        active_id: str | None = None
        if experiment_manager is not None:
            try:
                active_id = experiment_manager.active_experiment_id
            except Exception:  # noqa: BLE001
                active_id = None
        try:
            await driver.burst_start(experiment_id=active_id)
        except RuntimeError:
            return {
                "ok": False,
                "error_code": "multiline_burst_start_failed",
                "error": "MultiLine burst capture could not be started.",
            }
        if duration is not None and auto_stop_tasks is not None:
            # The auto-stop task lives on the engine event loop; the
            # caller schedules it because asyncio.create_task here would
            # bind to the test loop and not get cleaned up. Engine
            # closure passes a real dict so the task ref is retained.
            auto_stop_tasks[name] = {
                "duration_s": duration,
                "scheduled_at": time.monotonic(),
            }
        return {
            "ok": True,
            "name": name,
            "duration_s": duration,
            "experiment_id": active_id,
        }

    if action == "multiline.burst_stop":
        try:
            path = await driver.burst_stop(experiments_root=experiments_root)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "multiline.burst_stop failed: driver=%s exception=%s",
                _bounded_action_label(name),
                type(exc).__name__,
            )
            return {
                "ok": False,
                "error_code": "multiline_burst_stop_failed",
                "error": "MultiLine burst capture could not be stopped.",
            }
        if path is None:
            return {"ok": True, "path": None, "saved": False}
        if auto_stop_tasks is not None:
            auto_stop_tasks.pop(name, None)
        return {"ok": True, "path": str(path), "saved": True}

    return {
        "ok": False,
        "error_code": "multiline_burst_action_invalid",
        "error": "MultiLine burst action is invalid.",
    }


# B1 (2026-07): live index mutation and bootstrap-on-empty were removed.
# index logic below moved to cryodaq.agents.assistant_main — the standalone
# assistant process now owns the RAG index end-to-end (own REP command
# surface at tcp://127.0.0.1:5557). See scratchpad/montana/exec/impl_b1.md.
def _run_calibration_command(
    action: str,
    cmd: dict[str, Any],
    *,
    calibration_store: CalibrationStore,
    experiment_manager: ExperimentManager,
    drivers_by_name: dict[str, Any],
) -> dict[str, Any]:
    if action == "calibration_curve_evaluate":
        sensor_id = str(cmd.get("sensor_id", "")).strip()
        if not sensor_id:
            raise ValueError("sensor_id is required.")
        temperature = calibration_store.evaluate(sensor_id, float(cmd.get("raw_value")))
        return {"ok": True, "temperature_k": temperature}

    if action == "calibration_curve_list":
        return {
            "ok": True,
            "curves": calibration_store.list_curves(sensor_id=str(cmd.get("sensor_id", "")).strip() or None),
            "assignments": calibration_store.list_assignments(),
        }

    if action == "calibration_curve_get":
        sensor_id = str(cmd.get("sensor_id", "")).strip() or None
        curve_id = str(cmd.get("curve_id", "")).strip() or None
        curve = calibration_store.get_curve_info(sensor_id=sensor_id, curve_id=curve_id)
        return {"ok": True, "curve": curve}

    if action == "calibration_curve_lookup":
        sensor_id = str(cmd.get("sensor_id", "")).strip() or None
        channel_key = str(cmd.get("channel_key", "")).strip() or None
        lookup = calibration_store.lookup_curve(sensor_id=sensor_id, channel_key=channel_key)
        return {"ok": True, **lookup}

    if action == "calibration_curve_assign":
        sensor_id = str(cmd.get("sensor_id", "")).strip()
        if not sensor_id:
            raise ValueError("sensor_id is required.")
        assignment = calibration_store.assign_curve(
            sensor_id=sensor_id,
            curve_id=str(cmd.get("curve_id", "")).strip() or None,
            channel_key=str(cmd.get("channel_key", "")).strip() or None,
            runtime_apply_ready=bool(cmd.get("runtime_apply_ready", False)),
            reading_mode_policy=str(cmd.get("reading_mode_policy", "inherit")).strip() or "inherit",
        )
        return {"ok": True, "assignment": assignment}

    if action == "calibration_runtime_status":
        return {
            "ok": True,
            "runtime": calibration_store.get_runtime_settings(),
        }

    if action == "calibration_runtime_set_global":
        mode = calibration_store.set_runtime_global_mode(str(cmd.get("global_mode", "")).strip())
        return {
            "ok": True,
            "runtime": mode,
        }

    if action == "calibration_runtime_set_channel_policy":
        result = calibration_store.set_runtime_channel_policy(
            channel_key=str(cmd.get("channel_key", "")).strip(),
            policy=str(cmd.get("policy", "")).strip(),
            sensor_id=str(cmd.get("sensor_id", "")).strip() or None,
            curve_id=str(cmd.get("curve_id", "")).strip() or None,
            runtime_apply_ready=(bool(cmd.get("runtime_apply_ready")) if "runtime_apply_ready" in cmd else None),
        )
        return {"ok": True, **result}

    if action == "calibration_curve_export":
        sensor_id = str(cmd.get("sensor_id", "")).strip()
        if not sensor_id:
            raise ValueError("sensor_id is required.")

        # ME-6: an operator-supplied path must resolve inside the exports dir.
        # Empty -> None (store picks its own default location under base_dir).
        exports_base = calibration_store._exports_dir

        def _confine(key: str) -> Path | None:
            raw = str(cmd.get(key, "")).strip()
            if not raw:
                return None
            if exports_base is None:
                raise ValueError("path outside allowed directory")
            return resolve_within(exports_base, raw)

        try:
            json_target = _confine("json_path")
            table_target = _confine("table_path")
            cof_target = _confine("curve_cof_path")
            curve_340_target = _confine("curve_340_path")
        except ValueError:
            return {"ok": False, "error": "path outside allowed directory"}

        json_path = calibration_store.export_curve_json(sensor_id, json_target)
        table_path = calibration_store.export_curve_table(
            sensor_id,
            path=table_target,
            points=int(cmd.get("points", 200)),
        )
        curve_cof_path = calibration_store.export_curve_cof(
            sensor_id,
            path=cof_target,
        )
        curve_340_path = calibration_store.export_curve_340(
            sensor_id,
            path=curve_340_target,
            points=int(cmd.get("points", 200)),
        )
        return {
            "ok": True,
            "json_path": str(json_path),
            "table_path": str(table_path),
            "curve_cof_path": str(curve_cof_path),
            "curve_340_path": str(curve_340_path),
        }

    if action == "calibration_curve_import":
        raw_path = str(cmd.get("path", "")).strip()
        if not raw_path:
            raise ValueError("path is required.")
        # ME-6: confine imports to the exports dir (parsers validate content).
        exports_base = calibration_store._exports_dir
        try:
            if exports_base is None:
                raise ValueError("path outside allowed directory")
            import_target = resolve_within(exports_base, raw_path)
        except ValueError:
            return {"ok": False, "error": "path outside allowed directory"}
        curve = calibration_store.import_curve_file(
            import_target,
            sensor_id=str(cmd.get("sensor_id", "")).strip() or None,
            channel_key=str(cmd.get("channel_key", "")).strip() or None,
            raw_unit=str(cmd.get("raw_unit", "sensor_unit")).strip() or "sensor_unit",
            sensor_kind=str(cmd.get("sensor_kind", "generic")).strip() or "generic",
        )
        return {
            "ok": True,
            "curve": curve.to_payload(),
            "artifacts": calibration_store.get_curve_artifacts(curve.sensor_id),
            "assignment": calibration_store.lookup_curve(sensor_id=curve.sensor_id)["assignment"],
        }

    raise ValueError(f"Unsupported calibration command: {action}")


def _normalize_custom_fields_payload(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    raise ValueError("custom_fields must be a dictionary.")


def _normalize_dict_payload(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    raise ValueError("Expected dictionary payload.")


def _try_activate_calibration_acquisition(
    service: CalibrationAcquisitionService,
    experiment_manager: ExperimentManager,
    cmd: dict[str, Any],
) -> None:
    """Activate SRDG acquisition if the experiment template requests it."""
    try:
        template_id = str(cmd.get("template_id", "custom")).strip() or "custom"
        experiment_manager.get_template(template_id)  # validate template exists
        # Check raw YAML for calibration_acquisition flag
        raw_path = experiment_manager._templates_dir / f"{template_id}.yaml"
        if not raw_path.exists():
            return
        with raw_path.open(encoding="utf-8") as fh:
            import yaml as _yaml

            raw = _yaml.safe_load(fh) or {}
        if not raw.get("calibration_acquisition"):
            return
        custom_fields = _normalize_custom_fields_payload(cmd.get("custom_fields"))
        reference = str(custom_fields.get("reference_channel", "")).strip()
        targets_raw = str(custom_fields.get("target_channels", "")).strip()
        targets = [t.strip() for t in targets_raw.split(",") if t.strip()]
        if reference and targets:
            service.activate(reference, targets)
        else:
            logger.warning("Calibration experiment missing reference_channel/target_channels in custom_fields")
    except CalibrationCommandError as exc:
        logger.error(
            "Calibration activation rejected: exception=%s",
            type(exc).__name__,
        )
    except Exception as exc:
        logger.warning(
            "Calibration activation failed: exception=%s",
            type(exc).__name__,
        )


async def _run_cooldown_history_command(
    cmd: dict[str, Any],
    experiment_manager: ExperimentManager,
    writer: Any,
) -> dict[str, Any]:
    """Return a list of past completed cooldowns (spec §5, F3-Cycle3).

    Mines experiment metadata JSON files for cooldown phase transitions,
    filters to COMPLETED experiments where cooldown ended, and fetches
    T1 readings at cooldown boundaries from the readings store.
    """
    import json as _json

    limit = int(cmd.get("limit", 20))
    entries = await asyncio.to_thread(
        experiment_manager.list_archive_entries,
        sort_by="start_time",
        descending=True,
    )
    cooldowns: list[dict] = []
    for entry in entries:
        if len(cooldowns) >= limit:
            break
        if entry.status != "COMPLETED":
            continue
        try:
            # Offload the per-file metadata read off the engine loop (no
            # blocking I/O on the loop). json parse of a small file stays inline.
            raw_meta = await asyncio.to_thread(entry.metadata_path.read_text, encoding="utf-8")
            payload = _json.loads(raw_meta)
        except Exception:
            continue
        phases: list[dict] = payload.get("phases", [])
        cooldown_phase = next(
            (p for p in phases if p.get("phase") == "cooldown" and p.get("ended_at") is not None),
            None,
        )
        if cooldown_phase is None:
            continue
        cooldown_started_at = cooldown_phase.get("started_at")
        cooldown_ended_at = cooldown_phase.get("ended_at")
        if not cooldown_started_at or not cooldown_ended_at:
            continue
        try:
            started_dt = datetime.fromisoformat(cooldown_started_at).astimezone(UTC)
            ended_dt = datetime.fromisoformat(cooldown_ended_at).astimezone(UTC)
            duration_hours = round((ended_dt - started_dt).total_seconds() / 3600, 3)
        except Exception:
            continue
        start_t: float | None = None
        end_t: float | None = None
        try:
            t_hist = await writer.read_readings_history(
                channels=["Т1"],
                from_ts=started_dt.timestamp(),
                to_ts=ended_dt.timestamp(),
                limit_per_channel=500,
            )
            t_pts = t_hist.get("Т1", [])
            if t_pts:
                start_t = round(float(t_pts[0][1]), 2)
                end_t = round(float(t_pts[-1][1]), 2)
        except Exception:
            pass
        cooldowns.append(
            {
                "experiment_id": entry.experiment_id,
                "sample_name": entry.sample,
                "started_at": entry.start_time.isoformat(),
                "cooldown_started_at": cooldown_started_at,
                "cooldown_ended_at": cooldown_ended_at,
                "duration_hours": duration_hours,
                "start_T_kelvin": start_t,
                "end_T_kelvin": end_t,
                "phase_transitions": [
                    {"phase": p.get("phase"), "ts": p.get("started_at")} for p in phases if p.get("started_at")
                ],
            }
        )
    return {"ok": True, "cooldowns": cooldowns}


def _run_experiment_command(
    action: str,
    cmd: dict[str, Any],
    experiment_manager: ExperimentManager,
) -> dict[str, Any]:
    if action == "get_app_mode":
        return {"ok": True, "app_mode": experiment_manager.get_app_mode().value}

    if action == "set_app_mode":
        app_mode = experiment_manager.set_app_mode(str(cmd.get("app_mode", "")).strip())
        return {
            "ok": True,
            "app_mode": app_mode.value,
            "active_experiment": experiment_manager.active_experiment.to_payload()
            if experiment_manager.active_experiment
            else None,
        }

    if action == "experiment_templates":
        return {
            "ok": True,
            "templates": [template.to_payload() for template in experiment_manager.get_templates()],
        }

    if action == "experiment_status":
        return experiment_manager.get_status_payload()

    if action in {"experiment_archive_list", "experiment_list_archive"}:
        report_present_raw = cmd.get("report_present")
        if report_present_raw in (None, ""):
            report_present = None
        elif isinstance(report_present_raw, str):
            report_present = report_present_raw.strip().lower() in {"1", "true", "yes"}
        else:
            report_present = bool(report_present_raw)
        entries = experiment_manager.list_archive_entries(
            template_id=str(cmd.get("template_id", "")).strip() or None,
            operator=str(cmd.get("operator", "")).strip() or None,
            sample=str(cmd.get("sample", "")).strip() or None,
            start_date=_parse_experiment_time(cmd.get("start_date")),
            end_date=_parse_experiment_time(cmd.get("end_date")),
            report_present=report_present,
            sort_by=str(cmd.get("sort_by", "start_time")),
            descending=bool(cmd.get("descending", True)),
        )
        return {"ok": True, "entries": [entry.to_payload() for entry in entries]}

    if action == "experiment_get_active":
        return {
            "ok": True,
            "app_mode": experiment_manager.get_app_mode().value,
            "active_experiment": experiment_manager.active_experiment.to_payload()
            if experiment_manager.active_experiment
            else None,
        }

    if action in {"experiment_start", "experiment_create"}:
        # IV.4 F6: per-experiment report_enabled override. The GUI
        # dialog passes a bool when the operator flips the checkbox,
        # otherwise the key is absent and the template default wins.
        raw_report_enabled = cmd.get("report_enabled")
        report_override = bool(raw_report_enabled) if raw_report_enabled is not None else None
        info = experiment_manager.create_experiment(
            name=str(cmd.get("name", "")).strip() or str(cmd.get("title", "")).strip(),
            operator=str(cmd.get("operator", "")).strip(),
            template_id=str(cmd.get("template_id", "custom")).strip() or "custom",
            title=str(cmd.get("title", "")).strip() or None,
            sample=str(cmd.get("sample", "")).strip(),
            cryostat=str(cmd.get("cryostat", "")).strip(),
            description=str(cmd.get("description", "")).strip(),
            notes=str(cmd.get("notes", "")).strip(),
            custom_fields=_normalize_custom_fields_payload(cmd.get("custom_fields")),
            start_time=_parse_experiment_time(cmd.get("start_time")),
            report_enabled=report_override,
        )
        return {
            "ok": True,
            "experiment_id": info.experiment_id,
            "experiment": info.to_payload(),
            "active_experiment": info.to_payload(),
            "app_mode": experiment_manager.get_app_mode().value,
        }

    if action == "experiment_update":
        info = experiment_manager.update_experiment(
            experiment_id=str(cmd.get("experiment_id", "")).strip() or None,
            title=str(cmd.get("title", "")).strip() if "title" in cmd else None,
            sample=str(cmd.get("sample", "")).strip() if "sample" in cmd else None,
            notes=str(cmd.get("notes", "")).strip() if "notes" in cmd else None,
            description=str(cmd.get("description", "")).strip() if "description" in cmd else None,
            custom_fields=_normalize_custom_fields_payload(cmd.get("custom_fields"))
            if "custom_fields" in cmd
            else None,
        )
        return {"ok": True, "experiment": info.to_payload(), "active_experiment": info.to_payload()}

    if action in {"experiment_finalize", "experiment_stop"}:
        status_name = str(cmd.get("status", ExperimentStatus.COMPLETED.value)).upper()
        status = ExperimentStatus(status_name)
        info = experiment_manager.finalize_experiment(
            experiment_id=str(cmd.get("experiment_id", "")).strip() or None,
            status=status,
            title=str(cmd.get("title", "")).strip() or None,
            sample=str(cmd.get("sample", "")).strip() or None,
            notes=str(cmd.get("notes", "")).strip() or None,
            description=str(cmd.get("description", "")).strip() or None,
            custom_fields=_normalize_custom_fields_payload(cmd.get("custom_fields")),
            end_time=_parse_experiment_time(cmd.get("end_time")),
        )
        return {"ok": True, "experiment": info.to_payload()}

    if action == "experiment_abort":
        info = experiment_manager.abort_experiment(
            experiment_id=str(cmd.get("experiment_id", "")).strip() or None,
            title=str(cmd.get("title", "")).strip() or None,
            sample=str(cmd.get("sample", "")).strip() or None,
            notes=str(cmd.get("notes", "")).strip() or None,
            description=str(cmd.get("description", "")).strip() or None,
            custom_fields=_normalize_custom_fields_payload(cmd.get("custom_fields")),
            end_time=_parse_experiment_time(cmd.get("end_time")),
        )
        return {"ok": True, "experiment": info.to_payload()}

    if action == "experiment_get_archive_item":
        experiment_id = str(cmd.get("experiment_id", "")).strip()
        if not experiment_id:
            raise ValueError("experiment_id is required.")
        entry = experiment_manager.get_archive_item(experiment_id)
        return {"ok": True, "entry": entry.to_payload() if entry else None}

    if action == "experiment_attach_run_record":
        record = experiment_manager.attach_run_record(
            experiment_id=str(cmd.get("experiment_id", "")).strip() or None,
            source_tab=str(cmd.get("source_tab", "")).strip(),
            source_module=str(cmd.get("source_module", "")).strip(),
            run_type=str(cmd.get("run_type", "")).strip(),
            status=str(cmd.get("status", "")).strip(),
            started_at=_parse_experiment_time(cmd.get("started_at")),
            finished_at=_parse_experiment_time(cmd.get("finished_at")),
            source_run_id=str(cmd.get("source_run_id", "")).strip() or None,
            parameters=_normalize_dict_payload(cmd.get("parameters")),
            result_summary=_normalize_dict_payload(cmd.get("result_summary")),
            artifact_paths=[str(item).strip() for item in list(cmd.get("artifact_paths") or []) if str(item).strip()],
        )
        return {
            "ok": True,
            "attached": record is not None,
            "run_record": record.to_payload() if record else None,
        }

    if action == "experiment_create_retroactive":
        info = experiment_manager.create_retroactive_experiment(
            template_id=str(cmd.get("template_id", "custom")).strip() or "custom",
            title=str(cmd.get("title", "")).strip(),
            operator=str(cmd.get("operator", "")).strip(),
            start_time=_parse_experiment_time(cmd.get("start_time")),
            end_time=_parse_experiment_time(cmd.get("end_time")),
            sample=str(cmd.get("sample", "")).strip(),
            cryostat=str(cmd.get("cryostat", "")).strip(),
            description=str(cmd.get("description", "")).strip(),
            notes=str(cmd.get("notes", "")).strip(),
            custom_fields=_normalize_custom_fields_payload(cmd.get("custom_fields")),
        )
        return {"ok": True, "experiment": info.to_payload()}

    if action == "experiment_generate_report":
        experiment_id = str(cmd.get("experiment_id", "")).strip()
        if not experiment_id:
            raise ValueError("experiment_id is required for report generation.")
        raw_force = cmd.get("force", False)
        if type(raw_force) is not bool:
            return {
                "ok": False,
                "error_code": "invalid_force",
                "error": "force must be an exact JSON boolean",
            }
        force = raw_force is True
        force_context = cmd.get("force_context")
        operator = cmd.get("operator")
        if not force and ("force_context" in cmd or "operator" in cmd):
            return {
                "ok": False,
                "error_code": "invalid_force",
                "error": "force_context/operator require force=true",
            }
        if force:
            if (
                not isinstance(force_context, str)
                or len(force_context) != 64
                or any(char not in "0123456789abcdef" for char in force_context)
                or not isinstance(operator, str)
                or not (1 <= len(operator) <= 128)
                or operator != operator.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in operator)
            ):
                return {
                    "ok": False,
                    "error_code": "invalid_force",
                    "error": "force_context/operator are invalid",
                }
        runner = ReportProcessRunner(experiment_manager.data_dir)
        try:
            if force:
                report, generation_id = runner.generate_experiment_detailed(
                    experiment_id,
                    force=True,
                    force_context=force_context,
                    operator=operator,
                )
            else:
                report = runner.generate_experiment(experiment_id)
                generation_id = None
        except ReportProcessError as exc:
            return {
                "ok": False,
                "error_code": exc.error_code,
                "error": exc.error_text,
            }
        return {
            "ok": True,
            "report": report,
            "forced": force,
            "audit_id": generation_id,
        }

    if action == "experiment_advance_phase":
        expected_experiment_id = cmd.get("experiment_id")
        if type(expected_experiment_id) is not str or not expected_experiment_id:
            return {
                "ok": False,
                "error_code": "experiment_id_required",
                "error": "experiment_id must identify the experiment that owns this phase command",
            }
        if "expected_experiment_id" in cmd and cmd.get("expected_experiment_id") != expected_experiment_id:
            return {
                "ok": False,
                "error_code": "experiment_identity_conflict",
                "error": "expected_experiment_id must exactly match experiment_id",
                "retry_safe": False,
                "experiment_id": expected_experiment_id,
            }
        phase = str(cmd.get("phase", "")).strip()
        operator = str(cmd.get("operator", "")).strip()
        try:
            entry = experiment_manager.advance_phase(
                phase,
                operator,
                expected_experiment_id=expected_experiment_id,
            )
        except ExperimentIdentityMismatchError:
            return {
                "ok": False,
                "error_code": "stale_experiment_command",
                "error": "Experiment identity changed before the command could commit.",
                "experiment_id": expected_experiment_id,
            }
        return {"ok": True, "phase": entry, "experiment_id": expected_experiment_id}

    if action == "experiment_phase_status":
        current = experiment_manager.get_current_phase()
        history = experiment_manager.get_phase_history()
        elapsed = 0.0
        if history and history[-1].get("ended_at") is None:
            from datetime import datetime as _dt

            try:
                started = _dt.fromisoformat(history[-1]["started_at"])
                elapsed = (_dt.now(UTC) - started.astimezone(UTC)).total_seconds()
            except Exception as exc:
                logger.warning(
                    "Experiment phase elapsed-time projection failed: exception=%s",
                    type(exc).__name__,
                )
        return {
            "ok": True,
            "experiment_id": (
                experiment_manager.active_experiment.experiment_id
                if experiment_manager.active_experiment is not None
                else None
            ),
            "current_phase": current,
            "phases": history,
            "elapsed_in_phase_s": elapsed,
        }

    raise ValueError(f"Unsupported experiment command: {action}")


def _run_calibration_v2_command(
    action: str,
    cmd: dict[str, Any],
    calibration_store: Any,
) -> dict[str, Any]:
    """Sync calibration fitter commands — runs in thread to avoid blocking event loop."""
    from cryodaq.analytics.calibration_fitter import (
        CalibrationFitter,
        CalibrationSourceReadError,
    )

    fitter = CalibrationFitter()
    raw_channel = cmd.get("raw_channel")

    def _source_read_failure(skipped_sources: tuple[Path, ...]) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": "calibration_source_unreadable",
            "error": "Calibration source data could not be read; no result was produced.",
            "unreadable_sources": [str(path) for path in skipped_sources],
        }

    if action == "calibration_v2_extract":
        extraction = fitter.extract_pairs(
            _DATA_DIR,
            float(cmd.get("start_ts", 0)),
            float(cmd.get("end_ts", 0)),
            str(cmd["reference_channel"]),
            str(cmd["target_channel"]),
            raw_channel=raw_channel,
        )
        if extraction.skipped_sources:
            return _source_read_failure(extraction.skipped_sources)
        pairs = extraction.pairs
        return {"ok": True, "pair_count": len(pairs), "pairs_sample": pairs[:20]}
    if action == "calibration_v2_coverage":
        extraction = fitter.extract_pairs(
            _DATA_DIR,
            float(cmd.get("start_ts", 0)),
            float(cmd.get("end_ts", 0)),
            str(cmd["reference_channel"]),
            str(cmd["target_channel"]),
            raw_channel=raw_channel,
        )
        if extraction.skipped_sources:
            return _source_read_failure(extraction.skipped_sources)
        pairs = extraction.pairs
        coverage = fitter.compute_coverage(pairs)
        return {"ok": True, "coverage": coverage, "total_points": len(pairs)}
    if action == "calibration_v2_fit":
        try:
            result = fitter.fit(
                _DATA_DIR,
                float(cmd.get("start_ts", 0)),
                float(cmd.get("end_ts", 0)),
                str(cmd["reference_channel"]),
                str(cmd["target_channel"]),
                calibration_store,
                raw_channel=raw_channel,
            )
        except CalibrationSourceReadError as exc:
            return _source_read_failure(exc.skipped_sources)
        return {
            "ok": True,
            "sensor_id": result.sensor_id,
            "curve_id": result.curve.curve_id,
            "metrics": result.metrics,
            "raw_count": result.raw_pairs_count,
            "downsampled_count": result.downsampled_count,
            "breakpoint_count": result.breakpoint_count,
        }
    raise ValueError(f"Unknown calibration_v2 action: {action}")


def _get_memory_mb() -> float:
    """Получить RSS-память в MB (кроссплатформенно).

    Порядок попыток: psutil (наиболее точный RSS) → ctypes/Windows → resource/Unix.
    """
    try:
        import os

        import psutil  # type: ignore[import]

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        pass
    try:
        import ctypes
        import ctypes.wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _PMC()
        counters.cb = ctypes.sizeof(_PMC)
        ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        )
        return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    try:
        import resource as _resource  # Unix only

        return _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Загрузка конфигурации приборов
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DriverLoadResult:
    """Atomically constructed scheduler inputs with reviewed provenance.

    ``validated_configs`` preserves the exact canonical registry specs used to
    construct ``instrument_configs``.  Source authority is recorded while
    those pairs are still together; downstream code must not rediscover it
    from driver names, methods, or structural protocol conformance.
    """

    instrument_configs: tuple[InstrumentConfig, ...]
    validated_configs: tuple[ValidatedInstrumentConfig, ...]
    reviewed_source: InstrumentDriver | None
    reviewed_source_binding: ReviewedSourceBinding | None


def _load_drivers(
    config_path: Path,
    *,
    mock: bool,
    calibration_store: CalibrationStore | None = None,
    data_dir: Path | None = None,
) -> DriverLoadResult:
    """Validate and atomically construct the configured built-in drivers."""

    try:
        with config_path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise DriverRegistryError(f"{config_path}: unable to decode instrument config") from exc

    if not isinstance(raw, dict):
        raise DriverRegistryError(f"{config_path}: root config must be a mapping")
    if any(not isinstance(key, str) for key in raw):
        raise DriverRegistryError(f"{config_path}: root config keys must be strings")
    if "health_nodes" in raw:
        raise DriverRegistryError(
            f"{config_path}: health_nodes is not supported by the production engine; "
            "infrastructure health remains explicitly unavailable"
        )

    try:
        context = DriverConstructionContext.from_root_config(
            raw,
            mock=mock,
            calibration_store=calibration_store,
            data_dir=_DATA_DIR if data_dir is None else data_dir,
        )
        validated = validate_instrument_entries(raw.get("instruments", []))
    except DriverRegistryError as exc:
        raise DriverRegistryError(f"{config_path}: {exc}") from exc

    reviewed_configs = tuple(config for config in validated if config.spec.reviewed_source_binding is not None)
    if len(reviewed_configs) > 1:
        names = ", ".join(config.name for config in reviewed_configs)
        raise DriverRegistryError(
            f"{config_path}: instruments define multiple reviewed sources ({names}); "
            "SafetyManager supports exactly zero or one reviewed source"
        )

    instrument_configs: list[InstrumentConfig] = []
    reviewed_source: InstrumentDriver | None = None
    reviewed_binding: ReviewedSourceBinding | None = None
    for index, config in enumerate(validated):
        try:
            driver = construct_driver(config, context)
        except Exception as exc:
            raise DriverRegistryError(
                f"{config_path}: instruments[{index}] ({config.name!r}, "
                f"type {config.spec.type_name!r}) construction failed"
            ) from exc

        values = config.values
        poll_interval_s = values["poll_interval_s"]
        assert isinstance(poll_interval_s, float)
        resource = values.get("resource", "")
        assert isinstance(resource, str)
        instrument_configs.append(
            InstrumentConfig(
                driver=driver,
                poll_interval_s=poll_interval_s,
                resource_str=resource,
            )
        )

        binding = config.spec.reviewed_source_binding
        if binding is not None:
            if (
                not is_reviewed_source_binding(binding)
                or binding.driver_type != config.spec.type_name
                or not isinstance(driver, ControlledSource)
                or not isinstance(driver, VerifiedOffSource)
            ):
                raise DriverRegistryError(
                    f"{config_path}: instruments[{index}] ({config.name!r}, "
                    f"type {config.spec.type_name!r}) violates the reviewed source contract"
                )
            reviewed_source = driver
            reviewed_binding = binding

    for config, scheduler_config in zip(validated, instrument_configs, strict=True):
        logger.info(
            "Прибор сконфигурирован: %s (%s), ресурс=%s, интервал=%.2f с",
            config.name,
            config.spec.type_name,
            scheduler_config.resource_str,
            scheduler_config.poll_interval_s,
        )

    return DriverLoadResult(
        instrument_configs=tuple(instrument_configs),
        validated_configs=validated,
        reviewed_source=reviewed_source,
        reviewed_source_binding=reviewed_binding,
    )


# ---------------------------------------------------------------------------
# Самодиагностика (watchdog)
# ---------------------------------------------------------------------------


async def _watchdog(
    broker: DataBroker,
    scheduler: Scheduler,
    writer: SQLiteWriter,
    start_ts: float,
) -> None:
    """Периодически логирует heartbeat, статистику и потребление памяти."""
    try:
        while True:
            await asyncio.sleep(_WATCHDOG_INTERVAL_S)

            uptime_s = time.monotonic() - start_ts
            hours, remainder = divmod(int(uptime_s), 3600)
            minutes, secs = divmod(remainder, 60)

            mem_mb = _get_memory_mb()

            broker_stats = broker.stats
            sched_stats = scheduler.stats
            writer_stats = writer.stats

            total_queued = sum(s.get("queued", 0) for s in broker_stats.values())
            total_dropped = sum(s.get("dropped", 0) for s in broker_stats.values())

            logger.info(
                "HEARTBEAT | uptime=%02d:%02d:%02d | mem=%.1f MB | "
                "queued=%d | dropped=%d | written=%d | instruments=%s",
                hours,
                minutes,
                secs,
                mem_mb,
                total_queued,
                total_dropped,
                writer_stats.get("total_written", 0),
                {k: v.get("total_reads", 0) for k, v in sched_stats.items()},
            )
    except asyncio.CancelledError:
        return


# ---------------------------------------------------------------------------
# Основной цикл
# ---------------------------------------------------------------------------


def _set_safety_task_ref(safety_manager: Any, role: str, task: asyncio.Task[Any]) -> None:
    """on_spawn-хук для safety_collect/safety_monitor: синхронизирует ссылку на
    перезапущенную задачу в SafetyManager, чтобы stop() и sweep завершения
    видели живую задачу (раньше — вложенная lambda в _run_engine)."""
    safety_manager.replace_operator_child(role, task)


def _engine_config_path(name: str) -> Path:
    """Resolve a config, preferring the machine-local override."""
    local = _CONFIG_DIR / f"{name}.local.yaml"
    return local if local.exists() else _CONFIG_DIR / f"{name}.yaml"


def _log_physical_policy_receipt(policy: str, receipt: PhysicalPolicyReceipt) -> None:
    """Record the exact physical-policy bytes accepted by one loader."""
    log = logger.warning if receipt.origin == "local_override" else logger.info
    log(
        "Physical policy provenance: policy=%s source=%s origin=%s sha256=%s",
        policy,
        receipt.selected_path.name,
        receipt.origin,
        receipt.sha256,
    )


def _load_cooldown_config(path: Path) -> tuple[dict[str, Any], PhysicalPolicyReceipt]:
    """Read and parse one cooldown policy snapshot exactly once."""
    snapshot = path.read_bytes()
    raw = yaml.safe_load(snapshot) or {}
    if not isinstance(raw, dict):
        raise TypeError(f"cooldown.yaml at {path}: expected mapping, got {type(raw).__name__}")
    return raw, receipt_for_applied_policy("cooldown", path, snapshot)


async def _load_live_descriptor_authority(
    instruments_cfg: Path,
    driver_load: DriverLoadResult,
):
    """Load and validate production descriptor authority off the event loop."""

    descriptor_base = _CONFIG_DIR / "channel_descriptors.yaml"
    descriptor_local = (
        _CONFIG_DIR / "channel_descriptors.local.yaml" if instruments_cfg.name == "instruments.local.yaml" else None
    )
    owner = await asyncio.to_thread(
        load_live_channel_descriptor_catalog,
        descriptor_base,
        local_path=descriptor_local,
    )
    owner.require_exact_instruments(tuple(config.name for config in driver_load.validated_configs))
    return owner


@dataclass(slots=True)
class _SafetyFaultLogContext:
    writer: Any
    broker: Any
    alarm_dispatch_tasks: set[asyncio.Task[Any]]
    event_bus: Any | None = None
    experiment_manager: Any | None = None
    telegram_bot: Any | None = None


async def _safety_fault_log_callback(
    source: str,
    message: str,
    channel: str = "",
    value: float = 0.0,
    *,
    context: _SafetyFaultLogContext,
) -> None:
    """Persist and publish a SafetyManager fault through the existing paths."""
    entry = await context.writer.append_operator_log(
        message=message,
        author=source,
        source="machine",
        tags=("safety_fault", channel) if channel else ("safety_fault",),
    )
    try:
        await _publish_operator_log_entry(context.broker, entry)
    except Exception as exc:
        logger.error(
            "Safety fault operator-log publication failed: exception=%s",
            type(exc).__name__,
        )

    try:
        await _dispatch_alarm_notification(
            context.event_bus,
            context.alarm_dispatch_tasks,
            alarm_id=f"safety_fault_{source}" if source else "safety_fault",
            level="CRITICAL",
            message=message,
            experiment_id=context.experiment_manager.active_experiment_id,
            telegram_bot=context.telegram_bot,
            channel=channel,
            value=value,
        )
    except Exception as exc:
        logger.error(
            "Safety fault notification dispatch failed: exception=%s",
            type(exc).__name__,
        )


@dataclass(slots=True)
class _InterlockHandlerContext:
    safety_manager: Any
    alarm_dispatch_tasks: set[asyncio.Task[Any]]
    dead_channel_alarm_sent: set[str]
    event_bus: Any | None = None
    experiment_manager: Any | None = None


async def _interlock_noop() -> None:
    return None


async def _interlock_trip_handler(
    condition: Any,
    reading: Any,
    *,
    context: _InterlockHandlerContext,
) -> None:
    """Route an interlock trip to SafetyManager, failing closed on errors."""
    try:
        await context.safety_manager.on_interlock_trip(
            interlock_name=condition.name,
            channel=reading.channel,
            value=float(reading.value) if reading.value is not None else 0.0,
            action=condition.action,
        )
    except Exception as exc:
        logger.critical(
            "Interlock trip handler failed; action=%s exception=%s; escalating to fault",
            _bounded_action_label(condition.action),
            type(exc).__name__,
        )
        try:
            await context.safety_manager.latch_fault(
                reason=f"interlock_trip_handler_failed:{type(exc).__name__}",
                source="interlock",
                channel=reading.channel,
                value=float(reading.value) if reading.value is not None else 0.0,
            )
        except Exception as exc2:
            logger.critical(
                "Interlock fault escalation failed: exception=%s; instrument state is unknown",
                type(exc2).__name__,
            )


async def _interlock_dead_channel_handler(
    condition: Any,
    reading: Any,
    *,
    context: _InterlockHandlerContext,
) -> bool:
    """Route a persistently unusable protected channel, preserving retry policy."""
    try:
        escalated = await context.safety_manager.on_interlock_dead_channel(
            condition.name,
            reading.channel,
            value=float(reading.value) if reading.value is not None else float("nan"),
        )
    except Exception as exc:
        logger.critical(
            "Interlock dead-channel handler failed: exception=%s; escalating to fault",
            type(exc).__name__,
        )
        try:
            await context.safety_manager.latch_fault(
                reason=f"interlock_dead_channel_handler_failed:{type(exc).__name__}",
                source="interlock",
                channel=reading.channel,
            )
            return True
        except Exception as exc2:
            logger.critical(
                "Interlock dead-channel escalation failed: exception=%s",
                type(exc2).__name__,
            )
            return False

    key = f"{condition.name}:{reading.channel}"
    if _should_dispatch_dead_channel_alarm(key, escalated, context.dead_channel_alarm_sent):
        try:
            await _dispatch_alarm_notification(
                context.event_bus,
                context.alarm_dispatch_tasks,
                alarm_id=f"dead_channel_{reading.channel}",
                level="WARNING",
                message=(
                    f"Интерлок-канал {reading.channel} ('{condition.name}') "
                    "устойчиво непригоден, источник неактивен — fault не "
                    "латчится, но требуется внимание оператора."
                ),
                experiment_id=context.experiment_manager.active_experiment_id,
                channel=reading.channel,
                value=float(reading.value) if reading.value is not None else float("nan"),
            )
        except Exception as exc:
            logger.error(
                "Dead-channel notification dispatch failed: exception=%s",
                type(exc).__name__,
            )
    return escalated


def _interlock_dead_channel_recovery_handler(
    condition: Any,
    reading: Any,
    *,
    context: _InterlockHandlerContext,
) -> None:
    """Clear the exact blocker and alarm episode after usable evidence."""
    context.safety_manager.on_interlock_channel_recovered(
        condition.name,
        reading.channel,
    )
    channel_suffix = f":{reading.channel}"
    keys_to_clear = {key for key in context.dead_channel_alarm_sent if key.endswith(channel_suffix)}
    context.dead_channel_alarm_sent.difference_update(keys_to_clear)


async def _multiline_burst_auto_stop(
    driver_name: str,
    delay_s: float,
    *,
    drivers_by_name: dict[str, Any],
    experiments_root: Path,
    auto_stop_tasks: dict[str, asyncio.Task[None]],
) -> None:
    """Stop a timed MultiLine burst and remove its task bookkeeping entry."""
    try:
        await asyncio.sleep(delay_s)
        driver = drivers_by_name.get(driver_name)
        if driver is None:
            return
        try:
            path = await driver.burst_stop(experiments_root=experiments_root)
            logger.info(
                "MultiLine '%s' burst auto-stopped after %.1fs → %s",
                driver_name,
                delay_s,
                path,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "MultiLine auto-stop failed: driver=%s exception=%s",
                _bounded_action_label(driver_name),
                type(exc).__name__,
            )
    finally:
        auto_stop_tasks.pop(driver_name, None)


def _request_shutdown(shutdown_event: asyncio.Event, *_signal_args: Any) -> None:
    logger.info("Получен сигнал завершения")
    shutdown_event.set()


_EXPERIMENT_MUTATION_ACTIONS = frozenset(
    {
        "set_app_mode",
        "experiment_start",
        "experiment_create",
        "experiment_update",
        "experiment_finalize",
        "experiment_stop",
        "experiment_abort",
        "experiment_attach_run_record",
        "experiment_create_retroactive",
        "experiment_generate_report",
        "experiment_advance_phase",
    }
)
_EXPERIMENT_READ_ACTIONS = frozenset(
    {
        "get_app_mode",
        "experiment_templates",
        "experiment_archive_list",
        "experiment_list_archive",
        "experiment_get_active",
        "experiment_get_archive_item",
        "experiment_phase_status",
    }
)
_MAX_PENDING_EXPERIMENT_READS = 4
_MAX_PENDING_OPERATOR_LOG_ENTRIES = 4
_MAX_PENDING_ALARM_ACK_ENTRIES = 4
_OPERATOR_LOG_RECONCILE_BACKOFF_BASE_S = 0.05
_OPERATOR_LOG_RECONCILE_BACKOFF_MAX_S = 2.0
_ALARM_ACK_RECONCILE_BACKOFF_BASE_S = 0.05
_ALARM_ACK_RECONCILE_BACKOFF_MAX_S = 2.0
_MAX_OPERATOR_LOG_IDEMPOTENCY_RECEIPTS = 4096
_MUTATION_PROTOCOL_MAJOR = MUTATION_PROTOCOL_MAJOR
_MUTATION_CAPABILITY = ENGINE_MUTATION_CAPABILITY
_MUTATION_RECEIPT_SCHEMA = MUTATION_RECEIPT_SCHEMA
_MUTATION_ENVELOPE_KEYS = MUTATION_ENVELOPE_KEYS


@dataclass(slots=True)
class EngineCommandContext:
    safety_manager: Any
    event_logger: Any
    sink_registry: Any
    interlock_engine: Any
    leak_rate_estimator: Any
    leak_cfg: dict[str, Any]
    alarm_v2_state_mgr: Any
    alarm_ring: Any
    broker: Any
    experiment_manager: Any
    calibration_acquisition: Any
    event_bus: Any
    cooldown_alarm: Any
    vacuum_guard: Any
    alarm_dispatch_tasks: set[asyncio.Task[Any]]
    calibration_store: Any
    writer: Any
    drivers_by_name: dict[str, Any]
    sensor_diag: Any
    vacuum_trend: Any
    alarm_v2_state_tracker: Any
    multiline_burst_auto_stop_meta: dict[str, dict[str, Any]]
    multiline_burst_auto_stop_tasks: dict[str, asyncio.Task[None]]
    shutdown_event: asyncio.Event | None = None
    engine_instance_id: str = ""
    shutdown_capability: str = ""
    engine_ready_nonce: str = ""
    engine_ready_channel_fd: int | None = None
    engine_ready_pid: int = 0
    engine_ready_advertised: bool = False
    escalation_service: Any = None
    cooldown_service: Any = None
    zmq_publisher: ZMQPublisher | None = None
    recording_lifecycle_feed: RecordingLifecycleFeed | None = None
    annunciation_registry: AnnunciationRegistry | None = None
    experiment_command_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    experiment_command_tasks: set[asyncio.Task[dict[str, Any]]] = field(default_factory=set)
    experiment_read_tasks: set[asyncio.Task[dict[str, Any]]] = field(default_factory=set)
    experiment_status_task: asyncio.Task[dict[str, Any]] | None = None
    experiment_commands_accepting: bool = True
    mutation_capability_token: str | None = None
    operator_log_tasks: dict[str, tuple[str, asyncio.Task[dict[str, Any]]]] = field(default_factory=dict)
    operator_log_reconciliation_tasks: dict[str, tuple[str, asyncio.Task[dict[str, Any]]]] = field(default_factory=dict)
    operator_log_receipts: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    alarm_ack_tasks: dict[str, tuple[str, asyncio.Task[dict[str, Any]]]] = field(default_factory=dict)
    alarm_ack_reconciliation_tasks: dict[str, tuple[str, asyncio.Task[dict[str, Any]]]] = field(default_factory=dict)
    alarm_ack_receipts: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    alarm_ack_activation_owners: dict[tuple[str, str], asyncio.Future[None]] = field(default_factory=dict)
    shutdown_request_id: str | None = None
    shutdown_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    shutdown_receipt: dict[str, Any] | None = None


def _engine_ready_receipt(context: EngineCommandContext) -> dict[str, Any] | None:
    nonce = context.engine_ready_nonce
    instance_id = context.engine_instance_id
    pid = context.engine_ready_pid
    if (
        not context.engine_ready_advertised
        or type(nonce) is not str
        or len(nonce) != 64
        or any(char not in "0123456789abcdef" for char in nonce)
        or type(instance_id) is not str
        or len(instance_id) != 32
        or any(char not in "0123456789abcdef" for char in instance_id)
        or type(pid) is not int
        or pid <= 0
    ):
        return None
    return {
        "schema": _ENGINE_READY_SCHEMA,
        "nonce": nonce,
        "engine_instance_id": instance_id,
        "mode": "live",
        "pid": pid,
        "pub_addr": DEFAULT_PUB_ADDR,
        "cmd_addr": DEFAULT_CMD_ADDR,
        "safe_cmd_addr": DEFAULT_SAFE_CMD_ADDR,
    }


def _engine_ready_response(
    cmd: dict[str, Any],
    context: EngineCommandContext,
) -> dict[str, Any]:
    """Answer only one exact launcher-owned startup challenge."""

    if type(cmd) is not dict or cmd.get("cmd") != "engine_ready":
        return {"ok": False, "error_code": "engine_ready_invalid"}
    receipt = _engine_ready_receipt(context)
    if receipt is None:
        return {"ok": False, "error_code": "engine_ready_unavailable"}
    expected_keys = {"cmd", "nonce", "engine_instance_id", "pid", "pub_addr", "cmd_addr", "safe_cmd_addr"}
    if set(cmd) != expected_keys:
        return {"ok": False, "error_code": "engine_ready_invalid"}
    expected_values = {
        "nonce": receipt["nonce"],
        "engine_instance_id": receipt["engine_instance_id"],
        "pid": receipt["pid"],
        "pub_addr": receipt["pub_addr"],
        "cmd_addr": receipt["cmd_addr"],
        "safe_cmd_addr": receipt["safe_cmd_addr"],
    }
    for key, expected in expected_values.items():
        value = cmd.get(key)
        if type(value) is not type(expected) or value != expected:
            return {"ok": False, "error_code": "engine_ready_mismatch"}
    return {"ok": True, **receipt}


def _safe_engine_command_is_admitted(
    cmd: dict[str, Any],
    *,
    context: EngineCommandContext,
) -> bool:
    """Admit only one exact readiness proof or one exact safe direction."""

    if type(cmd) is not dict:
        return False
    if cmd.get("cmd") == "engine_ready":
        return _engine_ready_response(cmd, context).get("ok") is True
    return is_exact_safe_direction_envelope(cmd)


def _emit_engine_ready_receipt(context: EngineCommandContext) -> None:
    """Emit one machine-only receipt and permanently close its private pipe."""

    if context.engine_ready_advertised:
        raise RuntimeError("engine readiness was already advertised")
    descriptor = context.engine_ready_channel_fd
    if type(descriptor) is not int or descriptor <= 2:
        raise RuntimeError("engine readiness channel is unavailable")
    try:
        # Build with a temporary flag so validation and serialization use the
        # same exact receipt that the REP challenge will expose after
        # publication.
        context.engine_ready_advertised = True
        receipt = _engine_ready_receipt(context)
        context.engine_ready_advertised = False
        if receipt is None:
            raise RuntimeError("engine readiness authority is unavailable")
        payload = json.dumps(
            receipt,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        wire = _ENGINE_READY_WIRE_PREFIX + payload + b"\n"
        if len(wire) > 1024:
            raise RuntimeError("engine readiness receipt exceeds wire bound")
        offset = 0
        while offset < len(wire):
            written = os.write(descriptor, wire[offset:])
            if written <= 0:
                raise OSError("engine readiness pipe write made no progress")
            offset += written
    finally:
        context.engine_ready_channel_fd = None
        os.close(descriptor)
    context.engine_ready_advertised = True


def _is_mutating_command(action: object) -> bool:
    return is_mutation(action)


def _valid_mutation_capability_token(token: object) -> bool:
    return valid_capability_token(token)


def _mutation_protocol_failure(
    cmd: dict[str, Any],
    context: EngineCommandContext,
) -> dict[str, Any] | None:
    if not requires_compatibility(cmd.get("cmd")):
        return None
    token = context.mutation_capability_token
    major = cmd.get("protocol_major")
    capability = cmd.get("mutation_capability")
    presented_token = cmd.get("capability_token")
    compatible = (
        _valid_mutation_capability_token(token)
        and type(major) is int
        and major == _MUTATION_PROTOCOL_MAJOR
        and capability == _MUTATION_CAPABILITY
        and type(presented_token) is str
        and secrets.compare_digest(presented_token, token)
    )
    if compatible:
        return None
    return {
        "ok": False,
        "error_code": "mutation_protocol_incompatible",
        "error": "mutating command refused; perform mutation_capabilities discovery and retry explicitly",
        "delivery_state": "dispatched",
        "commit_state": "not_committed",
        "retry_safe": True,
        "compatibility_receipt": {
            "schema": _MUTATION_RECEIPT_SCHEMA,
            "accepted": False,
            "server_protocol_major": _MUTATION_PROTOCOL_MAJOR,
            "required_capability": _MUTATION_CAPABILITY,
        },
    }


def _operator_log_command_admission(cmd: dict[str, Any]) -> tuple[Any, str]:
    """Validate one untrusted command and fingerprint the persisted tuple."""

    keys = set(cmd)
    if not _OPERATOR_LOG_COMMAND_REQUIRED_KEYS.issubset(keys) or not keys.issubset(_OPERATOR_LOG_COMMAND_ALLOWED_KEYS):
        raise RuntimeError("operator-log command schema is invalid")
    if cmd.get("cmd") != "log_entry":
        raise RuntimeError("operator-log command action is invalid")
    if "tags" in cmd and (type(cmd["tags"]) is not list or any(type(tag) is not str for tag in cmd["tags"])):
        raise RuntimeError("operator-log tags must be an exact string list")
    if "experiment_id" in cmd:
        if "experiment_unbound" in cmd:
            raise RuntimeError("operator-log experiment binding conflicts")
        experiment_id = cmd["experiment_id"]
    else:
        if cmd.get("experiment_unbound") is not True:
            raise RuntimeError("operator-log experiment binding is ambiguous")
        experiment_id = None
    admission = SQLiteWriter.validate_operator_log_publication_admission(
        request_id=cmd["request_id"],
        message=cmd["message"],
        author=cmd["author"],
        source=cmd["source"],
        experiment_id=experiment_id,
        tags=cmd.get("tags"),
    )
    if admission.source not in _OPERATOR_LOG_UNTRUSTED_SOURCES:
        raise RuntimeError("operator-log source is not an untrusted ingress role")
    if admission.author.casefold() in _OPERATOR_LOG_RESERVED_ACTORS:
        raise RuntimeError("operator-log author impersonates a reserved actor")
    if any(tag.casefold() in _OPERATOR_LOG_RESERVED_TAGS for tag in admission.tags):
        raise RuntimeError("operator-log tags impersonate an internal event")
    semantic = {
        "schema": "operator_log_request_v1",
        "experiment_id": admission.experiment_id,
        "author": admission.author,
        "source": admission.source,
        "message": admission.message,
        "tags": list(admission.tags),
    }
    canonical = json.dumps(
        semantic,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return admission, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _operator_log_entry_matches_admission(entry: object, admission: Any) -> bool:
    return (
        type(entry) is OperatorLogEntry
        and entry.experiment_id == admission.experiment_id
        and entry.author == admission.author
        and entry.source == admission.source
        and entry.message == admission.message
        and entry.tags == admission.tags
    )


def _operator_log_success(entry: OperatorLogEntry, request_id: str) -> dict[str, Any]:
    payload = entry.to_payload()
    receipt = {
        "schema": _OPERATOR_LOG_COMMIT_SCHEMA,
        "request_id": request_id,
        "entry_id": entry.id,
        "experiment_id": entry.experiment_id,
        "committed": True,
    }
    event_copy, receipt_copy = SQLiteWriter.validate_operator_log_publication(
        request_id=request_id,
        event={"schema": _OPERATOR_LOG_COMMIT_SCHEMA, "entry": payload},
        receipt=receipt,
    )
    return {
        "ok": True,
        "committed": True,
        "retry_safe": False,
        "publication_state": "published",
        "entry": event_copy["entry"],
        "commit_receipt": receipt_copy,
    }


def _operator_log_committed_pending(entry: OperatorLogEntry, request_id: str) -> dict[str, Any]:
    success = _operator_log_success(entry, request_id)
    return {
        "ok": False,
        "committed": True,
        "retry_safe": False,
        "publication_state": "pending",
        "error_code": "committed_reconciliation_failed",
        "error": "operator log committed, but required publication remains pending",
        "entry": success["entry"],
        "commit_receipt": success["commit_receipt"],
    }


def _strict_operator_log_success(result: object, request_id: str) -> dict[str, Any] | None:
    """Detach only one exact, published, fully bound success receipt."""

    if type(result) is not dict or set(result) != _OPERATOR_LOG_SUCCESS_KEYS:
        return None
    if (
        result.get("ok") is not True
        or result.get("committed") is not True
        or result.get("retry_safe") is not False
        or result.get("publication_state") != "published"
    ):
        return None
    entry = result.get("entry")
    receipt = result.get("commit_receipt")
    try:
        event_copy, receipt_copy = SQLiteWriter.validate_operator_log_publication(
            request_id=request_id,
            event={"schema": _OPERATOR_LOG_COMMIT_SCHEMA, "entry": entry},
            receipt=receipt,
        )
    except RuntimeError:
        return None
    return {
        "ok": True,
        "committed": True,
        "retry_safe": False,
        "publication_state": "published",
        "entry": event_copy["entry"],
        "commit_receipt": receipt_copy,
    }


async def _await_retained_operator_log(operation: Awaitable[Any], *, name: str) -> Any:
    """Retain one persistence/publication owner through caller cancellation.

    Delegates to the canonical ``shutdown_settlement.await_executor_owner``: a
    terminal operation failure outranks caller cancellation so a caller cannot
    turn a failed persistence/publication mutation into an apparently harmless
    cancel. See ``cryodaq.core.shutdown_settlement`` and
    ``cryodaq.core.housekeeping`` for the sibling owners of this same
    settlement primitive.
    """

    task = asyncio.create_task(operation, name=name)
    return await await_executor_owner(task)


async def _settle_operator_log_publication(
    *,
    context: EngineCommandContext,
    entry: OperatorLogEntry,
    request_id: str,
    request_fingerprint: str,
    publication: object | None = None,
) -> None:
    payload = entry.to_payload()
    receipt = {
        "schema": _OPERATOR_LOG_COMMIT_SCHEMA,
        "request_id": request_id,
        "entry_id": entry.id,
        "experiment_id": entry.experiment_id,
        "committed": True,
    }
    event = {"schema": _OPERATOR_LOG_COMMIT_SCHEMA, "entry": payload}
    if publication is None:
        publication = await _await_retained_operator_log(
            context.writer.prepare_operator_log_publication_outbox(
                request_id=request_id,
                request_fingerprint=request_fingerprint,
                event=event,
                receipt=receipt,
            ),
            name=f"operator_log_intent_reconcile_{request_id[:8]}",
        )
    state = _validated_operator_log_publication_record(
        publication,
        request_id=request_id,
        request_fingerprint=request_fingerprint,
        event=event,
        receipt=receipt,
    )
    if state == "published":
        return
    if state != "intent":
        raise RuntimeError("operator-log publication intent state is invalid")
    await _await_retained_operator_log(
        _publish_operator_log_publication(
            context.writer,
            context.broker,
            request_id=request_id,
            request_fingerprint=request_fingerprint,
            event=event,
            receipt=receipt,
        ),
        name=f"operator_log_required_publish_{request_id[:8]}",
    )


def _operator_log_publication_identity(
    entry: OperatorLogEntry,
    request_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    success = _operator_log_success(entry, request_id)
    event = {"schema": _OPERATOR_LOG_COMMIT_SCHEMA, "entry": success["entry"]}
    receipt = success["commit_receipt"]
    return SQLiteWriter.validate_operator_log_publication(
        request_id=request_id,
        event=event,
        receipt=receipt,
    )


def _validated_operator_log_publication_record(
    publication: object,
    *,
    request_id: str,
    request_fingerprint: str,
    event: dict[str, Any],
    receipt: dict[str, Any],
) -> str:
    if type(publication) is not OperatorLogPublicationOutboxRecord:
        raise RuntimeError("operator-log reconciliation record type is invalid")
    if (
        publication.request_id != request_id
        or publication.request_fingerprint != request_fingerprint
        or publication.event != event
        or publication.receipt != receipt
        or publication.state not in {"intent", "published"}
    ):
        raise RuntimeError("operator-log reconciliation authority changed")
    event_copy, receipt_copy = SQLiteWriter.validate_operator_log_publication(
        request_id=request_id,
        event=publication.event,
        receipt=publication.receipt,
    )
    if event_copy != event or receipt_copy != receipt:
        raise RuntimeError("operator-log reconciliation payload changed")
    return publication.state


async def _run_operator_log_publication_reconciliation(
    context: EngineCommandContext,
    entry: OperatorLogEntry,
    request_id: str,
    request_fingerprint: str,
) -> dict[str, Any]:
    event, receipt = _operator_log_publication_identity(entry, request_id)
    delay = _OPERATOR_LOG_RECONCILE_BACKOFF_BASE_S
    while context.experiment_commands_accepting:
        await asyncio.sleep(delay)
        if not context.experiment_commands_accepting:
            break
        try:
            publication = await _await_retained_operator_log(
                context.writer.prepare_operator_log_publication_outbox(
                    request_id=request_id,
                    request_fingerprint=request_fingerprint,
                    event=event,
                    receipt=receipt,
                ),
                name=f"operator_log_background_prepare_{request_id[:8]}",
            )
            state = _validated_operator_log_publication_record(
                publication,
                request_id=request_id,
                request_fingerprint=request_fingerprint,
                event=event,
                receipt=receipt,
            )
            if state == "intent":
                await _await_retained_operator_log(
                    _publish_operator_log_publication(
                        context.writer,
                        context.broker,
                        request_id=request_id,
                        request_fingerprint=request_fingerprint,
                        event=event,
                        receipt=receipt,
                    ),
                    name=f"operator_log_background_publish_{request_id[:8]}",
                )
                publication = await _await_retained_operator_log(
                    context.writer.prepare_operator_log_publication_outbox(
                        request_id=request_id,
                        request_fingerprint=request_fingerprint,
                        event=event,
                        receipt=receipt,
                    ),
                    name=f"operator_log_background_verify_{request_id[:8]}",
                )
                state = _validated_operator_log_publication_record(
                    publication,
                    request_id=request_id,
                    request_fingerprint=request_fingerprint,
                    event=event,
                    receipt=receipt,
                )
            if state != "published":
                raise RuntimeError("operator-log background publication is incomplete")
            result = _operator_log_success(entry, request_id)
            if _strict_operator_log_success(result, request_id) is None:
                raise RuntimeError("operator-log background success receipt is invalid")
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Operator-log background publication retry failed: request=%s exception=%s",
                request_id,
                type(exc).__name__,
            )
            delay = min(delay * 2.0, _OPERATOR_LOG_RECONCILE_BACKOFF_MAX_S)
    return _operator_log_committed_pending(entry, request_id)


def _remember_operator_log_receipt(
    context: EngineCommandContext,
    request_id: str,
    fingerprint: str,
    result: object,
) -> None:
    validated = _strict_operator_log_success(result, request_id)
    if validated is None:
        return
    context.operator_log_receipts[request_id] = (fingerprint, copy.deepcopy(validated))
    while len(context.operator_log_receipts) > _MAX_OPERATOR_LOG_IDEMPOTENCY_RECEIPTS:
        context.operator_log_receipts.pop(next(iter(context.operator_log_receipts)))


def _owned_operator_log_reconciliation_done(
    context: EngineCommandContext,
    request_id: str,
    fingerprint: str,
    task: asyncio.Task[dict[str, Any]],
) -> None:
    current = context.operator_log_reconciliation_tasks.get(request_id)
    owns_mapping = current is not None and current[0] == fingerprint and current[1] is task
    if owns_mapping:
        del context.operator_log_reconciliation_tasks[request_id]
    if task.cancelled():
        logger.critical("Operator-log reconciliation owner was cancelled: %s", request_id)
        return
    exception = task.exception()
    if exception is not None:
        logger.error(
            "Operator-log reconciliation owner failed: request=%s exception=%s",
            request_id,
            type(exception).__name__,
        )
        return
    if owns_mapping:
        _remember_operator_log_receipt(context, request_id, fingerprint, task.result())


def _ensure_operator_log_publication_reconciliation(
    context: EngineCommandContext,
    entry: OperatorLogEntry,
    request_id: str,
    request_fingerprint: str,
) -> asyncio.Task[dict[str, Any]] | None:
    _operator_log_publication_identity(entry, request_id)
    current = context.operator_log_reconciliation_tasks.get(request_id)
    if current is not None:
        if current[0] != request_fingerprint:
            raise RuntimeError("operator-log reconciliation identity conflict")
        return current[1]
    if not context.experiment_commands_accepting:
        return None
    active_ids = set(context.operator_log_tasks) | set(context.operator_log_reconciliation_tasks)
    if request_id not in active_ids and len(active_ids) >= _MAX_PENDING_OPERATOR_LOG_ENTRIES:
        raise RuntimeError("operator-log reconciliation lane is full")
    task = asyncio.create_task(
        _run_operator_log_publication_reconciliation(
            context,
            entry,
            request_id,
            request_fingerprint,
        ),
        name=f"operator_log_reconcile_{request_id[:8]}",
    )
    context.operator_log_reconciliation_tasks[request_id] = (request_fingerprint, task)
    task.add_done_callback(
        functools.partial(
            _owned_operator_log_reconciliation_done,
            context,
            request_id,
            request_fingerprint,
        )
    )
    return task


async def _execute_owned_operator_log_entry(
    *,
    request_id: str,
    request_fingerprint: str,
    admission: Any,
    context: EngineCommandContext,
) -> dict[str, Any]:
    try:
        find_request = getattr(context.writer, "find_operator_log_request", None)
        if not callable(find_request):
            raise OperatorLogIdempotencyUnavailableError("durable operator-log lookup is unavailable")
        retained = await _await_retained_operator_log(
            find_request(
                request_id=request_id,
                request_fingerprint=request_fingerprint,
            ),
            name=f"operator_log_lookup_{request_id[:8]}",
        )
        if retained is not None:
            if not _operator_log_entry_matches_admission(retained.entry, admission):
                raise OperatorLogIdempotencyConflictError("retained operator-log payload does not match request")
            try:
                await _settle_operator_log_publication(
                    context=context,
                    entry=retained.entry,
                    request_id=request_id,
                    request_fingerprint=request_fingerprint,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - committed intent stays pending
                logger.error(
                    "Committed operator log reconciliation failed: request=%s exception=%s",
                    request_id,
                    type(exc).__name__,
                )
                _ensure_operator_log_publication_reconciliation(
                    context,
                    retained.entry,
                    request_id,
                    request_fingerprint,
                )
                return _operator_log_committed_pending(retained.entry, request_id)
            return _operator_log_success(retained.entry, request_id)

        atomic_append = getattr(context.writer, "append_operator_log_with_publication_intent", None)
        if not callable(atomic_append):
            raise OperatorLogIdempotencyUnavailableError(
                "atomic operator-log append and publication intent API is unavailable"
            )

        async def append_and_settle() -> dict[str, Any]:
            atomic_result = await _await_retained_operator_log(
                atomic_append(
                    message=admission.message,
                    request_id=request_id,
                    request_fingerprint=request_fingerprint,
                    author=admission.author,
                    source=admission.source,
                    experiment_id=admission.experiment_id,
                    tags=admission.tags,
                ),
                name=f"operator_log_atomic_append_{request_id[:8]}",
            )
            if type(atomic_result) is not tuple or len(atomic_result) != 2:
                raise OperatorLogIdempotencyUnavailableError("atomic operator-log result is malformed")
            commit, publication = atomic_result
            entry = getattr(commit, "entry", None)
            if not _operator_log_entry_matches_admission(entry, admission):
                raise OperatorLogIdempotencyUnavailableError("atomic operator-log result lost payload binding")
            try:
                await _settle_operator_log_publication(
                    context=context,
                    entry=entry,
                    request_id=request_id,
                    request_fingerprint=request_fingerprint,
                    publication=publication,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - atomic commit is already durable
                logger.error(
                    "Committed operator log publication failed: request=%s exception=%s",
                    request_id,
                    type(exc).__name__,
                )
                _ensure_operator_log_publication_reconciliation(
                    context,
                    entry,
                    request_id,
                    request_fingerprint,
                )
                return _operator_log_committed_pending(entry, request_id)
            return _operator_log_success(entry, request_id)

        expected_experiment_id = admission.experiment_id
        if expected_experiment_id is None:
            return await append_and_settle()
        try:
            reservation = context.experiment_manager.experiment_cas(expected_experiment_id)
            reservation.__enter__()
        except RuntimeError:
            if context.experiment_manager.active_experiment_id != expected_experiment_id:
                return {
                    "ok": False,
                    "committed": False,
                    "error_code": "stale_experiment_command",
                    "error": "Experiment identity changed before the operator log could commit.",
                    "retry_safe": False,
                    "request_id": request_id,
                }
            return {
                "ok": False,
                "committed": False,
                "error_code": "operator_log_busy",
                "error": "another durable experiment mutation is still authoritative",
                "retry_safe": True,
                "request_id": request_id,
            }
        try:
            context.experiment_manager.assert_experiment_cas(expected_experiment_id)
            settled = await append_and_settle()
        except BaseException:
            reservation.__exit__(*sys.exc_info())
            raise
        reservation.__exit__(None, None, None)
        return settled
    except OperatorLogIdempotencyConflictError:
        return {
            "ok": False,
            "committed": False,
            "error_code": "idempotency_key_conflict",
            "error": "request_id was already committed with different content",
            "retry_safe": False,
            "request_id": request_id,
        }
    except OperatorLogCommitOutcomeUnknownError:
        return {
            "ok": False,
            "error_code": "operator_log_commit_outcome_unknown",
            "error": "operator log commit outcome is unknown; reconcile this exact request key",
            "commit_state": "unknown",
            "retry_safe": False,
            "request_id": request_id,
        }
    except OperatorLogIdempotencyUnavailableError as exc:
        logger.error(
            "Operator-log idempotency registry unavailable: request=%s exception=%s",
            request_id,
            type(exc).__name__,
        )
        return {
            "ok": False,
            "error_code": "operator_log_idempotency_unavailable",
            "error": "operator log idempotency state is unavailable",
            "retry_safe": False,
            "request_id": request_id,
        }
    except Exception as exc:  # noqa: BLE001 - atomic commit outcome is not proven
        logger.error(
            "Operator log persistence failed: request=%s exception=%s",
            request_id,
            type(exc).__name__,
        )
        return {
            "ok": False,
            "error_code": "operator_log_persistence_failed",
            "error": "operator log persistence outcome is unknown; reconcile this exact request key",
            "commit_state": "unknown",
            "retry_safe": False,
            "request_id": request_id,
        }


def _owned_operator_log_done(
    context: EngineCommandContext,
    request_id: str,
    fingerprint: str,
    task: asyncio.Task[dict[str, Any]],
) -> None:
    current = context.operator_log_tasks.get(request_id)
    owns_mapping = current is not None and current[0] == fingerprint and current[1] is task
    if owns_mapping:
        del context.operator_log_tasks[request_id]
    if task.cancelled():
        logger.critical("Operator log owner was cancelled: %s", request_id)
        return
    exception = task.exception()
    if exception is not None:
        logger.error(
            "Operator log owner failed after submission: request=%s exception=%s",
            request_id,
            type(exception).__name__,
        )
        return
    if not owns_mapping:
        return
    _remember_operator_log_receipt(context, request_id, fingerprint, task.result())


async def _submit_operator_log_entry(
    cmd: dict[str, Any],
    context: EngineCommandContext,
) -> dict[str, Any]:
    if not context.experiment_commands_accepting:
        return {
            "ok": False,
            "committed": False,
            "error_code": "engine_shutting_down",
            "error": "operator log submissions are frozen for shutdown",
            "retry_safe": True,
        }
    request_id = cmd.get("request_id")
    if (
        type(request_id) is not str
        or len(request_id) != 32
        or any(char not in "0123456789abcdef" for char in request_id)
    ):
        return {
            "ok": False,
            "committed": False,
            "error_code": "operator_log_request_id_invalid",
            "error": "request_id must be exactly 32 lowercase hexadecimal characters",
            "retry_safe": True,
        }
    try:
        admission, fingerprint = _operator_log_command_admission(cmd)
    except RuntimeError:
        return {
            "ok": False,
            "committed": False,
            "error_code": "operator_log_admission_invalid",
            "error": "Operator-log command or publication fields are invalid.",
            "retry_safe": True,
            "request_id": request_id,
        }
    completed = context.operator_log_receipts.get(request_id)
    if completed is not None:
        if completed[0] != fingerprint:
            return {
                "ok": False,
                "committed": False,
                "error_code": "idempotency_key_conflict",
                "error": "request_id was already committed with different content",
                "retry_safe": False,
            }
        return copy.deepcopy(completed[1])
    pending = context.operator_log_tasks.get(request_id)
    if pending is not None:
        if pending[0] != fingerprint:
            return {
                "ok": False,
                "committed": False,
                "error_code": "idempotency_key_conflict",
                "error": "request_id is already in flight with different content",
                "retry_safe": False,
            }
        return copy.deepcopy(await asyncio.shield(pending[1]))
    reconciliation = context.operator_log_reconciliation_tasks.get(request_id)
    if reconciliation is not None:
        if reconciliation[0] != fingerprint:
            return {
                "ok": False,
                "committed": False,
                "error_code": "idempotency_key_conflict",
                "error": "request_id is reconciling different committed content",
                "retry_safe": False,
            }
        return copy.deepcopy(await asyncio.shield(reconciliation[1]))
    active_request_ids = set(context.operator_log_tasks) | set(context.operator_log_reconciliation_tasks)
    if len(active_request_ids) >= _MAX_PENDING_OPERATOR_LOG_ENTRIES:
        return {
            "ok": False,
            "committed": False,
            "error_code": "operator_log_busy",
            "error": "the bounded operator log commit lane is full",
            "retry_safe": True,
        }
    task = asyncio.create_task(
        _execute_owned_operator_log_entry(
            request_id=request_id,
            request_fingerprint=fingerprint,
            admission=admission,
            context=context,
        ),
        name=f"operator_log_{request_id[:8]}",
    )
    context.operator_log_tasks[request_id] = (fingerprint, task)
    task.add_done_callback(functools.partial(_owned_operator_log_done, context, request_id, fingerprint))
    return copy.deepcopy(await asyncio.shield(task))


def _validated_alarm_ack_outbox(
    outbox: AlarmAckOutboxRecord,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the exact durable/public ACK identity before any side effect."""

    if type(outbox) is not AlarmAckOutboxRecord:
        raise RuntimeError("alarm ACK outbox record type is invalid")
    event = outbox.event
    receipt = outbox.receipt
    if type(event) is not dict or set(event) != _ALARM_ACK_EVENT_KEYS:
        raise RuntimeError("alarm ACK durable event schema is invalid")
    if type(receipt) is not dict or set(receipt) != _ALARM_ACK_COMMIT_KEYS:
        raise RuntimeError("alarm ACK durable receipt schema is invalid")
    acknowledged_at = event.get("acknowledged_at")
    identity = {
        "request_id": outbox.request_id,
        "request_fingerprint": outbox.request_fingerprint,
        "alarm_name": outbox.alarm_name,
        "activation_id": outbox.activation_id,
        "engine_instance_id": outbox.engine_instance_id,
        "source_activation_id": outbox.source_activation_id,
    }
    if (
        event.get("schema") != _ALARM_ACK_EVENT_SCHEMA
        or receipt.get("schema") != _ALARM_ACK_COMMIT_SCHEMA
        or any(type(value) is not str or not value for value in identity.values())
        or any(event.get(key) != value for key, value in identity.items())
        or any(receipt.get(key) != value for key, value in identity.items())
        or type(acknowledged_at) is not float
        or not math.isfinite(acknowledged_at)
        or acknowledged_at <= 0.0
        or receipt.get("acknowledged_at") != acknowledged_at
        or type(event.get("operator")) is not str
        or not event["operator"]
        or type(event.get("reason")) is not str
        or not event["reason"]
        or receipt.get("committed") is not True
    ):
        raise RuntimeError("alarm ACK durable identity is invalid")
    return dict(event), dict(receipt)


def _alarm_ack_published_result(outbox: AlarmAckOutboxRecord) -> dict[str, Any]:
    event, receipt = _validated_alarm_ack_outbox(outbox)
    if outbox.state != "published":
        raise RuntimeError("alarm ACK publication is not settled")
    return {
        "ok": True,
        "committed": True,
        "retry_safe": False,
        "publication_state": "published",
        "event_emitted": True,
        "alarm_name": event["alarm_name"],
        "activation_id": event["activation_id"],
        "engine_instance_id": event["engine_instance_id"],
        "source_activation_id": event["source_activation_id"],
        "request_id": event["request_id"],
        "commit_receipt": receipt,
    }


def _alarm_ack_publication_pending(outbox: AlarmAckOutboxRecord) -> dict[str, Any]:
    event, receipt = _validated_alarm_ack_outbox(outbox)
    if outbox.state != "committed":
        raise RuntimeError("alarm ACK pending result is not durably committed")
    return {
        "ok": False,
        "committed": True,
        "retry_safe": False,
        "publication_state": "pending",
        "event_emitted": False,
        "error_code": "alarm_ack_publication_pending",
        "error": "alarm acknowledgement is committed; publication settlement is pending",
        "alarm_name": event["alarm_name"],
        "activation_id": event["activation_id"],
        "engine_instance_id": event["engine_instance_id"],
        "source_activation_id": event["source_activation_id"],
        "request_id": event["request_id"],
        "commit_receipt": receipt,
    }


def _alarm_ack_aborted_result(outbox: AlarmAckOutboxRecord) -> dict[str, Any]:
    """Return a terminal non-commit result without exposing intent receipts."""

    event, _receipt = _validated_alarm_ack_outbox(outbox)
    terminal_code = outbox.terminal_code
    terminal_engine_instance_id = outbox.terminal_engine_instance_id
    if (
        outbox.state != "aborted"
        or type(terminal_code) is not str
        or terminal_code not in _ALARM_ACK_ABORT_TERMINAL_CODES
        or type(terminal_engine_instance_id) is not str
        or len(terminal_engine_instance_id) != 32
        or any(char not in "0123456789abcdef" for char in terminal_engine_instance_id)
        or (
            terminal_code == "activation_changed_before_ack_commit"
            and terminal_engine_instance_id != outbox.engine_instance_id
        )
        or (
            terminal_code == "engine_restart_before_ack_commit"
            and terminal_engine_instance_id == outbox.engine_instance_id
        )
    ):
        raise RuntimeError("alarm ACK terminal disposition is invalid")
    return {
        "ok": False,
        "committed": False,
        "retry_safe": False,
        "publication_state": "aborted",
        "event_emitted": False,
        "error_code": "alarm_ack_aborted",
        "error": "alarm acknowledgement was terminally aborted before durable commit",
        "alarm_name": event["alarm_name"],
        "activation_id": event["activation_id"],
        "engine_instance_id": event["engine_instance_id"],
        "source_activation_id": event["source_activation_id"],
        "request_id": event["request_id"],
        "request_fingerprint": event["request_fingerprint"],
        "terminal_code": terminal_code,
        "terminal_engine_instance_id": terminal_engine_instance_id,
    }


def _validate_alarm_ack_abort_disposition(
    disposition: AlarmAckOutboxAbortDisposition,
    *,
    expected_request_id: str | None = None,
    expected_fingerprint: str | None = None,
    expected_activation_id: str | None = None,
    expected_source_activation_id: str | None = None,
    expected_prior_engine_instance_id: str | None = None,
    expected_terminal_code: str,
    expected_recovery_engine_instance_id: str,
) -> None:
    request_id = getattr(disposition, "request_id", None)
    request_fingerprint = getattr(disposition, "request_fingerprint", None)
    prior_engine_instance_id = getattr(disposition, "prior_engine_instance_id", None)
    activation_id = getattr(disposition, "activation_id", None)
    source_activation_id = getattr(disposition, "source_activation_id", None)
    recovery_engine_instance_id = getattr(disposition, "recovery_engine_instance_id", None)
    if (
        type(disposition) is not AlarmAckOutboxAbortDisposition
        or disposition.schema != "alarm_ack_abort_disposition_v1"
        or disposition.state != "aborted"
        or type(request_id) is not str
        or len(request_id) != 32
        or any(char not in "0123456789abcdef" for char in request_id)
        or type(request_fingerprint) is not str
        or len(request_fingerprint) != 64
        or any(char not in "0123456789abcdef" for char in request_fingerprint)
        or type(prior_engine_instance_id) is not str
        or len(prior_engine_instance_id) != 32
        or any(char not in "0123456789abcdef" for char in prior_engine_instance_id)
        or type(activation_id) is not str
        or not activation_id
        or not activation_id.isprintable()
        or not is_canonical_source_activation_id(source_activation_id)
        or type(recovery_engine_instance_id) is not str
        or len(recovery_engine_instance_id) != 32
        or any(char not in "0123456789abcdef" for char in recovery_engine_instance_id)
        or disposition.terminal_code != expected_terminal_code
        or disposition.recovery_engine_instance_id != expected_recovery_engine_instance_id
        or (
            expected_terminal_code == "engine_restart_before_ack_commit"
            and disposition.recovery_engine_instance_id == disposition.prior_engine_instance_id
        )
        or (
            expected_terminal_code == "activation_changed_before_ack_commit"
            and disposition.recovery_engine_instance_id != disposition.prior_engine_instance_id
        )
        or type(disposition.disposed_at) is not float
        or not math.isfinite(disposition.disposed_at)
        or disposition.disposed_at <= 0.0
        or (expected_request_id is not None and disposition.request_id != expected_request_id)
        or (expected_fingerprint is not None and disposition.request_fingerprint != expected_fingerprint)
        or (expected_activation_id is not None and disposition.activation_id != expected_activation_id)
        or (
            expected_source_activation_id is not None
            and disposition.source_activation_id != expected_source_activation_id
        )
        or (
            expected_prior_engine_instance_id is not None
            and disposition.prior_engine_instance_id != expected_prior_engine_instance_id
        )
    ):
        raise RuntimeError("alarm ACK abort disposition is invalid")


async def _abort_prepared_alarm_ack(
    context: EngineCommandContext,
    outbox: AlarmAckOutboxRecord,
) -> dict[str, Any]:
    """Durably terminalize one known PREPARED loser and re-read authority."""

    event, receipt = _validated_alarm_ack_outbox(outbox)
    if outbox.state != "prepared":
        raise RuntimeError("alarm ACK abort requires a prepared intent")
    disposition = await context.writer.abort_alarm_ack_outbox(
        request_id=outbox.request_id,
        request_fingerprint=outbox.request_fingerprint,
        engine_instance_id=outbox.engine_instance_id,
        activation_id=outbox.activation_id,
        source_activation_id=outbox.source_activation_id,
        event=event,
        receipt=receipt,
    )
    _validate_alarm_ack_abort_disposition(
        disposition,
        expected_request_id=outbox.request_id,
        expected_fingerprint=outbox.request_fingerprint,
        expected_activation_id=outbox.activation_id,
        expected_source_activation_id=outbox.source_activation_id,
        expected_prior_engine_instance_id=outbox.engine_instance_id,
        expected_terminal_code="activation_changed_before_ack_commit",
        expected_recovery_engine_instance_id=outbox.engine_instance_id,
    )
    find_outbox = getattr(context.writer, "find_alarm_ack_outbox", None)
    if not callable(find_outbox):
        raise RuntimeError("alarm ACK durable lookup is unavailable")
    aborted = await find_outbox(
        request_id=outbox.request_id,
        request_fingerprint=outbox.request_fingerprint,
    )
    if (
        type(aborted) is not AlarmAckOutboxRecord
        or aborted.request_id != outbox.request_id
        or aborted.request_fingerprint != outbox.request_fingerprint
        or aborted.alarm_name != outbox.alarm_name
        or aborted.activation_id != outbox.activation_id
        or aborted.engine_instance_id != outbox.engine_instance_id
        or aborted.source_activation_id != outbox.source_activation_id
        or aborted.operator_name != outbox.operator_name
        or aborted.reason != outbox.reason
        or aborted.event != outbox.event
        or aborted.receipt != outbox.receipt
    ):
        raise RuntimeError("alarm ACK aborted authority changed immutable identity")
    return _alarm_ack_aborted_result(aborted)


async def _publish_committed_alarm_ack(
    writer: SQLiteWriter,
    broker: DataBroker,
    outbox: AlarmAckOutboxRecord,
) -> AlarmAckOutboxRecord:
    """Settle one exact ACK publication, then CAS its durable state."""

    event, receipt = _validated_alarm_ack_outbox(outbox)
    if outbox.state == "published":
        return outbox
    if outbox.state != "committed":
        raise RuntimeError("alarm ACK cannot publish before durable commit")
    publication_receipt = await broker.publish_required(
        Reading(
            timestamp=datetime.fromtimestamp(event["acknowledged_at"], UTC),
            instrument_id="alarm_v2",
            channel="alarm_v2/acknowledged",
            value=event["acknowledged_at"],
            unit="",
            # Transport is explicitly at-least-once. These stable identities
            # let every consumer collapse a late send plus an exact retry.
            metadata=event,
        ),
        request_id=outbox.request_id,
        request_fingerprint=outbox.request_fingerprint,
    )
    if not broker.validates_required_publication(
        publication_receipt,
        request_id=outbox.request_id,
        request_fingerprint=outbox.request_fingerprint,
    ):
        raise RuntimeError("alarm ACK required publisher receipt is invalid")
    published = await writer.publish_alarm_ack_outbox(
        request_id=outbox.request_id,
        request_fingerprint=outbox.request_fingerprint,
        event=event,
        receipt=receipt,
    )
    _validated_alarm_ack_outbox(published)
    if published.state != "published":
        raise RuntimeError("alarm ACK publication settlement is incomplete")
    return published


async def _reconcile_committed_alarm_ack_outbox(
    writer: SQLiteWriter,
    broker: DataBroker,
) -> None:
    """Replay every committed ACK before exposing command ingress."""

    for outbox in await writer.committed_alarm_ack_outbox():
        await _publish_committed_alarm_ack(writer, broker, outbox)


def _remember_alarm_ack_receipt(
    context: EngineCommandContext,
    request_id: str,
    fingerprint: str,
    result: dict[str, Any],
) -> None:
    """Retain only one exact terminal publication receipt under a hard cap."""

    if not (
        result.get("ok") is True
        and result.get("committed") is True
        and result.get("publication_state") == "published"
        and result.get("event_emitted") is True
    ):
        return
    context.alarm_ack_receipts[request_id] = (fingerprint, dict(result))
    while len(context.alarm_ack_receipts) > _MAX_OPERATOR_LOG_IDEMPOTENCY_RECEIPTS:
        context.alarm_ack_receipts.pop(next(iter(context.alarm_ack_receipts)))


async def _run_alarm_ack_publication_reconciliation(
    context: EngineCommandContext,
    outbox: AlarmAckOutboxRecord,
) -> dict[str, Any]:
    """Retry one durable COMMITTED ACK independently of its REP/GUI waiter."""

    _validated_alarm_ack_outbox(outbox)
    if outbox.state != "committed":
        raise RuntimeError("alarm ACK reconciliation requires a committed outbox")
    delay = _ALARM_ACK_RECONCILE_BACKOFF_BASE_S
    while context.experiment_commands_accepting:
        await asyncio.sleep(delay)
        if not context.experiment_commands_accepting:
            break
        try:
            retained = await context.writer.find_alarm_ack_outbox(
                request_id=outbox.request_id,
                request_fingerprint=outbox.request_fingerprint,
            )
            if (
                type(retained) is not AlarmAckOutboxRecord
                or retained.request_id != outbox.request_id
                or retained.request_fingerprint != outbox.request_fingerprint
                or retained.alarm_name != outbox.alarm_name
                or retained.activation_id != outbox.activation_id
                or retained.engine_instance_id != outbox.engine_instance_id
                or retained.source_activation_id != outbox.source_activation_id
                or retained.operator_name != outbox.operator_name
                or retained.reason != outbox.reason
                or retained.event != outbox.event
                or retained.receipt != outbox.receipt
            ):
                raise RuntimeError("alarm ACK reconciliation authority changed")
            _validated_alarm_ack_outbox(retained)
            if retained.state == "published":
                return _alarm_ack_published_result(retained)
            if retained.state != "committed":
                raise RuntimeError("alarm ACK reconciliation state is invalid")
            published = await _publish_committed_alarm_ack(
                context.writer,
                context.broker,
                retained,
            )
            return _alarm_ack_published_result(published)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - durable intent remains authoritative
            logger.warning(
                "Alarm ACK background publication retry failed: request=%s exception=%s",
                outbox.request_id,
                type(exc).__name__,
            )
            delay = min(delay * 2.0, _ALARM_ACK_RECONCILE_BACKOFF_MAX_S)
    return _alarm_ack_publication_pending(outbox)


def _owned_alarm_ack_reconciliation_done(
    context: EngineCommandContext,
    request_id: str,
    fingerprint: str,
    task: asyncio.Task[dict[str, Any]],
) -> None:
    current = context.alarm_ack_reconciliation_tasks.get(request_id)
    if current is not None and current[1] is task:
        del context.alarm_ack_reconciliation_tasks[request_id]
    if task.cancelled():
        return
    exception = task.exception()
    if exception is not None:
        logger.error(
            "Alarm ACK background reconciler failed: request=%s exception=%s",
            request_id,
            type(exception).__name__,
        )
        return
    _remember_alarm_ack_receipt(context, request_id, fingerprint, task.result())


def _ensure_alarm_ack_publication_reconciliation(
    context: EngineCommandContext,
    outbox: AlarmAckOutboxRecord,
) -> asyncio.Task[dict[str, Any]] | None:
    """Own one exact bounded same-process reconciler for a committed ACK."""

    _validated_alarm_ack_outbox(outbox)
    if outbox.state != "committed":
        raise RuntimeError("alarm ACK reconciliation requires a committed outbox")
    current = context.alarm_ack_reconciliation_tasks.get(outbox.request_id)
    if current is not None:
        if current[0] != outbox.request_fingerprint:
            raise RuntimeError("alarm ACK reconciliation identity conflict")
        return current[1]
    if not context.experiment_commands_accepting:
        return None
    task = asyncio.create_task(
        _run_alarm_ack_publication_reconciliation(context, outbox),
        name=f"alarm_ack_reconcile_{outbox.request_id[:8]}",
    )
    context.alarm_ack_reconciliation_tasks[outbox.request_id] = (outbox.request_fingerprint, task)
    task.add_done_callback(
        functools.partial(
            _owned_alarm_ack_reconciliation_done,
            context,
            outbox.request_id,
            outbox.request_fingerprint,
        )
    )
    return task


async def _settle_alarm_ack_outbox_startup(
    writer: SQLiteWriter,
    broker: DataBroker,
    engine_instance_id: str,
) -> tuple[AlarmAckOutboxAbortDisposition, ...]:
    """Abort every PREPARED intent, then replay COMMITTED before REP opens."""

    dispositions = await writer.abort_prepared_alarm_ack_outbox(
        recovery_engine_instance_id=engine_instance_id,
    )
    if type(dispositions) is not tuple:
        raise RuntimeError("alarm ACK startup disposition inventory is invalid")
    for disposition in dispositions:
        _validate_alarm_ack_abort_disposition(
            disposition,
            expected_terminal_code="engine_restart_before_ack_commit",
            expected_recovery_engine_instance_id=engine_instance_id,
        )
    await _reconcile_committed_alarm_ack_outbox(writer, broker)
    return dispositions


async def _claim_alarm_ack_activation(
    context: EngineCommandContext,
    *,
    engine_instance_id: str,
    activation_id: str,
) -> tuple[tuple[str, str], asyncio.Future[None]]:
    """Serialize durable commits for one exact alarm activation."""

    key = (engine_instance_id, activation_id)
    while True:
        predecessor = context.alarm_ack_activation_owners.get(key)
        if predecessor is None:
            capability = asyncio.get_running_loop().create_future()
            context.alarm_ack_activation_owners[key] = capability
            return key, capability
        await asyncio.shield(predecessor)


def _release_alarm_ack_activation(
    context: EngineCommandContext,
    key: tuple[str, str],
    capability: asyncio.Future[None],
) -> None:
    """Release only the exact activation-owner capability that was issued."""

    if context.alarm_ack_activation_owners.get(key) is not capability:
        raise RuntimeError("alarm ACK activation ownership changed")
    del context.alarm_ack_activation_owners[key]
    if capability.done():
        raise RuntimeError("alarm ACK activation capability was already settled")
    capability.set_result(None)


def _apply_committed_alarm_ack_state(
    context: EngineCommandContext,
    outbox: AlarmAckOutboxRecord,
) -> None:
    """Apply one COMMITTED ACK to the matching live activation, never earlier."""

    event, _receipt = _validated_alarm_ack_outbox(outbox)
    if outbox.state not in {"committed", "published"}:
        raise RuntimeError("alarm ACK live transition requires durable commit")
    registry_engine_instance_id = getattr(context.annunciation_registry, "engine_instance_id", None)
    context_engine_instance_id = context.engine_instance_id
    if is_canonical_engine_instance_id(context_engine_instance_id):
        live_engine_instance_id = context_engine_instance_id
        if (
            is_canonical_engine_instance_id(registry_engine_instance_id)
            and registry_engine_instance_id != live_engine_instance_id
        ):
            raise RuntimeError("alarm ACK live incarnation authorities disagree")
    elif is_canonical_engine_instance_id(registry_engine_instance_id):
        live_engine_instance_id = registry_engine_instance_id
    else:
        raise RuntimeError("alarm ACK live incarnation authority is unavailable")
    if outbox.engine_instance_id != live_engine_instance_id:
        return

    source_activation_id = int(outbox.source_activation_id)
    active = context.alarm_v2_state_mgr.get_active()
    current = active.get(outbox.alarm_name) if type(active) is dict else None
    if current is None or getattr(current, "activation_id", None) != source_activation_id:
        # A cleared/replaced activation must never transfer its durable ACK to
        # the current alarm incarnation.
        return
    if context.alarm_v2_state_mgr.acknowledgement_matches(
        outbox.alarm_name,
        operator=outbox.operator_name,
        reason=outbox.reason,
        request_id=outbox.request_id,
        expected_activation_id=source_activation_id,
        acknowledged_at=event["acknowledged_at"],
    ):
        return
    if getattr(current, "acknowledged", None) is not False:
        raise RuntimeError("alarm ACK durable authority conflicts with live acknowledgement")
    ack_event = context.alarm_v2_state_mgr.acknowledge(
        outbox.alarm_name,
        operator=outbox.operator_name,
        reason=outbox.reason,
        expected_activation_id=source_activation_id,
        acknowledged_at=event["acknowledged_at"],
        request_id=outbox.request_id,
    )
    if ack_event != {
        "alarm_id": outbox.alarm_name,
        "acknowledged_at": event["acknowledged_at"],
        "operator": outbox.operator_name,
        "reason": outbox.reason,
        "request_id": outbox.request_id,
    }:
        raise RuntimeError("alarm ACK committed live transition is not exact")


async def _execute_owned_alarm_ack(
    cmd: dict[str, Any],
    context: EngineCommandContext,
    request_id: str,
    fingerprint: str,
) -> dict[str, Any]:
    alarm_name = cmd["alarm_name"]
    activation_id = cmd["activation_id"]
    engine_instance_id = cmd["engine_instance_id"]
    operator = cmd["operator"]
    reason = cmd["reason"]
    target = None

    try:
        find_outbox = getattr(context.writer, "find_alarm_ack_outbox", None)
        if not callable(find_outbox):
            raise RuntimeError("alarm ACK durable lookup is unavailable")
        outbox = await find_outbox(
            request_id=request_id,
            request_fingerprint=fingerprint,
        )
        if outbox is None:
            if context.annunciation_registry is None:
                return {
                    "ok": False,
                    "error_code": "alarm_activation_unavailable",
                    "error": "alarm activation authority is unavailable",
                    "retry_safe": True,
                    "request_id": request_id,
                }
            try:
                context.annunciation_registry.sync(
                    context.alarm_v2_state_mgr.get_active(),
                    context.safety_manager.get_status(),
                )
            except AnnunciationProjectionUnavailable:
                return {
                    "ok": False,
                    "error_code": "alarm_activation_unavailable",
                    "error": "alarm activation authority is unavailable",
                    "retry_safe": True,
                    "request_id": request_id,
                }
            target = context.annunciation_registry.resolve(engine_instance_id, activation_id)
            if target is None or target.source != "alarm_v2" or target.source_key != alarm_name:
                return {
                    "ok": False,
                    "error_code": "stale_or_unknown_activation",
                    "error": "alarm activation is stale or unknown",
                    "retry_safe": False,
                    "request_id": request_id,
                }
            source_activation_id = str(target.source_activation_id)
            acknowledged_at = time.time()
            if type(acknowledged_at) is not float or not math.isfinite(acknowledged_at) or acknowledged_at <= 0.0:
                raise RuntimeError("alarm ACK clock authority is invalid")
            event = {
                "schema": _ALARM_ACK_EVENT_SCHEMA,
                "request_id": request_id,
                "request_fingerprint": fingerprint,
                "alarm_name": alarm_name,
                "activation_id": activation_id,
                "engine_instance_id": engine_instance_id,
                "source_activation_id": source_activation_id,
                "acknowledged_at": acknowledged_at,
                "operator": operator,
                "reason": reason,
            }
            receipt = {
                "schema": _ALARM_ACK_COMMIT_SCHEMA,
                "request_id": request_id,
                "request_fingerprint": fingerprint,
                "alarm_name": alarm_name,
                "activation_id": activation_id,
                "engine_instance_id": engine_instance_id,
                "source_activation_id": source_activation_id,
                "acknowledged_at": acknowledged_at,
                "committed": True,
            }
            outbox = await context.writer.prepare_alarm_ack_outbox(
                request_id=request_id,
                request_fingerprint=fingerprint,
                alarm_name=alarm_name,
                activation_id=activation_id,
                engine_instance_id=engine_instance_id,
                source_activation_id=source_activation_id,
                operator_name=operator,
                reason=reason,
                event=event,
                receipt=receipt,
            )
    except OperatorLogIdempotencyConflictError:
        return {
            "ok": False,
            "error_code": "idempotency_key_conflict",
            "error": "request_id was already committed with different content",
            "retry_safe": False,
            "request_id": request_id,
        }
    except Exception as exc:
        logger.error(
            "Alarm ACK outbox intent failed: request=%s exception=%s",
            request_id,
            type(exc).__name__,
        )
        return {
            "ok": False,
            "error_code": "alarm_ack_persistence_failed",
            "error": "alarm acknowledgement persistence failed",
            "retry_safe": True,
            "request_id": request_id,
        }

    event, receipt = _validated_alarm_ack_outbox(outbox)
    if (
        outbox.request_id != request_id
        or outbox.request_fingerprint != fingerprint
        or outbox.alarm_name != alarm_name
        or outbox.activation_id != activation_id
        or outbox.engine_instance_id != engine_instance_id
        or outbox.operator_name != operator
        or outbox.reason != reason
    ):
        return {
            "ok": False,
            "error_code": "idempotency_key_conflict",
            "error": "request_id was already retained with different content",
            "retry_safe": False,
            "request_id": request_id,
        }
    if outbox.state == "aborted":
        return _alarm_ack_aborted_result(outbox)
    if outbox.state == "published":
        _apply_committed_alarm_ack_state(context, outbox)
        return _alarm_ack_published_result(outbox)

    if outbox.state == "prepared":
        owner_key, owner_capability = await _claim_alarm_ack_activation(
            context,
            engine_instance_id=engine_instance_id,
            activation_id=activation_id,
        )
        try:
            if context.annunciation_registry is None:
                return {
                    "ok": False,
                    "error_code": "alarm_activation_unavailable",
                    "error": "alarm activation authority is unavailable",
                    "retry_safe": True,
                    "request_id": request_id,
                }
            try:
                context.annunciation_registry.sync(
                    context.alarm_v2_state_mgr.get_active(),
                    context.safety_manager.get_status(),
                )
            except AnnunciationProjectionUnavailable:
                return {
                    "ok": False,
                    "error_code": "alarm_activation_unavailable",
                    "error": "alarm activation authority is unavailable",
                    "retry_safe": True,
                    "request_id": request_id,
                }
            target = context.annunciation_registry.resolve(engine_instance_id, activation_id)
            if (
                target is None
                or target.source != "alarm_v2"
                or target.source_key != alarm_name
                or str(target.source_activation_id) != outbox.source_activation_id
                or target.acknowledged is not False
            ):
                try:
                    return await _abort_prepared_alarm_ack(context, outbox)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(
                        "Alarm ACK stale intent disposition failed: request=%s exception=%s",
                        request_id,
                        type(exc).__name__,
                    )
                    return {
                        "ok": False,
                        "error_code": "alarm_ack_persistence_failed",
                        "error": "alarm acknowledgement persistence failed",
                        "retry_safe": True,
                        "request_id": request_id,
                    }
            # Persistence is the authority boundary. No AlarmStateManager or
            # annunciation-visible acknowledgement exists before this await
            # returns one exact COMMITTED record.
            outbox = await context.writer.commit_alarm_ack_outbox(
                request_id=request_id,
                request_fingerprint=fingerprint,
                event=event,
                receipt=receipt,
            )
            _validated_alarm_ack_outbox(outbox)
            if outbox.state not in {"committed", "published"}:
                raise RuntimeError("alarm ACK durable commit state is invalid")
            _apply_committed_alarm_ack_state(context, outbox)
        finally:
            _release_alarm_ack_activation(context, owner_key, owner_capability)
    if outbox.state != "committed":
        raise RuntimeError("alarm ACK outbox state is invalid")
    _apply_committed_alarm_ack_state(context, outbox)
    if context.annunciation_registry is not None:
        try:
            context.annunciation_registry.sync(
                context.alarm_v2_state_mgr.get_active(),
                context.safety_manager.get_status(),
            )
        except AnnunciationProjectionUnavailable:
            logger.error("Alarm acknowledgement projection refresh failed")
    try:
        published = await _publish_committed_alarm_ack(
            context.writer,
            context.broker,
            outbox,
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - exact committed intent remains retryable
        logger.error(
            "Alarm ACK publication remains pending: request=%s exception=%s",
            request_id,
            type(exc).__name__,
        )
        _ensure_alarm_ack_publication_reconciliation(context, outbox)
        return _alarm_ack_publication_pending(outbox)
    return _alarm_ack_published_result(published)


def _owned_alarm_ack_done(
    context: EngineCommandContext,
    request_id: str,
    fingerprint: str,
    task: asyncio.Task[dict[str, Any]],
) -> None:
    current = context.alarm_ack_tasks.get(request_id)
    if current is not None and current[1] is task:
        del context.alarm_ack_tasks[request_id]
    if task.cancelled() or task.exception() is not None:
        return
    _remember_alarm_ack_receipt(context, request_id, fingerprint, task.result())


async def _submit_alarm_ack(cmd: dict[str, Any], context: EngineCommandContext) -> dict[str, Any]:
    request_id = cmd.get("request_id")
    if (
        type(request_id) is not str
        or len(request_id) != 32
        or any(char not in "0123456789abcdef" for char in request_id)
    ):
        return {
            "ok": False,
            "error_code": "alarm_ack_request_id_invalid",
            "error": "request_id must be exactly 32 lowercase hexadecimal characters",
            "retry_safe": True,
        }
    if any(type(cmd.get(field)) is not str or cmd[field] != cmd[field].strip() for field in ("operator", "reason")):
        return {
            "ok": False,
            "error_code": "invalid_alarm_ack_command",
            "error": "alarm acknowledgement attribution must be canonical",
            "retry_safe": True,
        }
    try:
        fingerprint = alarm_ack_request_fingerprint(cmd)
    except ValueError:
        return {
            "ok": False,
            "error_code": "invalid_alarm_ack_command",
            "error": "alarm acknowledgement command is invalid",
            "retry_safe": True,
        }
    completed = context.alarm_ack_receipts.get(request_id)
    if completed is not None:
        if completed[0] != fingerprint:
            return {"ok": False, "error_code": "idempotency_key_conflict", "retry_safe": False}
        return dict(completed[1])
    pending = context.alarm_ack_tasks.get(request_id)
    if pending is not None:
        if pending[0] != fingerprint:
            return {"ok": False, "error_code": "idempotency_key_conflict", "retry_safe": False}
        return await asyncio.shield(pending[1])
    reconciliation = context.alarm_ack_reconciliation_tasks.get(request_id)
    if reconciliation is not None:
        if reconciliation[0] != fingerprint:
            return {"ok": False, "error_code": "idempotency_key_conflict", "retry_safe": False}
        return await asyncio.shield(reconciliation[1])
    if not context.experiment_commands_accepting:
        return {
            "ok": False,
            "error_code": "engine_shutting_down",
            "error": "alarm acknowledgement submissions are frozen for shutdown",
            "retry_safe": True,
            "request_id": request_id,
        }
    active_request_ids = set(context.alarm_ack_tasks) | set(context.alarm_ack_reconciliation_tasks)
    if len(active_request_ids) >= _MAX_PENDING_ALARM_ACK_ENTRIES:
        return {
            "ok": False,
            "error_code": "alarm_ack_busy",
            "error": "the bounded alarm acknowledgement lane is full",
            "retry_safe": True,
            "request_id": request_id,
        }
    task = asyncio.create_task(
        _execute_owned_alarm_ack(cmd, context, request_id, fingerprint),
        name=f"alarm_ack_{request_id[:8]}",
    )
    context.alarm_ack_tasks[request_id] = (fingerprint, task)
    task.add_done_callback(functools.partial(_owned_alarm_ack_done, context, request_id, fingerprint))
    return await asyncio.shield(task)


def _feed_recording_experiment_lifecycle(
    context: EngineCommandContext,
    action: str,
    result: dict[str, Any],
) -> str | None:
    """Reflect an already-committed experiment result into the dark feed."""

    feed = context.recording_lifecycle_feed
    if feed is None:
        return None
    try:
        snapshot = context.experiment_manager.snapshot_operator_experiment()
        if action in {"experiment_finalize", "experiment_stop", "experiment_abort"}:
            experiment_id = result.get("experiment", {}).get("experiment_id")
            if type(experiment_id) is not str or not experiment_id or snapshot.experiment_id is not None:
                raise ValueError("terminal experiment result does not match inactive manager truth")
            if action == "experiment_abort":
                feed.experiment_aborted(snapshot.revision, experiment_id)
            else:
                feed.experiment_finalized(snapshot.revision, experiment_id)
            return None

        result_experiment = result.get("experiment") or result.get("active_experiment")
        result_id = (
            snapshot.experiment_id
            if action == "experiment_advance_phase"
            else (result_experiment or {}).get("experiment_id")
        )
        if (
            type(result_id) is not str
            or result_id != snapshot.experiment_id
            or type(snapshot.experiment_name) is not str
        ):
            raise ValueError("active experiment result does not match manager truth")
        feed.experiment_active(
            snapshot.revision,
            result_id,
            snapshot.experiment_name,
            snapshot.phase,
        )
    except Exception as exc:  # noqa: BLE001 - observational bridge is fail-dark
        logger.warning(
            "Recording lifecycle feed unavailable: action=%s exception=%s",
            _bounded_action_label(action),
            type(exc).__name__,
        )
        return "recording_lifecycle_feed"
    return None


def _seed_recording_lifecycle(
    feed: RecordingLifecycleFeed,
    experiment_manager: ExperimentManager,
) -> None:
    snapshot = experiment_manager.snapshot_operator_experiment()
    if snapshot.experiment_id is None:
        feed.experiment_inactive(snapshot.revision)
    elif type(snapshot.experiment_name) is str:
        feed.experiment_active(
            snapshot.revision,
            snapshot.experiment_id,
            snapshot.experiment_name,
            snapshot.phase,
        )
    else:
        raise ValueError("active experiment snapshot has no exact name")


async def _start_scheduler_with_recording_feed(
    scheduler: Scheduler,
    feed: RecordingLifecycleFeed,
    sequence: int,
) -> int:
    epoch_id = secrets.token_hex(16)
    try:
        feed.persistence_started(epoch_id)
    except Exception as exc:  # noqa: BLE001 - observational bridge is fail-dark
        logger.warning(
            "Recording persistence feed unavailable: phase=before_scheduler_start exception=%s",
            type(exc).__name__,
        )
        try:
            feed.persistence_ambiguous()
        except Exception as terminal_exc:  # noqa: BLE001 - observational bridge is fail-dark
            logger.warning(
                "Recording persistence feed terminalization failed: exception=%s",
                type(terminal_exc).__name__,
            )
    try:
        await scheduler.start()
    except BaseException:
        try:
            feed.persistence_ambiguous()
        except Exception as exc:  # noqa: BLE001 - preserve the scheduler failure
            logger.warning(
                "Recording persistence feed unavailable: phase=scheduler_start_failure exception=%s",
                type(exc).__name__,
            )
        sequence += 1
        try:
            feed.acquisition_unavailable(sequence)
        except Exception as exc:  # noqa: BLE001 - preserve the scheduler failure
            logger.warning(
                "Recording acquisition feed unavailable: phase=scheduler_start_failure exception=%s",
                type(exc).__name__,
            )
        raise
    sequence += 1
    try:
        feed.acquisition_running(sequence, epoch_id)
    except Exception as exc:  # noqa: BLE001 - observational bridge is fail-dark
        logger.warning(
            "Recording acquisition feed unavailable: phase=after_scheduler_start exception=%s",
            type(exc).__name__,
        )
    return sequence


async def _stop_scheduler_with_recording_feed(
    scheduler: Scheduler,
    feed: RecordingLifecycleFeed,
    sequence: int,
    *,
    retry_delay_s: float = 0.1,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> int:
    requested_delay = float(retry_delay_s)
    bounded_retry_delay_s = min(max(0.0, requested_delay), 1.0) if math.isfinite(requested_delay) else 0.1
    while True:
        try:
            await scheduler.stop()
            break
        except ReviewedSourceSettlementIncomplete as exc:
            try:
                feed.persistence_ambiguous()
            except Exception as feed_exc:  # noqa: BLE001 - settlement retry must continue
                logger.warning(
                    "Recording persistence feed unavailable: phase=reviewed_source_settlement exception=%s",
                    type(feed_exc).__name__,
                )
            sequence += 1
            try:
                feed.acquisition_unavailable(sequence)
            except Exception as feed_exc:  # noqa: BLE001 - settlement retry must continue
                logger.warning(
                    "Recording acquisition feed unavailable: phase=reviewed_source_settlement exception=%s",
                    type(feed_exc).__name__,
                )
            logger.critical(
                "Scheduler stop retains reviewed-source authority: retry_s=%.3f exception=%s",
                bounded_retry_delay_s,
                type(exc).__name__,
            )
            await sleep(bounded_retry_delay_s)
        except BaseException:
            try:
                feed.persistence_ambiguous()
            except Exception as exc:  # noqa: BLE001 - preserve the scheduler failure
                logger.warning(
                    "Recording persistence feed unavailable: phase=scheduler_stop_failure exception=%s",
                    type(exc).__name__,
                )
            sequence += 1
            try:
                feed.acquisition_unavailable(sequence)
            except Exception as exc:  # noqa: BLE001 - preserve the scheduler failure
                logger.warning(
                    "Recording acquisition feed unavailable: phase=scheduler_stop_failure exception=%s",
                    type(exc).__name__,
                )
            raise
    sequence += 1
    try:
        feed.acquisition_stopped(sequence)
    except Exception as exc:  # noqa: BLE001 - observational bridge is fail-dark
        logger.warning(
            "Recording acquisition feed unavailable: phase=after_scheduler_stop exception=%s",
            type(exc).__name__,
        )
        sequence += 1
        try:
            feed.acquisition_unavailable(sequence)
        except Exception as terminal_exc:  # noqa: BLE001 - observational bridge is fail-dark
            logger.warning(
                "Recording acquisition feed terminalization failed: exception=%s",
                type(terminal_exc).__name__,
            )
    try:
        feed.persistence_stopped()
    except Exception as exc:  # noqa: BLE001 - observational bridge is fail-dark
        logger.warning(
            "Recording persistence feed unavailable: phase=after_scheduler_stop exception=%s",
            type(exc).__name__,
        )
        try:
            feed.persistence_ambiguous()
        except Exception as terminal_exc:  # noqa: BLE001 - observational bridge is fail-dark
            logger.warning(
                "Recording persistence feed terminalization failed: exception=%s",
                type(terminal_exc).__name__,
            )
    return sequence


def _periodic_query_failure(error_code: str) -> dict[str, Any]:
    return encode_periodic_command_reply(
        {
            "ok": False,
            "schema": PERIODIC_QUERY_SCHEMA,
            "error_code": error_code,
        }
    )


def _periodic_barrier_failure(error_code: str) -> dict[str, Any]:
    return encode_periodic_command_reply(
        {
            "ok": False,
            "schema": PERIODIC_BARRIER_SCHEMA,
            "error_code": error_code,
        }
    )


def _periodic_snapshot_response(context: EngineCommandContext) -> dict[str, Any]:
    try:
        snapshot = context.alarm_v2_state_mgr.snapshot_active_canonical()
        response = {
            "ok": True,
            "schema": PERIODIC_QUERY_SCHEMA,
            "state_revision": snapshot.state_revision,
            "state_token": snapshot.state_token,
            "active": snapshot.active,
        }
        encoded = encode_periodic_command_reply(response)
        if len(encoded.wire) > 60 * 1024:
            return _periodic_query_failure("snapshot_unavailable")
        return encoded
    except Exception:
        return _periodic_query_failure("snapshot_unavailable")


async def _execute_owned_experiment_read(
    action: str,
    cmd: dict[str, Any],
    context: EngineCommandContext,
) -> dict[str, Any]:
    """Run one retained read after earlier lifecycle mutations settle."""

    async with context.experiment_command_lock:
        return await asyncio.to_thread(
            _run_experiment_command,
            action,
            cmd,
            context.experiment_manager,
        )


def _owned_experiment_read_done(
    context: EngineCommandContext,
    action: str,
    task: asyncio.Task[dict[str, Any]],
) -> None:
    context.experiment_read_tasks.discard(task)
    action_label = _bounded_action_label(action)
    if task.cancelled():
        logger.critical("Experiment read owner was cancelled: action=%s", action_label)
        return
    exception = task.exception()
    if exception is not None:
        logger.error(
            "Experiment read owner failed after submission: action=%s exception=%s",
            action_label,
            type(exception).__name__,
        )


def _owned_experiment_status_done(
    context: EngineCommandContext,
    task: asyncio.Task[dict[str, Any]],
) -> None:
    if context.experiment_status_task is task:
        context.experiment_status_task = None
    if task.cancelled():
        logger.critical("Experiment status owner was cancelled")
        return
    exception = task.exception()
    if exception is not None:
        logger.error(
            "Experiment status owner failed after submission: exception=%s",
            type(exception).__name__,
        )


async def _drain_experiment_command_tasks(
    context: EngineCommandContext,
    logger_: logging.Logger,
    timeout: float = 30.0,  # noqa: ASYNC109 - internal shutdown gate
) -> bool:
    """Freeze submissions and settle experiment owners before teardown.

    The monotonic timeout is an escalation boundary, never a cancellation
    boundary. If it expires, shutdown is held fail-closed until the retained
    owners settle so a worker cannot commit after its reconciliation resources
    have been dismantled. ``False`` means the visible deadline was exceeded.
    """

    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError("timeout must be numeric")
    timeout_s = float(timeout)
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("timeout must be positive and finite")
    context.experiment_commands_accepting = False
    pending = set(context.experiment_command_tasks)
    pending.update(context.experiment_read_tasks)
    pending.update(task for _fingerprint, task in context.operator_log_tasks.values())
    pending.update(task for _fingerprint, task in getattr(context, "operator_log_reconciliation_tasks", {}).values())
    pending.update(task for _fingerprint, task in context.alarm_ack_tasks.values())
    pending.update(task for _fingerprint, task in getattr(context, "alarm_ack_reconciliation_tasks", {}).values())
    if context.experiment_status_task is not None:
        pending.add(context.experiment_status_task)
    pending = {task for task in pending if not task.done()}
    if not pending:
        return True

    logger_.info("Draining %d retained experiment command task(s) before shutdown", len(pending))
    drain = asyncio.gather(*pending, return_exceptions=True)

    async def settle() -> bool:
        try:
            await asyncio.wait_for(asyncio.shield(drain), timeout=timeout_s)
            return True
        except TimeoutError:
            logger_.critical(
                "Experiment command drain exceeded %.3fs; shutdown remains blocked until authority settles",
                timeout_s,
            )
            await drain
            return False

    settlement = asyncio.create_task(settle(), name="engine-retained-command-settlement")
    cancellation_seen = False
    while not settlement.done():
        try:
            await asyncio.shield(settlement)
        except asyncio.CancelledError:
            cancellation_seen = True
    completed_within_deadline = settlement.result()
    if cancellation_seen:
        raise asyncio.CancelledError
    return completed_within_deadline


def _note_experiment_reconciliation_failure(
    failures: list[str],
    step: str,
    exc: BaseException,
) -> None:
    failures.append(step)
    logger.error(
        "Committed experiment command reconciliation failed; step=%s exception=%s",
        step,
        type(exc).__name__,
    )


def _attempt_experiment_reconciliation_sync(
    failures: list[str],
    step: str,
    operation: Callable[[], Any],
) -> Any | None:
    try:
        return operation()
    except Exception as exc:  # noqa: BLE001 - classify committed partial outcome
        _note_experiment_reconciliation_failure(failures, step, exc)
        return None


async def _attempt_experiment_reconciliation_async(
    failures: list[str],
    step: str,
    operation: Callable[[], Awaitable[Any]],
) -> Any | None:
    try:
        return await operation()
    except Exception as exc:  # noqa: BLE001 - classify committed partial outcome
        _note_experiment_reconciliation_failure(failures, step, exc)
        return None


def _experiment_commit_receipt(
    action: str,
    cmd: dict[str, Any],
    result: dict[str, Any],
    manager: ExperimentManager,
) -> dict[str, Any]:
    experiment = result.get("experiment") or result.get("active_experiment") or {}
    experiment_id = result.get("experiment_id") or experiment.get("experiment_id") or cmd.get("experiment_id")
    snapshot = manager.snapshot_operator_experiment()
    return {
        "schema": "experiment_command_commit_v1",
        "action": action,
        "experiment_id": experiment_id if type(experiment_id) is str else None,
        "manager_revision": snapshot.revision,
        "committed": True,
    }


async def _execute_owned_experiment_command(
    action: str,
    cmd: dict[str, Any],
    context: EngineCommandContext,
) -> dict[str, Any]:
    """Own a lifecycle command through commit and every completion side effect.

    The task running this function is retained by ``EngineCommandContext`` and
    shielded from a timed-out/cancelled reply waiter. A timeout therefore means
    outcome unknown to the caller, while the single serialized owner still
    completes reconciliation and side effects exactly once.
    """

    async with context.experiment_command_lock:
        experiment_manager = context.experiment_manager
        experiment_call = asyncio.to_thread(
            _run_experiment_command,
            action,
            cmd,
            experiment_manager,
        )
        result = await experiment_call

        if not result.get("ok"):
            return result
        reconciliation_failures: list[str] = []
        try:
            receipt = _experiment_commit_receipt(action, cmd, result, experiment_manager)
        except Exception as exc:  # noqa: BLE001 - state is already committed
            _note_experiment_reconciliation_failure(
                reconciliation_failures,
                "commit_receipt_generation",
                exc,
            )
            experiment = result.get("experiment") or result.get("active_experiment") or {}
            experiment_id = result.get("experiment_id") or experiment.get("experiment_id") or cmd.get("experiment_id")
            receipt = {
                "schema": "experiment_command_commit_v1",
                "action": action,
                "experiment_id": experiment_id if type(experiment_id) is str else None,
                "manager_revision": None,
                "committed": True,
            }

        if action in {
            "experiment_start",
            "experiment_create",
            "experiment_update",
            "experiment_finalize",
            "experiment_stop",
            "experiment_abort",
            "experiment_advance_phase",
        }:
            feed_failure = _feed_recording_experiment_lifecycle(context, action, result)
            if feed_failure is not None:
                reconciliation_failures.append(feed_failure)

        if action in {"experiment_start", "experiment_create"}:
            await _attempt_experiment_reconciliation_async(
                reconciliation_failures,
                "calibration_acquisition_activate",
                lambda: asyncio.to_thread(
                    _try_activate_calibration_acquisition,
                    context.calibration_acquisition,
                    experiment_manager,
                    cmd,
                ),
            )
            name = cmd.get("name") or cmd.get("title") or "?"
            await _attempt_experiment_reconciliation_async(
                reconciliation_failures,
                "event_log_experiment_start",
                lambda: context.event_logger.log_event("experiment", f"Эксперимент начат: {name}"),
            )
            await _attempt_experiment_reconciliation_async(
                reconciliation_failures,
                "event_bus_experiment_start",
                lambda: context.event_bus.publish(
                    EngineEvent(
                        event_type="experiment_start",
                        timestamp=datetime.now(UTC),
                        payload={"name": name, "experiment_id": result.get("experiment_id")},
                        experiment_id=result.get("experiment_id"),
                    )
                ),
            )
        elif action in {
            "experiment_finalize",
            "experiment_stop",
            "experiment_abort",
        }:
            _attempt_experiment_reconciliation_sync(
                reconciliation_failures,
                "calibration_acquisition_deactivate",
                context.calibration_acquisition.deactivate,
            )
            if action == "experiment_abort":
                message = "⚠ Эксперимент прерван"
            else:
                message = "Эксперимент завершён"
            await _attempt_experiment_reconciliation_async(
                reconciliation_failures,
                "event_log_experiment_terminal",
                lambda: context.event_logger.log_event("experiment", message),
            )
            exp_info = result.get("experiment", {})
            await _attempt_experiment_reconciliation_async(
                reconciliation_failures,
                "event_bus_experiment_terminal",
                lambda: context.event_bus.publish(
                    EngineEvent(
                        event_type=action,
                        timestamp=datetime.now(UTC),
                        payload={"action": action, "experiment": exp_info},
                        experiment_id=exp_info.get("experiment_id"),
                    )
                ),
            )
            if context.cooldown_alarm is not None:
                _attempt_experiment_reconciliation_sync(
                    reconciliation_failures,
                    "cooldown_alarm_experiment_finalized",
                    context.cooldown_alarm.notify_experiment_finalized,
                )

            if context.sink_registry.sinks:

                async def dispatch_export() -> None:
                    experiment_id = exp_info.get("experiment_id") or ""
                    metadata: dict = {}
                    if experiment_id:
                        metadata_path = experiment_manager.data_dir / "experiments" / experiment_id / "metadata.json"
                        metadata = await asyncio.to_thread(_load_experiment_metadata_sync, metadata_path)
                    export = _build_experiment_export(exp_info, metadata)
                    task = asyncio.create_task(
                        context.sink_registry.dispatch(export),
                        name=f"sinks_dispatch_{(experiment_id or 'noid')[:8]}",
                    )
                    context.alarm_dispatch_tasks.add(task)
                    task.add_done_callback(context.alarm_dispatch_tasks.discard)

                await _attempt_experiment_reconciliation_async(
                    reconciliation_failures,
                    "sink_dispatch_setup",
                    dispatch_export,
                )
        elif action == "experiment_advance_phase":
            phase = cmd.get("phase", "?")
            await _attempt_experiment_reconciliation_async(
                reconciliation_failures,
                "event_log_phase_transition",
                lambda: context.event_logger.log_event("phase", f"Фаза: → {phase}"),
            )
            active = experiment_manager.active_experiment
            await _attempt_experiment_reconciliation_async(
                reconciliation_failures,
                "event_bus_phase_transition",
                lambda: context.event_bus.publish(
                    EngineEvent(
                        event_type="phase_transition",
                        timestamp=datetime.now(UTC),
                        payload={"phase": phase, "entry": result.get("phase", {})},
                        experiment_id=active.experiment_id if active else None,
                    )
                ),
            )
            cooldown_alarm = context.cooldown_alarm
            if cooldown_alarm is not None:
                _attempt_experiment_reconciliation_sync(
                    reconciliation_failures,
                    "cooldown_alarm_phase_change",
                    lambda: cooldown_alarm.notify_phase_change(phase),
                )
            if phase == "cooldown" and cooldown_alarm is not None and cooldown_alarm.is_auto_arm_enabled:
                armed = _attempt_experiment_reconciliation_sync(
                    reconciliation_failures,
                    "cooldown_alarm_arm",
                    cooldown_alarm.arm,
                )
                if armed is not None:
                    if not armed and cooldown_alarm.cold_start_skipped:
                        logger.info("CooldownAlarm: auto-arm skipped — cold-start detected")
                    else:
                        logger.info(
                            "CooldownAlarm: auto-arm на phase=cooldown → %s",
                            "ARMED" if armed else "FAILED (no model)",
                        )

        result = dict(result)
        result["committed"] = True
        result["commit_receipt"] = receipt
        result["retry_safe"] = False
        if reconciliation_failures:
            result.update(
                {
                    "ok": False,
                    "committed": True,
                    "error_code": "committed_reconciliation_failed",
                    "error": "experiment state committed, but one or more completion steps failed",
                    "reconciliation_failures": tuple(reconciliation_failures),
                }
            )
        return result


def _owned_experiment_task_done(
    context: EngineCommandContext,
    action: str,
    task: asyncio.Task[dict[str, Any]],
) -> None:
    context.experiment_command_tasks.discard(task)
    action_label = _bounded_action_label(action)
    if task.cancelled():
        logger.critical("Experiment command owner was cancelled: action=%s", action_label)
        return
    exception = task.exception()
    if exception is not None:
        logger.error(
            "Experiment command owner failed after submission: action=%s exception=%s",
            action_label,
            type(exception).__name__,
        )


def _request_teardown_after_shutdown_receipt(
    context: EngineCommandContext,
    cmd: dict[str, Any],
    reply: dict[str, Any],
) -> None:
    """Release engine teardown only after the exact receipt reached REP."""

    receipt = context.shutdown_receipt
    expected_wire_receipt = None if receipt is None else {**receipt, "proto": PROTOCOL_VERSION}
    if (
        cmd.get("cmd") == "launcher_shutdown"
        and receipt is not None
        and reply == expected_wire_receipt
        and reply.get("engine_instance_id") == context.engine_instance_id
        and parse_global_off_evidence(reply.get("off_evidence")) is not None
        and parse_global_off_evidence(reply.get("off_evidence")).verified_off
        and reply.get("teardown_requested") is True
        and context.shutdown_event is not None
    ):
        context.shutdown_event.set()


def _shutdown_command_identity(cmd: dict[str, Any]) -> tuple[str, str, str] | None:
    required = {"cmd", "engine_instance_id", "request_id", "shutdown_capability"}
    instance_id = cmd.get("engine_instance_id")
    request_id = cmd.get("request_id")
    capability = cmd.get("shutdown_capability")
    if not (
        set(cmd) == required
        and cmd.get("cmd") == "launcher_shutdown"
        and type(instance_id) is str
        and len(instance_id) == 32
        and all(ch in "0123456789abcdef" for ch in instance_id)
        and type(request_id) is str
        and len(request_id) == 32
        and all(ch in "0123456789abcdef" for ch in request_id)
        and type(capability) is str
        and len(capability) == 64
        and all(ch in "0123456789abcdef" for ch in capability)
    ):
        return None
    return instance_id, request_id, capability


def _shutdown_latch_failure(
    cmd: dict[str, Any],
    context: EngineCommandContext,
) -> dict[str, Any] | None:
    """Reject every post-latch state change except exact safety reconciliation."""

    request_id = context.shutdown_request_id
    if request_id is None:
        return None
    action = cmd.get("cmd")
    if not _is_mutating_command(action):
        return None
    if action == "keithley_emergency_off" and set(cmd) == {"cmd"}:
        return None
    if action == "launcher_shutdown":
        identity = _shutdown_command_identity(cmd)
        if (
            identity is not None
            and identity[1] == request_id
            and secrets.compare_digest(identity[0], context.engine_instance_id)
            and secrets.compare_digest(identity[2], context.shutdown_capability)
        ):
            return None
        if (
            identity is not None
            and secrets.compare_digest(identity[0], context.engine_instance_id)
            and secrets.compare_digest(identity[2], context.shutdown_capability)
        ):
            return {
                "ok": False,
                "error_code": "launcher_shutdown_already_requested",
                "error": "a different shutdown request already owns this engine incarnation",
                "delivery_state": "dispatched",
                "commit_state": "not_committed",
                "retry_safe": False,
            }
    return {
        "ok": False,
        "error_code": "engine_shutdown_latched",
        "error": "engine shutdown owns mutation admission; later state changes are refused",
        "delivery_state": "dispatched",
        "commit_state": "not_committed",
        "retry_safe": False,
    }


async def _handle_gui_command(
    cmd: dict[str, Any],
    *,
    context: EngineCommandContext,
) -> dict[str, Any]:
    safety_manager = context.safety_manager
    event_logger = context.event_logger
    sink_registry = context.sink_registry
    interlock_engine = context.interlock_engine
    leak_rate_estimator = context.leak_rate_estimator
    _leak_cfg = context.leak_cfg
    alarm_v2_state_mgr = context.alarm_v2_state_mgr
    annunciation_registry = context.annunciation_registry
    _alarm_ring = context.alarm_ring
    broker = context.broker
    experiment_manager = context.experiment_manager
    calibration_acquisition = context.calibration_acquisition
    event_bus = context.event_bus
    _cooldown_alarm = context.cooldown_alarm
    _vacuum_guard = context.vacuum_guard
    _alarm_dispatch_tasks = context.alarm_dispatch_tasks
    calibration_store = context.calibration_store
    writer = context.writer
    drivers_by_name = context.drivers_by_name
    sensor_diag = context.sensor_diag
    vacuum_trend = context.vacuum_trend
    _alarm_v2_state_tracker = context.alarm_v2_state_tracker
    _multiline_burst_auto_stop_meta = context.multiline_burst_auto_stop_meta
    _multiline_burst_auto_stop_tasks = context.multiline_burst_auto_stop_tasks
    escalation_service = context.escalation_service
    cooldown_service = context.cooldown_service
    action = cmd.get("cmd", "")
    if action == "engine_ready":
        return _engine_ready_response(cmd, context)
    if action == "mutation_capabilities":
        token = context.mutation_capability_token
        accepted = _valid_mutation_capability_token(token)
        receipt: dict[str, Any] = {
            "schema": _MUTATION_RECEIPT_SCHEMA,
            "accepted": accepted,
            "server_protocol_major": _MUTATION_PROTOCOL_MAJOR,
            "required_capability": _MUTATION_CAPABILITY,
        }
        if accepted:
            receipt["capability_token"] = token
        return {
            "ok": True,
            "compatibility_receipt": receipt,
        }
    protocol_failure = _mutation_protocol_failure(cmd, context)
    if protocol_failure is not None:
        return protocol_failure
    # Compatibility material is transport metadata, never handler input.  This
    # also strips a forged envelope from direct read and safe-direction calls.
    cmd = strip_mutation_envelope(cmd)
    shutdown_latch_failure = _shutdown_latch_failure(cmd, context)
    if shutdown_latch_failure is not None:
        return shutdown_latch_failure
    try:
        if action == "launcher_shutdown":
            identity = _shutdown_command_identity(cmd)
            if identity is None:
                return {
                    "ok": False,
                    "error_code": "launcher_shutdown_invalid",
                    "error": "launcher shutdown requires one exact typed authority envelope",
                    "delivery_state": "dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": True,
                }
            instance_id, request_id, capability = identity
            if not (
                secrets.compare_digest(instance_id, context.engine_instance_id)
                and secrets.compare_digest(capability, context.shutdown_capability)
            ):
                return {
                    "ok": False,
                    "error_code": "launcher_shutdown_authority_mismatch",
                    "error": "launcher shutdown authority does not match this engine incarnation",
                    "delivery_state": "dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": False,
                }
            async with context.shutdown_lock:
                if context.shutdown_request_id is None:
                    context.shutdown_request_id = request_id
                elif context.shutdown_request_id != request_id:
                    return {
                        "ok": False,
                        "error_code": "launcher_shutdown_already_requested",
                        "error": "a different shutdown request already owns this engine incarnation",
                        "delivery_state": "dispatched",
                        "commit_state": "not_committed",
                        "retry_safe": False,
                    }
                prior = context.shutdown_receipt
                if prior is not None:
                    return dict(prior)
                off_result = await _run_keithley_command(
                    "keithley_emergency_off", {"cmd": "keithley_emergency_off"}, safety_manager
                )
                off_evidence = parse_global_off_evidence(off_result.get("off_evidence"))
                if (
                    off_result.get("ok") is not True
                    or off_result.get("active_channels") != []
                    or off_evidence is None
                    or not off_evidence.verified_off
                ):
                    return {
                        "ok": False,
                        "error_code": "launcher_shutdown_global_off_unverified",
                        "error": "launcher shutdown is held because exact global OFF was not verified",
                        "delivery_state": "dispatched",
                        "commit_state": "not_committed",
                        "retry_safe": True,
                    }
                receipt = {
                    "ok": True,
                    "schema": _ENGINE_SHUTDOWN_RECEIPT_SCHEMA,
                    "engine_instance_id": instance_id,
                    "request_id": request_id,
                    "off_evidence": off_evidence.receipt_payload(),
                    "teardown_requested": True,
                    "delivery_state": "dispatched",
                    "commit_state": "committed",
                }
                context.shutdown_receipt = receipt
                return dict(receipt)
        if action == "periodic_subscription_barrier":
            if set(cmd) != {"cmd", "schema", "nonce"}:
                return _periodic_barrier_failure("barrier_invalid")
            if cmd.get("schema") != PERIODIC_QUERY_SCHEMA:
                return _periodic_barrier_failure("barrier_invalid")
            if context.zmq_publisher is None:
                return _periodic_barrier_failure("barrier_unavailable")
            nonce = cmd.get("nonce")
            if type(nonce) is not str or len(nonce) != 32 or any(ch not in "0123456789abcdef" for ch in nonce):
                return _periodic_barrier_failure("barrier_invalid")
            return encode_periodic_command_reply(await context.zmq_publisher.barrier(nonce))
        if action == "periodic_alarm_snapshot":
            if set(cmd) != {"cmd", "schema"} or cmd.get("schema") != PERIODIC_QUERY_SCHEMA:
                return _periodic_query_failure("snapshot_unavailable")
            return _periodic_snapshot_response(context)
        if action == "keithley_emergency_off":
            invalid_keys = set(cmd) - {"cmd", "channel"}
            channel = cmd.get("channel")
            if invalid_keys or ("channel" in cmd and (type(channel) is not str or not channel.strip())):
                return {
                    "ok": False,
                    "error_code": "safe_direction_command_invalid",
                    "error": "emergency-OFF accepts only cmd and an optional non-empty string channel",
                    "delivery_state": "dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": True,
                }
            try:
                normalize_smu_channel(channel)
            except (TypeError, ValueError):
                return {
                    "ok": False,
                    "error_code": "safe_direction_command_invalid",
                    "error": "Safe-direction channel identity is invalid.",
                    "delivery_state": "dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": True,
                }
        if action in {
            "keithley_emergency_off",
            "keithley_stop",
            "keithley_start",
            "keithley_set_target",
            "keithley_set_limits",
        }:
            result = await _run_keithley_command(action, cmd, safety_manager)
            if result.get("ok"):
                ch = cmd.get("channel", "?")
                if action == "keithley_start":
                    await event_logger.log_event("keithley", f"Keithley {ch}: запуск")
                elif action == "keithley_stop":
                    await event_logger.log_event("keithley", f"Keithley {ch}: остановка")
                elif action == "keithley_emergency_off":
                    await event_logger.log_event("keithley", f"\u26a0 Keithley {ch}: аварийное отключение")
                    if escalation_service is not None:
                        await escalation_service.escalate(
                            "emergency",
                            f"\u26a0 CryoDAQ: аварийное отключение Keithley {ch}",
                        )
            return result
        if action == "safety_status":
            return {
                "ok": True,
                **safety_manager.get_status(),
                "engine_instance_id": context.engine_instance_id,
            }
        if action == "annunciation_status":
            if set(cmd) != {"cmd"}:
                return {"ok": False, "error": "invalid_annunciation_command"}
            if annunciation_registry is None:
                return {"ok": False, "error": "annunciation_unavailable"}
            try:
                annunciation_registry.sync(alarm_v2_state_mgr.get_active(), safety_manager.get_status())
            except AnnunciationProjectionUnavailable:
                logger.error("Annunciation projection unavailable")
                return {"ok": False, "error": "annunciation_unavailable"}
            return {"ok": True, **annunciation_registry.snapshot()}
        if action == "annunciation_ack":
            required = {"cmd", "engine_instance_id", "activation_id", "operator", "reason", "request_id"}
            if set(cmd) != required or not all(
                type(cmd[key]) is str and len(cmd[key]) <= 256 for key in required - {"cmd"}
            ):
                return {"ok": False, "error": "invalid_annunciation_command"}
            if not cmd["engine_instance_id"] or not cmd["activation_id"]:
                return {"ok": False, "error": "invalid_annunciation_command"}
            if any(
                not cmd[key].strip() or cmd[key] != cmd[key].strip() or not cmd[key].isprintable()
                for key in ("operator", "reason")
            ):
                return {"ok": False, "error": "invalid_annunciation_command"}
            try:
                request_fingerprint = safety_audio_ack_request_fingerprint(cmd)
            except ValueError:
                return {"ok": False, "error": "invalid_annunciation_command"}
            expected_request_id = deterministic_safety_audio_ack_request_id(
                engine_instance_id=cmd["engine_instance_id"],
                activation_id=cmd["activation_id"],
                operator=cmd["operator"],
                reason=cmd["reason"],
            )
            if cmd["request_id"] != expected_request_id:
                return {"ok": False, "error": "invalid_annunciation_request_identity"}
            if annunciation_registry is None:
                return {"ok": False, "error": "annunciation_unavailable"}
            try:
                annunciation_registry.sync(alarm_v2_state_mgr.get_active(), safety_manager.get_status())
            except AnnunciationProjectionUnavailable:
                logger.error("Annunciation projection unavailable")
                return {"ok": False, "error": "annunciation_unavailable"}
            target = annunciation_registry.resolve(
                cmd["engine_instance_id"],
                cmd["activation_id"],
            )
            if target is None:
                return {"ok": False, "error": "stale_or_unknown_activation"}
            if target.source == "alarm_v2":
                return {
                    "ok": False,
                    "error_code": "canonical_alarm_ack_required",
                    "error": "alarm acknowledgements require the durable alarm_v2_ack command",
                }
            if target.source == "safety_fault":
                message = json.dumps(
                    {
                        "activation_id": target.activation_id,
                        "engine_instance_id": cmd["engine_instance_id"],
                        "event": "safety_audio_ack_request",
                        "reason": cmd["reason"].strip(),
                        "source_activation_id": str(target.source_activation_id),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                try:
                    audit_commit = await writer.append_operator_log_idempotent(
                        message=message,
                        author=cmd["operator"].strip(),
                        source="operator",
                        experiment_id=None,
                        tags=("safety_audio_ack", "safety_fault"),
                        request_id=cmd["request_id"],
                        request_fingerprint=request_fingerprint,
                    )
                except Exception as exc:
                    logger.error(
                        "Safety-audio acknowledgement audit persistence failed: exception=%s",
                        type(exc).__name__,
                    )
                    return {"ok": False, "error": "audit_persistence_failed"}
                if (
                    type(audit_commit) is not OperatorLogCommitResult
                    or audit_commit.entry.message != message
                    or audit_commit.entry.author != cmd["operator"].strip()
                    or audit_commit.entry.source != "operator"
                    or audit_commit.entry.experiment_id is not None
                    or audit_commit.entry.tags != ("safety_audio_ack", "safety_fault")
                ):
                    return {"ok": False, "error": "audit_receipt_invalid"}
                if not annunciation_registry.acknowledge_safety_audio(target.activation_id):
                    return {"ok": False, "error": "activation_changed"}
                return {
                    "ok": True,
                    "engine_instance_id": cmd["engine_instance_id"],
                    "activation_id": target.activation_id,
                    "request_id": cmd["request_id"],
                    "snapshot_revision": annunciation_registry.snapshot()["snapshot_revision"],
                    "audit_receipt": {
                        "schema": "safety_audio_ack_v1",
                        "request_id": cmd["request_id"],
                        "request_fingerprint": request_fingerprint,
                        "engine_instance_id": cmd["engine_instance_id"],
                        "activation_id": target.activation_id,
                        "source_activation_id": str(target.source_activation_id),
                        "entry_id": audit_commit.entry.id,
                        "committed": True,
                    },
                }
            return {"ok": False, "error": "stale_or_unknown_activation"}
        if action == "sinks_status":
            return {
                "ok": True,
                "results": [
                    {
                        "sink": r.sink_name,
                        "success": r.success,
                        "target": r.target,
                        "error": r.error,
                        "timestamp": r.timestamp.isoformat(),
                    }
                    for r in sink_registry.recent_results[-20:]
                ],
            }
        if action == "safety_acknowledge":
            reason = cmd.get("reason", "")
            return await safety_manager.acknowledge_fault(reason)
        if action == "interlock_acknowledge":
            # F24: re-arm a tripped interlock after operator clears the condition.
            name = cmd.get("interlock_name", "")
            try:
                interlock_engine.acknowledge(name)
                return {"ok": True, "action": "interlock_acknowledge", "interlock_name": name}
            except KeyError:
                return {
                    "ok": False,
                    "error_code": "interlock_unknown",
                    "error": "The requested interlock is unknown.",
                }
        _leak_resp = await _handle_leak_rate_command(action, cmd, leak_rate_estimator, _leak_cfg, event_logger)
        if _leak_resp is not None:
            return _leak_resp
        if action == "alarm_v2_status":
            if annunciation_registry is None:
                return {"ok": False, "error": "annunciation_unavailable"}
            active = alarm_v2_state_mgr.get_active()
            try:
                annunciation_registry.sync(active, safety_manager.get_status())
                annunciation = annunciation_registry.snapshot()
            except Exception:
                logger.error("Alarm activation projection unavailable")
                return {"ok": False, "error": "alarm_activation_unavailable"}
            activations = annunciation.get("activations") if isinstance(annunciation, dict) else None
            valid_activations = isinstance(activations, list) and all(
                isinstance(item, dict)
                and type(item.get("activation_id")) is str
                and bool(item["activation_id"])
                and type(item.get("source")) is str
                and bool(item["source"])
                and type(item.get("source_key")) is str
                and bool(item["source_key"])
                and type(item.get("severity")) is str
                and bool(item["severity"])
                and type(item.get("activated_at")) in (int, float)
                and math.isfinite(float(item["activated_at"]))
                and type(item.get("acknowledged")) is bool
                for item in activations or []
            )
            alarm_activations = (
                [item for item in activations if item["source"] == "alarm_v2"] if valid_activations else []
            )
            activation_keys = {item["source_key"] for item in alarm_activations}
            if (
                not valid_activations
                or len(alarm_activations) != len(activation_keys)
                or activation_keys != set(active)
            ):
                logger.error("Alarm activation projection unavailable")
                return {"ok": False, "error": "alarm_activation_unavailable"}
            activation_by_alarm = {item["source_key"]: item["activation_id"] for item in alarm_activations}
            return {
                "ok": True,
                "engine_instance_id": annunciation["engine_instance_id"],
                "snapshot_revision": annunciation["snapshot_revision"],
                "active": {
                    k: {
                        "level": v.level,
                        "message": v.message,
                        "triggered_at": v.triggered_at,
                        "channels": v.channels,
                        "acknowledged": v.acknowledged,
                        "acknowledged_at": v.acknowledged_at,
                        "acknowledged_by": v.acknowledged_by,
                        "activation_id": activation_by_alarm[k],
                        "evaluator_error": v.evaluator_error,
                    }
                    for k, v in active.items()
                },
                "history": alarm_v2_state_mgr.get_history(limit=20),
            }
        if action == "recent_alarms":
            # A3b: GUI sound poller — same (lack of) auth as alarm_v2_status.
            since_seq = int(cmd.get("since_seq", 0) or 0)
            return {"ok": True, **_alarm_ring.since(since_seq)}
        if action == "alarm_v2_history":
            # IV.4 F11: time-range slice of the existing alarm-v2
            # history deque. Used by the shift-end dialog to fill
            # the «Тревоги за смену» section; the state manager's
            # own 1000-entry ring buffer is the source of truth
            # (no persistence layer for alarm transitions yet).
            raw_start = cmd.get("start_ts")
            raw_end = cmd.get("end_ts")
            try:
                start_ts = float(raw_start) if raw_start is not None else None
                end_ts = float(raw_end) if raw_end is not None else None
            except (TypeError, ValueError):
                return {"ok": False, "error": "start_ts / end_ts must be numeric"}
            limit = int(cmd.get("limit", 500))
            history = alarm_v2_state_mgr.get_history(limit=1000)
            filtered: list[dict[str, Any]] = []
            for entry in history:
                at = float(entry.get("at", 0.0) or 0.0)
                if start_ts is not None and at < start_ts:
                    continue
                if end_ts is not None and at > end_ts:
                    continue
                filtered.append(entry)
            return {
                "ok": True,
                "history": filtered[:limit],
            }
        if action == "alarm_v2_ack":
            required = {
                "cmd",
                "alarm_name",
                "engine_instance_id",
                "activation_id",
                "operator",
                "reason",
                "request_id",
            }
            if set(cmd) != required or not all(
                type(cmd[key]) is str and len(cmd[key]) <= 256 for key in required - {"cmd"}
            ):
                return {"ok": False, "error": "invalid_alarm_ack_command"}
            if not cmd["alarm_name"] or not cmd["engine_instance_id"] or not cmd["activation_id"]:
                return {"ok": False, "error": "invalid_alarm_ack_command"}
            if any(
                not cmd[key].strip() or cmd[key] != cmd[key].strip() or not cmd[key].isprintable()
                for key in ("operator", "reason")
            ):
                return {"ok": False, "error": "invalid_alarm_ack_command"}
            return await _submit_alarm_ack(cmd, context)
        if action in _EXPERIMENT_MUTATION_ACTIONS:
            if not context.experiment_commands_accepting:
                return {
                    "ok": False,
                    "error_code": "engine_shutting_down",
                    "error": "experiment command submissions are frozen for shutdown",
                }
            if context.experiment_command_tasks:
                return {
                    "ok": False,
                    "error_code": "experiment_command_pending",
                    "error": "a prior experiment mutation is still authoritative; reconcile before retry",
                    "retry_safe": False,
                }
            owner_task = asyncio.create_task(
                _execute_owned_experiment_command(action, cmd, context),
                name=f"experiment_command_{_bounded_action_label(action)}",
            )
            context.experiment_command_tasks.add(owner_task)
            owner_task.add_done_callback(functools.partial(_owned_experiment_task_done, context, action))
            try:
                return await asyncio.shield(owner_task)
            except asyncio.CancelledError:
                logger.warning(
                    "Experiment command reply cancelled (action=%s): outcome unknown; "
                    "authoritative owner continues and automatic retry is unsafe",
                    _bounded_action_label(action),
                )
                raise
        if action == "experiment_status":
            if not context.experiment_commands_accepting:
                return {
                    "ok": False,
                    "error_code": "engine_shutting_down",
                    "error": "experiment command submissions are frozen for shutdown",
                }
            status_task = context.experiment_status_task
            if status_task is None or status_task.done():
                status_task = asyncio.create_task(
                    _execute_owned_experiment_read(action, cmd, context),
                    name="experiment_status_coalesced",
                )
                context.experiment_status_task = status_task
                status_task.add_done_callback(functools.partial(_owned_experiment_status_done, context))
            try:
                return await asyncio.wait_for(
                    asyncio.shield(status_task),
                    timeout=_EXPERIMENT_STATUS_TIMEOUT_S,
                )
            except TimeoutError:
                return {
                    "ok": False,
                    "error_code": "experiment_status_timeout",
                    "error": f"experiment_status timeout ({_EXPERIMENT_STATUS_TIMEOUT_S:g}s)",
                }
        if action in _EXPERIMENT_READ_ACTIONS:
            if not context.experiment_commands_accepting:
                return {
                    "ok": False,
                    "error_code": "engine_shutting_down",
                    "error": "experiment command submissions are frozen for shutdown",
                }
            if len(context.experiment_read_tasks) >= _MAX_PENDING_EXPERIMENT_READS:
                return {
                    "ok": False,
                    "error_code": "experiment_read_busy",
                    "error": "the bounded experiment read lane is full",
                }
            read_task = asyncio.create_task(
                _execute_owned_experiment_read(action, cmd, context),
                name=f"experiment_read_{_bounded_action_label(action)}",
            )
            context.experiment_read_tasks.add(read_task)
            read_task.add_done_callback(functools.partial(_owned_experiment_read_done, context, action))
            return await asyncio.shield(read_task)
        if action == "calibration_acquisition_status":
            return {"ok": True, **calibration_acquisition.stats}
        if action in {
            "calibration_v2_extract",
            "calibration_v2_fit",
            "calibration_v2_coverage",
        }:
            return await asyncio.to_thread(
                _run_calibration_v2_command,
                action,
                cmd,
                calibration_store,
            )
        if action == "readings_history":
            channels_raw = cmd.get("channels")
            channels = list(channels_raw) if channels_raw else None
            from_ts = cmd.get("from_ts")
            to_ts = cmd.get("to_ts")
            limit = int(cmd.get("limit_per_channel", 3600))
            data = await writer.read_readings_history(
                channels=channels,
                from_ts=float(from_ts) if from_ts is not None else None,
                to_ts=float(to_ts) if to_ts is not None else None,
                limit_per_channel=limit,
            )
            # Serialize: {channel: [[ts, value], ...]}
            return {
                "ok": True,
                "data": {ch: pts for ch, pts in data.items()},
            }
        if action == "cooldown_history_get":
            return await _run_cooldown_history_command(cmd, experiment_manager, writer)
        if action == "log_entry":
            return await _submit_operator_log_entry(cmd, context)
        if action == "log_get":
            log_scope = cmd.get("log_scope")
            requested_experiment = cmd.get("experiment_id")
            if log_scope == "experiment":
                if type(requested_experiment) is not str or not requested_experiment:
                    return {
                        "ok": False,
                        "error_code": "operator_log_scope_invalid",
                        "error": "log_scope=experiment requires a non-empty experiment_id",
                    }
                experiment_id = requested_experiment
            elif log_scope == "all":
                if requested_experiment is not None:
                    return {
                        "ok": False,
                        "error_code": "operator_log_scope_invalid",
                        "error": "log_scope=all cannot name an experiment_id",
                    }
                experiment_id = None
            else:
                return {
                    "ok": False,
                    "error_code": "operator_log_scope_invalid",
                    "error": "log_get requires explicit log_scope=experiment or log_scope=all",
                }
            scoped_cmd = {
                key: value
                for key, value in cmd.items()
                if key not in {"log_scope", "current_experiment", "experiment_id"}
            }
            if experiment_id is not None:
                scoped_cmd["experiment_id"] = experiment_id
            result = await _run_operator_log_command(
                action,
                scoped_cmd,
                writer,
                experiment_manager,
                broker,
            )
            result["scope_receipt"] = {
                "schema": "operator_log_read_scope_v1",
                "log_scope": log_scope,
                "experiment_id": experiment_id,
            }
            return result
        if action in {
            "calibration_curve_evaluate",
            "calibration_curve_list",
            "calibration_curve_get",
            "calibration_curve_lookup",
            "calibration_curve_assign",
            "calibration_runtime_status",
            "calibration_runtime_set_global",
            "calibration_runtime_set_channel_policy",
            "calibration_curve_export",
            "calibration_curve_import",
        }:
            return await asyncio.to_thread(
                _run_calibration_command,
                action,
                cmd,
                calibration_store=calibration_store,
                experiment_manager=experiment_manager,
                drivers_by_name=drivers_by_name,
            )
        if action == "get_sensor_diagnostics":
            if sensor_diag is None:
                return {"ok": False, "error": "SensorDiagnostics отключён"}
            from dataclasses import asdict

            diag = sensor_diag.get_diagnostics()
            summary = sensor_diag.get_summary()
            return {
                "ok": True,
                "channels": {k: asdict(v) for k, v in diag.items()},
                "summary": asdict(summary),
            }
        if action == "get_vacuum_trend":
            if vacuum_trend is None:
                return {"ok": False, "error": "VacuumTrendPredictor отключён"}
            from dataclasses import asdict

            pred = vacuum_trend.get_prediction()
            if pred is None:
                return {"ok": True, "status": "no_data"}
            return {"ok": True, **asdict(pred)}
        if action == "shift_handover_summary":
            shift_duration_h = cmd.get("shift_duration_h", 8)
            if (
                (type(shift_duration_h) is int and not 0 < shift_duration_h <= 168)
                or (
                    type(shift_duration_h) is float
                    and (not math.isfinite(shift_duration_h) or not 0 < shift_duration_h <= 168)
                )
                or type(shift_duration_h) not in (int, float)
            ):
                return {
                    "ok": False,
                    "error_code": "shift_duration_invalid",
                    "error": "shift_duration_h must be a finite number from 0 (exclusive) through 168 hours",
                    "delivery_state": "dispatched",
                    "commit_state": "not_committed",
                    "retry_safe": True,
                }
            _sh_active = experiment_manager.active_experiment
            await event_bus.publish(
                EngineEvent(
                    event_type="shift_handover_request",
                    timestamp=datetime.now(UTC),
                    payload={
                        "requested_by": cmd.get("operator", ""),
                        "shift_duration_h": shift_duration_h,
                    },
                    experiment_id=_sh_active.experiment_id if _sh_active else None,
                )
            )
            return {"ok": True, "status": "queued"}
        if action == "cooldown_alarm.arm":
            if _cooldown_alarm is None:
                return {"ok": False, "error": "CooldownAlarm не инициализирован"}
            ok = _cooldown_alarm.arm()
            return {"ok": ok, "state": _cooldown_alarm.state.name}
        if action == "cooldown_alarm.disarm":
            if _cooldown_alarm is None:
                return {"ok": False, "error": "CooldownAlarm не инициализирован"}
            _cooldown_alarm.disarm()
            return {"ok": True, "state": "DISARMED"}
        if action == "cooldown_alarm.status":
            if _cooldown_alarm is None:
                return {"state": "UNAVAILABLE"}
            _t_cold_state = _alarm_v2_state_tracker.get(_cooldown_alarm._cold_ch)
            _t_cold_val = _t_cold_state.value if _t_cold_state is not None and not _t_cold_state.is_stale else None
            return {
                "state": _cooldown_alarm.state.name,
                "eta_h": _cooldown_alarm.current_eta_h,
                "progress": _cooldown_alarm.current_progress,
                "t_cold": _t_cold_val,
            }
        if action == "vacuum_guard.status":
            if _vacuum_guard is None:
                return {"state": "UNAVAILABLE"}
            return {"state": _vacuum_guard.state.name}
        if action == "multiline.set_channels":
            # v0.55.16.0.1 (smoke hotfix): operator picks 1..32
            # channels via the panel selector dialog.
            return await _handle_multiline_set_channels_command(
                cmd,
                drivers_by_name=drivers_by_name,
                config_dir=_CONFIG_DIR,
            )
        if action.startswith("multiline.burst_"):
            # v0.55.11 (F-MultiLineContinuous): GUI burst-capture
            # button + status poll + manual stop.
            response = await _handle_multiline_burst_command(
                action,
                cmd,
                drivers_by_name=drivers_by_name,
                experiment_manager=experiment_manager,
                experiments_root=_DATA_DIR / "experiments",
                auto_stop_tasks=_multiline_burst_auto_stop_meta,
            )
            # Schedule auto-stop on the engine loop if duration_s
            # was set — the helper records intent in the meta dict;
            # this site materialises the task so it runs on the
            # right loop and gets cleaned up automatically.
            if response.get("ok") and action == "multiline.burst_start" and response.get("duration_s") is not None:
                target_name = response.get("name", "")
                duration_s = float(response["duration_s"])

                _t = asyncio.create_task(
                    _multiline_burst_auto_stop(
                        target_name,
                        duration_s,
                        drivers_by_name=drivers_by_name,
                        experiments_root=_DATA_DIR / "experiments",
                        auto_stop_tasks=_multiline_burst_auto_stop_tasks,
                    ),
                    name=f"multiline_burst_auto_stop_{_bounded_action_label(target_name)}",
                )
                # Cancel any pre-existing auto-stop for the same
                # driver — operator restarting the timer wins.
                prev = _multiline_burst_auto_stop_tasks.get(target_name)
                if prev is not None and not prev.done():
                    prev.cancel()
                _multiline_burst_auto_stop_tasks[target_name] = _t
            return response
        if action == "cooldown_eta_get":
            # B1 (2026-07): additive read-only command — exposes the
            # same CooldownService.last_prediction() the old in-process
            # CooldownAdapter read directly, now for the assistant
            # process's ZMQ-based CooldownAdapter (agents/assistant/
            # query/adapters/cooldown_adapter.py). Never a write path.
            if cooldown_service is None:
                return {"ok": True, "prediction": None}
            return {"ok": True, "prediction": cooldown_service.last_prediction()}
        return {
            "ok": False,
            "error_code": "command_unknown",
            "error": "Command is not supported.",
            "delivery_state": "dispatched",
            "commit_state": "not_committed",
            "retry_safe": False,
        }
    except Exception as exc:
        logger.error(
            "Engine command failed: action=%s exception=%s",
            _bounded_action_label(action),
            type(exc).__name__,
        )
        if _is_mutating_command(action):
            return {
                "ok": False,
                "error_code": "command_execution_failed",
                "error": "command execution failed",
                "delivery_state": "dispatched",
                "commit_state": "unknown",
                "retry_safe": False,
            }
        return {"ok": False, "error": "command execution failed"}


def _zmq_publisher_drop_count(broker: DataBroker) -> int:
    """Return the current publisher drop counter without nested wiring logic."""

    return int(broker.stats["zmq_publisher"]["dropped"])


class _EngineStartupRollback:
    """Retain reverse-order cleanup authority until live REP is acquired."""

    def __init__(self) -> None:
        self._callbacks: list[tuple[str, Callable[[], Any]]] = []
        self._settled = False
        self._rollback_started = False
        self._rollback_task: asyncio.Task[None] | None = None

    def add(self, label: str, callback: Callable[[], Any]) -> None:
        if self._settled or self._rollback_started:
            raise RuntimeError("engine startup transaction is already settled")
        self._callbacks.append((label, callback))

    async def acquire(
        self,
        operation: Awaitable[Any],
        *,
        label: str,
        rollback: Callable[[], Any],
    ) -> Any:
        # Register first: a start method may acquire a partial resource and
        # then raise, so its stop path must still run.
        self.add(label, rollback)
        return await self.guard(operation)

    async def call(self, operation: Callable[[], Any]) -> Any:
        try:
            result = operation()
            if inspect.isawaitable(result):
                return await result
            return result
        except BaseException:
            await self.rollback()
            raise

    async def guard(self, operation: Awaitable[Any]) -> Any:
        try:
            return await operation
        except BaseException:
            await self.rollback()
            raise

    async def rollback(self) -> None:
        if self._settled:
            return
        self._rollback_started = True
        task = self._rollback_task
        if task is None or task.done():
            task = asyncio.create_task(self._rollback_until_settled(), name="engine-startup-rollback")
            self._rollback_task = task

        cancellation_seen = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # The acquired resources outlive the cancelled caller. Keep
                # awaiting the retained cleanup task through every repeated
                # cancellation, then propagate cancellation after settlement.
                cancellation_seen = True
        task.result()
        if cancellation_seen:
            raise asyncio.CancelledError

    async def _rollback_until_settled(self) -> None:
        """Retry retained cleanup until no startup owner remains."""

        while not self._settled:
            try:
                await self._rollback_once()
            except BaseException as exc:  # noqa: BLE001 - retained owner stays in HOLD
                logger.critical(
                    "Engine startup rollback retained owners; exception=%s",
                    type(exc).__name__,
                )
                await asyncio.sleep(0.05)

    async def _rollback_once(self) -> None:
        failed: list[tuple[str, Callable[[], Any], BaseException]] = []
        while self._callbacks:
            label, callback = self._callbacks.pop()
            try:
                result = callback()
                if inspect.isawaitable(result):
                    await result
            except BaseException as exc:  # noqa: BLE001 - continue complete rollback
                failed.append((label, callback, exc))
                logger.error(
                    "Engine startup rollback failed: owner=%s exception=%s",
                    label,
                    type(exc).__name__,
                )
        if failed:
            # Preserve only unsettled owners, in their original registration
            # order, so a later rollback attempt retries them in reverse order.
            self._callbacks.extend((label, callback) for label, callback, _exc in reversed(failed))
            labels = ", ".join(label for label, _callback, _exc in failed)
            raise RuntimeError(f"engine startup rollback incomplete: {labels}") from failed[0][2]
        self._settled = True

    def commit(self) -> None:
        if self._settled or self._rollback_started:
            raise RuntimeError("engine startup transaction is already settled")
        self._settled = True
        self._callbacks.clear()


@dataclass(frozen=True, slots=True)
class _EngineShutdownOwner:
    """One retained shutdown callback with a stable, non-secret label."""

    label: str
    stop: Callable[[], Any]

    def __post_init__(self) -> None:
        if (
            type(self.label) is not str
            or not self.label
            or len(self.label) > 64
            or not self.label.isascii()
            or not all(char.isalnum() or char in {"_", "-"} for char in self.label)
            or not callable(self.stop)
        ):
            raise ValueError("engine shutdown owner is invalid")


@dataclass(frozen=True, slots=True)
class _EngineShutdownLayer:
    """One dependency layer whose owners are true settlement peers."""

    label: str
    owners: tuple[_EngineShutdownOwner, ...]

    def __post_init__(self) -> None:
        if (
            type(self.label) is not str
            or not self.label
            or len(self.label) > 64
            or not self.label.isascii()
            or not all(char.isalnum() or char in {"_", "-"} for char in self.label)
            or type(self.owners) is not tuple
            or not self.owners
        ):
            raise ValueError("engine shutdown layer is invalid")


class _EngineShutdownSettledFailure(ShutdownOwnerSettledError):
    """A terminal task owner settled, but its terminal result was failure."""

    def __init__(self, failure: BaseException) -> None:
        super().__init__(failure)


async def _invoke_engine_shutdown_owner(owner: _EngineShutdownOwner) -> None:
    result = owner.stop()
    if inspect.isawaitable(result):
        result = await result
    if result is not None:
        raise RuntimeError("shutdown callback did not return exact success")


async def _run_engine_shutdown_phase(
    owners: tuple[_EngineShutdownOwner, ...],
    logger_: logging.Logger,
    *,
    retry_delay_s: float,
    sleep: Callable[[float], Awaitable[None]],
) -> tuple[tuple[str, BaseException], ...]:
    """Attempt all retained peers per pass and retry failures without a cap."""

    remaining = list(owners)
    first_failures: list[tuple[str, BaseException]] = []
    failed_labels: set[str] = set()
    while remaining:
        tasks = tuple(
            asyncio.create_task(
                _invoke_engine_shutdown_owner(owner),
                name=f"engine-shutdown-{owner.label}",
            )
            for owner in remaining
        )
        results = await asyncio.gather(*tasks, return_exceptions=True)
        retry: list[_EngineShutdownOwner] = []
        for owner, result in zip(remaining, results, strict=True):
            if result is None:
                logger_.info("Engine shutdown owner settled: owner=%s", owner.label)
                continue
            if isinstance(result, ShutdownOwnerSettledError):
                if owner.label not in failed_labels:
                    failed_labels.add(owner.label)
                    first_failures.append((owner.label, result.failure))
                logger_.error(
                    "Engine shutdown terminal owner failed after settlement: owner=%s exception=%s",
                    owner.label,
                    type(result.failure).__name__,
                )
                continue
            assert isinstance(result, BaseException)
            if owner.label not in failed_labels:
                failed_labels.add(owner.label)
                first_failures.append((owner.label, result))
            logger_.error(
                "Engine shutdown owner retained for retry: owner=%s exception=%s",
                owner.label,
                type(result).__name__,
            )
            retry.append(owner)
        remaining = retry
        if remaining:
            await sleep(retry_delay_s)
    return tuple(first_failures)


async def _settle_engine_shutdown_phase(
    owners: tuple[_EngineShutdownOwner, ...],
    logger_: logging.Logger,
    *,
    retry_delay_s: float = 0.1,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[tuple[str, BaseException], ...]:
    """Retain one attempt-all phase through repeated caller cancellation."""

    if len({owner.label for owner in owners}) != len(owners):
        raise ValueError("engine shutdown owner labels must be unique")
    requested_delay = float(retry_delay_s)
    bounded_delay = min(max(requested_delay, 0.0), 1.0) if math.isfinite(requested_delay) else 0.1
    settlement = asyncio.create_task(
        _run_engine_shutdown_phase(
            owners,
            logger_,
            retry_delay_s=bounded_delay,
            sleep=sleep,
        ),
        name="engine-shutdown-phase-settlement",
    )
    cancellation: asyncio.CancelledError | None = None
    while not settlement.done():
        try:
            await asyncio.shield(settlement)
        except asyncio.CancelledError as exc:
            if cancellation is None:
                cancellation = exc
    failures = settlement.result()
    if cancellation is None:
        return failures
    return (("phase_wait", cancellation), *failures)


async def _settle_engine_shutdown_plan(
    layers: tuple[_EngineShutdownLayer, ...],
    logger_: logging.Logger,
    *,
    retry_delay_s: float = 0.1,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[tuple[str, BaseException], ...]:
    """Settle dependency layers sequentially and true peers concurrently."""

    if type(layers) is not tuple:
        raise TypeError("engine shutdown plan must be a tuple")
    if len({layer.label for layer in layers}) != len(layers):
        raise ValueError("engine shutdown layer labels must be unique")
    owner_labels = tuple(owner.label for layer in layers for owner in layer.owners)
    if len(set(owner_labels)) != len(owner_labels):
        raise ValueError("engine shutdown owner labels must be globally unique")

    failures: list[tuple[str, BaseException]] = []
    for layer in layers:
        logger_.info("Engine shutdown layer starting: layer=%s", layer.label)
        layer_failures = await _settle_engine_shutdown_phase(
            layer.owners,
            logger_,
            retry_delay_s=retry_delay_s,
            sleep=sleep,
        )
        failures.extend((f"{layer.label}.{owner_label}", failure) for owner_label, failure in layer_failures)
        logger_.info("Engine shutdown layer settled: layer=%s", layer.label)
    return tuple(failures)


async def _drain_retained_command_tasks_owner(
    context: EngineCommandContext,
    logger_: logging.Logger,
) -> None:
    """Normalize the retained-command deadline result for strict shutdown."""

    completed_within_deadline = await _drain_experiment_command_tasks(context, logger_)
    if completed_within_deadline is not True:
        raise _EngineShutdownSettledFailure(TimeoutError("retained command settlement exceeded its visible deadline"))


async def _stop_scheduler_shutdown_owner(
    scheduler: Scheduler,
    feed: RecordingLifecycleFeed,
    sequence: int,
) -> None:
    await _stop_scheduler_with_recording_feed(scheduler, feed, sequence)


async def _stop_terminal_task_owner(task: asyncio.Task[Any]) -> None:
    if not task.done():
        task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        return
    except BaseException as exc:  # noqa: BLE001 - task ownership is terminal
        raise _EngineShutdownSettledFailure(exc) from None


async def _request_and_settle_terminal_task_owner(
    request_stop: Callable[[], Any],
    task: asyncio.Task[Any] | None,
) -> None:
    result = request_stop()
    if inspect.isawaitable(result):
        result = await result
    if result is not None:
        raise RuntimeError("shutdown request did not return exact success")
    if task is None:
        return
    try:
        await task
    except BaseException as exc:  # noqa: BLE001 - task ownership is terminal
        raise _EngineShutdownSettledFailure(exc) from None


async def _settle_command_server_before_safety(
    command_server: Any,
    safety_manager: Any,
    logger_: logging.Logger,
    *,
    retry_delay_s: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[BaseException, ...]:
    """Freeze mutation ingress and retain teardown until global OFF is final.

    A command-server failure must never bypass the safety owner.  After every
    failed/cancelled server-stop attempt we prove global OFF, retain the
    process, and retry server settlement.  Once every command owner is settled,
    global OFF is proved one final time so no late mutation can invalidate it.
    Earlier failures are returned for deferred reporting after the remaining
    teardown owners have been attempted.
    """

    command_server.freeze_admission()
    failures: list[BaseException] = []
    while True:
        settlement = asyncio.create_task(
            command_server.stop(),
            name="command-server-shutdown-owner",
        )
        # Attempt OFF immediately, before waiting on an intentionally
        # cancellation-resistant mutation owner. While such an owner remains,
        # periodically reassert OFF; the process and all dependencies stay
        # retained until the command owner terminally settles.
        while not settlement.done():
            await stop_safety_manager_with_hold(safety_manager, logger_)
            if settlement.done():
                break
            retry_timer = asyncio.create_task(
                sleep(retry_delay_s),
                name="command-server-shutdown-safety-retry",
            )
            while not settlement.done() and not retry_timer.done():
                try:
                    await asyncio.wait(
                        {settlement, retry_timer},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                except asyncio.CancelledError as cancel_exc:
                    failures.append(cancel_exc)
            if not retry_timer.done():
                retry_timer.cancel()
            try:
                await retry_timer
            except asyncio.CancelledError:
                pass

        try:
            settlement.result()
        except BaseException as exc:  # noqa: BLE001 - safety settlement must still run
            failures.append(exc)
            logger_.critical(
                "Command-server shutdown incomplete; retaining process through safety settlement: %s",
                type(exc).__name__,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            await stop_safety_manager_with_hold(safety_manager, logger_)
            continue
        break

    # The final OFF proof starts only after the last command owner is known to
    # be terminal, covering a mutation that settled after an earlier proof.
    await stop_safety_manager_with_hold(safety_manager, logger_)
    return tuple(failures)


class _EngineTeardownState(Enum):
    """Monotonic engine teardown checkpoints."""

    NEW = "new"
    INGRESS_OFF_SETTLED = "ingress_off_settled"
    PLAN_SETTLED = "plan_settled"


class _EngineTeardownSequence:
    """Own ordered teardown settlement and its single final disposition."""

    def __init__(
        self,
        *,
        command_ingress: ZMQCommandIngressPair,
        safety_manager: Any,
        logger_: logging.Logger,
        ingress_terminal_failure: ZMQCommandIngressTerminalFailure | None,
    ) -> None:
        self._command_ingress = command_ingress
        self._safety_manager = safety_manager
        self._logger = logger_
        self._initial_ingress_terminal_failure = ingress_terminal_failure
        self._state = _EngineTeardownState.NEW
        self._ingress_failures: tuple[BaseException, ...] = ()
        self._plan_failures: tuple[tuple[str, BaseException], ...] = ()

    @property
    def state(self) -> _EngineTeardownState:
        return self._state

    async def settle_ingress_off(self) -> None:
        if self._state is not _EngineTeardownState.NEW:
            raise RuntimeError("engine teardown ingress/OFF settlement is out of sequence")
        self._ingress_failures = await _settle_command_server_before_safety(
            self._command_ingress,
            self._safety_manager,
            self._logger,
        )
        self._state = _EngineTeardownState.INGRESS_OFF_SETTLED

    async def settle_plan(self, layers: tuple[_EngineShutdownLayer, ...]) -> None:
        if self._state is not _EngineTeardownState.INGRESS_OFF_SETTLED:
            raise RuntimeError("engine teardown plan settlement is out of sequence")
        self._plan_failures = await _settle_engine_shutdown_plan(layers, self._logger)
        self._state = _EngineTeardownState.PLAN_SETTLED

    def finalize(self) -> None:
        if self._state is not _EngineTeardownState.PLAN_SETTLED:
            raise RuntimeError("engine teardown cannot finalize before the shutdown plan settles")
        shutdown_failures = (
            tuple(("command_server", failure) for failure in self._ingress_failures) + self._plan_failures
        )
        ingress_terminal_failure = self._command_ingress.terminal_failure or self._initial_ingress_terminal_failure
        if ingress_terminal_failure is not None:
            self._logger.error(
                "Engine command ingress terminated; endpoint=%s stage=%s failure=%s",
                ingress_terminal_failure.endpoint,
                ingress_terminal_failure.stage,
                ingress_terminal_failure.failure_type,
            )
            if shutdown_failures:
                self._logger.error(
                    "Engine ingress failure teardown recovered owner failures: owners=%s",
                    ",".join(label for label, _failure in shutdown_failures),
                )
            raise ZMQCommandIngressTerminalError(ingress_terminal_failure) from None
        if shutdown_failures:
            failure_labels = ",".join(label for label, _failure in shutdown_failures)
            first_label, first_failure = shutdown_failures[0]
            if isinstance(first_failure, asyncio.CancelledError):
                raise first_failure
            raise RuntimeError(
                f"engine shutdown settled after recovered owner failures: first={first_label}; owners={failure_labels}"
            ) from first_failure


async def _rollback_supervisor(supervisor: TaskSupervisor) -> None:
    """Stop restart authority and settle non-safety tasks during failed boot."""

    supervisor.stop()
    tasks = tuple(
        task
        for name, task in supervisor.supervised_tasks.items()
        if name not in {"safety_collect", "safety_monitor"} and not task.done()
    )
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _rollback_scheduler_startup(
    scheduler: Scheduler,
    recording_lifecycle_feed: RecordingLifecycleFeed,
    rollback_state: dict[str, Any],
) -> None:
    """Settle a scheduler whose startup transaction reached its start attempt."""

    if rollback_state["attempted"] is True:
        await _stop_scheduler_with_recording_feed(
            scheduler,
            recording_lifecycle_feed,
            rollback_state["sequence"],
        )


def _engine_startup_summary(
    driver_configs: tuple[InstrumentConfig, ...],
    alarm_configs: list[AlarmConfig],
    interlock_engine: InterlockEngine,
) -> tuple[int, int, int]:
    """Return the bounded startup counts logged after all owners are live."""

    return (
        len(driver_configs),
        len(alarm_configs),
        len(interlock_engine.get_state()),
    )


def _cold_rotation_project_root(data_dir: Path) -> Path:
    """Resolve relative cold-rotation archive paths from the hot-data authority."""
    return get_archive_dir(data_dir).parent.parent


def _install_engine_signal_handlers(shutdown_event: asyncio.Event) -> Callable[[], None]:
    """Install shutdown ownership and return its exact rollback action."""

    loop = asyncio.get_running_loop()
    request_shutdown = functools.partial(_request_shutdown, shutdown_event)
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, request_shutdown)
        try:
            loop.add_signal_handler(signal.SIGTERM, request_shutdown)
        except BaseException:
            loop.remove_signal_handler(signal.SIGINT)
            raise

        def remove() -> None:
            loop.remove_signal_handler(signal.SIGTERM)
            loop.remove_signal_handler(signal.SIGINT)

        return remove

    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, request_shutdown)

    def remove() -> None:
        signal.signal(signal.SIGINT, previous)

    return remove


async def _commit_engine_command_ingress_startup(
    *,
    command_ingress: ZMQCommandIngressPair,
    command_context: EngineCommandContext,
    startup: _EngineStartupRollback,
) -> None:
    """Commit READY inside one synchronous health/emit/health boundary."""

    try:
        health_result = command_ingress.require_healthy()
        _require_exact_synchronous_none(
            health_result,
            boundary="engine command ingress health check",
        )
        if command_context.engine_ready_nonce:
            ready_result = _emit_engine_ready_receipt(command_context)
            _require_exact_synchronous_none(
                ready_result,
                boundary="engine READY emitter",
            )
        health_result = command_ingress.require_healthy()
        _require_exact_synchronous_none(
            health_result,
            boundary="engine command ingress health check",
        )
        command_context.experiment_commands_accepting = True
        startup.commit()
    except BaseException:
        await startup.rollback()
        raise


def _require_exact_synchronous_none(result: object, *, boundary: str) -> None:
    """Reject and settle an unexpected awaitable without yielding to it."""

    if result is None:
        return
    if inspect.isawaitable(result):
        close = getattr(result, "close", None)
        if callable(close):
            close()
        elif isinstance(result, asyncio.Future):
            result.cancel()
    raise TypeError(f"{boundary} must return exactly None")


async def _wait_for_engine_shutdown_or_ingress_failure(
    shutdown_event: asyncio.Event,
    command_ingress: ZMQCommandIngressPair,
) -> ZMQCommandIngressTerminalFailure | None:
    """Wait for normal shutdown or sticky ingress failure, prioritizing failure."""

    shutdown_waiter = asyncio.create_task(shutdown_event.wait(), name="engine-shutdown-signal-waiter")
    ingress_waiter = asyncio.create_task(
        command_ingress.wait_terminal_failure(),
        name="engine-command-ingress-terminal-waiter",
    )
    failure: ZMQCommandIngressTerminalFailure | None = None
    try:
        await asyncio.wait(
            {shutdown_waiter, ingress_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Read the sticky pair authority after the wait returns and before any
        # further suspension. If both events are ready, ingress failure wins.
        failure = command_ingress.terminal_failure
        if failure is None and ingress_waiter.done():
            failure = ingress_waiter.result()
    finally:
        for waiter in (shutdown_waiter, ingress_waiter):
            if not waiter.done():
                waiter.cancel()
        await asyncio.gather(shutdown_waiter, ingress_waiter, return_exceptions=True)
    # Include a failure that latched while the losing waiter was being settled.
    # This closes the normal-signal/fatal-callback boundary race.
    return command_ingress.terminal_failure or failure


async def _run_engine(
    *,
    mock: bool = False,
    engine_instance_id: str = "",
    shutdown_capability: str = "",
    engine_ready_nonce: str = "",
    engine_ready_channel_fd: int | None = None,
) -> None:
    """Инициализировать и запустить все подсистемы engine."""
    engine_instance_id = _canonical_engine_instance_id(engine_instance_id)
    start_ts = time.monotonic()
    shutdown_event = asyncio.Event()
    logger.info("═══ CryoDAQ Engine запускается ═══")

    # --- Конфигурация путей (*.local.yaml приоритетнее *.yaml) ---
    instruments_cfg = _engine_config_path("instruments")
    interlocks_cfg = _engine_config_path("interlocks")
    housekeeping_cfg = _engine_config_path("housekeeping")
    safety_cfg = _engine_config_path("safety")
    cooldown_cfg_path = _engine_config_path("cooldown")
    # One read, shared by the throttle-pattern scan and InterlockEngine, so the
    # digest we disclose is the digest of the bytes we actually apply. An absent
    # interlocks file is not an error here: both consumers already tolerate it,
    # and skipping the read preserves that. There are no bytes to race on.
    interlocks_snapshot = interlocks_cfg.read_bytes() if interlocks_cfg.is_file() else None
    logger.info("Конфигурация: instruments=%s", instruments_cfg.name)
    # --- Создать основные компоненты ---
    broker = DataBroker()
    safety_broker = SafetyBroker()
    calibration_dir = _DATA_DIR / "calibration"
    calibration_store = CalibrationStore(calibration_dir)
    curves_dir = calibration_dir / "curves"
    if curves_dir.exists():
        calibration_store.load_curves(curves_dir)

    # Драйверы
    driver_load = _load_drivers(
        instruments_cfg,
        mock=mock,
        calibration_store=calibration_store,
        data_dir=_DATA_DIR,
    )
    driver_configs = driver_load.instrument_configs
    drivers_by_name = {cfg.driver.name: cfg.driver for cfg in driver_configs}
    reviewed_source_runtime_binding = None
    if driver_load.reviewed_source is not None:
        reviewed_source_runtime_binding = next(
            (cfg.runtime_binding for cfg in driver_configs if cfg.driver is driver_load.reviewed_source),
            None,
        )
        if (
            reviewed_source_runtime_binding is None
            or not is_issued_runtime_binding(reviewed_source_runtime_binding)
            or reviewed_source_runtime_binding.driver is not driver_load.reviewed_source
            or reviewed_source_runtime_binding.trust_class is not DriverTrustClass.REVIEWED_SOURCE
        ):
            raise DriverRegistryError("reviewed source lacks exact sealed runtime binding")

    qualification_receipt = None
    qualification_path = _DATA_DIR / "qualification" / "receipt.json"
    plugin_snapshot: dict[str, str] = {}
    if (
        not mock
        and qualification_path.is_file()
        and driver_load.reviewed_source is not None
        and reviewed_source_runtime_binding is not None
    ):
        try:
            qualification_context = source_checkout_qualification_context(
                project_root=_PROJECT_ROOT,
                config_directory=_CONFIG_DIR,
                reviewed_source=driver_load.reviewed_source,
                runtime_binding=reviewed_source_runtime_binding,
                instrument_configuration_path=instruments_cfg,
                plugins_snapshot=plugin_snapshot,
            )
            qualification_receipt = verify_qualification_receipt(
                qualification_path.read_bytes(),
                expected=qualification_context,
                replay_directory=_DATA_DIR / "qualification" / "consumed",
            )
        except (OSError, QualificationReceiptError, ValueError) as exc:
            logger.critical("Laboratory qualification refused: %s", exc)
    elif not mock and qualification_path.is_file():
        logger.critical("Laboratory qualification refused: reviewed-source binding is unavailable")
    elif not mock:
        logger.critical("Laboratory qualification receipt is absent; energizing mutations remain UNQUALIFIED")

    # SafetyManager — создаётся ПЕРВЫМ
    safety_manager = SafetyManager(
        safety_broker,
        keithley_driver=driver_load.reviewed_source,
        reviewed_source_runtime_binding=reviewed_source_runtime_binding,
        qualification_receipt=qualification_receipt,
        mock=mock,
        data_broker=broker,
    )
    _log_physical_policy_receipt("safety", safety_manager.load_config(safety_cfg))

    # F35: descriptor identity is mandatory production startup authority.
    # A machine-local instrument configuration requires a complete local
    # descriptor replacement; it never falls back to the tracked base.
    live_descriptor_catalog = await _load_live_descriptor_authority(instruments_cfg, driver_load)

    housekeeping_raw, housekeeping_receipt = load_housekeeping_config(housekeeping_cfg)
    _log_physical_policy_receipt("housekeeping", housekeeping_receipt)
    # Merge legacy interlocks.yaml protection patterns with the modern
    # alarms_v3.yaml critical channels. Without this the throttle thins
    # critical channels even though alarms_v3 marks them CRITICAL.
    legacy_patterns = load_protected_channel_patterns(
        interlocks_cfg,
        snapshots=None if interlocks_snapshot is None else {interlocks_cfg: interlocks_snapshot},
        descriptor_catalog=live_descriptor_catalog,
    )
    alarms_v3_path = _CONFIG_DIR / "alarms_v3.yaml"
    v3_patterns = load_critical_channels_from_alarms_v3(alarms_v3_path)
    merged_patterns = list({*legacy_patterns, *v3_patterns})
    logger.info(
        "Adaptive-throttle protection: %d legacy + %d v3 = %d unique patterns",
        len(legacy_patterns),
        len(v3_patterns),
        len(merged_patterns),
    )
    # F-1 startup diagnostic: resolve every canonical protected expression to
    # one exact raw emitted label before AdaptiveThrottle is constructed.  A
    # missing, ambiguous, or colliding binding is a startup configuration
    # error; do not boot with an optimistic/raw-substring fallback.
    merged_patterns = validate_safety_pattern_liveness(
        descriptor_catalog=live_descriptor_catalog,
        interlocks_config_path=interlocks_cfg,
        safety_manager=safety_manager,
        adaptive_throttle_patterns=v3_patterns,
        adaptive_throttle_raw_patterns=legacy_patterns,
    )
    adaptive_throttle = AdaptiveThrottle(
        housekeeping_raw.get("adaptive_throttle", {}),
        protected_patterns=merged_patterns,
    )

    # SQLite — persistence-first: writer создаётся ДО scheduler
    writer = SQLiteWriter(_DATA_DIR, channel_catalog=live_descriptor_catalog)
    # Disk-full graceful degradation (Phase 2a H.1): wire writer to the
    # engine event loop and SafetyManager so a disk-full error in the
    # writer thread can latch a safety fault via run_coroutine_threadsafe.
    # The reverse hook (acknowledge_fault → clear writer flag) ensures
    # polling does NOT resume until the operator explicitly acknowledges,
    # even if free space recovered earlier (no auto-recovery on flapping).
    writer.set_event_loop(asyncio.get_running_loop())
    writer.set_persistence_failure_callback(safety_manager.on_persistence_failure)
    safety_manager.set_persistence_failure_clear(writer.clear_disk_full)
    persistence_freshness_s = min(
        259_200.0,
        max(1.0, 3.0 * max((config.poll_interval_s for config in driver_configs), default=10.0)),
    )
    try:
        recording_lifecycle_feed = RecordingLifecycleFeed(
            writer,
            persistence_freshness_s=persistence_freshness_s,
        )
    except Exception as exc:  # noqa: BLE001 - observational bridge is fail-dark
        logger.warning(
            "Engine boot degraded; owner=recording_lifecycle_feed exception=%s",
            type(exc).__name__,
        )
        recording_lifecycle_feed = RecordingLifecycleFeed()

    # H.6: wire safety fault → operator_log machine event. Dependencies that
    # are created later are filled on this stable context before manager start.
    _alarm_dispatch_tasks: set[asyncio.Task[Any]] = set()
    safety_fault_context = _SafetyFaultLogContext(
        writer=writer,
        broker=broker,
        alarm_dispatch_tasks=_alarm_dispatch_tasks,
    )
    safety_manager._fault_log_callback = functools.partial(
        _safety_fault_log_callback,
        context=safety_fault_context,
    )

    # Calibration acquisition — continuous SRDG during calibration experiments
    calibration_acquisition = CalibrationAcquisitionService(
        writer,
        channel_manager=get_channel_manager(),
    )

    # Планировщик — публикует в ОБА брокера, пишет на диск ДО публикации
    scheduler = Scheduler(
        broker,
        safety_broker=safety_broker,
        sqlite_writer=writer,
        adaptive_throttle=adaptive_throttle,
        calibration_acquisition=calibration_acquisition,
        reviewed_source_connect_begin=safety_manager.begin_reviewed_source_connect,
        reviewed_source_connect_complete=safety_manager.complete_reviewed_source_connect,
        reviewed_source_uncertain=safety_manager.mark_reviewed_source_uncertain,
        reviewed_source_connect_abandon=safety_manager.abandon_reviewed_source_connect,
        reviewed_source_disconnect=safety_manager.disconnect_reviewed_source,
        drain_timeout_s=safety_manager._config.scheduler_drain_timeout_s,
        persistence_commit_observer=recording_lifecycle_feed.persistence_committed,
        persistence_rejection_observer=recording_lifecycle_feed.persistence_rejected,
        persistence_ambiguity_observer=recording_lifecycle_feed.persistence_ambiguous,
        failed_poll_persistence_handler=safety_manager.on_failed_poll_persistence_failure,
        failed_poll_persistence_recovery_handler=safety_manager.on_failed_poll_persistence_recovered,
    )
    for cfg in driver_configs:
        scheduler.add(cfg)

    # ZMQ PUB
    # F35 D4: only the ZMQ publisher path opts in to the descriptor envelope
    # companion — every other subscriber (writer, alarms, safety broker,
    # sound-carrier, assistant relay) stays on the default bare-Reading path.
    zmq_queue = await broker.subscribe(
        "zmq_publisher",
        wants_descriptor_envelope=True,
        required_publisher=True,
    )
    zmq_pub = ZMQPublisher()

    # Interlock Engine — действия делегируются SafetyManager.
    # The actions-dict callables are kept as no-ops for
    # backwards compatibility with InterlockEngine's required interface, but
    # the REAL safety routing happens via trip_handler which receives the
    # full (condition, reading) context. Without this the action name and
    # channel would be discarded and stop_source would behave as emergency_off.
    interlock_actions: dict[str, Any] = {
        "emergency_off": _interlock_noop,
        "stop_source": _interlock_noop,
    }

    interlock_handler_context = _InterlockHandlerContext(
        safety_manager=safety_manager,
        alarm_dispatch_tasks=_alarm_dispatch_tasks,
        dead_channel_alarm_sent=set(),
    )

    interlock_engine = InterlockEngine(
        broker,
        actions=interlock_actions,
        trip_handler=functools.partial(
            _interlock_trip_handler,
            context=interlock_handler_context,
        ),
        dead_channel_handler=functools.partial(
            _interlock_dead_channel_handler,
            context=interlock_handler_context,
        ),
        dead_channel_recovery_handler=functools.partial(
            _interlock_dead_channel_recovery_handler,
            context=interlock_handler_context,
        ),
    )
    _log_physical_policy_receipt(
        "interlocks",
        interlock_engine.load_config(
            interlocks_cfg,
            snapshot=interlocks_snapshot,
            descriptor_catalog=live_descriptor_catalog,
            poll_intervals_s_by_instrument={config.driver.name: config.poll_interval_s for config in driver_configs},
        ),
    )

    # ExperimentManager
    experiment_manager = ExperimentManager(
        data_dir=_DATA_DIR,
        instruments_config=instruments_cfg,
        templates_dir=_CONFIG_DIR / "experiment_templates",
    )
    try:
        _seed_recording_lifecycle(recording_lifecycle_feed, experiment_manager)
    except Exception as exc:  # noqa: BLE001 - dark presentation cannot block engine boot
        logger.warning(
            "Engine boot degraded; owner=recording_lifecycle_seed exception=%s",
            type(exc).__name__,
        )
    acquisition_lifecycle_sequence = 0

    # F31: sinks foundation (vault + webhooks). Local override beats base.
    from cryodaq.sinks import SinkRegistry  # local import keeps engine cold-start fast

    _sink_cfg_path = _CONFIG_DIR / "sinks.local.yaml"
    if not _sink_cfg_path.exists():
        _sink_cfg_path = _CONFIG_DIR / "sinks.yaml"
    sink_registry = SinkRegistry()
    sink_registry.load_config(_sink_cfg_path)

    event_bus = EventBus()
    safety_fault_context.event_bus = event_bus
    safety_fault_context.experiment_manager = experiment_manager
    interlock_handler_context.event_bus = event_bus
    interlock_handler_context.experiment_manager = experiment_manager
    # A3b: engine-side ring buffer of alarm_fired events for the GUI's
    # recent_alarms poll (sound) — see _alarm_ring_feed()/_AlarmRingBuffer.
    _alarm_ring = _AlarmRingBuffer()
    event_logger = EventLogger(writer, experiment_manager, event_bus=event_bus)

    # --- F13: Leak rate estimator ---
    _instruments_raw = yaml.safe_load(instruments_cfg.read_text(encoding="utf-8"))
    _chamber_cfg = _instruments_raw.get("chamber", {})
    _leak_cfg = _chamber_cfg.get("leak_rate", {})
    leak_rate_estimator = LeakRateEstimator(
        chamber_volume_l=float(_chamber_cfg.get("volume_l", 0.0)),
        sample_window_s=float(_leak_cfg.get("default_sample_window_s", 300.0)),
        data_dir=_DATA_DIR,
    )
    _leak_warn = _leak_rate_volume_warning(_chamber_cfg)
    if _leak_warn:
        logger.warning(_leak_warn)

    # --- Alarm Engine v2 ---
    _alarms_v3_cfg = _CONFIG_DIR / "alarms_v3.yaml"
    _alarm_v2_engine_cfg, _alarm_v2_configs = load_alarm_config(_alarms_v3_cfg)
    _alarm_v2_state_tracker = ChannelStateTracker(
        stale_timeout_s=30.0,
        fault_window_s=300.0,
    )
    _alarm_v2_rate = RateEstimator(
        window_s=_alarm_v2_engine_cfg.rate_window_s,
        min_points=_alarm_v2_engine_cfg.rate_min_points,
    )
    _alarm_v2_phase = ExperimentPhaseProvider(experiment_manager)
    _alarm_v2_setpoint = ExperimentSetpointProvider(experiment_manager, _alarm_v2_engine_cfg.setpoints)
    alarm_v2_evaluator = AlarmEvaluator(_alarm_v2_state_tracker, _alarm_v2_rate, _alarm_v2_phase, _alarm_v2_setpoint)
    alarm_v2_state_mgr = AlarmStateManager()
    zmq_pub.configure_periodic_authority(
        reading_drop_count=functools.partial(_zmq_publisher_drop_count, broker),
        alarm_snapshot=alarm_v2_state_mgr.snapshot_active_canonical,
    )
    # P2-5: interlock non-usable readings emit alarm-v2 events via the same
    # AlarmStateManager the sensor-diagnostics engine uses (built after the
    # InterlockEngine, so wired here by setter).
    interlock_engine.set_alarm_publisher(alarm_v2_state_mgr)
    if _alarm_v2_configs:
        logger.info("Alarm Engine v2: загружено %d алармов", len(_alarm_v2_configs))
    else:
        # A missing config file now raises AlarmConfigError (fail-closed, aborts
        # the engine), so this branch is reached only when the file exists and
        # parses but defines zero alarms — the message must reflect that.
        logger.info(
            "Alarm Engine v2: config/alarms_v3.yaml не содержит определений алармов — v2-движку нечего оценивать"
        )

    # --- Physical alarms (F-X v3): CooldownAlarm + VacuumGuard ---
    _phys_alarms_yaml = _CONFIG_DIR / "physical_alarms.yaml"
    _cooldown_cfg, _vacuum_cfg, _landmarks = load_production_physical_alarms_config(_phys_alarms_yaml)

    # F-ChannelLandmarks: install hardware-pinned landmark map (Т11/Т12 with
    # operator-phrasing aliases) on the shared ChannelManager. The query
    # agent's IntentClassifier reads it via channel_manager.get_landmarks()
    # to resolve phrases like "азотная плита" to the correct channel even
    # when an experiment-level alias has drifted onto another channel.
    get_channel_manager().set_landmarks(_landmarks)
    logger.info(
        "ChannelLandmarks: загружены для каналов %s",
        ", ".join(sorted(_landmarks)),
    )

    # Resolve model path relative to project root (not process cwd)
    _model_path_str = _cooldown_cfg.get("predictor_model_path", "model/predictor_model.json")
    if not Path(_model_path_str).is_absolute():
        _cooldown_cfg["predictor_model_path"] = str(_PROJECT_ROOT / _model_path_str)

    _cooldown_alarm: CooldownAlarm | None = None
    if _cooldown_cfg.get("enabled", True):
        _cooldown_alarm = CooldownAlarm(
            cfg=_cooldown_cfg,
            state_tracker=_alarm_v2_state_tracker,
            alarm_state_mgr=alarm_v2_state_mgr,
            event_bus=event_bus,
            # v0.55.12 — wire SafetyManager so CooldownAlarm CRITICAL
            # latches the safety FSM.
            safety_manager=safety_manager,
        )
        logger.info("CooldownAlarm: инициализирован (DISARMED по умолчанию)")
    else:
        logger.info("CooldownAlarm: отключён в конфиге")

    _vacuum_guard: VacuumGuard | None = None
    if _vacuum_cfg.get("enabled", True):
        try:
            _vacuum_guard = VacuumGuard(
                cfg=_vacuum_cfg,
                state_tracker=_alarm_v2_state_tracker,
                alarm_state_mgr=alarm_v2_state_mgr,
                event_bus=event_bus,
                # Opt-in (external safety review, HIGH): wire SafetyManager so a
                # FIRED vacuum guard latches a fault, not just an alarm. Strict
                # bool, fail-closed like the wdog gate — pass the handle only on
                # an explicit `escalate_to_safety: true`; default keeps None
                # (alarm-only, byte-identical to prior behavior).
                safety_manager=(safety_manager if _vacuum_cfg.get("escalate_to_safety") is True else None),
            )
        except Exception as exc:
            logger.warning(
                "Engine boot degraded: owner=vacuum_guard exception=%s",
                type(exc).__name__,
            )
    else:
        logger.info("VacuumGuard: отключён в конфиге")

    # --- Sensor Diagnostics Engine ---
    _plugins_cfg_path = _engine_config_path("plugins")
    _plugins_raw: dict[str, Any] = {}
    if _plugins_cfg_path.exists():
        with _plugins_cfg_path.open(encoding="utf-8") as fh:
            _plugins_raw = yaml.safe_load(fh) or {}
    _sd_cfg = _plugins_raw.get("sensor_diagnostics", {})
    _sd_enabled = _sd_cfg.get("enabled", False)
    sensor_diag: SensorDiagnosticsEngine | None = None
    if _sd_enabled:
        _ch_mgr = get_channel_manager()
        # Build correlation groups from config; channel ids use display prefix (Т1→T1)
        _sd_alarm_publisher = alarm_v2_state_mgr if _sd_cfg.get("alarm_publishing_enabled", True) else None
        sensor_diag = SensorDiagnosticsEngine(
            config=_sd_cfg,
            alarm_publisher=_sd_alarm_publisher,
            warning_duration_s=float(_sd_cfg.get("warning_duration_s", 300.0)),
            critical_duration_s=float(_sd_cfg.get("critical_duration_s", 900.0)),
            channel_catalog=live_descriptor_catalog.storage_catalog_snapshot(),
        )
        # Set display names from channel_manager
        sensor_diag.set_channel_names({ch_id: _ch_mgr.get_display_name(ch_id) for ch_id in _ch_mgr.get_all()})
        # v0.55.2 A4: tell the engine which channels are cryogenic so warm
        # references (calibration, flange, vacuum case, structural) don't
        # get scored against cryogenic noise/drift thresholds.
        sensor_diag.set_channel_cold_map(
            {ch_id: bool(info.get("is_cold", True)) for ch_id, info in _ch_mgr.get_all().items()}
        )
        logger.info(
            "SensorDiagnostics: enabled, update_interval=%ds, groups=%d, alarm_publishing=%s",
            _sd_cfg.get("update_interval_s", 10),
            len(_sd_cfg.get("correlation_groups", {})),
            _sd_alarm_publisher is not None,
        )
    else:
        logger.info("SensorDiagnostics: отключён (plugins.yaml не найден или enabled=false)")

    # --- Vacuum Trend Predictor ---
    _vt_cfg = _plugins_raw.get("vacuum_trend", {})
    _vt_enabled = _vt_cfg.get("enabled", False)
    vacuum_trend: VacuumTrendPredictor | None = None
    if _vt_enabled:
        vacuum_trend = VacuumTrendPredictor(config=_vt_cfg)
        logger.info(
            "VacuumTrendPredictor: enabled, window=%ds, targets=%s",
            _vt_cfg.get("window_s", 3600),
            _vt_cfg.get("targets_mbar", [1e-4, 1e-5, 1e-6]),
        )
    else:
        logger.info("VacuumTrendPredictor: отключён")

    housekeeping_service = HousekeepingService(
        _DATA_DIR,
        experiment_manager.data_dir / "experiments",
        config=housekeeping_raw.get("retention", {}),
        # F1a: while rotation is enabled, retention must not gzip daily readings
        # DBs — rotation owns their lifecycle, and a .db.gz is invisible to
        # every reader (the day-14 gzip starved the day-30 rotation).
        skip_daily_db_compression=((housekeeping_raw.get("cold_rotation", {}) or {}).get("enabled") is True),
    )

    # Cold rotation: aged daily SQLite → Parquet cold storage, once per day at
    # the configured quiet hour. Fail-closed on a strict `enabled: true`; the
    # matching read side (ArchiveReader) is already threaded into the CSV/XLSX
    # exporters so rotated days stay visible to date-range exports.
    cold_cfg = housekeeping_raw.get("cold_rotation", {}) or {}
    cold_rotation_service = build_cold_rotation_service(
        cold_cfg,
        data_dir=_DATA_DIR,
        project_root=_cold_rotation_project_root(_DATA_DIR),
        # F1c: warns when retention compression is configured to fire before
        # rotation's age_days (starvation hazard; moot for daily DBs with F1a).
        retention_cfg=housekeeping_raw.get("retention", {}),
    )
    # Validate the schedule at build time: seconds_until_next() runs outside the
    # scheduler's per-pass try, so a malformed HH:MM would raise once and kill
    # rotation silently. normalize_schedule_time falls back to 03:00 + ERROR log.
    cold_rotation_schedule = normalize_schedule_time(str(cold_cfg.get("schedule_time", "03:00")))

    # v0.55.11 — auto-stop bookkeeping for multiline.burst_start. The
    # meta dict is populated by the helper (intent); the tasks dict is
    # populated at the dispatch site (materialised on the engine loop).
    _multiline_burst_auto_stop_meta: dict[str, dict[str, Any]] = {}
    _multiline_burst_auto_stop_tasks: dict[str, asyncio.Task[None]] = {}

    command_context = EngineCommandContext(
        safety_manager=safety_manager,
        event_logger=event_logger,
        sink_registry=sink_registry,
        interlock_engine=interlock_engine,
        leak_rate_estimator=leak_rate_estimator,
        leak_cfg=_leak_cfg,
        alarm_v2_state_mgr=alarm_v2_state_mgr,
        alarm_ring=_alarm_ring,
        broker=broker,
        experiment_manager=experiment_manager,
        calibration_acquisition=calibration_acquisition,
        event_bus=event_bus,
        cooldown_alarm=_cooldown_alarm,
        vacuum_guard=_vacuum_guard,
        alarm_dispatch_tasks=_alarm_dispatch_tasks,
        calibration_store=calibration_store,
        writer=writer,
        drivers_by_name=drivers_by_name,
        sensor_diag=sensor_diag,
        vacuum_trend=vacuum_trend,
        alarm_v2_state_tracker=_alarm_v2_state_tracker,
        multiline_burst_auto_stop_meta=_multiline_burst_auto_stop_meta,
        multiline_burst_auto_stop_tasks=_multiline_burst_auto_stop_tasks,
        shutdown_event=shutdown_event,
        engine_instance_id=engine_instance_id,
        shutdown_capability=shutdown_capability,
        engine_ready_nonce=engine_ready_nonce,
        engine_ready_channel_fd=engine_ready_channel_fd,
        engine_ready_pid=os.getpid(),
        zmq_publisher=zmq_pub,
        recording_lifecycle_feed=recording_lifecycle_feed,
        annunciation_registry=AnnunciationRegistry(engine_instance_id=engine_instance_id),
        mutation_capability_token=secrets.token_urlsafe(32),
    )
    handle_gui_command = functools.partial(
        _handle_gui_command,
        context=command_context,
    )

    command_authority_registry = CommandAuthorityRegistry()
    cmd_server = ZMQCommandServer(
        DEFAULT_CMD_ADDR,
        handler=handle_gui_command,
        reply_sent_callback=functools.partial(
            _request_teardown_after_shutdown_receipt,
            command_context,
        ),
        authority_registry=command_authority_registry,
        accepted_command_predicate=is_ordinary_command_endpoint_admitted,
    )
    safe_cmd_server = ZMQCommandServer(
        DEFAULT_SAFE_CMD_ADDR,
        handler=handle_gui_command,
        reply_sent_callback=functools.partial(
            _request_teardown_after_shutdown_receipt,
            command_context,
        ),
        authority_registry=command_authority_registry,
        accepted_actions=frozenset({"engine_ready", "keithley_emergency_off", "launcher_shutdown"}),
        accepted_command_predicate=functools.partial(
            _safe_engine_command_is_admitted,
            context=command_context,
        ),
    )
    command_ingress = ZMQCommandIngressPair(ordinary=cmd_server, safe=safe_cmd_server)

    # Plugin Pipeline
    plugin_pipeline = PluginPipeline(
        broker,
        _PLUGINS_DIR,
        hot_reload=qualification_receipt is None,
        frozen_plugin_digests=plugin_snapshot if qualification_receipt is not None else None,
    )

    # --- CooldownService (прогноз охлаждения) ---
    cooldown_service: Any = None
    if cooldown_cfg_path.exists():
        try:
            _cd_raw, cooldown_receipt = _load_cooldown_config(cooldown_cfg_path)
            _log_physical_policy_receipt("cooldown", cooldown_receipt)
            _cd_cfg = _cd_raw.get("cooldown", {})
            _applied_cold_channel = _cd_cfg.get("channel_cold")
            if isinstance(_applied_cold_channel, str) and _applied_cold_channel.strip():
                zmq_pub.configure_applied_cold_stage_channel(_applied_cold_channel)
            if _cd_cfg.get("enabled", False):
                from cryodaq.analytics.cooldown_service import CooldownService

                cooldown_service = CooldownService(
                    broker=broker,
                    config=_cd_cfg,
                    model_dir=_PROJECT_ROOT / _cd_cfg.get("model_dir", "data/cooldown_model"),
                    # A1: cooldown-end push event on the engine EventBus.
                    event_bus=event_bus,
                    # A2: read-only history reader for ultimate_vacuum enrichment.
                    reader=writer,
                    # P0 fail-open fix (PR2-T3): the same SafetyManager instance
                    # constructed above (line ~6414, "создаётся ПЕРВЫМ") and used
                    # as the engine's sole source authority throughout this
                    # function. CooldownService reports predictor model health
                    # through it in _start_locked(), so a missing/malformed/
                    # zero-curve model blocks request_run() via the existing
                    # SafetyManager._check_preconditions() gate instead of
                    # silently reporting available.
                    safety_manager=safety_manager,
                )
                logger.info("CooldownService создан")
                # v0.55.4 A2: hand the cooldown_service-owned
                # SteadyStatePredictor to CooldownAlarm so its WATCHING
                # path can short-circuit when the system is quasi-steady.
                if _cooldown_alarm is not None:
                    _cooldown_alarm.set_steady_state_predictor(cooldown_service._ss_predictor)
        except Exception as exc:
            logger.error(
                "Engine boot degraded: owner=cooldown_service exception=%s",
                type(exc).__name__,
            )
    command_context.cooldown_service = cooldown_service

    # --- Уведомления (один раз разбираем YAML) ---
    telegram_bot: TelegramCommandBot | None = None
    _photo_handler: CompositionPhotoHandler | None = None
    escalation_service: EscalationService | None = None
    notifications_cfg = _engine_config_path("notifications")
    if notifications_cfg.exists():
        try:
            with notifications_cfg.open(encoding="utf-8") as fh:
                notif_raw: dict[str, Any] = yaml.safe_load(fh) or {}

            tg_cfg = notif_raw.get("telegram", {})
            bot_token = str(tg_cfg.get("bot_token", ""))
            token_valid = bot_token and bot_token != "YOUR_BOT_TOKEN_HERE"
            verify_ssl = bool(tg_cfg.get("verify_ssl", True))

            # TelegramCommandBot
            cmd_cfg = notif_raw.get("commands", {})
            commands_enabled = bool(cmd_cfg.get("enabled", False)) and token_valid
            if commands_enabled:
                allowed_raw = tg_cfg.get("allowed_chat_ids") or cmd_cfg.get("allowed_chat_ids") or []
                allowed_ids = [int(x) for x in allowed_raw]
                # TelegramCommandBot raises on empty list,
                # so refuse to enable cleanly here with a config-error log
                # rather than letting the constructor surface an exception
                # mid-startup.
                if not allowed_ids:
                    logger.error(
                        "Telegram commands are enabled but allowed_chat_ids "
                        "is empty. Refusing to start TelegramCommandBot. "
                        "Add at least one chat ID or set commands.enabled: false."
                    )
                else:
                    telegram_bot = TelegramCommandBot(
                        broker,
                        alarm_v2_state_mgr,
                        bot_token=bot_token,
                        allowed_chat_ids=allowed_ids,
                        poll_interval_s=float(cmd_cfg.get("poll_interval_s", 2.0)),
                        command_handler=handle_gui_command,
                        verify_ssl=verify_ssl,
                    )
                    logger.info(
                        "TelegramCommandBot создан (allowed=%d chat ids)",
                        len(allowed_ids),
                    )

                    # F27 — composition photo handler
                    _photo_handler = CompositionPhotoHandler(
                        bot=telegram_bot,
                        experiment_manager=experiment_manager,
                        channel_manager=get_channel_manager(),
                        event_bus=event_bus,
                    )
                    telegram_bot._photo_handler = _photo_handler
                    logger.info("CompositionPhotoHandler создан")

            # EscalationService
            if token_valid and notif_raw.get("escalation"):
                from cryodaq.notifications.telegram import TelegramNotifier

                _esc_notifier = TelegramNotifier(
                    bot_token=bot_token,
                    chat_id=tg_cfg.get("chat_id", 0),
                    verify_ssl=verify_ssl,
                )
                escalation_service = EscalationService(_esc_notifier, notif_raw)
                logger.info("EscalationService создан (%d уровней)", len(notif_raw["escalation"]))

            if not token_valid:
                logger.info("Telegram-уведомления отключены (bot_token не настроен)")
        except Exception as exc:
            logger.error(
                "Engine boot degraded: owner=notification_config exception=%s",
                type(exc).__name__,
            )
    else:
        logger.info("Файл конфигурации уведомлений не найден: %s", notifications_cfg)
    command_context.escalation_service = escalation_service
    safety_fault_context.telegram_bot = telegram_bot

    # --- B1 (2026-07): Гемма (AssistantLiveAgent), RAG searcher, and
    # AssistantQueryAgent (F30 live chat) all moved to the standalone
    # cryodaq-assistant process (agents/assistant_main.py) — the engine no
    # longer imports agents/ at all. The engine keeps only:
    #  - the events relay below (publishes the EngineEvent types Гемма
    #    reacts to onto the ZMQ "events" topic — see core/zmq_bridge.py);
    #  - a read-only proxy so Telegram free-text chat (previously
    #    ``telegram_bot._query_agent = <in-process AssistantQueryAgent>``)
    #    still resolves, by forwarding to the assistant process's own
    #    REP (:5557) instead of calling an in-process object.
    # See scratchpad/montana/exec/impl_b1.md for the full design.
    if telegram_bot is not None:
        telegram_bot._query_agent = _RemoteAssistantQueryProxy()

    # B1: relay the EngineEvent types the assistant process's
    # AssistantLiveAgent reacts to onto the ZMQ "events" topic (additive —
    # existing GUI subscribers only subscribe to the "readings" topic and
    # never see this). Generic forwarder, not agents/-specific: it does
    # not know what Гемма does with these events, only that these are the
    # event types worth shipping across the process boundary.
    _ASSISTANT_RELAY_EVENT_TYPES = frozenset(
        {
            "alarm_fired",
            "alarm_cleared",
            "experiment_finalize",
            "experiment_stop",
            "experiment_abort",
            "sensor_anomaly_critical",
            "shift_handover_request",
            "periodic_report_request",
        }
    )

    _assistant_relay_queue = await event_bus.subscribe("assistant_zmq_relay", maxsize=1000)

    # --- Запуск всех подсистем ---
    startup = _EngineStartupRollback()
    startup.add(
        "assistant_event_relay_subscription",
        functools.partial(event_bus.unsubscribe, "assistant_zmq_relay"),
    )
    await startup.acquire(
        writer.start_immediate(),
        label="sqlite_writer",
        rollback=writer.stop,
    )
    await startup.acquire(
        safety_manager.start(),
        label="safety_manager",
        rollback=functools.partial(stop_safety_manager_with_hold, safety_manager, logger),
    )
    logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)

    # ─────────────────── Надзор за долгоживущими задачами (A2) ────────────────
    # Каждая долгоживущая задача движка регистрируется в TaskSupervisor. Если её
    # корутина неожиданно падает, done-callback пишет CRITICAL, поднимает
    # оператору тревогу по штатному каналу событий и перезапускает задачу с
    # экспоненц. выдержкой. safety_collect/safety_monitor создаёт SafetyManager;
    # движок надзирает за ними снаружи и после _SAFETY_TASK_MAX_RESTARTS
    # неудачных перезапусков латчит FAULT вместо бесконечного цикла. Политика
    # надзора вынесена в engine_wiring.supervision.TaskSupervisor.
    supervisor = await startup.call(
        functools.partial(
            TaskSupervisor,
            event_bus=event_bus,
            experiment_manager=experiment_manager,
            safety_manager=safety_manager,
            alarm_dispatch_tasks=_alarm_dispatch_tasks,
            logger_=logger,
        )
    )
    startup.add("task_supervisor_restart_authority", supervisor.stop)
    operator_snapshot_service = None
    try:
        operator_snapshot_service = build_operator_snapshot_publication_service(
            safety_owner=safety_manager,
            recording_feed=recording_lifecycle_feed,
            publisher=zmq_pub,
            data_root=_DATA_DIR,
        )
    except Exception as exc:  # noqa: BLE001 - observational publication is fail-dark
        logger.warning(
            "Engine boot degraded; owner=operator_snapshot_publication exception=%s",
            type(exc).__name__,
        )

    # safety_collect/safety_monitor уже созданы SafetyManager.start(); надзираем
    # за ними снаружи, не трогая safety_manager.py. Перезапуск повторно запускает
    # ту же петлю и синхронизирует ссылку в SafetyManager, чтобы stop() и sweep
    # завершения видели живую задачу.
    for _sname, _srole, _sattr in (
        ("safety_collect", "collect", "_collect_task"),
        ("safety_monitor", "monitor", "_monitor_task"),
    ):
        _stask = getattr(safety_manager, _sattr, None)
        if _stask is not None:
            _loop_fn = getattr(safety_manager, f"_{_sname.split('_', 1)[1]}_loop")
            await startup.call(
                functools.partial(
                    supervisor.register,
                    _sname,
                    _stask,
                    _loop_fn,
                    safety_critical=True,
                    on_spawn=functools.partial(_set_safety_task_ref, safety_manager, _srole),
                )
            )

    await startup.call(
        functools.partial(
            install_loop_exception_backstop,
            asyncio.get_running_loop(),
            logger,
        )
    )

    # writer уже запущен через start_immediate() выше
    await startup.acquire(
        zmq_pub.start(zmq_queue),
        label="zmq_publisher",
        rollback=zmq_pub.stop,
    )
    # Keyed operator-log mutations remain unavailable until the complete
    # retained registry is proven and every durable publication intent has
    # been replayed. Cancellation or failure therefore leaves REP unopened.
    # SQLiteWriter already retains its executor owner through cancellation.
    # Await that owner directly so a cancelled startup cannot abandon an outer
    # shield task while rollback concurrently settles the writer.
    command_ingress_recovery = _CommandIngressRecoveryAuthority(
        writer=writer,
        broker=broker,
        engine_instance_id=engine_instance_id,
    )
    await startup.guard(command_ingress_recovery.settle())
    await startup.acquire(
        interlock_engine.start(),
        label="interlock_engine",
        rollback=interlock_engine.stop,
    )
    await startup.acquire(
        plugin_pipeline.start(),
        label="plugin_pipeline",
        rollback=plugin_pipeline.stop,
    )
    if cooldown_service is not None:
        await startup.acquire(
            cooldown_service.start(),
            label="cooldown_service",
            rollback=cooldown_service.stop,
        )
    if telegram_bot is not None:
        await startup.acquire(
            telegram_bot.start(),
            label="telegram_bot",
            rollback=telegram_bot.stop,
        )
    if _photo_handler is not None:
        await startup.acquire(
            _photo_handler.start(),
            label="composition_photo_handler",
            rollback=_photo_handler.stop,
        )
    scheduler_rollback: dict[str, Any] = {
        "attempted": False,
        "sequence": acquisition_lifecycle_sequence,
    }

    startup.add(
        "scheduler",
        functools.partial(
            _rollback_scheduler_startup,
            scheduler,
            recording_lifecycle_feed,
            scheduler_rollback,
        ),
    )
    startup.add(
        "task_supervisor",
        functools.partial(_rollback_supervisor, supervisor),
    )
    # B1: relay EngineEvents to the assistant process over ZMQ (see the
    # wiring comment above _assistant_relay_queue for what this replaces).
    assistant_event_relay_task = await startup.call(
        functools.partial(
            supervisor.spawn,
            "assistant_event_relay",
            functools.partial(
                assistant_event_relay_loop,
                _assistant_relay_queue,
                zmq_pub,
                _ASSISTANT_RELAY_EVENT_TYPES,
            ),
        )
    )
    scheduler_rollback["attempted"] = True
    acquisition_lifecycle_sequence = await startup.guard(
        _start_scheduler_with_recording_feed(
            scheduler,
            recording_lifecycle_feed,
            acquisition_lifecycle_sequence,
        )
    )
    scheduler_rollback["sequence"] = acquisition_lifecycle_sequence
    if operator_snapshot_service is not None:
        await startup.call(
            functools.partial(
                supervisor.spawn,
                "operator_snapshot_publication",
                operator_snapshot_service.run,
            )
        )
        startup.add(
            "operator_snapshot_stop_signal",
            operator_snapshot_service.request_stop,
        )
    throttle_task = await startup.call(
        functools.partial(
            supervisor.spawn,
            "adaptive_throttle_runtime",
            functools.partial(track_runtime_signals, broker, adaptive_throttle),
        )
    )
    alarm_v2_feed_task = await startup.call(
        functools.partial(
            supervisor.spawn,
            "alarm_v2_feed",
            functools.partial(
                alarm_v2_feed_readings,
                broker,
                _alarm_v2_state_tracker,
                _alarm_v2_rate,
            ),
        )
    )
    alarm_ring_task = await startup.call(
        functools.partial(
            supervisor.spawn,
            "alarm_ring_buffer_feed",
            functools.partial(alarm_ring_feed, event_bus, _alarm_ring),
        )
    )
    alarm_v2_tick_task: asyncio.Task | None = None
    if _alarm_v2_configs:
        alarm_v2_tick_task = await startup.call(
            functools.partial(
                supervisor.spawn,
                "alarm_v2_tick",
                functools.partial(
                    alarm_v2_tick,
                    engine_cfg=_alarm_v2_engine_cfg,
                    configs=_alarm_v2_configs,
                    phase_provider=_alarm_v2_phase,
                    evaluator=alarm_v2_evaluator,
                    state_mgr=alarm_v2_state_mgr,
                    broker=broker,
                    telegram_bot=telegram_bot,
                    alarm_dispatch_tasks=_alarm_dispatch_tasks,
                    event_bus=event_bus,
                    experiment_manager=experiment_manager,
                ),
            )
        )

    cooldown_alarm_task: asyncio.Task | None = None
    vacuum_guard_task: asyncio.Task | None = None
    if _cooldown_alarm is not None:
        cooldown_alarm_task = await startup.call(
            functools.partial(
                supervisor.spawn,
                "cooldown_alarm_tick",
                functools.partial(
                    cooldown_alarm_tick_loop,
                    cooldown_cfg=_cooldown_cfg,
                    cooldown_alarm=_cooldown_alarm,
                    state_mgr=alarm_v2_state_mgr,
                    telegram_bot=telegram_bot,
                    alarm_dispatch_tasks=_alarm_dispatch_tasks,
                    event_bus=event_bus,
                    experiment_manager=experiment_manager,
                ),
            )
        )
    if _vacuum_guard is not None:
        vacuum_guard_task = await startup.call(
            functools.partial(
                supervisor.spawn,
                "vacuum_guard_tick",
                functools.partial(
                    vacuum_guard_tick_loop,
                    vacuum_cfg=_vacuum_cfg,
                    vacuum_guard=_vacuum_guard,
                    state_mgr=alarm_v2_state_mgr,
                    telegram_bot=telegram_bot,
                    alarm_dispatch_tasks=_alarm_dispatch_tasks,
                    event_bus=event_bus,
                    experiment_manager=experiment_manager,
                ),
            )
        )

    sd_feed_task: asyncio.Task | None = None
    sd_tick_task: asyncio.Task | None = None
    if sensor_diag is not None:
        sd_feed_task = await startup.call(
            functools.partial(
                supervisor.spawn,
                "sensor_diag_feed",
                functools.partial(sensor_diag_feed, sensor_diag, broker),
            )
        )
        sd_tick_task = await startup.call(
            functools.partial(
                supervisor.spawn,
                "sensor_diag_tick",
                functools.partial(
                    sensor_diag_tick,
                    sensor_diag=sensor_diag,
                    sd_cfg=_sd_cfg,
                    telegram_bot=telegram_bot,
                    alarm_dispatch_tasks=_alarm_dispatch_tasks,
                    event_bus=event_bus,
                    experiment_manager=experiment_manager,
                ),
            )
        )
        # v0.55.5 — anchor the cold-start grace at the moment the feed
        # and tick tasks are actually live. Doing this here (rather than
        # in the constructor) avoids counting the engine bootstrap
        # window as part of the grace.
        await startup.call(sensor_diag.mark_engine_started)
    vt_feed_task: asyncio.Task | None = None
    vt_tick_task: asyncio.Task | None = None
    if vacuum_trend is not None:
        vt_feed_task = await startup.call(
            functools.partial(
                supervisor.spawn,
                "vacuum_trend_feed",
                functools.partial(vacuum_trend_feed, vacuum_trend, _vt_cfg, broker),
            )
        )
        vt_tick_task = await startup.call(
            functools.partial(
                supervisor.spawn,
                "vacuum_trend_tick",
                functools.partial(vacuum_trend_tick, vacuum_trend, _vt_cfg),
            )
        )
    leak_rate_feed_task = await startup.call(
        functools.partial(
            supervisor.spawn,
            "leak_rate_feed",
            functools.partial(
                leak_rate_feed,
                vt_cfg=_vt_cfg,
                broker=broker,
                leak_rate_estimator=leak_rate_estimator,
                event_logger=event_logger,
            ),
        )
    )
    await startup.acquire(
        housekeeping_service.start(),
        label="housekeeping_service",
        rollback=housekeeping_service.stop,
    )

    cold_rotation_task: asyncio.Task | None = None
    if cold_rotation_service is not None:
        cold_rotation_task = await startup.call(
            functools.partial(
                supervisor.spawn,
                "cold_rotation_scheduler",
                functools.partial(
                    cold_rotation_scheduler,
                    cold_rotation_service,
                    cold_rotation_schedule,
                ),
            )
        )
        logger.info(
            "ColdRotationService запущен: archive=%s, age_days=%d, schedule=%s",
            cold_rotation_service._archive_dir,
            cold_rotation_service._age_days,
            cold_rotation_schedule,
        )
    else:
        logger.info("ColdRotationService отключён (cold_rotation.enabled != true)")

    # Watchdog
    watchdog_task = await startup.call(
        functools.partial(
            supervisor.spawn,
            "engine_watchdog",
            functools.partial(_watchdog, broker, scheduler, writer, start_ts),
        )
    )

    # DiskMonitor — also wires the writer so disk-recovery can clear the
    # _disk_full flag (Phase 2a H.1).
    disk_monitor = await startup.call(
        functools.partial(
            DiskMonitor,
            data_dir=_DATA_DIR,
            broker=broker,
            sqlite_writer=writer,
        )
    )
    await startup.acquire(
        disk_monitor.start(),
        label="disk_monitor",
        rollback=disk_monitor.stop,
    )

    startup_summary = await startup.call(
        functools.partial(
            _engine_startup_summary,
            driver_configs,
            _alarm_v2_configs,
            interlock_engine,
        )
    )

    remove_signal_handlers = await startup.call(functools.partial(_install_engine_signal_handlers, shutdown_event))
    startup.add("signal_handlers", remove_signal_handlers)

    # REP is the final startup acquisition. No external command surface exists
    # while any dependency or retained operator-log intent is unsettled.
    command_context.experiment_commands_accepting = False
    await startup.acquire(
        command_ingress_recovery.start(command_ingress),
        label="command_ingress",
        rollback=command_ingress.stop,
    )
    await _commit_engine_command_ingress_startup(
        command_ingress=command_ingress,
        command_context=command_context,
        startup=startup,
    )

    logger.info(
        "═══ CryoDAQ Engine запущен ═══ | приборов=%d | тревог=%d | блокировок=%d | mock=%s",
        *startup_summary,
        mock,
    )

    # --- Ожидание сигнала завершения ---
    ingress_terminal_failure = await _wait_for_engine_shutdown_or_ingress_failure(
        shutdown_event,
        command_ingress,
    )
    teardown_sequence = _EngineTeardownSequence(
        command_ingress=command_ingress,
        safety_manager=safety_manager,
        logger_=logger,
        ingress_terminal_failure=ingress_terminal_failure,
    )

    # --- Корректное завершение ---
    logger.info("═══ Завершение CryoDAQ Engine ═══")

    # Freeze the command ingress before draining retained owners. Stopping the
    # REP task may cancel a reply waiter, but shielded experiment owners remain
    # authoritative and are settled below before any dependent resource stops.
    command_context.experiment_commands_accepting = False
    # A2: гасим надзор до отмены задач — иначе done-callback перезапустит
    # только что отменённую задачу прямо во время завершения.
    supervisor.stop()

    # Synchronously freeze admission, settle every retained command owner, and
    # prove final global OFF. A REP teardown failure/cancellation is retained
    # and retried; it can neither bypass safety nor invalidate OFF later.
    await teardown_sequence.settle_ingress_off()
    logger.info("ZMQ CommandServer остановлен")

    # Build one explicit dependency plan. Owners inside a layer are true peers;
    # layers settle in order so no producer can enqueue behind a completed
    # dispatch drain and no persistence/transport dependency closes early.
    runtime_producer_owners: list[_EngineShutdownOwner] = []
    known_quiesce_tasks: set[asyncio.Task[Any]] = set()
    logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)

    if operator_snapshot_service is not None:
        operator_snapshot_task = supervisor.supervised_tasks.get("operator_snapshot_publication")
        if operator_snapshot_task is not None:
            known_quiesce_tasks.add(operator_snapshot_task)
        runtime_producer_owners.append(
            _EngineShutdownOwner(
                "operator_snapshot_publication",
                functools.partial(
                    _request_and_settle_terminal_task_owner,
                    operator_snapshot_service.request_stop,
                    operator_snapshot_task,
                ),
            )
        )

    terminal_task_specs = (
        ("watchdog_task", watchdog_task),
        ("throttle_task", throttle_task),
        ("alarm_v2_feed_task", alarm_v2_feed_task),
        ("alarm_ring_task", alarm_ring_task),
        ("alarm_v2_tick_task", alarm_v2_tick_task),
        ("sensor_diagnostic_feed_task", sd_feed_task),
        ("sensor_diagnostic_tick_task", sd_tick_task),
        ("cooldown_alarm_task", cooldown_alarm_task),
        ("vacuum_guard_task", vacuum_guard_task),
        ("vacuum_trend_feed_task", vt_feed_task),
        ("vacuum_trend_tick_task", vt_tick_task),
        ("assistant_event_relay_task", assistant_event_relay_task),
        ("leak_rate_feed_task", leak_rate_feed_task),
    )
    for label, task in terminal_task_specs:
        if task is None:
            continue
        known_quiesce_tasks.add(task)
        runtime_producer_owners.append(
            _EngineShutdownOwner(
                label,
                functools.partial(_stop_terminal_task_owner, task),
            )
        )

    # A2: подметаем перезапущенные надзором задачи — их именованные ссылки
    # выше могут указывать на уже мёртвый оригинал, а живой перезапуск висит
    # только в _supervised_tasks. safety_collect/safety_monitor исключаем:
    # их снимает safety_manager.stop() последними (ссылки синхронизированы при
    # перезапуске), чтобы мониторинг безопасности жил до конца завершения.
    for index, (name, task) in enumerate(sorted(supervisor.supervised_tasks.items())):
        if name in {"safety_collect", "safety_monitor"} or task in known_quiesce_tasks or task.done():
            continue
        known_quiesce_tasks.add(task)
        runtime_producer_owners.append(
            _EngineShutdownOwner(
                f"supervised_task_{index}",
                functools.partial(_stop_terminal_task_owner, task),
            )
        )

    shutdown_layers: list[_EngineShutdownLayer] = [
        _EngineShutdownLayer(
            "retained_mutations",
            (
                _EngineShutdownOwner(
                    "retained_command_tasks",
                    functools.partial(
                        _drain_retained_command_tasks_owner,
                        command_context,
                        logger,
                    ),
                ),
            ),
        ),
        _EngineShutdownLayer(
            "scheduler",
            (
                _EngineShutdownOwner(
                    "scheduler",
                    functools.partial(
                        _stop_scheduler_shutdown_owner,
                        scheduler,
                        recording_lifecycle_feed,
                        acquisition_lifecycle_sequence,
                    ),
                ),
            ),
        ),
        _EngineShutdownLayer(
            "plugin_pipeline",
            (_EngineShutdownOwner("plugin_pipeline", plugin_pipeline.stop),),
        ),
    ]
    if runtime_producer_owners:
        shutdown_layers.append(_EngineShutdownLayer("runtime_producers", tuple(runtime_producer_owners)))

    # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
    producer_service_owners: list[_EngineShutdownOwner] = []
    if cooldown_service is not None:
        producer_service_owners.append(_EngineShutdownOwner("cooldown_service", cooldown_service.stop))

    producer_service_owners.append(_EngineShutdownOwner("interlock_engine", interlock_engine.stop))
    producer_service_owners.append(_EngineShutdownOwner("disk_monitor", disk_monitor.stop))
    producer_service_owners.append(_EngineShutdownOwner("housekeeping_service", housekeeping_service.stop))

    if cold_rotation_task is not None:
        producer_service_owners.append(
            _EngineShutdownOwner(
                "cold_rotation_task",
                functools.partial(_stop_terminal_task_owner, cold_rotation_task),
            )
        )

    shutdown_layers.append(_EngineShutdownLayer("producer_services", tuple(producer_service_owners)))
    shutdown_layers.append(
        _EngineShutdownLayer(
            "event_relay_cutover",
            (
                _EngineShutdownOwner(
                    "assistant_event_subscription",
                    functools.partial(event_bus.unsubscribe, "assistant_zmq_relay"),
                ),
            ),
        )
    )
    if _photo_handler is not None:
        shutdown_layers.append(
            _EngineShutdownLayer(
                "composition_photo_handler",
                (_EngineShutdownOwner("composition_photo_handler", _photo_handler.stop),),
            )
        )
    shutdown_layers.append(
        _EngineShutdownLayer(
            "alarm_dispatch_drain",
            (
                _EngineShutdownOwner(
                    "alarm_dispatch_tasks",
                    functools.partial(_drain_dispatch_tasks, _alarm_dispatch_tasks, logger),
                ),
            ),
        )
    )
    if telegram_bot is not None:
        shutdown_layers.append(
            _EngineShutdownLayer(
                "downstream_notifications",
                (_EngineShutdownOwner("telegram_bot", telegram_bot.stop),),
            )
        )

    from cryodaq.drivers.transport.gpib import GPIBTransport

    shutdown_layers.append(
        _EngineShutdownLayer(
            "terminal_dependencies",
            (
                _EngineShutdownOwner("sqlite_writer", writer.stop),
                _EngineShutdownOwner("zmq_publisher", zmq_pub.stop),
                _EngineShutdownOwner("gpib_managers", GPIBTransport.close_all_managers),
                _EngineShutdownOwner("signal_handlers", remove_signal_handlers),
            ),
        )
    )
    await teardown_sequence.settle_plan(tuple(shutdown_layers))
    logger.info("SQLite shutdown settled: total_written=%d", writer.stats.get("total_written", 0))
    teardown_sequence.finalize()

    uptime = time.monotonic() - start_ts
    logger.info(
        "═══ CryoDAQ Engine завершён ═══ | uptime=%.1f с",
        uptime,
    )


# ---------------------------------------------------------------------------
# Single-instance guard
# ---------------------------------------------------------------------------

_LOCK_FILE = get_data_dir() / ".engine.lock"


def _acquire_engine_lock() -> int:
    """Acquire the exclusive engine lock on one persistent lock-file inode.

    Kernel lock ownership is authoritative. Keeping one validated inode at
    the stable path prevents two contenders from holding locks on different
    files after an unlink/recreate race.
    """
    fd = try_acquire_lock(_LOCK_FILE.name, lock_dir=_LOCK_FILE.parent)
    if fd is None:
        logger.error(
            "CryoDAQ engine уже запущен (lock: %s).\n"
            "  Автоматическое завершение процесса без проверяемой инкарнации запрещено.\n"
            "  Завершите подтверждённый процесс через launcher или Диспетчер задач.",
            _LOCK_FILE,
        )
        raise SystemExit(1)
    return fd


def _force_kill_existing() -> None:
    """Refuse unauthenticated termination while tolerating a free stale record.

    A PID and executable name cannot bind a live process to this data-root lock:
    the PID may have been reused, and another CryoDAQ installation has the same
    command line.  Therefore ``--force`` may only prove that no owner exists;
    a held lock requires operator-controlled shutdown of the actual incumbent.
    """

    probe_fd = try_acquire_lock(_LOCK_FILE.name, lock_dir=_LOCK_FILE.parent)
    if probe_fd is not None:
        _release_engine_lock(probe_fd)
        logger.info("Engine lock is free; no forced termination is required")
        return
    logger.error(
        "Refusing unauthenticated forced termination: the engine lock is held "
        "but its owning process incarnation cannot be proven"
    )
    raise SystemExit(1)


def _release_engine_lock(fd: int) -> None:
    # The persistent path is intentionally retained. Closing is the only
    # ownership transition, so no successor-created lock can be deleted in a
    # close/unlink gap and every contender continues to address one inode.
    os.close(fd)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

#: Exit code for unrecoverable startup config errors (Phase 2b H.3).
#: Launcher detects this and refuses to auto-restart.
ENGINE_CONFIG_ERROR_EXIT_CODE = 2

_MOCK_ENV = "CRYODAQ_MOCK"
_MOCK_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_MOCK_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _resolve_mock_mode(*, cli_mock: bool) -> bool:
    """Resolve mock mode once; reject malformed environment configuration."""
    raw = os.environ.get(_MOCK_ENV)
    if raw is None:
        return cli_mock
    normalized = raw.strip().lower()
    if normalized in _MOCK_TRUE_VALUES:
        return True
    if normalized in _MOCK_FALSE_VALUES:
        return cli_mock
    raise ValueError(f"Invalid {_MOCK_ENV}={raw!r}; expected one of 1/true/yes/on or 0/false/no/off")


def main() -> None:
    """Точка входа cryodaq-engine."""
    engine_instance_id, shutdown_capability, engine_ready_nonce, engine_ready_channel_fd = (
        _consume_engine_launch_authority()
    )
    import argparse

    parser = argparse.ArgumentParser(description="CryoDAQ Engine")
    parser.add_argument("--mock", action="store_true", help="Mock mode (simulated instruments)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Proceed only when the engine lock is free; never kill an unauthenticated owner",
    )
    args = parser.parse_args()

    from cryodaq.logging_setup import resolve_log_level, setup_logging

    setup_logging("engine", level=resolve_log_level())

    try:
        mock = _resolve_mock_mode(cli_mock=args.mock)
    except ValueError as exc:
        parser.error(str(exc))

    if args.force:
        _force_kill_existing()

    lock_fd = _acquire_engine_lock()
    try:
        if mock:
            logger.info("Режим MOCK: реальные приборы не используются")
        try:
            if sys.platform == "win32":
                # pyzmq requires a SelectorEventLoop on Windows (the default
                # Proactor loop lacks the socket support pyzmq needs). Force it
                # via Runner(loop_factory=...) rather than the deprecated
                # WindowsSelectorEventLoopPolicy (the policy system is deprecated
                # in Python 3.14+ and warns on import).
                with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                    runner.run(
                        _run_engine(
                            mock=mock,
                            engine_instance_id=engine_instance_id,
                            shutdown_capability=shutdown_capability,
                            engine_ready_nonce=engine_ready_nonce,
                            engine_ready_channel_fd=engine_ready_channel_fd,
                        )
                    )
            else:
                asyncio.run(
                    _run_engine(
                        mock=mock,
                        engine_instance_id=engine_instance_id,
                        shutdown_capability=shutdown_capability,
                        engine_ready_nonce=engine_ready_nonce,
                        engine_ready_channel_fd=engine_ready_channel_fd,
                    )
                )
        except KeyboardInterrupt:
            logger.info("Прервано оператором (Ctrl+C)")
        except yaml.YAMLError as exc:
            # Phase 2b H.3: a YAML parse error during startup is
            # unrecoverable by retry — exit with a distinct code so the
            # launcher refuses to spin in a tight restart loop.
            logger.critical(
                "Engine startup config failed: phase=yaml error=%s",
                exc,
            )
            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
        except FileNotFoundError as exc:
            # Missing required config file at startup is also a config
            # error: same exit code.
            logger.critical(
                "Engine startup config failed: phase=file_missing error=%s",
                exc,
            )
            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
        except (
            SafetyConfigError,
            AlarmConfigError,
            InterlockConfigError,
            HousekeepingConfigError,
            ChannelConfigError,
            ChannelDescriptorStorageError,
            DriverRegistryError,
        ) as exc:
            labels = (
                (SafetyConfigError, "safety"),
                (AlarmConfigError, "alarm"),
                (InterlockConfigError, "interlock"),
                (HousekeepingConfigError, "housekeeping"),
                (ChannelConfigError, "channel"),
                (ChannelDescriptorStorageError, "channel descriptor"),
                (DriverRegistryError, "driver registry"),
            )
            label = next(
                (label for error_type, label in labels if isinstance(exc, error_type)),
                "config",
            )
            logger.critical(
                "CONFIG ERROR (%s config): %s",
                label,
                exc,
            )
            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
    finally:
        _release_engine_lock(lock_fd)


if __name__ == "__main__":
    main()
