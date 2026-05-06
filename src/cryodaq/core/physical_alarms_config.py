"""Loader for config/physical_alarms.yaml — tunables for CooldownAlarm and VacuumGuard.

Graceful degradation: missing or partial YAML returns hard-coded defaults.
No exceptions raised at load time — engine must start regardless.
"""

from __future__ import annotations

import logging
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
}


def _merge_with_defaults(loaded: dict, defaults: dict) -> dict:
    """Return defaults dict updated with values from loaded, type-checked per-key."""
    result = dict(defaults)
    for key, default_val in defaults.items():
        if key not in loaded:
            continue
        val = loaded[key]
        if val is None:
            logger.warning("physical_alarms.yaml: '%s' is null, using default %r", key, default_val)
            continue
        if default_val is not None and not isinstance(val, type(default_val)):
            try:
                val = type(default_val)(val)
            except (TypeError, ValueError):
                logger.warning(
                    "physical_alarms.yaml: '%s' type mismatch (got %s, expected %s), using default %r",
                    key,
                    type(val).__name__,
                    type(default_val).__name__,
                    default_val,
                )
                continue
        result[key] = val
    return result


def load_physical_alarms_config(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load physical_alarms.yaml.

    Returns (cooldown_cfg, vacuum_cfg). On any failure, returns hard-coded defaults
    and logs a WARNING. Never raises.
    """
    if not path.exists():
        logger.warning("physical_alarms.yaml not found at %s — using built-in defaults", path)
        return dict(_COOLDOWN_DEFAULTS), dict(_VACUUM_DEFAULTS)

    try:
        with path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        logger.warning("physical_alarms.yaml YAML error — using defaults: %s", exc)
        return dict(_COOLDOWN_DEFAULTS), dict(_VACUUM_DEFAULTS)

    if not isinstance(raw, dict):
        logger.warning(
            "physical_alarms.yaml: expected mapping, got %s — using defaults", type(raw).__name__
        )
        return dict(_COOLDOWN_DEFAULTS), dict(_VACUUM_DEFAULTS)

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

    cooldown_cfg = _merge_with_defaults(cooldown_raw, _COOLDOWN_DEFAULTS)
    vacuum_cfg = _merge_with_defaults(vacuum_raw, _VACUUM_DEFAULTS)

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
    except yaml.YAMLError as exc:
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
