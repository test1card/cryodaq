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


def test_deviation_from_setpoint_unknown_setpoint_source_raises(tmp_path: Path) -> None:
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
            setpoint_source: T12_setpoint_typo
            threshold: 0.5
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError) as exc_info:
        load_alarm_config(p)
    assert str(exc_info.value) == (
        "alarm 'drift' (check=deviation_from_setpoint) has undefined setpoint_source 'T12_setpoint_typo'"
    )


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


# ---------------------------------------------------------------------------
# fail-OPEN gap: composite `operator`. alarm_v2._eval_composite (L291-305)
# dispatches on a CASE-SENSITIVE `operator == "AND"` / `== "OR"` and its `else`
# branch only logs a warning and returns None — a CRITICAL annunciator that
# loaded cleanly then silently never fires forever (dead, looks healthy).
# Absent operator is legitimate: runtime defaults to "AND" (L292).
# ---------------------------------------------------------------------------
def test_composite_unknown_operator_raises(tmp_path: Path) -> None:
    """Reported defect: operator: ADN (typo) loads, both conditions true,
    evaluator returns None forever — a dead CRITICAL annunciator."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: ADN
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
    with pytest.raises(AlarmConfigError, match="operator"):
        load_alarm_config(p)


def test_composite_wrong_case_operator_raises(tmp_path: Path) -> None:
    """Runtime comparison is case-sensitive: operator: and / And are also
    dead at runtime (fall into the `else` branch). Must be rejected at load,
    not normalised — normalising would change runtime behaviour."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: and
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
    with pytest.raises(AlarmConfigError, match="operator"):
        load_alarm_config(p)


def test_composite_nonstring_operator_raises(tmp_path: Path) -> None:
    """A non-string operator (e.g. a list) must be rejected with
    AlarmConfigError, not crash the loader with a TypeError."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: [AND]
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
    with pytest.raises(AlarmConfigError, match="operator"):
        load_alarm_config(p)


def test_composite_absent_operator_loads(tmp_path: Path) -> None:
    """An absent operator key is legitimate: alarm_v2._eval_composite L292
    defaults to 'AND'. Must NOT be rejected."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
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


# ---------------------------------------------------------------------------
# fail-OPEN gap: composite `conditions` presence/type. alarm_v2._eval_composite
# (L293-305) does `conditions = cfg.get("conditions", [])` then
# `results = [self._eval_condition(c) for c in conditions]` and runs all()/
# any() on it. Each defect below was VERIFIED by running the evaluator against
# the pre-fix loader — these are observed fail-open shapes, not theoretical.
#
#   1. missing/empty conditions + AND (default op): all([]) is True → the alarm
#      FIRES on vacuous truth forever. Observed: a CRITICAL annunciator firing
#      continuously with channels=[] and no evidence (alarm fatigue + poisons
#      the ack workflow).
#   2. missing/empty conditions + OR: any([]) is False → silently never fires.
#      Same dead-annunciator class as the operator defect.
#   3. non-dict entry, e.g. conditions: ["typo_string"]: _eval_condition does
#      cond.get(...) (alarm_v2.py:331) → AttributeError → swallowed by
#      evaluate()'s broad `except Exception` → returns None → silently dead.
#      The loader currently SKIPS non-dict entries (`if isinstance(cond, dict)`);
#      skipping a malformed entry is exactly the fail-open shape being closed.
#   4. non-list `conditions` (e.g. a dict or a string) is the same hole — the
#      runtime would either mis-iterate or AttributeError — and must not load.
# ---------------------------------------------------------------------------
def test_composite_missing_conditions_raises(tmp_path: Path) -> None:
    """Reported defect #1 (AND form): no `conditions` key → cfg.get(..., [])
    yields [] → all([]) is True → a CRITICAL alarm fires on vacuous truth
    forever. Observed event: AlarmEvent(alarm_id='a1', level='CRITICAL',
    channels=[], ...)."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="conditions"):
        load_alarm_config(p)


def test_composite_empty_conditions_list_raises(tmp_path: Path) -> None:
    """Reported defect #2 (OR form, same shape for AND): an explicitly empty
    conditions list. OR → any([]) is False → silently never fires; AND →
    all([]) is True → fires forever. Either way it is a dead/misfiring
    annunciator that loaded cleanly."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: OR
            conditions: []
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="conditions"):
        load_alarm_config(p)


def test_composite_non_dict_condition_entry_raises(tmp_path: Path) -> None:
    """Reported defect #3: conditions: ["typo_string"] — _eval_condition does
    cond.get(...) (alarm_v2.py:331) → AttributeError('str' object has no
    attribute 'get') → swallowed by evaluate()'s broad except → returns None
    → silently dead. The loader currently SKIPS non-dict entries; skipping a
    malformed entry is the fail-open shape being eliminated. Must name the
    index and the offending value so an operator can find the fault."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            conditions:
              - "typo_string"
              - channel: P1
                check: above
                threshold: 1.0e-3
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="conditions"):
        load_alarm_config(p)


def test_composite_non_list_conditions_raises(tmp_path: Path) -> None:
    """A non-list `conditions` (e.g. a dict or a string) must not be silently
    accepted: the runtime would mis-iterate or AttributeError. Same fail-open
    hole as missing/empty, one level up — reject it at load with the field
    name and the offending value."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            conditions: not_a_list
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="conditions"):
        load_alarm_config(p)


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


# ---------------------------------------------------------------------------
# fail-OPEN gap (round 3): four more shapes found by a reviewer after the
# operator (f07314e6) and conditions-container (a6b6db88) fixes. Each was
# VERIFIED by running the evaluator against the pre-fix loader — these load
# cleanly today and then silently never fire (or silently vanish) at runtime.
#
#   1. non-dict alarm entry silently DROPPED (_expand_alarm returned None).
#   2. composite sub-condition with no channel selector: _eval_condition's
#      `if not ch: return False` (alarm_v2.py:345) → dead forever.
#   3. top-level threshold/rate alarm with no channel selector:
#      _resolve_channels returns [] → the for-loop body never runs → None.
#   4. truthy non-dict additional_condition: _eval_condition hard-reads
#      cond.get(...) (alarm_v2.py:331) → AttributeError → swallowed by
#      evaluate()'s broad `except Exception` → None → dead.
# ---------------------------------------------------------------------------
def test_non_dict_alarm_entry_raises(tmp_path: Path) -> None:
    """Defect #1: a non-dict alarm entry (e.g. global_alarms: {bad: "typo"})
    was silently DROPPED — _expand_alarm returned None and the caller discarded
    it, so the alarm went MISSING from the loaded set with no error and no log.
    An operator who wrote it believes it is configured. Skipping a malformed
    entry is the fail-open shape this series eliminates; must raise, naming the
    alarm id and the offending value."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          typo_alarm: "just_a_string"
        """,
    )
    with pytest.raises(AlarmConfigError, match="typo_alarm"):
        load_alarm_config(p)


def test_composite_sub_condition_missing_channel_selector_raises(tmp_path: Path) -> None:
    """Defect #2: a composite sub-condition with check: above and a threshold
    but NO channel. alarm_v2._eval_condition (L343-352) reads cond.get('channel')
    DIRECTLY — not _resolve_channels — so 'channels'/'channel_group' would not
    satisfy it either; absent channel → `if not ch: return False` (L345) →
    silently dead forever. A CRITICAL annunciator that looks configured."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            conditions:
              - check: above
                threshold: 1.0
              - channel: P1
                check: above
                threshold: 1.0e-3
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel"):
        load_alarm_config(p)


def test_composite_sub_condition_any_below_missing_channel_selector_raises(tmp_path: Path) -> None:
    """Defect #2 (any_* family): a composite sub-condition with check:
    any_below and a threshold but NO channel/channels/channel_group.
    alarm_v2._eval_condition (L333-336) calls _resolve_channels(cond) which
    returns [] without a selector → any() over [] is False → silently dead.
    The any_* family accepts channel/channels/channel_group (multi-channel
    selector via _resolve_channels), unlike the single-channel family above."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            conditions:
              - check: any_below
                threshold: 200
              - channel: P1
                check: above
                threshold: 1.0e-3
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel"):
        load_alarm_config(p)


def test_threshold_alarm_missing_channel_selector_raises(tmp_path: Path) -> None:
    """Defect #3 (threshold): a top-level threshold alarm with no channel/
    channels/channel_group. alarm_v2._eval_threshold (L218) calls
    _resolve_channels(cfg) which returns [] when none is present → the for-loop
    (L223) never executes → returns None forever — silently dead."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          orphan_threshold:
            alarm_type: threshold
            check: above
            threshold: 4.0
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel"):
        load_alarm_config(p)


def test_rate_alarm_missing_channel_selector_raises(tmp_path: Path) -> None:
    """Defect #3 (rate): same fail-open shape on the rate path.
    alarm_v2._eval_rate (L395) calls _resolve_channels(cfg) → [] → the for-loop
    (L401) never executes → returns None forever."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          orphan_rate:
            alarm_type: rate
            check: rate_above
            threshold: 5.0
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel"):
        load_alarm_config(p)


def test_rate_additional_condition_non_dict_raises(tmp_path: Path) -> None:
    """Defect #4: a truthy non-dict additional_condition (e.g. a string).
    alarm_v2._eval_rate (L421-422) does `if add_cond and not
    self._eval_condition(add_cond)` — a truthy non-dict is passed to
    _eval_condition which hard-reads cond.get(...) (L331) → AttributeError →
    swallowed by evaluate()'s broad `except Exception` (L201-203) → returns
    None → silently dead. The loader previously validated additional_condition
    only inside `if isinstance(add_cond, dict)`, so a truthy non-dict slipped
    through."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          steady_state_check:
            alarm_type: rate
            channel: T11
            check: rate_near_zero
            additional_condition: "typo_string"
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="additional_condition"):
        load_alarm_config(p)


# ---------------------------------------------------------------------------
# selector-rule precision guards: the channel-selector rule derived from
# alarm_v2 must accept every legitimate selector shape the runtime honours,
# not just the common case. These pin the accepted shapes so a later
# tightening cannot brick a valid lab config.
# ---------------------------------------------------------------------------
def test_composite_sub_condition_phase_elapsed_s_channel_loads(tmp_path: Path) -> None:
    """channel: phase_elapsed_s is a legitimate selector for check: above —
    alarm_v2._eval_condition (L348-350) special-cases the phase-elapsed
    pseudo-channel. The single-channel selector rule must accept it (it is a
    non-empty string), not reject it. Pins the shipped vacuum_insufficient
    alarm shape."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          phase_too_long:
            alarm_type: composite
            operator: AND
            conditions:
              - channel: phase_elapsed_s
                check: above
                threshold: 3600
              - channel: P1
                check: above
                threshold: 1.0e-4
            level: WARNING
        """,
    )
    _, alarms = load_alarm_config(p)
    assert any(a.alarm_id == "phase_too_long" for a in alarms)


# ---------------------------------------------------------------------------
# fail-OPEN gap (round 4): four more shapes a reviewer reproduced after the
# selector-family split (f07314e6 / a6b6db88 / 2a16488b). Each loads cleanly
# today and is then dead — or gone — at runtime.
#
#   1. alarm_type: stale skipped selector validation entirely, yet
#      _eval_stale (alarm_v2.py:442) calls _resolve_channels(cfg) exactly like
#      _eval_threshold/_eval_rate do, and its for-loop (L447) never runs on [].
#      Exempting stale from the selector rule was an oversight: "no hard reads"
#      justifies exempting it from the THRESHOLD rule, not from the SELECTOR
#      rule.
#   2. the selector rule tested KEY PRESENCE ONLY. Presence is not a selector:
#      `channels: []`, `channels: null`, `channel: null` and a channel_group
#      whose member list is empty all satisfy `key in cfg` and still resolve to
#      [] (or crash) inside _resolve_channels (alarm_v2.py:468-476). A
#      top-level `channel: phase_elapsed_s` is the same shape — L474 refuses to
#      resolve the pseudo-channel, so it too yields [].
#   3. channel_group was expanded in cfg and in composite conditions[i] but NOT
#      in a rate alarm's additional_condition, so a legitimate any_above group
#      sub-condition kept its channel_group key — which _resolve_channels never
#      reads — and resolved to [] at runtime.
#   4. a non-dict PHASE CONTAINER (phase_alarms: {cooldown: "typo"}) was
#      silently `continue`d, dropping EVERY alarm of that phase. Same fail-open
#      shape 2a16488b closed one level down for a non-dict alarm entry.
# ---------------------------------------------------------------------------
def test_stale_alarm_missing_channel_selector_raises(tmp_path: Path) -> None:
    """Defect #1: alarm_type: stale with no channel/channels/channel_group.
    _validate_required_keys exempted stale entirely ("no hard reads"), but
    alarm_v2._eval_stale (L442) calls _resolve_channels(cfg) — which returns []
    without a selector (L476) — and its per-channel for-loop (L447) then never
    executes, so the alarm returns None forever. A CRITICAL data-loss
    annunciator that loaded cleanly and can never fire."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          data_loss:
            alarm_type: stale
            timeout_s: 120
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel"):
        load_alarm_config(p)


def test_stale_alarm_with_channel_group_loads(tmp_path: Path) -> None:
    """Guard for defect #1: the shipped data_loss_temperature shape (stale +
    channel_group) must keep loading — channel_group is rewritten to `channels`
    at load, so _resolve_channels honours it."""
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          all_temp: [T11, T12]
        global_alarms:
          data_loss_temperature:
            alarm_type: stale
            channel_group: all_temp
            timeout_s: 120
            level: CRITICAL
        """,
    )
    _, alarms = load_alarm_config(p)
    found = next(a for a in alarms if a.alarm_id == "data_loss_temperature")
    assert found.config["channels"] == ["T11", "T12"]


def test_threshold_empty_channels_list_raises(tmp_path: Path) -> None:
    """Defect #2: `channels: []` satisfies `'channels' in cfg` but
    alarm_v2._resolve_channels returns list([]) == [] (L470-471), so
    _eval_threshold's for-loop (L223) never runs → dead forever. Presence is
    not a selector; it must resolve to at least one channel."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          empty_selector:
            alarm_type: threshold
            channels: []
            check: above
            threshold: 4.0
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="channels"):
        load_alarm_config(p)


def test_threshold_null_channel_raises(tmp_path: Path) -> None:
    """Defect #2 (`channel: null` form): the key is present, so the old
    presence-only rule passed it. At runtime alarm_v2._resolve_channels
    (L472-475) returns [None], _state.get(None) never matches any tracked
    channel, and the alarm is dead forever."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          null_selector:
            alarm_type: threshold
            channel: null
            check: above
            threshold: 4.0
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel"):
        load_alarm_config(p)


def test_rate_null_channels_raises(tmp_path: Path) -> None:
    """Defect #2 (`channels: null` form): _resolve_channels does
    list(cfg["channels"]) (L471) → TypeError on None → swallowed by
    evaluate()'s broad `except Exception` (alarm_v2.py:201-203) → returns None
    → silently dead."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          null_list_selector:
            alarm_type: rate
            channels: null
            check: rate_above
            threshold: 5.0
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="channels"):
        load_alarm_config(p)


def test_threshold_channel_group_with_empty_member_list_raises(tmp_path: Path) -> None:
    """Defect #2 (channel_group form): a KNOWN group whose member list is empty
    expands to `channels: []` — the same [] resolution as an empty literal
    selector, just one indirection away. Reject it where the resolution
    actually happens."""
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          retired: []
        global_alarms:
          group_selector:
            alarm_type: threshold
            channel_group: retired
            check: outside_range
            range: [0.0, 350.0]
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel_group"):
        load_alarm_config(p)


def test_threshold_top_level_phase_elapsed_s_channel_raises(tmp_path: Path) -> None:
    """Defect #2 (pseudo-channel form): alarm_v2._resolve_channels explicitly
    refuses to resolve `phase_elapsed_s` (L474: `if ch != "phase_elapsed_s"`),
    so a TOP-LEVEL threshold/rate/stale alarm selecting it resolves to [] and
    is dead. It is legitimate only inside a sub-condition, where
    _eval_condition reads cond.get("channel") directly and re-routes it to the
    phase provider (L348-350) — that shape stays accepted (see
    test_composite_sub_condition_phase_elapsed_s_channel_loads)."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          phase_too_long:
            alarm_type: threshold
            channel: phase_elapsed_s
            check: above
            threshold: 3600
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="phase_elapsed_s"):
        load_alarm_config(p)


def test_composite_sub_condition_empty_channels_list_raises(tmp_path: Path) -> None:
    """Defect #2 on the sub-condition path: the any_* family resolves its
    selector through _resolve_channels(cond) (alarm_v2.py:334/339), so an empty
    `channels` makes any() over [] False forever — the same dead sub-condition
    the presence-only rule was meant to stop."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            conditions:
              - channels: []
                check: any_below
                threshold: 200
              - channel: P1
                check: above
                threshold: 1.0e-3
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="channels"):
        load_alarm_config(p)


def test_rate_additional_condition_channel_group_is_expanded(tmp_path: Path) -> None:
    """Defect #3: channel_group is expanded in cfg and in composite
    conditions[i] but NOT in a rate alarm's additional_condition, even though
    both are the same sub-condition shape consumed by the same
    _eval_condition. alarm_v2._resolve_channels never reads `channel_group`
    (L468-476) — the loader is the only thing that gives that key meaning — so
    the sub-condition resolved to [] and any() over [] gated the rate alarm
    off forever. Resolution chosen: EXPAND (see _expand_alarm)."""
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          calibrated: [T11, T12]
        global_alarms:
          vacuum_stall:
            alarm_type: rate
            channel: P1
            check: relative_rate_near_zero
            rate_threshold: 0.01
            additional_condition:
              channel_group: calibrated
              check: any_above
              threshold: 200
            level: INFO
        """,
    )
    _, alarms = load_alarm_config(p)
    found = next(a for a in alarms if a.alarm_id == "vacuum_stall")
    add_cond = found.config["additional_condition"]
    assert add_cond.get("channels") == ["T11", "T12"], (
        f"additional_condition was left as {add_cond!r}: alarm_v2._resolve_channels "
        f"never reads 'channel_group' (alarm_v2.py:468-476), so it resolves to [] "
        f"and any() over [] is False → the rate alarm can never fire"
    )
    assert "channel_group" not in add_cond


def test_rate_additional_condition_unknown_channel_group_raises(tmp_path: Path) -> None:
    """Consequence of expanding defect #3: a channel_group TYPO inside
    additional_condition must now fail closed exactly as it already does in cfg
    and in composite conditions[i], instead of resolving to [] at runtime."""
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          calibrated: [T11, T12]
        global_alarms:
          vacuum_stall:
            alarm_type: rate
            channel: P1
            check: relative_rate_near_zero
            additional_condition:
              channel_group: calibrted
              check: any_above
              threshold: 200
            level: INFO
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel_group"):
        load_alarm_config(p)


def test_non_dict_phase_container_raises(tmp_path: Path) -> None:
    """Defect #4: a non-dict phase container (phase_alarms: {cooldown: "typo"})
    was silently `continue`d by the loader, so EVERY alarm of that phase went
    missing with no error and no log — the fail-open shape 2a16488b closed one
    level down for a non-dict alarm ENTRY. Must raise, naming the phase and the
    offending value."""
    p = _write_yaml(
        tmp_path,
        """
        phase_alarms:
          cooldown: "typo"
        """,
    )
    with pytest.raises(AlarmConfigError, match="cooldown"):
        load_alarm_config(p)


def test_wellformed_phase_container_still_loads(tmp_path: Path) -> None:
    """Guard for defect #4: a well-formed phase container keeps loading and
    keeps its phase_filter."""
    p = _write_yaml(
        tmp_path,
        """
        phase_alarms:
          cooldown:
            excessive_cooling_rate:
              alarm_type: rate
              channels: [T11, T12]
              check: rate_below
              threshold: -5.0
              level: WARNING
        """,
    )
    _, alarms = load_alarm_config(p)
    found = next(a for a in alarms if a.alarm_id == "excessive_cooling_rate")
    assert found.phase_filter == ["cooldown"]


# ---------------------------------------------------------------------------
# fail-OPEN gap (round 5), reproduced by an external reviewer:
#
#   P1. `phase_elapsed_s` was accepted as the `channel` selector for EVERY
#       member of the single-channel sub-condition family (above / below /
#       rate_above / rate_below / rate_near_zero), but alarm_v2._eval_condition
#       special-cases the pseudo-channel in exactly ONE branch — `above`
#       (alarm_v2.py:348-350), which routes it to PhaseProvider. The other four
#       branches query ordinary channel data the pseudo-channel has none of:
#         below (L358)  → self._state.get("phase_elapsed_s") → None → False
#         rate_* (L366/374/382) → self._rate.get_rate_custom_window(...) → None
#                                 → False
#       A composite alarm containing `channel: phase_elapsed_s, check: below,
#       threshold: 3600` therefore loaded cleanly and then held its AND-gate
#       shut forever, suppressing the ENCLOSING alarm — a dead annunciator that
#       looks configured. (The top-level form is a different code path and was
#       already refused; see
#       test_threshold_top_level_phase_elapsed_s_channel_raises.)
#
#   P2. A condition supplying BOTH an explicit channel selector
#       (`channels` / `channel`) AND a `channel_group` had the explicit one
#       SILENTLY OVERWRITTEN by _expand_channel_group (`cfg["channels"] =
#       list(members)`). An alarm whose YAML reads `channels: [T1]` then
#       evaluates the group's members instead — the config says one thing and
#       the runtime monitors another, with no error and no log.
# ---------------------------------------------------------------------------


def test_composite_sub_condition_phase_elapsed_s_below_raises(tmp_path: Path) -> None:
    """P1, the shape the reviewer reproduced: check=below on the pseudo-channel.

    alarm_v2._eval_condition's `below` branch (L354-359) does
    `self._state.get("phase_elapsed_s")`; ChannelStateTracker is keyed by
    published Reading channel names and never holds that key, so the
    sub-condition is False even when the phase provider reports 10 s — and an
    AND-composite gated on it can never fire.
    """
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          phase_short_enough:
            alarm_type: composite
            operator: AND
            conditions:
              - channel: phase_elapsed_s
                check: below
                threshold: 3600
              - channel: P1
                check: above
                threshold: 1.0e-4
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="phase_elapsed_s"):
        load_alarm_config(p)


@pytest.mark.parametrize("check", ["rate_above", "rate_below", "rate_near_zero"])
def test_composite_sub_condition_phase_elapsed_s_rate_checks_raise(tmp_path: Path, check: str) -> None:
    """P1, rate family: the same gap admits all three rate checks.

    alarm_v2._eval_condition's rate branches (L361-384) call
    `self._rate.get_rate_custom_window("phase_elapsed_s", window)`. No sample is
    ever pushed for the pseudo-channel, so the estimator returns None and every
    one of these returns False forever.
    """
    p = _write_yaml(
        tmp_path,
        f"""
        global_alarms:
          phase_rate:
            alarm_type: composite
            operator: AND
            conditions:
              - channel: phase_elapsed_s
                check: {check}
                threshold: 1.0
              - channel: P1
                check: above
                threshold: 1.0e-4
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="phase_elapsed_s"):
        load_alarm_config(p)


def test_rate_additional_condition_phase_elapsed_s_below_raises(tmp_path: Path) -> None:
    """P1 on the additional_condition path — the same sub-condition shape, the
    same _eval_condition consumer, so it must be refused the same way."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vacuum_stall:
            alarm_type: rate
            channel: P1
            check: relative_rate_near_zero
            rate_threshold: 0.01
            additional_condition:
              channel: phase_elapsed_s
              check: below
              threshold: 3600
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="phase_elapsed_s"):
        load_alarm_config(p)


def test_phase_elapsed_s_rejection_names_alarm_context_check_and_value(tmp_path: Path) -> None:
    """The rejection must be actionable without reading source: it names the
    alarm id, the sub-condition context, the check and the offending value."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          phase_short_enough:
            alarm_type: composite
            operator: AND
            conditions:
              - channel: P1
                check: above
                threshold: 1.0e-4
              - channel: phase_elapsed_s
                check: below
                threshold: 3600
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError) as excinfo:
        load_alarm_config(p)
    msg = str(excinfo.value)
    assert "phase_short_enough" in msg
    assert "conditions[1]" in msg
    assert "below" in msg
    assert "phase_elapsed_s" in msg


def test_rate_additional_condition_phase_elapsed_s_above_still_loads(tmp_path: Path) -> None:
    """Keep-good guard for P1: `above` is the ONE check alarm_v2 re-routes to
    the phase provider (L348-350), and it must keep loading on the
    additional_condition path too — the P1 rule must not over-reach."""
    p = _write_yaml(
        tmp_path,
        """
        global_alarms:
          vacuum_stall:
            alarm_type: rate
            channel: P1
            check: relative_rate_near_zero
            rate_threshold: 0.01
            additional_condition:
              channel: phase_elapsed_s
              check: above
              threshold: 3600
            level: WARNING
        """,
    )
    _, alarms = load_alarm_config(p)
    found = next(a for a in alarms if a.alarm_id == "vacuum_stall")
    assert found.config["additional_condition"]["channel"] == "phase_elapsed_s"


def test_phase_elapsed_s_below_is_dead_at_runtime(tmp_path: Path) -> None:
    """Evidence for P1, read off the runtime rather than asserted from the spec.

    This exercises alarm_v2 directly (unchanged by this fix) to show WHY the
    loader must refuse the shape: with the phase provider reporting 10 s, an
    `above 3600` sub-condition is correctly False and a `below 3600`
    sub-condition — which SHOULD be True — is ALSO False, because it never
    reaches the phase provider at all.

    Passes both before and after the loader fix; it is a keep-good guard on the
    premise, not a red test.
    """
    from unittest.mock import MagicMock

    from cryodaq.core.alarm_v2 import AlarmEvaluator, PhaseProvider, SetpointProvider
    from cryodaq.core.channel_state import ChannelStateTracker
    from cryodaq.core.rate_estimator import RateEstimator

    phase_provider = MagicMock(spec=PhaseProvider)
    phase_provider.get_current_phase.return_value = "cooldown"
    phase_provider.get_phase_elapsed_s.return_value = 10.0
    ev = AlarmEvaluator(
        ChannelStateTracker(),
        RateEstimator(window_s=120.0, min_points=2),
        phase_provider,
        SetpointProvider({}),
    )

    above = {"channel": "phase_elapsed_s", "check": "above", "threshold": 3600}
    below = {"channel": "phase_elapsed_s", "check": "below", "threshold": 3600}
    assert ev._eval_condition(above) is False, "10 s is not > 3600 s"
    assert ev._eval_condition(below) is False, (
        "10 s IS < 3600 s, so a working `below` would be True; it is False because "
        "alarm_v2._eval_condition L354-359 looks the pseudo-channel up in "
        "ChannelStateTracker instead of the phase provider — the condition is dead"
    )


def test_top_level_channels_and_channel_group_raises(tmp_path: Path) -> None:
    """P2, the shape the reviewer reproduced: an explicit `channels: [T1]` next
    to a `channel_group`. _expand_channel_group did
    `cfg["channels"] = list(members)`, so the alarm silently stopped evaluating
    T1 and started evaluating the group's members instead."""
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          g: [T2]
        global_alarms:
          mixed_selector:
            alarm_type: threshold
            channels: [T1]
            channel_group: g
            check: above
            threshold: 4.0
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel_group"):
        load_alarm_config(p)


def test_top_level_channel_and_channel_group_raises(tmp_path: Path) -> None:
    """P2, scalar form: `channel: T1` + `channel_group: g`. The group becomes
    `channels`, and alarm_v2._resolve_channels prefers `channels` (L470) over
    `channel` (L472) — so the named channel is silently ignored."""
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          g: [T2]
        global_alarms:
          mixed_selector:
            alarm_type: stale
            channel: T1
            channel_group: g
            timeout_s: 120
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel_group"):
        load_alarm_config(p)


def test_composite_sub_condition_channels_and_channel_group_raises(tmp_path: Path) -> None:
    """P2 on the composite sub-condition path — expansion happens there too
    (_expand_alarm conditions loop), so the same silent substitution applies."""
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          g: [T2]
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            conditions:
              - channels: [T1]
                channel_group: g
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


def test_rate_additional_condition_channels_and_channel_group_raises(tmp_path: Path) -> None:
    """P2 on the additional_condition path — the third expansion site. The rule
    must be applied wherever channel_group is expanded, not per-site."""
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          g: [T2]
        global_alarms:
          vacuum_stall:
            alarm_type: rate
            channel: P1
            check: relative_rate_near_zero
            rate_threshold: 0.01
            additional_condition:
              channels: [T1]
              channel_group: g
              check: any_above
              threshold: 200
            level: WARNING
        """,
    )
    with pytest.raises(AlarmConfigError, match="channel_group"):
        load_alarm_config(p)


def test_mixed_selector_rejection_names_alarm_context_and_both_keys(tmp_path: Path) -> None:
    """The rejection must name the alarm, the context and BOTH conflicting
    selector keys, so the operator can see which key to delete."""
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          g: [T2]
        global_alarms:
          vac_cold:
            alarm_type: composite
            operator: AND
            conditions:
              - channel: P1
                check: above
                threshold: 1.0e-3
              - channels: [T1]
                channel_group: g
                check: any_below
                threshold: 200
            level: CRITICAL
        """,
    )
    with pytest.raises(AlarmConfigError) as excinfo:
        load_alarm_config(p)
    msg = str(excinfo.value)
    assert "vac_cold" in msg
    assert "conditions[1]" in msg
    assert "channel_group" in msg
    assert "channels" in msg


def test_single_explicit_channels_selector_still_loads(tmp_path: Path) -> None:
    """Keep-good guard for P2: the rule must fire only on a MIXED selector. An
    explicit `channels` with no channel_group anywhere keeps loading verbatim."""
    p = _write_yaml(
        tmp_path,
        """
        channel_groups:
          g: [T2]
        global_alarms:
          explicit_only:
            alarm_type: threshold
            channels: [T1]
            check: above
            threshold: 4.0
            level: CRITICAL
        """,
    )
    _, alarms = load_alarm_config(p)
    found = next(a for a in alarms if a.alarm_id == "explicit_only")
    assert found.config["channels"] == ["T1"]


def test_shipped_configs_still_load(tmp_path: Path) -> None:
    """Shipped-config safety gate: neither P1 nor P2 may reject a config that
    actually ships. config/alarms_v3.yaml uses `phase_elapsed_s` only with
    check=above (vacuum_insufficient) and never mixes selectors;
    config/physical_alarms.yaml defines no alarms at all."""
    repo_root = Path(__file__).resolve().parents[2]
    _, alarms = load_alarm_config(repo_root / "config" / "alarms_v3.yaml")
    assert len(alarms) == 16
    _, physical = load_alarm_config(repo_root / "config" / "physical_alarms.yaml")
    assert len(physical) == 0
