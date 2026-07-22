"""Loader for config/physical_alarms.yaml — tunables for CooldownAlarm and VacuumGuard.

Missing YAML retains documented defaults. Existing invalid or safety-incomplete
YAML strengthens vacuum escalation while keeping engine startup available.
"""

from __future__ import annotations

import logging
import math
import unicodedata
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hard-coded defaults (all tunables)
# ---------------------------------------------------------------------------

_COOLDOWN_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "eval_interval_s": 30,
    "k_p": 2.5,
    "sustained_min": 5,
    "base_temp_K": 5.0,
    "base_epsilon_K": 1.0,
    "eta_slip_window_min": 60,
    "eta_slip_message_threshold_h": 0.5,
    "auto_disarm_progress": 0.95,
    "cold_channel": "Т12",
    "warm_channel": "Т11",
    "predictor_model_path": "data/cooldown_model/predictor_model.json",
    # v0.55.12 — these were silently ignored before because absent from
    # defaults; the merge logic only honours keys it recognises.
    "auto_arm": True,
    "watchdog_enabled": False,
    "watchdog_margin_K": 1.0,
    "watchdog_sustained_s": 300.0,
    "watchdog_level": "WARNING",
    # v0.55.12 — cold-start auto-detect threshold (skip auto-arm if the
    # cryostat is already at base T at engine restart).
    "cold_start_skip_margin_K": 5.0,
}

_VACUUM_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "eval_interval_s": 30,
    "pressure_channel": "VSP63D_1/pressure",
    "reference_temp_channel": "Т12",
    "arm_threshold_K": 260.0,
    "disarm_threshold_K": 270.0,
    "fire_pressure_mbar": 1.0e-2,
    "clear_pressure_mbar": 1.0e-3,
    "sustained_s": 30,
    "severity": "CRITICAL",
    # Opt-in SafetyManager escalation on FIRED (default false = alarm-only).
    # Strict bool: only YAML `true` enables — see fail-closed override below.
    "escalate_to_safety": False,
}


def _invalid_existing_config_defaults(reason: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep startup available but strengthen vacuum escalation on corrupt input."""

    logger.critical(
        "physical_alarms.yaml is invalid (%s); enabling fail-safe vacuum escalation",
        reason,
    )
    vacuum = dict(_VACUUM_DEFAULTS)
    vacuum["escalate_to_safety"] = True
    return dict(_COOLDOWN_DEFAULTS), vacuum


def _validate_complete_vacuum_config(loaded: dict[str, Any]) -> dict[str, Any]:
    """Validate the complete safety-bearing vacuum section without coercion."""

    expected = set(_VACUUM_DEFAULTS)
    missing = sorted(expected - set(loaded))
    unknown = sorted(set(loaded) - expected)
    if missing:
        raise ValueError(f"vacuum section is missing critical fields: {', '.join(missing)}")
    if unknown:
        raise ValueError(f"vacuum section has unknown fields: {', '.join(unknown)}")
    for key in ("enabled", "escalate_to_safety"):
        if type(loaded[key]) is not bool:
            raise ValueError(f"vacuum.{key} must be a boolean")
    for key in ("pressure_channel", "reference_temp_channel"):
        value = loaded[key]
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError(f"vacuum.{key} must be a non-empty trimmed string")
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise ValueError(f"vacuum.{key} contains control characters")
    if loaded["severity"] != "CRITICAL":
        raise ValueError("vacuum.severity must remain CRITICAL")

    numeric: dict[str, float] = {}
    for key in (
        "eval_interval_s",
        "arm_threshold_K",
        "disarm_threshold_K",
        "fire_pressure_mbar",
        "clear_pressure_mbar",
        "sustained_s",
    ):
        value = loaded[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"vacuum.{key} must be a number")
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ValueError(f"vacuum.{key} must be finite")
        numeric[key] = normalized
    for key in ("eval_interval_s", "fire_pressure_mbar", "clear_pressure_mbar", "sustained_s"):
        if numeric[key] <= 0:
            raise ValueError(f"vacuum.{key} must be > 0")
    for key in ("arm_threshold_K", "disarm_threshold_K"):
        if numeric[key] < 0:
            raise ValueError(f"vacuum.{key} must be >= 0")
    if numeric["arm_threshold_K"] >= numeric["disarm_threshold_K"]:
        raise ValueError("vacuum arm_threshold_K must be below disarm_threshold_K")
    if numeric["clear_pressure_mbar"] >= numeric["fire_pressure_mbar"]:
        raise ValueError("vacuum clear_pressure_mbar must be below fire_pressure_mbar")
    upper_bounds = {
        "eval_interval_s": 86_400.0,
        "arm_threshold_K": 1_000.0,
        "disarm_threshold_K": 1_000.0,
        "fire_pressure_mbar": 1_000_000.0,
        "clear_pressure_mbar": 1_000_000.0,
        "sustained_s": 86_400.0,
    }
    for key, maximum in upper_bounds.items():
        if numeric[key] > maximum:
            raise ValueError(f"vacuum.{key} must be <= {maximum:g}")
    return dict(loaded)


def _validate_cooldown_config(loaded: dict[str, Any]) -> dict[str, Any]:
    """Validate cooldown overrides without truthiness or non-finite coercion."""

    unknown = sorted(set(loaded) - set(_COOLDOWN_DEFAULTS))
    if unknown:
        raise ValueError(f"cooldown section has unknown fields: {', '.join(unknown)}")
    boolean_keys = {"enabled", "auto_arm", "watchdog_enabled"}
    numeric_keys = {
        key
        for key, default in _COOLDOWN_DEFAULTS.items()
        if isinstance(default, (int, float)) and not isinstance(default, bool)
    }
    string_keys = set(_COOLDOWN_DEFAULTS) - boolean_keys - numeric_keys

    for key in boolean_keys & loaded.keys():
        if type(loaded[key]) is not bool:
            raise ValueError(f"cooldown.{key} must be a boolean")
    for key in numeric_keys & loaded.keys():
        value = loaded[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"cooldown.{key} must be a number")
        if not math.isfinite(float(value)):
            raise ValueError(f"cooldown.{key} must be finite")
    if "sustained_min" in loaded and type(loaded["sustained_min"]) is not int:
        raise ValueError("cooldown.sustained_min must be an integer")

    positive_keys = {
        "eval_interval_s",
        "k_p",
        "sustained_min",
        "eta_slip_window_min",
        "watchdog_sustained_s",
    }
    for key in positive_keys & loaded.keys():
        if float(loaded[key]) <= 0:
            raise ValueError(f"cooldown.{key} must be > 0")
    nonnegative_keys = {
        "base_temp_K",
        "base_epsilon_K",
        "eta_slip_message_threshold_h",
        "watchdog_margin_K",
        "cold_start_skip_margin_K",
    }
    for key in nonnegative_keys & loaded.keys():
        if float(loaded[key]) < 0:
            raise ValueError(f"cooldown.{key} must be >= 0")
    upper_bounds = {
        "eval_interval_s": 86_400.0,
        "k_p": 100.0,
        "sustained_min": 10_000.0,
        "base_temp_K": 1_000.0,
        "base_epsilon_K": 1_000.0,
        "eta_slip_window_min": 10_080.0,
        "eta_slip_message_threshold_h": 8_760.0,
        "watchdog_margin_K": 1_000.0,
        "watchdog_sustained_s": 604_800.0,
        "cold_start_skip_margin_K": 1_000.0,
    }
    for key, maximum in upper_bounds.items():
        if key in loaded and float(loaded[key]) > maximum:
            raise ValueError(f"cooldown.{key} must be <= {maximum:g}")
    if "auto_disarm_progress" in loaded and not (0 < float(loaded["auto_disarm_progress"]) <= 1):
        raise ValueError("cooldown.auto_disarm_progress must be > 0 and <= 1")
    for key in string_keys & loaded.keys():
        value = loaded[key]
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError(f"cooldown.{key} must be a non-empty trimmed string")
        if any(unicodedata.category(character).startswith("C") for character in value):
            raise ValueError(f"cooldown.{key} contains control characters")
    if "watchdog_level" in loaded and loaded["watchdog_level"] not in {
        "INFO",
        "WARNING",
        "CRITICAL",
    }:
        raise ValueError("cooldown.watchdog_level must be one of INFO, WARNING, CRITICAL")
    result = dict(_COOLDOWN_DEFAULTS)
    result.update(loaded)
    return result


def load_physical_alarms_config(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load physical_alarms.yaml.

    Returns ``(cooldown_cfg, vacuum_cfg)`` and never raises. A genuinely
    missing file retains the documented defaults. An existing unreadable,
    corrupt, or safety-incomplete file instead enables fail-safe vacuum
    escalation and emits a CRITICAL diagnostic.
    """
    try:
        path.stat()
    except FileNotFoundError:
        logger.warning("physical_alarms.yaml not found at %s; using built-in defaults", path)
        return dict(_COOLDOWN_DEFAULTS), dict(_VACUUM_DEFAULTS)
    except Exception as exc:
        return _invalid_existing_config_defaults(f"file metadata error: {exc}")

    try:
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except Exception as exc:  # existing corrupt input must never abort startup
        return _invalid_existing_config_defaults(f"read/decode/YAML error: {exc}")

    if not isinstance(raw, dict):
        return _invalid_existing_config_defaults(f"expected mapping, got {type(raw).__name__}")

    cooldown_raw = raw.get("cooldown")
    if not isinstance(cooldown_raw, dict):
        if cooldown_raw is not None:
            logger.warning(
                "physical_alarms.yaml: 'cooldown' section is not a mapping (got %s) — using defaults",
                type(cooldown_raw).__name__,
            )
        cooldown_raw = {}

    vacuum_raw = raw.get("vacuum")
    if not isinstance(vacuum_raw, dict):
        if vacuum_raw is not None:
            logger.warning(
                "physical_alarms.yaml: 'vacuum' section is not a mapping (got %s) — using defaults",
                type(vacuum_raw).__name__,
            )
        vacuum_raw = {}

    try:
        cooldown_cfg = _validate_cooldown_config(cooldown_raw)
    except Exception as exc:
        logger.critical(
            "physical_alarms.yaml cooldown schema is invalid (%s); using safe enabled defaults",
            exc,
        )
        cooldown_cfg = dict(_COOLDOWN_DEFAULTS)

    try:
        vacuum_cfg = _validate_complete_vacuum_config(vacuum_raw)
    except Exception as exc:
        logger.critical(
            "physical_alarms.yaml vacuum safety schema is invalid (%s); enabling fail-safe vacuum escalation",
            exc,
        )
        vacuum_cfg = dict(_VACUUM_DEFAULTS)
        vacuum_cfg["escalate_to_safety"] = True

    return cooldown_cfg, vacuum_cfg


def load_channel_landmarks(path: Path) -> dict[str, dict[str, Any]]:
    """Load the ``landmarks:`` section from physical_alarms.yaml.

    Returns a dict keyed by channel ID — for example::

        {
            "Т11": {
                "role": "warm_stage",
                "physical": "1-я ступень GM-cooler, ~40K при работе",
                "aliases": ["азотная плита", "плита", ...],
            },
            ...
        }

    Aliases are normalized to lowercased, stripped strings so downstream
    consumers (the IntentClassifier prompt builder) can match operator
    phrasing case-insensitively without re-normalizing on every query.

    Returns an empty dict on any failure (missing file, missing section,
    malformed entry, YAML error). Never raises — landmarks are an
    optional layer; engine startup must not depend on them.
    """
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except Exception as exc:
        logger.warning("physical_alarms.yaml landmarks: YAML error — %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    landmarks_raw = raw.get("landmarks")
    if landmarks_raw is None:
        return {}
    if not isinstance(landmarks_raw, dict):
        logger.warning(
            "physical_alarms.yaml: 'landmarks' section is not a mapping (got %s) — ignoring",
            type(landmarks_raw).__name__,
        )
        return {}

    out: dict[str, dict[str, Any]] = {}
    for ch_id, entry in landmarks_raw.items():
        if not isinstance(entry, dict):
            logger.warning(
                "physical_alarms.yaml landmarks[%s]: not a mapping — skipping",
                ch_id,
            )
            continue
        aliases_raw = entry.get("aliases", [])
        if not isinstance(aliases_raw, list):
            logger.warning(
                "physical_alarms.yaml landmarks[%s].aliases: not a list — using []",
                ch_id,
            )
            aliases_raw = []
        aliases = [str(a).strip().lower() for a in aliases_raw if a]
        out[str(ch_id)] = {
            "role": str(entry.get("role", "")),
            "physical": str(entry.get("physical", "")),
            "aliases": aliases,
        }
    return out
