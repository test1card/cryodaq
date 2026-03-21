from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import (
    QFrame,
    QFormLayout,
    QGroupBox,
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


def apply_status_label_style(label: QLabel, level: str, *, bold: bool = False) -> None:
    base = {
        "muted": "#888888",
        "info": "#888888",
        "success": "#2ECC40",
        "warning": "#FFDC00",
        "error": "#FF4136",
        "accent": "#58a6ff",
    }.get(level, "#888888")
    weight = "font-weight: bold;" if bold else ""
    label.setStyleSheet(f"color: {base}; {weight}".strip())


def apply_button_style(button: QPushButton, variant: str = "neutral", *, compact: bool = False) -> None:
    variants = {
        "neutral": ("#21262d", "#30363d", "#c9d1d9"),
        "primary": ("#238636", "#2ea043", "#ffffff"),
        "warning": ("#9e6a03", "#d29922", "#ffffff"),
        "danger": ("#da3633", "#f85149", "#ffffff"),
    }
    bg, hover, fg = variants.get(variant, variants["neutral"])
    padding = "4px 8px" if compact else "6px 14px"
    radius = "3px" if compact else "4px"
    button.setStyleSheet(
        "QPushButton { "
        f"background: {bg}; color: {fg}; border: 1px solid #30363d; border-radius: {radius}; padding: {padding}; "
        "}"
        f"QPushButton:hover {{ background: {hover}; }}"
        "QPushButton:disabled { background: #555555; color: #c9d1d9; }"
    )


def apply_group_box_style(box: QGroupBox, accent: str = "#58a6ff") -> None:
    box.setStyleSheet(
        "QGroupBox { "
        f"color: {accent}; border: 1px solid #30363d; border-radius: 4px; padding-top: 12px; "
        "}"
    )


def apply_panel_frame_style(
    frame: QFrame,
    *,
    background: str = "#1E1E1E",
    border: str = "#333",
    radius: int = 4,
) -> None:
    frame.setStyleSheet(
        f"{frame.__class__.__name__} {{ background-color: {background}; border: 1px solid {border}; border-radius: {radius}px; }}"
    )


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


def snap_x_range(
    plot_item: object,
    now: float,
    window_s: float,
    earliest: float,
    margin_frac: float = 0.05,
) -> None:
    """Set X range, snapping left edge to earliest data point.

    Prevents empty space when data is younger than the window.
    """
    x_min = now - window_s
    if earliest < now:
        margin = (now - earliest) * margin_frac
        x_min = max(x_min, earliest - margin)
    plot_item.setXRange(x_min, now, padding=0)
