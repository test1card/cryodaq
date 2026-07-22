from __future__ import annotations

from pathlib import Path

import pytest

from cryodaq.core.housekeeping import HousekeepingConfigError, resolve_canonical_temperature_bindings
from cryodaq.core.physical_alarms_config import (
    PhysicalAlarmsConfigError,
    load_production_physical_alarms_config,
)
from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog

_ROOT = Path(__file__).parents[2]


def test_production_physical_alarm_document_is_complete_and_exact() -> None:
    cooldown, vacuum, landmarks = load_production_physical_alarms_config(_ROOT / "config" / "physical_alarms.yaml")
    assert cooldown["warm_channel"] == "Т11"
    assert cooldown["cold_channel"] == "Т12"
    assert vacuum["reference_temp_channel"] == "Т12"
    assert set(landmarks) == {"Т11", "Т12"}


def test_production_loader_rejects_missing_duplicate_and_aliases(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(PhysicalAlarmsConfigError):
        load_production_physical_alarms_config(missing)
    duplicate = tmp_path / "duplicate.yaml"
    duplicate.write_text("cooldown: {}\ncooldown: {}\nvacuum: {}\nlandmarks: {}\n", encoding="utf-8")
    with pytest.raises(PhysicalAlarmsConfigError, match="duplicate"):
        load_production_physical_alarms_config(duplicate)
    aliased = tmp_path / "alias.yaml"
    aliased.write_text("cooldown: &same {}\nvacuum: *same\nlandmarks: {}\n", encoding="utf-8")
    with pytest.raises(PhysicalAlarmsConfigError, match="aliases"):
        load_production_physical_alarms_config(aliased)


def test_canonical_temperatures_reverse_map_to_one_nonraw_full_match() -> None:
    catalog = load_live_channel_descriptor_catalog(_ROOT / "config" / "channel_descriptors.yaml")
    exact = resolve_canonical_temperature_bindings(catalog, {"Т11", "Т12"})
    assert exact == {r"^Т11\ Теплообменник\ 1$", r"^Т12\ Теплообменник\ 2$"}
    assert all("raw" not in pattern for pattern in exact)


def test_canonical_binding_collision_is_rejected() -> None:
    class _Catalog:
        _bindings = {
            ("one", "Т11 one"): "Т11",
            ("two", "Т11 two"): "Т11",
        }

    with pytest.raises(HousekeepingConfigError, match="exactly one"):
        resolve_canonical_temperature_bindings(_Catalog(), {"Т11"})
