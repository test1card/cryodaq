"""Russian display-name helpers shared across engine and assistant process.

B1 (agents/ process extraction): ``notifications/telegram_commands.py``
lives in the engine process and needs ``phase_display_name`` for its
``/status`` command, but the canonical copy used to live under
``agents/assistant/query/ru_labels.py`` — importing it there pulled the
whole assistant package tree into the engine process. Moved here (no
agents/ dependency) so the engine stays clean; ``agents/assistant/query/ru_labels``
re-exports these for its existing internal callers.
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
