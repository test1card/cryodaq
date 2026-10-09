"""Russian display-name helpers for F30 Live Query Agent.

All operator-facing labels must be in Russian per project standard.
These helpers provide consistent translation for phase names, status strings,
and boolean values across format prompts and response formatting.
"""

from __future__ import annotations

_PHASE_MAP: dict[str, str] = {
    "cooldown": "захолаживание",
    "warmup": "отогрев",
    "measurement": "измерение",
    "preparation": "подготовка",
    "vacuum": "откачка вакуума",
    "teardown": "разборка",
}

_STATUS_MAP: dict[str, str] = {
    "running": "работает",
    "completed": "завершён",
    "aborted": "прерван",
}


def phase_display_name(phase: str | None) -> str:
    """Return Russian display name for an experiment phase.

    Unknown phases are passed through unchanged. None returns "нет данных".
    """
    if phase is None:
        return "нет данных"
    return _PHASE_MAP.get(phase, phase)


def experiment_status_display(status: str | None) -> str:
    """Return Russian display name for experiment status."""
    if status is None:
        return "нет данных"
    return _STATUS_MAP.get(status, status)


def ru_bool(value: bool | None) -> str:
    """Render a boolean as Russian да/нет, or неизвестно for None."""
    if value is None:
        return "неизвестно"
    return "да" if value else "нет"
