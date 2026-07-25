"""Fail-closed load-time validation for alarms_v3.yaml.

A misconfigured *safety-relevant* alarm must fail CLOSED at startup
(AlarmConfigError) rather than silently never-firing at runtime — the
evaluate-time KeyError backstop in alarm_v2 leaves only an ERROR log,
so the alarm silently disappears. These tests pin the load-time guards.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from cryodaq.core.alarm_config import AlarmConfigError, load_alarm_config


def _write_yaml(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "alarms_v3.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# threshold alarm — required keys per check
# ---------------------------------------------------------------------------


def test_threshold_check_above_missing_threshold_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          over_power:
            alarm_type: threshold
            channel: smua_power
            check: above
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="threshold"):
        load_alarm_config(p)


def test_threshold_check_below_missing_threshold_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          low_disk:
            alarm_type: threshold
            channel: system_disk_gb
            check: below
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="threshold"):
        load_alarm_config(p)


def test_threshold_check_above_nonnumeric_threshold_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          over_power:
            alarm_type: threshold
            channel: smua_power
            check: above
            threshold: not_a_number
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="threshold"):
        load_alarm_config(p)


def test_outside_range_missing_range_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          sensor_range:
            alarm_type: threshold
            channel: T11
            check: outside_range
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="range"):
        load_alarm_config(p)


def test_outside_range_wrong_length_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          sensor_range:
            alarm_type: threshold
            channel: T11
            check: outside_range
            range: [1.0]
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="range"):
        load_alarm_config(p)


def test_outside_range_nonnumeric_element_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          sensor_range:
            alarm_type: threshold
            channel: T11
            check: outside_range
            range: [1.0, high]
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="range"):
        load_alarm_config(p)


def test_deviation_from_setpoint_missing_setpoint_source_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          drift:
            alarm_type: threshold
            channel: T12
            check: deviation_from_setpoint
            threshold: 0.5
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="setpoint_source"):
        load_alarm_config(p)


# ---------------------------------------------------------------------------
# well-formed configs of each type still load
# ---------------------------------------------------------------------------


def test_wellformed_above_loads(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          over_power:
            alarm_type: threshold
            channel: smua_power
            check: above
            threshold: 4.0
            level: CRITICAL
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "over_power" for a in alarms)


def test_wellformed_outside_range_loads(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          sensor_range:
            alarm_type: threshold
            channel: T11
            check: outside_range
            range: [1.0, 350.0]
            level: CRITICAL
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "sensor_range" for a in alarms)


def test_wellformed_deviation_loads(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        engine:
          setpoints:
            T12_setpoint:
              source: experiment_metadata
              default: 4.2
        global_alarms:
          drift:
            alarm_type: threshold
            channel: T12
            check: deviation_from_setpoint
            setpoint_source: T12_setpoint
            threshold: 0.5
            level: WARNING
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "drift" for a in alarms)


def test_fault_count_in_window_needs_no_threshold(tmp_path: Path) -> None:
    """fault_count_in_window does not read cfg['threshold'] — must not be rejected."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          fault_burst:
            alarm_type: threshold
            channel: T11
            check: fault_count_in_window
            range: [0.0, 350.0]
            window_s: 300
            min_fault_count: 1
            level: WARNING
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "fault_burst" for a in alarms)


# ---------------------------------------------------------------------------
# engine numeric range checks
# ---------------------------------------------------------------------------


def test_negative_poll_interval_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        engine:
          poll_interval_s: -1.0
        global_alarms: {}
        """,
    )
    with pytest.raises(AlarmConfigError, match="poll_interval_s"):
        load_alarm_config(p)


def test_zero_rate_window_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        engine:
          rate_window_s: 0
        global_alarms: {}
        """,
    )
    with pytest.raises(AlarmConfigError, match="rate_window_s"):
        load_alarm_config(p)


def test_zero_rate_min_points_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        engine:
          rate_min_points: 0
        global_alarms: {}
        """,
    )
    with pytest.raises(AlarmConfigError, match="rate_min_points"):
        load_alarm_config(p)


def test_nonfinite_setpoint_default_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        engine:
          setpoints:
            bad:
              source: constant
              default: .nan
        global_alarms: {}
        """,
    )
    with pytest.raises(AlarmConfigError, match="default"):
        load_alarm_config(p)


# ---------------------------------------------------------------------------
# amend — rate alarm validation
# Mirrors alarm_v2._eval_rate L362-365: cfg["threshold"] for rate_above/rate_below
# ---------------------------------------------------------------------------


def test_rate_alarm_rate_above_missing_threshold_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          excessive_cooling:
            alarm_type: rate
            channels: [T11, T12]
            check: rate_above
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="threshold"):
        load_alarm_config(p)


def test_rate_alarm_rate_below_missing_threshold_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          cooling_stall:
            alarm_type: rate
            channel: T11
            check: rate_below
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="threshold"):
        load_alarm_config(p)


def test_rate_alarm_rate_near_zero_no_threshold_needed(tmp_path: Path) -> None:
    """rate_near_zero uses .get('rate_threshold', 0.1) — must NOT be rejected."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          stable_temp:
            alarm_type: rate
            channel: T11
            check: rate_near_zero
            level: INFO
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "stable_temp" for a in alarms)


def test_rate_alarm_wellformed_loads(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          excessive_cooling:
            alarm_type: rate
            channels: [T11, T12]
            check: rate_above
            threshold: 5.0
            level: WARNING
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "excessive_cooling" for a in alarms)


# ---------------------------------------------------------------------------
# amend — additional_condition validation
# Mirrors alarm_v2._eval_rate L376-378: calls _eval_condition(add_cond)
# which hard-reads cond["threshold"] for above/below/rate_above/rate_below/etc.
# ---------------------------------------------------------------------------


def test_rate_alarm_additional_condition_missing_threshold_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          steady_state_check:
            alarm_type: rate
            channel: T11
            check: rate_near_zero
            additional_condition:
              channel: T12
              check: above
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="threshold"):
        load_alarm_config(p)


def test_rate_alarm_additional_condition_wellformed_loads(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          steady_state_check:
            alarm_type: rate
            channel: T11
            check: rate_near_zero
            additional_condition:
              channel: T12
              check: above
              threshold: 10.0
            level: WARNING
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "steady_state_check" for a in alarms)


# ---------------------------------------------------------------------------
# amend — composite sub-condition validation
# Mirrors alarm_v2._eval_condition L284-330: hard-reads cond["threshold"] for
# any_below (L286), any_above (L293), above (L305/307), below (L314),
# rate_above (L322), rate_below (L330).
# ---------------------------------------------------------------------------


def test_composite_sub_condition_any_below_missing_threshold_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            conditions:
              - channels: [T11, T12]
                check: any_below
              - channel: P1
                check: above
                threshold: 1.0e-3
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="threshold"):
        load_alarm_config(p)


def test_composite_sub_condition_above_missing_threshold_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          pressure_check:
            alarm_type: composite
            operator: AND
            conditions:
              - channel: P1
                check: above
              - channel: T11
                check: below
                threshold: 200.0
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="threshold"):
        load_alarm_config(p)


def test_composite_sub_condition_rate_above_missing_threshold_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          pressure_rising:
            alarm_type: composite
            operator: AND
            conditions:
              - channel: P1
                check: rate_above
              - channel: T11
                check: below
                threshold: 200.0
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="threshold"):
        load_alarm_config(p)


def test_composite_sub_condition_rate_near_zero_no_threshold_needed(tmp_path: Path) -> None:
    """rate_near_zero uses .get('rate_threshold', 0.1) — must NOT be rejected."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          plateau_check:
            alarm_type: composite
            operator: AND
            conditions:
              - channel: T11
                check: rate_near_zero
              - channel: T11
                check: below
                threshold: 10.0
            level: INFO
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "plateau_check" for a in alarms)


def test_composite_wellformed_loads(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            conditions:
              - channels: [T11, T12]
                check: any_below
                threshold: 200
              - channel: P1
                check: above
                threshold: 1.0e-3
            level: CRITICAL
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "vac_cold" for a in alarms)


def test_shipped_alarms_v3_still_loads() -> None:
    """The shipped config/alarms_v3.yaml must continue to load cleanly."""
    _, alarms = load_alarm_config(None)
    assert len(alarms) > 0


# ---------------------------------------------------------------------------
# fail-OPEN gap: unrecognised alarm_type / check / channel_group used to load
# cleanly and then silently never fire at runtime (alarm_v2's own dispatch
# `else` branches only log a warning and return None/False — see
# alarm_v2.py:198-200, 283-285, 386-388). These pin the fix: unrecognised
# values must now raise AlarmConfigError at LOAD time instead.
# ---------------------------------------------------------------------------


def test_unknown_alarm_type_typo_raises(tmp_path: Path) -> None:
    """Reported defect: alarm_type: composit (typo for composite) on a
    vacuum_loss_cold-style alarm used to load with no error and never fire."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vacuum_loss_cold:
            alarm_type: composit
            operator: AND
            conditions:
              - channels: [T11, T12]
                check: any_below
                threshold: 200
              - channel: P1
                check: above
                threshold: 1.0e-3
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="alarm_type"):
        load_alarm_config(p)


def test_unknown_threshold_check_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          over_power:
            alarm_type: threshold
            channel: smua_power
            check: abov
            threshold: 4.0
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="check"):
        load_alarm_config(p)


def test_unknown_rate_check_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          excessive_cooling:
            alarm_type: rate
            channels: [T11, T12]
            check: rate_abov
            threshold: -5.0
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="check"):
        load_alarm_config(p)


def test_unknown_composite_sub_condition_check_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            conditions:
              - channels: [T11, T12]
                check: any_belw
                threshold: 200
              - channel: P1
                check: above
                threshold: 1.0e-3
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="check"):
        load_alarm_config(p)


def test_unknown_channel_group_raises(tmp_path: Path) -> None:
    """A channel_group typo used to be silently dropped (no 'channels' key
    ever set), leaving alarm_v2._resolve_channels() an empty list at
    runtime — the alarm silently never fired for any channel."""
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          uncalibrated: [T1, T2]
        global_alarms:
          sensor_fault:
            alarm_type: threshold
            channel_group: uncalibrted
            check: outside_range
            range: [0.0, 350.0]
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel_group"):
        load_alarm_config(p)


def test_unknown_channel_group_in_composite_condition_raises(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          calibrated: [T11, T12]
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            conditions:
              - channel_group: calibrted
                check: any_below
                threshold: 200
              - channel: P1
                check: above
                threshold: 1.0e-3
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel_group"):
        load_alarm_config(p)


# ---------------------------------------------------------------------------
# known-good values of the newly-validated fields must be unaffected
# ---------------------------------------------------------------------------


def test_known_good_alarm_type_stale_unaffected(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          data_loss_temperature:
            alarm_type: stale
            channel: T11
            timeout_s: 120
            level: CRITICAL
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "data_loss_temperature" for a in alarms)


def test_known_good_rate_check_relative_rate_near_zero_unaffected(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vacuum_stall:
            alarm_type: rate
            channel: P1
            check: relative_rate_near_zero
            rate_threshold: 0.01
            level: INFO
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "vacuum_stall" for a in alarms)


def test_known_good_channel_group_unaffected(tmp_path: Path) -> None:
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          uncalibrated: [T1, T2]
        global_alarms:
          sensor_fault:
            alarm_type: threshold
            channel_group: uncalibrated
            check: outside_range
            range: [0.0, 350.0]
            level: WARNING
        """,
    )
    _, alarms = load_alarm_config(p)
    found = next(a for a in alarms if a.alarm_id == "sensor_fault")
    assert found.config["channels"] == ["T1", "T2"]


def test_shipped_physical_alarms_and_interlocks_not_parsed_by_this_loader() -> None:
    """physical_alarms.yaml and interlocks.yaml are consumed by other modules
    (CooldownAlarm/VacuumGuard, the interlock engine), not by
    load_alarm_config — so this loader's stricter validation cannot newly
    reject anything in them. Documented here so that assumption stays
    pinned; it is NOT a claim that this loader validates those files."""
    import inspect

    from cryodaq.core import alarm_config

    source = inspect.getsource(alarm_config)
    assert "physical_alarms" not in source
    assert "interlocks.yaml" not in source
