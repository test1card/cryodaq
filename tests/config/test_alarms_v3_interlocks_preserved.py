"""Regression: keithley_overpower_interlock must stay in alarms_v3.yaml.

Its channels (smua_power, smub_power) are not covered by any regex in
config/interlocks.yaml and would lose throttle protection if removed.
"""
from pathlib import Path

import yaml

ALARMS_V3 = Path("config/alarms_v3.yaml")


def test_keithley_overpower_interlock_preserved():
    data = yaml.safe_load(ALARMS_V3.read_text(encoding="utf-8"))
    interlocks = data.get("interlocks") or {}
    assert "keithley_overpower_interlock" in interlocks
    entry = interlocks["keithley_overpower_interlock"]
    assert "smua_power" in entry.get("channels", [])
    assert "smub_power" in entry.get("channels", [])


def test_duplicate_interlocks_not_readded():
    data = yaml.safe_load(ALARMS_V3.read_text(encoding="utf-8"))
    interlocks = data.get("interlocks") or {}
    assert "overheat_cryostat" not in interlocks
    assert "detector_warmup_interlock" not in interlocks
