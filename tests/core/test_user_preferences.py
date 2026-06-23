"""Tests for UserPreferences and suggest_experiment_name."""

from __future__ import annotations

from pathlib import Path

from cryodaq.core.user_preferences import UserPreferences, suggest_experiment_name


def test_save_load_roundtrip(tmp_path: Path) -> None:
    prefs = UserPreferences(tmp_path / "prefs.json")
    prefs.save_last_experiment(
        template_id="thermal_conductivity",
        operator="Фоменко В.Н.",
        sample="УУКМ-3",
        cryostat="Криостат-1",
        description="Тест",
        custom_fields={"reference_channel": "T1"},
    )

    prefs2 = UserPreferences(tmp_path / "prefs.json")
    last = prefs2.get_last_experiment()

    assert last["template_id"] == "thermal_conductivity"
    assert last["operator"] == "Фоменко В.Н."
    assert last["sample"] == "УУКМ-3"
    assert last["cryostat"] == "Криостат-1"
    assert last["description"] == "Тест"
    assert last["custom_fields"]["reference_channel"] == "T1"


def test_history_dedup(tmp_path: Path) -> None:
    prefs = UserPreferences(tmp_path / "prefs.json")
    for _ in range(3):
        prefs.save_last_experiment(
            template_id="t", operator="Иванов", sample="S", cryostat="C", description=""
        )

    history = prefs.get_history("operator")
    assert history.count("Иванов") == 1
    assert history[0] == "Иванов"


def test_history_max_limit(tmp_path: Path) -> None:
    prefs = UserPreferences(tmp_path / "prefs.json")
    for i in range(25):
        prefs.save_last_experiment(
            template_id="t",
            operator=f"Operator-{i:02d}",
            sample="S",
            cryostat="C",
            description="",
        )

    history = prefs.get_history("operator")
    # Exactly 20 entries kept (not fewer — tests that truncation happened).
    assert len(history) == 20
    # Most-recently-added is first; oldest surviving entry is Operator-05.
    # Operator-00..04 were evicted by the 20-item cap.
    assert history[0] == "Operator-24"
    assert history[-1] == "Operator-05"
    assert history == [f"Operator-{i:02d}" for i in range(24, 4, -1)]


def test_empty_value_ignored(tmp_path: Path) -> None:
    prefs = UserPreferences(tmp_path / "prefs.json")
    prefs._add_to_history("operator_history", "")
    prefs._add_to_history("operator_history", "   ")
    assert prefs.get_history("operator") == []


def test_empty_prefs_file(tmp_path: Path) -> None:
    prefs = UserPreferences(tmp_path / "nonexistent.json")
    assert prefs.get_last_experiment() == {}
    assert prefs.get_history("operator") == []


def test_suggest_name_increments() -> None:
    existing = ["Cooldown-001", "Cooldown-003", "Cooldown-005"]
    name = suggest_experiment_name("cooldown", existing, {"cooldown": "Cooldown"})
    assert name == "Cooldown-006"


def test_suggest_name_no_existing() -> None:
    name = suggest_experiment_name("cooldown", [], {"cooldown": "Cooldown"})
    assert name == "Cooldown-001"


def test_suggest_name_without_map() -> None:
    # Without a map, template_id is title-cased ("My Template"); first slot → 001.
    name = suggest_experiment_name("my_template", [])
    assert name == "My Template-001"


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    prefs = UserPreferences(tmp_path / "a" / "b" / "prefs.json")
    prefs._add_to_history("operator_history", "Test")
    prefs.save()
    assert (tmp_path / "a" / "b" / "prefs.json").exists()
