"""Shared time-window selector.

Renders the 4-button (or optional 5-button) row for historical
plots. Clicking a button calls the global controller's set_window;
the broadcast updates every subscribed plot synchronously.

Phase III.A decoupling: checked-button background is `ACCENT` (UI
activation); safety-green is reserved for the status-display tier.
Unchecked buttons use `SURFACE_MUTED` + `FOREGROUND`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from cryodaq.gui import theme
from cryodaq.gui.state.time_window import TimeWindow, get_time_window_controller


class TimeWindowSelector(QWidget):
    """Button row that drives the global time-window controller."""

    def __init__(
        self,
        show_6h: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._buttons: dict[TimeWindow, QPushButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._build_ui(show_6h)
        controller = get_time_window_controller()
        self._sync_ui(controller.get_window())
        controller.window_changed.connect(self._sync_ui)

    def _build_ui(self, show_6h: bool) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)
        options = [TimeWindow.MIN_1, TimeWindow.HOUR_1]
        if show_6h:
            options.append(TimeWindow.HOUR_6)
        options.extend([TimeWindow.HOUR_24, TimeWindow.ALL])
        for tw in options:
            btn = QPushButton(tw.label, self)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _checked, w=tw: get_time_window_controller().set_window(w))
            self._group.addButton(btn)
            self._buttons[tw] = btn
            self._apply_style(btn, checked=False)
            layout.addWidget(btn)

    def _sync_ui(self, window: TimeWindow) -> None:
        for tw, btn in self._buttons.items():
            checked = tw is window
            if btn.isChecked() != checked:
                btn.setChecked(checked)
            self._apply_style(btn, checked=checked)

    def _apply_style(self, btn: QPushButton, *, checked: bool) -> None:
        if checked:
            # Phase III.A: UI activation renders in ACCENT, never in a
            # status-tier token (safety colours stay semantic).
            bg, fg = theme.ACCENT, theme.ON_ACCENT
            border = theme.ACCENT
        else:
            bg, fg = theme.SURFACE_MUTED, theme.FOREGROUND
            border = theme.BORDER_SUBTLE
        btn.setStyleSheet(
            f"QPushButton {{"
            f" background-color: {bg};"
            f" color: {fg};"
            f" border: 1px solid {border};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f" padding: {theme.SPACE_1}px {theme.SPACE_3}px;"
            f" font-family: '{theme.FONT_BODY}';"
            f" font-size: {theme.FONT_LABEL_SIZE}px;"
            f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
            f"}}"
        )
