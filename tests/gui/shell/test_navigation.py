from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from cryodaq.gui.shell.navigation import (
    DESTINATIONS_BY_KEY,
    NAVIGATION_SECTIONS,
    AvailabilityPolicy,
    NavigationDestination,
    NavigationGroup,
)

_LEGACY_ROUTE_KEYS = {
    "home",
    "new_experiment",
    "experiment",
    "source",
    "analytics",
    "conductivity",
    "multiline",
    "alarms",
    "log",
    "knowledge_base",
    "instruments",
    "archive",
    "calibration",
    "settings",
    "web_panel",
    "restart_engine",
}


def test_every_current_route_key_and_roadmap_destination_is_preserved() -> None:
    assert set(DESTINATIONS_BY_KEY) == _LEGACY_ROUTE_KEYS
    assert [section.group for section in NAVIGATION_SECTIONS] == list(NavigationGroup)
    assert [destination.key for destination in NAVIGATION_SECTIONS[0].destinations if destination.primary] == [
        "home",
        "experiment",
        "source",
        "alarms",
        "instruments",
    ]
    assert [destination.key for destination in NAVIGATION_SECTIONS[1].destinations] == [
        "analytics",
        "conductivity",
        "multiline",
    ]
    assert [destination.key for destination in NAVIGATION_SECTIONS[2].destinations] == ["log", "archive"]
    assert [destination.key for destination in NAVIGATION_SECTIONS[3].destinations] == [
        "calibration",
        "knowledge_base",
        "settings",
        "web_panel",
        "restart_engine",
    ]


def test_current_mnemonic_and_numeric_shortcuts_are_preserved_without_collision() -> None:
    expected = {
        "Ctrl+L": "log",
        "Ctrl+E": "experiment",
        "Ctrl+A": "analytics",
        "Ctrl+K": "source",
        "Ctrl+M": "alarms",
        "Ctrl+R": "archive",
        "Ctrl+C": "conductivity",
        "Ctrl+D": "instruments",
        "Ctrl+1": "home",
        "Ctrl+2": "new_experiment",
        "Ctrl+3": "experiment",
        "Ctrl+4": "source",
        "Ctrl+5": "analytics",
        "Ctrl+6": "conductivity",
        "Ctrl+7": "multiline",
        "Ctrl+8": "alarms",
        "Ctrl+9": "log",
    }
    actual = {
        shortcut: destination.key
        for destination in DESTINATIONS_BY_KEY.values()
        for shortcut in destination.all_shortcuts
    }
    assert actual == expected
    assert len(actual) == sum(len(destination.all_shortcuts) for destination in DESTINATIONS_BY_KEY.values())


def test_registry_and_nested_models_are_immutable() -> None:
    with pytest.raises(TypeError):
        DESTINATIONS_BY_KEY["other"] = DESTINATIONS_BY_KEY["home"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        NAVIGATION_SECTIONS[0].label = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        DESTINATIONS_BY_KEY["home"].label = "changed"  # type: ignore[misc]


def test_contextual_experiment_creation_preserves_single_existing_route() -> None:
    experiment = DESTINATIONS_BY_KEY["experiment"]
    creation = experiment.contextual_experiment_creation
    assert creation is not None
    assert creation.route_key == "new_experiment"
    assert creation.label == "Создать эксперимент"
    assert DESTINATIONS_BY_KEY[creation.route_key].primary is False
    assert DESTINATIONS_BY_KEY[creation.route_key].availability_policy is AvailabilityPolicy.CONTEXTUAL


def test_unavailable_or_contextual_destination_requires_visible_reason() -> None:
    with pytest.raises(ValueError, match="requires an unavailable reason"):
        NavigationDestination(
            "future",
            NavigationGroup.MORE,
            "Будущий раздел",
            availability_policy=AvailabilityPolicy.UNAVAILABLE,
        )
    assert DESTINATIONS_BY_KEY["new_experiment"].unavailable_reason


def test_labels_and_order_are_deterministic_and_operator_facing() -> None:
    snapshot = [
        (section.group.value, section.label, [(item.key, item.label) for item in section.destinations])
        for section in NAVIGATION_SECTIONS
    ]
    assert snapshot == [
        (
            "operate",
            "Работа",
            [
                ("home", "Главная"),
                ("experiment", "Эксперимент"),
                ("new_experiment", "Новый эксперимент"),
                ("source", "Источник мощности"),
                ("alarms", "Тревоги"),
                ("instruments", "Приборы"),
            ],
        ),
        (
            "analyze",
            "Анализ",
            [
                ("analytics", "Аналитика"),
                ("conductivity", "Теплопроводность"),
                ("multiline", "MultiLine"),
            ],
        ),
        ("record_review", "Запись и обзор", [("log", "Журнал оператора"), ("archive", "Обзор и архив")]),
        (
            "more",
            "Ещё",
            [
                ("calibration", "Калибровка"),
                ("knowledge_base", "База знаний"),
                ("settings", "Настройки"),
                ("web_panel", "Web-панель"),
                ("restart_engine", "Перезапуск Engine"),
            ],
        ),
    ]


def test_navigation_model_has_no_control_callable_or_product_authority_import() -> None:
    source_path = Path("src/cryodaq/gui/shell/navigation.py")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(
        module.startswith(("PySide6", "cryodaq.core", "cryodaq.drivers", "cryodaq.safety"))
        for module in imported_modules
    )
    assert "Callable" not in source
    assert "handler" not in source
    assert "command" not in {node.id.casefold() for node in ast.walk(tree) if isinstance(node, ast.Name)}
