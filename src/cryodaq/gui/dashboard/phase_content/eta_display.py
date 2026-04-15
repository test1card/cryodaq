"""ETA display — estimated time of arrival with confidence range.

Status: dashboard usage removed in B.5.6 (compact phase strip).
Reserved for B.10 Analytics overlay where hero treatment fits the
context (full screen real estate, drill-down view).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from cryodaq.gui import theme


def _format_duration_ru(seconds: float) -> str:
    """Format seconds as compact Russian duration: 14ч 20мин, 45мин, 30с."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}\u0441"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}\u043c\u0438\u043d"
    hours = minutes // 60
    rem = minutes % 60
    if rem == 0:
        return f"{hours}\u0447"
    return f"{hours}\u0447 {rem}\u043c\u0438\u043d"


class EtaDisplay(QWidget):
    """ETA hero display with optional confidence range."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("etaDisplay")
        self._build_ui()
        self.set_eta(None)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._title_label = QLabel("ETA")
        self._title_label.setObjectName("etaDisplayTitle")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet(
            f"#etaDisplayTitle {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"}}"
        )
        layout.addWidget(self._title_label)

        self._value_label = QLabel("\u2014")
        self._value_label.setObjectName("etaDisplayValue")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_label.setStyleSheet(
            f"#etaDisplayValue {{ "
            f"color: {theme.FOREGROUND}; "
            f"font-family: '{theme.FONT_MONO}'; "
            f"font-size: {theme.FONT_SIZE_2XL}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"}}"
        )
        layout.addWidget(self._value_label)

        self._confidence_label = QLabel("")
        self._confidence_label.setObjectName("etaDisplayConfidence")
        self._confidence_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._confidence_label.setStyleSheet(
            f"#etaDisplayConfidence {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_XS}px; "
            f"}}"
        )
        layout.addWidget(self._confidence_label)

    def set_eta(
        self,
        seconds: float | None,
        confidence_seconds: float | None = None,
        label: str = "ETA",
    ) -> None:
        self._title_label.setText(label)
        if seconds is None:
            self._value_label.setText(
                "\u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e"
            )  # недоступно
            self._confidence_label.setText("")
            self._confidence_label.setVisible(False)
            return
        self._value_label.setText(_format_duration_ru(seconds))
        if confidence_seconds is not None:
            self._confidence_label.setText(
                f"\u00b1 {_format_duration_ru(confidence_seconds)}"
            )
            self._confidence_label.setVisible(True)
        else:
            self._confidence_label.setText("")
            self._confidence_label.setVisible(False)
