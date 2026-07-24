from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cryodaq.core.housekeeping import (
    HousekeepingConfigError,
    resolve_canonical_temperature_bindings,
    resolve_canonical_temperature_labels,
    resolve_protected_channel_bindings,
)
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


def test_selected_descriptor_installs_exact_temperature_and_throttle_labels() -> None:
    catalog = load_live_channel_descriptor_catalog(_ROOT / "config" / "channel_descriptors.yaml")
    labels = resolve_canonical_temperature_labels(catalog, {"\u042211", "\u042212"})
    assert labels == {
        "\u042211": "\u042211 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 1",
        "\u042212": "\u042212 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2",
    }
    resolved = resolve_protected_channel_bindings(catalog, {"\u0422(11|12)$"})
    assert resolved == {
        "^\u042211\\ \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a\\ 1$",
        "^\u042212\\ \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a\\ 2$",
    }


def _production_document() -> dict:
    return yaml.safe_load((_ROOT / "config" / "physical_alarms.yaml").read_text(encoding="utf-8"))


def _write_document(path: Path, document: object) -> None:
    path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document["cooldown"].__setitem__("enabled", "true"),
        lambda document: document["cooldown"].__setitem__("unknown", 1),
        lambda document: document["vacuum"].pop("severity"),
        lambda document: document["landmarks"]["\u042211"].__setitem__("role", "cold_stage"),
        lambda document: document["landmarks"]["\u042212"]["aliases"].append(
            document["landmarks"]["\u042211"]["aliases"][0]
        ),
        lambda document: document["landmarks"]["\u042211"]["aliases"].append("e\u0301"),
        lambda document: document["landmarks"]["\u042211"]["aliases"].append("bad\u200dformat"),
    ],
)
def test_production_loader_normalizes_schema_identity_and_unicode_failures(
    tmp_path: Path,
    mutation,
) -> None:
    document = _production_document()
    mutation(document)
    path = tmp_path / "physical_alarms.yaml"
    _write_document(path, document)
    with pytest.raises(PhysicalAlarmsConfigError):
        load_production_physical_alarms_config(path)


def test_production_loader_rejects_invalid_utf8_size_depth_and_node_bounds(tmp_path: Path) -> None:
    invalid_utf8 = tmp_path / "invalid-utf8.yaml"
    invalid_utf8.write_bytes(b"cooldown: \xff")
    oversized = tmp_path / "oversized.yaml"
    oversized.write_text("#" + ("x" * (64 * 1024)), encoding="utf-8")
    too_deep = tmp_path / "too-deep.yaml"
    too_deep.write_text(("node:\n" * 30), encoding="utf-8")
    node_heavy = tmp_path / "node-heavy.yaml"
    node_heavy.write_text(
        "\n".join(f"key_{index}: {index}" for index in range(1_100)),
        encoding="utf-8",
    )
    too_deep.write_text(
        'root:\n'
        + ''.join(('  ' * depth) + f'level_{depth}:\n' for depth in range(1, 31))
        + ('  ' * 31)
        + 'leaf: 1\n',
        encoding='utf-8',
    )
    for path in (invalid_utf8, oversized, too_deep, node_heavy):
        with pytest.raises(PhysicalAlarmsConfigError):
            load_production_physical_alarms_config(path)


def test_production_loader_rejects_nonregular_traversal_and_predictor_directory(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    outside = tmp_path / "outside.yaml"
    _write_document(outside, _production_document())
    with pytest.raises(PhysicalAlarmsConfigError, match="escapes"):
        load_production_physical_alarms_config(outside, trusted_config_root=config_dir)
    nonregular = config_dir / "physical_alarms.yaml"
    nonregular.mkdir()
    with pytest.raises(PhysicalAlarmsConfigError, match="regular"):
        load_production_physical_alarms_config(nonregular, trusted_config_root=config_dir)
    nonregular.rmdir()
    _write_document(nonregular, _production_document())
    predictor = tmp_path / "data" / "cooldown_model" / "predictor_model.json"
    predictor.mkdir(parents=True)
    with pytest.raises(PhysicalAlarmsConfigError, match="predictor"):
        load_production_physical_alarms_config(
            nonregular,
            trusted_config_root=config_dir,
            project_root=tmp_path,
        )


def test_canonical_binding_collision_is_rejected() -> None:
    class _Catalog:
        _bindings = {
            ("one", "Т11 one"): "Т11",
            ("two", "Т11 two"): "Т11",
        }

    with pytest.raises(HousekeepingConfigError, match="exactly one"):
        resolve_canonical_temperature_bindings(_Catalog(), {"Т11"})
