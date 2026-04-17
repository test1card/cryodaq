"""Standalone visual showcase for Phase I.1 overlay primitives."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QMainWindow, QVBoxLayout, QWidget

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays._design_system import (
    BentoGrid,
    DrillDownBreadcrumb,
    ModalCard,
)


def _placeholder_tile(title: str, description: str) -> QFrame:
    tile = QFrame()
    tile.setObjectName("showcaseTile")
    tile.setMinimumHeight(120)
    tile.setStyleSheet(
        f"#showcaseTile {{"
        f"background: {theme.SURFACE_PANEL};"
        f"border: 1px solid {theme.BORDER};"
        f"border-radius: {theme.RADIUS_MD}px;"
        f"}}"
        f"#showcaseTile QLabel {{"
        f"background: transparent;"
        f"border: none;"
        f"}}"
    )
    layout = QVBoxLayout(tile)
    layout.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
    layout.setSpacing(theme.SPACE_2)

    title_label = QLabel(title)
    title_label.setStyleSheet(
        f"background: transparent;"
        f"color: {theme.FOREGROUND};"
        f"font-family: '{theme.FONT_BODY}';"
        f"font-size: {theme.FONT_SIZE_BASE}px;"
        f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
    )
    body_label = QLabel(description)
    body_label.setStyleSheet(
        f"background: transparent;"
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

    breadcrumb = DrillDownBreadcrumb(
        "\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430", show_close_button=False
    )
    content_layout.addWidget(breadcrumb)

    # Canonical 8-column Bento layout (AD-001). Composition:
    #   Row 0:  Exec half(0..4)  |  Live half(4..8)
    #   Row 1:  Wide left(0..5)  |  Tall right(5..8, row_span=2)
    #   Row 2:  Support(0..5) under Wide; Tall still covers (5..8)
    #   Row 3:  Dense half(0..4) |  Telemetry half(4..8)
    grid = BentoGrid()
    grid.add_tile(
        _placeholder_tile(
            "Executive tile",
            "Executive KPI: large numeric readout with delta.",
        ),
        col=0,
        row=0,
        col_span=4,
        row_span=1,
    )
    grid.add_tile(
        _placeholder_tile(
            "Live tile",
            "Real-time indicator without pulse.",
        ),
        col=4,
        row=0,
        col_span=4,
        row_span=1,
    )
    grid.add_tile(
        _placeholder_tile(
            "Wide tile",
            "Time-series chart, 5-column span in 8-column grid.",
        ),
        col=0,
        row=1,
        col_span=5,
        row_span=1,
    )
    grid.add_tile(
        _placeholder_tile(
            "Tall tile",
            "Vertical scroll content, 2-row span on the right.",
        ),
        col=5,
        row=1,
        col_span=3,
        row_span=2,
    )
    grid.add_tile(
        _placeholder_tile(
            "Support tile",
            "Secondary context info; sits under Wide.",
        ),
        col=0,
        row=2,
        col_span=5,
        row_span=1,
    )
    grid.add_tile(
        _placeholder_tile(
            "Dense tile",
            "Compressed multi-value table.",
        ),
        col=0,
        row=3,
        col_span=4,
        row_span=1,
    )
    grid.add_tile(
        _placeholder_tile(
            "Telemetry tile",
            "Multi-channel live readout.",
        ),
        col=4,
        row=3,
        col_span=4,
        row_span=1,
    )
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
