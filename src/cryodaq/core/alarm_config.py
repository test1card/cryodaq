"""AlarmConfig — загрузка и парсинг конфигурации алармов v3.

Читает alarms_v3.yaml и возвращает:
  - EngineConfig    — параметры движка (rate_window_s, setpoints…)
  - list[AlarmConfig] — плоский список всех алармов с фазовым фильтром
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_MAX_CONFIG_BYTES = 1_048_576


class _StrictConfigLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        event = self.peek_event()
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None) is not None:
            raise yaml.YAMLError("YAML anchors and aliases are forbidden")
        return super().compose_node(parent, index)


def _construct_unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.YAMLError(f"duplicate YAML key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictConfigLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


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


@dataclass(frozen=True)
class AlarmConfigAuthority:
    """One validated alarm document shared by every startup consumer."""

    engine_config: EngineConfig
    alarms: tuple[AlarmConfig, ...]
    critical_channel_patterns: frozenset[str]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_alarm_config(
    path: str | Path | None = None,
) -> tuple[EngineConfig, list[AlarmConfig]]:
    authority = load_alarm_config_authority(path)
    return authority.engine_config, list(authority.alarms)


def load_alarm_config_authority(
    path: str | Path | None = None,
) -> AlarmConfigAuthority:
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
            f"alarms_v3.yaml not found at {path} — refusing to start alarm engine without alarm configuration"
        )

    if path.is_symlink():
        raise AlarmConfigError("alarms_v3.yaml must not be a symbolic link")
    try:
        payload = path.read_bytes()
        if len(payload) > _MAX_CONFIG_BYTES:
            raise AlarmConfigError("alarms_v3.yaml exceeds the bounded size limit")
        raw = yaml.load(payload.decode("utf-8"), Loader=_StrictConfigLoader)
    except (OSError, UnicodeError) as exc:
        raise AlarmConfigError(f"alarms_v3.yaml could not be read as UTF-8: {type(exc).__name__}") from exc
    except yaml.YAMLError as exc:
        raise AlarmConfigError(f"alarms_v3.yaml at {path}: YAML parse error — {exc}") from exc

    if not isinstance(raw, dict):
        raise AlarmConfigError(f"alarms_v3.yaml at {path} is malformed (expected mapping, got {type(raw).__name__})")

    _validate_alarm_document_shape(raw)
    channel_groups: dict[str, list[str]] = raw.get("channel_groups", {})
    try:
        engine_cfg = _parse_engine_config(raw.get("engine", {}))
        alarms: list[AlarmConfig] = []

        # --- Global alarms ---
        for alarm_id, alarm_raw in raw.get("global_alarms", {}).items():
            cfg = _expand_alarm(alarm_id, alarm_raw, channel_groups)
            alarms.append(cfg)

        # --- Phase alarms ---
        for phase_name, phase_dict in raw.get("phase_alarms", {}).items():
            for alarm_id, alarm_raw in phase_dict.items():
                cfg = _expand_alarm(alarm_id, alarm_raw, channel_groups, phase_filter=[phase_name])
                alarms.append(cfg)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise AlarmConfigError(f"alarms_v3.yaml at {path}: invalid config value — {type(exc).__name__}: {exc}") from exc

    return AlarmConfigAuthority(
        engine_config=engine_cfg,
        alarms=tuple(alarms),
        critical_channel_patterns=frozenset(_critical_channel_patterns(alarms, raw.get("interlocks", {}))),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


_ALARM_FIELDS = {
    "alarm_type",
    "channel",
    "channels",
    "channel_group",
    "check",
    "threshold",
    "range",
    "timeout_s",
    "window_s",
    "min_fault_count",
    "rate_window_s",
    "rate_threshold",
    "additional_condition",
    "operator",
    "conditions",
    "level",
    "hysteresis",
    "message",
    "notify",
    "gui_action",
    "side_effect",
    "interlock",
    "setpoint_source",
}
_CONDITION_FIELDS = {
    "channel",
    "channels",
    "channel_group",
    "check",
    "threshold",
    "rate_window_s",
    "rate_threshold",
}


def _explicit_channel_refs(node: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(node, dict):
        channel = node.get("channel")
        if isinstance(channel, str):
            refs.append(channel)
        channels = node.get("channels")
        if isinstance(channels, (list, tuple)):
            refs.extend(item for item in channels if isinstance(item, str))
        for key, value in node.items():
            if key not in {"channel", "channels"} and isinstance(value, (dict, list, tuple)):
                refs.extend(_explicit_channel_refs(value))
    elif isinstance(node, (list, tuple)):
        for value in node:
            refs.extend(_explicit_channel_refs(value))
    return refs


def _critical_channel_patterns(alarms: list[AlarmConfig], phantom_interlocks: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for alarm in alarms:
        if alarm.config.get("level") == "CRITICAL":
            refs.update(_explicit_channel_refs(alarm.config))
    for entry in phantom_interlocks.values():
        refs.update(_explicit_channel_refs(entry))
    return {re.escape(ref) for ref in refs}


def _validated_rate_method(value: Any) -> str:
    if value != "linear_fit":
        raise AlarmConfigError("engine.rate_method must be 'linear_fit'")
    return value


def _validate_channel_binding(context: str, cfg: dict[str, Any]) -> None:
    present = [key for key in ("channel", "channels", "channel_group") if key in cfg]
    if len(present) != 1:
        raise AlarmConfigError(f"{context} requires exactly one channel binding")
    key = present[0]
    value = cfg[key]
    if key in {"channel", "channel_group"}:
        if not isinstance(value, str) or not value:
            raise AlarmConfigError(f"{context}.{key} must be a non-empty string")
    elif not (isinstance(value, list) and value and all(isinstance(item, str) and item for item in value)):
        raise AlarmConfigError(f"{context}.channels must be a non-empty string list")


def _validate_condition_schema(context: str, cond: Any) -> None:
    if not isinstance(cond, dict):
        raise AlarmConfigError(f"{context} must be a mapping")
    unknown = set(cond) - _CONDITION_FIELDS
    if unknown:
        raise AlarmConfigError(f"{context} contains unknown keys: {sorted(unknown)}")
    _validate_channel_binding(context, cond)
    check = cond.get("check")
    known = {
        "any_below",
        "any_above",
        "above",
        "below",
        "rate_above",
        "rate_below",
        "rate_near_zero",
        "relative_rate_near_zero",
    }
    if check not in known:
        raise AlarmConfigError(f"{context}.check is invalid")
    for key in ("threshold", "rate_window_s", "rate_threshold"):
        if key in cond and (not _is_number(cond[key]) or not math.isfinite(cond[key])):
            raise AlarmConfigError(f"{context}.{key} must be finite numeric")


def _validate_alarm_entry_schema(alarm_id: str, entry: Any) -> None:
    if not isinstance(alarm_id, str) or not alarm_id or not isinstance(entry, dict):
        raise AlarmConfigError("alarm entries must be named mappings")
    unknown = set(entry) - _ALARM_FIELDS
    if unknown:
        raise AlarmConfigError(f"alarm {alarm_id!r} contains unknown keys: {sorted(unknown)}")
    alarm_type = entry.get("alarm_type")
    if alarm_type not in {"threshold", "rate", "composite", "stale"}:
        raise AlarmConfigError(f"alarm {alarm_id!r} has invalid alarm_type")
    if entry.get("level") not in {"INFO", "WARNING", "CRITICAL"}:
        raise AlarmConfigError(f"alarm {alarm_id!r} has invalid level")
    if "message" in entry and (not isinstance(entry["message"], str) or not entry["message"]):
        raise AlarmConfigError(f"alarm {alarm_id!r}.message must be a non-empty string")
    notify = entry.get("notify", [])
    if not isinstance(notify, list) or not all(
        isinstance(item, str) and item in {"gui", "telegram", "sound"} for item in notify
    ):
        raise AlarmConfigError(f"alarm {alarm_id!r} notify is invalid")
    for key in (
        "threshold",
        "timeout_s",
        "window_s",
        "rate_window_s",
        "rate_threshold",
    ):
        if key in entry and (not _is_number(entry[key]) or not math.isfinite(entry[key])):
            raise AlarmConfigError(f"alarm {alarm_id!r}.{key} must be finite numeric")
    if "min_fault_count" in entry and (type(entry["min_fault_count"]) is not int or entry["min_fault_count"] < 1):
        raise AlarmConfigError(f"alarm {alarm_id!r}.min_fault_count must be positive int")
    if "range" in entry and not (
        isinstance(entry["range"], list)
        and len(entry["range"]) == 2
        and all(_is_number(value) and math.isfinite(value) for value in entry["range"])
    ):
        raise AlarmConfigError(f"alarm {alarm_id!r}.range must contain two finite numbers")
    hysteresis = entry.get("hysteresis")
    if hysteresis is not None:
        values = hysteresis.values() if isinstance(hysteresis, dict) else (hysteresis,)
        if not all(_is_number(value) and math.isfinite(value) for value in values):
            raise AlarmConfigError(f"alarm {alarm_id!r}.hysteresis must be finite numeric")
    for key in ("gui_action", "side_effect", "interlock", "setpoint_source"):
        if key in entry and (not isinstance(entry[key], str) or not entry[key]):
            raise AlarmConfigError(f"alarm {alarm_id!r}.{key} must be a non-empty string")

    if alarm_type == "composite":
        if entry.get("operator") not in {"AND", "OR"}:
            raise AlarmConfigError(f"alarm {alarm_id!r}.operator is invalid")
        conditions = entry.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            raise AlarmConfigError(f"alarm {alarm_id!r}.conditions must be a non-empty list")
        for index, condition in enumerate(conditions):
            _validate_condition_schema(f"alarm {alarm_id!r}.conditions[{index}]", condition)
    else:
        _validate_channel_binding(f"alarm {alarm_id!r}", entry)
        check = entry.get("check")
        known_checks = {
            "threshold": {"above", "below", "outside_range", "deviation_from_setpoint", "fault_count_in_window"},
            "rate": {"rate_above", "rate_below", "rate_near_zero", "relative_rate_near_zero"},
            "stale": {None},
        }[alarm_type]
        if check not in known_checks:
            raise AlarmConfigError(f"alarm {alarm_id!r}.check is invalid")
        if alarm_type == "stale" and (not _is_number(entry.get("timeout_s")) or entry["timeout_s"] <= 0):
            raise AlarmConfigError(f"alarm {alarm_id!r}.timeout_s must be positive")
        if "additional_condition" in entry:
            if alarm_type != "rate":
                raise AlarmConfigError(f"alarm {alarm_id!r} cannot have additional_condition")
            _validate_condition_schema(f"alarm {alarm_id!r}.additional_condition", entry["additional_condition"])


def _validate_alarm_document_shape(raw: dict[str, Any]) -> None:
    unknown_top = set(raw) - {
        "engine",
        "channel_groups",
        "global_alarms",
        "phase_alarms",
        "interlocks",
    }
    if unknown_top:
        raise AlarmConfigError(f"alarms_v3.yaml contains unknown keys: {sorted(unknown_top)}")
    groups = raw.get("channel_groups", {})
    if not isinstance(groups, dict):
        raise AlarmConfigError("channel_groups must be a mapping")
    for name, channels in groups.items():
        if (
            not isinstance(name, str)
            or not name
            or not (
                isinstance(channels, list)
                and channels
                and all(isinstance(channel, str) and channel for channel in channels)
            )
        ):
            raise AlarmConfigError("channel_groups entries must be non-empty string lists")

    seen: set[str] = set()
    global_alarms = raw.get("global_alarms", {})
    if not isinstance(global_alarms, dict):
        raise AlarmConfigError("global_alarms must be a mapping")
    for alarm_id, entry in global_alarms.items():
        _validate_alarm_entry_schema(alarm_id, entry)
        if alarm_id in seen:
            raise AlarmConfigError(f"duplicate alarm id {alarm_id!r}")
        seen.add(alarm_id)

    phases = raw.get("phase_alarms", {})
    if not isinstance(phases, dict):
        raise AlarmConfigError("phase_alarms must be a mapping")
    for phase, entries in phases.items():
        if not isinstance(phase, str) or not phase or not isinstance(entries, dict):
            raise AlarmConfigError("phase_alarms entries must be named mappings")
        for alarm_id, entry in entries.items():
            _validate_alarm_entry_schema(alarm_id, entry)
            if alarm_id in seen:
                raise AlarmConfigError(f"duplicate alarm id {alarm_id!r}")
            seen.add(alarm_id)

    phantom = raw.get("interlocks", {})
    if not isinstance(phantom, dict):
        raise AlarmConfigError("interlocks must be a mapping")
    for name, entry in phantom.items():
        if not isinstance(name, str) or not name or not isinstance(entry, dict):
            raise AlarmConfigError("interlock entries must be named mappings")
        if set(entry) != {"channels", "check", "threshold", "action"}:
            raise AlarmConfigError(f"interlock {name!r} has an invalid schema")
        if not (
            isinstance(entry["channels"], list)
            and entry["channels"]
            and all(isinstance(channel, str) and channel for channel in entry["channels"])
            and entry["check"] in {"any_above", "any_below"}
            and _is_number(entry["threshold"])
            and math.isfinite(entry["threshold"])
            and isinstance(entry["action"], str)
            and entry["action"]
        ):
            raise AlarmConfigError(f"interlock {name!r} has invalid values")


def _parse_engine_config(raw: dict) -> EngineConfig:
    if not isinstance(raw, dict):
        raise AlarmConfigError("engine must be a mapping")
    unknown = set(raw) - {
        "poll_interval_s",
        "rate_window_s",
        "rate_min_points",
        "rate_method",
        "setpoints",
    }
    if unknown:
        raise AlarmConfigError(f"engine contains unknown keys: {sorted(unknown)}")
    setpoints: dict[str, SetpointDef] = {}
    setpoints_raw = raw.get("setpoints", {})
    if not isinstance(setpoints_raw, dict):
        raise AlarmConfigError("engine.setpoints must be a mapping")
    for key, sp_raw in setpoints_raw.items():
        if not isinstance(key, str) or not key or not isinstance(sp_raw, dict):
            raise AlarmConfigError("engine.setpoints entries must be named mappings")
        if not {"source", "default"}.issubset(sp_raw) or set(sp_raw) - {
            "source",
            "default",
            "unit",
        }:
            raise AlarmConfigError(f"engine.setpoints.{key} has an invalid schema")
        source = sp_raw["source"]
        unit = sp_raw.get("unit", "K")
        default = sp_raw["default"]
        if source not in {"experiment_metadata", "constant"}:
            raise AlarmConfigError(f"engine.setpoints.{key}.source is invalid")
        if not isinstance(unit, str) or not unit:
            raise AlarmConfigError(f"engine.setpoints.{key}.unit must be a non-empty string")
        if not _is_number(default):
            raise AlarmConfigError(f"engine.setpoints.{key}.default must be numeric")
        default = float(default)
        if not math.isfinite(default):
            raise AlarmConfigError(f"engine.setpoints.{key}.default must be finite, got {default!r}")
        setpoints[key] = SetpointDef(
            key=key,
            source=source,
            default=default,
            unit=unit,
        )

    poll_interval_raw = raw.get("poll_interval_s", 2.0)
    if not _is_number(poll_interval_raw):
        raise AlarmConfigError("engine.poll_interval_s must be numeric")
    poll_interval_s = float(poll_interval_raw)
    if not (math.isfinite(poll_interval_s) and poll_interval_s > 0):
        raise AlarmConfigError(f"engine.poll_interval_s must be a finite value > 0, got {poll_interval_s!r}")

    rate_window_raw = raw.get("rate_window_s", 120.0)
    if not _is_number(rate_window_raw):
        raise AlarmConfigError("engine.rate_window_s must be numeric")
    rate_window_s = float(rate_window_raw)
    if not (math.isfinite(rate_window_s) and rate_window_s > 0):
        raise AlarmConfigError(f"engine.rate_window_s must be a finite value > 0, got {rate_window_s!r}")

    rate_min_points = raw.get("rate_min_points", 60)
    if type(rate_min_points) is not int:
        raise AlarmConfigError("engine.rate_min_points must be an integer")
    if rate_min_points < 1:
        raise AlarmConfigError(f"engine.rate_min_points must be >= 1, got {rate_min_points!r}")

    return EngineConfig(
        poll_interval_s=poll_interval_s,
        rate_window_s=rate_window_s,
        rate_min_points=rate_min_points,
        rate_method=_validated_rate_method(raw.get("rate_method", "linear_fit")),
        setpoints=setpoints,
    )


def _expand_alarm(
    alarm_id: str,
    alarm_raw: Any,
    channel_groups: dict[str, list[str]],
    phase_filter: list[str] | None = None,
) -> AlarmConfig:
    """Создать AlarmConfig из raw YAML-словаря, раскрыв channel_group."""
    if not isinstance(alarm_raw, dict):
        raise AlarmConfigError(f"alarm {alarm_id!r} must be a mapping")

    cfg = copy.deepcopy(alarm_raw)
    notify = cfg.pop("notify", [])
    if not isinstance(notify, list) or not all(
        isinstance(item, str) and item in {"gui", "telegram", "sound"} for item in notify
    ):
        raise AlarmConfigError(f"alarm {alarm_id!r} notify must be a known-string list")
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
        notify=notify,
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
                f"alarm {alarm_id!r} (check={check}) requires a numeric 'threshold', got {cfg.get('threshold')!r}"
            )
    elif check == "outside_range":
        # alarm_v2._check_threshold_channel L229
        r = cfg.get("range")
        if not (isinstance(r, (list, tuple)) and len(r) == 2 and all(_is_number(x) for x in r)):
            raise AlarmConfigError(
                f"alarm {alarm_id!r} (check=outside_range) requires a 2-element numeric 'range', got {r!r}"
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
    if group_name is not None:
        if not isinstance(group_name, str) or group_name not in groups:
            raise AlarmConfigError(f"unknown channel_group {group_name!r}")
        cfg["channels"] = list(groups[group_name])


def _find_default_config() -> Path | None:
    """Найти config/alarms_v3.yaml, поднимаясь от текущего файла."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "alarms_v3.yaml"
        if candidate.exists():
            return candidate
    return None
