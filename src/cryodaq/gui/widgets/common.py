from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme


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
        "info": f"color: {theme.TEXT_MUTED};",
        "success": f"color: {theme.STATUS_OK};",
        "warning": f"color: {theme.STATUS_CAUTION};",
        "error": f"color: {theme.STATUS_FAULT};",
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
        "muted": theme.TEXT_MUTED,
        "info": theme.TEXT_MUTED,  # legacy: info == muted in callers
        "success": theme.STATUS_OK,
        "warning": theme.STATUS_CAUTION,  # see StatusBanner note
        "error": theme.STATUS_FAULT,
        "accent": theme.TEXT_ACCENT,
    }.get(level, theme.TEXT_MUTED)
    weight = "font-weight: bold;" if bold else ""
    label.setStyleSheet(f"color: {base}; {weight}".strip())


def apply_button_style(
    button: QPushButton, variant: str = "neutral", *, compact: bool = False
) -> None:
    # Tokens are string-interpolated here. This helper is the single place
    # where button variants are defined — do not duplicate elsewhere.
    variants = {
        "neutral": (theme.SURFACE_ELEVATED, theme.STONE_300, theme.TEXT_SECONDARY),
        "primary": (theme.ACCENT_400, theme.ACCENT_500, theme.TEXT_INVERSE),
        "warning": (theme.STATUS_WARNING, theme.STATUS_CAUTION, theme.TEXT_INVERSE),
        "danger": (theme.STATUS_FAULT, theme.STATUS_FAULT, theme.TEXT_INVERSE),
    }
    bg, hover, fg = variants.get(variant, variants["neutral"])
    padding = (
        f"{theme.SPACE_1}px {theme.SPACE_2}px"
        if compact
        else f"{theme.SPACE_2 - 2}px {theme.SPACE_3 + 2}px"
    )
    radius = f"{theme.RADIUS_SM}px" if compact else f"{theme.RADIUS_MD - 1}px"
    button.setStyleSheet(
        "QPushButton { "
        f"background: {bg}; color: {fg}; border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {radius}; padding: {padding}; "  # noqa: E501
        "}"
        f"QPushButton:hover {{ background: {hover}; }}"
        "QPushButton:disabled { background: "
        + theme.STONE_400
        + "; color: "
        + theme.TEXT_DISABLED
        + "; }"
    )


def apply_group_box_style(box: QGroupBox, accent: str | None = None) -> None:
    color = accent if accent is not None else theme.TEXT_ACCENT
    box.setStyleSheet(
        "QGroupBox { "
        f"color: {color}; border: 1px solid {theme.BORDER_SUBTLE}; border-radius: {theme.RADIUS_MD}px; padding-top: 12px; "  # noqa: E501
        "}"
    )


def apply_panel_frame_style(
    frame: QFrame,
    *,
    background: str | None = None,
    border: str | None = None,
    radius: int | None = None,
) -> None:
    bg = background if background is not None else theme.SURFACE_PANEL
    br = border if border is not None else theme.BORDER_SUBTLE
    rd = radius if radius is not None else theme.RADIUS_MD
    frame.setStyleSheet(
        f"{frame.__class__.__name__} {{ background-color: {bg}; border: 1px solid {br}; border-radius: {rd}px; }}"  # noqa: E501
    )


def create_panel_root(widget: QWidget) -> QVBoxLayout:
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
    layout.setSpacing(theme.SPACE_2)
    return layout


class PanelHeader(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background-color: {theme.SURFACE_CARD}; "
            f"border: 1px solid {theme.BORDER_SUBTLE}; "
            f"border-radius: {theme.RADIUS_MD}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-weight: bold;")
        layout.addWidget(title_label)

        if subtitle:
            subtitle_label = QLabel(subtitle)
            subtitle_label.setWordWrap(True)
            subtitle_label.setStyleSheet(f"color: {theme.TEXT_MUTED};")
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
