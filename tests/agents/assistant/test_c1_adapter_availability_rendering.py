"""Unavailable adapter results must remain unavailable in formatter input."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
from cryodaq.agents.assistant.query.schemas import (
    AlarmHistoryResult,
    AlarmStatusResult,
    ArchiveListResult,
    CompositeStatus,
    CooldownETA,
    ExperimentStatus,
    KnowledgeQueryResult,
    RangeStats,
    VacuumETA,
)


def _unavailable(result_type, *args, **kwargs):
    return result_type(*args, available=False, stale=True, reason="engine unavailable", **kwargs)


@pytest.mark.parametrize(
    ("formatter", "data"),
    [
        ("_fmt_eta_cooldown", {"cooldown_eta": _unavailable(CooldownETA, 0, 0, 0, 0, "", 0, False)}),
        ("_fmt_eta_vacuum", {"vacuum_eta": _unavailable(VacuumETA, None, None, 1e-6, "", 0)}),
        (
            "_fmt_range_stats",
            {"range_stats": {"P": _unavailable(RangeStats, "P", 60, 0, 0, 0, 0, 0)}, "window_minutes": 60},
        ),
        ("_fmt_phase_info", {"experiment_status": _unavailable(ExperimentStatus, "", None, None, None)}),
        ("_fmt_alarm_status", {"alarm_result": _unavailable(AlarmStatusResult)}),
        (
            "_fmt_composite",
            {
                "composite_status": _unavailable(
                    CompositeStatus,
                    datetime.now(UTC),
                    None,
                    None,
                    None,
                    [],
                    {},
                    None,
                )
            },
        ),
        ("_fmt_archive_list", {"archive_list": _unavailable(ArchiveListResult)}),
        ("_fmt_alarm_history", {"alarm_history": _unavailable(AlarmHistoryResult, "")}),
        ("_fmt_knowledge_query", {"knowledge_query": _unavailable(KnowledgeQueryResult, "q"), "query": "q"}),
    ],
)
def test_formatter_names_unavailable_result(formatter: str, data: dict) -> None:
    agent = object.__new__(AssistantQueryAgent)
    prompt = getattr(agent, formatter)("query", data)
    assert "недоступ" in prompt.lower()
    assert "engine unavailable" in prompt
