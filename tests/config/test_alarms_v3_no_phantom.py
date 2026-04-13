"""Regression test for A.6: alarms_v3.yaml must not contain phantom interlocks."""
from pathlib import Path

import yaml

ALARMS_V3 = Path("config/alarms_v3.yaml")


def test_no_interlocks_key_in_alarms_v3():
    """A.6: interlocks are configured in config/interlocks.yaml, not here."""
    raw = yaml.safe_load(ALARMS_V3.read_text(encoding="utf-8"))
    assert "interlocks" not in raw, (
        "Phantom interlocks section found in alarms_v3.yaml — "
        "interlocks belong in config/interlocks.yaml"
    )
