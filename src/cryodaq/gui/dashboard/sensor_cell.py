"""Single sensor cell widget for the DynamicSensorGrid.

Shows channel label, current value, unit, and status-colored border.
Supports inline rename (double-click) and right-click context menu.
"""

from __future__ import annotations

import logging
import math
import time

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui import theme
from cryodaq.gui.dashboard.channel_buffer import ChannelBufferStore

logger = logging.getLogger(__name__)

_STALE_THRESHOLD_S = 30.0

# Map actual ChannelStatus enum members to Russian operator labels.
_STATUS_LABELS: dict[ChannelStatus, str] = {
    ChannelStatus.OK: "Норма",
    ChannelStatus.OVERRANGE: "Перегрузка",
    ChannelStatus.UNDERRANGE: "Занижение",
    ChannelStatus.SENSOR_ERROR: "Ошибка датчика",
    ChannelStatus.TIMEOUT: "Таймаут",
}

# Map ChannelStatus to theme status colors.
_STATUS_COLORS: dict[ChannelStatus, str] = {
    ChannelStatus.OK: theme.STATUS_OK,
    ChannelStatus.OVERRANGE: theme.STATUS_FAULT,
    ChannelStatus.UNDERRANGE: theme.STATUS_WARNING,
    ChannelStatus.SENSOR_ERROR: theme.STATUS_FAULT,
    ChannelStatus.TIMEOUT: theme.STATUS_STALE,
}


class SensorCell(QFrame):
    """Single sensor cell in the DynamicSensorGrid.

    Shows: channel label (renameable), current value, unit, status
    color border.

    Updates: pulled by parent grid's refresh() at 1 Hz from
    ChannelBufferStore, and pushed via update_value() when readings
    arrive.

    Interactions:
    - Double-click → inline rename mode
    - Right-click → context menu (rename / hide / plot / history)
    """

    rename_requested = Signal(str, str)  # channel_id, new_name
    hide_requested = Signal(str)  # channel_id
    show_on_plot_requested = Signal(str)  # channel_id
    history_requested = Signal(str)  # channel_id

    def __init__(
        self,
        channel_id: str,
        channel_manager: ChannelManager,
        buffer_store: ChannelBufferStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._channel_id = channel_id
        self._channel_mgr = channel_manager
        self._buffer = buffer_store
        self._last_status: ChannelStatus | None = None
        self._data_stale = True
        self._is_renaming = False
        self._rename_edit: QLineEdit | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setObjectName("sensorCell")
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(2)

        # Channel label (top, dim text, elided)
        self._label_widget = QLabel()
        self._label_widget.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; "
            f"font-family: '{theme.FONT_UI}'; "
            f"font-size: {theme.FONT_LABEL_SIZE}px;"
        )
        self._label_widget.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._label_widget.setWordWrap(False)
        self._label_widget.setMinimumWidth(0)
        root.addWidget(self._label_widget)

        # Value row (center)
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(4)

        self._value_widget = QLabel("\u2014")  # em dash
        self._value_widget.setStyleSheet(
            f"color: {theme.TEXT_PRIMARY}; "
            f"font-family: '{theme.FONT_MONO}'; "
            f"font-size: {theme.FONT_MONO_VALUE_SIZE}px; "
            f"font-weight: {theme.FONT_MONO_VALUE_WEIGHT};"
        )
        value_row.addWidget(self._value_widget)

        self._unit_widget = QLabel("")
        self._unit_widget.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; "
            f"font-family: '{theme.FONT_UI}'; "
            f"font-size: {theme.FONT_LABEL_SIZE}px;"
        )
        value_row.addWidget(self._unit_widget)
        value_row.addStretch()
        root.addLayout(value_row)

        # Status hint (bottom, small text)
        self._status_hint_widget = QLabel(
            "\u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"
        )  # Нет данных
        self._status_hint_widget.setStyleSheet(
            f"color: {theme.TEXT_MUTED}; "
            f"font-family: '{theme.FONT_UI}'; "
            f"font-size: {theme.FONT_LABEL_SIZE - 1}px;"
        )
        root.addWidget(self._status_hint_widget)

        # Initial appearance: stale
        self._apply_stale_style()
        self._refresh_label()

    # ------------------------------------------------------------------
    # Label
    # ------------------------------------------------------------------

    def _refresh_label(self) -> None:
        full_name = self._channel_mgr.get_display_name(self._channel_id)
        self._label_widget.setText(full_name)
        self._label_widget.setToolTip(
            f"\u041f\u043e\u043b\u043d\u043e\u0435 \u0438\u043c\u044f: {full_name}"  # Полное имя:
        )

    # ------------------------------------------------------------------
    # Status styling
    # ------------------------------------------------------------------

    def _apply_status_style(self, status: ChannelStatus) -> None:
        """Update border color based on channel status."""
        border_color = _STATUS_COLORS.get(status, theme.BORDER_SUBTLE)
        self.setStyleSheet(
            f"#sensorCell {{ "
            f"background-color: {theme.SURFACE_CARD}; "
            f"border: 2px solid {border_color}; "
            f"border-radius: {theme.RADIUS_MD}px; "
            f"padding: 4px 8px; "
            f"}}"
        )

    def _apply_stale_style(self) -> None:
        """Apply stale/no-data border style."""
        self.setStyleSheet(
            f"#sensorCell {{ "
            f"background-color: {theme.SURFACE_CARD}; "
            f"border: 2px solid {theme.STATUS_STALE}; "
            f"border-radius: {theme.RADIUS_MD}px; "
            f"padding: 4px 8px; "
            f"}}"
        )

    # ------------------------------------------------------------------
    # Value updates
    # ------------------------------------------------------------------

    def update_value(self, reading: Reading) -> None:
        """Update displayed value and status from a Reading (push path)."""
        if not reading.channel.startswith(self._channel_id):
            return

        value = reading.value
        if isinstance(value, (int, float)) and not math.isnan(value):
            if abs(value) >= 1000 or (abs(value) < 0.01 and value != 0):
                text = f"{value:.2e}"
            else:
                text = f"{value:.2f}"
            self._value_widget.setText(text)
        else:
            self._value_widget.setText("\u2014")

        self._unit_widget.setText(reading.unit or "")
        was_stale = self._data_stale
        self._data_stale = False

        if reading.status != self._last_status or was_stale:
            self._apply_status_style(reading.status)
            self._status_hint_widget.setText(
                _STATUS_LABELS.get(
                    reading.status,
                    "\u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445",  # Нет данных
                )
            )
            self._last_status = reading.status

    def refresh_from_buffer(self) -> None:
        """Pull latest value from buffer store (1 Hz timer path).

        Buffer stores only (timestamp, value) — no ChannelStatus.
        This path tracks staleness by data age; full status comes
        through the update_value() push path.
        """
        last = self._buffer.get_last(self._channel_id)
        if last is None:
            if not self._data_stale:
                self._value_widget.setText("\u2014")
                self._unit_widget.setText("")
                self._apply_stale_style()
                self._status_hint_widget.setText(
                    "\u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445"  # Нет данных
                )
                self._data_stale = True
            return

        timestamp_epoch, value = last
        age = time.time() - timestamp_epoch
        if age > _STALE_THRESHOLD_S:
            if not self._data_stale:
                self._apply_stale_style()
                self._status_hint_widget.setText(
                    "\u0423\u0441\u0442\u0430\u0440\u0435\u043b\u043e"  # Устарело
                )
                self._data_stale = True
            return

        if isinstance(value, (int, float)) and not math.isnan(value):
            if abs(value) >= 1000 or (abs(value) < 0.01 and value != 0):
                text = f"{value:.2e}"
            else:
                text = f"{value:.2f}"
            self._value_widget.setText(text)
        self._data_stale = False

    # ------------------------------------------------------------------
    # Inline rename
    # ------------------------------------------------------------------

    def mouseDoubleClickEvent(self, event):  # noqa: ANN001
        if event.button() == Qt.MouseButton.LeftButton:
            self._enter_rename_mode()
        super().mouseDoubleClickEvent(event)

    def _enter_rename_mode(self) -> None:
        """Replace label with QLineEdit for inline rename."""
        if self._is_renaming:
            return
        self._is_renaming = True
        current_name = self._channel_mgr.get_name(self._channel_id)
        self._rename_edit = QLineEdit(current_name, self)
        self._rename_edit.setPlaceholderText(
            "\u041d\u043e\u0432\u043e\u0435 \u0438\u043c\u044f\u2026"  # Новое имя…
        )
        label_h = self._label_widget.height()
        if label_h > 0:
            self._rename_edit.setFixedHeight(label_h)
        layout = self.layout()
        layout.replaceWidget(self._label_widget, self._rename_edit)
        self._label_widget.hide()
        self._rename_edit.setFocus()
        self._rename_edit.selectAll()
        self._rename_edit.editingFinished.connect(self._commit_rename)
        self._rename_edit.installEventFilter(self)

    def _commit_rename(self) -> None:
        """Save new name and exit rename mode."""
        if not self._is_renaming:
            return
        new_name = self._rename_edit.text().strip()
        if new_name and new_name != self._channel_mgr.get_name(self._channel_id):
            self.rename_requested.emit(self._channel_id, new_name)
        self._exit_rename_mode()

    def _exit_rename_mode(self) -> None:
        if not self._is_renaming:
            return
        layout = self.layout()
        layout.replaceWidget(self._rename_edit, self._label_widget)
        self._rename_edit.deleteLater()
        self._rename_edit = None
        self._label_widget.show()
        self._is_renaming = False
        self._refresh_label()

    def eventFilter(self, obj, event):  # noqa: ANN001
        """Handle Esc key to cancel rename."""
        if (
            obj is self._rename_edit
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self._exit_rename_mode()
            return True
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def contextMenuEvent(self, event):  # noqa: ANN001
        menu = QMenu(self)
        menu.setObjectName("sensorCellContextMenu")

        rename_action = menu.addAction(
            "\u041f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u0442\u044c"  # Переименовать  # noqa: E501
        )
        rename_action.triggered.connect(self._enter_rename_mode)

        hide_action = menu.addAction(
            "\u0421\u043a\u0440\u044b\u0442\u044c"  # Скрыть
        )
        hide_action.triggered.connect(lambda: self.hide_requested.emit(self._channel_id))

        menu.addSeparator()

        plot_action = menu.addAction(
            "\u041f\u043e\u043a\u0430\u0437\u0430\u0442\u044c \u043d\u0430 \u0433\u0440\u0430\u0444\u0438\u043a\u0435"  # Показать на графике  # noqa: E501
        )
        plot_action.triggered.connect(lambda: self.show_on_plot_requested.emit(self._channel_id))

        history_action = menu.addAction(
            "\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u0437\u0430 \u0447\u0430\u0441"  # История за час  # noqa: E501
        )
        history_action.triggered.connect(lambda: self.history_requested.emit(self._channel_id))

        menu.exec(event.globalPos())
