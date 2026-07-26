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
            f"alarms_v3.yaml not found at {path} — refusing to start alarm engine without alarm configuration"
        )

    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise AlarmConfigError(f"alarms_v3.yaml at {path}: YAML parse error — {exc}") from exc

    if not isinstance(raw, dict):
        raise AlarmConfigError(f"alarms_v3.yaml at {path} is malformed (expected mapping, got {type(raw).__name__})")

    channel_groups: dict[str, list[str]] = raw.get("channel_groups", {})
    try:
        engine_cfg = _parse_engine_config(raw.get("engine", {}))
        alarms: list[AlarmConfig] = []

        # --- Global alarms ---
        for alarm_id, alarm_raw in raw.get("global_alarms", {}).items():
            alarms.append(_expand_alarm(alarm_id, alarm_raw, channel_groups))

        # --- Phase alarms ---
        for phase_name, phase_dict in raw.get("phase_alarms", {}).items():
            if not isinstance(phase_dict, dict):
                continue
            for alarm_id, alarm_raw in phase_dict.items():
                alarms.append(_expand_alarm(alarm_id, alarm_raw, channel_groups, phase_filter=[phase_name]))
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise AlarmConfigError(f"alarms_v3.yaml at {path}: invalid config value — {type(exc).__name__}: {exc}") from exc

    return engine_cfg, alarms


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_engine_config(raw: dict) -> EngineConfig:
    setpoints: dict[str, SetpointDef] = {}
    for key, sp_raw in raw.get("setpoints", {}).items():
        default = float(sp_raw.get("default", 0.0))
        if not math.isfinite(default):
            raise AlarmConfigError(f"engine.setpoints.{key}.default must be finite, got {default!r}")
        setpoints[key] = SetpointDef(
            key=key,
            source=sp_raw.get("source", "constant"),
            default=default,
            unit=sp_raw.get("unit", "K"),
        )

    poll_interval_s = float(raw.get("poll_interval_s", 2.0))
    if not (math.isfinite(poll_interval_s) and poll_interval_s > 0):
        raise AlarmConfigError(f"engine.poll_interval_s must be a finite value > 0, got {poll_interval_s!r}")

    rate_window_s = float(raw.get("rate_window_s", 120.0))
    if not (math.isfinite(rate_window_s) and rate_window_s > 0):
        raise AlarmConfigError(f"engine.rate_window_s must be a finite value > 0, got {rate_window_s!r}")

    rate_min_points = int(raw.get("rate_min_points", 60))
    if rate_min_points < 1:
        raise AlarmConfigError(f"engine.rate_min_points must be >= 1, got {rate_min_points!r}")

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
) -> AlarmConfig:
    """Создать AlarmConfig из raw YAML-словаря, раскрыв channel_group.

    Fail-closed: a non-dict alarm entry (e.g. ``global_alarms: {bad: "typo"}``)
    used to return None and be silently DROPPED by the caller, so the alarm
    simply went MISSING from the loaded set — no error, no log, and an
    operator who believes it is configured. Skipping a malformed entry is the
    fail-open shape this series has been eliminating; raise instead, naming
    the alarm id and the offending value.
    """
    if not isinstance(alarm_raw, dict):
        raise AlarmConfigError(f"alarm {alarm_id!r} must be a mapping, got {type(alarm_raw).__name__} {alarm_raw!r}")

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
    _expand_channel_group(alarm_id, cfg, channel_groups)

    # Expand channel_group inside composite conditions
    for i, cond in enumerate(cfg.get("conditions", [])):
        if isinstance(cond, dict):
            _expand_channel_group(alarm_id, cond, channel_groups, context=f"conditions[{i}]")

    return AlarmConfig(
        alarm_id=alarm_id,
        config=cfg,
        phase_filter=phase_filter,
        notify=notify if isinstance(notify, list) else [notify],
    )


def _is_number(value: Any) -> bool:
    """True for a real numeric scalar (rejects bool, str, None)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# alarm_type values recognised by alarm_v2.AlarmEvaluator.evaluate() (alarm_v2.py:185-200).
# Anything else falls into evaluate()'s own `else` branch, which only logs a
# warning and returns None — i.e. the alarm silently never fires at runtime.
_VALID_ALARM_TYPES = frozenset({"threshold", "rate", "composite", "stale"})

# check values recognised by alarm_v2._check_threshold_channel (alarm_v2.py:261-285).
# Its own `else` branch (L283-285) only logs a warning and returns (False, value).
_VALID_THRESHOLD_CHECKS = frozenset(
    {"above", "below", "outside_range", "deviation_from_setpoint", "fault_count_in_window"}
)

# check values recognised by alarm_v2._eval_rate (alarm_v2.py:394-434). Unknown
# values leave `fired` at its initial False — the rate alarm silently never fires.
_VALID_RATE_CHECKS = frozenset({"rate_above", "rate_below", "rate_near_zero", "relative_rate_near_zero"})

# check values recognised by alarm_v2._eval_condition (alarm_v2.py:329-388), used
# for composite sub-conditions and rate additional_condition. Its own `else`
# branch (L386-388) only logs a warning and returns False.
_VALID_CONDITION_CHECKS = frozenset(
    {"any_below", "any_above", "above", "below", "rate_above", "rate_below", "rate_near_zero"}
)

# operator values recognised by alarm_v2._eval_composite (alarm_v2.py:299-305).
# The runtime comparison is CASE-SENSITIVE (`operator == "AND"`), so "and"/"And"
# fall into its `else` branch, which only logs a warning and returns None — a
# CRITICAL annunciator that loaded cleanly then silently never fires. Do NOT
# normalise case at load time: that would mask a config typo by changing runtime
# behaviour instead of rejecting it. Absent operator is legitimate — runtime
# defaults to "AND" (alarm_v2.py:292).
_VALID_COMPOSITE_OPERATORS = frozenset({"AND", "OR"})

# Channel-selector keys accepted by alarm_v2._resolve_channels (alarm_v2.py:468-476):
#   `channels` (list) — returned verbatim (L470-471)
#   `channel`  (scalar) — wrapped in a one-element list, unless it is the
#               phase_elapsed_s pseudo-channel which is intentionally NOT
#               resolved here (L472-475)
#   `channel_group` — not read at runtime; _expand_channel_group rewrites it to
#               `channels` at load, so it is a valid selector at validation
#               time (it will be gone before the evaluator ever sees the cfg).
# Without one of these keys _resolve_channels returns [] (L476), and the
# per-channel for-loop in _eval_threshold (L223), _eval_rate (L401), and
# _eval_stale (L447) never executes — the alarm returns None forever (a dead
# annunciator that looks configured).
_MULTI_CHANNEL_SELECTOR_KEYS = frozenset({"channels", "channel", "channel_group"})

# Sub-condition checks that read their selector via _resolve_channels(cond)
# (alarm_v2.py:334/339) — the multi-channel family. Accept channel/channels/
# channel_group. An empty resolution makes any() over [] return False (L336/341)
# → silently dead.
_MULTI_CHANNEL_CONDITION_CHECKS = frozenset({"any_below", "any_above"})

# Sub-condition checks that read cond.get("channel") DIRECTLY
# (alarm_v2.py:344/355/362/370/378) — the single-channel family. They do NOT
# call _resolve_channels, so `channels`/`channel_group` do NOT satisfy them:
# even after channel_group expansion sets `channels`, cond.get("channel") stays
# None and `if not ch: return False` (L345/356/363/371/379) fires → silently
# dead. Only a present, non-empty `channel` string is valid. The special value
# "phase_elapsed_s" is legitimate for `above` (L348-350 re-routes it to the
# phase provider) and must not be rejected.
_SINGLE_CHANNEL_CONDITION_CHECKS = frozenset({"above", "below", "rate_above", "rate_below", "rate_near_zero"})


def _validate_required_keys(alarm_id: str, cfg: dict) -> None:
    """Fail-closed presence/type check of evaluate-time required keys.

    Mirrors EVERY hard subscript in alarm_v2 so a misconfigured alarm
    fails closed at startup (AlarmConfigError) instead of silently
    returning None at runtime (KeyError caught by evaluate()).

    Also mirrors every dispatch `else` branch (alarm_type / check /
    channel_group) that would otherwise let an unrecognised value — e.g. a
    typo like alarm_type: composit — load cleanly and then silently never
    fire at runtime (evaluate() logs a warning and returns None; see
    alarm_v2.py:198-200, 283-285, 386-388).

    alarm_type: threshold — _check_threshold_channel (alarm_v2.py:224-233)
      - check above/below             → numeric `threshold`
      - check outside_range           → 2-element numeric `range`
      - check deviation_from_setpoint → str `setpoint_source` + numeric `threshold`
      - check fault_count_in_window   → exempt (uses .get("min_fault_count", 1))
      - any other check               → rejected (unknown to alarm_v2)
      - channel selector (channel/channels/channel_group) required —
        _eval_threshold (L218) calls _resolve_channels; [] → never fires

    alarm_type: rate — _eval_rate (alarm_v2.py:362-365)
      - check rate_above/rate_below   → numeric `threshold`
      - check rate_near_zero / relative_rate_near_zero → exempt (.get("rate_threshold", …))
      - any other check               → rejected (unknown to alarm_v2)
      - channel selector (channel/channels/channel_group) required —
        _eval_rate (L395) calls _resolve_channels; [] → never fires
      - additional_condition (if present/non-None) → must be a dict and is
        validated as a composite sub-condition; a truthy non-dict reaches
        _eval_condition and dies silently (defect #4)

    alarm_type: composite — sub-conditions via _eval_condition (alarm_v2.py:329-388)
      - operator AND|OR (case-sensitive; absent defaults to AND, alarm_v2.py:292)
        any other / wrong-case / non-string operator → rejected
      - check any_below / any_above / above / below / rate_above / rate_below
        → each sub-condition requires numeric `threshold`
      - check rate_near_zero → exempt (.get("rate_threshold", 0.1))
      - any other check       → rejected (unknown to alarm_v2)
      - channel selector required per check family (see _validate_condition):
        any_below/any_above accept channel/channels/channel_group;
        above/below/rate_* accept ONLY scalar `channel`

    alarm_type: stale → no hard reads, exempt.

    Any other alarm_type → rejected (unknown to alarm_v2).
    """
    alarm_type = cfg.get("alarm_type")

    if alarm_type == "threshold":
        _validate_threshold_check(alarm_id, cfg)
        # channel selector — alarm_v2._eval_threshold (L218) calls
        # _resolve_channels(cfg); without one it returns [] and the per-channel
        # for-loop (L223) never runs → the alarm returns None forever (dead
        # annunciator that looks configured).
        _require_multi_channel_selector(alarm_id, cfg, "(alarm_type=threshold)")

    elif alarm_type == "rate":
        # alarm_v2._eval_rate L362-365 / L407-417
        check = cfg.get("check", "rate_above")
        if check not in _VALID_RATE_CHECKS:
            raise AlarmConfigError(
                f"alarm {alarm_id!r} has alarm_type=rate with unknown check "
                f"{check!r}; valid checks are {sorted(_VALID_RATE_CHECKS)}"
            )
        if check in ("rate_above", "rate_below"):
            if not _is_number(cfg.get("threshold")):
                raise AlarmConfigError(
                    f"alarm {alarm_id!r} (alarm_type=rate, check={check}) requires a "
                    f"numeric 'threshold', got {cfg.get('threshold')!r}"
                )
        # channel selector — alarm_v2._eval_rate (L395) calls _resolve_channels;
        # without one it returns [] and the per-channel for-loop (L401) never
        # runs → the alarm returns None forever.
        _require_multi_channel_selector(alarm_id, cfg, "(alarm_type=rate)")
        # additional_condition is passed to _eval_condition (alarm_v2._eval_rate
        # L421-422: `if add_cond and not self._eval_condition(add_cond)`). A
        # truthy non-dict (e.g. a string) reaches _eval_condition which hard-
        # reads cond.get(...) (alarm_v2.py:331) → AttributeError → swallowed by
        # evaluate()'s broad `except Exception` (L201-203) → returns None →
        # silently dead. A falsy non-dict (None/absent) is skipped by the
        # `if add_cond` guard and is harmless, but any non-None value must be
        # a dict — then validate it as a sub-condition.
        add_cond = cfg.get("additional_condition")
        if add_cond is not None:
            if not isinstance(add_cond, dict):
                raise AlarmConfigError(
                    f"alarm {alarm_id!r} additional_condition must be a sub-condition "
                    f"dict (or null/absent), got {type(add_cond).__name__} {add_cond!r}"
                )
            _validate_condition(alarm_id, add_cond, context="additional_condition")

    elif alarm_type == "composite":
        # composite operator — alarm_v2._eval_composite (L291-305) dispatches on
        # a case-sensitive `operator == "AND"` / `== "OR"`; its `else` branch
        # only logs a warning and returns None, so a typo'd, wrong-case, or
        # non-string operator loads cleanly then silently never fires (a dead
        # CRITICAL annunciator that looks healthy). Absent operator is
        # legitimate — runtime defaults to "AND" (L292). isinstance() short-
        # circuits before the membership test so an unhashable value (e.g. a
        # list) is rejected here rather than raising TypeError.
        operator = cfg.get("operator", "AND")
        if not isinstance(operator, str) or operator not in _VALID_COMPOSITE_OPERATORS:
            raise AlarmConfigError(
                f"alarm {alarm_id!r} (alarm_type=composite) has unknown operator "
                f"{operator!r}; valid operators are {sorted(_VALID_COMPOSITE_OPERATORS)}"
            )
        # composite `conditions` — alarm_v2._eval_composite (L293-300) does
        # `conditions = cfg.get("conditions", [])` then
        # `results = [self._eval_condition(c) for c in conditions]`, then
        # all(results) for AND / any(results) for OR. Three fail-open shapes
        # were VERIFIED by running the evaluator against the pre-fix loader:
        #
        #   - missing/empty conditions + AND (the default op): all([]) is True
        #     → the alarm FIRES on vacuous truth forever. Observed a CRITICAL
        #     annunciator firing continuously with channels=[] and no evidence.
        #   - missing/empty conditions + OR: any([]) is False → silently never
        #     fires. Same dead-annunciator class as the operator defect above.
        #   - a non-dict entry (e.g. conditions: ["typo_string"]): _eval_condition
        #     does cond.get(...) (alarm_v2.py:331) → AttributeError → swallowed
        #     by evaluate()'s broad `except Exception` → returns None → silently
        #     dead. The loader previously SKIPPED non-dict entries; skipping a
        #     malformed entry is exactly the fail-open shape being eliminated.
        #
        # Reject all three at load time. A non-list `conditions` (e.g. a dict
        # or a string) is the same hole one level up and is rejected the same
        # way rather than silently accepted.
        if "conditions" not in cfg:
            raise AlarmConfigError(
                f"alarm {alarm_id!r} (alarm_type=composite) is missing required "
                f"field 'conditions' (a non-empty list of sub-condition dicts); "
                f"runtime cfg.get('conditions', []) yields [] → all([])/any([]) "
                f"is vacuous (AND fires forever, OR never fires)"
            )
        conditions = cfg["conditions"]
        if not isinstance(conditions, list):
            raise AlarmConfigError(
                f"alarm {alarm_id!r} (alarm_type=composite) field 'conditions' "
                f"must be a list, got {type(conditions).__name__} {conditions!r}"
            )
        if not conditions:
            raise AlarmConfigError(
                f"alarm {alarm_id!r} (alarm_type=composite) field 'conditions' "
                f"is an empty list; all([])/any([]) is vacuous (AND fires "
                f"forever, OR never fires) — supply at least one sub-condition"
            )
        # Each element of `conditions` is passed to _eval_condition
        # (alarm_v2.py:331 hard-reads cond.get(...)). Reject a non-dict entry
        # instead of skipping it, naming the index and offending value so an
        # operator can find the fault without reading source.
        for i, cond in enumerate(conditions):
            if not isinstance(cond, dict):
                raise AlarmConfigError(
                    f"alarm {alarm_id!r} (alarm_type=composite) "
                    f"conditions[{i}] must be a sub-condition dict, got "
                    f"{type(cond).__name__} {cond!r}"
                )
            _validate_condition(alarm_id, cond, context=f"conditions[{i}]")

    elif alarm_type == "stale":
        pass  # no hard reads — exempt (alarm_v2._eval_stale, alarm_v2.py:440-462)

    else:
        raise AlarmConfigError(
            f"alarm {alarm_id!r} has unknown alarm_type {alarm_type!r}; valid values are {sorted(_VALID_ALARM_TYPES)}"
        )


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
    elif check == "fault_count_in_window":
        pass  # exempt — uses .get("min_fault_count", 1), no hard subscript
    else:
        raise AlarmConfigError(
            f"alarm {alarm_id!r} has alarm_type=threshold with unknown check "
            f"{check!r}; valid checks are {sorted(_VALID_THRESHOLD_CHECKS)}"
        )


def _validate_condition(alarm_id: str, cond: dict, context: str) -> None:
    """Validate a composite sub-condition or additional_condition dict.

    Mirrors alarm_v2._eval_condition (alarm_v2.py:329-388).
    Threshold hard-reads:
      any_below, any_above              → cond["threshold"]  (L335/340)
      above, below                      → cond["threshold"]  (L350/352/359)
      rate_above, rate_below            → cond["threshold"]  (L367/375)
      rate_near_zero                    → exempt (.get("rate_threshold", 0.1), L383)
    Channel selector (which channel(s) the check evaluates):
      any_below, any_above              → _resolve_channels(cond) (L334/339):
                                          multi-channel family — accepts
                                          channel/channels/channel_group
      above, below, rate_above,
      rate_below, rate_near_zero        → cond.get("channel") (L344/355/362/370/
                                          378): single-channel family — reads
                                          `channel` DIRECTLY, not _resolve_channels,
                                          so channels/channel_group do NOT satisfy
                                          it; `if not ch: return False` (L345/356/
                                          363/371/379) makes an absent/falsy channel
                                          dead. "phase_elapsed_s" is legitimate for
                                          `above` (L348-350).
    """
    check = cond.get("check", "above")
    if check not in _VALID_CONDITION_CHECKS:
        raise AlarmConfigError(
            f"alarm {alarm_id!r} {context} has unknown check {check!r}; "
            f"valid checks are {sorted(_VALID_CONDITION_CHECKS)}"
        )
    needs_threshold = check in ("any_below", "any_above", "above", "below", "rate_above", "rate_below")
    if needs_threshold and not _is_number(cond.get("threshold")):
        raise AlarmConfigError(
            f"alarm {alarm_id!r} {context} (check={check}) requires a numeric 'threshold', "
            f"got {cond.get('threshold')!r}"
        )
    # Channel selector — which channel(s) this sub-condition evaluates. The
    # two check families read the selector differently (see docstring above);
    # without the right one the check returns False forever — a dead
    # annunciator that looks configured.
    _validate_condition_selector(alarm_id, cond, check, context)


def _require_multi_channel_selector(alarm_id: str, cfg: dict, context: str) -> None:
    """Require a selector that _resolve_channels expands to a non-empty list.

    Mirrors alarm_v2._resolve_channels (L468-476): accepts ``channels`` (list),
    ``channel`` (scalar), or ``channel_group`` (rewritten to ``channels`` at
    load by _expand_channel_group). Without one, _resolve_channels returns []
    and the for-loop in _eval_threshold (L223) / _eval_rate (L401) never
    executes, so the alarm returns None forever — a dead annunciator that
    looks configured.
    """
    if not any(key in cfg for key in _MULTI_CHANNEL_SELECTOR_KEYS):
        raise AlarmConfigError(
            f"alarm {alarm_id!r} {context} requires a channel selector "
            f"('channel', 'channels', or 'channel_group'); without one "
            f"alarm_v2._resolve_channels returns [] and the alarm never fires"
        )


def _validate_condition_selector(alarm_id: str, cond: dict, check: str, context: str) -> None:
    """Require the channel selector the check family actually reads at runtime.

    Two families, derived from alarm_v2._eval_condition (L329-388):
      any_below / any_above (L333-341): call _resolve_channels(cond), so they
        accept channel/channels/channel_group — the multi-channel family.
      above / below / rate_above / rate_below / rate_near_zero (L343-384): read
        cond.get('channel') DIRECTLY and do NOT call _resolve_channels, so only
        a scalar ``channel`` satisfies them. ``if not ch: return False``
        (L345/356/363/371/379) makes an absent/falsy channel return False
        forever — silently dead. ``phase_elapsed_s`` is legitimate for ``above``
        (L348-350 re-routes it to the phase provider).
    """
    if check in _MULTI_CHANNEL_CONDITION_CHECKS:
        _require_multi_channel_selector(alarm_id, cond, context)
    elif check in _SINGLE_CHANNEL_CONDITION_CHECKS:
        ch = cond.get("channel")
        if not isinstance(ch, str) or not ch:
            raise AlarmConfigError(
                f"alarm {alarm_id!r} {context} (check={check}) requires a "
                f"'channel' string selector, got {ch!r}; alarm_v2._eval_condition "
                f"reads cond.get('channel') directly (not _resolve_channels) and "
                f"returns False forever when it is absent or falsy "
                f"(alarm_v2.py:345/356/363/371/379). 'channels'/'channel_group' "
                f"are NOT read by this check — use 'channel'."
            )


def _expand_channel_group(
    alarm_id: str,
    cfg: dict,
    groups: dict[str, list[str]],
    context: str = "",
) -> None:
    """Заменить channel_group → channels in-place.

    Fail-closed: a channel_group typo (e.g. "uncalibrted") must not be
    silently dropped. Previously an unknown group_name left `cfg` without a
    `channels` key at all, so alarm_v2._resolve_channels() resolved to an
    empty list at runtime and the alarm silently never fired (no hard read,
    no exception — a dead annunciator that looks configured).
    """
    group_name = cfg.pop("channel_group", None)
    if group_name is None:
        return
    if group_name not in groups:
        where = f" {context}" if context else ""
        raise AlarmConfigError(
            f"alarm {alarm_id!r}{where} references unknown channel_group "
            f"{group_name!r}; known groups are {sorted(groups)}"
        )
    cfg["channels"] = list(groups[group_name])


def _find_default_config() -> Path | None:
    """Найти config/alarms_v3.yaml, поднимаясь от текущего файла."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "alarms_v3.yaml"
        if candidate.exists():
            return candidate
    return None
