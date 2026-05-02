"""Verify cooldown_stall was removed from alarms_v3.yaml (F-X v3 cleanup).

The cooldown_stall composite alarm (static threshold workaround) was deleted
in F-X v3. CooldownAlarm (predictor-based) replaces it.
See config/physical_alarms.yaml.
"""
from pathlib import Path

import yaml


ALARMS_V3 = Path("config/alarms_v3.yaml")


def test_cooldown_stall_removed_replaced_by_physical_alarm():
    """cooldown_stall no longer exists in alarms_v3.yaml — replaced by F-X v3 CooldownAlarm."""
    data = yaml.safe_load(ALARMS_V3.read_text(encoding="utf-8"))
    cooldown_section = data.get("phase_alarms", {}).get("cooldown", {})
    assert "cooldown_stall" not in cooldown_section, (
        "cooldown_stall should have been removed in F-X v3 (replaced by CooldownAlarm). "
        "See config/physical_alarms.yaml."
    )
