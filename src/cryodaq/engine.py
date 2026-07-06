"""Головной процесс CryoDAQ Engine (безголовый).

Запуск:
    cryodaq-engine          # через entry point
    python -m cryodaq.engine  # напрямую

Загружает конфигурации, создаёт и связывает все подсистемы:
    drivers → DataBroker →
    [SQLiteWriter, ZMQPublisher, AlarmEngine, InterlockEngine, PluginPipeline]

Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import signal
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime

# Windows: pyzmq требует SelectorEventLoop (не Proactor)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from pathlib import Path
from typing import Any

import yaml

from cryodaq.agents.assistant.live.agent import AssistantConfig, AssistantLiveAgent
from cryodaq.agents.assistant.live.context_builder import ContextBuilder
from cryodaq.agents.assistant.live.output_router import OutputRouter
from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant.shared.ollama_client import OllamaClient
from cryodaq.analytics.calibration import CalibrationStore
from cryodaq.analytics.leak_rate import LeakRateEstimator
from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor
from cryodaq.core.alarm import AlarmEngine
from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config
from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmStateManager, tick_alarm
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
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine
from cryodaq.core.smu_channel import normalize_smu_channel
from cryodaq.core.vacuum_guard import VacuumGuard
from cryodaq.core.zmq_bridge import ZMQCommandServer, ZMQPublisher
from cryodaq.drivers.base import Reading
from cryodaq.notifications.composition_photo_handler import CompositionPhotoHandler
from cryodaq.notifications.escalation import EscalationService
from cryodaq.notifications.periodic_report import PeriodicReporter
from cryodaq.notifications.telegram_commands import TelegramCommandBot
from cryodaq.paths import get_config_dir, get_data_dir, get_project_root
from cryodaq.reporting.generator import ReportGenerator
from cryodaq.storage.sqlite_writer import SQLiteWriter

logger = logging.getLogger("cryodaq.engine")

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


async def _periodic_report_tick(
    agent_config: AssistantConfig,
    event_bus: EventBus,
    experiment_manager: ExperimentManager,
    *,
    sleep=asyncio.sleep,
) -> None:
    """Publish periodic_report_request events on the assistant schedule."""
    interval_s = float(agent_config.get_periodic_report_interval_s())
    if interval_s <= 0:
        logger.info("Periodic assistant reports disabled (interval=0)")
        return

    window_minutes = int(agent_config.periodic_report_interval_minutes)
    while True:
        await sleep(interval_s)
        try:
            experiment_id = getattr(experiment_manager, "active_experiment_id", None)
            if experiment_id is None:
                active = getattr(experiment_manager, "active_experiment", None)
                experiment_id = getattr(active, "experiment_id", None) if active else None
            await event_bus.publish(
                EngineEvent(
                    event_type="periodic_report_request",
                    timestamp=datetime.now(UTC),
                    payload={
                        "window_minutes": window_minutes,
                        "trigger": "scheduled",
                    },
                    experiment_id=experiment_id,
                )
            )
        except Exception as exc:
            logger.error("Periodic assistant report tick error: %s", exc)


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
            v = (
                _coerce_finite_setpoint(cmd["v_comp"], "v_comp")
                if cmd.get("v_comp") is not None
                else None
            )
            i = (
                _coerce_finite_setpoint(cmd["i_comp"], "i_comp")
                if cmd.get("i_comp") is not None
                else None
            )
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


async def _handle_assistant_query_command(
    query_agent: Any,
    cmd: dict[str, Any],
    *,
    timeout_s: float = 50.0,  # H7: bumped from 25s for Ollama cold-start
) -> dict[str, Any]:
    """Dispatch ``assistant.query`` GUI/Telegram command to AssistantQueryAgent.

    F34: extracted as a module-level helper so the dispatch logic is unit-
    testable without spinning up the full engine. Mirrors the exception
    hierarchy of :class:`AssistantQueryAgent.handle_query` (never raises;
    returns a Russian error string-shaped dict on every failure path).

    Default ``timeout_s`` (50 s) is chosen to absorb Ollama cold-start
    on the first query after engine boot: loading gemma4:e2b takes
    20–40 s, and the previous 25 s ceiling fired before the model had
    finished loading, surfacing a Russian "Запрос обрабатывался слишком
    долго" error on the operator's first GUI query. The surrounding
    transport budget is bumped in lockstep and nests strictly: ZMQ slow
    envelope ``HANDLER_TIMEOUT_SLOW_S`` is 55 s (``core/zmq_bridge.py``)
    < subprocess REQ socket ``SUBPROCESS_REQ_TIMEOUT_S`` 60 s
    (``core/zmq_subprocess.py``) < GUI client reply timeout
    ``_CMD_REPLY_TIMEOUT_S`` 65 s (``gui/zmq_client.py``); Telegram path
    stays at 60 s via ``telegram_commands.py`` (it does not flow through
    the ZMQ REP server). Subsequent warm-cache queries land well under 5 s.
    """
    query = str(cmd.get("query", "")).strip()
    chat_id = cmd.get("chat_id", "gui")
    if not query:
        return {"ok": False, "error": "Пустой запрос."}
    if query_agent is None:
        return {
            "ok": False,
            "error": (
                "AssistantQueryAgent не сконфигурирован "
                "(query_enabled=false в agent.yaml)."
            ),
        }
    try:
        response = await asyncio.wait_for(
            query_agent.handle_query(query, chat_id=chat_id),
            timeout=timeout_s,
        )
        return {"ok": True, "response": response}
    except TimeoutError:
        return {
            "ok": False,
            "error": (
                f"Запрос обрабатывался слишком долго (>{timeout_s:g}s). "
                "Попробуй ещё раз — модель уже прогрелась — "
                "или используй Telegram-бота для длинных вопросов."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("assistant.query error: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}


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


def _format_diag_telegram_messages(
    new_events: list[Any],
    aggregation_threshold: int = 3,
) -> list[tuple[str, str]]:
    """Build the Telegram dispatch ``(task_name, message)`` pairs for a batch
    of sensor-diagnostic events.

    F10/F20: extracted from the ``_sensor_diag_tick`` closure so the message
    formatting — including the F20 aggregation rule (more than
    *aggregation_threshold* simultaneous events collapse into one batch
    summary; otherwise one message per event) — is unit-testable without the
    engine loop. Returns pairs in dispatch order (empty when nothing to send).
    Behaviour-preserving, including the asyncio task names.
    """
    if not new_events:
        return []
    if len(new_events) > aggregation_threshold:
        criticals = [e for e in new_events if e.level == "CRITICAL"]
        warnings = [e for e in new_events if e.level == "WARNING"]
        parts: list[str] = []
        if criticals:
            names = ", ".join(
                e.channels[0] if e.channels else e.alarm_id for e in criticals
            )
            parts.append(f"{len(criticals)} channels critical: {names}")
        if warnings:
            names = ", ".join(
                e.channels[0] if e.channels else e.alarm_id for e in warnings
            )
            parts.append(f"{len(warnings)} channels warning: {names}")
        return [("diag_tg_batch", "⚠ Diagnostic alarm batch:\n" + "\n".join(parts))]
    return [
        (
            f"diag_tg_{event.alarm_id}",
            f"⚠ [{event.level}] {event.alarm_id}\n{event.message}",
        )
        for event in new_events
    ]


async def _handle_rag_search_command(
    rag_searcher: Any,
    cmd: dict[str, Any],
    *,
    timeout_s: float = 30.0,
) -> dict[str, Any]:
    """Dispatch ``rag.search`` GUI command to the F32 RagSearcher.

    Module-level helper mirrors :func:`_handle_assistant_query_command` so
    the v0.55.6 knowledge-base overlay's dispatch path is unit-testable
    without spinning up the engine. Returns a serialised list of
    SearchResult dicts on success or a Russian error string-shaped dict
    on every failure (missing index, empty query, timeout, exception).
    """
    if rag_searcher is None:
        return {
            "ok": False,
            "error": "RAG индекс не построен. Запустите cryodaq-rag-index.",
        }
    query = str(cmd.get("query", "")).strip()
    if not query:
        return {"ok": False, "error": "Пустой запрос."}
    top_k = int(cmd.get("limit", cmd.get("top_k", 10)))
    raw_filter = cmd.get("source_kind_filter")
    if raw_filter is None:
        source_kind_filter: list[str] | None = None
    elif isinstance(raw_filter, list):
        source_kind_filter = [str(x) for x in raw_filter]
    else:
        source_kind_filter = [str(raw_filter)]
    try:
        results = await asyncio.wait_for(
            rag_searcher.search(
                query,
                top_k=top_k,
                source_kind_filter=source_kind_filter,
            ),
            timeout=timeout_s,
        )
        return {
            "ok": True,
            "results": [
                {
                    "chunk_id": r.chunk_id,
                    "source_kind": r.source_kind,
                    "source_id": r.source_id,
                    "text": r.text,
                    "metadata": r.metadata,
                    "score": r.score,
                }
                for r in results
            ],
        }
    except TimeoutError:
        return {
            "ok": False,
            "error": (
                f"RAG-поиск занял больше {timeout_s:g}с — возможно Ollama зависла."
            ),
        }
    except Exception as exc:  # noqa: BLE001
        logger.error("rag.search error: %s", exc, exc_info=True)
        return {"ok": False, "error": str(exc)}


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
        ml_names = [
            n
            for n, d in drivers_by_name.items()
            if d.__class__.__name__ == "MultiLineDriver"
        ]
        if len(ml_names) == 1:
            name = ml_names[0]
        else:
            return {
                "ok": False,
                "error": (
                    "MultiLine instance not specified and multiple drivers "
                    "are configured"
                ),
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
        _persist_multiline_channels_to_local_yaml(
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

    Codex audit cycle 1 amend (smoke hotfix): the original helper
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

    base_instruments = [
        e for e in (base_raw.get("instruments") or []) if isinstance(e, dict)
    ]
    local_instruments = [
        e for e in (local_raw.get("instruments") or []) if isinstance(e, dict)
    ]

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
        if (
            str(entry.get("type")) == "etalon_multiline"
            and str(entry.get("name")) == instrument_name
        ):
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

    # Codex audit cycle 2 amend: engine loads instruments.local.yaml
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
        ml_names = [
            n
            for n, d in drivers_by_name.items()
            if d.__class__.__name__ == "MultiLineDriver"
        ]
        if len(ml_names) == 1:
            name = ml_names[0]
        else:
            return {
                "ok": False,
                "error": (
                    "MultiLine instance not specified and "
                    f"{len(ml_names)} configured — pass `name` explicitly."
                ),
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


# v0.55.7.1 — rag.rebuild_index command state machine. Single-instance:
# concurrent rebuild is rejected с a Russian error string. State is
# module-level rather than per-engine because the rebuild is also
# operator-facing (GUI poll), and idle/running/complete/failed maps
# directly к the panel's status label states. The accompanying task
# ref is also held here; engine startup constructs both fresh.
_rag_rebuild_state: dict[str, Any] = {
    "state": "idle",
    "started_at": None,
    "finished_at": None,
    "chunks_indexed": 0,
    "error": None,
}
_rag_rebuild_task: asyncio.Task[None] | None = None


def _rag_rebuild_status_snapshot() -> dict[str, Any]:
    """Return a JSON-serialisable copy of the rebuild state."""
    return {
        "ok": True,
        "state": _rag_rebuild_state["state"],
        "started_at": _rag_rebuild_state["started_at"],
        "finished_at": _rag_rebuild_state["finished_at"],
        "chunks_indexed": _rag_rebuild_state["chunks_indexed"],
        "error": _rag_rebuild_state["error"],
    }


async def _run_rag_rebuild(
    *,
    db_path: Path,
    embeddings_client: Any,
    knowledge_dir: Path,
    experiments_dir: Path,
    sqlite_path: Path | None,
    repo_root: Path,
) -> None:
    """Body of the manual rebuild task.

    Updates ``_rag_rebuild_state`` in-place across the lifecycle so
    poll responses always reflect the latest state. Failures populate
    ``error`` field rather than re-raising; the engine task wrapper
    discards the task ref после completion.
    """
    try:
        from cryodaq.agents.rag.indexer import build_index  # noqa: PLC0415

        stats = await build_index(
            experiments_dir=experiments_dir,
            vault_dir=None,
            sqlite_path=sqlite_path,
            db_path=db_path,
            embeddings_client=embeddings_client,
            pdf_dir=knowledge_dir / "equipment_manuals",
            procedures_dir=knowledge_dir / "procedures",
            reference_root=repo_root,
        )
        _rag_rebuild_state.update(
            {
                "state": "complete",
                "finished_at": time.time(),
                "chunks_indexed": int(stats.get("indexed", 0)),
                "error": None,
            }
        )
        logger.info(
            "RAG manual rebuild complete: %d chunks indexed в %s",
            stats.get("indexed", 0),
            db_path,
        )
    except Exception as exc:  # noqa: BLE001
        _rag_rebuild_state.update(
            {
                "state": "failed",
                "finished_at": time.time(),
                "error": str(exc),
            }
        )
        logger.error("RAG manual rebuild failed: %s", exc, exc_info=True)


async def _handle_rag_rebuild_command(
    action: str,
    cmd: dict[str, Any],
    *,
    db_path: Path | None,
    embeddings_client: Any | None,
    knowledge_dir: Path | None,
    experiments_dir: Path | None,
    sqlite_path: Path | None,
    repo_root: Path | None,
) -> dict[str, Any]:
    """Dispatch ``rag.rebuild_index`` / ``rag.rebuild_status`` GUI commands.

    Module-level helper (mirrors ``_handle_assistant_query_command``)
    so the closure inside ``_handle_gui_command`` is a one-line delegate
    and tests can exercise the dispatch path without spinning up an
    engine. Concurrent rebuilds rejected — operator must wait for the
    current run to finish before re-clicking the GUI button.
    """
    global _rag_rebuild_task

    if action == "rag.rebuild_status":
        return _rag_rebuild_status_snapshot()

    if action != "rag.rebuild_index":
        return {"ok": False, "error": f"unknown rebuild action: {action}"}

    if _rag_rebuild_state["state"] == "running":
        return {
            "ok": False,
            "error": "Rebuild уже идёт — дождитесь завершения.",
        }
    if (
        embeddings_client is None
        or db_path is None
        or knowledge_dir is None
        or experiments_dir is None
        or repo_root is None
    ):
        return {
            "ok": False,
            "error": "RAG не сконфигурирован (config/rag.yaml отсутствует?).",
        }

    # Reset state — operator-clicked start always wins over a stale
    # complete/failed status from a previous run.
    _rag_rebuild_state.update(
        {
            "state": "running",
            "started_at": time.time(),
            "finished_at": None,
            "chunks_indexed": 0,
            "error": None,
        }
    )
    _rag_rebuild_task = asyncio.create_task(
        _run_rag_rebuild(
            db_path=db_path,
            embeddings_client=embeddings_client,
            knowledge_dir=knowledge_dir,
            experiments_dir=experiments_dir,
            sqlite_path=sqlite_path,
            repo_root=repo_root,
        ),
        name="rag_manual_rebuild",
    )
    return {
        "ok": True,
        "state": "running",
        "started_at": _rag_rebuild_state["started_at"],
    }


async def _bootstrap_rag_index_if_empty(
    *,
    db_path: Path,
    embeddings_client: Any,
    knowledge_dir: Path,
    experiments_dir: Path,
    sqlite_path: Path | None,
    repo_root: Path,
) -> None:
    """Build the RAG index из bundled corpus if it's empty.

    F-KnowledgeBaseExpansion (v0.55.7.1): operator demos на свежем
    клон должны видеть базу знаний без manual ``cryodaq-rag-index``
    step. The engine fires this as ``asyncio.create_task`` — the
    bootstrap progresses в фоне; engine ``ready`` signal is NOT
    awaited on it. Failures are logged but never propagated; operator
    briefly sees empty KnowledgeBasePanel, then it populates без
    restart once embeddings finish.

    Idempotent: probes the index с a 1-result search; non-empty
    response → skip. Pre-existing tables therefore safe to leave
    alone (e.g. RAGIndexSink built one earlier in this engine's
    lifetime, or a manual ``cryodaq-rag-index`` run).
    """
    try:
        from cryodaq.agents.rag.searcher import RagSearcher  # noqa: PLC0415

        searcher = RagSearcher(
            db_path=db_path, embeddings_client=embeddings_client
        )
        sample = await searcher.search("test", top_k=1)
        if sample:
            logger.info(
                "RAG index already populated (%d sample), skipping bootstrap",
                len(sample),
            )
            return
    except Exception as exc:  # noqa: BLE001
        # Probe failure is expected on the very first run (table missing).
        # Log at INFO — that path IS the bootstrap's reason for existing.
        logger.info("RAG index probe failed, proceeding with bootstrap: %s", exc)

    logger.info("RAG bootstrap starting from bundled sources в %s", knowledge_dir)
    try:
        from cryodaq.agents.rag.indexer import build_index  # noqa: PLC0415

        stats = await build_index(
            experiments_dir=experiments_dir,
            vault_dir=None,  # vault не bundled
            sqlite_path=sqlite_path,
            db_path=db_path,
            embeddings_client=embeddings_client,
            pdf_dir=knowledge_dir / "equipment_manuals",
            procedures_dir=knowledge_dir / "procedures",
            reference_root=repo_root,
        )
        logger.info(
            "RAG bootstrap complete: %d chunks indexed в %s",
            stats.get("indexed", 0),
            db_path,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("RAG bootstrap failed: %s", exc, exc_info=True)


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
            "curves": calibration_store.list_curves(
                sensor_id=str(cmd.get("sensor_id", "")).strip() or None
            ),
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
            runtime_apply_ready=(
                bool(cmd.get("runtime_apply_ready")) if "runtime_apply_ready" in cmd else None
            ),
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
            logger.warning(
                "Calibration experiment missing reference_channel/target_channels in custom_fields"
            )
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
            payload = _json.loads(entry.metadata_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        phases: list[dict] = payload.get("phases", [])
        cooldown_phase = next(
            (
                p
                for p in phases
                if p.get("phase") == "cooldown" and p.get("ended_at") is not None
            ),
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
            duration_hours = round(
                (ended_dt - started_dt).total_seconds() / 3600, 3
            )
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
                    {"phase": p.get("phase"), "ts": p.get("started_at")}
                    for p in phases
                    if p.get("started_at")
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
        # Report is generated inside finalize_experiment() by ExperimentManager.
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
            artifact_paths=[
                str(item).strip()
                for item in list(cmd.get("artifact_paths") or [])
                if str(item).strip()
            ],
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
        generator = ReportGenerator(experiment_manager.data_dir)
        result = generator.generate(experiment_id)
        return {
            "ok": True,
            "report": {
                "docx_path": str(result.docx_path),
                "pdf_path": str(result.pdf_path) if result.pdf_path else None,
                "assets_dir": str(result.assets_dir),
                "sections": list(result.sections),
                "skipped": result.skipped,
                "reason": result.reason,
            },
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
                    "Не удалось вычислить elapsed_in_phase_s из started_at=%r: %s — "
                    "возвращаю 0.0 (display-only)",
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


def _load_drivers(
    config_path: Path,
    *,
    mock: bool,
    calibration_store: CalibrationStore | None = None,
) -> list[InstrumentConfig]:
    """Загрузить драйверы из config/instruments.yaml.

    Возвращает список InstrumentConfig, готовых к регистрации в Scheduler.
    """
    with config_path.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh)

    configs: list[InstrumentConfig] = []

    for entry in raw.get("instruments", []):
        itype = entry["type"]
        name = entry["name"]
        resource = entry.get("resource", "")
        poll_interval_s = float(entry.get("poll_interval_s", 1.0))
        channels = entry.get("channels", {})

        if itype == "lakeshore_218s":
            from cryodaq.drivers.instruments.lakeshore_218s import LakeShore218S

            channel_labels = {int(k): v for k, v in channels.items()}
            driver = LakeShore218S(
                name,
                resource,
                channel_labels=channel_labels,
                mock=mock,
                calibration_store=calibration_store,
            )
        elif itype == "keithley_2604b":
            from cryodaq.drivers.instruments.keithley_2604b import Keithley2604B

            wdog_cfg = raw.get("keithley", {}).get("watchdog", {})
            driver = Keithley2604B(
                name,
                resource,
                mock=mock,
                watchdog_enabled=bool(wdog_cfg.get("enabled", False)),
                watchdog_timeout_s=float(wdog_cfg.get("timeout_s", 5.0)),
            )
        elif itype == "thyracont_vsp63d":
            from cryodaq.drivers.instruments.thyracont_vsp63d import ThyracontVSP63D

            baudrate = int(entry.get("baudrate", 9600))
            validate_checksum = bool(entry.get("validate_checksum", True))
            driver = ThyracontVSP63D(
                name, resource, baudrate=baudrate, validate_checksum=validate_checksum, mock=mock
            )
        elif itype == "etalon_multiline":
            from cryodaq.drivers.instruments.etalon_multiline import MultiLineDriver

            # v0.55.6.1: accept either explicit ``channels`` list or the
            # convenience ``channel_count`` integer (1..32). Driver
            # validates the resolved set; failure raises ValueError and
            # the engine drops the entry with the existing logger path.
            # v0.55.11: also pass ``mode`` (averaged|continuous) and
            # ``target_rate_hz`` so continuous-mode deployments can
            # opt-in via config without code changes. Burst dir defaults
            # to ``<DATA_DIR>/multiline_bursts`` so the fallback path
            # (no active experiment) lands inside the data root rather
            # than CWD.
            _ml_channels = entry.get("channels")
            _ml_channel_count = entry.get("channel_count")
            driver = MultiLineDriver(
                name,
                host=str(entry.get("host", "localhost")),
                port=int(entry.get("port", 2001)),
                channel_numbers=list(_ml_channels) if _ml_channels else None,
                channel_count=(int(_ml_channel_count) if _ml_channel_count else None),
                connect_timeout_s=float(entry.get("connect_timeout_s", 5.0)),
                read_timeout_s=float(entry.get("read_timeout_s", 10.0)),
                mode=str(entry.get("mode", "averaged")),
                target_rate_hz=float(entry.get("target_rate_hz", 1.0)),
                burst_dir=_DATA_DIR / "multiline_bursts",
                mock=mock,
            )
        else:
            logger.warning("Неизвестный тип прибора '%s', пропущен", itype)
            continue

        configs.append(
            InstrumentConfig(driver=driver, poll_interval_s=poll_interval_s, resource_str=resource)
        )
        logger.info(
            "Прибор сконфигурирован: %s (%s), ресурс=%s, интервал=%.2f с",
            name,
            itype,
            resource,
            poll_interval_s,
        )

    return configs


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


def _push_if_finite(push: Callable[..., None], *args: Any) -> bool:
    """Forward a live reading into a rolling estimator, dropping non-finite samples.

    HI-2/ME-15: drivers emit value=NaN on SENSOR_ERROR/TIMEOUT and the
    scheduler still publishes those readings. One NaN inside an OLS window
    makes the slope undefined (rate_estimator returns None), blinding the
    estimator for up to the whole window length (~120 s / ~1 h). The last
    positional argument is the reading value; NaN/±inf samples are dropped
    (not forwarded) so they never enter the rolling window.

    Returns True when the sample was forwarded to ``push``.
    """
    if not math.isfinite(args[-1]):
        return False
    push(*args)
    return True


# ---------------------------------------------------------------------------
# Основной цикл
# ---------------------------------------------------------------------------


async def _run_engine(*, mock: bool = False) -> None:
    """Инициализировать и запустить все подсистемы engine."""
    start_ts = time.monotonic()
    logger.info("═══ CryoDAQ Engine запускается ═══")

    # --- Конфигурация путей (*.local.yaml приоритетнее *.yaml) ---
    def _cfg(name: str) -> Path:
        local = _CONFIG_DIR / f"{name}.local.yaml"
        return local if local.exists() else _CONFIG_DIR / f"{name}.yaml"

    instruments_cfg = _cfg("instruments")
    alarms_cfg = _cfg("alarms")
    interlocks_cfg = _cfg("interlocks")
    housekeeping_cfg = _cfg("housekeeping")
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
    driver_configs = _load_drivers(instruments_cfg, mock=mock, calibration_store=calibration_store)
    drivers_by_name = {cfg.driver.name: cfg.driver for cfg in driver_configs}

    # Keithley driver (нужен для SafetyManager)
    keithley_driver = None
    for cfg in driver_configs:
        if hasattr(cfg.driver, "emergency_off"):
            keithley_driver = cfg.driver
            break

    # SafetyManager — создаётся ПЕРВЫМ
    safety_cfg = _cfg("safety")
    safety_manager = SafetyManager(
        safety_broker,
        keithley_driver=keithley_driver,
        mock=mock,
        data_broker=broker,
    )
    safety_manager.load_config(safety_cfg)

    housekeeping_raw = load_housekeeping_config(housekeeping_cfg)
    # Phase 2b Codex H.1: merge legacy alarms.yaml/interlocks.yaml protection
    # patterns with the modern alarms_v3.yaml critical channels. Without this
    # the throttle thins critical channels even though alarms_v3 marks them
    # CRITICAL.
    legacy_patterns = load_protected_channel_patterns(alarms_cfg, interlocks_cfg)
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

    # SQLite — persistence-first: writer создаётся ДО scheduler
    writer = SQLiteWriter(_DATA_DIR)
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

    # H.6: wire safety fault → operator_log machine event
    async def _safety_fault_log_callback(
        source: str,
        message: str,
        channel: str = "",
        value: float = 0.0,
    ) -> None:
        entry = await writer.append_operator_log(
            message=message,
            author=source,
            source="machine",
            tags=("safety_fault", channel) if channel else ("safety_fault",),
        )
        # Codex followup: publish to broker so live consumers (GUI, web)
        # see safety faults without waiting for SQLite refresh.
        try:
            await _publish_operator_log_entry(broker, entry)
        except Exception as exc:
            logger.error("Failed to publish safety fault operator_log entry: %s", exc)

    safety_manager._fault_log_callback = _safety_fault_log_callback

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
        drain_timeout_s=safety_manager._config.scheduler_drain_timeout_s,
    )
    for cfg in driver_configs:
        scheduler.add(cfg)

    # ZMQ PUB
    zmq_queue = await broker.subscribe("zmq_publisher")
    zmq_pub = ZMQPublisher()

    # Alarm Engine
    alarm_engine = AlarmEngine(broker)
    if alarms_cfg.exists():
        alarm_engine.load_config(alarms_cfg)
    else:
        logger.warning("Файл тревог не найден: %s", alarms_cfg)

    # Interlock Engine — действия делегируются SafetyManager.
    # Phase 2a Codex I.1: the actions-dict callables are kept as no-ops for
    # backwards compatibility with InterlockEngine's required interface, but
    # the REAL safety routing happens via trip_handler which receives the
    # full (condition, reading) context. Without this the action name and
    # channel would be discarded and stop_source would behave as emergency_off.
    async def _interlock_noop() -> None:
        return None

    interlock_actions: dict[str, Any] = {
        "emergency_off": _interlock_noop,
        "stop_source": _interlock_noop,
    }

    async def _interlock_trip_handler(condition: Any, reading: Any) -> None:
        # SAFETY (Phase 2a Codex P1): the actions-dict callables are no-ops,
        # so this handler is the SOLE path that triggers a SafetyManager
        # response. If anything raises here, InterlockEngine._trip will
        # log-and-swallow → fail-open. We catch ourselves and escalate to
        # a guaranteed _fault as a last resort. _fault is unlocked and
        # idempotent on the Keithley side (verified Phase 1).
        try:
            await safety_manager.on_interlock_trip(
                interlock_name=condition.name,
                channel=reading.channel,
                value=float(reading.value) if reading.value is not None else 0.0,
                action=condition.action,
            )
        except Exception as exc:
            logger.critical(
                "INTERLOCK trip_handler FAILED for '%s' (action=%s): %s — "
                "escalating to guaranteed fault.",
                condition.name,
                condition.action,
                exc,
                exc_info=True,
            )
            try:
                # v0.55.12 — public latch_fault() replaces the private
                # _fault() call (Codex audit SCOPE 1.1 follow-up).
                await safety_manager.latch_fault(
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

    interlock_engine = InterlockEngine(
        broker,
        actions=interlock_actions,
        trip_handler=_interlock_trip_handler,
    )
    interlock_engine.load_config(interlocks_cfg)

    # ExperimentManager
    experiment_manager = ExperimentManager(
        data_dir=_DATA_DIR,
        instruments_config=instruments_cfg,
        templates_dir=_CONFIG_DIR / "experiment_templates",
    )

    # F31: sinks foundation (vault + webhooks). Local override beats base.
    from cryodaq.sinks import SinkRegistry  # local import keeps engine cold-start fast

    _sink_cfg_path = _CONFIG_DIR / "sinks.local.yaml"
    if not _sink_cfg_path.exists():
        _sink_cfg_path = _CONFIG_DIR / "sinks.yaml"
    sink_registry = SinkRegistry()
    sink_registry.load_config(_sink_cfg_path)

    event_bus = EventBus()
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
    _alarm_v2_setpoint = ExperimentSetpointProvider(
        experiment_manager, _alarm_v2_engine_cfg.setpoints
    )
    alarm_v2_evaluator = AlarmEvaluator(
        _alarm_v2_state_tracker, _alarm_v2_rate, _alarm_v2_phase, _alarm_v2_setpoint
    )
    alarm_v2_state_mgr = AlarmStateManager()
    if _alarm_v2_configs:
        logger.info("Alarm Engine v2: загружено %d алармов", len(_alarm_v2_configs))
    else:
        # A missing config file now raises AlarmConfigError (fail-closed, aborts
        # the engine), so this branch is reached only when the file exists and
        # parses but defines zero alarms — the message must reflect that.
        logger.info(
            "Alarm Engine v2: config/alarms_v3.yaml не содержит определений "
            "алармов — v2-движку нечего оценивать"
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
            # latches the safety FSM (Codex audit SCOPE 1 finding 1.1).
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
            )
        except Exception as exc:
            logger.warning("VacuumGuard: ошибка инициализации, отключён — %s", exc)
    else:
        logger.info("VacuumGuard: отключён в конфиге")

    # --- Sensor Diagnostics Engine ---
    _plugins_cfg_path = _cfg("plugins")
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
        _sd_alarm_publisher = (
            alarm_v2_state_mgr
            if _sd_cfg.get("alarm_publishing_enabled", True)
            else None
        )
        sensor_diag = SensorDiagnosticsEngine(
            config=_sd_cfg,
            alarm_publisher=_sd_alarm_publisher,
            warning_duration_s=float(_sd_cfg.get("warning_duration_s", 300.0)),
            critical_duration_s=float(_sd_cfg.get("critical_duration_s", 900.0)),
        )
        # Set display names from channel_manager
        sensor_diag.set_channel_names(
            {ch_id: _ch_mgr.get_display_name(ch_id) for ch_id in _ch_mgr.get_all()}
        )
        # v0.55.2 A4: tell the engine which channels are cryogenic so warm
        # references (calibration, flange, vacuum case, structural) don't
        # get scored against cryogenic noise/drift thresholds.
        sensor_diag.set_channel_cold_map(
            {
                ch_id: bool(info.get("is_cold", True))
                for ch_id, info in _ch_mgr.get_all().items()
            }
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
    )

    async def _track_runtime_signals() -> None:
        queue = await broker.subscribe("adaptive_throttle_runtime", maxsize=2000)
        try:
            while True:
                adaptive_throttle.observe_runtime_signal(await queue.get())
        except asyncio.CancelledError:
            return

    async def _alarm_v2_feed_readings() -> None:
        """Подписаться на DataBroker и кормить v2 channel_state + rate_estimator."""
        queue = await broker.subscribe("alarm_v2_state_feed", maxsize=2000)
        try:
            while True:
                reading: Reading = await queue.get()
                _alarm_v2_state_tracker.update(reading)
                # HI-2: drop NaN/inf so a flapping sensor can't poison the OLS window
                _push_if_finite(
                    _alarm_v2_rate.push,
                    reading.channel,
                    reading.timestamp.timestamp(),
                    reading.value,
                )
        except asyncio.CancelledError:
            return

    # Strong-ref set for fire-and-forget Telegram dispatch tasks.
    # Without this the loop only weak-refs tasks and GC can drop a pending
    # alarm notification mid-flight. See DEEP_AUDIT_CC.md A.1/A.2/I.2.
    _alarm_dispatch_tasks: set[asyncio.Task] = set()

    async def _alarm_v2_tick() -> None:
        """Периодически вычислять алармы v2 и диспетчеризировать события."""
        poll_s = _alarm_v2_engine_cfg.poll_interval_s
        while True:
            await asyncio.sleep(poll_s)
            if not _alarm_v2_configs:
                continue
            current_phase = _alarm_v2_phase.get_current_phase()
            for alarm_cfg in _alarm_v2_configs:
                try:
                    # Phase-filter -> evaluate -> process. Shared with tests via
                    # cryodaq.core.alarm_v2.tick_alarm so suppression is covered
                    # by the real production logic. Out-of-phase returns
                    # (None, None) after clearing, so nothing dispatches below.
                    event, transition = tick_alarm(
                        alarm_cfg, current_phase, alarm_v2_evaluator, alarm_v2_state_mgr
                    )
                    if transition == "TRIGGERED" and event is not None:
                        # GUI polls via alarm_v2_status command; optionally notify via Telegram
                        if "telegram" in alarm_cfg.notify and telegram_bot is not None:
                            msg = f"⚠ [{event.level}] {event.alarm_id}\n{event.message}"
                            t = asyncio.create_task(
                                telegram_bot._send_to_all(msg),
                                name=f"alarm_v2_tg_{alarm_cfg.alarm_id}",
                            )
                            _alarm_dispatch_tasks.add(t)
                            t.add_done_callback(_alarm_dispatch_tasks.discard)
                        await event_bus.publish(
                            EngineEvent(
                                event_type="alarm_fired",
                                timestamp=datetime.now(UTC),
                                payload={
                                    "alarm_id": event.alarm_id,
                                    "level": event.level,
                                    "message": event.message,
                                    "channels": event.channels,
                                    "values": event.values,
                                },
                                experiment_id=experiment_manager.active_experiment_id,
                            )
                        )
                    elif transition == "CLEARED":
                        await event_bus.publish(
                            EngineEvent(
                                event_type="alarm_cleared",
                                timestamp=datetime.now(UTC),
                                payload={"alarm_id": alarm_cfg.alarm_id},
                                experiment_id=experiment_manager.active_experiment_id,
                            )
                        )
                except Exception as exc:
                    logger.error("Alarm v2 tick error %s: %s", alarm_cfg.alarm_id, exc)

    # --- Sensor diagnostics feed + tick tasks ---
    async def _sensor_diag_feed() -> None:
        """Feed readings into SensorDiagnosticsEngine buffers."""
        if sensor_diag is None:
            return
        queue = await broker.subscribe("sensor_diag_feed", maxsize=2000)
        try:
            while True:
                reading: Reading = await queue.get()
                # HI-2: drop NaN/inf so error readings don't poison diagnostics buffers
                _push_if_finite(
                    sensor_diag.push,
                    reading.channel,
                    reading.timestamp.timestamp(),
                    reading.value,
                )
        except asyncio.CancelledError:
            return

    async def _sensor_diag_tick() -> None:
        """Periodically recompute sensor diagnostics and dispatch alarm notifications."""
        if sensor_diag is None:
            return
        interval = _sd_cfg.get("update_interval_s", 10)
        # v0.55.5: default False — sensor-health alarms route to GUI only
        # by policy; the hourly periodic_report carries a digest section.
        _notify_telegram = _sd_cfg.get("notify_telegram", False)
        while True:
            await asyncio.sleep(interval)
            try:
                new_events = sensor_diag.update()
                if _notify_telegram and telegram_bot is not None and new_events:
                    aggregation_threshold = _sd_cfg.get("aggregation_threshold", 3)
                    # F20 aggregation handled by _format_diag_telegram_messages.
                    for _tg_name, _tg_msg in _format_diag_telegram_messages(
                        new_events, aggregation_threshold
                    ):
                        t = asyncio.create_task(
                            telegram_bot._send_to_all(_tg_msg),
                            name=_tg_name,
                        )
                        _alarm_dispatch_tasks.add(t)
                        t.add_done_callback(_alarm_dispatch_tasks.discard)
                for _sd_ev in new_events:
                    if _sd_ev.level.upper() == "CRITICAL":
                        await event_bus.publish(
                            EngineEvent(
                                event_type="sensor_anomaly_critical",
                                timestamp=datetime.now(UTC),
                                payload={
                                    "alarm_id": _sd_ev.alarm_id,
                                    "level": _sd_ev.level,
                                    "channels": _sd_ev.channels,
                                    "values": _sd_ev.values,
                                    "message": _sd_ev.message,
                                },
                                experiment_id=experiment_manager.active_experiment_id,
                            )
                        )
            except Exception as exc:
                logger.error("SensorDiagnostics tick error: %s", exc)

    # --- Vacuum trend feed + tick tasks ---
    async def _vacuum_trend_feed() -> None:
        """Feed pressure readings into VacuumTrendPredictor."""
        if vacuum_trend is None:
            return
        pressure_channel = _vt_cfg.get("pressure_channel", "")
        queue = await broker.subscribe("vacuum_trend_feed", maxsize=2000)
        try:
            while True:
                reading: Reading = await queue.get()
                # Accept readings from the pressure channel or any mbar-unit reading
                if pressure_channel and reading.channel != pressure_channel:
                    if reading.unit != "mbar":
                        continue
                elif not pressure_channel and reading.unit != "mbar":
                    continue
                # HI-2/ME-15: VacuumTrendPredictor.push only rejects P <= 0,
                # so NaN would slip through — drop non-finite here.
                _push_if_finite(vacuum_trend.push, reading.timestamp.timestamp(), reading.value)
        except asyncio.CancelledError:
            return

    async def _vacuum_trend_tick() -> None:
        """Periodically recompute vacuum trend prediction."""
        if vacuum_trend is None:
            return
        interval = _vt_cfg.get("update_interval_s", 30)
        while True:
            await asyncio.sleep(interval)
            try:
                vacuum_trend.update()
            except Exception as exc:
                logger.error("VacuumTrendPredictor tick error: %s", exc)

    async def _leak_rate_feed() -> None:
        """Feed pressure readings into LeakRateEstimator; auto-finalize on window expiry."""
        pressure_channel = _vt_cfg.get("pressure_channel", "")
        queue = await broker.subscribe("leak_rate_feed", maxsize=500)
        try:
            while True:
                reading: Reading = await queue.get()
                if pressure_channel and reading.channel != pressure_channel:
                    continue
                if reading.unit != "mbar":
                    continue
                if not leak_rate_estimator.is_active:
                    continue
                leak_rate_estimator.add_sample(reading.timestamp, reading.value)
                if leak_rate_estimator.should_finalize():
                    try:
                        result = leak_rate_estimator.finalize()
                        await event_logger.log_event(
                            "leak_rate",
                            f"Leak rate (auto): {result.leak_rate_mbar_l_per_s:.3e} mbar·L/s",
                        )
                    except (ValueError, Exception) as exc:  # noqa: BLE001
                        logger.error("Leak rate auto-finalize failed: %s", exc)
        except asyncio.CancelledError:
            return

    # v0.55.11 — auto-stop bookkeeping for multiline.burst_start. The
    # meta dict is populated by the helper (intent); the tasks dict is
    # populated at the dispatch site (materialised on the engine loop).
    _multiline_burst_auto_stop_meta: dict[str, dict[str, Any]] = {}
    _multiline_burst_auto_stop_tasks: dict[str, asyncio.Task[None]] = {}

    # Обработчик команд от GUI — через SafetyManager
    async def _handle_gui_command(cmd: dict[str, Any]) -> dict[str, Any]:
        action = cmd.get("cmd", "")
        try:
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
                        await event_logger.log_event(
                            "keithley", f"\u26a0 Keithley {ch}: аварийное отключение"
                        )
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
            if action == "alarm_acknowledge":
                name = cmd.get("alarm_name", "")
                try:
                    await alarm_engine.acknowledge(name)
                    return {"ok": True, "action": "alarm_acknowledge"}
                except (KeyError, ValueError) as exc:
                    return {"ok": False, "error": str(exc)}
            if action == "interlock_acknowledge":
                # F24: re-arm a tripped interlock after operator clears the condition.
                name = cmd.get("interlock_name", "")
                try:
                    interlock_engine.acknowledge(name)
                    return {"ok": True, "action": "interlock_acknowledge", "interlock_name": name}
                except KeyError as exc:
                    return {"ok": False, "error": str(exc)}
            _leak_resp = await _handle_leak_rate_command(
                action, cmd, leak_rate_estimator, _leak_cfg, event_logger
            )
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
                    # ("actually interrupt") is not available. See Codex commit-7 review.
                    try:
                        result = await asyncio.wait_for(
                            experiment_call,
                            timeout=_EXPERIMENT_STATUS_TIMEOUT_S,
                        )
                    except TimeoutError as exc:
                        raise TimeoutError(
                            f"experiment_status timeout ({_EXPERIMENT_STATUS_TIMEOUT_S:g}s)"
                        ) from exc
                else:
                    result = await experiment_call
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
                                _meta_path = (
                                    experiment_manager.data_dir
                                    / "experiments"
                                    / _exp_id
                                    / "metadata.json"
                                )
                                # H2: offload metadata read to thread.
                                _metadata = await asyncio.to_thread(
                                    _load_experiment_metadata_sync, _meta_path
                                )
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
                            logger.warning(
                                "F31: sink dispatch setup failed: %s", _exc, exc_info=True
                            )
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
                    # operator advances away from cooldown (Codex audit
                    # SCOPE 1 finding 1.2) and clear its cold-start flag
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
                    if (
                        phase == "cooldown"
                        and _cooldown_alarm is not None
                        and _cooldown_alarm.is_auto_arm_enabled
                    ):
                        try:
                            armed = _cooldown_alarm.arm()
                            if not armed and _cooldown_alarm.cold_start_skipped:
                                # v0.55.12 — surface the skip explicitly so
                                # the operator log shows why auto-arm
                                # didn't engage on this phase entry.
                                logger.info(
                                    "CooldownAlarm: auto-arm skipped — "
                                    "cold-start detected"
                                )
                            else:
                                logger.info(
                                    "CooldownAlarm: auto-arm на phase=cooldown → %s",
                                    "ARMED" if armed else "FAILED (no model)",
                                )
                        except Exception as _exc:
                            logger.warning(
                                "CooldownAlarm: auto-arm ошибка: %s", _exc, exc_info=True
                            )
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
                return await _run_cooldown_history_command(
                    cmd, experiment_manager, writer
                )
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
                _t_cold_val = (
                    _t_cold_state.value
                    if _t_cold_state is not None and not _t_cold_state.is_stale
                    else None
                )
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
            if action == "assistant.query":
                # F34: Гемма chat overlay reuses F30 AssistantQueryAgent.
                return await _handle_assistant_query_command(_query_agent, cmd)
            if action == "rag.search":
                # v0.55.6 — knowledge-base GUI overlay calls this from
                # ZmqCommandWorker. Helper extracted for unit-testing.
                return await _handle_rag_search_command(_rag_searcher, cmd)
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
                if (
                    response.get("ok")
                    and action == "multiline.burst_start"
                    and response.get("duration_s") is not None
                ):
                    target_name = response.get("name", "")
                    duration_s = float(response["duration_s"])

                    async def _auto_stop(driver_name: str = target_name,
                                         delay_s: float = duration_s) -> None:
                        try:
                            await asyncio.sleep(delay_s)
                            d = drivers_by_name.get(driver_name)
                            if d is None:
                                return
                            try:
                                path = await d.burst_stop(
                                    experiments_root=_DATA_DIR / "experiments",
                                )
                                logger.info(
                                    "MultiLine '%s' burst auto-stopped after %.1fs → %s",
                                    driver_name, delay_s, path,
                                )
                            except Exception as exc:  # noqa: BLE001
                                logger.error(
                                    "MultiLine '%s' auto-stop failed: %s",
                                    driver_name, exc, exc_info=True,
                                )
                        finally:
                            _multiline_burst_auto_stop_tasks.pop(driver_name, None)

                    _t = asyncio.create_task(
                        _auto_stop(),
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
                # v0.55.7.1 PHASE 8 — operator-driven «Обновить индекс»
                # in KnowledgeBasePanel. Single-instance enforced inside
                # the helper; concurrent click rejected. State machine
                # exposed via rag.rebuild_status poll.
                return await _handle_rag_rebuild_command(
                    action,
                    cmd,
                    db_path=_rag_rebuild_db_path,
                    embeddings_client=_rag_rebuild_embeddings,
                    knowledge_dir=_rag_rebuild_knowledge_dir,
                    experiments_dir=_DATA_DIR / "experiments",
                    sqlite_path=None,
                    repo_root=_PROJECT_ROOT,
                )
            return {"ok": False, "error": f"unknown command: {action}"}
        except Exception as exc:
            logger.error("Ошибка выполнения команды '%s': %s", action, exc)
            return {"ok": False, "error": str(exc)}

    cmd_server = ZMQCommandServer(handler=_handle_gui_command)

    # Plugin Pipeline
    plugin_pipeline = PluginPipeline(broker, _PLUGINS_DIR)

    # --- CooldownService (прогноз охлаждения) ---
    cooldown_service: Any = None
    cooldown_cfg_path = _cfg("cooldown")
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
                )
                logger.info("CooldownService создан")
                # v0.55.4 A2: hand the cooldown_service-owned
                # SteadyStatePredictor to CooldownAlarm so its WATCHING
                # path can short-circuit when the system is quasi-steady.
                if _cooldown_alarm is not None:
                    _cooldown_alarm.set_steady_state_predictor(
                        cooldown_service._ss_predictor
                    )
        except Exception as exc:
            logger.error("Ошибка создания CooldownService: %s", exc)

    # --- Уведомления (один раз разбираем YAML) ---
    periodic_reporter: PeriodicReporter | None = None
    telegram_bot: TelegramCommandBot | None = None
    _photo_handler: CompositionPhotoHandler | None = None
    escalation_service: EscalationService | None = None
    notifications_cfg = _cfg("notifications")
    if notifications_cfg.exists():
        try:
            with notifications_cfg.open(encoding="utf-8") as fh:
                notif_raw: dict[str, Any] = yaml.safe_load(fh) or {}

            tg_cfg = notif_raw.get("telegram", {})
            bot_token = str(tg_cfg.get("bot_token", ""))
            token_valid = bot_token and bot_token != "YOUR_BOT_TOKEN_HERE"
            verify_ssl = bool(tg_cfg.get("verify_ssl", True))

            # PeriodicReporter
            pr_cfg = notif_raw.get("periodic_report", {})
            if pr_cfg.get("enabled", False) and token_valid:
                periodic_reporter = PeriodicReporter(
                    broker,
                    alarm_engine,
                    bot_token=bot_token,
                    chat_id=tg_cfg.get("chat_id", 0),
                    report_interval_s=float(pr_cfg.get("report_interval_s", 1800)),
                    chart_hours=float(pr_cfg.get("chart_hours", 2.0)),
                    include_channels=pr_cfg.get("include_channels"),
                )
                logger.info("PeriodicReporter создан")

            # TelegramCommandBot
            cmd_cfg = notif_raw.get("commands", {})
            commands_enabled = bool(cmd_cfg.get("enabled", False)) and token_valid
            if commands_enabled:
                allowed_raw = (
                    tg_cfg.get("allowed_chat_ids") or cmd_cfg.get("allowed_chat_ids") or []
                )
                allowed_ids = [int(x) for x in allowed_raw]
                # Phase 2b Codex K.1 — TelegramCommandBot raises on empty list,
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
                        alarm_engine,
                        bot_token=bot_token,
                        allowed_chat_ids=allowed_ids,
                        poll_interval_s=float(cmd_cfg.get("poll_interval_s", 2.0)),
                        command_handler=_handle_gui_command,
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

    # --- AssistantLiveAgent (Гемма local LLM agent) ---
    _agent_cfg_path = _CONFIG_DIR / "agent.yaml"
    _gemma_config: AssistantConfig | None = None
    gemma_agent: AssistantLiveAgent | None = None
    if _agent_cfg_path.exists():
        try:
            _gemma_config = AssistantConfig.from_yaml_path(_agent_cfg_path)
            if _gemma_config.enabled:
                _gemma_ollama = OllamaClient(
                    base_url=_gemma_config.ollama_base_url,
                    default_model=_gemma_config.default_model,
                    timeout_s=_gemma_config.timeout_s,
                )
                # v0.55.5 — pass a lazy snapshot fn so the hourly periodic
                # report can include a sensor-health digest without coupling
                # ContextBuilder to the SensorDiagnosticsEngine instance.
                _sd_for_ctx = sensor_diag
                _gemma_ctx = ContextBuilder(
                    writer,
                    experiment_manager,
                    sensor_diag_provider=(
                        _sd_for_ctx.get_summary if _sd_for_ctx is not None else None
                    ),
                )
                _gemma_audit = AuditLogger(
                    _DATA_DIR / "agents" / "assistant" / "audit",
                    enabled=_gemma_config.audit_enabled,
                    retention_days=_gemma_config.audit_retention_days,
                )
                _gemma_router = OutputRouter(
                    telegram_bot=telegram_bot,
                    event_logger=event_logger,
                    event_bus=event_bus,
                    brand_name=_gemma_config.brand_name,
                    brand_emoji=_gemma_config.brand_emoji,
                )
                gemma_agent = AssistantLiveAgent(
                    config=_gemma_config,
                    event_bus=event_bus,
                    ollama_client=_gemma_ollama,
                    context_builder=_gemma_ctx,
                    audit_logger=_gemma_audit,
                    output_router=_gemma_router,
                )
                logger.info(
                    "AssistantLiveAgent (Гемма): инициализирован, модель=%s",
                    _gemma_config.default_model,
                )
        except Exception as _gemma_exc:
            logger.warning("AssistantLiveAgent: ошибка инициализации — %s", _gemma_exc, exc_info=True)  # noqa: E501 — single RU log call, splitting hurts grep-ability
    else:
        logger.info("AssistantLiveAgent: config/agent.yaml не найден, агент отключён")

    # --- F32 RAG searcher (relocated from post-QueryAdapters in v0.55.7 so
    #     the AssistantQueryAgent KNOWLEDGE_QUERY adapter can wrap the same
    #     RagSearcher instance the GUI knowledge-base overlay already uses).
    _rag_searcher: Any = None
    # v0.55.7.1: handles for the rebuild dispatch helper. Populated
    # below when the searcher block successfully resolves config.
    _rag_rebuild_db_path: Path | None = None
    _rag_rebuild_embeddings: Any | None = None
    _rag_rebuild_knowledge_dir: Path | None = None
    try:
        from cryodaq.agents.rag.embeddings import EmbeddingsClient  # noqa: PLC0415
        from cryodaq.agents.rag.searcher import RagSearcher  # noqa: PLC0415

        # v0.55.14 (Codex audit SCOPE 6 finding 6.8) — config-resolution
        # priority: rag.local.yaml → rag.yaml → rag.yaml.example.
        # The v0.55.7 ship report claimed an example fallback existed
        # but the code didn't implement it; now it does. The example
        # ships in-repo so RAG defaults are always available.
        _rag_cfg_path = _CONFIG_DIR / "rag.local.yaml"
        _rag_cfg_source = "rag.local.yaml"
        if not _rag_cfg_path.exists():
            _rag_cfg_path = _CONFIG_DIR / "rag.yaml"
            _rag_cfg_source = "rag.yaml"
        if not _rag_cfg_path.exists():
            _rag_cfg_path = _CONFIG_DIR / "rag.yaml.example"
            _rag_cfg_source = "rag.yaml.example (defaults)"
        if _rag_cfg_path.exists():
            import yaml as _yaml  # noqa: PLC0415

            _rag_raw = _yaml.safe_load(_rag_cfg_path.read_text(encoding="utf-8")) or {}
            _rag_cfg = _rag_raw.get("rag", {})
            _rag_db_path = Path(str(_rag_cfg.get("db_path", "data/rag_index"))).expanduser()  # noqa: ASYNC240 — .expanduser() does no I/O; one-time startup config load
            _rag_table = str(_rag_cfg.get("table_name", "cryodaq_corpus"))
            _rag_emb_url = str(_rag_cfg.get("ollama_base_url", "http://localhost:11434"))
            # v0.55.7.1: default fallback aligned с modernized stack —
            # qwen3-embedding:0.6b (1024d). Older v0.55.7 default
            # multilingual-e5-small (384d) deprecated due к Ollama
            # 0.23+ runtime incompatibility for community uploads.
            _rag_emb_model = str(_rag_cfg.get("embedding_model", "qwen3-embedding:0.6b"))
            _rag_knowledge_dir = Path(  # noqa: ASYNC240 — .expanduser() does no I/O; one-time startup config load
                str(_rag_cfg.get("knowledge_dir", _DATA_DIR / "knowledge"))
            ).expanduser()
            # v0.55.7.1: create searcher unconditionally — LanceDB
            # connects lazily on the first .search() call, so an
            # absent db_path is fine. Bootstrap (below) will populate
            # the index from the bundled corpus в фоне; the searcher
            # itself returns [] from search() until the table exists.
            _rag_db_path.mkdir(parents=True, exist_ok=True)
            _rag_emb = EmbeddingsClient(
                base_url=_rag_emb_url,
                model=_rag_emb_model,
            )
            _rag_searcher = RagSearcher(
                db_path=_rag_db_path,
                embeddings_client=_rag_emb,
                table_name=_rag_table,
            )
            # Hand off resolved paths к the rebuild dispatch helper.
            _rag_rebuild_db_path = _rag_db_path
            _rag_rebuild_embeddings = _rag_emb
            _rag_rebuild_knowledge_dir = _rag_knowledge_dir
            logger.info(
                "RAG searcher: инициализирован (config=%s, db=%s, table=%s, knowledge=%s)",
                _rag_cfg_source,
                _rag_db_path,
                _rag_table,
                _rag_knowledge_dir,
            )
            # v0.55.7.1 PHASE 6: fire-and-forget bootstrap. Engine
            # ready signal does NOT await this; the operator may
            # briefly see empty KnowledgeBasePanel during first boot
            # of a fresh deploy, then it populates без restart.
            asyncio.create_task(
                _bootstrap_rag_index_if_empty(
                    db_path=_rag_db_path,
                    embeddings_client=_rag_emb,
                    knowledge_dir=_rag_knowledge_dir,
                    experiments_dir=_DATA_DIR / "experiments",
                    sqlite_path=None,
                    repo_root=_PROJECT_ROOT,
                ),
                name="rag_bootstrap",
            )
        else:
            logger.info(
                "RAG searcher: ни rag.local.yaml/rag.yaml/rag.yaml.example "
                "не найдены — RAG отключён"
            )
    except Exception as _rag_exc:
        logger.warning("RAG searcher: ошибка инициализации — %s", _rag_exc)
        _rag_searcher = None

    # --- AssistantQueryAgent (F30 Live Query) ---
    _query_agent: Any = None
    _q_broker_snap: Any = None
    if _gemma_config is not None and _gemma_config.query_enabled:
        try:
            from cryodaq.agents.assistant.query.adapters.alarm_adapter import AlarmAdapter
            from cryodaq.agents.assistant.query.adapters.archive_adapter import ArchiveAdapter
            from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot
            from cryodaq.agents.assistant.query.adapters.composite_adapter import CompositeAdapter
            from cryodaq.agents.assistant.query.adapters.cooldown_adapter import CooldownAdapter
            from cryodaq.agents.assistant.query.adapters.experiment_adapter import ExperimentAdapter
            from cryodaq.agents.assistant.query.adapters.rag_adapter import RAGAdapter
            from cryodaq.agents.assistant.query.adapters.sqlite_adapter import SQLiteAdapter
            from cryodaq.agents.assistant.query.adapters.vacuum_adapter import VacuumAdapter
            from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
            from cryodaq.agents.assistant.query.schemas import QueryAdapters

            try:
                _q_ollama = _gemma_ollama
                _q_audit = _gemma_audit
            except NameError:
                _q_ollama = OllamaClient(
                    base_url=_gemma_config.ollama_base_url,
                    default_model=_gemma_config.default_model,
                    timeout_s=_gemma_config.timeout_s,
                )
                _q_audit = AuditLogger(
                    _DATA_DIR / "agents" / "assistant" / "audit",
                    enabled=_gemma_config.audit_enabled,
                )

            _q_broker_snap = BrokerSnapshot(broker, channel_manager=get_channel_manager())
            await _q_broker_snap.start()

            _q_cooldown = CooldownAdapter(cooldown_service)
            _q_vacuum = VacuumAdapter(vacuum_trend)
            _q_sqlite = SQLiteAdapter(writer)
            _q_alarms = AlarmAdapter(alarm_engine)
            _q_experiment = ExperimentAdapter(experiment_manager)
            _q_archive = ArchiveAdapter(experiment_manager, alarm_v2_state_mgr)
            _q_rag = RAGAdapter(_rag_searcher)
            _q_composite = CompositeAdapter(
                broker_snapshot=_q_broker_snap,
                cooldown=_q_cooldown,
                vacuum=_q_vacuum,
                alarms=_q_alarms,
                experiment=_q_experiment,
            )

            from cryodaq.agents.assistant.query.chart_dispatcher import (
                ChartDispatcher,  # noqa: PLC0415
            )

            _q_chart_dispatcher: ChartDispatcher | None = None
            if telegram_bot is not None:
                _q_chart_dispatcher = ChartDispatcher(
                    send_photo=telegram_bot.send_photo
                )

            _query_agent = AssistantQueryAgent(
                ollama_client=_q_ollama,
                audit_logger=_q_audit,
                config=_gemma_config,
                adapters=QueryAdapters(
                    broker_snapshot=_q_broker_snap,
                    cooldown=_q_cooldown,
                    vacuum=_q_vacuum,
                    sqlite=_q_sqlite,
                    alarms=_q_alarms,
                    experiment=_q_experiment,
                    composite=_q_composite,
                    archive=_q_archive,
                    rag=_q_rag,
                ),
                intent_model=_gemma_config.query_intent_model,
                format_model=_gemma_config.query_format_model,
                intent_temperature=_gemma_config.query_intent_temperature,
                format_temperature=_gemma_config.query_format_temperature,
                intent_timeout_s=_gemma_config.query_intent_timeout_s,
                format_timeout_s=_gemma_config.query_format_timeout_s,
                max_queries_per_chat_per_hour=_gemma_config.query_max_per_chat_per_hour,
                channel_manager=get_channel_manager(),
                chart_dispatcher=_q_chart_dispatcher,
            )

            if telegram_bot is not None:
                telegram_bot._query_agent = _query_agent
            logger.info("AssistantQueryAgent (F30): инициализирован")
        except Exception as _q_exc:
            logger.warning(
                "AssistantQueryAgent: ошибка инициализации — %s", _q_exc, exc_info=True
            )

    # --- Запуск всех подсистем ---
    await safety_manager.start()
    logger.info("SafetyManager запущен: состояние=%s", safety_manager.state.value)
    # writer уже запущен через start_immediate() выше
    await zmq_pub.start(zmq_queue)
    await cmd_server.start()
    await alarm_engine.start()
    await interlock_engine.start()
    await plugin_pipeline.start()
    if cooldown_service is not None:
        await cooldown_service.start()
    if periodic_reporter is not None:
        await periodic_reporter.start()
    if telegram_bot is not None:
        await telegram_bot.start()
    if _photo_handler is not None:
        await _photo_handler.start()
    if gemma_agent is not None:
        try:
            await gemma_agent.start()
        except Exception as _gemma_start_exc:
            logger.warning("AssistantLiveAgent: ошибка запуска — %s. Агент отключён.", _gemma_start_exc)  # noqa: E501 — single RU log call, splitting hurts grep-ability
            gemma_agent = None
    periodic_report_tick_task: asyncio.Task | None = None
    if _gemma_config is not None and _gemma_config.periodic_report_enabled:
        periodic_report_tick_task = asyncio.create_task(
            _periodic_report_tick(_gemma_config, event_bus, experiment_manager),
            name="periodic_report_tick",
        )
    await scheduler.start()
    throttle_task = asyncio.create_task(_track_runtime_signals(), name="adaptive_throttle_runtime")
    alarm_v2_feed_task = asyncio.create_task(_alarm_v2_feed_readings(), name="alarm_v2_feed")
    alarm_v2_tick_task: asyncio.Task | None = None
    if _alarm_v2_configs:
        alarm_v2_tick_task = asyncio.create_task(_alarm_v2_tick(), name="alarm_v2_tick")

    async def _cooldown_alarm_tick_loop() -> None:
        """Independent tick for CooldownAlarm at its own configured cadence (F-X v3)."""
        interval = float(_cooldown_cfg.get("eval_interval_s", 30))
        _last_triggered_id = "cooldown_alarm"
        while True:
            await asyncio.sleep(interval)
            try:
                transition = await _cooldown_alarm.tick()  # type: ignore[union-attr]
            except Exception as exc:
                logger.error("CooldownAlarm tick error: %s", exc)
                continue
            if transition == "TRIGGERED":
                _active = alarm_v2_state_mgr.get_active()
                # CooldownAlarm fires under "cooldown_alarm" OR "cooldown_watchdog"
                _ev = _active.get("cooldown_alarm") or _active.get("cooldown_watchdog")
                if _ev is not None:
                    _last_triggered_id = _ev.alarm_id
                    if telegram_bot is not None:
                        _pt = asyncio.create_task(
                            telegram_bot._send_to_all(
                                f"⚠ [{_ev.level}] {_ev.alarm_id}\n{_ev.message}"
                            ),
                            name=f"phys_alarm_tg_{_ev.alarm_id}",
                        )
                        _alarm_dispatch_tasks.add(_pt)
                        _pt.add_done_callback(_alarm_dispatch_tasks.discard)
                    await event_bus.publish(
                        EngineEvent(
                            event_type="alarm_fired",
                            timestamp=datetime.now(UTC),
                            payload={
                                "alarm_id": _ev.alarm_id,
                                "level": _ev.level,
                                "message": _ev.message,
                                "channels": _ev.channels,
                                "values": _ev.values,
                            },
                            experiment_id=experiment_manager.active_experiment_id,
                        )
                    )
            elif transition == "CLEARED":
                await event_bus.publish(
                    EngineEvent(
                        event_type="alarm_cleared",
                        timestamp=datetime.now(UTC),
                        payload={"alarm_id": _last_triggered_id},
                        experiment_id=experiment_manager.active_experiment_id,
                    )
                )

    async def _vacuum_guard_tick_loop() -> None:
        """Independent tick for VacuumGuard at its own configured cadence (F-X v3)."""
        interval = float(_vacuum_cfg.get("eval_interval_s", 30))
        while True:
            await asyncio.sleep(interval)
            try:
                transition = await _vacuum_guard.tick()  # type: ignore[union-attr]
            except Exception as exc:
                logger.error("VacuumGuard tick error: %s", exc)
                continue
            if transition == "TRIGGERED":
                _active = alarm_v2_state_mgr.get_active()
                _ev = _active.get("vacuum_guard")
                if _ev is not None:
                    if telegram_bot is not None:
                        _pt = asyncio.create_task(
                            telegram_bot._send_to_all(
                                f"⚠ [{_ev.level}] {_ev.alarm_id}\n{_ev.message}"
                            ),
                            name="phys_alarm_tg_vacuum_guard",
                        )
                        _alarm_dispatch_tasks.add(_pt)
                        _pt.add_done_callback(_alarm_dispatch_tasks.discard)
                    await event_bus.publish(
                        EngineEvent(
                            event_type="alarm_fired",
                            timestamp=datetime.now(UTC),
                            payload={
                                "alarm_id": _ev.alarm_id,
                                "level": _ev.level,
                                "message": _ev.message,
                                "channels": _ev.channels,
                                "values": _ev.values,
                            },
                            experiment_id=experiment_manager.active_experiment_id,
                        )
                    )
            elif transition == "CLEARED":
                await event_bus.publish(
                    EngineEvent(
                        event_type="alarm_cleared",
                        timestamp=datetime.now(UTC),
                        payload={"alarm_id": "vacuum_guard"},
                        experiment_id=experiment_manager.active_experiment_id,
                    )
                )

    cooldown_alarm_task: asyncio.Task | None = None
    vacuum_guard_task: asyncio.Task | None = None
    if _cooldown_alarm is not None:
        cooldown_alarm_task = asyncio.create_task(
            _cooldown_alarm_tick_loop(), name="cooldown_alarm_tick"
        )
    if _vacuum_guard is not None:
        vacuum_guard_task = asyncio.create_task(
            _vacuum_guard_tick_loop(), name="vacuum_guard_tick"
        )

    sd_feed_task: asyncio.Task | None = None
    sd_tick_task: asyncio.Task | None = None
    if sensor_diag is not None:
        sd_feed_task = asyncio.create_task(_sensor_diag_feed(), name="sensor_diag_feed")
        sd_tick_task = asyncio.create_task(_sensor_diag_tick(), name="sensor_diag_tick")
        # v0.55.5 — anchor the cold-start grace at the moment the feed
        # and tick tasks are actually live. Doing this here (rather than
        # in the constructor) avoids counting the engine bootstrap
        # window as part of the grace.
        sensor_diag.mark_engine_started()
    vt_feed_task: asyncio.Task | None = None
    vt_tick_task: asyncio.Task | None = None
    if vacuum_trend is not None:
        vt_feed_task = asyncio.create_task(_vacuum_trend_feed(), name="vacuum_trend_feed")
        vt_tick_task = asyncio.create_task(_vacuum_trend_tick(), name="vacuum_trend_tick")
    leak_rate_feed_task = asyncio.create_task(_leak_rate_feed(), name="leak_rate_feed")
    await housekeeping_service.start()

    # Watchdog
    watchdog_task = asyncio.create_task(
        _watchdog(broker, scheduler, writer, start_ts),
        name="engine_watchdog",
    )

    # DiskMonitor — also wires the writer so disk-recovery can clear the
    # _disk_full flag (Phase 2a H.1).
    disk_monitor = DiskMonitor(data_dir=_DATA_DIR, broker=broker, sqlite_writer=writer)
    await disk_monitor.start()

    logger.info(
        "═══ CryoDAQ Engine запущен ═══ | приборов=%d | тревог=%d | блокировок=%d | mock=%s",
        len(driver_configs),
        len(alarm_engine.get_state()),
        len(interlock_engine.get_state()),
        mock,
    )

    # --- Ожидание сигнала завершения ---
    shutdown_event = asyncio.Event()

    def _request_shutdown() -> None:
        logger.info("Получен сигнал завершения")
        shutdown_event.set()

    # Регистрация обработчиков сигналов
    loop = asyncio.get_running_loop()
    if sys.platform != "win32":
        loop.add_signal_handler(signal.SIGINT, _request_shutdown)
        loop.add_signal_handler(signal.SIGTERM, _request_shutdown)
    else:
        # Windows: signal.signal работает только в главном потоке
        signal.signal(signal.SIGINT, lambda *_: _request_shutdown())

    await shutdown_event.wait()

    # --- Корректное завершение ---
    logger.info("═══ Завершение CryoDAQ Engine ═══")

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
    if periodic_report_tick_task is not None:
        periodic_report_tick_task.cancel()
        try:
            await periodic_report_tick_task
        except asyncio.CancelledError:
            pass
    leak_rate_feed_task.cancel()
    try:
        await leak_rate_feed_task
    except asyncio.CancelledError:
        pass

    # Порядок: scheduler → plugins → alarms → interlocks → writer → zmq
    await scheduler.stop()
    logger.info("Планировщик остановлен")

    await plugin_pipeline.stop()
    logger.info("Пайплайн плагинов остановлен")

    if cooldown_service is not None:
        await cooldown_service.stop()
        logger.info("CooldownService остановлен")

    if periodic_reporter is not None:
        await periodic_reporter.stop()
        logger.info("PeriodicReporter остановлен")

    if gemma_agent is not None:
        await gemma_agent.stop()
        logger.info("AssistantLiveAgent (Гемма) остановлен")

    if _q_broker_snap is not None:
        await _q_broker_snap.stop()
        logger.info("QueryAgent BrokerSnapshot остановлен")

    if _photo_handler is not None:
        await _photo_handler.stop()
        logger.info("CompositionPhotoHandler остановлен")

    if telegram_bot is not None:
        await telegram_bot.stop()
        logger.info("TelegramCommandBot остановлен")

    await alarm_engine.stop()
    logger.info("Движок тревог остановлен")

    await interlock_engine.stop()
    logger.info("Движок блокировок остановлен")

    await safety_manager.stop()
    logger.info("SafetyManager остановлен: состояние=%s", safety_manager.state.value)

    await disk_monitor.stop()
    logger.info("DiskMonitor остановлен")

    await housekeeping_service.stop()
    logger.info("HousekeepingService остановлен")

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
        ) as exc:
            labels = {
                SafetyConfigError: "safety",
                AlarmConfigError: "alarm",
                InterlockConfigError: "interlock",
                HousekeepingConfigError: "housekeeping",
                ChannelConfigError: "channel",
            }
            label = labels.get(type(exc), "config")
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
