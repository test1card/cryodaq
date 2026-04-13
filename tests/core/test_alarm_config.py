"""Tests for alarm_config.py — loader, channel_group expansion, phase_filter."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock
from datetime import datetime, timezone, timedelta

import pytest
import yaml

from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config, AlarmConfig, EngineConfig
from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "alarms_v3.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# load_alarm_config
# ---------------------------------------------------------------------------

MINIMAL_YAML = """
engine:
  poll_interval_s: 0.5
  rate_window_s: 60
  rate_min_points: 30
  setpoints:
    T12_setpoint:
      source: experiment_metadata
      default: 4.2
      unit: K

channel_groups:
  calibrated: [T11, T12]
  all_temp: [T1, T2, T11, T12]

global_alarms:
  sensor_range:
    alarm_type: threshold
    channel_group: calibrated
    check: outside_range
    range: [1.0, 350.0]
    level: CRITICAL
    notify: [gui, telegram]

  data_stale:
    alarm_type: stale
    channel: T12
    timeout_s: 30
    level: WARNING
    notify: [gui]

phase_alarms:
  cooldown:
    excessive_cooling:
      alarm_type: rate
      channels: [T11, T12]
      check: rate_below
      threshold: -5.0
      level: WARNING
      notify: [gui, telegram]

  measurement:
    detector_drift:
      alarm_type: threshold
      channel: T12
      check: deviation_from_setpoint
      setpoint_source: T12_setpoint
      threshold: 0.5
      level: WARNING
      notify: []
"""


def test_load_returns_engine_config(tmp_path: Path) -> None:
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    engine, _ = load_alarm_config(p)
    assert isinstance(engine, EngineConfig)
    assert engine.poll_interval_s == 0.5
    assert engine.rate_window_s == 60.0
    assert engine.rate_min_points == 30
    assert "T12_setpoint" in engine.setpoints
    sp = engine.setpoints["T12_setpoint"]
    assert sp.default == 4.2
    assert sp.source == "experiment_metadata"
    assert sp.unit == "K"


def test_load_global_alarms(tmp_path: Path) -> None:
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    _, alarms = load_alarm_config(p)
    ids = [a.alarm_id for a in alarms]
    assert "sensor_range" in ids
    assert "data_stale" in ids


def test_channel_group_expanded(tmp_path: Path) -> None:
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    _, alarms = load_alarm_config(p)
    sensor = next(a for a in alarms if a.alarm_id == "sensor_range")
    assert "channels" in sensor.config
    assert "T11" in sensor.config["channels"]
    assert "T12" in sensor.config["channels"]
    # channel_group key should be removed
    assert "channel_group" not in sensor.config


def test_notify_preserved(tmp_path: Path) -> None:
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    _, alarms = load_alarm_config(p)
    sensor = next(a for a in alarms if a.alarm_id == "sensor_range")
    assert "gui" in sensor.notify
    assert "telegram" in sensor.notify


def test_phase_filter_set(tmp_path: Path) -> None:
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    _, alarms = load_alarm_config(p)
    cooling = next(a for a in alarms if a.alarm_id == "excessive_cooling")
    assert cooling.phase_filter == ["cooldown"]

    drift = next(a for a in alarms if a.alarm_id == "detector_drift")
    assert drift.phase_filter == ["measurement"]


def test_global_alarm_phase_filter_none(tmp_path: Path) -> None:
    p = _write_yaml(tmp_path, MINIMAL_YAML)
    _, alarms = load_alarm_config(p)
    stale = next(a for a in alarms if a.alarm_id == "data_stale")
    assert stale.phase_filter is None


def test_missing_file_raises_alarm_config_error() -> None:
    """A.7: missing alarms_v3.yaml must be startup-fatal."""
    with pytest.raises(AlarmConfigError, match="not found"):
        load_alarm_config("/nonexistent/alarms.yaml")


def test_none_path_finds_default() -> None:
    """load_alarm_config(None) should find config/alarms_v3.yaml via traversal."""
    engine, alarms = load_alarm_config(None)
    assert isinstance(engine, EngineConfig)
    assert isinstance(alarms, list)


def test_malformed_yaml_raises_alarm_config_error(tmp_path: Path) -> None:
    """A.7: malformed YAML must raise AlarmConfigError."""
    p = tmp_path / "bad.yaml"
    p.write_text("not: valid: yaml: [broken")
    with pytest.raises(AlarmConfigError, match="YAML parse error"):
        load_alarm_config(p)


def test_non_mapping_raises_alarm_config_error(tmp_path: Path) -> None:
    """A.7: non-mapping YAML must raise AlarmConfigError."""
    p = tmp_path / "list.yaml"
    p.write_text("- item1\n- item2\n")
    with pytest.raises(AlarmConfigError, match="malformed"):
        load_alarm_config(p)


def test_alarm_config_error_is_runtime_error_subclass() -> None:
    """A.7: AlarmConfigError must be catchable as RuntimeError."""
    err = AlarmConfigError("test")
    assert isinstance(err, RuntimeError)


def test_composite_conditions_channel_group_expanded(tmp_path: Path) -> None:
    content = """
channel_groups:
  sensors: [T11, T12]

global_alarms:
  vac_cold:
    alarm_type: composite
    operator: AND
    conditions:
      - channel_group: sensors
        check: any_below
        threshold: 200
      - channel: P1
        check: above
        threshold: 1.0e-3
    level: CRITICAL
    notify: [gui]
"""
    p = _write_yaml(tmp_path, content)
    _, alarms = load_alarm_config(p)
    vac = next(a for a in alarms if a.alarm_id == "vac_cold")
    conds = vac.config["conditions"]
    sensor_cond = next(c for c in conds if "channels" in c or "channel_group" in c)
    # channel_group should be expanded
    assert "channel_group" not in sensor_cond
    assert sensor_cond["channels"] == ["T11", "T12"]


# ---------------------------------------------------------------------------
# ExperimentPhaseProvider
# ---------------------------------------------------------------------------

def _make_mgr(phase: str | None = "cooldown", started_ago_s: float = 3700.0):
    mgr = MagicMock()
    mgr.get_current_phase.return_value = phase
    if phase:
        dt = datetime.now(timezone.utc) - timedelta(seconds=started_ago_s)
        mgr.get_phase_history.return_value = [
            {"phase": phase, "started_at": dt.isoformat(), "ended_at": None}
        ]
        mgr.get_active_experiment.return_value = MagicMock()
    else:
        mgr.get_phase_history.return_value = []
        mgr.get_active_experiment.return_value = None
    return mgr


def test_phase_provider_returns_phase() -> None:
    provider = ExperimentPhaseProvider(_make_mgr("cooldown"))
    assert provider.get_current_phase() == "cooldown"


def test_phase_provider_none_when_no_experiment() -> None:
    provider = ExperimentPhaseProvider(_make_mgr(None))
    assert provider.get_current_phase() is None


def test_phase_provider_elapsed_s() -> None:
    provider = ExperimentPhaseProvider(_make_mgr("cooldown", started_ago_s=3700.0))
    elapsed = provider.get_phase_elapsed_s()
    assert abs(elapsed - 3700.0) < 2.0  # 2s tolerance


def test_phase_provider_elapsed_zero_no_phase() -> None:
    provider = ExperimentPhaseProvider(_make_mgr(None))
    assert provider.get_phase_elapsed_s() == 0.0


# ---------------------------------------------------------------------------
# ExperimentSetpointProvider
# ---------------------------------------------------------------------------

def _make_setpoint_defs():
    from cryodaq.core.alarm_config import SetpointDef
    return {
        "T12_setpoint": SetpointDef(
            key="T12_setpoint",
            source="experiment_metadata",
            default=4.2,
            unit="K",
        )
    }


def test_setpoint_from_custom_fields() -> None:
    mgr = MagicMock()
    active = MagicMock()
    active.custom_fields = {"T12_setpoint": "3.8"}
    mgr.get_active_experiment.return_value = active
    provider = ExperimentSetpointProvider(mgr, _make_setpoint_defs())
    assert abs(provider.get("T12_setpoint") - 3.8) < 1e-9


def test_setpoint_fallback_to_default() -> None:
    mgr = MagicMock()
    mgr.get_active_experiment.return_value = None
    provider = ExperimentSetpointProvider(mgr, _make_setpoint_defs())
    assert provider.get("T12_setpoint") == 4.2


def test_setpoint_missing_key_returns_zero() -> None:
    mgr = MagicMock()
    mgr.get_active_experiment.return_value = None
    provider = ExperimentSetpointProvider(mgr, {})
    assert provider.get("nonexistent") == 0.0


def test_setpoint_invalid_custom_field_fallback() -> None:
    """Non-numeric custom_field → default."""
    mgr = MagicMock()
    active = MagicMock()
    active.custom_fields = {"T12_setpoint": "not_a_number"}
    mgr.get_active_experiment.return_value = active
    provider = ExperimentSetpointProvider(mgr, _make_setpoint_defs())
    assert provider.get("T12_setpoint") == 4.2
