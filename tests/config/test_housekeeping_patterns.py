"""Regression test for C.5: Latin T in housekeeping.yaml include_patterns."""
import re
from pathlib import Path

import yaml

HOUSEKEEPING_YAML = Path("config/housekeeping.yaml")


def test_include_patterns_match_cyrillic_channels():
    """include_patterns must match real Cyrillic Т channel names."""
    raw = yaml.safe_load(HOUSEKEEPING_YAML.read_text(encoding="utf-8"))
    patterns = [re.compile(p) for p in raw["adaptive_throttle"]["include_patterns"]]

    real_channels = [
        "Т9 Компрессор вход",
        "Т10 Компрессор выход",
        "Т11 Теплообменник 1",
        "Т12 Теплообменник 2",
        "Т17 Зеркало 1",
    ]
    for channel in real_channels:
        assert any(p.match(channel) for p in patterns), (
            f"No include pattern matched Cyrillic channel {channel!r}"
        )


def test_include_patterns_still_exclude_cryostat_critical():
    """Т1-Т8 must NOT be throttled (negative lookahead)."""
    raw = yaml.safe_load(HOUSEKEEPING_YAML.read_text(encoding="utf-8"))
    patterns = [re.compile(p) for p in raw["adaptive_throttle"]["include_patterns"]]

    excluded = ["Т1 Криостат верх", "Т7 Детектор", "Т8 Калибровка"]
    for channel in excluded:
        assert not any(p.match(channel) for p in patterns), (
            f"Critical channel {channel!r} should NOT be throttled"
        )


def test_include_patterns_still_match_latin_fallback():
    """Both Cyrillic AND Latin T must match for defense in depth."""
    raw = yaml.safe_load(HOUSEKEEPING_YAML.read_text(encoding="utf-8"))
    patterns = [re.compile(p) for p in raw["adaptive_throttle"]["include_patterns"]]

    assert any(p.match("T9 Compressor in") for p in patterns), (
        "Latin T fallback missing from include_patterns"
    )
