"""Immutable operator-intent navigation model.

This module describes destinations only.  It deliberately imports no Qt,
transport, command, or safety code and carries no callbacks: resolving a route
to a widget or action remains the shell host's responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final


class NavigationGroup(StrEnum):
    """Stable operator-intent groups in display order."""

    OPERATE = "operate"
    ANALYZE = "analyze"
    RECORD_REVIEW = "record_review"
    MORE = "more"


class AvailabilityPolicy(StrEnum):
    """Static policy a future view may evaluate using backend truth."""

    ALWAYS = "always"
    CONTEXTUAL = "contextual"
    UNAVAILABLE = "unavailable"


class ExperimentCreationContext(StrEnum):
    """Reviewed placement for the existing experiment-creation route."""

    NO_ACTIVE_EXPERIMENT = "no_active_experiment"


@dataclass(frozen=True, slots=True)
class ContextualExperimentCreation:
    """Metadata linking experiment navigation to the existing creation flow."""

    route_key: str
    label: str
    show_when: ExperimentCreationContext

    def __post_init__(self) -> None:
        if self.route_key != "new_experiment":
            raise ValueError("experiment creation must preserve the new_experiment route key")
        if not self.label.strip():
            raise ValueError("experiment creation label must be non-empty")


@dataclass(frozen=True, slots=True)
class NavigationDestination:
    """One static route descriptor with no command or widget authority."""

    key: str
    group: NavigationGroup
    label: str
    shortcut: str | None = None
    legacy_shortcuts: tuple[str, ...] = ()
    availability_policy: AvailabilityPolicy = AvailabilityPolicy.ALWAYS
    unavailable_reason: str | None = None
    primary: bool = True
    contextual_experiment_creation: ContextualExperimentCreation | None = None

    def __post_init__(self) -> None:
        if not self.key or not self.key.isascii() or not self.key.replace("_", "").isalnum():
            raise ValueError("navigation key must be a non-empty ASCII identifier")
        if not self.label.strip():
            raise ValueError("navigation label must be non-empty")
        shortcuts = tuple(self.legacy_shortcuts)
        if any(not shortcut.strip() for shortcut in shortcuts):
            raise ValueError("legacy shortcuts must be non-empty")
        object.__setattr__(self, "legacy_shortcuts", shortcuts)
        if self.availability_policy is AvailabilityPolicy.ALWAYS:
            if self.unavailable_reason is not None:
                raise ValueError("always-available destination cannot have an unavailable reason")
        elif self.unavailable_reason is None or not self.unavailable_reason.strip():
            raise ValueError("non-always destination requires an unavailable reason")
        if self.contextual_experiment_creation is not None and self.key != "experiment":
            raise ValueError("experiment creation metadata belongs only to the experiment route")

    @property
    def all_shortcuts(self) -> tuple[str, ...]:
        """Canonical shortcut followed by preserved transitional aliases."""

        canonical = () if self.shortcut is None else (self.shortcut,)
        return canonical + self.legacy_shortcuts


@dataclass(frozen=True, slots=True)
class NavigationSection:
    """One ordered intent group and its ordered destinations."""

    group: NavigationGroup
    label: str
    destinations: tuple[NavigationDestination, ...]

    def __post_init__(self) -> None:
        destinations = tuple(self.destinations)
        if not self.label.strip() or not destinations:
            raise ValueError("navigation section requires a label and destinations")
        if any(destination.group is not self.group for destination in destinations):
            raise ValueError("destination group contradicts its section")
        object.__setattr__(self, "destinations", destinations)


_CREATE_EXPERIMENT = ContextualExperimentCreation(
    route_key="new_experiment",
    label="Создать эксперимент",
    show_when=ExperimentCreationContext.NO_ACTIVE_EXPERIMENT,
)

NAVIGATION_SECTIONS: Final[tuple[NavigationSection, ...]] = (
    NavigationSection(
        NavigationGroup.OPERATE,
        "Работа",
        (
            NavigationDestination(
                "home",
                NavigationGroup.OPERATE,
                "Главная",
                shortcut="Ctrl+H",
                legacy_shortcuts=("Ctrl+1",),
            ),
            NavigationDestination(
                "experiment",
                NavigationGroup.OPERATE,
                "Эксперимент",
                shortcut="Ctrl+E",
                legacy_shortcuts=("Ctrl+3",),
                contextual_experiment_creation=_CREATE_EXPERIMENT,
            ),
            NavigationDestination(
                "new_experiment",
                NavigationGroup.OPERATE,
                "Новый эксперимент",
                legacy_shortcuts=("Ctrl+2",),
                availability_policy=AvailabilityPolicy.CONTEXTUAL,
                unavailable_reason="Создание доступно из контекста эксперимента.",
                primary=False,
            ),
            NavigationDestination(
                "source",
                NavigationGroup.OPERATE,
                "Источник мощности",
                shortcut="Ctrl+K",
                legacy_shortcuts=("Ctrl+4",),
            ),
            NavigationDestination(
                "alarms",
                NavigationGroup.OPERATE,
                "Тревоги",
                shortcut="Ctrl+M",
                legacy_shortcuts=("Ctrl+8",),
            ),
            NavigationDestination(
                "instruments",
                NavigationGroup.OPERATE,
                "Приборы",
                shortcut="Ctrl+D",
            ),
        ),
    ),
    NavigationSection(
        NavigationGroup.ANALYZE,
        "Анализ",
        (
            NavigationDestination(
                "analytics",
                NavigationGroup.ANALYZE,
                "Аналитика",
                shortcut="Ctrl+A",
                legacy_shortcuts=("Ctrl+5",),
            ),
            NavigationDestination(
                "conductivity",
                NavigationGroup.ANALYZE,
                "Теплопроводность",
                shortcut="Ctrl+C",
                legacy_shortcuts=("Ctrl+6",),
            ),
            NavigationDestination(
                "multiline",
                NavigationGroup.ANALYZE,
                "MultiLine",
                legacy_shortcuts=("Ctrl+7",),
            ),
        ),
    ),
    NavigationSection(
        NavigationGroup.RECORD_REVIEW,
        "Запись и обзор",
        (
            NavigationDestination(
                "log",
                NavigationGroup.RECORD_REVIEW,
                "Журнал оператора",
                shortcut="Ctrl+L",
                legacy_shortcuts=("Ctrl+9",),
            ),
            NavigationDestination(
                "archive",
                NavigationGroup.RECORD_REVIEW,
                "Обзор и архив",
                shortcut="Ctrl+R",
            ),
        ),
    ),
    NavigationSection(
        NavigationGroup.MORE,
        "Ещё",
        (
            NavigationDestination("summary", NavigationGroup.MORE, "Сводка смены"),
            NavigationDestination("calibration", NavigationGroup.MORE, "Калибровка"),
            NavigationDestination("knowledge_base", NavigationGroup.MORE, "База знаний"),
            NavigationDestination("settings", NavigationGroup.MORE, "Настройки"),
            NavigationDestination("web_panel", NavigationGroup.MORE, "Web-панель"),
            NavigationDestination("restart_engine", NavigationGroup.MORE, "Перезапуск Engine"),
        ),
    ),
)


def _build_destination_index(
    sections: tuple[NavigationSection, ...],
) -> MappingProxyType[str, NavigationDestination]:
    expected_groups = tuple(NavigationGroup)
    if tuple(section.group for section in sections) != expected_groups:
        raise ValueError("navigation sections must use deterministic intent-group ordering")
    destinations = tuple(destination for section in sections for destination in section.destinations)
    keys = [destination.key for destination in destinations]
    if len(keys) != len(set(keys)):
        raise ValueError("navigation destination keys must be unique")
    shortcuts = [shortcut.casefold() for destination in destinations for shortcut in destination.all_shortcuts]
    if len(shortcuts) != len(set(shortcuts)):
        raise ValueError("navigation shortcuts must be unique")
    return MappingProxyType({destination.key: destination for destination in destinations})


DESTINATIONS_BY_KEY: Final = _build_destination_index(NAVIGATION_SECTIONS)
