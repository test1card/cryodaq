"""v0.55.5 — hourly summary digest invariants.

PART D extends PeriodicReportContext with:
- physics_alarm_entries / sensor_health_alarm_entries split
- sensor_health_summary snapshot from SensorDiagnosticsEngine
- to_template_dict() exposing physics_alarms_section, sensor_health_section,
  sensor_health_alarms_section
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.assistant.live.context_builder import (
    ContextBuilder,
    _is_sensor_health_alarm_entry,
)


def _entry(
    message: str,
    tags: tuple[str, ...] = (),
    source: str = "auto",
    ts: datetime | None = None,
) -> MagicMock:
    e = MagicMock()
    e.timestamp = ts or datetime(2026, 5, 7, 12, 0, 0, tzinfo=UTC)
    e.message = message
    e.tags = tags
    e.source = source
    return e


def _builder(
    entries: list,
    sensor_summary: object | None = None,
    experiment_id: str | None = "exp-001",
) -> ContextBuilder:
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=entries)
    em = MagicMock()
    em.active_experiment_id = experiment_id
    em.get_current_phase = MagicMock(return_value="COOL")
    provider = (lambda: sensor_summary) if sensor_summary is not None else None
    return ContextBuilder(reader, em, sensor_diag_provider=provider)


# ---------------------------------------------------------------------------
# Classification helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tags,message,expected",
    [
        # Physics alarms — operator sees these in alarms section.
        (("auto", "alarm", "vacuum_loss_cold"), "ПОТЕРЯ ВАКУУМА", False),
        (("auto", "alarm", "cooldown_alarm"), "Отклонение от траектории", False),
        (("auto", "alarm", "calibrated_sensor_fault"), "Т11: 360 K — fault", False),
        # Sensor-health alarms — operator sees these only in digest counts.
        (("auto", "alarm", "sensor_fault"), "Датчик Т7: 400 K — вне диапазона", True),
        (("auto", "alarm", "sensor_fault_intermittent"), "скачки за 0/350 K", True),
        (("auto", "alarm", "diag:T16"), "Excessive noise", True),
        (("auto", "alarm", "diag_T1"), "noise", True),
    ],
)
def test_classifier_routes_alarm_correctly(
    tags: tuple[str, ...], message: str, expected: bool
) -> None:
    e = _entry(message, tags=tags)
    assert _is_sensor_health_alarm_entry(e) is expected


# ---------------------------------------------------------------------------
# Context split
# ---------------------------------------------------------------------------


async def test_alarm_split_physics_vs_sensor_health() -> None:
    entries = [
        _entry("ПОТЕРЯ ВАКУУМА", ("auto", "alarm", "vacuum_loss_cold")),
        _entry("Датчик Т7: 400 K — вне диапазона", ("auto", "alarm", "sensor_fault")),
        _entry("Excessive noise", ("auto", "alarm", "diag:T1")),
    ]
    cb = _builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)

    assert len(ctx.alarm_entries) == 3, "all 3 still tagged 'alarm'"
    assert len(ctx.physics_alarm_entries) == 1
    assert len(ctx.sensor_health_alarm_entries) == 2


# ---------------------------------------------------------------------------
# Sensor health snapshot
# ---------------------------------------------------------------------------


def _summary(total=20, healthy=18, warning=2, critical=0, worst="Т7", score=55):
    s = MagicMock()
    s.total_channels = total
    s.healthy = healthy
    s.warning = warning
    s.critical = critical
    s.worst_channel = worst
    s.worst_score = score
    s.worst_flags = []
    return s


async def test_sensor_health_summary_passes_through() -> None:
    cb = _builder([], sensor_summary=_summary())
    ctx = await cb.build_periodic_report_context(window_minutes=60)
    assert ctx.sensor_health_summary is not None
    assert ctx.sensor_health_summary.total_channels == 20


async def test_template_dict_exposes_sensor_health_section() -> None:
    cb = _builder([], sensor_summary=_summary(warning=4, worst="Т7", score=42))
    ctx = await cb.build_periodic_report_context(window_minutes=60)
    td = ctx.to_template_dict()
    assert "sensor_health_section" in td
    section = td["sensor_health_section"]
    # Aggregate counts must be present in the digest line.
    assert "ОК 18" in section or "OK" in section.upper()
    assert "ПРЕД 4" in section
    assert "КРИТ 0" in section
    # Worst-channel callout when warnings/criticals present.
    assert "Т7" in section


async def test_template_dict_exposes_physics_only_alarms_section() -> None:
    entries = [
        _entry("ПОТЕРЯ ВАКУУМА", ("auto", "alarm", "vacuum_loss_cold")),
        _entry("Датчик Т7: 400 K", ("auto", "alarm", "sensor_fault")),
    ]
    cb = _builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)
    td = ctx.to_template_dict()
    assert "vacuum_loss_cold" not in td["physics_alarms_section"], (
        "alarm_id is a tag, not a message — message field carries the human text"
    )
    assert "ПОТЕРЯ ВАКУУМА" in td["physics_alarms_section"]
    # Sensor-health entries don't bleed into the physics section.
    assert "Датчик Т7" not in td["physics_alarms_section"]
    # … and the dedicated sensor-health section carries them.
    assert "Датчик Т7" in td["sensor_health_alarms_section"]


async def test_template_dict_handles_no_sensor_provider() -> None:
    cb = _builder([])
    ctx = await cb.build_periodic_report_context(window_minutes=60)
    td = ctx.to_template_dict()
    assert td["sensor_health_section"] == "нет данных"


async def test_template_dict_handles_empty_sensor_summary() -> None:
    cb = _builder([], sensor_summary=_summary(total=0, healthy=0, warning=0, critical=0))
    ctx = await cb.build_periodic_report_context(window_minutes=60)
    td = ctx.to_template_dict()
    assert td["sensor_health_section"] == "нет данных"


# ---------------------------------------------------------------------------
# Skip-if-idle still works (regression guard for v0.55.5 changes)
# ---------------------------------------------------------------------------


async def test_total_event_count_unchanged_by_split() -> None:
    """The split is a view, not a re-count — total_event_count must stay accurate."""
    entries = [
        _entry("ПОТЕРЯ ВАКУУМА", ("auto", "alarm", "vacuum_loss_cold")),
        _entry("Датчик Т7", ("auto", "alarm", "sensor_fault")),
        _entry("Phase → COOL", ("auto", "phase_transition")),
    ]
    cb = _builder(entries)
    ctx = await cb.build_periodic_report_context(window_minutes=60)
    assert ctx.total_event_count == 3
