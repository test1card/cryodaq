"""Tests for physical_alarms_config loader — Phase A of F-X v3."""
from __future__ import annotations

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


def test_loads_valid_yaml(tmp_path):
    p = _write(tmp_path, """
    cooldown:
      enabled: true
      k_p: 3.0
      cold_channel: "Т12"
    vacuum:
      enabled: true
      fire_pressure_mbar: 5.0e-3
    """)
    cd, vd = load_physical_alarms_config(p)
    assert cd["k_p"] == 3.0
    assert cd["cold_channel"] == "Т12"
    assert vd["fire_pressure_mbar"] == pytest.approx(5.0e-3)


def test_missing_file_returns_defaults(tmp_path):
    p = tmp_path / "nonexistent.yaml"
    cd, vd = load_physical_alarms_config(p)
    assert cd == _COOLDOWN_DEFAULTS
    assert vd == _VACUUM_DEFAULTS


def test_partial_yaml_fills_missing_section(tmp_path):
    p = _write(tmp_path, """
    cooldown:
      k_p: 2.0
    """)
    cd, vd = load_physical_alarms_config(p)
    assert cd["k_p"] == 2.0
    # vacuum section entirely missing → full defaults
    assert vd == _VACUUM_DEFAULTS


def test_invalid_type_falls_back_to_default(tmp_path):
    p = _write(tmp_path, """
    cooldown:
      k_p: "not_a_float"
      sustained_min: 5
    vacuum:
      enabled: true
    """)
    cd, vd = load_physical_alarms_config(p)
    assert cd["k_p"] == _COOLDOWN_DEFAULTS["k_p"]
    assert cd["sustained_min"] == 5


def test_null_value_falls_back_to_default(tmp_path):
    p = _write(tmp_path, """
    cooldown:
      k_p: null
    vacuum:
      enabled: null
    """)
    cd, vd = load_physical_alarms_config(p)
    assert cd["k_p"] == _COOLDOWN_DEFAULTS["k_p"]
    assert vd["enabled"] == _VACUUM_DEFAULTS["enabled"]


def test_yaml_parse_error_returns_defaults(tmp_path):
    p = tmp_path / "physical_alarms.yaml"
    p.write_text("cooldown: {\n  broken yaml", encoding="utf-8")
    cd, vd = load_physical_alarms_config(p)
    assert cd == _COOLDOWN_DEFAULTS
    assert vd == _VACUUM_DEFAULTS


def test_escalate_to_safety_absent_defaults_false(tmp_path):
    p = _write(tmp_path, """
    vacuum:
      enabled: true
    """)
    _, vd = load_physical_alarms_config(p)
    assert vd["escalate_to_safety"] is False


def test_escalate_to_safety_true_enables(tmp_path):
    p = _write(tmp_path, """
    vacuum:
      escalate_to_safety: true
    """)
    _, vd = load_physical_alarms_config(p)
    assert vd["escalate_to_safety"] is True


@pytest.mark.parametrize("raw", ['"true"', '"yes"', "1", '"on"', '"false"'])
def test_escalate_to_safety_strict_bool_rejects_non_bool(tmp_path, raw):
    """Only YAML `true` enables — strings/ints must NOT (fail-closed)."""
    p = _write(tmp_path, f"""
    vacuum:
      escalate_to_safety: {raw}
    """)
    _, vd = load_physical_alarms_config(p)
    assert vd["escalate_to_safety"] is False


def test_defaults_round_trip(tmp_path):
    """Defaults can survive a write-read cycle (values are YAML-serialisable)."""
    import yaml
    content = yaml.dump({"cooldown": _COOLDOWN_DEFAULTS, "vacuum": _VACUUM_DEFAULTS})
    p = tmp_path / "physical_alarms.yaml"
    p.write_text(content, encoding="utf-8")
    cd, vd = load_physical_alarms_config(p)
    assert cd["k_p"] == _COOLDOWN_DEFAULTS["k_p"]
    assert vd["fire_pressure_mbar"] == pytest.approx(_VACUUM_DEFAULTS["fire_pressure_mbar"])
