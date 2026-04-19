"""Tests for InstrumentsPanel (Phase II.8 overlay, K2-critical)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.instruments_panel import (
    _DEFAULT_TIMEOUT_S,
    _MIN_READINGS_FOR_ADAPTIVE,
    _MIN_TIMEOUT_S,
    _TIMEOUT_MULTIPLIER,
    InstrumentsPanel,
    _health_color,
    _InstrumentCard,
    _StatusIndicator,
    _tint_for_health,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


class _FakeSignal:
    def __init__(self) -> None:
        self._slot = None

    def connect(self, slot) -> None:
        self._slot = slot

    def emit(self, *args) -> None:
        if self._slot is not None:
            self._slot(*args)


class _StubWorker:
    """Plain-Python stub for ZmqCommandWorker."""

    dispatched: list[dict] = []
    next_result: dict | None = None

    def __init__(self, cmd, *, parent=None) -> None:
        self._cmd = dict(cmd)
        _StubWorker.dispatched.append(self._cmd)
        self.finished = _FakeSignal()

    def start(self) -> None:
        if _StubWorker.next_result is not None:
            self.finished.emit(_StubWorker.next_result)

    def isRunning(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def _reset_stub(monkeypatch):
    import cryodaq.gui.shell.overlays.instruments_panel as module

    _StubWorker.dispatched = []
    _StubWorker.next_result = None
    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    yield


def _reading(channel: str, value: float = 1.0, instrument_id: str = "") -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id=instrument_id,
        channel=channel,
        value=value,
        unit="K",
        metadata={},
        status=ChannelStatus.OK,
    )


# ----------------------------------------------------------------------
# Invariants on constants (architect mandate — do NOT tune)
# ----------------------------------------------------------------------


def test_liveness_constants_unchanged():
    assert _TIMEOUT_MULTIPLIER == 5.0
    assert _MIN_TIMEOUT_S == 10.0
    assert _DEFAULT_TIMEOUT_S == 300.0
    assert _MIN_READINGS_FOR_ADAPTIVE == 3


# ----------------------------------------------------------------------
# Smoke / structure
# ----------------------------------------------------------------------


def test_panel_constructs(app):
    panel = InstrumentsPanel()
    assert panel.objectName() == "instrumentsPanel"
    assert panel.get_instrument_count() == 0


def test_panel_has_diag_section(app):
    panel = InstrumentsPanel()
    assert panel.sensor_diag_section.row_count == 0


def test_poll_timer_not_active_on_construction(app):
    panel = InstrumentsPanel()
    assert panel._diag_poll_timer.isActive() is False


# ----------------------------------------------------------------------
# _extract_instrument_id
# ----------------------------------------------------------------------


def test_extract_from_instrument_id_field(app):
    r = _reading("foo", instrument_id="LakeShore_42")
    assert InstrumentsPanel._extract_instrument_id(r) == "LakeShore_42"


def test_extract_keithley_channel_prefix(app):
    r = _reading("Keithley_1/smua/voltage")
    assert InstrumentsPanel._extract_instrument_id(r) == "Keithley_1"


def test_extract_lakeshore_t1_to_ls218_1(app):
    assert InstrumentsPanel._extract_instrument_id(_reading("Т7 Детектор")) == "LS218_1"


def test_extract_lakeshore_t9_to_ls218_2(app):
    assert InstrumentsPanel._extract_instrument_id(_reading("Т12")) == "LS218_2"


def test_extract_lakeshore_t17_to_ls218_3(app):
    assert InstrumentsPanel._extract_instrument_id(_reading("Т20")) == "LS218_3"


def test_extract_bare_analytics_channel_dropped(app):
    """Legacy parity: `analytics/…` falls through the prefix-split branch
    (returns "analytics"); only a bare analytics-less non-T channel
    returns empty. Verbatim from v1 — do not tune."""
    r = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="",
        channel="analytics",
        value=0.0,
        unit="",
        metadata={},
    )
    assert InstrumentsPanel._extract_instrument_id(r) == ""


# ----------------------------------------------------------------------
# Card creation
# ----------------------------------------------------------------------


def test_new_instrument_creates_card(app):
    panel = InstrumentsPanel()
    panel._handle_reading(_reading("Т1", instrument_id="LS218_1"))
    assert panel.get_instrument_count() == 1
    assert "LS218_1" in panel._cards


def test_repeated_reading_updates_same_card(app):
    panel = InstrumentsPanel()
    panel._handle_reading(_reading("Т1", instrument_id="LS218_1"))
    panel._handle_reading(_reading("Т2", instrument_id="LS218_1"))
    assert panel.get_instrument_count() == 1
    assert panel._cards["LS218_1"].total_readings == 2


def test_two_distinct_instruments_create_two_cards(app):
    panel = InstrumentsPanel()
    panel._handle_reading(_reading("Т1", instrument_id="LS218_1"))
    panel._handle_reading(_reading("Keithley_1/smua/voltage"))
    assert panel.get_instrument_count() == 2
    assert {"LS218_1", "Keithley_1"}.issubset(panel._cards.keys())


def test_reading_without_instrument_id_and_no_prefix_dropped(app):
    panel = InstrumentsPanel()
    panel._handle_reading(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="",
            channel="nontracked",
            value=1.0,
            unit="",
            metadata={},
        )
    )
    assert panel.get_instrument_count() == 0


# ----------------------------------------------------------------------
# Adaptive liveness
# ----------------------------------------------------------------------


def test_initial_timeout_is_default(app):
    card = _InstrumentCard("inst")
    assert card.timeout_s == _DEFAULT_TIMEOUT_S


def test_adaptive_timeout_computed_from_intervals(app):
    card = _InstrumentCard("inst")
    for _ in range(5):
        card._intervals.append(3.0)  # median 3s → timeout = 15s
    card._recompute_timeout()
    assert card.timeout_s == pytest.approx(15.0, abs=0.01)


def test_timeout_floor_enforced_for_fast_sources(app):
    card = _InstrumentCard("inst")
    # Inject 5 very fast intervals — below floor.
    for _ in range(5):
        card._intervals.append(0.1)
    card._recompute_timeout()
    assert card.timeout_s >= _MIN_TIMEOUT_S


def test_stale_detection_marks_fault(app):
    card = _InstrumentCard("inst")
    card.update_from_reading(_reading("x", instrument_id="inst"))
    # Force past-timeout.
    card._last_reading_time = time.monotonic() - 1000.0
    card._timeout_s = _MIN_TIMEOUT_S
    card.refresh_liveness()
    assert card.indicator_color == theme.STATUS_FAULT


def test_fresh_reading_recovers_to_ok(app):
    card = _InstrumentCard("inst")
    card._last_reading_time = time.monotonic() - 1000.0
    card.refresh_liveness()
    assert card.indicator_color == theme.STATUS_FAULT
    card.update_from_reading(_reading("x", instrument_id="inst"))
    assert card.indicator_color == theme.STATUS_OK


# ----------------------------------------------------------------------
# Status indicator (painted widget, NOT text)
# ----------------------------------------------------------------------


def test_status_indicator_is_painted_qframe(app):
    ind = _StatusIndicator()
    # Painted — no text.
    assert not hasattr(ind, "text") or callable(getattr(ind, "text", lambda: ""))
    qss = ind.styleSheet()
    assert "border-radius" in qss
    assert theme.BORDER_SUBTLE in qss


def test_status_indicator_color_updates_via_setter(app):
    ind = _StatusIndicator()
    ind.set_color(theme.STATUS_OK)
    assert ind.current_color() == theme.STATUS_OK
    assert theme.STATUS_OK in ind.styleSheet()


def test_status_indicator_color_is_ds_token(app):
    ind = _StatusIndicator()
    # Default STALE maps to DS token, not hardcoded hex.
    assert ind.current_color() == theme.STATUS_STALE


# ----------------------------------------------------------------------
# Sensor diag polling
# ----------------------------------------------------------------------


def test_poll_skipped_when_disconnected(app):
    panel = InstrumentsPanel()
    panel._poll_diagnostics()
    assert _StubWorker.dispatched == []


def test_poll_dispatches_get_sensor_diagnostics(app):
    panel = InstrumentsPanel()
    panel.set_connected(True)
    _StubWorker.dispatched = []
    panel._poll_diagnostics()
    assert _StubWorker.dispatched == [{"cmd": "get_sensor_diagnostics"}]
    panel._diag_poll_timer.stop()


def test_poll_in_flight_guard(app):
    panel = InstrumentsPanel()
    panel.set_connected(True)
    _StubWorker.dispatched = []
    panel._poll_diagnostics()
    panel._poll_diagnostics()  # skipped
    assert len(_StubWorker.dispatched) == 1
    panel._diag_poll_timer.stop()


def test_poll_result_populates_table(app):
    panel = InstrumentsPanel()
    panel.set_connected(True)
    _StubWorker.next_result = {
        "ok": True,
        "channels": {"Т1": {"channel_name": "Т1 Plate", "health_score": 95}},
        "summary": {"healthy": 1, "warning": 0, "critical": 0},
    }
    panel._poll_diagnostics()
    assert panel.sensor_diag_section.row_count == 1
    panel._diag_poll_timer.stop()


def test_disconnect_pauses_polling(app):
    panel = InstrumentsPanel()
    panel.set_connected(True)
    assert panel._diag_poll_timer.isActive()
    panel.set_connected(False)
    assert not panel._diag_poll_timer.isActive()


# ----------------------------------------------------------------------
# Sensor diag table
# ----------------------------------------------------------------------


def test_seven_columns_rendered(app):
    panel = InstrumentsPanel()
    panel.set_diagnostics(
        {"Т1": {"channel_name": "Т1", "health_score": 90}},
        {"healthy": 1, "warning": 0, "critical": 0},
    )
    section = panel.sensor_diag_section
    assert section._table.columnCount() == 7


def test_health_column_colored_ok(app):
    panel = InstrumentsPanel()
    panel.set_diagnostics(
        {"Т1": {"channel_name": "Т1", "health_score": 95}},
        {"healthy": 1, "warning": 0, "critical": 0},
    )
    table = panel.sensor_diag_section._table
    fg = table.item(0, 6).foreground().color().name()
    # STATUS_OK should be the color; allow for QColor name format.
    assert fg.lower() == theme.STATUS_OK.lower()


def test_health_column_colored_caution(app):
    panel = InstrumentsPanel()
    panel.set_diagnostics(
        {"Т1": {"channel_name": "Т1", "health_score": 60}},
        {"healthy": 0, "warning": 1, "critical": 0},
    )
    fg = panel.sensor_diag_section._table.item(0, 6).foreground().color().name()
    assert fg.lower() == theme.STATUS_CAUTION.lower()


def test_rows_sorted_by_health_ascending(app):
    panel = InstrumentsPanel()
    panel.set_diagnostics(
        {
            "Т1": {"channel_name": "Т1", "health_score": 95},
            "Т2": {"channel_name": "Т2", "health_score": 30},
            "Т3": {"channel_name": "Т3", "health_score": 65},
        },
        {"healthy": 1, "warning": 1, "critical": 1},
    )
    table = panel.sensor_diag_section._table
    # Worst first.
    assert table.item(0, 0).text() == "Т2"
    assert table.item(1, 0).text() == "Т3"
    assert table.item(2, 0).text() == "Т1"


def test_row_tint_uses_ds_token_alpha(app):
    critical_tint = _tint_for_health(20)
    warning_tint = _tint_for_health(60)
    ok_tint = _tint_for_health(95)
    # Alpha non-zero for problems, zero for OK.
    assert critical_tint.alpha() > 0
    assert warning_tint.alpha() > 0
    assert ok_tint.alpha() == 0
    # Base color is derived from status token (not hardcoded rgba).
    assert critical_tint.red() == QColorHex(theme.STATUS_FAULT)[0]


def QColorHex(hex_str: str) -> tuple[int, int, int]:
    """Tiny helper for tests: hex → (r, g, b) without Qt import."""
    s = hex_str.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


# ----------------------------------------------------------------------
# Summary rendering (no emoji)
# ----------------------------------------------------------------------


def test_summary_uses_severity_chip(app):
    panel = InstrumentsPanel()
    panel.set_diagnostics(
        {},
        {"healthy": 18, "warning": 1, "critical": 1},
    )
    section = panel.sensor_diag_section
    # The chip container holds SeverityChip instances now.
    chip_texts = [w.text() for w in section._chip_widgets]
    joined = " ".join(chip_texts)
    assert "18 ОК" in joined
    assert "1 ПРЕД" in joined
    assert "1 КРИТ" in joined


def test_summary_no_emoji_in_labels(app):
    panel = InstrumentsPanel()
    panel.set_diagnostics(
        {},
        {"healthy": 5, "warning": 2, "critical": 1},
    )
    section = panel.sensor_diag_section
    for chip in section._chip_widgets:
        text = chip.text()
        for ch in text:
            code = ord(ch)
            assert not (0x2600 <= code <= 0x27BF), f"emoji in summary: {ch!r}"
            assert not (0x1F300 <= code <= 0x1FAFF), f"emoji in summary: {ch!r}"


def test_summary_empty_shows_em_dash(app):
    panel = InstrumentsPanel()
    assert panel.get_sensor_summary_text() == "—"


# ----------------------------------------------------------------------
# get_sensor_summary_text (plain, no emoji — for status bar consumer)
# ----------------------------------------------------------------------


def test_get_sensor_summary_text_plain(app):
    panel = InstrumentsPanel()
    panel.set_diagnostics(
        {},
        {"healthy": 18, "warning": 1, "critical": 1},
    )
    text = panel.get_sensor_summary_text()
    assert "18 ОК" in text
    assert "1 ПРЕД" in text
    assert "1 КРИТ" in text
    # No emoji.
    for ch in text:
        code = ord(ch)
        assert not (0x2600 <= code <= 0x27BF), f"emoji: {ch!r}"


# ----------------------------------------------------------------------
# Fail-OPEN — disconnect preserves last state
# ----------------------------------------------------------------------


def test_disconnect_keeps_diag_rows(app):
    panel = InstrumentsPanel()
    panel.set_connected(True)
    panel.set_diagnostics(
        {"Т1": {"channel_name": "Т1", "health_score": 40}},
        {"healthy": 0, "warning": 0, "critical": 1},
    )
    panel.set_connected(False)
    assert panel.sensor_diag_section.row_count == 1


def test_disconnect_keeps_cards_alive(app):
    panel = InstrumentsPanel()
    panel._handle_reading(_reading("Т1", instrument_id="LS218_1"))
    panel.set_connected(True)
    panel.set_connected(False)
    assert panel.get_instrument_count() == 1


# ----------------------------------------------------------------------
# _health_color thresholds
# ----------------------------------------------------------------------


def test_health_color_ok_threshold():
    assert _health_color(80) == theme.STATUS_OK
    assert _health_color(95) == theme.STATUS_OK


def test_health_color_caution_threshold():
    assert _health_color(50) == theme.STATUS_CAUTION
    assert _health_color(79) == theme.STATUS_CAUTION


def test_health_color_fault_threshold():
    assert _health_color(49) == theme.STATUS_FAULT
    assert _health_color(0) == theme.STATUS_FAULT
