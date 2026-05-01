"""Tests for Track E — Russian-fication of labels and prompts.

Covers ru_labels helper functions and no-English-leakage in FORMAT_* prompts.
"""

from __future__ import annotations

import re

from cryodaq.agents.assistant.query import prompts as p
from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
from cryodaq.agents.assistant.query.ru_labels import (
    experiment_status_display,
    phase_display_name,
    ru_bool,
)

# ---------------------------------------------------------------------------
# ru_labels — phase_display_name
# ---------------------------------------------------------------------------


def test_phase_display_name_cooldown() -> None:
    assert phase_display_name("cooldown") == "захолаживание"


def test_phase_display_name_warmup() -> None:
    assert phase_display_name("warmup") == "отогрев"


def test_phase_display_name_measurement() -> None:
    assert phase_display_name("measurement") == "измерение"


def test_phase_display_name_preparation() -> None:
    assert phase_display_name("preparation") == "подготовка"


def test_phase_display_name_vacuum() -> None:
    assert phase_display_name("vacuum") == "откачка вакуума"


def test_phase_display_name_teardown() -> None:
    assert phase_display_name("teardown") == "разборка"


def test_phase_display_name_passthrough_unknown() -> None:
    assert phase_display_name("unknown_phase") == "unknown_phase"


def test_phase_display_name_none() -> None:
    assert phase_display_name(None) == "нет данных"


# ---------------------------------------------------------------------------
# ru_labels — experiment_status_display
# ---------------------------------------------------------------------------


def test_experiment_status_display_running() -> None:
    assert experiment_status_display("running") == "работает"


def test_experiment_status_display_completed() -> None:
    assert experiment_status_display("completed") == "завершён"


def test_experiment_status_display_aborted() -> None:
    assert experiment_status_display("aborted") == "прерван"


# ---------------------------------------------------------------------------
# ru_labels — ru_bool
# ---------------------------------------------------------------------------


def test_ru_bool_true() -> None:
    assert ru_bool(True) == "да"


def test_ru_bool_false() -> None:
    assert ru_bool(False) == "нет"


def test_ru_bool_none() -> None:
    assert ru_bool(None) == "неизвестно"


# ---------------------------------------------------------------------------
# Track E — prompt Russian-fication verification
# ---------------------------------------------------------------------------

_ALLOWED_ENGLISH = {
    # Units
    "K", "mbar", "Pa", "Hz", "ETA",
    # Technical proper nouns / abbreviations
    "JSON", "LaTeX", "Unicode", "UUID", "API", "GUI", "F33", "v0",
    # Format parameter names in {braces} — excluded by regex
    # Version numbers like v0.49.0 — excluded by stripping {braces}
    "CryoDAQ",
    # Acceptable abbreviations
    "R", "min", "max", "URL", "Юникод",
}

_PROMPTS_TO_CHECK = [
    ("FORMAT_RESPONSE_SYSTEM", p.FORMAT_RESPONSE_SYSTEM),
    ("FORMAT_CURRENT_VALUE_USER", p.FORMAT_CURRENT_VALUE_USER),
    ("FORMAT_ETA_COOLDOWN_USER", p.FORMAT_ETA_COOLDOWN_USER),
    ("FORMAT_ETA_VACUUM_USER", p.FORMAT_ETA_VACUUM_USER),
    ("FORMAT_RANGE_STATS_USER", p.FORMAT_RANGE_STATS_USER),
    ("FORMAT_PHASE_INFO_USER", p.FORMAT_PHASE_INFO_USER),
    ("FORMAT_ALARM_STATUS_USER", p.FORMAT_ALARM_STATUS_USER),
    ("FORMAT_COMPOSITE_STATUS_USER", p.FORMAT_COMPOSITE_STATUS_USER),
    ("FORMAT_OUT_OF_SCOPE_HISTORICAL_USER", p.FORMAT_OUT_OF_SCOPE_HISTORICAL_USER),
    ("FORMAT_OUT_OF_SCOPE_GENERAL_USER", p.FORMAT_OUT_OF_SCOPE_GENERAL_USER),
    ("FORMAT_UNKNOWN_USER", p.FORMAT_UNKNOWN_USER),
]


def test_format_prompts_no_english_leakage() -> None:
    """FORMAT_* prompts must not contain standalone English content words."""
    violations: list[str] = []

    for name, prompt in _PROMPTS_TO_CHECK:
        # Strip Python format placeholders {var_name}
        stripped = re.sub(r"\{[^}]+\}", "", prompt)
        # Find standalone English words of 4+ chars (to avoid false positives on R², σ)
        english_words = re.findall(r"\b[A-Za-z]{4,}\b", stripped)
        leaked = [w for w in english_words if w not in _ALLOWED_ENGLISH]
        if leaked:
            violations.append(f"{name}: {leaked}")

    assert not violations, "English leakage in prompts:\n" + "\n".join(violations)


def test_eta_cooldown_uses_zaholazhivanie() -> None:
    stripped = re.sub(r"\{[^}]+\}", "", p.FORMAT_ETA_COOLDOWN_USER)
    assert "захолаживан" in stripped.lower()
    assert "cooldown" not in stripped.lower()


def test_eta_cooldown_no_ci_english() -> None:
    assert "CI 68" not in p.FORMAT_ETA_COOLDOWN_USER
    assert "доверительный" in p.FORMAT_ETA_COOLDOWN_USER


def test_composite_prompt_has_anti_pattern_guard() -> None:
    assert "НЕ начинай" in p.FORMAT_COMPOSITE_STATUS_USER
    guard = p.FORMAT_COMPOSITE_STATUS_USER
    assert "Плохой" in guard or "ПЛОХО" in guard or "НЕ ДЕЛАЙ" in guard


def test_composite_prompt_uses_prognoz_not_eta_label() -> None:
    assert "Прогноз захолаживания" in p.FORMAT_COMPOSITE_STATUS_USER


def test_composite_prompt_has_good_example() -> None:
    assert "захолаживания" in p.FORMAT_COMPOSITE_STATUS_USER


def test_eta_cooldown_fallback_uses_russian_bool() -> None:
    agent = object.__new__(AssistantQueryAgent)

    prompt = agent._fmt_eta_cooldown("когда 4К?", {"cooldown_eta": None})

    assert "Захолаживание активно: нет" in prompt
    assert "False" not in prompt


def test_range_stats_prompt_uses_russian_min_max_labels() -> None:
    assert "- Минимум:" in p.FORMAT_RANGE_STATS_USER
    assert "- Максимум:" in p.FORMAT_RANGE_STATS_USER
    assert "- Min:" not in p.FORMAT_RANGE_STATS_USER
    assert "- Max:" not in p.FORMAT_RANGE_STATS_USER
