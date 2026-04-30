"""Tests for PeriodicReportContext and build_periodic_report_context (F29)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.live.context_builder import ContextBuilder


def _make_entry(message: str, tags: tuple[str, ...], source: str = "auto") -> MagicMock:
    entry = MagicMock()
    entry.timestamp = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    entry.message = message
    entry.tags = tags
    entry.source = source
    return entry


def _make_context_builder(entries: list, experiment_id: str | None = "exp-001") -> ContextBuilder:
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=entries)
    em = MagicMock()
    em.active_experiment_id = experiment_id
    em.get_current_phase = MagicMock(return_value="COOL")
    return ContextBuilder(reader, em)


async def test_periodic_report_context_aggregates_window() -> None:
    entries = [
        _make_entry("Alarm fired", ("auto", "alarm", "alarm_T1")),
        _make_entry("Phase → COOL", ("auto", "phase_transition")),
        _make_entry("Experiment started", ("auto", "experiment")),
    ]
    cb = _make_context_builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert len(ctx.alarm_entries) == 1
    assert len(ctx.phase_entries) == 1
    assert len(ctx.experiment_entries) == 1
    assert ctx.total_event_count == 3
    assert ctx.active_experiment_id == "exp-001"
    assert ctx.active_experiment_phase == "COOL"


async def test_periodic_report_context_handles_empty_window() -> None:
    cb = _make_context_builder([])
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert ctx.total_event_count == 0
    assert ctx.alarm_entries == []
    assert ctx.phase_entries == []
    assert ctx.operator_entries == []


async def test_periodic_report_context_excludes_machine_log_entries() -> None:
    entries = [
        _make_entry("AI summary", ("auto", "ai", "abc123")),
        _make_entry("Manual note", (), source="operator"),
    ]
    cb = _make_context_builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    # AI entry must NOT appear in operator_entries
    assert len(ctx.operator_entries) == 1
    assert ctx.operator_entries[0].message == "Manual note"
    assert ctx.total_event_count == 1  # only the operator entry


async def test_periodic_report_context_total_count_correct() -> None:
    entries = [
        _make_entry("Alarm 1", ("auto", "alarm")),
        _make_entry("Alarm 2", ("auto", "alarm")),
        _make_entry("Phase", ("auto", "phase_transition")),
        _make_entry("Operator note", (), source="operator"),
        _make_entry("Leak rate", ("auto", "leak_rate")),
    ]
    cb = _make_context_builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert ctx.total_event_count == 5


async def test_periodic_report_context_no_experiment() -> None:
    cb = _make_context_builder([], experiment_id=None)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert ctx.active_experiment_id is None
    tmpl = ctx.to_template_dict()
    assert "нет активного" in tmpl["active_experiment_summary"]


async def test_periodic_report_context_to_template_dict_structure() -> None:
    entries = [
        _make_entry("Alarm T1 high", ("auto", "alarm")),
    ]
    cb = _make_context_builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    tmpl = ctx.to_template_dict()
    assert "active_experiment_summary" in tmpl
    assert "events_section" in tmpl
    assert "alarms_section" in tmpl
    assert "phase_transitions_section" in tmpl
    assert "operator_entries_section" in tmpl
    assert "total_event_count" in tmpl
    assert "Alarm T1 high" in tmpl["alarms_section"]
    assert tmpl["total_event_count"] == "1"


async def test_periodic_report_context_formats_calibration_section() -> None:
    entries = [
        _make_entry("T1 offset +0.02 K", ("auto", "calibration")),
    ]
    cb = _make_context_builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    tmpl = ctx.to_template_dict()
    assert "T1 offset" in tmpl["calibration_section"]
    assert "T1 offset" not in tmpl["events_section"]
    assert ctx.total_event_count == 1
