"""II.4 host integration: MainWindowV2 ↔ AlarmPanel wiring.

Verifies:
- Connection mirror via `_tick_status` reaches the eagerly-built alarm overlay.
- `_dispatch_reading` routes readings through `on_reading`.
- Overlay is registered under the "alarms" key.
- `v2_alarm_count_changed` signal reaches TopWatchBar.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.shell.overlays.alarm_panel import AlarmPanel


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(w: MainWindowV2) -> None:
    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def _alarm_reading(alarm_name: str) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="engine",
        channel="analytics/alarm",
        value=1.0,
        unit="",
        metadata={
            "alarm_name": alarm_name,
            "severity": "CRITICAL",
            "event_type": "activated",
            "threshold": 0.0,
            "channel": "T1",
        },
    )


# ----------------------------------------------------------------------
# Overlay is present and registered
# ----------------------------------------------------------------------


def test_alarm_panel_built_eagerly():
    _app()
    w = MainWindowV2()
    try:
        assert isinstance(w._alarm_panel, AlarmPanel)
    finally:
        _stop_timers(w)


def test_alarms_key_registered_in_overlay_container():
    _app()
    w = MainWindowV2()
    try:
        # OverlayContainer.show_overlay should accept the "alarms" key
        # without raising. Most reliable probe: verify the panel is the
        # exact instance stored under the "alarms" stack.
        w._overlay.show_overlay("alarms")
        assert w._overlay.currentWidget() is w._alarm_panel
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Connection mirror via _tick_status
# ----------------------------------------------------------------------


def test_tick_sets_alarm_connected_true_when_recent():
    """Freeze monotonic clock so 'recent' is deterministic.

    Assert rendered effect: ACK buttons enabled (connection gate open).
    Injects a real v1 alarm first so the button list is non-empty.
    """
    import unittest.mock as mock

    from PySide6.QtCore import QCoreApplication

    _app()
    w = MainWindowV2()
    try:
        frozen = 100_000.0
        w._last_reading_time = frozen
        with mock.patch("time.monotonic", return_value=frozen + 0.5):
            w._tick_status()
        assert w._alarm_panel._connected is True

        # Inject a live v1 alarm so _v1_ack_buttons is non-empty.
        panel: AlarmPanel = w._alarm_panel
        panel.set_connected(True)
        panel._handle_reading(_alarm_reading("test_alarm_conn_true"))
        QCoreApplication.processEvents()

        v1_btns = panel._v1_ack_buttons
        assert len(v1_btns) > 0, "v1 ACK button list is empty after injecting alarm"
        for btn in v1_btns:
            assert btn.isEnabled(), "ACK button should be enabled when connected"
    finally:
        _stop_timers(w)


def test_tick_sets_alarm_connected_false_when_stale():
    """Freeze monotonic clock so 'stale' is deterministic (10 s gap).

    Assert rendered effect: ACK buttons disabled (connection gate closed).
    Injects a real v1 alarm first so the button list is non-empty.
    """
    import unittest.mock as mock

    from PySide6.QtCore import QCoreApplication

    _app()
    w = MainWindowV2()
    try:
        frozen = 100_000.0
        # First inject alarm while connected so ACK buttons are created.
        panel: AlarmPanel = w._alarm_panel
        panel.set_connected(True)
        panel._handle_reading(_alarm_reading("test_alarm_conn_false"))
        QCoreApplication.processEvents()

        v1_btns = panel._v1_ack_buttons
        assert len(v1_btns) > 0, "v1 ACK button list is empty after injecting alarm"

        # Now simulate stale reading → set_connected(False).
        w._last_reading_time = frozen - 10.0
        with mock.patch("time.monotonic", return_value=frozen):
            w._tick_status()
        assert w._alarm_panel._connected is False
        QCoreApplication.processEvents()

        for btn in v1_btns:
            assert not btn.isEnabled(), "ACK button should be disabled when disconnected"
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# Reading dispatch
# ----------------------------------------------------------------------


def test_dispatch_reading_routes_to_alarm_panel():
    """Assert rendered row: chip widget + alarm name in table cell."""
    _app()
    w = MainWindowV2()
    try:
        w._dispatch_reading(_alarm_reading("hot_plate"))
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.processEvents()
        # Private dict check preserved for quick existence proof.
        assert "hot_plate" in w._alarm_panel._alarms
        # Rendered check: table must have exactly 1 row with a chip widget
        # at column 0 and the alarm name at column 1.
        from cryodaq.gui.shell.overlays.alarm_panel import SeverityChip

        table = w._alarm_panel._table
        assert table.rowCount() >= 1, "v1 alarm table must have at least 1 row"
        chip = table.cellWidget(0, 0)
        assert isinstance(chip, SeverityChip), (
            f"column 0 must hold SeverityChip, got {type(chip)}"
        )
        name_item = table.item(0, 1)
        assert name_item is not None, "column 1 (name) must have a QTableWidgetItem"
        assert name_item.text() == "hot_plate", (
            f"alarm name cell: expected 'hot_plate', got {name_item.text()!r}"
        )
    finally:
        _stop_timers(w)


def test_unrelated_reading_not_dispatched_as_alarm():
    _app()
    w = MainWindowV2()
    try:
        w._dispatch_reading(
            Reading(
                timestamp=datetime.now(UTC),
                instrument_id="x",
                channel="T1",
                value=1.0,
                unit="K",
                metadata={},
            )
        )
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.processEvents()
        assert w._alarm_panel._alarms == {}
    finally:
        _stop_timers(w)


# ----------------------------------------------------------------------
# v2 count signal reaches TopWatchBar
# ----------------------------------------------------------------------


def test_v2_count_signal_forwards_to_top_bar():
    """Assert TopWatchBar label text reflects the forwarded count.

    AlarmPanel.v2_alarm_count_changed is wired to TopWatchBar.set_alarm_count,
    which updates _alarms_label.  Two active v2 alarms → label includes "2".
    """
    _app()
    w = MainWindowV2()
    try:
        w._alarm_panel.update_v2_status(
            {"ok": True, "active": {"a": {"level": "CRITICAL"}, "b": {"level": "WARNING"}}}
        )
        from PySide6.QtCore import QCoreApplication

        QCoreApplication.processEvents()
        assert w._alarm_panel.get_active_v2_count() == 2
        # Rendered: TopWatchBar label must contain the count "2".
        label_text = w._top_bar._alarms_label.text()
        assert "2" in label_text, (
            f"TopWatchBar _alarms_label should contain '2' after 2 active alarms, "
            f"got: {label_text!r}"
        )
    finally:
        _stop_timers(w)
