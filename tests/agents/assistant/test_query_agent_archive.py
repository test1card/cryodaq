"""F33 — AssistantQueryAgent format-prompt routing for archive categories.

We exercise the pure ``_format_dispatch`` path: feed each new
``QueryCategory`` plus a hand-crafted data dict matching what
``QueryRouter`` produces, and assert the rendered prompt contains the
expected operator-facing text. No Ollama call is made.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cryodaq.agents.assistant.live.agent import AssistantConfig
from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
from cryodaq.agents.assistant.query.schemas import (
    AlarmHistoryResult,
    ArchiveDetailResult,
    ArchiveListResult,
    QueryAdapters,
    QueryCategory,
)


@pytest.fixture
def agent() -> AssistantQueryAgent:
    return AssistantQueryAgent(
        ollama_client=MagicMock(),
        audit_logger=MagicMock(),
        config=AssistantConfig(brand_name="Гемма"),
        adapters=QueryAdapters(
            broker_snapshot=MagicMock(),
            cooldown=MagicMock(),
            vacuum=MagicMock(),
            sqlite=MagicMock(),
            alarms=MagicMock(),
            experiment=MagicMock(),
            composite=MagicMock(),
            archive=MagicMock(),
        ),
    )


# ---------------------------------------------------------------------------
# ARCHIVE_LIST
# ---------------------------------------------------------------------------


def test_archive_list_renders_entries(agent: AssistantQueryAgent) -> None:
    result = ArchiveListResult(
        entries=[
            {
                "experiment_id": "exp-1",
                "title": "Detector cooldown",
                "sample": "детектор-А",
                "operator": "Иванов",
                "start_time": "2025-12-01T09:00:00+00:00",
                "status": "completed",
            }
        ],
        total_count=1,
        filter_summary="за последние 7 дней",
    )
    prompt = agent._format_dispatch(
        "какие эксперименты на этой неделе",
        QueryCategory.ARCHIVE_LIST,
        {"archive_list": result},
    )
    assert "exp-1" in prompt
    assert "Detector cooldown" in prompt
    assert "Иванов" in prompt
    assert "за последние 7 дней" in prompt


def test_archive_list_empty_renders_explicit_marker(agent: AssistantQueryAgent) -> None:
    result = ArchiveListResult(entries=[], total_count=0, filter_summary="за последние 7 дней")
    prompt = agent._format_dispatch(
        "архив за неделю", QueryCategory.ARCHIVE_LIST, {"archive_list": result}
    )
    assert "(нет записей за выбранный период)" in prompt


def test_archive_list_none_renders_adapter_unavailable(agent: AssistantQueryAgent) -> None:
    prompt = agent._format_dispatch(
        "архив", QueryCategory.ARCHIVE_LIST, {"archive_list": None}
    )
    assert "адаптер архива не сконфигурирован" in prompt


# ---------------------------------------------------------------------------
# ARCHIVE_DETAIL
# ---------------------------------------------------------------------------


def test_archive_detail_renders_phases_and_cooldown(agent: AssistantQueryAgent) -> None:
    result = ArchiveDetailResult(
        experiment_id="exp-1",
        sample="детектор-А",
        operator="Иванов",
        status="completed",
        started_at="2025-12-01T08:00:00+00:00",
        ended_at="2025-12-02T04:00:00+00:00",
        duration_h=20.0,
        phases=[
            {
                "phase": "cooldown",
                "started_at": "2025-12-01T09:00",
                "ended_at": "2025-12-01T19:00",
            },
        ],
        cooldown_metrics={
            "started_at": "2025-12-01T09:00",
            "ended_at": "2025-12-01T19:00",
        },
    )
    prompt = agent._format_dispatch(
        "детали последнего",
        QueryCategory.ARCHIVE_DETAIL,
        {"archive_detail": result, "experiment_id": "exp-1"},
    )
    assert "exp-1" in prompt
    assert "детектор-А" in prompt
    assert "20ч 0мин" in prompt
    assert "cooldown" in prompt
    assert "2025-12-01T09:00" in prompt


def test_archive_detail_none_renders_not_found(agent: AssistantQueryAgent) -> None:
    prompt = agent._format_dispatch(
        "детали exp-X",
        QueryCategory.ARCHIVE_DETAIL,
        {"archive_detail": None, "experiment_id": "exp-X"},
    )
    assert "exp-X" in prompt
    assert "не зафиксировано" in prompt or "—" in prompt


def test_archive_detail_missing_duration_renders_unknown(agent: AssistantQueryAgent) -> None:
    result = ArchiveDetailResult(
        experiment_id="exp-1",
        sample="A",
        operator="Op",
        status="aborted",
        started_at="2025-12-01T08:00",
        ended_at=None,
        duration_h=None,
        phases=[],
        cooldown_metrics=None,
    )
    prompt = agent._format_dispatch(
        "детали exp-1",
        QueryCategory.ARCHIVE_DETAIL,
        {"archive_detail": result, "experiment_id": "exp-1"},
    )
    assert "не зафиксировано" in prompt
    assert "(нет данных)" in prompt
    assert "(нет фазы cooldown в архиве этого эксперимента)" in prompt


# ---------------------------------------------------------------------------
# ALARM_HISTORY
# ---------------------------------------------------------------------------


def test_alarm_history_renders_breakdown(agent: AssistantQueryAgent) -> None:
    result = AlarmHistoryResult(
        window_description="за последние 7 дней",
        triggered_count=4,
        cleared_count=2,
        by_alarm_id={"overheat": 3, "vacuum_loss": 1},
    )
    prompt = agent._format_dispatch(
        "сколько раз сработал overheat за неделю",
        QueryCategory.ALARM_HISTORY,
        {"alarm_history": result},
    )
    assert "overheat ×3" in prompt
    assert "vacuum_loss ×1" in prompt
    assert "Сработано: 4" in prompt
    assert "Снято: 2" in prompt


def test_alarm_history_empty_renders_quiet_marker(agent: AssistantQueryAgent) -> None:
    result = AlarmHistoryResult(
        window_description="за последние 7 дней",
        triggered_count=0,
        cleared_count=0,
        by_alarm_id={},
    )
    prompt = agent._format_dispatch(
        "тревоги за неделю",
        QueryCategory.ALARM_HISTORY,
        {"alarm_history": result},
    )
    assert "(тревог не было)" in prompt


def test_alarm_history_none_renders_adapter_unavailable(
    agent: AssistantQueryAgent,
) -> None:
    prompt = agent._format_dispatch(
        "тревоги",
        QueryCategory.ALARM_HISTORY,
        {"alarm_history": None},
    )
    assert "адаптер архива не сконфигурирован" in prompt
