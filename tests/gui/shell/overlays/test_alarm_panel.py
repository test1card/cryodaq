"""Tests for AlarmPanel (Phase II.4 overlay, K1-critical)."""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.alarm_panel import (
    AlarmPanel,
    SeverityChip,
    _elapsed_text,
    _make_ack_button,
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
    """Plain-Python stub for ZmqCommandWorker — no threads, captures
    commands, lets tests emit canned results synchronously."""

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
    import cryodaq.gui.shell.overlays.alarm_panel as module

    _StubWorker.dispatched = []
    _StubWorker.next_result = None
    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    yield


def _alarm_reading(
    alarm_name: str,
    severity: str,
    event_type: str,
    value: float = 0.0,
    threshold: float = 0.0,
    channel: str = "T1",
) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="engine",
        channel="analytics/alarm",
        value=value,
        unit="",
        metadata={
            "alarm_name": alarm_name,
            "severity": severity,
            "event_type": event_type,
            "threshold": threshold,
            "channel": channel,
        },
    )


# ----------------------------------------------------------------------
# Structure / defaults
# ----------------------------------------------------------------------


def test_panel_constructs(app):
    panel = AlarmPanel()
    assert panel.objectName() == "alarmPanel"
    assert panel._connected is False
    assert panel._alarms == {}
    assert panel._v2_alarms == {}


def test_panel_has_v1_and_v2_tables(app):
    panel = AlarmPanel()
    assert panel._table.columnCount() == 8
    assert panel._v2_table.columnCount() == 6


def test_poll_timer_not_active_on_construction(app):
    panel = AlarmPanel()
    assert panel._v2_poll_timer.isActive() is False


def test_empty_label_visible_by_default(app):
    panel = AlarmPanel()
    assert panel._v2_empty_label.isHidden() is False


def test_summary_label_hidden_when_no_alarms(app):
    panel = AlarmPanel()
    assert panel._summary_label.isHidden() is True


# ----------------------------------------------------------------------
# SeverityChip
# ----------------------------------------------------------------------


def test_severity_chip_critical_label(app):
    chip = SeverityChip("CRITICAL")
    assert chip.text() == "КРИТ"
    assert chip.severity == "CRITICAL"


def test_severity_chip_warning_label(app):
    chip = SeverityChip("WARNING")
    assert chip.text() == "ПРЕД"


def test_severity_chip_info_label(app):
    chip = SeverityChip("INFO")
    assert chip.text() == "ИНФО"


def test_severity_chip_uses_status_fault_token(app):
    chip = SeverityChip("CRITICAL")
    qss = chip.styleSheet()
    assert theme.STATUS_FAULT in qss


def test_severity_chip_uses_status_warning_token(app):
    chip = SeverityChip("WARNING")
    qss = chip.styleSheet()
    assert theme.STATUS_WARNING in qss


def test_severity_chip_no_emoji_in_label(app):
    for sev in ("CRITICAL", "WARNING", "INFO"):
        chip = SeverityChip(sev)
        text = chip.text()
        assert all(ord(ch) < 0x2600 or ord(ch) > 0x27BF for ch in text)
        assert all(not (0x1F300 <= ord(ch) <= 0x1FAFF) for ch in text)


def test_severity_chip_unknown_severity_falls_back(app):
    chip = SeverityChip("FOOBAR")
    # Falls back to INFO color and truncated label.
    assert theme.STATUS_INFO in chip.styleSheet()


# ----------------------------------------------------------------------
# _make_ack_button
# ----------------------------------------------------------------------


def test_ack_button_default_label(app):
    btn = _make_ack_button("CRITICAL")
    assert btn.text() == "ПОДТВЕРДИТЬ"


def test_ack_button_custom_label(app):
    btn = _make_ack_button("WARNING", label="ACK")
    assert btn.text() == "ACK"


def test_ack_button_uses_status_fault_color(app):
    btn = _make_ack_button("CRITICAL")
    assert theme.STATUS_FAULT in btn.styleSheet()


def test_ack_button_disabled_uses_muted_token(app):
    btn = _make_ack_button("CRITICAL")
    qss = btn.styleSheet()
    assert theme.SURFACE_MUTED in qss
    assert theme.MUTED_FOREGROUND in qss


# ----------------------------------------------------------------------
# v1 reading path
# ----------------------------------------------------------------------


def test_reading_without_alarm_name_is_dropped(app):
    panel = AlarmPanel()
    reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="x",
        channel="T1",
        value=1.0,
        unit="K",
        metadata={},
    )
    panel._handle_reading(reading)
    assert panel._alarms == {}


def test_reading_activated_adds_row(app):
    panel = AlarmPanel()
    panel._handle_reading(
        _alarm_reading("cold_plate_hot", "CRITICAL", "activated", value=300.0, threshold=290.0)
    )
    assert "cold_plate_hot" in panel._alarms
    row = panel._alarms["cold_plate_hot"]
    assert row.severity == "CRITICAL"
    assert row.state == "active"
    assert row.trigger_count == 1


def test_reading_acknowledged_updates_state(app):
    panel = AlarmPanel()
    panel._handle_reading(_alarm_reading("x", "WARNING", "activated"))
    panel._handle_reading(_alarm_reading("x", "WARNING", "acknowledged"))
    assert panel._alarms["x"].state == "acknowledged"


def test_reading_cleared_updates_state(app):
    panel = AlarmPanel()
    panel._handle_reading(_alarm_reading("x", "WARNING", "activated"))
    panel._handle_reading(_alarm_reading("x", "WARNING", "cleared"))
    assert panel._alarms["x"].state == "cleared"


def test_reading_reactivated_increments_trigger_count(app):
    panel = AlarmPanel()
    panel._handle_reading(_alarm_reading("x", "INFO", "activated"))
    panel._handle_reading(_alarm_reading("x", "INFO", "cleared"))
    panel._handle_reading(_alarm_reading("x", "INFO", "activated"))
    assert panel._alarms["x"].trigger_count == 2


def test_reading_invalid_value_defaults_to_zero(app):
    panel = AlarmPanel()
    reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="x",
        channel="T1",
        value=float("nan"),  # a number, but invalid strings also coerced
        unit="",
        metadata={
            "alarm_name": "bad",
            "severity": "INFO",
            "event_type": "activated",
            "threshold": "not_a_number",
        },
    )
    panel._handle_reading(reading)
    assert panel._alarms["bad"].threshold == 0.0


def test_get_active_v1_count(app):
    panel = AlarmPanel()
    panel._handle_reading(_alarm_reading("a", "WARNING", "activated"))
    panel._handle_reading(_alarm_reading("b", "CRITICAL", "activated"))
    panel._handle_reading(_alarm_reading("c", "INFO", "cleared"))
    assert panel.get_active_v1_count() == 2


# ----------------------------------------------------------------------
# set_connected gating
# ----------------------------------------------------------------------


def test_set_connected_true_starts_poll_timer(app):
    panel = AlarmPanel()
    panel.set_connected(True)
    assert panel._v2_poll_timer.isActive() is True
    panel._v2_poll_timer.stop()


def test_set_connected_false_stops_poll_timer(app):
    panel = AlarmPanel()
    panel.set_connected(True)
    panel.set_connected(False)
    assert panel._v2_poll_timer.isActive() is False


def test_set_connected_same_value_is_noop(app):
    panel = AlarmPanel()
    panel.set_connected(False)
    assert panel._v2_poll_timer.isActive() is False


def test_set_connected_enables_v1_ack_buttons(app):
    panel = AlarmPanel()
    panel._handle_reading(_alarm_reading("a", "CRITICAL", "activated"))
    # Rebuild triggered the button with current connected state (False).
    assert panel._v1_ack_buttons[0].isEnabled() is False
    panel.set_connected(True)
    assert panel._v1_ack_buttons[0].isEnabled() is True
    panel._v2_poll_timer.stop()


# ----------------------------------------------------------------------
# v2 update_v2_status + signal
# ----------------------------------------------------------------------


def test_update_v2_status_empty_payload_clears(app):
    panel = AlarmPanel()
    panel.update_v2_status({"ok": True, "active": {}})
    assert panel._v2_alarms == {}
    assert panel._v2_empty_label.isHidden() is False


def test_update_v2_status_populates_table(app):
    panel = AlarmPanel()
    payload = {
        "ok": True,
        "active": {
            "cold_plate": {
                "level": "CRITICAL",
                "message": "Cold plate overheat",
                "channels": ["T1", "T2"],
                "triggered_at": time.time(),
            }
        },
    }
    panel.update_v2_status(payload)
    assert panel._v2_alarms == payload["active"]
    assert panel._v2_table.rowCount() == 1
    assert panel._v2_empty_label.isHidden() is True


def test_update_v2_status_emits_count_signal(app):
    panel = AlarmPanel()
    received: list[int] = []
    panel.v2_alarm_count_changed.connect(lambda n: received.append(n))
    panel.update_v2_status(
        {"ok": True, "active": {"a": {"level": "INFO"}, "b": {"level": "WARNING"}}}
    )
    assert received == [2]


def test_update_v2_status_truncates_long_message(app):
    panel = AlarmPanel()
    long_msg = "x" * 200
    panel.update_v2_status(
        {
            "ok": True,
            "active": {
                "a": {"level": "INFO", "message": long_msg, "triggered_at": time.time()},
            },
        }
    )
    cell = panel._v2_table.item(0, 2)
    assert cell is not None
    assert cell.text().endswith("…")
    assert len(cell.text()) < len(long_msg)


def test_update_v2_status_malformed_payload_is_safe(app):
    panel = AlarmPanel()
    panel.update_v2_status({"active": "nope"})
    assert panel._v2_alarms == {}


def test_get_active_v2_count(app):
    panel = AlarmPanel()
    panel.update_v2_status(
        {"ok": True, "active": {"a": {"level": "CRITICAL"}, "b": {"level": "INFO"}}}
    )
    assert panel.get_active_v2_count() == 2


def test_v2_row_ack_button_disabled_before_connect(app):
    panel = AlarmPanel()
    panel.update_v2_status({"ok": True, "active": {"a": {"level": "CRITICAL"}}})
    assert panel._v2_ack_buttons[0].isEnabled() is False


def test_v2_row_ack_button_enabled_after_connect(app):
    panel = AlarmPanel()
    panel.update_v2_status({"ok": True, "active": {"a": {"level": "CRITICAL"}}})
    panel.set_connected(True)
    assert panel._v2_ack_buttons[0].isEnabled() is True
    panel._v2_poll_timer.stop()


# ----------------------------------------------------------------------
# Summary label
# ----------------------------------------------------------------------


def test_summary_shows_criticals(app):
    panel = AlarmPanel()
    panel._handle_reading(_alarm_reading("a", "CRITICAL", "activated"))
    panel._handle_reading(_alarm_reading("b", "CRITICAL", "activated"))
    assert "критических" in panel._summary_label.text()
    assert panel._summary_label.isHidden() is False


def test_summary_shows_warnings(app):
    panel = AlarmPanel()
    panel._handle_reading(_alarm_reading("a", "WARNING", "activated"))
    assert "предупреждений" in panel._summary_label.text()


def test_summary_hidden_when_only_cleared(app):
    panel = AlarmPanel()
    panel._handle_reading(_alarm_reading("a", "INFO", "cleared"))
    assert panel._summary_label.isHidden() is True


# ----------------------------------------------------------------------
# Polling
# ----------------------------------------------------------------------


def test_poll_v2_status_skipped_when_disconnected(app):
    panel = AlarmPanel()
    panel._poll_v2_status()
    assert _StubWorker.dispatched == []


def test_poll_v2_status_dispatches_when_connected(app):
    panel = AlarmPanel()
    panel.set_connected(True)
    _StubWorker.dispatched = []
    panel._poll_v2_status()
    assert _StubWorker.dispatched == [{"cmd": "alarm_v2_status"}]
    panel._v2_poll_timer.stop()


def test_poll_in_flight_guard_prevents_double_dispatch(app):
    panel = AlarmPanel()
    panel.set_connected(True)
    _StubWorker.dispatched = []
    panel._poll_v2_status()  # in-flight = True
    panel._poll_v2_status()  # skipped
    assert len(_StubWorker.dispatched) == 1
    panel._v2_poll_timer.stop()


def test_poll_result_ok_updates_table(app):
    panel = AlarmPanel()
    panel.set_connected(True)
    _StubWorker.next_result = {
        "ok": True,
        "active": {"a": {"level": "WARNING", "message": "m"}},
    }
    panel._poll_v2_status()
    assert panel._v2_alarms == {"a": {"level": "WARNING", "message": "m"}}
    panel._v2_poll_timer.stop()


def test_poll_result_failure_preserves_last_state(app):
    """Fail-OPEN: engine error must not wipe table."""
    panel = AlarmPanel()
    panel.update_v2_status({"ok": True, "active": {"a": {"level": "CRITICAL"}}})
    panel.set_connected(True)
    _StubWorker.next_result = {"ok": False, "error": "boom"}
    panel._poll_v2_status()
    assert "a" in panel._v2_alarms
    panel._v2_poll_timer.stop()


def test_poll_result_non_dict_is_safe(app):
    panel = AlarmPanel()
    panel.set_connected(True)
    _StubWorker.next_result = "bad"  # type: ignore[assignment]
    panel._poll_v2_status()
    # No crash; in-flight guard cleared.
    assert panel._v2_poll_in_flight is False
    panel._v2_poll_timer.stop()


# ----------------------------------------------------------------------
# ACK dispatch
# ----------------------------------------------------------------------


def test_v1_acknowledge_dispatches_zmq_command(app):
    panel = AlarmPanel()
    panel._handle_reading(_alarm_reading("hot", "CRITICAL", "activated"))
    panel.set_connected(True)
    _StubWorker.dispatched = []
    panel._acknowledge("hot")
    assert _StubWorker.dispatched == [{"cmd": "alarm_acknowledge", "alarm_name": "hot"}]
    panel._v2_poll_timer.stop()


def test_v2_acknowledge_dispatches_zmq_command(app):
    panel = AlarmPanel()
    panel.update_v2_status({"ok": True, "active": {"cold": {"level": "CRITICAL"}}})
    panel.set_connected(True)
    _StubWorker.dispatched = []
    panel._acknowledge_v2("cold")
    assert _StubWorker.dispatched == [{"cmd": "alarm_v2_ack", "alarm_name": "cold"}]
    panel._v2_poll_timer.stop()


# ----------------------------------------------------------------------
# Fail-OPEN (disconnect behavior)
# ----------------------------------------------------------------------


def test_disconnect_keeps_v1_rows(app):
    panel = AlarmPanel()
    panel._handle_reading(_alarm_reading("a", "CRITICAL", "activated"))
    panel.set_connected(True)
    panel.set_connected(False)
    assert panel._alarms != {}


def test_disconnect_keeps_v2_rows(app):
    panel = AlarmPanel()
    panel.update_v2_status({"ok": True, "active": {"a": {"level": "CRITICAL"}}})
    panel.set_connected(True)
    panel.set_connected(False)
    assert panel._v2_alarms != {}


# ----------------------------------------------------------------------
# _elapsed_text formatter
# ----------------------------------------------------------------------


def test_elapsed_text_seconds():
    assert _elapsed_text(45.0) == "45 с"


def test_elapsed_text_minutes():
    assert _elapsed_text(120.0) == "2 мин"


def test_elapsed_text_hours():
    assert _elapsed_text(3660.0) == "1.0 ч"
