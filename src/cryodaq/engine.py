"""Головной процесс CryoDAQ Engine (безголовый).

Запуск:
    cryodaq-engine          # через entry point
    python -m cryodaq.engine  # напрямую

Загружает конфигурации, создаёт и связывает все подсистемы:
    drivers → DataBroker → [SQLiteWriter, ZMQPublisher, AlarmEngine, InterlockEngine, PluginPipeline]

Корректное завершение по SIGINT / SIGTERM (Unix) или Ctrl+C (Windows).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
import signal
import sys
import time

# Windows: pyzmq требует SelectorEventLoop (не Proactor)
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
from pathlib import Path
from typing import Any

import yaml

from cryodaq.analytics.calibration import CalibrationStore
from cryodaq.core.calibration_acquisition import CalibrationAcquisitionService
from cryodaq.core.event_logger import EventLogger
from cryodaq.core.alarm import AlarmEngine
from cryodaq.core.alarm_v2 import AlarmEvaluator, AlarmStateManager
from cryodaq.core.alarm_config import load_alarm_config
from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine
from cryodaq.core.broker import DataBroker
from cryodaq.core.disk_monitor import DiskMonitor
from cryodaq.core.experiment import ExperimentManager, ExperimentStatus
from cryodaq.core.housekeeping import (
    AdaptiveThrottle,
    HousekeepingService,
    load_housekeeping_config,
    load_protected_channel_patterns,
)
from cryodaq.core.interlock import InterlockEngine
from cryodaq.core.operator_log import OperatorLogEntry
from cryodaq.core.smu_channel import normalize_smu_channel
from cryodaq.core.safety_broker import SafetyBroker
from cryodaq.core.safety_manager import SafetyManager
from cryodaq.core.scheduler import InstrumentConfig, Scheduler
from cryodaq.core.zmq_bridge import ZMQCommandServer, ZMQPublisher
from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.drivers.base import Reading
from cryodaq.notifications.periodic_report import PeriodicReporter
from cryodaq.reporting.generator import ReportGenerator
from cryodaq.notifications.telegram_commands import TelegramCommandBot
from cryodaq.notifications.escalation import EscalationService
from cryodaq.storage.sqlite_writer import SQLiteWriter

logger = logging.getLogger("cryodaq.engine")

# ---------------------------------------------------------------------------
# Пути по умолчанию (относительно корня проекта)
# ---------------------------------------------------------------------------
from cryodaq.paths import get_project_root, get_data_dir, get_config_dir

_PROJECT_ROOT = get_project_root()
_CONFIG_DIR = get_config_dir()
_PLUGINS_DIR = _PROJECT_ROOT / "plugins"
_DATA_DIR = get_data_dir()

# Интервал самодиагностики (секунды)
_WATCHDOG_INTERVAL_S = 30.0


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
        return await _keithley_set_target(cmd, safety_manager)

    if action == "keithley_set_limits":
        return await _keithley_set_limits(cmd, safety_manager)

    raise ValueError(f"Unsupported Keithley command: {action}")


async def _keithley_set_target(
    cmd: dict[str, Any],
    safety_manager: SafetyManager,
) -> dict[str, Any]:
    """Live-update P_target on an active channel without restart."""
    channel = cmd.get("channel")
    smu_channel = normalize_smu_channel(channel)
    p_target = float(cmd.get("p_target", 0))
    if p_target <= 0:
        return {"ok": False, "error": "p_target must be > 0"}

    keithley = safety_manager._keithley
    if keithley is None:
        return {"ok": False, "error": "Keithley not connected"}

    runtime = keithley._channels.get(smu_channel)
    if runtime is None or not runtime.active:
        return {"ok": False, "error": f"Channel {smu_channel} not active"}

    runtime.p_target = p_target
    return {"ok": True, "channel": smu_channel, "p_target": p_target}


async def _keithley_set_limits(
    cmd: dict[str, Any],
    safety_manager: SafetyManager,
) -> dict[str, Any]:
    """Live-update V/I compliance limits on an active channel."""
    channel = cmd.get("channel")
    smu_channel = normalize_smu_channel(channel)

    keithley = safety_manager._keithley
    if keithley is None:
        return {"ok": False, "error": "Keithley not connected"}

    runtime = keithley._channels.get(smu_channel)
    if runtime is None or not runtime.active:
        return {"ok": False, "error": f"Channel {smu_channel} not active"}

    v_comp = cmd.get("v_comp")
    i_comp = cmd.get("i_comp")

    if v_comp is not None:
        v_comp = float(v_comp)
        if v_comp <= 0:
            return {"ok": False, "error": "v_comp must be > 0"}
        runtime.v_comp = v_comp
        if not keithley.mock:
            await keithley._transport.write(f"{smu_channel}.source.limitv = {v_comp}")

    if i_comp is not None:
        i_comp = float(i_comp)
        if i_comp <= 0:
            return {"ok": False, "error": "i_comp must be > 0"}
        runtime.i_comp = i_comp
        if not keithley.mock:
            await keithley._transport.write(f"{smu_channel}.source.limiti = {i_comp}")

    return {"ok": True, "channel": smu_channel, "v_comp": runtime.v_comp, "i_comp": runtime.i_comp}


def _parse_log_time(raw: Any) -> datetime | None:
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return None
        if value.endswith("Z"):
            value = f"{value[:-1]}+00:00"
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
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

        entries = await writer.get_operator_log(
            experiment_id=str(experiment_id) if experiment_id is not None else None,
            start_time=_parse_log_time(cmd.get("start_time", cmd.get("start_ts"))),
            end_time=_parse_log_time(cmd.get("end_time", cmd.get("end_ts"))),
            limit=int(cmd.get("limit", 100)),
        )
        return {"ok": True, "entries": [entry.to_payload() for entry in entries]}

    raise ValueError(f"Unsupported operator log command: {action}")


async def _run_calibration_command(
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
            runtime_apply_ready=(
                bool(cmd.get("runtime_apply_ready"))
                if "runtime_apply_ready" in cmd
                else None
            ),
        )
        return {"ok": True, **result}

    if action == "calibration_curve_export":
        sensor_id = str(cmd.get("sensor_id", "")).strip()
        if not sensor_id:
            raise ValueError("sensor_id is required.")
        json_path = calibration_store.export_curve_json(
            sensor_id,
            Path(str(cmd.get("json_path")).strip()) if str(cmd.get("json_path", "")).strip() else None,
        )
        table_path = calibration_store.export_curve_table(
            sensor_id,
            path=Path(str(cmd.get("table_path")).strip()) if str(cmd.get("table_path", "")).strip() else None,
            points=int(cmd.get("points", 200)),
        )
        curve_330_path = calibration_store.export_curve_330(
            sensor_id,
            path=Path(str(cmd.get("curve_330_path")).strip()) if str(cmd.get("curve_330_path", "")).strip() else None,
            points=int(cmd.get("points", 200)),
        )
        curve_340_path = calibration_store.export_curve_340(
            sensor_id,
            path=Path(str(cmd.get("curve_340_path")).strip()) if str(cmd.get("curve_340_path", "")).strip() else None,
            points=int(cmd.get("points", 200)),
        )
        return {
            "ok": True,
            "json_path": str(json_path),
            "table_path": str(table_path),
            "curve_330_path": str(curve_330_path),
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
        template = experiment_manager.get_template(template_id)
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
    except Exception:
        logger.warning("Failed to activate calibration acquisition", exc_info=True)


async def _run_experiment_command(
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
        # Auto-generate report if template enables it
        report_generated = False
        try:
            template = experiment_manager.get_template(info.template_id)
            if template.report_enabled:
                generator = ReportGenerator(experiment_manager.data_dir)
                generator.generate(info.experiment_id)
                report_generated = True
        except Exception as exc:
            logger.warning("Auto-report generation failed: %s", exc)
        return {"ok": True, "experiment": info.to_payload(), "report_generated": report_generated}

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
        return {"ok": True, "attached": record is not None, "run_record": record.to_payload() if record else None}

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
                elapsed = (_dt.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()
            except Exception:
                pass
        return {
            "ok": True,
            "current_phase": current,
            "phases": history,
            "elapsed_in_phase_s": elapsed,
        }

    raise ValueError(f"Unsupported experiment command: {action}")


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
            driver = ThyracontVSP63D(name, resource, baudrate=baudrate, mock=mock)
        else:
            logger.warning("Неизвестный тип прибора '%s', пропущен", itype)
            continue

        configs.append(InstrumentConfig(driver=driver, poll_interval_s=poll_interval_s, resource_str=resource))
        logger.info(
            "Прибор сконфигурирован: %s (%s), ресурс=%s, интервал=%.2f с",
            name, itype, resource, poll_interval_s,
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
                hours, minutes, secs,
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
    adaptive_throttle = AdaptiveThrottle(
        housekeeping_raw.get("adaptive_throttle", {}),
        protected_patterns=load_protected_channel_patterns(alarms_cfg, interlocks_cfg),
    )

    # SQLite — persistence-first: writer создаётся ДО scheduler
    writer = SQLiteWriter(_DATA_DIR)
    await writer.start_immediate()

    # Calibration acquisition — continuous SRDG during calibration experiments
    calibration_acquisition = CalibrationAcquisitionService(writer)

    # Планировщик — публикует в ОБА брокера, пишет на диск ДО публикации
    scheduler = Scheduler(
        broker,
        safety_broker=safety_broker,
        sqlite_writer=writer,
        adaptive_throttle=adaptive_throttle,
        calibration_acquisition=calibration_acquisition,
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

    # Interlock Engine — действия делегируются SafetyManager
    async def _interlock_emergency_off() -> None:
        await safety_manager.on_interlock_trip("interlock", "", 0)

    async def _interlock_stop_source() -> None:
        await safety_manager.on_interlock_trip("interlock", "", 0)

    interlock_actions: dict[str, Any] = {
        "emergency_off": _interlock_emergency_off,
        "stop_source": _interlock_stop_source,
    }

    interlock_engine = InterlockEngine(broker, actions=interlock_actions)
    if interlocks_cfg.exists():
        interlock_engine.load_config(interlocks_cfg)
    else:
        logger.warning("Файл блокировок не найден: %s", interlocks_cfg)

    # ExperimentManager
    experiment_manager = ExperimentManager(
        data_dir=_DATA_DIR,
        instruments_config=instruments_cfg,
        templates_dir=_CONFIG_DIR / "experiment_templates",
    )
    event_logger = EventLogger(writer, experiment_manager)

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
        from cryodaq.core.channel_manager import get_channel_manager
        _ch_mgr = get_channel_manager()
        # Build correlation groups from config; channel ids use display prefix (Т1→T1)
        sensor_diag = SensorDiagnosticsEngine(config=_sd_cfg)
        # Set display names from channel_manager
        sensor_diag.set_channel_names(
            {ch_id: _ch_mgr.get_display_name(ch_id) for ch_id in _ch_mgr.get_all()}
        )
        logger.info(
            "SensorDiagnostics: enabled, update_interval=%ds, groups=%d",
            _sd_cfg.get("update_interval_s", 10),
            len(_sd_cfg.get("correlation_groups", {})),
        )
    else:
        logger.info("SensorDiagnostics: отключён (plugins.yaml не найден или enabled=false)")

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
                    event = alarm_v2_evaluator.evaluate(alarm_cfg.alarm_id, alarm_cfg.config)
                    transition = alarm_v2_state_mgr.process(alarm_cfg.alarm_id, event, alarm_cfg.config)
                    if transition == "TRIGGERED" and event is not None:
                        # GUI polls via alarm_v2_status command; optionally notify via Telegram
                        if "telegram" in alarm_cfg.notify and telegram_bot is not None:
                            msg = f"⚠ [{event.level}] {event.alarm_id}\n{event.message}"
                            asyncio.create_task(
                                telegram_bot._send_to_all(msg),
                                name=f"alarm_v2_tg_{alarm_cfg.alarm_id}",
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
        """Periodically recompute sensor diagnostics."""
        if sensor_diag is None:
            return
        interval = _sd_cfg.get("update_interval_s", 10)
        while True:
            await asyncio.sleep(interval)
            try:
                sensor_diag.update()
            except Exception as exc:
                logger.error("SensorDiagnostics tick error: %s", exc)

    # Обработчик команд от GUI — через SafetyManager
    async def _handle_gui_command(cmd: dict[str, Any]) -> dict[str, Any]:
        action = cmd.get("cmd", "")
        try:
            if action in {"keithley_emergency_off", "keithley_stop", "keithley_start", "keithley_set_target", "keithley_set_limits"}:
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
                        }
                        for k, v in active.items()
                    },
                    "history": alarm_v2_state_mgr.get_history(limit=20),
                }
            if action == "alarm_v2_ack":
                name = cmd.get("alarm_name", "")
                return {"ok": alarm_v2_state_mgr.acknowledge(name), "alarm_name": name}
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
                result = await _run_experiment_command(action, cmd, experiment_manager)
                # Hook calibration acquisition on experiment lifecycle
                if result.get("ok") and action in {"experiment_start", "experiment_create"}:
                    _try_activate_calibration_acquisition(
                        calibration_acquisition, experiment_manager, cmd,
                    )
                    name = cmd.get("name") or cmd.get("title") or "?"
                    await event_logger.log_event("experiment", f"Эксперимент начат: {name}")
                elif result.get("ok") and action in {
                    "experiment_finalize", "experiment_stop", "experiment_abort",
                }:
                    calibration_acquisition.deactivate()
                    if action == "experiment_abort":
                        await event_logger.log_event("experiment", "\u26a0 Эксперимент прерван")
                    else:
                        await event_logger.log_event("experiment", "Эксперимент завершён")
                elif result.get("ok") and action == "experiment_advance_phase":
                    phase = cmd.get("phase", "?")
                    await event_logger.log_event("phase", f"Фаза: → {phase}")
                return result
            if action == "calibration_acquisition_status":
                return {"ok": True, **calibration_acquisition.stats}
            if action in {
                "calibration_v2_extract",
                "calibration_v2_fit",
                "calibration_v2_coverage",
            }:
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
                return await _run_calibration_command(
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
                    broker, alarm_engine,
                    bot_token=bot_token,
                    chat_id=tg_cfg.get("chat_id", 0),
                    report_interval_s=float(pr_cfg.get("report_interval_s", 1800)),
                    chart_hours=float(pr_cfg.get("chart_hours", 2.0)),
                    include_channels=pr_cfg.get("include_channels"),
                )
                logger.info("PeriodicReporter создан")

            # TelegramCommandBot
            cmd_cfg = notif_raw.get("commands", {})
            if cmd_cfg.get("enabled", False) and token_valid:
                allowed = tg_cfg.get("allowed_chat_ids") or []
                telegram_bot = TelegramCommandBot(
                    broker, alarm_engine,
                    bot_token=bot_token,
                    allowed_chat_ids=[int(x) for x in allowed] if allowed else None,
                    poll_interval_s=float(cmd_cfg.get("poll_interval_s", 2.0)),
                    command_handler=_handle_gui_command,
                )
                logger.info("TelegramCommandBot создан")

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
    await housekeeping_service.start()

    # Watchdog
    watchdog_task = asyncio.create_task(
        _watchdog(broker, scheduler, writer, start_ts), name="engine_watchdog",
    )

    # DiskMonitor
    disk_monitor = DiskMonitor(data_dir=_DATA_DIR, broker=broker)
    await disk_monitor.start()

    logger.info(
        "═══ CryoDAQ Engine запущен ═══ | "
        "приборов=%d | тревог=%d | блокировок=%d | mock=%s",
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

    uptime = time.monotonic() - start_ts
    logger.info(
        "═══ CryoDAQ Engine завершён ═══ | uptime=%.1f с", uptime,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Точка входа cryodaq-engine."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    mock = "--mock" in sys.argv or os.environ.get("CRYODAQ_MOCK", "").lower() in ("1", "true")
    if mock:
        logger.info("Режим MOCK: реальные приборы не используются")

    try:
        asyncio.run(_run_engine(mock=mock))
    except KeyboardInterrupt:
        logger.info("Прервано оператором (Ctrl+C)")


if __name__ == "__main__":
    main()
