"""Standalone visual showcase for Phase I.1 overlay primitives."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays._design_system import (
    BentoGrid,
    DrillDownBreadcrumb,
    ModalCard,
)


def _placeholder_tile(title: str) -> QFrame:
    tile = QFrame()
    tile.setObjectName("showcaseTile")
    tile.setMinimumHeight(120)
    tile.setStyleSheet(
        f"#showcaseTile {{"
        f"background: {theme.SURFACE_PANEL};"
        f"border: 1px solid {theme.BORDER};"
        f"border-radius: {theme.RADIUS_MD}px;"
        f"}}"
    )
    layout = QVBoxLayout(tile)
    layout.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
    layout.setSpacing(theme.SPACE_2)

    title_label = QLabel(title)
    title_label.setStyleSheet(
        f"color: {theme.FOREGROUND};"
        f"font-family: '{theme.FONT_BODY}';"
        f"font-size: {theme.FONT_SIZE_BASE}px;"
        f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
    )
    body_label = QLabel("Sample overlay content")
    body_label.setStyleSheet(
        f"color: {theme.MUTED_FOREGROUND};"
        f"font-family: '{theme.FONT_BODY}';"
        f"font-size: {theme.FONT_SIZE_SM}px;"
    )
    body_label.setWordWrap(True)
    layout.addWidget(title_label)
    layout.addWidget(body_label)
    layout.addStretch()
    return tile


def build_showcase() -> QMainWindow:
    window = QMainWindow()
    window.setWindowTitle("CryoDAQ Overlay Design System Showcase")
    window.resize(1440, 960)

    root = QWidget()
    root.setStyleSheet(f"background: {theme.SURFACE_BG};")
    window.setCentralWidget(root)
    root_layout = QVBoxLayout(root)
    root_layout.setContentsMargins(0, 0, 0, 0)
    root_layout.setSpacing(0)

    modal = ModalCard(root)
    root_layout.addWidget(modal)

    content = QWidget()
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(0, 0, 0, 0)
    content_layout.setSpacing(theme.SPACE_4)

    breadcrumb = DrillDownBreadcrumb("\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430", show_close_button=False)
    content_layout.addWidget(breadcrumb)

    intro = QLabel("Sample overlay content")
    intro.setStyleSheet(
        f"color: {theme.MUTED_FOREGROUND};"
        f"font-family: '{theme.FONT_BODY}';"
        f"font-size: {theme.FONT_SIZE_SM}px;"
    )
    content_layout.addWidget(intro)

    grid = BentoGrid()
    grid.add_tile(_placeholder_tile("Executive tile"), col=0, row=0, col_span=4, row_span=1)
    grid.add_tile(_placeholder_tile("Live tile"), col=4, row=0, col_span=4, row_span=1)
    grid.add_tile(_placeholder_tile("Dense tile"), col=8, row=0, col_span=4, row_span=1)
    grid.add_tile(_placeholder_tile("Wide tile"), col=0, row=1, col_span=8, row_span=1)
    grid.add_tile(_placeholder_tile("Tall tile"), col=8, row=1, col_span=4, row_span=2)
    grid.add_tile(_placeholder_tile("Support tile"), col=0, row=2, col_span=4, row_span=1)
    grid.add_tile(_placeholder_tile("Telemetry tile"), col=4, row=2, col_span=4, row_span=1)
    content_layout.addWidget(grid, 1)

    modal.set_content(content)
    modal.closed.connect(window.close)
    breadcrumb.back_requested.connect(window.close)
    return window


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = build_showcase()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
