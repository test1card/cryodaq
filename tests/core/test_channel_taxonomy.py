"""F-X (v0.55.9) — channel taxonomy + phase-aware alarm band tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cryodaq.core.channel_manager import ChannelManager


@pytest.fixture
def mgr() -> ChannelManager:
    """Fresh manager loaded from the in-repo `config/channels.yaml`."""
    return ChannelManager()


# ---------------------------------------------------------------------------
# thermal_zone classification
# ---------------------------------------------------------------------------


def test_thermal_zone_loaded_from_yaml(mgr: ChannelManager) -> None:
    """Every architect-classified channel should have a thermal_zone."""
    classified = {
        "Т1": "intermediate",
        "Т5": "cold_77k",
        "Т6": "cold_4k",
        "Т7": "cold_4k",
        "Т8": "warm_reference",
        "Т11": "cold_landmark",
        "Т12": "cold_landmark",
        "Т15": "warm_flange",
        "Т16": "warm_flange",
        "Т17": "disconnected_reserve",
        "Т24": "disconnected_reserve",
    }
    for ch, expected in classified.items():
        assert mgr.get_thermal_zone(ch) == expected, f"{ch} expected {expected}"


def test_get_thermal_zone_unknown_channel_returns_none(mgr: ChannelManager) -> None:
    assert mgr.get_thermal_zone("ChannelDoesNotExist") is None


def test_get_thermal_zone_accepts_full_label(mgr: ChannelManager) -> None:
    """Resolves canonical "Т7 Детектор" or short "Т7" identically."""
    assert mgr.get_thermal_zone("Т7 Детектор") == "cold_4k"


def test_get_channels_in_zone_disconnected_reserve(mgr: ChannelManager) -> None:
    reserves = mgr.get_channels_in_zone("disconnected_reserve")
    # 8 reserve+optics channels (Т17..Т24) — assert exact membership, not just endpoints
    assert set(reserves) == {f"Т{i}" for i in range(17, 25)}, (
        f"Expected Т17..Т24, got {sorted(reserves)}"
    )


def test_get_channels_in_zone_cold_4k(mgr: ChannelManager) -> None:
    cold_4k = mgr.get_channels_in_zone("cold_4k")
    assert "Т6" in cold_4k
    assert "Т7" in cold_4k


def test_get_channels_in_zone_unknown_zone_returns_empty(mgr: ChannelManager) -> None:
    assert mgr.get_channels_in_zone("not_a_real_zone") == []


# ---------------------------------------------------------------------------
# get_alarm_band — phase resolution
# ---------------------------------------------------------------------------


def test_get_alarm_band_returns_phase_specific_for_cold_4k(mgr: ChannelManager) -> None:
    """Detector (cold_4k) narrows from cooldown's wide window to the
    measurement-phase tight band."""
    cooldown = mgr.get_alarm_band("Т7", phase="cooldown")
    measurement = mgr.get_alarm_band("Т7", phase="measurement")
    assert cooldown == (3.5, 320.0)
    assert measurement == (3.5, 5.0)
    # Narrower upper bound during measurement
    assert measurement[1] < cooldown[1]


def test_get_alarm_band_falls_back_to_all_phases(mgr: ChannelManager) -> None:
    """If the requested phase isn't in the band dict, fall back to all_phases."""
    band = mgr.get_alarm_band("Т7", phase="some_unknown_phase")
    assert band == (3.5, 320.0)


def test_get_alarm_band_no_phase_returns_all_phases(mgr: ChannelManager) -> None:
    band = mgr.get_alarm_band("Т7")
    assert band == (3.5, 320.0)


def test_get_alarm_band_warm_reference_constant_band(mgr: ChannelManager) -> None:
    """Reference block stays warm — same band for every phase."""
    for phase in ("cooldown", "measurement", "warmup", None):
        band = mgr.get_alarm_band("Т8", phase=phase)
        assert band == (285.0, 310.0)


def test_get_alarm_band_warm_flange_band(mgr: ChannelManager) -> None:
    band = mgr.get_alarm_band("Т16")
    assert band == (270.0, 320.0)


def test_get_alarm_band_returns_none_for_uncategorized(mgr: ChannelManager) -> None:
    """disconnected_reserve channels (Т17..Т24) have no alarm_band."""
    assert mgr.get_alarm_band("Т17") is None
    assert mgr.get_alarm_band("Т24", phase="measurement") is None


def test_get_alarm_band_accepts_phase_case_insensitive(mgr: ChannelManager) -> None:
    """`phase="COOLDOWN"` resolves the same as `phase="cooldown"`."""
    assert mgr.get_alarm_band("Т7", phase="COOLDOWN") == mgr.get_alarm_band(
        "Т7", phase="cooldown"
    )


def test_get_alarm_band_accepts_full_label(mgr: ChannelManager) -> None:
    assert mgr.get_alarm_band("Т7 Детектор", phase="measurement") == (3.5, 5.0)


# ---------------------------------------------------------------------------
# Defensive parsing
# ---------------------------------------------------------------------------


def test_get_alarm_band_handles_non_numeric_band(tmp_path: Path) -> None:
    """A malformed YAML band (non-numeric values) must not crash —
    method returns None and logs a warning."""
    cfg = tmp_path / "channels.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "channels": {
                    "Т_test": {
                        "name": "Test",
                        "thermal_zone": "cold_4k",
                        "alarm_band": {
                            "all_phases": ["not", "numeric"],
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    mgr = ChannelManager(config_path=cfg)
    mgr.load()
    assert mgr.get_alarm_band("Т_test") is None


def test_get_alarm_band_handles_reversed_range(tmp_path: Path) -> None:
    """A reversed [high, low] range is rejected (would never trigger)."""
    cfg = tmp_path / "channels.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "channels": {
                    "Т_test": {
                        "name": "Test",
                        "alarm_band": {"all_phases": [310.0, 285.0]},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    mgr = ChannelManager(config_path=cfg)
    mgr.load()
    assert mgr.get_alarm_band("Т_test") is None


def test_get_alarm_band_handles_wrong_length_list(tmp_path: Path) -> None:
    cfg = tmp_path / "channels.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "channels": {
                    "Т_test": {
                        "name": "Test",
                        "alarm_band": {"all_phases": [285.0, 290.0, 300.0]},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    mgr = ChannelManager(config_path=cfg)
    mgr.load()
    assert mgr.get_alarm_band("Т_test") is None


def test_get_alarm_band_handles_alarm_band_not_dict(tmp_path: Path) -> None:
    """If `alarm_band` is somehow a string / list (legacy data),
    method returns None instead of crashing."""
    cfg = tmp_path / "channels.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "channels": {
                    "Т_test": {
                        "name": "Test",
                        "alarm_band": "not a dict",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    mgr = ChannelManager(config_path=cfg)
    mgr.load()
    assert mgr.get_alarm_band("Т_test") is None


# ---------------------------------------------------------------------------
# Behavioural acceptance — the real lab scenarios from the spec
# ---------------------------------------------------------------------------


def test_warm_reference_at_300K_passes_band(mgr: ChannelManager) -> None:
    """Т8 Калибровка at 300K is within band — no alarm should fire
    (regression of the 2026-05-01 lab observation)."""
    low, high = mgr.get_alarm_band("Т8")
    assert low <= 300.0 <= high


def test_warm_flange_at_300K_passes_band(mgr: ChannelManager) -> None:
    """Т16 Фланец stays at room T by design — 300K must be inside band."""
    low, high = mgr.get_alarm_band("Т16")
    assert low <= 300.0 <= high


def test_cold_4k_at_300K_in_measurement_phase_alarms(mgr: ChannelManager) -> None:
    """Detector at 300K during measurement phase = real disconnect /
    catastrophic warmup — band must reject."""
    low, high = mgr.get_alarm_band("Т7", phase="measurement")
    assert not (low <= 300.0 <= high)


def test_cold_4k_at_300K_during_cooldown_passes_band(mgr: ChannelManager) -> None:
    """Detector at 300K during cooldown phase is OK (transient warmup
    state)."""
    low, high = mgr.get_alarm_band("Т7", phase="cooldown")
    assert low <= 300.0 <= high


def test_cold_landmark_t12_at_3K_in_measurement_passes(mgr: ChannelManager) -> None:
    """Т12 cold-landmark at ~3K (operating temp per landmarks doc) is OK."""
    low, high = mgr.get_alarm_band("Т12", phase="measurement")
    assert low <= 3.0 <= high


def test_cold_landmark_t11_at_40K_in_measurement_passes(mgr: ChannelManager) -> None:
    """Т11 1st-stage at ~40K (operating temp) is OK."""
    low, high = mgr.get_alarm_band("Т11", phase="measurement")
    assert low <= 40.0 <= high


def test_disconnected_reserve_has_no_band(mgr: ChannelManager) -> None:
    """Reserve channels (Т17..Т24) get None — alarm engine falls
    through to legacy alarms_v3.yaml rules."""
    for ch in mgr.get_channels_in_zone("disconnected_reserve"):
        assert mgr.get_alarm_band(ch) is None
