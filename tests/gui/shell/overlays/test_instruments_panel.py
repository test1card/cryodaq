"""Tests for InstrumentsPanel (Phase II.8 overlay, K2-critical)."""

from __future__ import annotations

import os
import socket
import time
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.channels.descriptors import (
    MAX_CATALOG_DESCRIPTORS,
    ChannelDescriptorV1,
    ChannelQuantity,
    ChannelRole,
    ChannelSafetyClass,
)
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
from cryodaq.gui.state.descriptor_store import (
    DescriptorDiagnostic,
    DescriptorView,
    IdentityStatus,
    TransportState,
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


def _view(
    reading: Reading,
    *,
    identity_status: IdentityStatus = IdentityStatus.AUTHORITATIVE,
    transport_state: TransportState = TransportState.CONNECTED,
) -> DescriptorView:
    descriptor = ChannelDescriptorV1(
        schema_version=1,
        channel_id=reading.channel,
        instrument_id=reading.instrument_id,
        source_key="measurement.primary",
        quantity=ChannelQuantity.TEMPERATURE,
        unit=reading.unit,
        role=ChannelRole.PRIMARY_MEASUREMENT,
        safety_class=ChannelSafetyClass.OBSERVATIONAL,
        display_group="generic",
        display_name="Generic channel",
        visible_by_default=True,
        display_order=1,
        descriptor_revision=1,
    )
    return DescriptorView(
        channel_id=reading.channel,
        descriptor=descriptor,
        identity_status=identity_status,
        transport_state=transport_state,
        diagnostics=(),
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
# Descriptor-only identity
# ----------------------------------------------------------------------


@pytest.mark.parametrize("channel", ["Т7 Детектор", "Т12", "Т20", "Keithley_1/smua/voltage"])
def test_name_patterns_without_descriptor_never_create_card(app, channel):
    panel = InstrumentsPanel()
    panel.on_descriptor_reading(_reading(channel, instrument_id="LS218_1"), None)
    QApplication.processEvents()
    assert panel.get_instrument_count() == 0
    assert panel._empty_cards_label.text() == ("Идентификация прибора недоступна: описание канала отклонено")


def test_provider_neutral_authoritative_descriptor_creates_card(app):
    panel = InstrumentsPanel()
    reading = _reading("opaque-channel-7", instrument_id="asc-reference-42")
    panel.on_descriptor_reading(reading, _view(reading))
    QApplication.processEvents()
    assert set(panel._cards) == {"asc-reference-42"}


def test_legacy_absent_is_visible_but_not_attributed(app):
    panel = InstrumentsPanel()
    reading = _reading("opaque-channel", instrument_id="claimed")
    panel.on_descriptor_reading(
        reading,
        _view(reading, identity_status=IdentityStatus.LEGACY_ABSENT),
    )
    QApplication.processEvents()
    assert panel.get_instrument_count() == 0
    text = panel._empty_cards_label.text()
    style = panel._empty_cards_label.styleSheet()
    assert text == "Идентификация прибора недоступна: описание канала отсутствует"
    assert len(text.encode("utf-8")) <= 256
    assert reading.instrument_id not in text
    assert reading.channel not in text
    assert theme.FOREGROUND in style
    assert theme.STATUS_STALE in style
    assert theme.STATUS_OK not in style


def test_refused_retained_descriptor_does_not_update_card_and_requalifies(app):
    panel = InstrumentsPanel()
    reading = _reading("opaque-channel", instrument_id="asc-reference")
    panel.on_descriptor_reading(reading, _view(reading))
    QApplication.processEvents()
    assert panel._cards["asc-reference"].total_readings == 1

    panel.on_descriptor_reading(
        reading,
        _view(reading, identity_status=IdentityStatus.REFUSED),
    )
    QApplication.processEvents()
    assert panel._cards["asc-reference"].total_readings == 1
    assert "отклонено" in panel._empty_cards_label.text()

    panel.on_descriptor_reading(reading, _view(reading))
    QApplication.processEvents()
    assert panel._cards["asc-reference"].total_readings == 2
    assert panel._empty_cards_label.isHidden()


def test_disconnected_or_mismatched_view_never_attributes(app):
    panel = InstrumentsPanel()
    reading = _reading("opaque-channel", instrument_id="asc-reference")
    panel.on_descriptor_reading(
        reading,
        _view(reading, transport_state=TransportState.DISCONNECTED),
    )
    mismatched = _view(reading)
    panel.on_descriptor_reading(
        reading,
        DescriptorView(
            channel_id="different-channel",
            descriptor=mismatched.descriptor,
            identity_status=mismatched.identity_status,
            transport_state=mismatched.transport_state,
            diagnostics=(),
        ),
    )
    QApplication.processEvents()
    assert panel.get_instrument_count() == 0
    assert "отклонено" in panel._empty_cards_label.text()


def test_identity_notice_mutates_only_on_state_transitions(app, monkeypatch):
    panel = InstrumentsPanel()
    reading = _reading("opaque-channel", instrument_id="asc-reference")
    panel.on_descriptor_reading(reading, _view(reading))
    QApplication.processEvents()

    calls = {"style": 0, "text": 0, "visible": 0}
    label = panel._empty_cards_label
    original_style = label.setStyleSheet
    original_text = label.setText
    original_visible = label.setVisible

    def set_style(value):
        calls["style"] += 1
        original_style(value)

    def set_text(value):
        calls["text"] += 1
        original_text(value)

    def set_visible(value):
        calls["visible"] += 1
        original_visible(value)

    monkeypatch.setattr(label, "setStyleSheet", set_style)
    monkeypatch.setattr(label, "setText", set_text)
    monkeypatch.setattr(label, "setVisible", set_visible)

    for _ in range(50):
        panel._handle_descriptor_reading(reading, _view(reading))
    assert calls == {"style": 0, "text": 0, "visible": 0}

    refused = _view(reading, identity_status=IdentityStatus.REFUSED)
    panel._handle_descriptor_reading(reading, refused)
    transition_calls = dict(calls)
    assert all(count > 0 for count in transition_calls.values())
    for _ in range(50):
        panel._handle_descriptor_reading(reading, refused)
    assert calls == transition_calls


def test_unavailable_notice_is_bounded_russian_noncolor_and_excludes_hostile_text(app):
    panel = InstrumentsPanel()
    hostile = "<b>HOSTILE_VENDOR_PAYLOAD_DIAGNOSTIC</b>"
    reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="hostile-vendor",
        channel="hostile-channel",
        value=1.0,
        unit="K",
        metadata={"payload": hostile},
    )
    refused = _view(reading, identity_status=IdentityStatus.REFUSED)
    refused = DescriptorView(
        channel_id=refused.channel_id,
        descriptor=refused.descriptor,
        identity_status=refused.identity_status,
        transport_state=refused.transport_state,
        diagnostics=(DescriptorDiagnostic(hostile, 1, None),),
    )
    panel._handle_descriptor_reading(reading, refused)

    text = panel._empty_cards_label.text()
    style = panel._empty_cards_label.styleSheet()
    assert text == "Идентификация прибора недоступна: описание канала отклонено"
    assert len(text.encode("utf-8")) <= 256
    assert all(value not in text for value in (hostile, reading.instrument_id, reading.channel))
    assert theme.FOREGROUND in style
    assert theme.STATUS_FAULT in style
    assert theme.STATUS_OK not in style


def test_identity_issue_tracking_is_o1_bounded_and_has_no_blocking_io(app, monkeypatch):
    panel = InstrumentsPanel()
    for index in range(MAX_CATALOG_DESCRIPTORS):
        panel._set_identity_issue(f"channel-{index}", IdentityStatus.LEGACY_ABSENT)
    panel._set_identity_issue("over-capacity", IdentityStatus.REFUSED)
    assert len(panel._identity_issues) == MAX_CATALOG_DESCRIPTORS
    assert panel._identity_issue_sticky is True
    assert panel._refused_identity_count == 0

    reading = _reading("bounded-channel", instrument_id="bounded-instrument")
    view = _view(reading)

    def blocking_io_forbidden(*args, **kwargs):
        raise AssertionError("blocking I/O reached descriptor presentation")

    with monkeypatch.context() as guarded:
        guarded.setattr("builtins.open", blocking_io_forbidden)
        guarded.setattr(socket, "socket", blocking_io_forbidden)
        guarded.setattr(time, "sleep", blocking_io_forbidden)
        panel._handle_descriptor_reading(reading, view)


# ----------------------------------------------------------------------
# Card creation
# ----------------------------------------------------------------------


def test_new_instrument_creates_card(app):
    from PySide6.QtCore import QCoreApplication

    panel = InstrumentsPanel()
    reading = _reading("Т1", instrument_id="LS218_1")
    panel.on_descriptor_reading(reading, _view(reading))
    QCoreApplication.processEvents()
    assert panel.get_instrument_count() == 1
    assert "LS218_1" in panel._cards
    # Card label must display the instrument name.
    card = panel._cards["LS218_1"]
    assert card._name_label.text() == "LS218_1", f"Card name label wrong: {card._name_label.text()!r}"
    # Indicator must be present (a _StatusIndicator, not a label).
    assert isinstance(card._indicator, _StatusIndicator)
    # Empty-state overlay must be hidden after the first reading.
    assert panel._empty_cards_label.isHidden() is True


def test_repeated_reading_updates_same_card(app):
    from PySide6.QtCore import QCoreApplication

    panel = InstrumentsPanel()
    first = _reading("Т1", instrument_id="LS218_1")
    panel.on_descriptor_reading(first, _view(first))
    QCoreApplication.processEvents()
    second = _reading("Т2", instrument_id="LS218_1")
    panel.on_descriptor_reading(second, _view(second))
    QCoreApplication.processEvents()
    assert panel.get_instrument_count() == 1
    assert panel._cards["LS218_1"].total_readings == 2
    # Assert rendered counter text — not just the private total_readings int.
    counter_text = panel._cards["LS218_1"]._counters_label.text()
    assert counter_text == "Показания: 2 | Ошибки: 0", f"Counter label text wrong: {counter_text!r}"


def test_two_distinct_instruments_create_two_cards(app):
    from PySide6.QtCore import QCoreApplication

    panel = InstrumentsPanel()
    first = _reading("Т1", instrument_id="LS218_1")
    panel.on_descriptor_reading(first, _view(first))
    QCoreApplication.processEvents()
    second = _reading("Keithley_1/smua/voltage", instrument_id="Keithley_1")
    panel.on_descriptor_reading(second, _view(second))
    QCoreApplication.processEvents()
    assert panel.get_instrument_count() == 2
    assert {"LS218_1", "Keithley_1"}.issubset(panel._cards.keys())
    # Assert both visible card names are displayed correctly.
    assert panel._cards["LS218_1"]._name_label.text() == "LS218_1"
    assert panel._cards["Keithley_1"]._name_label.text() == "Keithley_1"


def test_malformed_view_is_visible_and_never_attributed(app):
    panel = InstrumentsPanel()
    panel.on_descriptor_reading(_reading("nontracked", instrument_id="claimed"), object())
    QApplication.processEvents()
    assert panel.get_instrument_count() == 0
    assert "отклонено" in panel._empty_cards_label.text()


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
    # Assert rendered status label text (not just indicator color).
    assert "Нет связи" in card._status_label.text(), f"Stale card status label wrong: {card._status_label.text()!r}"
    # Counters must still reflect the one reading.
    assert "Показания: 1" in card._counters_label.text()


def test_fresh_reading_recovers_to_ok(app):
    card = _InstrumentCard("inst")
    card._last_reading_time = time.monotonic() - 1000.0
    card.refresh_liveness()
    assert card.indicator_color == theme.STATUS_FAULT
    assert "Нет связи" in card._status_label.text(), f"Pre-recovery status label wrong: {card._status_label.text()!r}"
    card.update_from_reading(_reading("x", instrument_id="inst"))
    assert card.indicator_color == theme.STATUS_OK
    # After fresh reading, status must say Норма.
    assert "Норма" in card._status_label.text(), f"Post-recovery status label wrong: {card._status_label.text()!r}"
    # Counters must reflect the new reading.
    assert "Показания: 1" in card._counters_label.text()


# ----------------------------------------------------------------------
# Status indicator (painted widget, NOT text)
# ----------------------------------------------------------------------


def test_status_indicator_is_painted_qframe(app):
    from PySide6.QtWidgets import QFrame, QLabel

    ind = _StatusIndicator()
    # Must be a QFrame subclass (painted, not a text label).
    assert isinstance(ind, QFrame), f"_StatusIndicator must be QFrame, got {type(ind)}"
    # Must NOT be a QLabel (which has a text() method and renders glyphs).
    assert not isinstance(ind, QLabel), "_StatusIndicator must not be a QLabel"
    # Must have no text() method on the instance (painted, no glyph dependency).
    assert not hasattr(ind, "text"), "_StatusIndicator must not have text() — it is a painted widget, not a text label"
    # Fixed size enforced (circle geometry).
    assert ind.width() > 0 and ind.height() > 0
    assert ind.minimumWidth() == ind.maximumWidth(), "Indicator must have fixed width"
    # QSS contract: border-radius for circle + DS border token.
    qss = ind.styleSheet()
    assert "border-radius" in qss, f"border-radius missing from styleSheet: {qss!r}"
    assert theme.BORDER_SUBTLE in qss, f"BORDER_SUBTLE token missing from styleSheet: {qss!r}"
    # Color accessor must work.
    assert ind.current_color() == theme.STATUS_STALE


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
    # set_connected(True) now fires one immediate poll (II.8) —
    # verify that AND the 10 s timer is armed.
    assert _StubWorker.dispatched == [{"cmd": "get_sensor_diagnostics"}]
    panel._diag_poll_timer.stop()


def test_poll_in_flight_guard(app):
    panel = InstrumentsPanel()
    panel.set_connected(True)
    _StubWorker.dispatched = []
    # After set_connected(True), _diag_poll_in_flight is True (stub did
    # not deliver result). Clear it and verify the guard on two sequential
    # polls in isolation.
    panel._diag_poll_in_flight = False
    panel._poll_diagnostics()
    panel._poll_diagnostics()  # skipped by in-flight guard
    assert len(_StubWorker.dispatched) == 1
    panel._diag_poll_timer.stop()


def test_poll_result_populates_table(app):
    panel = InstrumentsPanel()
    _StubWorker.next_result = {
        "ok": True,
        "channels": {"Т1": {"channel_name": "Т1 Plate", "health_score": 95}},
        "summary": {"healthy": 1, "warning": 0, "critical": 0},
    }
    panel.set_connected(True)  # fires the immediate poll which consumes next_result
    assert panel.sensor_diag_section.row_count == 1

    # Assert exact channel name in first row (column 0).
    table = panel.sensor_diag_section._table
    assert table.item(0, 0).text() == "Т1 Plate", f"Row channel name wrong: {table.item(0, 0).text()!r}"
    # Assert health score in last column (column 6) = "95".
    assert table.item(0, 6).text() == "95", f"Health score wrong: {table.item(0, 6).text()!r}"
    # Health 95 → STATUS_OK color on health column.
    fg = table.item(0, 6).foreground().color().name()
    assert fg.lower() == theme.STATUS_OK.lower(), f"Health color wrong for score 95: {fg!r}"
    # Summary chip must show "1 ОК".
    chip_texts = [w.text() for w in panel.sensor_diag_section._chip_widgets]
    assert any("1 ОК" in t for t in chip_texts), f"Summary chip '1 ОК' missing; chips: {chip_texts}"

    panel._diag_poll_timer.stop()


def test_set_connected_fires_immediate_poll(app):
    """II.8: False → True transition must not leave the K2
    diagnostics table blank for up to 10 s."""
    panel = InstrumentsPanel()
    _StubWorker.dispatched = []
    panel.set_connected(True)
    assert _StubWorker.dispatched == [{"cmd": "get_sensor_diagnostics"}]
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
    # Assert exact column headers in order (not just count).
    expected_headers = ["Канал", "T (K)", "Шум (мК)", "Дрейф (мК/мин)", "Выбросы", "Корр.", "Здоровье"]
    actual_headers = [section._table.horizontalHeaderItem(c).text() for c in range(section._table.columnCount())]
    assert actual_headers == expected_headers, (
        f"Column headers mismatch:\n  expected: {expected_headers}\n  got: {actual_headers}"
    )


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
        {"Т1": {"channel_name": "Т1 Plate", "health_score": 40}},
        {"healthy": 0, "warning": 0, "critical": 1},
    )
    panel.set_connected(False)
    assert panel.sensor_diag_section.row_count == 1
    # Assert row text is preserved (not blanked on disconnect).
    table = panel.sensor_diag_section._table
    assert table.item(0, 0).text() == "Т1 Plate", (
        f"Row channel name wrong after disconnect: {table.item(0, 0).text()!r}"
    )
    # Health score 40 → FAULT color preserved.
    fg = table.item(0, 6).foreground().color().name()
    from cryodaq.gui import theme as _theme

    assert fg.lower() == _theme.STATUS_FAULT.lower(), f"Health color wrong after disconnect: {fg!r}"


def test_disconnect_keeps_cards_alive(app):
    from PySide6.QtCore import QCoreApplication

    panel = InstrumentsPanel()
    reading = _reading("Т1", instrument_id="LS218_1")
    panel.on_descriptor_reading(reading, _view(reading))
    QCoreApplication.processEvents()
    panel.set_connected(True)
    panel.set_connected(False)
    assert panel.get_instrument_count() == 1
    # Card must still display the instrument name after disconnect.
    card = panel._cards["LS218_1"]
    assert card._name_label.text() == "LS218_1"
    # Card status should NOT be reset to empty — liveness timer will update it.
    assert card._status_label.text() != "", "Status label must not be cleared on disconnect"


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
