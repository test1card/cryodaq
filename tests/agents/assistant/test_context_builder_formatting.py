"""F-BotPolish — ContextBuilder float formatting + sanity hints (Stage 2/3)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cryodaq.agents.assistant.live.context_builder import (
    ContextBuilder,
    _build_anomaly_hint_text,
    _detect_implausible,
    _format_value_for_prompt,
    _format_values_dict,
    _is_pressure_channel,
)

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
    """Cycle-2 fix for Codex finding on commit 53981a1: a pressure value
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
