"""v0.55.5 — verify Telegram dispatch policy invariants.

Telegram = one-shot physics-critical events only. Sensor-health alarms go
to GUI Diagnostics tab (and the hourly periodic_report digest).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from cryodaq.core.alarm_config import load_alarm_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_sensor_fault_notify_gui_only() -> None:
    """sensor_fault and sensor_fault_intermittent must NOT carry telegram in notify."""
    _, alarms = load_alarm_config(REPO_ROOT / "config" / "alarms_v3.yaml")
    by_id = {a.alarm_id: a for a in alarms}

    for aid in ("sensor_fault", "sensor_fault_intermittent"):
        assert aid in by_id, f"{aid} missing from alarms_v3.yaml"
        assert "telegram" not in by_id[aid].notify, (
            f"{aid} must not dispatch to Telegram (v0.55.5 policy)"
        )
        assert "gui" in by_id[aid].notify, f"{aid} must keep gui dispatch"


def test_vacuum_loss_cold_notify_telegram() -> None:
    """vacuum_loss_cold (physics-critical) must dispatch to Telegram."""
    _, alarms = load_alarm_config(REPO_ROOT / "config" / "alarms_v3.yaml")
    by_id = {a.alarm_id: a for a in alarms}

    assert "vacuum_loss_cold" in by_id
    assert "telegram" in by_id["vacuum_loss_cold"].notify
    assert "gui" in by_id["vacuum_loss_cold"].notify


def test_calibrated_sensor_fault_notify_telegram() -> None:
    """Hardware fault on calibrated Т11/Т12 is CRITICAL — keeps Telegram."""
    _, alarms = load_alarm_config(REPO_ROOT / "config" / "alarms_v3.yaml")
    by_id = {a.alarm_id: a for a in alarms}

    assert "calibrated_sensor_fault" in by_id
    assert "telegram" in by_id["calibrated_sensor_fault"].notify


def test_data_stale_warning_gui_only() -> None:
    """data_stale_temperature is WARNING-level diagnostic — GUI only."""
    _, alarms = load_alarm_config(REPO_ROOT / "config" / "alarms_v3.yaml")
    by_id = {a.alarm_id: a for a in alarms}

    assert "telegram" not in by_id["data_stale_temperature"].notify


def test_plugins_yaml_sensor_diag_telegram_disabled() -> None:
    """sensor_diagnostics.notify_telegram must default to False (v0.55.5 policy)."""
    raw = yaml.safe_load((REPO_ROOT / "config" / "plugins.yaml").read_text(encoding="utf-8"))
    sd = raw.get("sensor_diagnostics", {})
    assert sd.get("notify_telegram", True) is False, (
        "sensor_diagnostics.notify_telegram must be False — sensor health "
        "alarms route to GUI only (v0.55.5)"
    )
