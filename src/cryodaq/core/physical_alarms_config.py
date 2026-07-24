"""Loader for config/physical_alarms.yaml — tunables for CooldownAlarm and VacuumGuard.

Missing YAML retains documented defaults. Existing invalid or safety-incomplete
YAML strengthens vacuum escalation while keeping engine startup available.
"""

from __future__ import annotations

import logging
import math
import os
import stat
import unicodedata
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_MAX_PRODUCTION_CONFIG_BYTES = 64 * 1024
_MAX_PRODUCTION_NODES = 2_048
_MAX_PRODUCTION_DEPTH = 24
_MAX_PRODUCTION_STRING_CHARS = 4_096
_MAX_PRODUCTION_SEQUENCE_ITEMS = 64
_MAX_PREDICTOR_BYTES = 16 * 1024 * 1024

_T11 = "\u042211"
_T12 = "\u042212"
_LANDMARK_REQUIREMENTS = {
    _T11: {
        "role": "warm_stage",
        "physical": (
            "1-\u044f \u0441\u0442\u0443\u043f\u0435\u043d\u044c GM-cooler, ~40K "
            "\u043f\u0440\u0438 \u0440\u0430\u0431\u043e\u0442\u0435"
        ),
        "required_alias": "\u0430\u0437\u043e\u0442\u043d\u0430\u044f \u043f\u043b\u0438\u0442\u0430",
    },
    _T12: {
        "role": "cold_stage",
        "physical": (
            "2-\u044f \u0441\u0442\u0443\u043f\u0435\u043d\u044c GM-cooler, ~2.9K "
            "\u043f\u0440\u0438 \u0440\u0430\u0431\u043e\u0442\u0435"
        ),
        "required_alias": "\u0445\u043e\u043b\u043e\u0434\u043d\u0430\u044f \u0442\u043e\u0447\u043a\u0430",
    },
}


class PhysicalAlarmsConfigError(RuntimeError):
    """Production physical-alarm configuration is absent or unsafe to use."""


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


def _stable_file_snapshot(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _is_reparse_point(metadata: os.stat_result) -> bool:
    return bool(getattr(metadata, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _read_bounded_regular_utf8(path: Path, *, trusted_root: Path | None) -> str:
    if trusted_root is not None:
        root = trusted_root.resolve(strict=True)
        candidate = path.resolve(strict=False)
        if candidate.parent != root:
            raise PhysicalAlarmsConfigError("physical alarms path escapes the selected config directory")
    try:
        before = path.lstat()
    except OSError as exc:
        raise PhysicalAlarmsConfigError("physical alarms configuration metadata is unavailable") from exc
    if path.is_symlink() or _is_reparse_point(before) or not stat.S_ISREG(before.st_mode):
        raise PhysicalAlarmsConfigError("physical alarms configuration must be a non-symlink regular file")
    if before.st_size > _MAX_PRODUCTION_CONFIG_BYTES:
        raise PhysicalAlarmsConfigError(f"physical alarms configuration exceeds {_MAX_PRODUCTION_CONFIG_BYTES} bytes")
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or _is_reparse_point(opened):
                raise PhysicalAlarmsConfigError("physical alarms configuration changed to a nonregular file")
            if not os.path.samestat(before, opened) or (
                before.st_size,
                before.st_mtime_ns,
            ) != (opened.st_size, opened.st_mtime_ns):
                raise PhysicalAlarmsConfigError("physical alarms configuration changed while opening")
            payload = bytearray()
            while len(payload) <= _MAX_PRODUCTION_CONFIG_BYTES:
                chunk = os.read(descriptor, min(8_192, _MAX_PRODUCTION_CONFIG_BYTES + 1 - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)
            if len(payload) > _MAX_PRODUCTION_CONFIG_BYTES:
                raise PhysicalAlarmsConfigError(
                    f"physical alarms configuration exceeds {_MAX_PRODUCTION_CONFIG_BYTES} bytes"
                )
            after = os.fstat(descriptor)
            if _stable_file_snapshot(after) != _stable_file_snapshot(opened):
                raise PhysicalAlarmsConfigError("physical alarms configuration changed while reading")
            if len(payload) != after.st_size:
                raise PhysicalAlarmsConfigError("physical alarms configuration changed size while reading")
            after_path = path.lstat()
            if (
                path.is_symlink()
                or _is_reparse_point(after_path)
                or not stat.S_ISREG(after_path.st_mode)
                or not os.path.samestat(after_path, after)
                or (after_path.st_size, after_path.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            ):
                raise PhysicalAlarmsConfigError("physical alarms configuration path changed while reading")
        finally:
            os.close(descriptor)
    except PhysicalAlarmsConfigError:
        raise
    except OSError as exc:
        raise PhysicalAlarmsConfigError("physical alarms configuration cannot be read") from exc
    try:
        return bytes(payload).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PhysicalAlarmsConfigError("physical alarms configuration is not valid UTF-8") from exc


class _BoundedUniqueSafeLoader(yaml.SafeLoader):
    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._node_count = 0
        self._node_depth = 0

    def compose_node(self, parent: yaml.Node | None, index: object) -> yaml.Node:
        event = self.peek_event()
        if isinstance(event, yaml.events.AliasEvent) or getattr(event, "anchor", None) is not None:
            raise PhysicalAlarmsConfigError("YAML aliases and anchors are not permitted")
        self._node_count += 1
        if self._node_count > _MAX_PRODUCTION_NODES:
            raise PhysicalAlarmsConfigError(f"physical alarms configuration exceeds {_MAX_PRODUCTION_NODES} YAML nodes")
        self._node_depth += 1
        try:
            if self._node_depth > _MAX_PRODUCTION_DEPTH:
                raise PhysicalAlarmsConfigError(f"physical alarms configuration exceeds depth {_MAX_PRODUCTION_DEPTH}")
            return super().compose_node(parent, index)
        finally:
            self._node_depth -= 1


def _construct_unique_mapping(
    loader: yaml.SafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise PhysicalAlarmsConfigError("configuration keys must be scalar strings") from exc
        if duplicate:
            raise PhysicalAlarmsConfigError(f"duplicate configuration key {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_BoundedUniqueSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _validate_bounded_tree(value: Any, *, depth: int = 0) -> None:
    if depth > _MAX_PRODUCTION_DEPTH:
        raise PhysicalAlarmsConfigError(f"physical alarms configuration exceeds depth {_MAX_PRODUCTION_DEPTH}")
    if isinstance(value, dict):
        if len(value) > _MAX_PRODUCTION_SEQUENCE_ITEMS:
            raise PhysicalAlarmsConfigError("configuration mapping contains too many fields")
        for key, child in value.items():
            if not isinstance(key, str):
                raise PhysicalAlarmsConfigError("configuration keys must be strings")
            _validate_bounded_tree(key, depth=depth + 1)
            _validate_bounded_tree(child, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > _MAX_PRODUCTION_SEQUENCE_ITEMS:
            raise PhysicalAlarmsConfigError("configuration list contains too many items")
        for child in value:
            _validate_bounded_tree(child, depth=depth + 1)
        return
    if isinstance(value, str):
        if len(value) > _MAX_PRODUCTION_STRING_CHARS:
            raise PhysicalAlarmsConfigError("configuration string is too long")
        if unicodedata.normalize("NFC", value) != value:
            raise PhysicalAlarmsConfigError("configuration strings must use Unicode NFC")
        if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
            raise PhysicalAlarmsConfigError("configuration strings contain forbidden control or format characters")
        return
    if value is not None and type(value) not in {bool, int, float}:
        raise PhysicalAlarmsConfigError(f"unsupported configuration value type {type(value).__name__}")


def _validate_production_landmarks(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict) or set(raw) != set(_LANDMARK_REQUIREMENTS):
        raise PhysicalAlarmsConfigError("landmarks must contain exactly canonical T11 and T12")
    normalized_aliases = {canonical.casefold() for canonical in _LANDMARK_REQUIREMENTS}
    landmarks: dict[str, dict[str, Any]] = {}
    for canonical, requirement in _LANDMARK_REQUIREMENTS.items():
        entry = raw[canonical]
        if not isinstance(entry, dict) or set(entry) != {"role", "physical", "aliases"}:
            raise PhysicalAlarmsConfigError(f"landmarks[{canonical!r}] must contain exactly role, physical, aliases")
        if entry["role"] != requirement["role"] or entry["physical"] != requirement["physical"]:
            raise PhysicalAlarmsConfigError(f"landmarks[{canonical!r}] contradicts the ratified physical-stage mapping")
        aliases = entry["aliases"]
        if not isinstance(aliases, list) or not aliases:
            raise PhysicalAlarmsConfigError(f"landmarks[{canonical!r}].aliases must be a non-empty list")
        canonical_aliases: list[str] = []
        for alias in aliases:
            if not isinstance(alias, str) or not alias or alias != alias.strip():
                raise PhysicalAlarmsConfigError(
                    f"landmarks[{canonical!r}].aliases must contain trimmed non-empty strings"
                )
            folded = alias.casefold()
            if folded in normalized_aliases:
                raise PhysicalAlarmsConfigError(f"ambiguous or duplicate landmark alias {alias!r}")
            normalized_aliases.add(folded)
            canonical_aliases.append(folded)
        if requirement["required_alias"].casefold() not in canonical_aliases:
            raise PhysicalAlarmsConfigError(f"landmarks[{canonical!r}] is missing its ratified physical alias")
        landmarks[canonical] = {
            "role": entry["role"],
            "physical": entry["physical"],
            "aliases": canonical_aliases,
        }
    return landmarks


def _validate_predictor_path(cooldown: dict[str, Any], *, project_root: Path | None) -> None:
    configured = cooldown["predictor_model_path"]
    if not isinstance(configured, str):
        raise PhysicalAlarmsConfigError("cooldown.predictor_model_path must be a string")
    relative = Path(configured)
    if relative.is_absolute() or ".." in relative.parts or relative.name != "predictor_model.json":
        raise PhysicalAlarmsConfigError(
            "cooldown.predictor_model_path must be a contained relative predictor_model.json path"
        )
    if project_root is None:
        return
    root = project_root.resolve(strict=True)
    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PhysicalAlarmsConfigError("cooldown predictor path escapes the project root") from exc
    if candidate.exists() or candidate.is_symlink():
        try:
            target = candidate.lstat()
        except OSError as exc:
            raise PhysicalAlarmsConfigError(f"cannot inspect cooldown predictor: {exc}") from exc
        if candidate.is_symlink() or not stat.S_ISREG(target.st_mode):
            raise PhysicalAlarmsConfigError("cooldown predictor must be a non-symlink regular file when present")
        if target.st_size > _MAX_PREDICTOR_BYTES:
            raise PhysicalAlarmsConfigError(f"cooldown predictor exceeds {_MAX_PREDICTOR_BYTES} bytes")
    cooldown["predictor_model_path"] = str(candidate)


def load_production_physical_alarms_config(
    path: Path,
    *,
    trusted_config_root: Path | None = None,
    project_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
    try:
        text = _read_bounded_regular_utf8(path, trusted_root=trusted_config_root)
        raw = yaml.load(text, Loader=_BoundedUniqueSafeLoader)
        _validate_bounded_tree(raw)
        if not isinstance(raw, dict) or set(raw) != {"cooldown", "vacuum", "landmarks"}:
            raise PhysicalAlarmsConfigError("physical alarms document must contain exactly cooldown, vacuum, landmarks")
        if not isinstance(raw["cooldown"], dict) or set(raw["cooldown"]) != set(_COOLDOWN_DEFAULTS):
            raise PhysicalAlarmsConfigError("cooldown section is incomplete or contains unknown fields")
        if not isinstance(raw["vacuum"], dict) or set(raw["vacuum"]) != set(_VACUUM_DEFAULTS):
            raise PhysicalAlarmsConfigError("vacuum section is incomplete or contains unknown fields")
        cooldown = _validate_cooldown_config(raw["cooldown"])
        vacuum = _validate_complete_vacuum_config(raw["vacuum"])
        expected_channels = {
            "warm_channel": _T11,
            "cold_channel": _T12,
        }
        for field, expected in expected_channels.items():
            if cooldown[field] != expected:
                raise PhysicalAlarmsConfigError(f"cooldown.{field} must remain bound to canonical {expected}")
        if vacuum["reference_temp_channel"] != _T12:
            raise PhysicalAlarmsConfigError("vacuum.reference_temp_channel must remain bound to canonical T12")
        if vacuum["pressure_channel"] != "VSP63D_1/pressure":
            raise PhysicalAlarmsConfigError("vacuum.pressure_channel contradicts the selected pressure authority")
        landmarks = _validate_production_landmarks(raw["landmarks"])
        _validate_predictor_path(cooldown, project_root=project_root)
        return cooldown, vacuum, landmarks
    except PhysicalAlarmsConfigError:
        raise
    except (OSError, UnicodeError, yaml.YAMLError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise PhysicalAlarmsConfigError(f"invalid physical alarms configuration: {type(exc).__name__}: {exc}") from exc


def load_channel_landmarks_from_document(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate landmarks from an already parsed physical-alarm document."""
    landmarks_raw = raw.get("landmarks")
    if not isinstance(landmarks_raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for channel_id, entry in landmarks_raw.items():
        if not isinstance(channel_id, str) or not isinstance(entry, dict):
            return {}
        aliases = entry.get("aliases")
        if not isinstance(aliases, list) or not all(isinstance(alias, str) and alias.strip() for alias in aliases):
            return {}
        out[channel_id] = {
            "role": str(entry.get("role", "")),
            "physical": str(entry.get("physical", "")),
            "aliases": [alias.strip().lower() for alias in aliases],
        }
    return out


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
