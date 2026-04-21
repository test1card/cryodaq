from pathlib import Path

import yaml


ALARMS_V3 = Path("config/alarms_v3.yaml")


def test_cooldown_stall_uses_static_threshold_not_threshold_expr():
    data = yaml.safe_load(ALARMS_V3.read_text(encoding="utf-8"))
    stall = data["phase_alarms"]["cooldown"]["cooldown_stall"]
    conditions = stall["conditions"]
    above = next(c for c in conditions if c.get("check") == "above")
    assert above["threshold"] == 150
    assert "threshold_expr" not in above
