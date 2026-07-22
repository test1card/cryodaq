"""Tests for TopWatchBar persistent context strip (B.4)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui import theme
from cryodaq.gui.shell import top_watch_bar as top_watch_bar_module
from cryodaq.gui.shell.top_watch_bar import (
    _PRESENTATION_INTERVAL_MS,
    TopWatchBar,
    _format_pressure,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def mock_channel_mgr():
    mgr = MagicMock()
    mgr.get_visible_cold_channels.return_value = [
        "\u04221",
        "\u04227",
        "\u042212",
    ]
    mgr.get_all_visible.return_value = [
        "\u04221",
        "\u04227",
        "\u042212",
    ]
    mgr.get_cold_channels.return_value = [
        "\u04221",
        "\u04227",
        "\u042212",
    ]
    mgr.on_change = MagicMock()
    mgr.off_change = MagicMock()
    return mgr


def _stop_timers(bar: TopWatchBar) -> None:
    bar._fast_timer.stop()
    bar._slow_timer.stop()
    bar._channel_refresh_timer.stop()
    bar._stale_timer.stop()


def _make_reading(
    channel: str,
    value: float,
    unit: str = "K",
    *,
    timestamp: datetime | None = None,
    status: ChannelStatus = ChannelStatus.OK,
) -> Reading:
    return Reading(
        channel=channel,
        value=value,
        unit=unit,
        timestamp=timestamp or datetime.now(UTC),
        status=status,
        instrument_id="test",
    )


def test_provenance_identity_is_escaped_as_literal_tooltip_text() -> None:
    reading = Reading(
        channel="<b>channel</b>\x01",
        value=1.0,
        unit="K",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="<img src=x onerror=bad>",
    )

    detail = TopWatchBar._provenance_text(reading)
    assert "&lt;img src=x onerror=bad&gt;" in detail
    assert "&lt;b&gt;channel&lt;/b&gt;�" in detail


def test_constructs_with_channel_mgr(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    assert bar._ctx_pressure_value is not None
    assert bar._ctx_second_stage_value is not None
    assert bar._ctx_n2_plate_value is not None
    assert _PRESENTATION_INTERVAL_MS == 500
    assert bar._stale_timer.interval() == _PRESENTATION_INTERVAL_MS


def test_initial_state_shows_dashes(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    assert "\u2014" in bar._ctx_pressure_value.text()
    assert "\u2014" in bar._ctx_second_stage_value.text()
    assert "\u2014" in bar._ctx_n2_plate_value.text()
    style = bar._ctx_pressure_value.styleSheet()
    assert theme.FONT_MONO in style
    assert f"font-size: {theme.FONT_SIZE_SM}px" in style
    assert f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}" in style
    assert "Текущих данных нет" in bar._ctx_pressure_value.accessibleDescription()


def test_no_heater_cell_in_top_watch_bar(app, mock_channel_mgr):
    # Heater removed from TopWatchBar anatomy — header now shows only
    # pressure + fixed second-stage and nitrogen-plate references (plus
    # outer zones). Heater concept
    # still exists on the Keithley panel.
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    assert not hasattr(bar, "_ctx_heater_value")
    assert not hasattr(bar, "_ctx_heater_label")
    assert not hasattr(bar, "_update_heater_display")


def test_no_time_window_picker_in_top_watch_bar(app, mock_channel_mgr):
    # Picker lives on TempPlotWidget — must not surface in the header.
    from PySide6.QtWidgets import QPushButton

    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    btns = bar.findChildren(QPushButton)
    labels_to_reject = {"1мин", "1ч", "6ч", "24ч", "Всё"}
    for b in btns:
        assert b.text() not in labels_to_reject, f"unexpected time-window button: {b.text()}"
    assert not hasattr(bar, "_time_window_echo_label")
    assert not hasattr(bar, "set_time_window_echo")


def test_pressure_reading_updates_display(app, mock_channel_mgr):
    # Operator-facing unit is Cyrillic "мбар" (RULE-COPY-006).
    # Internal variable / upstream Reading.unit remains Latin "mbar"
    # because that's what the driver emits; the TopWatchBar re-labels
    # for display only.
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(_make_reading("VSP63D_1/pressure", 1.2e-3, "mbar"))
    assert bar._ctx_pressure_value.text() == "\u2014"
    bar._flush_persistent_context()
    text = bar._ctx_pressure_value.text()
    # Compact scientific — no leading zeros in exponent ("1.2e-3" not
    # "1.20e-03"). See _format_pressure.
    assert "1.2e-3" in text
    assert "\u043c\u0431\u0430\u0440" in text  # мбар


def test_physical_temperature_labels_and_channels_are_exact(app, mock_channel_mgr):
    # The fixed references name their physical locations. Arbitrary cold
    # channels like Т1 / Т7 must not populate these cells.
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    assert bar._ctx_second_stage_label.text() == "Т 2-й ступени"
    assert bar._ctx_n2_plate_label.text() == "Т плиты N₂"

    # Т12 -> second-stage cell (cold reference, ~2.9 K)
    bar.on_reading(_make_reading("\u042212 \u0420\u0435\u0444\u0435\u0440\u0435\u043d\u0446 2", 4.2))
    # Т11 -> nitrogen-plate cell (~40 K)
    bar.on_reading(_make_reading("\u042211 \u0420\u0435\u0444\u0435\u0440\u0435\u043d\u0446 1", 76.5))
    assert bar._ctx_second_stage_value.text() == "\u2014"
    assert bar._ctx_n2_plate_value.text() == "\u2014"
    bar._flush_persistent_context()
    assert "4.20" in bar._ctx_second_stage_value.text()
    assert "76.50" in bar._ctx_n2_plate_value.text()


def test_non_reference_cold_channel_ignored_for_physical_references(app, mock_channel_mgr):
    # Reading from a non-reference cold channel (e.g. Т1) must not affect
    # the fixed Т11 / Т12 physical references regardless of what other
    # channels report.
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(_make_reading("\u04221 \u041a\u0440\u0438\u043e\u0441\u0442\u0430\u0442", 4.2))
    bar.on_reading(_make_reading("\u04227 \u0414\u0435\u0442\u0435\u043a\u0442\u043e\u0440", 76.5))
    assert "\u2014" in bar._ctx_second_stage_value.text()
    assert "\u2014" in bar._ctx_n2_plate_value.text()


def test_warm_channel_ignored_for_physical_references(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(
        _make_reading(
            "\u042215 \u0412\u0430\u043a\u0443\u0443\u043c\u043d\u044b\u0439 \u043a\u043e\u0436\u0443\u0445",  # noqa: E501
            295.0,
        )
    )
    assert "\u2014" in bar._ctx_second_stage_value.text()
    assert "\u2014" in bar._ctx_n2_plate_value.text()


def test_nan_value_ignored(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(_make_reading("\u04221 X", float("nan")))
    assert "\u2014" in bar._ctx_second_stage_value.text()


def test_bounded_cut_renders_latest_source_time_and_interval_range(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    base = datetime.now(UTC) - timedelta(seconds=5)

    bar.on_reading(_make_reading("\u042212 ref", 4.20, timestamp=base))
    bar.on_reading(_make_reading("\u042212 ref", 4.55, timestamp=base + timedelta(milliseconds=100)))
    bar.on_reading(_make_reading("\u042212 ref", 4.35, timestamp=base + timedelta(milliseconds=200)))

    assert bar._ctx_second_stage_value.text() == "\u2014"
    assert len(bar._pending_vital_cuts) == 1
    assert bar._pending_vital_cuts["\u042212"].count == 3

    bar._flush_persistent_context()

    assert bar._ctx_second_stage_value.text() == "4.35 K ↕"
    detail = bar._ctx_second_stage_value.accessibleDescription()
    assert "минимум: 4.20 K" in detail
    assert "максимум: 4.55 K" in detail
    assert f"время минимума: {base.strftime('%Y-%m-%d %H:%M:%S.%f UTC')}" in detail
    maximum_time = base + timedelta(milliseconds=100)
    assert (f"время максимума: {maximum_time.strftime('%Y-%m-%d %H:%M:%S.%f UTC')}") in detail
    assert "прибор: test; канал: Т12 ref" in detail
    assert "отсчётов: 3" in detail
    assert "Маркер ↕" in detail

    bar.on_reading(_make_reading("\u042212 ref", 4.40, timestamp=base + timedelta(seconds=1)))
    bar._flush_persistent_context()
    assert bar._ctx_second_stage_value.text() == "4.40 K"


def test_older_source_timestamp_cannot_roll_back_latest_digit(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    base = datetime.now(UTC) - timedelta(seconds=5)

    bar.on_reading(_make_reading("\u042211 ref", 76.0, timestamp=base + timedelta(seconds=2)))
    bar.on_reading(_make_reading("\u042211 ref", 70.0, timestamp=base))
    bar._flush_persistent_context()

    assert bar._ctx_n2_plate_value.text().startswith("76.00 K")
    assert "↕" in bar._ctx_n2_plate_value.text()


def test_invalid_vital_is_immediate_textual_and_interval_evidence_survives_tick(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    base = datetime.now(UTC) - timedelta(seconds=5)

    bar.on_reading(_make_reading("\u042212 ref", 4.20, timestamp=base))
    bar._flush_persistent_context()
    assert bar._ctx_second_stage_value.text() == "4.20 K"

    bar.on_reading(
        _make_reading(
            "\u042212 ref",
            float("nan"),
            timestamp=base + timedelta(milliseconds=100),
            status=ChannelStatus.TIMEOUT,
        )
    )
    assert "4.20 K" in bar._ctx_second_stage_value.text()
    assert "НЕТ ДАННЫХ" in bar._ctx_second_stage_value.text()
    assert theme.STATUS_FAULT in bar._ctx_second_stage_value.styleSheet()

    bar.on_reading(_make_reading("\u042212 ref", 4.30, timestamp=base + timedelta(milliseconds=200)))
    assert "НЕТ ДАННЫХ" in bar._ctx_second_stage_value.text()
    bar._flush_persistent_context()
    assert bar._ctx_second_stage_value.text() == "4.30 K · СБОЙ ЗА ИНТ."
    assert "худший статус: тайм-аут" in (bar._ctx_second_stage_value.accessibleDescription())

    bar.on_reading(_make_reading("\u042212 ref", 4.40, timestamp=base + timedelta(seconds=1)))
    bar._flush_persistent_context()
    assert bar._ctx_second_stage_value.text() == "4.40 K"
    assert theme.STATUS_FAULT not in bar._ctx_second_stage_value.styleSheet()


def test_stale_uses_source_timestamp_without_erasing_value(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    old = datetime.now(UTC) - timedelta(seconds=31)

    bar.on_reading(_make_reading("VSP63D_1/pressure", 1.2e-3, "mbar", timestamp=old))
    bar._flush_persistent_context()

    assert "1.2e-3 мбар" in bar._ctx_pressure_value.text()
    assert "(устар.)" in bar._ctx_pressure_value.text()
    assert theme.TEXT_MUTED in bar._ctx_pressure_value.styleSheet()
    assert theme.FONT_MONO in bar._ctx_pressure_value.styleSheet()
    description = bar._ctx_pressure_value.accessibleDescription()
    assert "Данные устарели" in description
    assert "прибор: test; канал: VSP63D_1/pressure" in description


def test_non_positive_pressure_is_invalid_and_retains_last_usable(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    base = datetime.now(UTC) - timedelta(seconds=5)

    bar.on_reading(_make_reading("VSP63D_1/pressure", 1.2e-3, "mbar", timestamp=base))
    bar._flush_persistent_context()
    bar.on_reading(
        _make_reading(
            "VSP63D_1/pressure",
            0.0,
            "mbar",
            timestamp=base + timedelta(seconds=1),
        )
    )

    assert "1.2e-3 мбар" in bar._ctx_pressure_value.text()
    assert "НЕТ ДАННЫХ" in bar._ctx_pressure_value.text()
    assert theme.STATUS_FAULT in bar._ctx_pressure_value.styleSheet()
    assert "давление должно быть больше нуля" in (bar._ctx_pressure_value.accessibleDescription())


def test_older_clean_cut_cannot_clear_newer_interval_fault_evidence(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    base = datetime.now(UTC) - timedelta(seconds=10)

    bar.on_reading(_make_reading("Т12 ref", 4.20, timestamp=base))
    bar._flush_persistent_context()
    bar.on_reading(
        _make_reading(
            "Т12 ref",
            float("nan"),
            timestamp=base + timedelta(seconds=3),
            status=ChannelStatus.TIMEOUT,
        )
    )
    bar.on_reading(_make_reading("Т12 ref", 4.30, timestamp=base + timedelta(seconds=4)))
    bar._flush_persistent_context()
    assert "СБОЙ ЗА ИНТ." in bar._ctx_second_stage_value.text()

    bar.on_reading(_make_reading("Т12 ref", 4.10, timestamp=base + timedelta(seconds=2)))
    bar._flush_persistent_context()
    assert bar._ctx_second_stage_value.text().startswith("4.30 K")
    assert "СБОЙ ЗА ИНТ." in bar._ctx_second_stage_value.text()

    bar.on_reading(_make_reading("Т12 ref", 4.40, timestamp=base + timedelta(seconds=5)))
    bar._flush_persistent_context()
    assert bar._ctx_second_stage_value.text() == "4.40 K"


def test_engine_disconnect_retains_digits_with_explicit_cue(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    bar.on_reading(_make_reading("Т12 ref", 4.20))
    bar._flush_persistent_context()

    bar.set_engine_state(False)

    assert bar._ctx_second_stage_value.text() == "4.20 K · НЕТ СВЯЗИ"
    assert theme.FONT_MONO in bar._ctx_second_stage_value.styleSheet()
    assert "Связь с Engine отсутствует" in (bar._ctx_second_stage_value.accessibleDescription())

    bar.set_engine_state(True)
    assert bar._ctx_second_stage_value.text() == "4.20 K"


def test_future_timestamp_is_visible_caution_and_does_not_pin_order(app, mock_channel_mgr, monkeypatch):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    now = datetime.now(UTC).timestamp()
    monkeypatch.setattr(top_watch_bar_module.time, "time", lambda: now)

    bar.on_reading(
        _make_reading(
            "Т12 ref",
            4.20,
            timestamp=datetime.fromtimestamp(now + 60.0, UTC),
        )
    )
    bar._flush_persistent_context()
    assert "РАССИНХР. ЧАСОВ" in bar._ctx_second_stage_value.text()
    assert theme.STATUS_CAUTION in bar._ctx_second_stage_value.styleSheet()
    assert "впереди часов GUI" in (bar._ctx_second_stage_value.accessibleDescription())

    bar.on_reading(
        _make_reading(
            "Т12 ref",
            4.30,
            timestamp=datetime.fromtimestamp(now + 0.5, UTC),
        )
    )
    bar._flush_persistent_context()
    assert bar._ctx_second_stage_value.text() == "4.30 K"
    assert theme.STATUS_CAUTION not in bar._ctx_second_stage_value.styleSheet()


def test_transient_future_timestamp_survives_one_presentation_cut(app, mock_channel_mgr, monkeypatch):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    now = datetime.now(UTC).timestamp()
    monkeypatch.setattr(top_watch_bar_module.time, "time", lambda: now)

    bar.on_reading(_make_reading("Т12 ref", 4.20, timestamp=datetime.fromtimestamp(now + 60.0, UTC)))
    bar.on_reading(_make_reading("Т12 ref", 4.30, timestamp=datetime.fromtimestamp(now + 0.5, UTC)))
    bar._flush_persistent_context()

    assert bar._ctx_second_stage_value.text().startswith("4.30 K")
    assert "РАССИНХР. ЧАСОВ" in bar._ctx_second_stage_value.text()


def test_10000_updates_keep_one_constant_size_cut(app, mock_channel_mgr):
    bar = TopWatchBar(mock_channel_mgr)
    _stop_timers(bar)
    base = datetime.now(UTC) - timedelta(seconds=5)

    for index in range(10_000):
        bar.on_reading(
            _make_reading(
                "Т12 ref",
                4.0 + (index % 10) / 100.0,
                timestamp=base + timedelta(microseconds=index),
            )
        )

    assert len(bar._pending_vital_cuts) == 1
    cut = bar._pending_vital_cuts["Т12"]
    assert cut.count == 10_000
    assert not hasattr(cut, "__dict__")
    assert not any(
        isinstance(value, (list, dict, set))
        for value in (
            cut.latest,
            cut.latest_usable,
            cut.minimum,
            cut.maximum,
            cut.status_evidence,
            cut.invalid_value_evidence,
            cut.clock_skew_evidence,
        )
    )


# --- _format_pressure helper (Batch A) ---


def test_format_pressure_compact_scientific():
    assert _format_pressure(1.45e-6) == "1.5e-6"
    assert _format_pressure(3.2e-3) == "3.2e-3"
    assert _format_pressure(9.87e-1) == "9.9e-1"


def test_format_pressure_non_positive_returns_dash():
    assert _format_pressure(0.0) == "\u2014"
    assert _format_pressure(-1.0) == "\u2014"
