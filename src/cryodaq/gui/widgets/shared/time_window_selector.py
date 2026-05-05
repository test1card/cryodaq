from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from cryodaq.gui import theme
from cryodaq.gui.state.time_window import TimeWindow

_WINDOW_OPTIONS: tuple[TimeWindow, ...] = (
    TimeWindow.MIN_1,
    TimeWindow.HOUR_1,
    TimeWindow.HOUR_6,
    TimeWindow.HOUR_24,
    TimeWindow.ALL,
)


class TimeWindowSelector(QWidget):
    """5-button time-window selector emitting TimeWindow enum on change.

    Default: TimeWindow.HOUR_1.
    Mirrors PredictionWidget's horizon selector pattern.
    """

    window_changed = Signal(object)  # emits TimeWindow

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current: TimeWindow = TimeWindow.HOUR_1
        self._buttons: dict[TimeWindow, QPushButton] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)
        for window in _WINDOW_OPTIONS:
            btn = QPushButton(window.label)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked, w=window: self.set_window(w))
            self._buttons[window] = btn
            layout.addWidget(btn)
        self._apply_styles()

    def _apply_styles(self) -> None:
        for window, btn in self._buttons.items():
            checked = window == self._current
            if btn.isChecked() != checked:
                btn.setChecked(checked)
            if checked:
                bg, fg, border = theme.ACCENT, theme.ON_ACCENT, theme.ACCENT
            else:
                bg = theme.SURFACE_MUTED
                fg = theme.FOREGROUND
                border = theme.BORDER_SUBTLE
            btn.setStyleSheet(
                f"QPushButton {{"
                f" background-color: {bg};"
                f" color: {fg};"
                f" border: 1px solid {border};"
                f" border-radius: {theme.RADIUS_SM}px;"
                f" padding: {theme.SPACE_0}px {theme.SPACE_2}px;"
                f" font-size: {theme.FONT_LABEL_SIZE}px;"
                f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
                f"}}"
            )

    def get_window(self) -> TimeWindow:
        return self._current

    def set_window(self, window: TimeWindow) -> None:
        if window == self._current:
            return
        self._current = window
        self._apply_styles()
        self.window_changed.emit(window)
