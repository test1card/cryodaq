"""Hero readout — large primary numeric value with unit and annotation."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from cryodaq.gui import theme


class HeroReadout(QWidget):
    """Large primary number display for dashboard phase content."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("heroReadout")
        self._build_ui()
        self.set_value(None, "")

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._value_label = QLabel("\u2014")
        self._value_label.setObjectName("heroReadoutValue")
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._value_label.setStyleSheet(
            f"#heroReadoutValue {{ "
            f"color: {theme.FOREGROUND}; "
            f"font-family: '{theme.FONT_MONO}'; "
            f"font-size: {theme.FONT_SIZE_2XL}px; "
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD}; "
            f"}}"
        )
        layout.addWidget(self._value_label)

        self._unit_label = QLabel("")
        self._unit_label.setObjectName("heroReadoutUnit")
        self._unit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._unit_label.setStyleSheet(
            f"#heroReadoutUnit {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_SM}px; "
            f"}}"
        )
        layout.addWidget(self._unit_label)

        self._annotation_label = QLabel("")
        self._annotation_label.setObjectName("heroReadoutAnnotation")
        self._annotation_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._annotation_label.setStyleSheet(
            f"#heroReadoutAnnotation {{ "
            f"color: {theme.MUTED_FOREGROUND}; "
            f"font-family: '{theme.FONT_BODY}'; "
            f"font-size: {theme.FONT_SIZE_XS}px; "
            f"}}"
        )
        layout.addWidget(self._annotation_label)

    def set_value(
        self,
        value: float | None,
        unit: str,
        annotation: str | None = None,
    ) -> None:
        if value is None:
            self._value_label.setText("\u2014")
        else:
            if abs(value) >= 1000 or (abs(value) < 0.01 and value != 0):
                self._value_label.setText(f"{value:.2e}")
            else:
                self._value_label.setText(f"{value:.2f}")
        self._unit_label.setText(unit)
        self._annotation_label.setText(annotation or "")
        self._annotation_label.setVisible(bool(annotation))
