"""AlarmConfig — загрузка и парсинг конфигурации алармов v3.

Читает alarms_v3.yaml и возвращает:
  - EngineConfig    — параметры движка (rate_window_s, setpoints…)
  - list[AlarmConfig] — плоский список всех алармов с фазовым фильтром
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class AlarmConfigError(RuntimeError):
    """Raised when alarms_v3.yaml cannot be loaded in a fail-closed manner.

    Distinct class so engine startup maps it to config exit code
    instead of generic runtime crash.
    """


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SetpointDef:
    """Описание одного setpoint из секции engine.setpoints."""

    key: str
    source: str  # "experiment_metadata" | "constant"
    default: float
    unit: str = "K"


@dataclass
class EngineConfig:
    """Параметры движка алармов из секции engine."""

    poll_interval_s: float = 2.0
    rate_window_s: float = 120.0
    rate_min_points: int = 60
    rate_method: str = "linear_fit"
    setpoints: dict[str, SetpointDef] = field(default_factory=dict)


@dataclass
class AlarmConfig:
    """Одна alarm-запись, готовая к передаче в AlarmEvaluator.

    Атрибуты
    ----------
    alarm_id:
        Уникальный идентификатор аларма.
    config:
        Словарь конфигурации (alarm_type, check, threshold, …).
        channel_group уже раскрыт → channels list.
    phase_filter:
        None — работает всегда (global alarm).
        list[str] — только при активной фазе из этого списка.
    notify:
        Список каналов уведомлений: "gui", "telegram", "sound".
    """

    alarm_id: str
    config: dict[str, Any]
    phase_filter: list[str] | None = None
    notify: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_alarm_config(
    path: str | Path | None = None,
) -> tuple[EngineConfig, list[AlarmConfig]]:
    """Загрузить alarms_v3.yaml → (EngineConfig, list[AlarmConfig]).

    Если path не задан, ищет config/alarms_v3.yaml рядом с этим модулем
    (поднимаясь до корня пакета).

    Raises AlarmConfigError if file is missing, malformed, non-mapping,
    or contains coercion errors in alarm definitions.
    """
    if path is None:
        path = _find_default_config()
        if path is None:
            raise AlarmConfigError(
                "alarms_v3.yaml not found: no path provided and no default "
                "config located via standard search. Refusing to start alarm "
                "engine without alarm configuration."
            )
    path = Path(path)
    if not path.exists():
        raise AlarmConfigError(
            f"alarms_v3.yaml not found at {path} — refusing to start "
            f"alarm engine without alarm configuration"
        )

    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise AlarmConfigError(f"alarms_v3.yaml at {path}: YAML parse error — {exc}") from exc

    if not isinstance(raw, dict):
        raise AlarmConfigError(
            f"alarms_v3.yaml at {path} is malformed (expected mapping, got {type(raw).__name__})"
        )

    channel_groups: dict[str, list[str]] = raw.get("channel_groups", {})
    try:
        engine_cfg = _parse_engine_config(raw.get("engine", {}))
        alarms: list[AlarmConfig] = []

        # --- Global alarms ---
        for alarm_id, alarm_raw in raw.get("global_alarms", {}).items():
            cfg = _expand_alarm(alarm_id, alarm_raw, channel_groups)
            if cfg is not None:
                alarms.append(cfg)

        # --- Phase alarms ---
        for phase_name, phase_dict in raw.get("phase_alarms", {}).items():
            if not isinstance(phase_dict, dict):
                continue
            for alarm_id, alarm_raw in phase_dict.items():
                cfg = _expand_alarm(alarm_id, alarm_raw, channel_groups, phase_filter=[phase_name])
                if cfg is not None:
                    alarms.append(cfg)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise AlarmConfigError(
            f"alarms_v3.yaml at {path}: invalid config value — {type(exc).__name__}: {exc}"
        ) from exc

    return engine_cfg, alarms


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_engine_config(raw: dict) -> EngineConfig:
    setpoints: dict[str, SetpointDef] = {}
    for key, sp_raw in raw.get("setpoints", {}).items():
        setpoints[key] = SetpointDef(
            key=key,
            source=sp_raw.get("source", "constant"),
            default=float(sp_raw.get("default", 0.0)),
            unit=sp_raw.get("unit", "K"),
        )
    return EngineConfig(
        poll_interval_s=float(raw.get("poll_interval_s", 2.0)),
        rate_window_s=float(raw.get("rate_window_s", 120.0)),
        rate_min_points=int(raw.get("rate_min_points", 60)),
        rate_method=str(raw.get("rate_method", "linear_fit")),
        setpoints=setpoints,
    )


def _expand_alarm(
    alarm_id: str,
    alarm_raw: Any,
    channel_groups: dict[str, list[str]],
    phase_filter: list[str] | None = None,
) -> AlarmConfig | None:
    """Создать AlarmConfig из raw YAML-словаря, раскрыв channel_group."""
    if not isinstance(alarm_raw, dict):
        return None

    cfg = copy.deepcopy(alarm_raw)
    notify: list[str] = cfg.pop("notify", []) or []
    # Remove non-evaluator keys
    for key in ("gui_action", "side_effect"):
        cfg.pop(key, None)

    # Expand channel_group → channels
    _expand_channel_group(cfg, channel_groups)

    # Expand channel_group inside composite conditions
    for cond in cfg.get("conditions", []):
        if isinstance(cond, dict):
            _expand_channel_group(cond, channel_groups)

    return AlarmConfig(
        alarm_id=alarm_id,
        config=cfg,
        phase_filter=phase_filter,
        notify=notify if isinstance(notify, list) else [notify],
    )


def _expand_channel_group(cfg: dict, groups: dict[str, list[str]]) -> None:
    """Заменить channel_group → channels in-place."""
    group_name = cfg.pop("channel_group", None)
    if group_name and group_name in groups:
        cfg["channels"] = list(groups[group_name])


def _find_default_config() -> Path | None:
    """Найти config/alarms_v3.yaml, поднимаясь от текущего файла."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "alarms_v3.yaml"
        if candidate.exists():
            return candidate
    return None
