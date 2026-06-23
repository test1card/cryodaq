from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel

from cryodaq.gui.shell.overlays._design_system import (
    BentoGrid,
    DrillDownBreadcrumb,
    ModalCard,
)
from cryodaq.gui.shell.overlays._design_system._showcase import build_showcase


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


# HIGH: assert modal content + breadcrumb visibility + seven tile labels +
#       bento grid positions/spans
def test_showcase_builds_all_phase_i1_primitives(app):
    window = build_showcase()
    window.show()
    app.processEvents()

    assert window.windowTitle() == "CryoDAQ Overlay Design System Showcase"

    # ModalCard present
    modal = window.findChild(ModalCard)
    assert modal is not None, "ModalCard must be present in showcase"

    # DrillDownBreadcrumb present and shows "Аналитика"
    breadcrumb = window.findChild(DrillDownBreadcrumb)
    assert breadcrumb is not None, "DrillDownBreadcrumb must be present"
    assert "Аналитика" in breadcrumb._overlay_label.toolTip() or \
           "Аналитика" in breadcrumb._overlay_label.text(), (
        f"Breadcrumb must show 'Аналитика', got text={breadcrumb._overlay_label.text()!r}"
    )

    # BentoGrid present
    grid = window.findChild(BentoGrid)
    assert grid is not None, "BentoGrid must be present in showcase"

    # Collect all tile title labels (the first QLabel child of each showcaseTile QFrame)
    all_frames = window.findChildren(QFrame, "showcaseTile")
    assert len(all_frames) == 7, (
        f"Expected 7 showcase tiles, found {len(all_frames)}: "
        f"{[f.objectName() for f in all_frames]}"
    )

    # Collect the title text from each tile (first QLabel child)
    tile_titles = []
    for frame in all_frames:
        labels = frame.findChildren(QLabel)
        if labels:
            tile_titles.append(labels[0].text())

    expected_titles = {
        "Executive tile",
        "Live tile",
        "Wide tile",
        "Tall tile",
        "Support tile",
        "Dense tile",
        "Telemetry tile",
    }
    found_titles = set(tile_titles)
    assert found_titles == expected_titles, (
        f"Tile titles mismatch.\nExpected: {sorted(expected_titles)}\n"
        f"Got:      {sorted(found_titles)}"
    )

    # Verify bento grid layout positions/spans via QGridLayout
    layout = grid._layout
    # Expected: (row, col, row_span, col_span) for each tile title
    expected_positions = {
        "Executive tile": (0, 0, 1, 4),
        "Live tile":      (0, 4, 1, 4),
        "Wide tile":      (1, 0, 1, 5),
        "Tall tile":      (1, 5, 2, 3),
        "Support tile":   (2, 0, 1, 5),
        "Dense tile":     (3, 0, 1, 4),
        "Telemetry tile": (3, 4, 1, 4),
    }
    for frame in all_frames:
        labels = frame.findChildren(QLabel)
        if not labels:
            continue
        title = labels[0].text()
        if title not in expected_positions:
            continue
        exp_row, exp_col, exp_row_span, exp_col_span = expected_positions[title]
        idx = layout.indexOf(frame)
        assert idx >= 0, f"Tile '{title}' not found in grid layout"
        row, col, row_span, col_span = layout.getItemPosition(idx)
        assert (row, col, row_span, col_span) == (exp_row, exp_col, exp_row_span, exp_col_span), (
            f"Tile '{title}': expected position (row={exp_row}, col={exp_col}, "
            f"row_span={exp_row_span}, col_span={exp_col_span}), "
            f"got (row={row}, col={col}, row_span={row_span}, col_span={col_span})"
        )
