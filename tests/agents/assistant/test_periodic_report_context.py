"""Tests for PeriodicReportContext and build_periodic_report_context (F29)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.live.context_builder import ContextBuilder
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine


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
    diagnostics = SensorDiagnosticsEngine()
    return ContextBuilder(reader, em, sensor_diag_provider=diagnostics.get_summary)


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


async def test_periodic_report_context_phase_tag_classified_correctly() -> None:
    """Engine logs phase events with tag 'phase'; must appear in phase_entries not other."""
    entries = [
        _make_entry("Фаза: → COOL", ("auto", "phase")),
    ]
    cb = _make_context_builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert len(ctx.phase_entries) == 1
    assert len(ctx.other_entries) == 0
    tmpl = ctx.to_template_dict()
    assert "Фаза:" in tmpl["phase_transitions_section"]


async def test_periodic_report_context_read_failure_sets_flag() -> None:
    """SQLite failure must set context_read_failed=True, not silently return empty."""
    from unittest.mock import AsyncMock, MagicMock

    reader = MagicMock()
    reader.get_operator_log = AsyncMock(side_effect=RuntimeError("db locked"))
    em = MagicMock()
    em.active_experiment_id = None
    cb = ContextBuilder(reader, em)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert ctx.context_read_failed is True
    assert ctx.total_event_count == 0
    template = ctx.to_template_dict()
    assert template["total_event_count"] != "0"
    assert template["alarms_section"] != "(нет)"
    assert "недоступ" in template["total_event_count"]


async def test_periodic_report_context_marks_saturated_source_and_hidden_critical_section_content() -> None:
    """A 50-row read and a 10-row section cap cannot look complete or empty."""
    entries = [_make_entry(f"Warning {number}", ("auto", "alarm")) for number in range(10)]
    entries.append(_make_entry("CRITICAL hidden beyond display cap", ("auto", "alarm")))
    entries.extend(_make_entry(f"other {number}", ("auto", "leak_rate")) for number in range(39))
    cb = _make_context_builder(entries)

    ctx = await cb.build_periodic_report_context(window_minutes=60)

    template = ctx.to_template_dict()
    assert "50+" in template["total_event_count"]
    assert "непол" in template["source_completeness"]
    assert "CRITICAL hidden beyond display cap" not in template["physics_alarms_section"]
    assert (
        "Показано 10 из 11 записей; пропущенные события могут включать критические."
        in template["physics_alarms_section"]
    )
    assert ctx.source_saturated is True


async def test_periodic_report_context_warns_when_display_cap_hides_critical_without_source_saturation() -> None:
    """A locally truncated section must disclose that its omitted row may be critical."""
    entries = [_make_entry(f"Warning {number}", ("auto", "alarm")) for number in range(10)]
    entries.append(_make_entry("CRITICAL hidden beyond display cap", ("auto", "alarm")))
    cb = _make_context_builder(entries)

    ctx = await cb.build_periodic_report_context(window_minutes=60)

    template = ctx.to_template_dict()
    assert template["total_event_count"] == "11"
    assert template["source_completeness"] == "полный"
    assert "CRITICAL hidden beyond display cap" not in template["physics_alarms_section"]
    assert (
        "Показано 10 из 11 записей; пропущенные события могут включать критические."
        in template["physics_alarms_section"]
    )


async def test_periodic_report_context_distinguishes_missing_diagnostics_provider_from_empty_summary() -> None:
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    em = MagicMock()
    em.active_experiment_id = None
    missing_provider = ContextBuilder(reader, em)

    missing = await missing_provider.build_periodic_report_context(window_minutes=60)

    assert missing.context_read_failed is True
    assert "недоступ" in missing.to_template_dict()["sensor_health_section"]

    diagnostics = SensorDiagnosticsEngine()
    known_empty = ContextBuilder(reader, em, sensor_diag_provider=diagnostics.get_summary)
    empty = await known_empty.build_periodic_report_context(window_minutes=60)

    assert empty.context_read_failed is False
    assert empty.to_template_dict()["sensor_health_section"] == "нет данных"


async def test_periodic_report_context_rejects_failed_or_malformed_diagnostics_provider() -> None:
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    em = MagicMock()
    em.active_experiment_id = None

    for provider in (
        MagicMock(side_effect=RuntimeError("diagnostics cache unavailable")),
        lambda: {"total_channels": 1, "healthy": 1, "warning": 1, "critical": 0},
    ):
        context = await ContextBuilder(reader, em, sensor_diag_provider=provider).build_periodic_report_context(
            window_minutes=60
        )
        assert context.context_read_failed is True
        assert "недоступ" in context.to_template_dict()["total_event_count"]


async def test_periodic_report_context_missing_log_capability_is_unavailable() -> None:
    """A reader without the allowlisted method is not a known-empty window."""
    em = MagicMock()
    em.active_experiment_id = None
    cb = ContextBuilder(object(), em)

    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert ctx.context_read_failed is True
    assert "недоступ" in ctx.to_template_dict()["total_event_count"]
