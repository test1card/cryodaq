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
import functools
import logging
import math
import os
import secrets
import signal
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from cryodaq.analytics.calibration import CalibrationStore
from cryodaq.analytics.leak_rate import LeakRateEstimator
from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor
from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config
from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmStateManager
from cryodaq.core.broker import DataBroker
from cryodaq.core.calibration_acquisition import (
    CalibrationAcquisitionService,
    CalibrationCommandError,
)
from cryodaq.core.channel_manager import ChannelConfigError, get_channel_manager
from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.core.cooldown_alarm import CooldownAlarm
from cryodaq.core.disk_monitor import DiskMonitor
from cryodaq.core.event_bus import EngineEvent, EventBus
from cryodaq.core.event_logger import EventLogger
from cryodaq.core.experiment import ExperimentManager, ExperimentStatus
from cryodaq.core.housekeeping import (
    AdaptiveThrottle,
    HousekeepingConfigError,
    HousekeepingService,
    load_critical_channels_from_alarms_v3,
    load_housekeeping_config,
    load_protected_channel_patterns,
)
from cryodaq.core.interlock import InterlockConfigError, InterlockEngine
from cryodaq.core.operator_log import OperatorLogEntry
from cryodaq.core.path_jail import resolve_within
from cryodaq.core.physical_alarms_config import (
    load_channel_landmarks,
    load_physical_alarms_config,
)
from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager
from cryodaq.core.safety_pattern_liveness import (
    SafetyPatternLivenessError,
    validate_safety_pattern_liveness,
)
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine
from cryodaq.core.smu_channel import normalize_smu_channel
from cryodaq.core.vacuum_guard import VacuumGuard
from cryodaq.core.zmq_bridge import (
    PERIODIC_BARRIER_SCHEMA,
    PERIODIC_QUERY_SCHEMA,
    ZMQCommandServer,
    ZMQPublisher,
    encode_periodic_command_reply,
)
from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.drivers.contracts import ControlledSource, VerifiedOffSource
from cryodaq.drivers.registry import (
    KEITHLEY_2604B_SOURCE_BINDING,
    REVIEWED_SOURCE_SPECS,
    DriverConstructionContext,
    DriverRegistryError,
    ReviewedSourceBinding,
    ValidatedInstrumentConfig,
    construct_driver,
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
)
from cryodaq.notifications.composition_photo_handler import CompositionPhotoHandler
from cryodaq.notifications.escalation import EscalationService
from cryodaq.notifications.telegram_commands import TelegramCommandBot
from cryodaq.paths import get_config_dir, get_data_dir, get_project_root
from cryodaq.report_process import ReportProcessError, ReportProcessRunner
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog
from cryodaq.storage.cold_rotation import build_cold_rotation_service, normalize_schedule_time
from cryodaq.storage.sqlite_writer import SQLiteWriter

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
        except (TypeError, ValueError, OverflowError) as exc:
            return {"ok": False, "channel": smu_channel, "error": str(exc)}
        return await safety_manager.request_run(p, v, i, channel=smu_channel)

    if action == "keithley_stop":
        smu_channel = normalize_smu_channel(channel)
        return await safety_manager.request_stop(channel=smu_channel)

    if action == "keithley_emergency_off":
        smu_channel = normalize_smu_channel(channel)
        return await safety_manager.emergency_off(channel=smu_channel)

    if action == "keithley_set_target":
        smu_channel = normalize_smu_channel(cmd.get("channel"))
        try:
            p = _coerce_finite_setpoint(cmd.get("p_target", 0), "p_target")
        except (TypeError, ValueError, OverflowError) as exc:
            return {"ok": False, "channel": smu_channel, "error": str(exc)}
        return await safety_manager.update_target(p, channel=smu_channel)

    if action == "keithley_set_limits":
        smu_channel = normalize_smu_channel(cmd.get("channel"))
        try:
            v = _coerce_finite_setpoint(cmd["v_comp"], "v_comp") if cmd.get("v_comp") is not None else None
            i = _coerce_finite_setpoint(cmd["i_comp"], "i_comp") if cmd.get("i_comp") is not None else None
        except (TypeError, ValueError, OverflowError) as exc:
            return {"ok": False, "channel": smu_channel, "error": str(exc)}
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
            "F31: metadata.json read failed (%s): %s",
            meta_path.parent.name,
            exc,
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


async def _run_operator_log_command(
    action: str,
    cmd: dict[str, Any],
    writer: SQLiteWriter,
    experiment_manager: ExperimentManager,
    broker: DataBroker | None = None,
) -> dict[str, Any]:
    if action == "log_entry":
        message = str(cmd.get("message", "")).strip()
        if not message:
            raise ValueError("Operator log message must not be empty.")

        experiment_id = cmd.get("experiment_id")
        if experiment_id is None and cmd.get("current_experiment", True):
            experiment_id = experiment_manager.active_experiment_id

        entry = await writer.append_operator_log(
            message=message,
            author=str(cmd.get("author", "")).strip(),
            source=str(cmd.get("source", "")).strip() or "command",
            experiment_id=str(experiment_id) if experiment_id is not None else None,
            tags=cmd.get("tags"),
            timestamp=_parse_log_time(cmd.get("timestamp")),
        )
        await _publish_operator_log_entry(broker, entry)
        return {"ok": True, "entry": entry.to_payload()}

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
            return f"🤖 Гемма: ассистент недоступен ({exc})."
        finally:
            sock.close(linger=0)
        if reply.get("ok"):
            return str(reply.get("response", ""))
        return str(reply.get("error", "Ассистент вернул ошибку."))


def _assistant_process_unavailable_reply(action: str) -> dict[str, Any]:
    """B1: Гемма/RAG moved out of the engine into the standalone
    ``cryodaq-assistant`` process (own REP at ``tcp://127.0.0.1:5557``).

    The GUI's ZMQ bridge subprocess routes ``assistant.*`` / ``rag.*``
    actions directly to that port now (see ``core/zmq_subprocess.py``),
    so this engine-side handler should not normally be hit. It exists as
    a backward-compat safety net — an old bridge build, or any other
    client still pointed at the engine's REP (:5556) for these actions —
    gets a clear redirect message instead of "unknown command".
    """
    return {
        "ok": False,
        "error": (
            f"'{action}' обслуживается процессом cryodaq-assistant "
            "(tcp://127.0.0.1:5557), а не engine. Убедитесь, что ассистент "
            "запущен, и что GUI подключается к его порту."
        ),
    }


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
            return {"ok": False, "error": str(exc)}
    if action == "leak_rate_stop":
        try:
            from dataclasses import asdict as _asdict  # noqa: PLC0415

            result = leak_rate_estimator.finalize()
            await event_logger.log_event(
                "leak_rate",
                f"Leak rate: {result.leak_rate_mbar_l_per_s:.3e} mbar·L/s",
            )
            return {"ok": True, "action": "leak_rate_stop", "measurement": _asdict(result)}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
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
    if tasks:
        logger_.info(
            "Draining %d in-flight dispatch task(s) before shutdown",
            len(tasks),
        )
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        except TimeoutError:
            logger_.warning(
                "Sink drain timed out (%ss); cancelling %d remaining",
                timeout,
                len(tasks),
            )
            for t in tasks:
                t.cancel()


# ───────────────────────── Task supervision (A2) ──────────────────────────
# Политика надзора (TaskSupervisor + решающее ядро
# _handle_supervised_task_exit + константы бэкоффа) вынесена в
# engine_wiring.supervision и импортируется выше. Тихая смерть долгоживущей
# задачи — риск №1 в ночную смену; ядро тестируется в изоляции.


# ─────────────────────────── Audible faults (A3) ──────────────────────────
# Safety faults and a dead sensor outside RUNNING used to be log-only — an
# operator had to be staring at the log to notice. The helpers below reuse
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
    """Once-per-episode edge-trigger for the outside-RUNNING dead-channel alert.

    ``on_interlock_dead_channel`` stays log-only outside RUNNING by design
    (SafetyManager's decision, unchanged) and — also by design — is retried
    on every subsequent non-usable sample so the fault still latches the
    moment RUNNING begins (see interlock.py's ``_NonUsableWindow.escalated``
    docstring). Dispatching sound on every one of those retries would beep
    on every poll; fire at most once per continuous decline episode, and
    clear once escalation succeeds (RUNNING began / fault latched — that
    path gets its own CRITICAL alarm via ``_safety_fault_log_callback``) so
    a later, distinct dead episode still alerts.
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
        return {"ok": False, "error": f"MultiLine driver '{name}' not found"}

    try:
        applied = await driver.reconfigure_channels(channels)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — surface the message to GUI
        logger.error(
            "multiline.set_channels reconfigure failed for '%s': %s",
            name,
            exc,
            exc_info=True,
        )
        return {"ok": False, "error": f"reconfigure failed: {exc}"}

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
            "multiline.set_channels persist failed for '%s': %s — "
            "change is runtime-only and will revert on engine restart",
            name,
            exc,
        )
        persist_warning = f"persist failed: {exc}"

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
            "error": f"MultiLine driver '{name}' не сконфигурирован.",
        }

    if action == "multiline.burst_status":
        try:
            return {"ok": True, **driver.burst_status()}
        except Exception as exc:  # noqa: BLE001
            logger.error("multiline.burst_status error: %s", exc, exc_info=True)
            return {"ok": False, "error": str(exc)}

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
        except RuntimeError as exc:
            return {"ok": False, "error": str(exc)}
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
            logger.error("multiline.burst_stop error: %s", exc, exc_info=True)
            return {"ok": False, "error": str(exc)}
        if path is None:
            return {"ok": True, "path": None, "saved": False}
        if auto_stop_tasks is not None:
            auto_stop_tasks.pop(name, None)
        return {"ok": True, "path": str(path), "saved": True}

    return {"ok": False, "error": f"unknown burst action: {action}"}


# B1 (2026-07): the rag.rebuild_index state machine + bootstrap-on-empty
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
    except CalibrationCommandError as e:
        logger.error("Calibration activation rejected: %s", e)
    except Exception:
        logger.warning("Failed to activate calibration acquisition", exc_info=True)


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
        phase = str(cmd.get("phase", "")).strip()
        operator = str(cmd.get("operator", "")).strip()
        entry = experiment_manager.advance_phase(phase, operator)
        return {"ok": True, "phase": entry}

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
                    "Не удалось вычислить elapsed_in_phase_s из started_at=%r: %s — возвращаю 0.0 (display-only)",
                    history[-1].get("started_at"),
                    exc,
                )
        return {
            "ok": True,
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
    from cryodaq.analytics.calibration_fitter import CalibrationFitter

    fitter = CalibrationFitter()
    if action == "calibration_v2_extract":
        pairs = fitter.extract_pairs(
            _DATA_DIR,
            float(cmd.get("start_ts", 0)),
            float(cmd.get("end_ts", 0)),
            str(cmd["reference_channel"]),
            str(cmd["target_channel"]),
        )
        return {"ok": True, "pair_count": len(pairs), "pairs_sample": pairs[:20]}
    if action == "calibration_v2_coverage":
        pairs = fitter.extract_pairs(
            _DATA_DIR,
            float(cmd.get("start_ts", 0)),
            float(cmd.get("end_ts", 0)),
            str(cmd["reference_channel"]),
            str(cmd["target_channel"]),
        )
        coverage = fitter.compute_coverage(pairs)
        return {"ok": True, "coverage": coverage, "total_points": len(pairs)}
    if action == "calibration_v2_fit":
        result = fitter.fit(
            _DATA_DIR,
            float(cmd.get("start_ts", 0)),
            float(cmd.get("end_ts", 0)),
            str(cmd["reference_channel"]),
            str(cmd["target_channel"]),
            calibration_store,
        )
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

    canonical_source_spec = REVIEWED_SOURCE_SPECS["keithley_2604b"]
    reviewed_configs = tuple(config for config in validated if config.spec is canonical_source_spec)
    if len(reviewed_configs) > 1:
        names = ", ".join(config.name for config in reviewed_configs)
        raise DriverRegistryError(
            f"{config_path}: instruments define multiple reviewed sources ({names}); "
            "SafetyManager supports exactly zero or one"
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

        if config.spec is canonical_source_spec:
            binding = config.spec.reviewed_source_binding
            if (
                binding is not KEITHLEY_2604B_SOURCE_BINDING
                or not isinstance(driver, ControlledSource)
                or not isinstance(driver, VerifiedOffSource)
            ):
                raise DriverRegistryError(
                    f"{config_path}: instruments[{index}] ({config.name!r}, "
                    "type 'keithley_2604b') violates the reviewed source contract"
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


def _set_safety_task_ref(safety_manager: Any, attr: str, task: asyncio.Task[Any]) -> None:
    """on_spawn-хук для safety_collect/safety_monitor: синхронизирует ссылку на
    перезапущенную задачу в SafetyManager, чтобы stop() и sweep завершения
    видели живую задачу (раньше — вложенная lambda в _run_engine)."""
    setattr(safety_manager, attr, task)


def _engine_config_path(name: str) -> Path:
    """Resolve a config, preferring the machine-local override."""
    local = _CONFIG_DIR / f"{name}.local.yaml"
    return local if local.exists() else _CONFIG_DIR / f"{name}.yaml"


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
        logger.error("Failed to publish safety fault operator_log entry: %s", exc)

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
        logger.error("Failed to dispatch safety fault alarm/telegram: %s", exc)


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
            "INTERLOCK trip_handler FAILED for '%s' (action=%s): %s — escalating to guaranteed fault.",
            condition.name,
            condition.action,
            exc,
            exc_info=True,
        )
        try:
            await context.safety_manager.latch_fault(
                reason=f"Interlock trip_handler failed: {condition.name}: {exc}",
                source="interlock",
                channel=reading.channel,
                value=float(reading.value) if reading.value is not None else 0.0,
            )
        except Exception as exc2:
            logger.critical(
                "INTERLOCK escalation _fault FAILED for '%s': %s — "
                "instrument state UNKNOWN, immediate operator intervention!",
                condition.name,
                exc2,
                exc_info=True,
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
            "INTERLOCK dead_channel_handler FAILED for '%s' channel '%s': %s — escalating to guaranteed fault.",
            condition.name,
            reading.channel,
            exc,
            exc_info=True,
        )
        try:
            await context.safety_manager.latch_fault(
                reason=f"Interlock dead_channel handler failed: {condition.name}: {exc}",
                source="interlock",
                channel=reading.channel,
            )
            return True
        except Exception as exc2:
            logger.critical(
                "INTERLOCK dead-channel escalation _fault FAILED for '%s': %s",
                condition.name,
                exc2,
                exc_info=True,
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
                "Dead-channel audible dispatch failed for '%s': %s",
                reading.channel,
                exc,
            )
    return escalated


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
                "MultiLine '%s' auto-stop failed: %s",
                driver_name,
                exc,
                exc_info=True,
            )
    finally:
        auto_stop_tasks.pop(driver_name, None)


def _request_shutdown(shutdown_event: asyncio.Event, *_signal_args: Any) -> None:
    logger.info("Получен сигнал завершения")
    shutdown_event.set()


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
    escalation_service: Any = None
    cooldown_service: Any = None
    zmq_publisher: ZMQPublisher | None = None
    recording_lifecycle_feed: RecordingLifecycleFeed | None = None


def _feed_recording_experiment_lifecycle(
    context: EngineCommandContext,
    action: str,
    result: dict[str, Any],
) -> None:
    """Reflect an already-committed experiment result into the dark feed."""

    feed = context.recording_lifecycle_feed
    if feed is None:
        return
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
            return

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
        logger.warning("Recording lifecycle feed unavailable after %s: %s", action, exc, exc_info=True)


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
        logger.warning("Recording persistence feed unavailable before scheduler start: %s", exc, exc_info=True)
        try:
            feed.persistence_ambiguous()
        except Exception as terminal_exc:  # noqa: BLE001 - observational bridge is fail-dark
            logger.warning("Recording persistence feed could not be terminalized: %s", terminal_exc, exc_info=True)
    try:
        await scheduler.start()
    except BaseException:
        try:
            feed.persistence_ambiguous()
        except Exception as exc:  # noqa: BLE001 - preserve the scheduler failure
            logger.warning("Recording persistence feed unavailable after scheduler failure: %s", exc, exc_info=True)
        sequence += 1
        try:
            feed.acquisition_unavailable(sequence)
        except Exception as exc:  # noqa: BLE001 - preserve the scheduler failure
            logger.warning("Recording acquisition feed unavailable after scheduler failure: %s", exc, exc_info=True)
        raise
    sequence += 1
    try:
        feed.acquisition_running(sequence, epoch_id)
    except Exception as exc:  # noqa: BLE001 - observational bridge is fail-dark
        logger.warning("Recording acquisition feed unavailable after scheduler start: %s", exc, exc_info=True)
    return sequence


async def _stop_scheduler_with_recording_feed(
    scheduler: Scheduler,
    feed: RecordingLifecycleFeed,
    sequence: int,
) -> int:
    try:
        await scheduler.stop()
    except BaseException:
        try:
            feed.persistence_ambiguous()
        except Exception as exc:  # noqa: BLE001 - preserve the scheduler failure
            logger.warning("Recording persistence feed unavailable after scheduler failure: %s", exc, exc_info=True)
        sequence += 1
        try:
            feed.acquisition_unavailable(sequence)
        except Exception as exc:  # noqa: BLE001 - preserve the scheduler failure
            logger.warning("Recording acquisition feed unavailable after scheduler failure: %s", exc, exc_info=True)
        raise
    sequence += 1
    try:
        feed.acquisition_stopped(sequence)
    except Exception as exc:  # noqa: BLE001 - observational bridge is fail-dark
        logger.warning("Recording acquisition feed unavailable after scheduler stop: %s", exc, exc_info=True)
        sequence += 1
        try:
            feed.acquisition_unavailable(sequence)
        except Exception as terminal_exc:  # noqa: BLE001 - observational bridge is fail-dark
            logger.warning("Recording acquisition feed could not be terminalized: %s", terminal_exc, exc_info=True)
    try:
        feed.persistence_stopped()
    except Exception as exc:  # noqa: BLE001 - observational bridge is fail-dark
        logger.warning("Recording persistence feed unavailable after scheduler stop: %s", exc, exc_info=True)
        try:
            feed.persistence_ambiguous()
        except Exception as terminal_exc:  # noqa: BLE001 - observational bridge is fail-dark
            logger.warning("Recording persistence feed could not be terminalized: %s", terminal_exc, exc_info=True)
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
    try:
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
            return {"ok": True, **safety_manager.get_status()}
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
            except KeyError as exc:
                return {"ok": False, "error": str(exc)}
        _leak_resp = await _handle_leak_rate_command(action, cmd, leak_rate_estimator, _leak_cfg, event_logger)
        if _leak_resp is not None:
            return _leak_resp
        if action == "alarm_v2_status":
            active = alarm_v2_state_mgr.get_active()
            return {
                "ok": True,
                "active": {
                    k: {
                        "level": v.level,
                        "message": v.message,
                        "triggered_at": v.triggered_at,
                        "channels": v.channels,
                        "acknowledged": v.acknowledged,
                        "acknowledged_at": v.acknowledged_at,
                        "acknowledged_by": v.acknowledged_by,
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
            name = cmd.get("alarm_name", "")
            operator = cmd.get("operator", "")
            reason = cmd.get("reason", "")
            ack_event = alarm_v2_state_mgr.acknowledge(
                name,
                operator=operator,
                reason=reason,
            )
            if ack_event is not None:
                await broker.publish(
                    Reading(
                        timestamp=datetime.now(UTC),
                        instrument_id="alarm_v2",
                        channel="alarm_v2/acknowledged",
                        value=ack_event["acknowledged_at"],
                        unit="",
                        metadata=ack_event,
                    )
                )
            return {
                "ok": ack_event is not None or name in alarm_v2_state_mgr.get_active(),
                "alarm_name": name,
                "event_emitted": ack_event is not None,
            }
        if action in {
            "get_app_mode",
            "set_app_mode",
            "experiment_templates",
            "experiment_status",
            "experiment_archive_list",
            "experiment_list_archive",
            "experiment_start",
            "experiment_create",
            "experiment_get_active",
            "experiment_update",
            "experiment_finalize",
            "experiment_stop",
            "experiment_abort",
            "experiment_get_archive_item",
            "experiment_attach_run_record",
            "experiment_create_retroactive",
            "experiment_generate_report",
            "experiment_advance_phase",
            "experiment_phase_status",
        }:
            experiment_call = asyncio.to_thread(
                _run_experiment_command,
                action,
                cmd,
                experiment_manager,
            )
            if action == "experiment_status":
                # NOTE: asyncio.wait_for on an asyncio.to_thread() call times out the AWAIT,
                # not the worker thread. If get_status_payload() is pathologically slow, the
                # background thread keeps running until it returns naturally. This is an
                # accepted residual risk — REP is still protected by the outer 2.0s handler
                # timeout envelope in ZMQCommandServer._run_handler(); this inner 1.5s wrapper
                # only gives faster client feedback and frees the REP loop earlier. There is
                # no safe way to terminate a Python thread mid-call, so Option C
                # ("actually interrupt") is not available.
                try:
                    result = await asyncio.wait_for(
                        experiment_call,
                        timeout=_EXPERIMENT_STATUS_TIMEOUT_S,
                    )
                except TimeoutError as exc:
                    raise TimeoutError(f"experiment_status timeout ({_EXPERIMENT_STATUS_TIMEOUT_S:g}s)") from exc
            else:
                result = await experiment_call
            if result.get("ok") and action in {
                "experiment_start",
                "experiment_create",
                "experiment_update",
                "experiment_finalize",
                "experiment_stop",
                "experiment_abort",
                "experiment_advance_phase",
            }:
                _feed_recording_experiment_lifecycle(context, action, result)
            # Hook calibration acquisition on experiment lifecycle
            if result.get("ok") and action in {"experiment_start", "experiment_create"}:
                await asyncio.to_thread(
                    _try_activate_calibration_acquisition,
                    calibration_acquisition,
                    experiment_manager,
                    cmd,
                )
                name = cmd.get("name") or cmd.get("title") or "?"
                await event_logger.log_event("experiment", f"Эксперимент начат: {name}")
                await event_bus.publish(
                    EngineEvent(
                        event_type="experiment_start",
                        timestamp=datetime.now(UTC),
                        payload={"name": name, "experiment_id": result.get("experiment_id")},
                        experiment_id=result.get("experiment_id"),
                    )
                )
            elif result.get("ok") and action in {
                "experiment_finalize",
                "experiment_stop",
                "experiment_abort",
            }:
                calibration_acquisition.deactivate()
                if action == "experiment_abort":
                    await event_logger.log_event("experiment", "\u26a0 Эксперимент прерван")
                else:
                    await event_logger.log_event("experiment", "Эксперимент завершён")
                _exp_info = result.get("experiment", {})
                await event_bus.publish(
                    EngineEvent(
                        event_type=action,
                        timestamp=datetime.now(UTC),
                        payload={"action": action, "experiment": _exp_info},
                        experiment_id=_exp_info.get("experiment_id"),
                    )
                )
                if _cooldown_alarm is not None:
                    _cooldown_alarm.notify_experiment_finalized()

                # F31: dispatch experiment export to sinks (fire-and-forget,
                # strong-ref against GC via _alarm_dispatch_tasks).
                if sink_registry.sinks:
                    try:
                        _exp_id = _exp_info.get("experiment_id") or ""
                        _metadata: dict = {}
                        if _exp_id:
                            _meta_path = experiment_manager.data_dir / "experiments" / _exp_id / "metadata.json"
                            # H2: offload metadata read to thread.
                            _metadata = await asyncio.to_thread(_load_experiment_metadata_sync, _meta_path)
                        # F31 H1: build the sink export via the extracted
                        # helper — summary comes from the canonical
                        # "summary_metadata" metadata key, not the empty
                        # bare "summary" key.
                        _export = _build_experiment_export(_exp_info, _metadata)
                        _t = asyncio.create_task(
                            sink_registry.dispatch(_export),
                            name=f"sinks_dispatch_{(_exp_id or 'noid')[:8]}",
                        )
                        _alarm_dispatch_tasks.add(_t)
                        _t.add_done_callback(_alarm_dispatch_tasks.discard)
                    except Exception as _exc:  # noqa: BLE001 — fire-and-forget
                        logger.warning("F31: sink dispatch setup failed: %s", _exc, exc_info=True)
            elif result.get("ok") and action == "experiment_advance_phase":
                phase = cmd.get("phase", "?")
                await event_logger.log_event("phase", f"Фаза: → {phase}")
                _active = experiment_manager.active_experiment
                await event_bus.publish(
                    EngineEvent(
                        event_type="phase_transition",
                        timestamp=datetime.now(UTC),
                        payload={"phase": phase, "entry": result.get("phase", {})},
                        experiment_id=_active.experiment_id if _active else None,
                    )
                )
                # v0.55.12 — feed every phase transition into the
                # CooldownAlarm so it can disarm itself when the
                # operator advances away from cooldown and clear
                # its cold-start flag
                # on a fresh cooldown entry (finding 1.5). Runs
                # BEFORE the auto-arm path so a phase=cooldown call
                # always sees a cleared flag.
                if _cooldown_alarm is not None:
                    try:
                        _cooldown_alarm.notify_phase_change(phase)
                    except Exception as _exc:
                        logger.warning(
                            "CooldownAlarm: notify_phase_change ошибка: %s",
                            _exc,
                            exc_info=True,
                        )
                # v0.55.4 A1 — auto-arm CooldownAlarm on cooldown phase
                # entry. Operator can still disarm manually via the
                # alarm panel footer button. Idempotent: arm() is a
                # no-op if already armed.
                if phase == "cooldown" and _cooldown_alarm is not None and _cooldown_alarm.is_auto_arm_enabled:
                    try:
                        armed = _cooldown_alarm.arm()
                        if not armed and _cooldown_alarm.cold_start_skipped:
                            # v0.55.12 — surface the skip explicitly so
                            # the operator log shows why auto-arm
                            # didn't engage on this phase entry.
                            logger.info("CooldownAlarm: auto-arm skipped — cold-start detected")
                        else:
                            logger.info(
                                "CooldownAlarm: auto-arm на phase=cooldown → %s",
                                "ARMED" if armed else "FAILED (no model)",
                            )
                    except Exception as _exc:
                        logger.warning("CooldownAlarm: auto-arm ошибка: %s", _exc, exc_info=True)
            return result
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
        if action in {"log_entry", "log_get"}:
            return await _run_operator_log_command(
                action,
                cmd,
                writer,
                experiment_manager,
                broker,
            )
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
            _sh_active = experiment_manager.active_experiment
            await event_bus.publish(
                EngineEvent(
                    event_type="shift_handover_request",
                    timestamp=datetime.now(UTC),
                    payload={
                        "requested_by": cmd.get("operator", ""),
                        "shift_duration_h": int(cmd.get("shift_duration_h", 8)),
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
        if action in ("assistant.query", "rag.search"):
            # B1 (2026-07): the GUI bridge routes these directly to
            # the cryodaq-assistant process's own REP (:5557) now —
            # this is a backward-compat fallback, see the helper.
            return _assistant_process_unavailable_reply(action)
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
                    name=f"multiline_burst_auto_stop_{target_name}",
                )
                # Cancel any pre-existing auto-stop for the same
                # driver — operator restarting the timer wins.
                prev = _multiline_burst_auto_stop_tasks.get(target_name)
                if prev is not None and not prev.done():
                    prev.cancel()
                _multiline_burst_auto_stop_tasks[target_name] = _t
            return response
        if action in ("rag.rebuild_index", "rag.rebuild_status"):
            # B1 (2026-07): moved to cryodaq-assistant's own REP (:5557).
            return _assistant_process_unavailable_reply(action)
        if action == "cooldown_eta_get":
            # B1 (2026-07): additive read-only command — exposes the
            # same CooldownService.last_prediction() the old in-process
            # CooldownAdapter read directly, now for the assistant
            # process's ZMQ-based CooldownAdapter (agents/assistant/
            # query/adapters/cooldown_adapter.py). Never a write path.
            if cooldown_service is None:
                return {"ok": True, "prediction": None}
            return {"ok": True, "prediction": cooldown_service.last_prediction()}
        return {"ok": False, "error": f"unknown command: {action}"}
    except Exception as exc:
        logger.error("Ошибка выполнения команды '%s': %s", action, exc)
        return {"ok": False, "error": str(exc)}


def _zmq_publisher_drop_count(broker: DataBroker) -> int:
    """Return the current publisher drop counter without nested wiring logic."""

    return int(broker.stats["zmq_publisher"]["dropped"])


async def _run_engine(*, mock: bool = False) -> None:
    """Инициализировать и запустить все подсистемы engine."""
    start_ts = time.monotonic()
    logger.info("═══ CryoDAQ Engine запускается ═══")

    # --- Конфигурация путей (*.local.yaml приоритетнее *.yaml) ---
    instruments_cfg = _engine_config_path("instruments")
    interlocks_cfg = _engine_config_path("interlocks")
    housekeeping_cfg = _engine_config_path("housekeeping")
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

    # SafetyManager — создаётся ПЕРВЫМ
    safety_cfg = _engine_config_path("safety")
    safety_manager = SafetyManager(
        safety_broker,
        keithley_driver=driver_load.reviewed_source,
        mock=mock,
        data_broker=broker,
    )
    safety_manager.load_config(safety_cfg)

    # F35: descriptor identity is mandatory production startup authority.
    # A machine-local instrument configuration requires a complete local
    # descriptor replacement; it never falls back to the tracked base.
    live_descriptor_catalog = await _load_live_descriptor_authority(instruments_cfg, driver_load)

    housekeeping_raw = load_housekeeping_config(housekeeping_cfg)
    # Merge legacy interlocks.yaml protection patterns with the modern
    # alarms_v3.yaml critical channels. Without this the throttle thins
    # critical channels even though alarms_v3 marks them CRITICAL.
    legacy_patterns = load_protected_channel_patterns(interlocks_cfg)
    alarms_v3_path = _CONFIG_DIR / "alarms_v3.yaml"
    v3_patterns = load_critical_channels_from_alarms_v3(alarms_v3_path)
    merged_patterns = list({*legacy_patterns, *v3_patterns})
    logger.info(
        "Adaptive-throttle protection: %d legacy + %d v3 = %d unique patterns",
        len(legacy_patterns),
        len(v3_patterns),
        len(merged_patterns),
    )
    adaptive_throttle = AdaptiveThrottle(
        housekeeping_raw.get("adaptive_throttle", {}),
        protected_patterns=merged_patterns,
    )

    # F-1 startup diagnostic: a dead CRITICAL/safety pattern silently disarms
    # its runtime consumer. Validate the exact protected-pattern union supplied
    # to AdaptiveThrottle against the SELECTED descriptor manifest, before any
    # broker subscriber, writer, scheduler, or acquisition exists. TEMPORARY
    # no-brick policy for the lab build: catch only this diagnostic exception,
    # log it at CRITICAL, and continue until the exact lab-local manifest has
    # been validated and recorded. Then remove this catch to enable the
    # exception's intended fail-closed exit-2 behavior.
    try:
        validate_safety_pattern_liveness(
            descriptor_catalog=live_descriptor_catalog,
            interlocks_config_path=interlocks_cfg,
            safety_manager=safety_manager,
            adaptive_throttle_patterns=merged_patterns,
        )
    except SafetyPatternLivenessError as exc:
        logger.critical(
            "TEMPORARY LAB BUILD: startup safety-pattern liveness failed; "
            "continuing boot until the selected lab manifest is validated:\n%s",
            exc,
        )

    # SQLite — persistence-first: writer создаётся ДО scheduler
    writer = SQLiteWriter(_DATA_DIR, channel_catalog=live_descriptor_catalog)
    await writer.start_immediate()
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
        logger.warning("Direct SQLite recording feed unavailable at engine boot: %s", exc, exc_info=True)
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
        reviewed_source_disconnect=safety_manager.disconnect_reviewed_source,
        drain_timeout_s=safety_manager._config.scheduler_drain_timeout_s,
        persistence_commit_observer=recording_lifecycle_feed.persistence_committed,
        persistence_rejection_observer=recording_lifecycle_feed.persistence_rejected,
        persistence_ambiguity_observer=recording_lifecycle_feed.persistence_ambiguous,
    )
    for cfg in driver_configs:
        scheduler.add(cfg)

    # ZMQ PUB
    # F35 D4: only the ZMQ publisher path opts in to the descriptor envelope
    # companion — every other subscriber (writer, alarms, safety broker,
    # sound-carrier, assistant relay) stays on the default bare-Reading path.
    zmq_queue = await broker.subscribe("zmq_publisher", wants_descriptor_envelope=True)
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
    )
    interlock_engine.load_config(interlocks_cfg)

    # ExperimentManager
    experiment_manager = ExperimentManager(
        data_dir=_DATA_DIR,
        instruments_config=instruments_cfg,
        templates_dir=_CONFIG_DIR / "experiment_templates",
    )
    try:
        _seed_recording_lifecycle(recording_lifecycle_feed, experiment_manager)
    except Exception as exc:  # noqa: BLE001 - dark presentation cannot block engine boot
        logger.warning("Recording lifecycle feed unavailable at engine boot: %s", exc, exc_info=True)
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
    _cooldown_cfg, _vacuum_cfg = load_physical_alarms_config(_phys_alarms_yaml)

    # F-ChannelLandmarks: install hardware-pinned landmark map (Т11/Т12 with
    # operator-phrasing aliases) on the shared ChannelManager. The query
    # agent's IntentClassifier reads it via channel_manager.get_landmarks()
    # to resolve phrases like "азотная плита" to the correct channel even
    # when an experiment-level alias has drifted onto another channel.
    try:
        _landmarks = load_channel_landmarks(_phys_alarms_yaml)
        get_channel_manager().set_landmarks(_landmarks)
        if _landmarks:
            logger.info(
                "ChannelLandmarks: загружены для каналов %s",
                ", ".join(sorted(_landmarks)),
            )
    except Exception as exc:
        logger.warning("ChannelLandmarks: ошибка загрузки — %s", exc, exc_info=True)

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
            logger.warning("VacuumGuard: ошибка инициализации, отключён — %s", exc)
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
        project_root=get_project_root(),
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
        zmq_publisher=zmq_pub,
        recording_lifecycle_feed=recording_lifecycle_feed,
    )
    handle_gui_command = functools.partial(
        _handle_gui_command,
        context=command_context,
    )
    cmd_server = ZMQCommandServer(handler=handle_gui_command)

    # Plugin Pipeline
    plugin_pipeline = PluginPipeline(broker, _PLUGINS_DIR)

    # --- CooldownService (прогноз охлаждения) ---
    cooldown_service: Any = None
    cooldown_cfg_path = _engine_config_path("cooldown")
    if cooldown_cfg_path.exists():
        try:
            with cooldown_cfg_path.open(encoding="utf-8") as fh:
                _cd_raw = yaml.safe_load(fh) or {}
            _cd_cfg = _cd_raw.get("cooldown", {})
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
                )
                logger.info("CooldownService создан")
                # v0.55.4 A2: hand the cooldown_service-owned
                # SteadyStatePredictor to CooldownAlarm so its WATCHING
                # path can short-circuit when the system is quasi-steady.
                if _cooldown_alarm is not None:
                    _cooldown_alarm.set_steady_state_predictor(cooldown_service._ss_predictor)
        except Exception as exc:
            logger.error("Ошибка создания CooldownService: %s", exc)
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
            logger.error("Ошибка загрузки конфигурации уведомлений: %s", exc)
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
    await safety_manager.start()
    logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)

    # ─────────────────── Надзор за долгоживущими задачами (A2) ────────────────
    # Каждая долгоживущая задача движка регистрируется в TaskSupervisor. Если её
    # корутина неожиданно падает, done-callback пишет CRITICAL, поднимает
    # оператору тревогу по штатному каналу событий и перезапускает задачу с
    # экспоненц. выдержкой. safety_collect/safety_monitor создаёт SafetyManager;
    # движок надзирает за ними снаружи и после _SAFETY_TASK_MAX_RESTARTS
    # неудачных перезапусков латчит FAULT вместо бесконечного цикла. Политика
    # надзора вынесена в engine_wiring.supervision.TaskSupervisor.
    supervisor = TaskSupervisor(
        event_bus=event_bus,
        experiment_manager=experiment_manager,
        safety_manager=safety_manager,
        alarm_dispatch_tasks=_alarm_dispatch_tasks,
        logger_=logger,
    )
    operator_snapshot_service = None
    try:
        operator_snapshot_service = build_operator_snapshot_publication_service(
            safety_owner=safety_manager,
            recording_feed=recording_lifecycle_feed,
            publisher=zmq_pub,
            data_root=_DATA_DIR,
        )
    except Exception as exc:  # noqa: BLE001 - observational publication is fail-dark
        logger.warning("Operator snapshot publication unavailable at engine boot: %s", exc, exc_info=True)

    # safety_collect/safety_monitor уже созданы SafetyManager.start(); надзираем
    # за ними снаружи, не трогая safety_manager.py. Перезапуск повторно запускает
    # ту же петлю и синхронизирует ссылку в SafetyManager, чтобы stop() и sweep
    # завершения видели живую задачу.
    for _sname, _sattr in (("safety_collect", "_collect_task"), ("safety_monitor", "_monitor_task")):
        _stask = getattr(safety_manager, _sattr, None)
        if _stask is not None:
            _loop_fn = getattr(safety_manager, f"_{_sname.split('_', 1)[1]}_loop")
            supervisor.register(
                _sname,
                _stask,
                _loop_fn,
                safety_critical=True,
                on_spawn=functools.partial(_set_safety_task_ref, safety_manager, _sattr),
            )

    install_loop_exception_backstop(asyncio.get_running_loop(), logger)

    # writer уже запущен через start_immediate() выше
    await zmq_pub.start(zmq_queue)
    await cmd_server.start()
    await interlock_engine.start()
    await plugin_pipeline.start()
    if cooldown_service is not None:
        await cooldown_service.start()
    if telegram_bot is not None:
        await telegram_bot.start()
    if _photo_handler is not None:
        await _photo_handler.start()
    # B1: relay EngineEvents to the assistant process over ZMQ (see the
    # wiring comment above _assistant_relay_queue for what this replaces).
    assistant_event_relay_task = supervisor.spawn(
        "assistant_event_relay",
        functools.partial(
            assistant_event_relay_loop,
            _assistant_relay_queue,
            zmq_pub,
            _ASSISTANT_RELAY_EVENT_TYPES,
        ),
    )
    acquisition_lifecycle_sequence = await _start_scheduler_with_recording_feed(
        scheduler,
        recording_lifecycle_feed,
        acquisition_lifecycle_sequence,
    )
    if operator_snapshot_service is not None:
        supervisor.spawn(
            "operator_snapshot_publication",
            operator_snapshot_service.run,
        )
    throttle_task = supervisor.spawn(
        "adaptive_throttle_runtime",
        functools.partial(track_runtime_signals, broker, adaptive_throttle),
    )
    alarm_v2_feed_task = supervisor.spawn(
        "alarm_v2_feed",
        functools.partial(
            alarm_v2_feed_readings,
            broker,
            _alarm_v2_state_tracker,
            _alarm_v2_rate,
        ),
    )
    alarm_ring_task = supervisor.spawn(
        "alarm_ring_buffer_feed",
        functools.partial(alarm_ring_feed, event_bus, _alarm_ring),
    )
    alarm_v2_tick_task: asyncio.Task | None = None
    if _alarm_v2_configs:
        alarm_v2_tick_task = supervisor.spawn(
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

    cooldown_alarm_task: asyncio.Task | None = None
    vacuum_guard_task: asyncio.Task | None = None
    if _cooldown_alarm is not None:
        cooldown_alarm_task = supervisor.spawn(
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
    if _vacuum_guard is not None:
        vacuum_guard_task = supervisor.spawn(
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

    sd_feed_task: asyncio.Task | None = None
    sd_tick_task: asyncio.Task | None = None
    if sensor_diag is not None:
        sd_feed_task = supervisor.spawn(
            "sensor_diag_feed",
            functools.partial(sensor_diag_feed, sensor_diag, broker),
        )
        sd_tick_task = supervisor.spawn(
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
        # v0.55.5 — anchor the cold-start grace at the moment the feed
        # and tick tasks are actually live. Doing this here (rather than
        # in the constructor) avoids counting the engine bootstrap
        # window as part of the grace.
        sensor_diag.mark_engine_started()
    vt_feed_task: asyncio.Task | None = None
    vt_tick_task: asyncio.Task | None = None
    if vacuum_trend is not None:
        vt_feed_task = supervisor.spawn(
            "vacuum_trend_feed",
            functools.partial(vacuum_trend_feed, vacuum_trend, _vt_cfg, broker),
        )
        vt_tick_task = supervisor.spawn(
            "vacuum_trend_tick",
            functools.partial(vacuum_trend_tick, vacuum_trend, _vt_cfg),
        )
    leak_rate_feed_task = supervisor.spawn(
        "leak_rate_feed",
        functools.partial(
            leak_rate_feed,
            vt_cfg=_vt_cfg,
            broker=broker,
            leak_rate_estimator=leak_rate_estimator,
            event_logger=event_logger,
        ),
    )
    await housekeeping_service.start()

    cold_rotation_task: asyncio.Task | None = None
    if cold_rotation_service is not None:
        cold_rotation_task = supervisor.spawn(
            "cold_rotation_scheduler",
            functools.partial(
                cold_rotation_scheduler,
                cold_rotation_service,
                cold_rotation_schedule,
            ),
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
    watchdog_task = supervisor.spawn(
        "engine_watchdog",
        functools.partial(_watchdog, broker, scheduler, writer, start_ts),
    )

    # DiskMonitor — also wires the writer so disk-recovery can clear the
    # _disk_full flag (Phase 2a H.1).
    disk_monitor = DiskMonitor(data_dir=_DATA_DIR, broker=broker, sqlite_writer=writer)
    await disk_monitor.start()

    logger.info(
        "═══ CryoDAQ Engine запущен ═══ | приборов=%d | тревог=%d | блокировок=%d | mock=%s",
        len(driver_configs),
        len(_alarm_v2_configs),
        len(interlock_engine.get_state()),
        mock,
    )

    # --- Ожидание сигнала завершения ---
    shutdown_event = asyncio.Event()

    # Регистрация обработчиков сигналов
    loop = asyncio.get_running_loop()
    request_shutdown = functools.partial(_request_shutdown, shutdown_event)
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, request_shutdown)
        loop.add_signal_handler(signal.SIGTERM, request_shutdown)
    else:
        # Windows: signal.signal работает только в главном потоке
        signal.signal(signal.SIGINT, request_shutdown)

    await shutdown_event.wait()

    # --- Корректное завершение ---
    logger.info("═══ Завершение CryoDAQ Engine ═══")

    # A2: гасим надзор до отмены задач — иначе done-callback перезапустит
    # только что отменённую задачу прямо во время завершения.
    supervisor.stop()
    if operator_snapshot_service is not None:
        operator_snapshot_service.request_stop()
        operator_snapshot_task = supervisor.supervised_tasks.get("operator_snapshot_publication")
        if operator_snapshot_task is not None:
            try:
                await operator_snapshot_task
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - presentation failure cannot block shutdown
                logger.warning("Operator snapshot publication stopped with failure: %s", exc, exc_info=True)

    # F31 H3: drain in-flight sink dispatches before downstream teardown.
    # _alarm_dispatch_tasks holds vault-write and webhook-POST tasks
    # that are mid-flight at SIGTERM time; cancelling them mid-flight
    # corrupts vault notes and aborts webhook POSTs. Cap at 10s.
    await _drain_dispatch_tasks(_alarm_dispatch_tasks, logger)

    watchdog_task.cancel()
    try:
        await watchdog_task
    except asyncio.CancelledError:
        pass

    throttle_task.cancel()
    try:
        await throttle_task
    except asyncio.CancelledError:
        pass

    alarm_v2_feed_task.cancel()
    try:
        await alarm_v2_feed_task
    except asyncio.CancelledError:
        pass

    alarm_ring_task.cancel()
    try:
        await alarm_ring_task
    except asyncio.CancelledError:
        pass
    if alarm_v2_tick_task is not None:
        alarm_v2_tick_task.cancel()
        try:
            await alarm_v2_tick_task
        except asyncio.CancelledError:
            pass

    if sd_feed_task is not None:
        sd_feed_task.cancel()
        try:
            await sd_feed_task
        except asyncio.CancelledError:
            pass
    if sd_tick_task is not None:
        sd_tick_task.cancel()
        try:
            await sd_tick_task
        except asyncio.CancelledError:
            pass
    if cooldown_alarm_task is not None:
        cooldown_alarm_task.cancel()
        try:
            await cooldown_alarm_task
        except asyncio.CancelledError:
            pass
    if vacuum_guard_task is not None:
        vacuum_guard_task.cancel()
        try:
            await vacuum_guard_task
        except asyncio.CancelledError:
            pass

    if vt_feed_task is not None:
        vt_feed_task.cancel()
        try:
            await vt_feed_task
        except asyncio.CancelledError:
            pass
    if vt_tick_task is not None:
        vt_tick_task.cancel()
        try:
            await vt_tick_task
        except asyncio.CancelledError:
            pass
    assistant_event_relay_task.cancel()
    try:
        await assistant_event_relay_task
    except asyncio.CancelledError:
        pass
    leak_rate_feed_task.cancel()
    try:
        await leak_rate_feed_task
    except asyncio.CancelledError:
        pass

    # A2: подметаем перезапущенные надзором задачи — их именованные ссылки
    # выше могут указывать на уже мёртвый оригинал, а живой перезапуск висит
    # только в _supervised_tasks. safety_collect/safety_monitor исключаем:
    # их снимает safety_manager.stop() последними (ссылки синхронизированы при
    # перезапуске), чтобы мониторинг безопасности жил до конца завершения.
    _stragglers = [
        t
        for name, t in supervisor.supervised_tasks.items()
        if name not in ("safety_collect", "safety_monitor") and not t.done()
    ]
    for _t in _stragglers:
        _t.cancel()
    if _stragglers:
        await asyncio.gather(*_stragglers, return_exceptions=True)

    # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
    acquisition_lifecycle_sequence = await _stop_scheduler_with_recording_feed(
        scheduler,
        recording_lifecycle_feed,
        acquisition_lifecycle_sequence,
    )
    logger.info("Планировщик остановлен")

    await plugin_pipeline.stop()
    logger.info("Пайплайн плагинов остановлен")

    if cooldown_service is not None:
        await cooldown_service.stop()
        logger.info("CooldownService остановлен")

    event_bus.unsubscribe("assistant_zmq_relay")

    if _photo_handler is not None:
        await _photo_handler.stop()
        logger.info("CompositionPhotoHandler остановлен")

    if telegram_bot is not None:
        await telegram_bot.stop()
        logger.info("TelegramCommandBot остановлен")

    await interlock_engine.stop()
    logger.info("Движок блокировок остановлен")

    await safety_manager.stop()
    logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)

    await disk_monitor.stop()
    logger.info("DiskMonitor остановлен")

    await housekeeping_service.stop()
    logger.info("HousekeepingService остановлен")

    if cold_rotation_task is not None:
        cold_rotation_task.cancel()
        try:
            await cold_rotation_task
        except asyncio.CancelledError:
            pass
        logger.info("ColdRotationService остановлен")

    await writer.stop()
    logger.info("SQLite записано: %d", writer.stats.get("total_written", 0))

    await cmd_server.stop()
    logger.info("ZMQ CommandServer остановлен")

    await zmq_pub.stop()
    logger.info("ZMQ Publisher остановлен")

    from cryodaq.drivers.transport.gpib import GPIBTransport

    GPIBTransport.close_all_managers()
    logger.info("GPIB ResourceManagers закрыты")

    uptime = time.monotonic() - start_ts
    logger.info(
        "═══ CryoDAQ Engine завершён ═══ | uptime=%.1f с",
        uptime,
    )


# ---------------------------------------------------------------------------
# Single-instance guard
# ---------------------------------------------------------------------------

_LOCK_FILE = get_data_dir() / ".engine.lock"


def _is_pid_alive(pid: int) -> bool:
    """Check if process with given PID exists."""
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


def _acquire_engine_lock() -> int:
    """Acquire exclusive engine lock via flock/msvcrt. Returns fd.

    If lock is held by a dead process, auto-cleans and retries.
    Shows helpful error with PID and kill command if lock is live.
    """
    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(_LOCK_FILE), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Lock held by another process (flock/msvcrt is authoritative)
        os.close(fd)
        logger.error(
            "CryoDAQ engine уже запущен (lock: %s).\n"
            "  Для принудительного запуска: cryodaq-engine --force\n"
            "  Или завершите процесс через Диспетчер задач (python/pythonw).",
            _LOCK_FILE,
        )
        raise SystemExit(1)

    os.ftruncate(fd, 0)
    os.lseek(fd, 0, os.SEEK_SET)
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def _force_kill_existing() -> None:
    """Force-kill any running engine and remove lock."""
    if not _LOCK_FILE.exists():
        return
    # Read PID via os.open — works even when file is locked by msvcrt
    pid = None
    fd = None
    try:
        fd = os.open(str(_LOCK_FILE), os.O_RDONLY)
        raw = os.read(fd, 64).decode().strip()
        pid = int(raw)
    except (OSError, ValueError):
        pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    if pid is None:
        try:
            _LOCK_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return
    if _is_pid_alive(pid):
        logger.warning("Принудительная остановка engine (PID %d)...", pid)
        try:
            if sys.platform == "win32":
                import subprocess

                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=5)
            else:
                os.kill(pid, 9)  # SIGKILL
        except Exception as exc:
            logger.error("Не удалось завершить PID %d: %s", pid, exc)
            raise SystemExit(1)
        for _ in range(20):
            time.sleep(0.25)
            if not _is_pid_alive(pid):
                break
        else:
            logger.error("PID %d не завершился после 5с", pid)
            raise SystemExit(1)
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        logger.debug("Lock file busy (will be released by OS)")
    logger.info("Старый engine остановлен, lock очищен")


def _release_engine_lock(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

#: Exit code for unrecoverable startup config errors (Phase 2b H.3).
#: Launcher detects this and refuses to auto-restart.
ENGINE_CONFIG_ERROR_EXIT_CODE = 2


def main() -> None:
    """Точка входа cryodaq-engine."""
    import argparse
    import traceback

    parser = argparse.ArgumentParser(description="CryoDAQ Engine")
    parser.add_argument("--mock", action="store_true", help="Mock mode (simulated instruments)")
    parser.add_argument("--force", action="store_true", help="Kill existing engine and take over")
    args = parser.parse_args()

    from cryodaq.logging_setup import resolve_log_level, setup_logging

    setup_logging("engine", level=resolve_log_level())

    if args.force:
        _force_kill_existing()

    mock = args.mock or os.environ.get("CRYODAQ_MOCK", "").lower() in ("1", "true")

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
                    runner.run(_run_engine(mock=mock))
            else:
                asyncio.run(_run_engine(mock=mock))
        except KeyboardInterrupt:
            logger.info("Прервано оператором (Ctrl+C)")
        except yaml.YAMLError as exc:
            # Phase 2b H.3: a YAML parse error during startup is
            # unrecoverable by retry — exit with a distinct code so the
            # launcher refuses to spin in a tight restart loop.
            logger.critical(
                "CONFIG ERROR (YAML parse): %s\n%s",
                exc,
                traceback.format_exc(),
            )
            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
        except FileNotFoundError as exc:
            # Missing required config file at startup is also a config
            # error: same exit code.
            logger.critical(
                "CONFIG ERROR (file not found): %s\n%s",
                exc,
                traceback.format_exc(),
            )
            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
        except (
            SafetyConfigError,
            AlarmConfigError,
            InterlockConfigError,
            HousekeepingConfigError,
            ChannelConfigError,
            DriverRegistryError,
        ) as exc:
            labels = (
                (SafetyConfigError, "safety"),
                (AlarmConfigError, "alarm"),
                (InterlockConfigError, "interlock"),
                (HousekeepingConfigError, "housekeeping"),
                (ChannelConfigError, "channel"),
                (DriverRegistryError, "driver registry"),
            )
            label = next(
                (label for error_type, label in labels if isinstance(exc, error_type)),
                "config",
            )
            logger.critical(
                "CONFIG ERROR (%s config): %s\n%s",
                label,
                exc,
                traceback.format_exc(),
            )
            sys.exit(ENGINE_CONFIG_ERROR_EXIT_CODE)
    finally:
        _release_engine_lock(lock_fd)


if __name__ == "__main__":
    main()
