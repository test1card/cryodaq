from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays._design_system import BentoGrid


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_bento_grid_default_columns_is_eight(app):
    # AD-001: canonical 8-column grid.
    grid = BentoGrid()
    assert grid.columns == 8


def test_bento_grid_add_tile_places_widget(app):
    grid = BentoGrid()
    tile = QLabel("A")
    grid.add_tile(tile, col=2, row=1, col_span=3, row_span=2)

    index = grid._layout.indexOf(tile)
    row, col, row_span, col_span = grid._layout.getItemPosition(index)
    assert (row, col, row_span, col_span) == (1, 2, 2, 3)


def test_bento_grid_requires_explicit_col_row(app):
    # Auto-flow is not part of the canonical contract. add_tile uses
    # keyword-only col/row so calling without them is a TypeError.
    grid = BentoGrid(columns=4)
    with pytest.raises(TypeError):
        grid.add_tile(QLabel("no-coords"))  # type: ignore[call-arg]


def test_bento_grid_col_span_validation(app):
    grid = BentoGrid(columns=4)
    with pytest.raises(ValueError):
        grid.add_tile(QLabel("bad"), col=3, row=0, col_span=2)


def test_bento_grid_rejects_negative_coordinates(app):
    grid = BentoGrid(columns=4)
    with pytest.raises(ValueError):
        grid.add_tile(QLabel("bad"), col=-1, row=0)
    with pytest.raises(ValueError):
        grid.add_tile(QLabel("bad"), col=0, row=-1)


def test_bento_grid_rejects_zero_or_negative_spans(app):
    grid = BentoGrid(columns=4)
    with pytest.raises(ValueError):
        grid.add_tile(QLabel("bad"), col=0, row=0, col_span=0)
    with pytest.raises(ValueError):
        grid.add_tile(QLabel("bad"), col=0, row=0, row_span=0)


def test_bento_grid_rejects_overlap(app):
    # Two tiles cannot share any cell.
    grid = BentoGrid()
    grid.add_tile(QLabel("first"), col=0, row=0, col_span=4, row_span=2)
    # Overlap on row 1 cols 2..4 — must raise.
    with pytest.raises(ValueError):
        grid.add_tile(QLabel("overlap"), col=2, row=1, col_span=3, row_span=1)


def test_bento_grid_adjacent_tiles_allowed(app):
    # Edge-touching (not overlapping) placement succeeds.
    grid = BentoGrid()
    grid.add_tile(QLabel("left"), col=0, row=0, col_span=4, row_span=1)
    grid.add_tile(QLabel("right"), col=4, row=0, col_span=4, row_span=1)
    grid.add_tile(QLabel("below"), col=0, row=1, col_span=8, row_span=1)
    assert grid._layout.count() == 3


def test_bento_grid_clear_tiles_removes_all(app):
    grid = BentoGrid()
    a = QLabel("A")
    b = QLabel("B")
    grid.add_tile(a, col=0, row=0)
    grid.add_tile(b, col=1, row=0)

    grid.clear_tiles()
    assert grid._layout.count() == 0
    assert a.parent() is None
    assert b.parent() is None
    # Occupancy map must be empty so re-adding in cleared cells works.
    grid.add_tile(QLabel("C"), col=0, row=0)


def test_bento_grid_gap_defaults_to_theme_spacing(app):
    grid = BentoGrid()
    assert grid._layout.horizontalSpacing() == theme.SPACE_3
    assert grid._layout.verticalSpacing() == theme.SPACE_3


def test_bento_grid_gap_override_respected(app):
    grid = BentoGrid(gap=20)
    assert grid._layout.horizontalSpacing() == 20
    assert grid._layout.verticalSpacing() == 20


def test_bento_grid_row_span_affects_rendered_height(app):
    host = QWidget()
    host.resize(900, 600)
    grid = BentoGrid(parent=host, columns=4)
    grid.setGeometry(host.rect())

    wide = QLabel("wide")
    tall = QLabel("tall")
    support = QLabel("support")
    for tile in (wide, tall, support):
        tile.setMinimumHeight(100)

    grid.add_tile(wide, col=0, row=0, col_span=3, row_span=1)
    grid.add_tile(tall, col=3, row=0, col_span=1, row_span=2)
    grid.add_tile(support, col=0, row=1, col_span=3, row_span=1)

    host.show()
    app.processEvents()

    assert tall.height() > wide.height() * 1.7
