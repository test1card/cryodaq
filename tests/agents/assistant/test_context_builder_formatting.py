"""F-BotPolish — ContextBuilder float formatting + sanity hints (Stage 2/3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.assistant.live.context_builder import (
    ContextBuilder,
    _build_anomaly_hint_text,
    _detect_implausible,
    _format_sensor_health_section,
    _format_value_for_prompt,
    _format_values_dict,
    _is_pressure_channel,
    is_valid_sensor_health_summary,
)
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine

# ---------------------------------------------------------------------------
# _format_value_for_prompt
# ---------------------------------------------------------------------------


def test_temperature_rounded_to_one_decimal():
    assert _format_value_for_prompt(4.347123456789, "Т1") == "4.3"
    assert _format_value_for_prompt(77.5, "Т12") == "77.5"
    # Latin "T" path covered defensively.
    assert _format_value_for_prompt(294.0, "T_room") == "294.0"


def test_pressure_rendered_as_two_decimal_places_scientific():
    """Pressure values use {v:.2e} — two decimal places in scientific notation (e.g. 1.86e-06)."""
    assert _format_value_for_prompt(1.86e-06, "P_main") == "1.86e-06"
    # 12-digit operator-supplied value collapses to scientific form.
    assert _format_value_for_prompt(0.000000123456, "P_main") == "1.23e-07"


def test_pressure_mid_magnitude_still_scientific():
    """Cycle-2 fix from commit 53981a1: a pressure value
    that lands between the magnitude bands (1e-3 ≤ |v| ≤ 1e6) used to
    collapse to ``"0.00"``. Channel-name detection now wins over the
    magnitude fallback."""
    assert _format_value_for_prompt(1e-3, "P_main") == "1.00e-03"
    assert _format_value_for_prompt(5e-3, "P_main") == "5.00e-03"
    assert _format_value_for_prompt(0.5, "P_main") == "5.00e-01"


def test_pressure_detected_by_unit_when_channel_unknown():
    """Unit-based detection covers payloads where the channel id is opaque
    but the unit is the canonical Cyrillic «мбар»."""
    assert _format_value_for_prompt(1.5e-3, channel="anon", unit="мбар") == "1.50e-03"
    assert _format_value_for_prompt(1.5e-3, channel="anon", unit="mbar") == "1.50e-03"


def test_pressure_channel_patterns():
    """Common pressure-channel names should all be detected."""
    assert _is_pressure_channel("P_main")
    assert _is_pressure_channel("p_compressor")  # lowercase
    assert _is_pressure_channel("MV00")
    assert _is_pressure_channel("V1")
    assert _is_pressure_channel("VSP63D/pressure")
    assert _is_pressure_channel("Anon/mbar")
    # Non-pressure channels.
    assert not _is_pressure_channel("Т12")
    assert not _is_pressure_channel("smua/voltage")
    assert not _is_pressure_channel("")


def test_default_two_decimals_for_other_channels():
    assert _format_value_for_prompt(5.123456, "smua/voltage") == "5.12"
    assert _format_value_for_prompt(-2.0, "Keithley_A") == "-2.00"


def test_non_numeric_value_falls_back_to_str():
    assert _format_value_for_prompt("OFFLINE", "Т1") == "OFFLINE"
    assert _format_value_for_prompt(None, "Т1") == "None"


def test_format_values_dict_applies_per_channel():
    out = _format_values_dict({"Т1": 4.3471, "P_main": 1.86e-06, "x": 1.234})
    assert out == {"Т1": "4.3", "P_main": "1.86e-06", "x": "1.23"}


# ---------------------------------------------------------------------------
# _detect_implausible
# ---------------------------------------------------------------------------


def test_detect_implausible_flags_extreme_high_temperature():
    hint = _detect_implausible("Т1", 948.0)
    assert hint is not None
    assert "сбой сенсора" in hint


def test_detect_implausible_flags_extreme_low_temperature():
    hint = _detect_implausible("Т1", -100.0)
    assert hint is not None
    assert "физически невозможно" in hint


def test_detect_implausible_passes_normal_cryo():
    assert _detect_implausible("Т1", 77.0) is None
    assert _detect_implausible("Т12", 4.5) is None
    assert _detect_implausible("Т12", 0.0) is None


def test_detect_implausible_skips_non_cryo_channels():
    # smua/voltage = 948 V is fine — not a cryo channel.
    assert _detect_implausible("smua/voltage", 948.0) is None


def test_detect_implausible_skips_non_kelvin_units():
    assert _detect_implausible("Т1", 948.0, unit="Ом") is None


def test_detect_implausible_handles_non_numeric():
    assert _detect_implausible("Т1", "OFFLINE") is None
    assert _detect_implausible("Т1", None) is None


# ---------------------------------------------------------------------------
# _build_anomaly_hint_text
# ---------------------------------------------------------------------------


def test_anomaly_hint_text_lists_only_implausible():
    text = _build_anomaly_hint_text({"Т1": 948.0, "Т12": 4.5})
    assert "Т1" in text
    assert "948.0 K" in text
    assert "Т12" not in text  # 4.5 K is normal


def test_anomaly_hint_text_empty_when_all_normal():
    assert _build_anomaly_hint_text({"Т1": 77.0, "Т12": 4.5}) == ""


# ---------------------------------------------------------------------------
# build_alarm_context integration
# ---------------------------------------------------------------------------


def _build_em_stub():
    em = MagicMock()
    em.active_experiment_id = "exp-1"
    em.get_current_phase.return_value = "cooldown"
    em.get_phase_history.return_value = []
    return em


@pytest.mark.asyncio
async def test_build_alarm_context_formats_values():
    builder = ContextBuilder(sqlite_reader=MagicMock(), experiment_manager=_build_em_stub())
    payload = {
        "alarm_id": "cold_too_warm",
        "level": "WARNING",
        "channels": ["Т12"],
        "values": {"Т12": 4.347123456789},
    }
    ctx = await builder.build_alarm_context(payload)
    # Values are pre-formatted strings now (1-decimal Kelvin) — the prompt
    # template stringifies the dict and gets compact output.
    assert ctx.values == {"Т12": "4.3"}


@pytest.mark.asyncio
async def test_build_alarm_context_emits_implausibility_hint():
    builder = ContextBuilder(sqlite_reader=MagicMock(), experiment_manager=_build_em_stub())
    payload = {
        "alarm_id": "sensor_fault",
        "level": "CRITICAL",
        "channels": ["Т1"],
        "values": {"Т1": 948.0},
    }
    ctx = await builder.build_alarm_context(payload)
    assert "сбой сенсора" in ctx.recent_readings_text
    assert "Т1" in ctx.recent_readings_text


@pytest.mark.asyncio
async def test_build_alarm_context_keeps_stub_when_values_normal():
    builder = ContextBuilder(sqlite_reader=MagicMock(), experiment_manager=_build_em_stub())
    payload = {
        "alarm_id": "ok_event",
        "level": "WARNING",
        "channels": ["Т12"],
        "values": {"Т12": 4.5},
    }
    ctx = await builder.build_alarm_context(payload)
    # No anomaly → falls back to existing stub text, not an empty string.
    assert ctx.recent_readings_text == "нет данных"


@pytest.mark.asyncio
async def test_shift_handover_context_reads_required_window_and_alarm_snapshot():
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(
        return_value=[
            SimpleNamespace(
                timestamp=datetime(2026, 5, 1, 19, 30, tzinfo=UTC),
                message="CRITICAL alarm was acknowledged",
            )
        ]
    )
    builder = ContextBuilder(reader, _build_em_stub())
    builder._alarm_reader = MagicMock()
    builder._alarm_reader.active = AsyncMock(
        return_value=SimpleNamespace(active=[SimpleNamespace(alarm_id="T1-high", level="CRITICAL", channels=["T1"])])
    )

    context = await builder.build_shift_handover_context({"shift_duration_h": 8})

    reader.get_operator_log.assert_awaited_once()
    request = reader.get_operator_log.call_args.kwargs
    assert request["end_time"] - request["start_time"] == timedelta(hours=8)
    assert "CRITICAL: T1-high (T1)" in context.active_alarms
    assert "CRITICAL alarm was acknowledged" in context.recent_events


@pytest.mark.asyncio
async def test_shift_handover_context_keeps_known_empty_distinct_from_unavailable():
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    builder = ContextBuilder(reader, _build_em_stub())
    builder._alarm_reader = MagicMock()
    builder._alarm_reader.active = AsyncMock(return_value=SimpleNamespace(active=[]))

    context = await builder.build_shift_handover_context({"shift_duration_h": 8})

    assert context.active_alarms == "нет активных тревог"
    assert context.recent_events == "нет событий за смену"


@pytest.mark.asyncio
async def test_shift_handover_context_prioritizes_critical_alarm_within_display_bound():
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    alarm_reader = MagicMock()
    alarm_reader.active = AsyncMock(
        return_value=SimpleNamespace(
            active=[
                *[
                    SimpleNamespace(alarm_id=f"warning-{number:02d}", level="WARNING", channels=[])
                    for number in range(10, 0, -1)
                ],
                SimpleNamespace(alarm_id="unknown-late", level="ESCALATED", channels=[]),
                SimpleNamespace(alarm_id="critical-late", level="CRITICAL", channels=[]),
            ]
        )
    )
    builder = ContextBuilder(reader, _build_em_stub())
    builder._alarm_reader = alarm_reader

    context = await builder.build_shift_handover_context({"shift_duration_h": 8})

    assert context.active_alarms.splitlines() == [
        "Показано 10 из 12 активных тревог:",
        "- CRITICAL: critical-late",
        "- ESCALATED: unknown-late",
        *[f"- WARNING: warning-{number:02d}" for number in range(1, 9)],
    ]


@pytest.mark.asyncio
async def test_shift_handover_context_keeps_critical_ahead_of_lexically_earlier_unknown_levels():
    """An unknown level is pessimistic, but cannot displace CRITICAL at the display cap."""
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    alarm_reader = MagicMock()
    alarm_reader.active = AsyncMock(
        return_value=SimpleNamespace(
            active=[
                *[
                    SimpleNamespace(alarm_id=f"unknown-{number:02d}", level="ALARM", channels=[])
                    for number in range(10)
                ],
                SimpleNamespace(alarm_id="critical-late", level="CRITICAL", channels=[]),
            ]
        )
    )
    builder = ContextBuilder(reader, _build_em_stub())
    builder._alarm_reader = alarm_reader

    context = await builder.build_shift_handover_context({"shift_duration_h": 8})

    shown = context.active_alarms.splitlines()
    assert shown[0] == "Показано 10 из 11 активных тревог:"
    assert shown[1] == "- CRITICAL: critical-late"
    assert "- ALARM: unknown-09" not in shown


@pytest.mark.asyncio
@pytest.mark.parametrize(("entry_count", "total"), [(11, "11"), (12, "12"), (50, "50+")])
async def test_shift_handover_context_reports_displayed_event_count(entry_count: int, total: str):
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(
        return_value=[
            SimpleNamespace(
                timestamp=datetime(2026, 5, 1, 19, 30, tzinfo=UTC),
                message="CRITICAL event beyond display cap" if number == 11 else f"event-{number:02d}",
            )
            for number in range(1, entry_count + 1)
        ]
    )
    builder = ContextBuilder(reader, _build_em_stub())
    builder._alarm_reader = MagicMock()
    builder._alarm_reader.active = AsyncMock(return_value=SimpleNamespace(active=[]))

    context = await builder.build_shift_handover_context({"shift_duration_h": 8})

    expected = f"Показано 10 из {total} событий"
    assert context.recent_events.splitlines()[0].startswith(expected)
    assert "пропущенные события могут включать критические" in context.recent_events
    assert context.recent_events.count("Показано") == 1
    assert "event-10" in context.recent_events
    assert "CRITICAL event beyond display cap" not in context.recent_events


@pytest.mark.asyncio
@pytest.mark.parametrize("shift_duration_h", [True, 0, -1, float("nan"), float("inf"), 169])
async def test_shift_handover_context_rejects_invalid_duration_before_reading_window(shift_duration_h: object):
    reader = MagicMock()
    reader.get_operator_log = AsyncMock()
    alarm_reader = MagicMock()
    alarm_reader.active = AsyncMock()
    builder = ContextBuilder(reader, _build_em_stub(), alarm_reader=alarm_reader)

    context = await builder.build_shift_handover_context({"shift_duration_h": shift_duration_h})

    assert context.context_unavailable is True
    reader.get_operator_log.assert_not_awaited()
    alarm_reader.active.assert_not_awaited()


@pytest.mark.asyncio
async def test_shift_handover_context_rejects_huge_integer_duration_before_reading_window() -> None:
    reader = MagicMock()
    reader.get_operator_log = AsyncMock()
    alarm_reader = MagicMock()
    alarm_reader.active = AsyncMock()
    builder = ContextBuilder(reader, _build_em_stub(), alarm_reader=alarm_reader)

    context = await builder.build_shift_handover_context({"shift_duration_h": 10**10_000})

    assert context.context_unavailable is True
    reader.get_operator_log.assert_not_awaited()
    alarm_reader.active.assert_not_awaited()


def _real_sensor_summary(*, include_critical: bool) -> object:
    engine = SensorDiagnosticsEngine()
    engine.set_channel_cold_map({"T1": True, "T16": False})
    for index in range(20):
        engine.push("T16", index * 0.5, 298.0)
        if include_critical:
            engine.push("T1", index * 0.5, 380.0)
    engine.update()
    return engine.get_summary()


def test_sensor_health_summary_accepts_real_unscored_warm_reference() -> None:
    summary = _real_sensor_summary(include_critical=False)

    assert is_valid_sensor_health_summary(summary)
    section = _format_sensor_health_section(summary)
    assert "всего 1" in section
    assert "не оценено 1" in section


def test_sensor_health_summary_preserves_real_critical_with_warm_reference() -> None:
    summary = _real_sensor_summary(include_critical=True)

    assert is_valid_sensor_health_summary(summary)
    section = _format_sensor_health_section(summary)
    assert "КРИТ 1" in section
    assert "не оценено 1" in section
