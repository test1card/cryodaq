"""Phase G: verify T11/T12 absolute-threshold alarms removed from alarms_v3.yaml."""
from __future__ import annotations

from pathlib import Path

import yaml


_RETAINED_ALARM_IDS = {
    # calibrated_sensor_fault: sensor hardware failure detection (< 1K or > 350K).
    # NOT replaced by F-X v3 — CooldownAlarm/VacuumGuard evaluate physical state,
    # not sensor validity.
    "calibrated_sensor_fault",
}


def test_measurement_thresholds_removed_from_t11_t12():
    """Measurement-specific absolute-threshold rules for Т11/Т12 must be removed.

    Retained: calibrated_sensor_fault (hardware fault detection — impossible raw values).
    Removed: detector_drift, detector_unstable, cooldown_stall (replaced by F-X v3).
    Rate alarms (check: rate_*) are NOT absolute thresholds — they are permitted.
    """
    path = Path(__file__).parents[2] / "config" / "alarms_v3.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    removed_alarm_ids = {
        "detector_drift", "detector_unstable", "cooldown_stall",
    }

    violations: list[str] = []

    def _walk(obj: object, path_str: str, alarm_id: str = "") -> None:
        if not isinstance(obj, dict):
            return
        for key, val in obj.items():
            _alarm_id = key if isinstance(val, dict) and val.get("alarm_type") else alarm_id
            if _alarm_id in removed_alarm_ids:
                violations.append(f"{path_str}.{key}: should have been removed by F-X v3")
            _walk(val, f"{path_str}.{key}", _alarm_id)

    _walk(raw, "alarms_v3")
    assert not violations, (
        "alarms_v3.yaml contains alarm rules that should have been deleted by F-X v3:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_calibrated_sensor_fault_retained():
    """calibrated_sensor_fault must remain — hardware fault detection, not replaced by F-X v3."""
    path = Path(__file__).parents[2] / "config" / "alarms_v3.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    found = False

    def _walk(obj: object) -> None:
        nonlocal found
        if not isinstance(obj, dict):
            return
        if "calibrated_sensor_fault" in obj:
            found = True
        for val in obj.values():
            _walk(val)

    _walk(raw)
    assert found, (
        "calibrated_sensor_fault must be retained in alarms_v3.yaml — "
        "it detects hardware sensor failure (values < 1K or > 350K), "
        "which CooldownAlarm/VacuumGuard do not cover."
    )
