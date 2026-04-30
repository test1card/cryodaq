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
import os
import signal
import sys
import time
from datetime import UTC, datetime

# Windows: pyzmq требует SelectorEventLoop (не Proactor)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from pathlib import Path
from typing import Any

import yaml

from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant.live.context_builder import ContextBuilder
from cryodaq.agents.assistant.live.agent import AssistantLiveAgent, AssistantConfig
from cryodaq.agents.assistant.shared.ollama_client import OllamaClient
from cryodaq.agents.assistant.live.output_router import OutputRouter
from cryodaq.analytics.calibration import CalibrationStore
from cryodaq.analytics.leak_rate import LeakRateEstimator
from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor
from cryodaq.core.alarm import AlarmEngine
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
from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyConfigError, SafetyManager
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine
from cryodaq.core.smu_channel import normalize_smu_channel
from cryodaq.core.zmq_bridge import ZMQCommandServer, ZMQPublisher
from cryodaq.drivers.base import Reading
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
_LOG_GET_TIMEOUT_S = 1.5
_EXPERIMENT_STATUS_TIMEOUT_S = 1.5


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


async def _run_keithley_command(
    action: str,
    cmd: dict[str, Any],
    safety_manager: SafetyManager,
) -> dict[str, Any]:
    """Dispatch channel-scoped Keithley commands to SafetyManager."""
    channel = cmd.get("channel")

    if action == "keithley_start":
        smu_channel = normalize_smu_channel(channel)
        p = float(cmd.get("p_target", 0))
        v = float(cmd.get("v_comp", 40))
        i = float(cmd.get("i_comp", 1.0))
        return await safety_manager.request_run(p, v, i, channel=smu_channel)

    if action == "keithley_stop":
        smu_channel = normalize_smu_channel(channel)
        return await safety_manager.request_stop(channel=smu_channel)

    if action == "keithley_emergency_off":
        smu_channel = normalize_smu_channel(channel)
        return await safety_manager.emergency_off(channel=smu_channel)

    if action == "keithley_set_target":
        smu_channel = normalize_smu_channel(cmd.get("channel"))
        p = float(cmd.get("p_target", 0))
        return await safety_manager.update_target(p, channel=smu_channel)

    if action == "keithley_set_limits":
        smu_channel = normalize_smu_channel(cmd.get("channel"))
        return await safety_manager.update_limits(
            channel=smu_channel,
            v_comp=float(cmd["v_comp"]) if cmd.get("v_comp") is not None else None,
            i_comp=float(cmd["i_comp"]) if cmd.get("i_comp") is not None else None,
        )

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
        json_path = calibration_store.export_curve_json(
            sensor_id,
            Path(str(cmd.get("json_path")).strip())
            if str(cmd.get("json_path", "")).strip()
            else None,
        )
        table_path = calibration_store.export_curve_table(
            sensor_id,
            path=Path(str(cmd.get("table_path")).strip())
            if str(cmd.get("table_path", "")).strip()
            else None,
            points=int(cmd.get("points", 200)),
        )
        curve_cof_path = calibration_store.export_curve_cof(
            sensor_id,
            path=Path(str(cmd.get("curve_cof_path")).strip())
            if str(cmd.get("curve_cof_path", "")).strip()
            else None,
        )
        curve_340_path = calibration_store.export_curve_340(
            sensor_id,
            path=Path(str(cmd.get("curve_340_path")).strip())
            if str(cmd.get("curve_340_path", "")).strip()
            else None,
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
        curve = calibration_store.import_curve_file(
            Path(raw_path),
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
            except Exception:
                pass
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

            driver = Keithley2604B(name, resource, mock=mock)
        elif itype == "thyracont_vsp63d":
            from cryodaq.drivers.instruments.thyracont_vsp63d import ThyracontVSP63D

            baudrate = int(entry.get("baudrate", 9600))
            validate_checksum = bool(entry.get("validate_checksum", True))
            driver = ThyracontVSP63D(
                name, resource, baudrate=baudrate, validate_checksum=validate_checksum, mock=mock
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
                await safety_manager._fault(
                    f"Interlock trip_handler failed: {condition.name}: {exc}",
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
        logger.info("Alarm Engine v2: config/alarms_v3.yaml не найден, v2 отключён")

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
                _alarm_v2_rate.push(
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
                # Проверка фазового фильтра
                if alarm_cfg.phase_filter is not None:
                    if current_phase not in alarm_cfg.phase_filter:
                        # Вне фазы — явно очистить если был активен
                        alarm_v2_state_mgr.process(alarm_cfg.alarm_id, None, alarm_cfg.config)
                        continue
                try:
                    _active_alarms = alarm_v2_state_mgr.get_active()
                    _active_event = _active_alarms.get(alarm_cfg.alarm_id)
                    event = alarm_v2_evaluator.evaluate(
                        alarm_cfg.alarm_id,
                        alarm_cfg.config,
                        is_active=_active_event is not None,
                        active_channels=(
                            frozenset(_active_event.channels)
                            if _active_event is not None
                            else None
                        ),
                    )
                    transition = alarm_v2_state_mgr.process(
                        alarm_cfg.alarm_id, event, alarm_cfg.config
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
                sensor_diag.push(
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
        _notify_telegram = _sd_cfg.get("notify_telegram", True)
        while True:
            await asyncio.sleep(interval)
            try:
                new_events = sensor_diag.update()
                if _notify_telegram and telegram_bot is not None and new_events:
                    aggregation_threshold = _sd_cfg.get("aggregation_threshold", 3)
                    # F20 aggregation: batch > N simultaneous events into one message
                    if len(new_events) > aggregation_threshold:
                        criticals = [e for e in new_events if e.level == "CRITICAL"]
                        warnings = [e for e in new_events if e.level == "WARNING"]
                        parts: list[str] = []
                        if criticals:
                            names = ", ".join(
                                e.channels[0] if e.channels else e.alarm_id
                                for e in criticals
                            )
                            parts.append(f"{len(criticals)} channels critical: {names}")
                        if warnings:
                            names = ", ".join(
                                e.channels[0] if e.channels else e.alarm_id
                                for e in warnings
                            )
                            parts.append(f"{len(warnings)} channels warning: {names}")
                        msg = "⚠ Diagnostic alarm batch:\n" + "\n".join(parts)
                        t = asyncio.create_task(
                            telegram_bot._send_to_all(msg),
                            name="diag_tg_batch",
                        )
                        _alarm_dispatch_tasks.add(t)
                        t.add_done_callback(_alarm_dispatch_tasks.discard)
                    else:
                        for event in new_events:
                            msg = f"⚠ [{event.level}] {event.alarm_id}\n{event.message}"
                            t = asyncio.create_task(
                                telegram_bot._send_to_all(msg),
                                name=f"diag_tg_{event.alarm_id}",
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
                vacuum_trend.push(reading.timestamp.timestamp(), reading.value)
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
            if action == "leak_rate_start":
                if not _leak_cfg.get("enabled", True):
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
        except Exception as exc:
            logger.error("Ошибка создания CooldownService: %s", exc)

    # --- Уведомления (один раз разбираем YAML) ---
    periodic_reporter: PeriodicReporter | None = None
    telegram_bot: TelegramCommandBot | None = None
    escalation_service: EscalationService | None = None
    notifications_cfg = _cfg("notifications")
    if notifications_cfg.exists():
        try:
            with notifications_cfg.open(encoding="utf-8") as fh:
                notif_raw: dict[str, Any] = yaml.safe_load(fh) or {}

            tg_cfg = notif_raw.get("telegram", {})
            bot_token = str(tg_cfg.get("bot_token", ""))
            token_valid = bot_token and bot_token != "YOUR_BOT_TOKEN_HERE"

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
                    )
                    logger.info(
                        "TelegramCommandBot создан (allowed=%d chat ids)",
                        len(allowed_ids),
                    )

            # EscalationService
            if token_valid and notif_raw.get("escalation"):
                from cryodaq.notifications.telegram import TelegramNotifier

                _esc_notifier = TelegramNotifier(
                    bot_token=bot_token,
                    chat_id=tg_cfg.get("chat_id", 0),
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
                _gemma_ctx = ContextBuilder(writer, experiment_manager)
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
            logger.warning("AssistantLiveAgent: ошибка инициализации — %s", _gemma_exc, exc_info=True)
    else:
        logger.info("AssistantLiveAgent: config/agent.yaml не найден, агент отключён")

    # --- AssistantQueryAgent (F30 Live Query) ---
    _query_agent: Any = None
    _q_broker_snap: Any = None
    if _gemma_config is not None and _gemma_config.query_enabled:
        try:
            from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
            from cryodaq.agents.assistant.query.adapters.alarm_adapter import AlarmAdapter
            from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot
            from cryodaq.agents.assistant.query.adapters.composite_adapter import CompositeAdapter
            from cryodaq.agents.assistant.query.adapters.cooldown_adapter import CooldownAdapter
            from cryodaq.agents.assistant.query.adapters.experiment_adapter import ExperimentAdapter
            from cryodaq.agents.assistant.query.adapters.sqlite_adapter import SQLiteAdapter
            from cryodaq.agents.assistant.query.adapters.vacuum_adapter import VacuumAdapter
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

            _q_broker_snap = BrokerSnapshot(broker)
            await _q_broker_snap.start()

            _q_cooldown = CooldownAdapter(cooldown_service)
            _q_vacuum = VacuumAdapter(vacuum_trend)
            _q_sqlite = SQLiteAdapter(writer)
            _q_alarms = AlarmAdapter(alarm_engine)
            _q_experiment = ExperimentAdapter(experiment_manager)
            _q_composite = CompositeAdapter(
                broker_snapshot=_q_broker_snap,
                cooldown=_q_cooldown,
                vacuum=_q_vacuum,
                alarms=_q_alarms,
                experiment=_q_experiment,
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
                ),
                intent_model=_gemma_config.query_intent_model,
                format_model=_gemma_config.query_format_model,
                intent_temperature=_gemma_config.query_intent_temperature,
                format_temperature=_gemma_config.query_format_temperature,
                intent_timeout_s=_gemma_config.query_intent_timeout_s,
                format_timeout_s=_gemma_config.query_format_timeout_s,
                max_queries_per_chat_per_hour=_gemma_config.query_max_per_chat_per_hour,
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
    if gemma_agent is not None:
        try:
            await gemma_agent.start()
        except Exception as _gemma_start_exc:
            logger.warning("AssistantLiveAgent: ошибка запуска — %s. Агент отключён.", _gemma_start_exc)
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
    sd_feed_task: asyncio.Task | None = None
    sd_tick_task: asyncio.Task | None = None
    if sensor_diag is not None:
        sd_feed_task = asyncio.create_task(_sensor_diag_feed(), name="sensor_diag_feed")
        sd_tick_task = asyncio.create_task(_sensor_diag_tick(), name="sensor_diag_tick")
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
