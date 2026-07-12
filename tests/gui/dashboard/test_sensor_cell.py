"""Tests for SensorCell (Phase UI-1 v2 Block B.3)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui import theme
from cryodaq.gui.dashboard.sensor_cell import SensorCell


# LOW: assert initial label text, dash value, hint text, stale style
def test_sensor_cell_constructs(app, mock_channel_mgr, buffer_store):
    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)
    assert cell is not None
    assert cell.objectName() == "sensorCell"
    # initial label contains channel id or display name
    assert "Т1" in cell._label_widget.text()
    # initial value is em-dash
    assert cell._value_widget.text() == "—"
    # initial hint shows "Нет данных"
    assert "данных" in cell._status_hint_widget.text() or "данн" in cell._status_hint_widget.text()
    # initial style uses STATUS_STALE border
    assert theme.STATUS_STALE in cell.styleSheet()


def test_sensor_cell_displays_label(app, mock_channel_mgr, buffer_store):
    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)
    assert "Т1" in cell._label_widget.text()


def test_sensor_cell_update_value_with_reading(app, mock_channel_mgr, buffer_store):
    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)
    reading = Reading(
        channel="Т1 Криостат верх",
        value=4.21,
        unit="K",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    cell.update_value(reading)
    assert "4.21" in cell._value_widget.text()
    assert cell._unit_widget.text() == "K"
    assert cell._last_status == ChannelStatus.OK


# HIGH: assert dash value, empty unit, stale text + stale style token
def test_sensor_cell_refresh_from_empty_buffer_marks_stale(app, mock_channel_mgr, buffer_store):
    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)
    # Provide a reading first to clear initial stale state
    reading = Reading(
        channel="Т1 Криостат верх",
        value=4.21,
        unit="K",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    cell.update_value(reading)
    assert not cell._data_stale
    # Now refresh from empty buffer → must go stale
    cell.refresh_from_buffer()
    # rendered contract: value = "—", unit = "", stale style, hint text
    assert cell._value_widget.text() == "—", f"Expected em-dash after stale refresh, got {cell._value_widget.text()!r}"
    assert cell._unit_widget.text() == "", f"Expected empty unit after stale refresh, got {cell._unit_widget.text()!r}"
    assert theme.STATUS_STALE in cell.styleSheet(), "Expected STATUS_STALE in stylesheet after stale refresh"
    assert cell._data_stale is True


# MED: trigger rename via mouseDoubleClickEvent + editingFinished signal, assert signal + label restored
def test_sensor_cell_inline_rename_signals(app, mock_channel_mgr, buffer_store):
    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)

    received = []
    cell.rename_requested.connect(lambda ch, name: received.append((ch, name)))

    # Trigger rename via mouseDoubleClickEvent (real Qt path)
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    evt = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(0, 0),
        QPointF(0, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    cell.mouseDoubleClickEvent(evt)
    app.processEvents()
    assert cell._is_renaming is True, "mouseDoubleClickEvent should enter rename mode"

    # Set text directly and emit editingFinished (the real signal path _commit_rename is connected to)
    cell._rename_edit.setText("Новое имя")
    cell._rename_edit.editingFinished.emit()
    app.processEvents()

    assert received == [("Т1", "Новое имя")], f"Expected rename signal with ('Т1', 'Новое имя'), got {received!r}"
    # label restored, not renaming
    assert cell._is_renaming is False
    assert not cell._label_widget.isHidden()


def test_sensor_cell_read_only_rejects_mouse_rename(app, mock_channel_mgr, buffer_store):
    """Replay double-click cannot expose the inline config editor."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)
    received = []
    cell.rename_requested.connect(lambda ch, name: received.append((ch, name)))
    cell.set_read_only(True)

    event = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(0, 0),
        QPointF(0, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    cell.mouseDoubleClickEvent(event)
    app.processEvents()

    assert cell._is_renaming is False
    assert cell._rename_edit is None
    assert received == []


def test_sensor_cell_read_only_cancels_inflight_keyboard_rename(app, mock_channel_mgr, buffer_store):
    """A replay transition settles an open editor before Enter/focus loss."""
    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)
    received = []
    cell.rename_requested.connect(lambda ch, name: received.append((ch, name)))
    cell._enter_rename_mode()
    edit = cell._rename_edit
    assert edit is not None
    edit.setText("Не сохранять")

    cell.set_read_only(True)
    edit.editingFinished.emit()
    app.processEvents()

    assert cell._is_renaming is False
    assert cell._rename_edit is None
    assert received == []


def test_sensor_cell_read_only_context_menu_omits_config_actions(app, mock_channel_mgr, buffer_store):
    """Replay right-click retains inspection but removes rename and hide."""
    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)
    cell.set_read_only(True)
    menu = cell._build_context_menu()
    seen = [action.text() for action in menu.actions() if not action.isSeparator()]

    assert "Переименовать" not in seen
    assert "Скрыть" not in seen
    assert "Показать на графике" in seen
    assert "История за час" in seen


# HIGH: send Escape through eventFilter via synthetic QKeyEvent, assert label restored
def test_sensor_cell_rename_escape_cancels(app, mock_channel_mgr, buffer_store):
    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)

    # Enter rename mode via the real mouseDoubleClickEvent path
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    dbl_evt = QMouseEvent(
        QEvent.Type.MouseButtonDblClick,
        QPointF(0, 0),
        QPointF(0, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    cell.mouseDoubleClickEvent(dbl_evt)
    app.processEvents()
    assert cell._is_renaming is True

    original_label_text = cell._label_widget.text()

    # Send Escape through the eventFilter (the real path the widget uses)
    esc_evt = QKeyEvent(
        QEvent.Type.KeyPress,
        Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier,
    )
    result = cell.eventFilter(cell._rename_edit, esc_evt)
    app.processEvents()

    assert result is True, "eventFilter must consume (return True) the Escape key event"
    # rendered contract: rename cancelled, label restored, edit widget gone
    assert cell._is_renaming is False, "Escape must exit rename mode"
    assert cell._rename_edit is None, "rename edit must be removed after Escape"
    assert not cell._label_widget.isHidden(), "label must be visible after Escape"
    assert cell._label_widget.text() == original_label_text, (
        f"Label text must be restored to {original_label_text!r}, got {cell._label_widget.text()!r}"
    )


# MED: exact "1.50e+03"
def test_sensor_cell_update_value_large_number(app, mock_channel_mgr, buffer_store):
    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)
    reading = Reading(
        channel="Т1 Криостат верх",
        value=1500.0,
        unit="K",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    cell.update_value(reading)
    assert cell._value_widget.text() == "1.50e+03", f"Expected '1.50e+03', got {cell._value_widget.text()!r}"


# MED: exact "5.00e-03"
def test_sensor_cell_update_value_small_number(app, mock_channel_mgr, buffer_store):
    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)
    reading = Reading(
        channel="Т1 Криостат верх",
        value=0.005,
        unit="K",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    cell.update_value(reading)
    assert cell._value_widget.text() == "5.00e-03", f"Expected '5.00e-03', got {cell._value_widget.text()!r}"


def test_sensor_cell_stale_recovery(app, mock_channel_mgr, buffer_store):
    """After refresh marks cell stale, update_value with OK must restore style."""
    cell = SensorCell("Т1", mock_channel_mgr, buffer_store)
    # Push a reading to set status to OK
    reading = Reading(
        channel="Т1 Криостат верх",
        value=4.2,
        unit="K",
        timestamp=datetime.now(UTC),
        status=ChannelStatus.OK,
        instrument_id="lakeshore_218s",
    )
    cell.update_value(reading)
    assert cell._last_status == ChannelStatus.OK
    assert cell._data_stale is False
    # Simulate stale via empty buffer refresh
    cell._data_stale = False  # reset guard
    cell._buffer = buffer_store  # empty
    cell.refresh_from_buffer()
    assert cell._data_stale is True
    # Push another OK reading — must re-apply OK border
    cell.update_value(reading)
    assert cell._data_stale is False
    assert cell._last_status == ChannelStatus.OK
    # Verify border is not stale anymore
    ss = cell.styleSheet()
    assert theme.STATUS_OK in ss
