"""Tests for physical_alarms_config loader — Phase A of F-X v3."""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest

from cryodaq.core.physical_alarms_config import (
    _COOLDOWN_DEFAULTS,
    _VACUUM_DEFAULTS,
    load_physical_alarms_config,
)


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "physical_alarms.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _write_complete_vacuum(tmp_path: Path, **overrides: object) -> Path:
    import yaml

    vacuum = {**_VACUUM_DEFAULTS, **overrides}
    path = tmp_path / "physical_alarms.yaml"
    path.write_text(
        yaml.safe_dump({"cooldown": _COOLDOWN_DEFAULTS, "vacuum": vacuum}),
        encoding="utf-8",
    )
    return path


def test_incomplete_vacuum_preserves_valid_cooldown_but_fails_vacuum_safe(tmp_path):
    p = _write(
        tmp_path,
        """
    cooldown:
      enabled: true
      k_p: 3.0
      cold_channel: "Т12"
    vacuum:
      enabled: true
      fire_pressure_mbar: 5.0e-3
    """,
    )
    cd, vd = load_physical_alarms_config(p)
    assert cd["k_p"] == 3.0
    assert cd["cold_channel"] == "Т12"
    assert vd == {**_VACUUM_DEFAULTS, "escalate_to_safety": True}


def test_missing_file_returns_defaults(tmp_path):
    p = tmp_path / "nonexistent.yaml"
    cd, vd = load_physical_alarms_config(p)
    assert cd == _COOLDOWN_DEFAULTS
    assert vd == _VACUUM_DEFAULTS


def test_partial_yaml_fills_missing_section(tmp_path):
    p = _write(
        tmp_path,
        """
    cooldown:
      k_p: 2.0
    """,
    )
    cd, vd = load_physical_alarms_config(p)
    assert cd["k_p"] == 2.0
    # vacuum section entirely missing → full defaults
    assert vd == {**_VACUUM_DEFAULTS, "escalate_to_safety": True}


def test_complete_vacuum_accepts_valid_override(tmp_path):
    p = _write_complete_vacuum(tmp_path, fire_pressure_mbar=5.0e-3)

    _cd, vd = load_physical_alarms_config(p)

    assert vd["fire_pressure_mbar"] == pytest.approx(5.0e-3)
    assert vd["escalate_to_safety"] is False


def test_invalid_type_falls_back_to_default(tmp_path):
    p = _write(
        tmp_path,
        """
    cooldown:
      k_p: "not_a_float"
      sustained_min: 5
    vacuum:
      enabled: true
    """,
    )
    cd, vd = load_physical_alarms_config(p)
    assert cd["k_p"] == _COOLDOWN_DEFAULTS["k_p"]
    assert cd["sustained_min"] == 5


def test_null_value_falls_back_to_default(tmp_path):
    p = _write(
        tmp_path,
        """
    cooldown:
      k_p: null
    vacuum:
      enabled: null
    """,
    )
    cd, vd = load_physical_alarms_config(p)
    assert cd["k_p"] == _COOLDOWN_DEFAULTS["k_p"]
    assert vd["enabled"] == _VACUUM_DEFAULTS["enabled"]


def test_existing_yaml_parse_error_fails_safe_and_visible(tmp_path, caplog):
    p = tmp_path / "physical_alarms.yaml"
    p.write_text("cooldown: {\n  broken yaml", encoding="utf-8")
    with caplog.at_level(logging.CRITICAL):
        cd, vd = load_physical_alarms_config(p)
    assert cd == _COOLDOWN_DEFAULTS
    assert vd == {**_VACUUM_DEFAULTS, "escalate_to_safety": True}
    assert "fail-safe" in caplog.text.lower()


@pytest.mark.parametrize("content", ["[]", "vacuum: []"])
def test_existing_malformed_root_or_vacuum_fails_safe(tmp_path, content, caplog):
    p = _write(tmp_path, content)
    with caplog.at_level(logging.CRITICAL):
        _cd, vd = load_physical_alarms_config(p)
    assert vd["escalate_to_safety"] is True
    assert "fail-safe" in caplog.text.lower()


def test_escalate_to_safety_absent_in_existing_file_fails_safe_true(tmp_path):
    p = _write(
        tmp_path,
        """
    vacuum:
      enabled: true
    """,
    )
    _, vd = load_physical_alarms_config(p)
    assert vd["escalate_to_safety"] is True


def test_escalate_to_safety_true_enables(tmp_path):
    p = _write_complete_vacuum(tmp_path, escalate_to_safety=True)
    _, vd = load_physical_alarms_config(p)
    assert vd["escalate_to_safety"] is True


@pytest.mark.parametrize("raw", ['"true"', '"yes"', "1", '"on"', '"false"'])
def test_escalate_to_safety_strict_bool_rejects_non_bool(tmp_path, raw):
    """Non-bools are rejected as config and trigger the stronger fallback."""
    p = _write(
        tmp_path,
        f"""
    vacuum:
      escalate_to_safety: {raw}
    """,
    )
    _, vd = load_physical_alarms_config(p)
    assert vd["escalate_to_safety"] is True


def test_defaults_round_trip(tmp_path):
    """Defaults can survive a write-read cycle (values are YAML-serialisable)."""
    import yaml

    content = yaml.dump({"cooldown": _COOLDOWN_DEFAULTS, "vacuum": _VACUUM_DEFAULTS})
    p = tmp_path / "physical_alarms.yaml"
    p.write_text(content, encoding="utf-8")
    cd, vd = load_physical_alarms_config(p)
    assert cd["k_p"] == _COOLDOWN_DEFAULTS["k_p"]
    assert vd["fire_pressure_mbar"] == pytest.approx(_VACUUM_DEFAULTS["fire_pressure_mbar"])


def test_invalid_utf8_existing_file_never_raises_and_escalates(tmp_path, caplog):
    p = tmp_path / "physical_alarms.yaml"
    p.write_bytes(b"vacuum:\n  enabled: true\n\xff")

    with caplog.at_level(logging.CRITICAL):
        cd, vd = load_physical_alarms_config(p)

    assert cd == _COOLDOWN_DEFAULTS
    assert vd == {**_VACUUM_DEFAULTS, "escalate_to_safety": True}
    assert "fail-safe" in caplog.text.lower()


@pytest.mark.parametrize("missing", sorted(_VACUUM_DEFAULTS))
def test_existing_vacuum_missing_any_critical_field_fails_safe(tmp_path, missing, caplog):
    import yaml

    vacuum = dict(_VACUUM_DEFAULTS)
    vacuum.pop(missing)
    p = tmp_path / "physical_alarms.yaml"
    p.write_text(yaml.safe_dump({"vacuum": vacuum}), encoding="utf-8")

    with caplog.at_level(logging.CRITICAL):
        _cd, vd = load_physical_alarms_config(p)

    assert vd == {**_VACUUM_DEFAULTS, "escalate_to_safety": True}
    assert "safety schema is invalid" in caplog.text


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"eval_interval_s": float("nan")}, "finite"),
        ({"fire_pressure_mbar": float("inf")}, "finite"),
        ({"sustained_s": 0}, "> 0"),
        ({"arm_threshold_K": 280.0, "disarm_threshold_K": 270.0}, "below"),
        ({"clear_pressure_mbar": 0.1, "fire_pressure_mbar": 0.01}, "below"),
        ({"severity": "WARNING"}, "CRITICAL"),
        ({"escalate_to_safety": "true"}, "boolean"),
        ({"eval_interval_s": 86_401}, "<= 86400"),
        ({"unexpected_field": "unsafe"}, "unknown fields"),
    ],
)
def test_invalid_vacuum_numbers_ranges_order_and_opt_in_fail_safe(
    tmp_path,
    overrides,
    reason,
    caplog,
):
    p = _write_complete_vacuum(tmp_path, **overrides)

    with caplog.at_level(logging.CRITICAL):
        _cd, vd = load_physical_alarms_config(p)

    assert vd == {**_VACUUM_DEFAULTS, "escalate_to_safety": True}
    assert reason in caplog.text


@pytest.mark.parametrize(
    ("key", "value", "reason"),
    [
        ("enabled", 0, "boolean"),
        ("auto_arm", "false", "boolean"),
        ("watchdog_enabled", 1, "boolean"),
        ("k_p", float("nan"), "finite"),
        ("watchdog_sustained_s", float("inf"), "finite"),
        ("eval_interval_s", 0, "> 0"),
        ("sustained_min", 1.5, "integer"),
        ("eta_slip_window_min", -1, "> 0"),
        ("auto_disarm_progress", 1.1, "<= 1"),
        ("eval_interval_s", 86_401, "<= 86400"),
        ("k_p", 101, "<= 100"),
        ("sustained_min", 10_001, "<= 10000"),
        ("eta_slip_window_min", 10_081, "<= 10080"),
        ("watchdog_sustained_s", 604_801, "<= 604800"),
        ("watchdog_level", "ALARM", "one of INFO, WARNING, CRITICAL"),
    ],
)
def test_invalid_cooldown_values_are_visible_and_use_safe_defaults(
    tmp_path,
    key,
    value,
    reason,
    caplog,
):
    import yaml

    cooldown = {**_COOLDOWN_DEFAULTS, key: value}
    path = tmp_path / "physical_alarms.yaml"
    path.write_text(
        yaml.safe_dump({"cooldown": cooldown, "vacuum": _VACUUM_DEFAULTS}),
        encoding="utf-8",
    )

    with caplog.at_level(logging.CRITICAL):
        cooldown_cfg, vacuum_cfg = load_physical_alarms_config(path)

    assert cooldown_cfg == _COOLDOWN_DEFAULTS
    assert vacuum_cfg == _VACUUM_DEFAULTS
    assert "cooldown schema is invalid" in caplog.text
    assert reason in caplog.text


def test_valid_fractional_eval_interval_is_not_truncated(tmp_path) -> None:
    import yaml

    cooldown = {**_COOLDOWN_DEFAULTS, "eval_interval_s": 0.5}
    path = tmp_path / "physical_alarms.yaml"
    path.write_text(
        yaml.safe_dump({"cooldown": cooldown, "vacuum": _VACUUM_DEFAULTS}),
        encoding="utf-8",
    )

    cooldown_cfg, vacuum_cfg = load_physical_alarms_config(path)

    assert cooldown_cfg["eval_interval_s"] == 0.5
    assert vacuum_cfg == _VACUUM_DEFAULTS


def test_unknown_cooldown_field_is_visible_and_uses_defaults(tmp_path, caplog) -> None:
    import yaml

    cooldown = {**_COOLDOWN_DEFAULTS, "enable": False}
    path = tmp_path / "physical_alarms.yaml"
    path.write_text(
        yaml.safe_dump({"cooldown": cooldown, "vacuum": _VACUUM_DEFAULTS}),
        encoding="utf-8",
    )

    with caplog.at_level(logging.CRITICAL):
        cooldown_cfg, vacuum_cfg = load_physical_alarms_config(path)

    assert cooldown_cfg == _COOLDOWN_DEFAULTS
    assert vacuum_cfg == _VACUUM_DEFAULTS
    assert "unknown fields: enable" in caplog.text
