"""F-LegacyChannelMap — channel rename mappings for historical recordings.

Pre-thermal-bridge era (before 2025-02-20): channel 8 on LakeShore #1
was disconnected, so subsequent labels shifted by 1. Old "cold" was
labelled "Т10" (current canonical: "Т12", 2nd-stage GM cooler);
"Т11" (warm, 1st-stage / N₂ plate) was already canonical and stays.

Mapping is applied only on the SQLiteReplay / DirectoryReplay path —
CurveReplay (cooldown_v5/*.json) is post-bridge era and is NOT touched.
"""

from __future__ import annotations

ERA_PRE_2025_02: dict[str, str] = {
    "Т10": "Т12",
    "Т9": "Т10",
    "Т8": "Т9",
}

LEGACY_CHANNEL_MAPS: dict[str, dict[str, str]] = {
    "pre-2025-02": ERA_PRE_2025_02,
}


def get_legacy_map(era: str) -> dict[str, str]:
    """Return the channel rename map for an era, or {} if unknown."""
    return LEGACY_CHANNEL_MAPS.get(era, {})
