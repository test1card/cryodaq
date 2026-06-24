"""AlarmConfig — загрузка и парсинг конфигурации алармов v3.

Читает alarms_v3.yaml и возвращает:
  - EngineConfig    — параметры движка (rate_window_s, setpoints…)
  - list[AlarmConfig] — плоский список всех алармов с фазовым фильтром
"""

from __future__ import annotations

import copy
import math
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
        default = float(sp_raw.get("default", 0.0))
        if not math.isfinite(default):
            raise AlarmConfigError(
                f"engine.setpoints.{key}.default must be finite, got {default!r}"
            )
        setpoints[key] = SetpointDef(
            key=key,
            source=sp_raw.get("source", "constant"),
            default=default,
            unit=sp_raw.get("unit", "K"),
        )

    poll_interval_s = float(raw.get("poll_interval_s", 2.0))
    if not (math.isfinite(poll_interval_s) and poll_interval_s > 0):
        raise AlarmConfigError(
            f"engine.poll_interval_s must be a finite value > 0, got {poll_interval_s!r}"
        )

    rate_window_s = float(raw.get("rate_window_s", 120.0))
    if not (math.isfinite(rate_window_s) and rate_window_s > 0):
        raise AlarmConfigError(
            f"engine.rate_window_s must be a finite value > 0, got {rate_window_s!r}"
        )

    rate_min_points = int(raw.get("rate_min_points", 60))
    if rate_min_points < 1:
        raise AlarmConfigError(
            f"engine.rate_min_points must be >= 1, got {rate_min_points!r}"
        )

    return EngineConfig(
        poll_interval_s=poll_interval_s,
        rate_window_s=rate_window_s,
        rate_min_points=rate_min_points,
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

    # Fail-closed: validate required keys at LOAD time so a misconfigured
    # (possibly safety-relevant) alarm aborts startup instead of silently
    # never-firing at runtime (alarm_v2.evaluate() catches the KeyError,
    # logs it, and returns None).
    _validate_required_keys(alarm_id, cfg)

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


def _is_number(value: Any) -> bool:
    """True for a real numeric scalar (rejects bool, str, None)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_required_keys(alarm_id: str, cfg: dict) -> None:
    """Fail-closed presence/type check of evaluate-time required keys.

    Mirrors EVERY hard subscript in alarm_v2 so a misconfigured alarm
    fails closed at startup (AlarmConfigError) instead of silently
    returning None at runtime (KeyError caught by evaluate()).

    alarm_type: threshold — _check_threshold_channel (alarm_v2.py:224-233)
      - check above/below             → numeric `threshold`
      - check outside_range           → 2-element numeric `range`
      - check deviation_from_setpoint → str `setpoint_source` + numeric `threshold`
      - check fault_count_in_window   → exempt (uses .get("min_fault_count", 1))

    alarm_type: rate — _eval_rate (alarm_v2.py:362-365)
      - check rate_above/rate_below   → numeric `threshold`
      - check rate_near_zero / relative_rate_near_zero → exempt (.get("rate_threshold", …))
      - additional_condition (if present) → validated as a composite sub-condition

    alarm_type: composite — sub-conditions via _eval_condition (alarm_v2.py:284-330)
      - check any_below / any_above / above / below / rate_above / rate_below
        → each sub-condition requires numeric `threshold`
      - check rate_near_zero → exempt (.get("rate_threshold", 0.1))

    alarm_type: stale → no hard reads, exempt.
    """
    alarm_type = cfg.get("alarm_type")

    if alarm_type == "threshold":
        _validate_threshold_check(alarm_id, cfg)

    elif alarm_type == "rate":
        # alarm_v2._eval_rate L362-365
        check = cfg.get("check", "rate_above")
        if check in ("rate_above", "rate_below"):
            if not _is_number(cfg.get("threshold")):
                raise AlarmConfigError(
                    f"alarm {alarm_id!r} (alarm_type=rate, check={check}) requires a "
                    f"numeric 'threshold', got {cfg.get('threshold')!r}"
                )
        # additional_condition is passed to _eval_condition — validate it too
        # alarm_v2._eval_rate L376-378
        add_cond = cfg.get("additional_condition")
        if isinstance(add_cond, dict):
            _validate_condition(alarm_id, add_cond, context="additional_condition")

    elif alarm_type == "composite":
        # Each element of `conditions` is passed to _eval_condition
        for i, cond in enumerate(cfg.get("conditions", [])):
            if isinstance(cond, dict):
                _validate_condition(alarm_id, cond, context=f"conditions[{i}]")


def _validate_threshold_check(alarm_id: str, cfg: dict) -> None:
    """Validate keys for alarm_type=threshold (mirrors _check_threshold_channel)."""
    check = cfg.get("check", "above")

    if check in ("above", "below"):
        # alarm_v2._check_threshold_channel L225/L227
        if not _is_number(cfg.get("threshold")):
            raise AlarmConfigError(
                f"alarm {alarm_id!r} (check={check}) requires a numeric 'threshold', "
                f"got {cfg.get('threshold')!r}"
            )
    elif check == "outside_range":
        # alarm_v2._check_threshold_channel L229
        r = cfg.get("range")
        if not (isinstance(r, (list, tuple)) and len(r) == 2 and all(_is_number(x) for x in r)):
            raise AlarmConfigError(
                f"alarm {alarm_id!r} (check=outside_range) requires a 2-element numeric "
                f"'range', got {r!r}"
            )
    elif check == "deviation_from_setpoint":
        # alarm_v2._check_threshold_channel L232-233
        if not isinstance(cfg.get("setpoint_source"), str) or not cfg.get("setpoint_source"):
            raise AlarmConfigError(
                f"alarm {alarm_id!r} (check=deviation_from_setpoint) requires a "
                f"'setpoint_source' string, got {cfg.get('setpoint_source')!r}"
            )
        if not _is_number(cfg.get("threshold")):
            raise AlarmConfigError(
                f"alarm {alarm_id!r} (check=deviation_from_setpoint) requires a numeric "
                f"'threshold', got {cfg.get('threshold')!r}"
            )
    # fault_count_in_window: exempt — uses .get("min_fault_count", 1), no hard subscript


def _validate_condition(alarm_id: str, cond: dict, context: str) -> None:
    """Validate a composite sub-condition or additional_condition dict.

    Mirrors alarm_v2._eval_condition hard subscripts (alarm_v2.py:284-330):
      any_below, any_above, above, below → cond["threshold"]  (L286/293/305/307/314)
      rate_above, rate_below             → cond["threshold"]  (L322/330)
      rate_near_zero                     → exempt (.get("rate_threshold", 0.1))
    """
    check = cond.get("check", "above")
    needs_threshold = check in ("any_below", "any_above", "above", "below", "rate_above", "rate_below")
    if needs_threshold and not _is_number(cond.get("threshold")):
        raise AlarmConfigError(
            f"alarm {alarm_id!r} {context} (check={check}) requires a numeric 'threshold', "
            f"got {cond.get('threshold')!r}"
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
