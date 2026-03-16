from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import (
    QFrame,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


def setup_standard_table(table: QTableWidget, headers: Iterable[str]) -> None:
    header_list = list(headers)
    table.setColumnCount(len(header_list))
    table.setHorizontalHeaderLabels(header_list)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)


def build_action_row(*widgets: QWidget, add_stretch: bool = False) -> QHBoxLayout:
    layout = QHBoxLayout()
    for widget in widgets:
        layout.addWidget(widget)
    if add_stretch:
        layout.addStretch(1)
    return layout


def add_form_rows(form: QFormLayout, rows: Iterable[tuple[str, QWidget]]) -> None:
    for label, widget in rows:
        form.addRow(label, widget)


class StatusBanner(QLabel):
    _STYLES = {
        "info": "color: #888888;",
        "success": "color: #2ECC40;",
        "warning": "color: #FFDC00;",
        "error": "color: #FF4136;",
    }

    def __init__(self, text: str = " ", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.show_info(text)

    def clear_message(self) -> None:
        self.show_info(" ")

    def show_info(self, text: str) -> None:
        self._apply("info", text)

    def show_success(self, text: str) -> None:
        self._apply("success", text)

    def show_warning(self, text: str) -> None:
        self._apply("warning", text)

    def show_error(self, text: str) -> None:
        self._apply("error", text)

    def _apply(self, level: str, text: str) -> None:
        self.setText(text)
        self.setStyleSheet(self._STYLES[level])


def create_panel_root(widget: QWidget) -> QVBoxLayout:
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)
    return layout


class PanelHeader(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background-color: #11151d; border: 1px solid #30363d; border-radius: 6px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet("color: #f0f6fc; font-weight: bold;")
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            subtitle_label.setStyleSheet("color: #8b949e;")
            layout.addWidget(subtitle_label)
