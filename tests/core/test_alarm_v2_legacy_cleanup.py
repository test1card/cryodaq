"""Phase G: verify T11/T12 absolute-threshold alarms removed from alarms_v3.yaml."""
from __future__ import annotations

from pathlib import Path

from cryodaq.core.alarm_config import load_alarm_config

_RETAINED_ALARM_IDS = {
    # calibrated_sensor_fault: sensor hardware failure detection (< 1K or > 350K).
    # NOT replaced by F-X v3 — CooldownAlarm/VacuumGuard evaluate physical state,
    # not sensor validity.
    "calibrated_sensor_fault",
}

# Absolute-value threshold checks that must NOT appear on Т11/Т12 in measurement phase.
# Rate checks (rate_above, rate_below, relative_rate_near_zero, …) are explicitly allowed.
_ABSOLUTE_THRESHOLD_CHECKS = frozenset({
    "above", "below", "outside_range", "any_above", "any_below",
    "deviation_from_setpoint",
})

_CALIBRATED_CHANNELS = frozenset({"Т11", "Т12"})


def test_measurement_thresholds_removed_from_t11_t12():
    """Measurement-specific absolute-threshold rules for Т11/Т12 must be removed.

    Retained: calibrated_sensor_fault (hardware fault detection — impossible raw values).
    Removed: detector_drift, detector_unstable, cooldown_stall (replaced by F-X v3).
    Rate alarms (check: rate_*) are NOT absolute thresholds — they are permitted.

    Uses load_alarm_config() so that any future renamed alarm that targets Т11/Т12
    with an absolute threshold check is also caught — not just hard-coded alarm IDs.
    """
    path = Path(__file__).parents[2] / "config" / "alarms_v3.yaml"
    _, alarms = load_alarm_config(path)

    violations: list[str] = []

    for alarm in alarms:
        # Only care about measurement-phase alarms
        if alarm.phase_filter != ["measurement"]:
            continue
        # calibrated_sensor_fault is explicitly retained — skip
        if alarm.alarm_id in _RETAINED_ALARM_IDS:
            continue

        cfg = alarm.config
        check = cfg.get("check", "")
        if check not in _ABSOLUTE_THRESHOLD_CHECKS:
            continue

        # Collect channels referenced by this alarm rule
        channels: list[str] = []
        if "channel" in cfg:
            channels.append(cfg["channel"])
        if "channels" in cfg:
            channels.extend(cfg["channels"])

        # Flag if any calibrated channel (Т11/Т12) is targeted
        offending = _CALIBRATED_CHANNELS.intersection(channels)
        if offending:
            violations.append(
                f"alarm '{alarm.alarm_id}' (phase=measurement, check={check!r}) "
                f"targets calibrated channels {sorted(offending)} — "
                "should have been removed by F-X v3"
            )

    assert not violations, (
        "alarms_v3.yaml contains absolute-threshold rules on Т11/Т12 "
        "that should have been deleted by F-X v3:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_calibrated_sensor_fault_retained():
    """calibrated_sensor_fault must remain with correct semantics — hardware fault detection.

    Asserts rule semantics: global scope (no phase_filter), check=outside_range,
    channels=[Т11, Т12], range=[1.0, 350.0] K, level=CRITICAL.
    """
    path = Path(__file__).parents[2] / "config" / "alarms_v3.yaml"
    _, alarms = load_alarm_config(path)

    matching = [a for a in alarms if a.alarm_id == "calibrated_sensor_fault"]
    assert matching, (
        "calibrated_sensor_fault must be retained in alarms_v3.yaml — "
        "it detects hardware sensor failure (values < 1K or > 350K), "
        "which CooldownAlarm/VacuumGuard do not cover."
    )

    rule = matching[0]
    cfg = rule.config

    # Must be global (no phase restriction)
    assert rule.phase_filter is None, (
        f"calibrated_sensor_fault must be global (phase_filter=None), got {rule.phase_filter}"
    )

    # Must use threshold alarm type with outside_range check
    assert cfg.get("alarm_type") == "threshold", (
        f"expected alarm_type='threshold', got {cfg.get('alarm_type')!r}"
    )
    assert cfg.get("check") == "outside_range", (
        f"expected check='outside_range', got {cfg.get('check')!r}"
    )

    # Must target exactly the calibrated channels Т11 and Т12
    channels = set(cfg.get("channels", []))
    assert channels == {"Т11", "Т12"}, (
        f"expected channels={{Т11, Т12}}, got {channels}"
    )

    # Range must cover [1.0, 350.0] K — values outside indicate sensor hardware failure
    range_val = cfg.get("range")
    assert isinstance(range_val, list) and len(range_val) == 2, (
        f"expected range=[lo, hi], got {range_val!r}"
    )
    lo, hi = range_val
    assert lo == 1.0, f"expected range lower bound 1.0 K (DT-670 calibration floor), got {lo}"
    assert hi == 350.0, f"expected range upper bound 350.0 K, got {hi}"

    # Must be CRITICAL severity
    assert cfg.get("level") == "CRITICAL", (
        f"expected level='CRITICAL', got {cfg.get('level')!r}"
    )
