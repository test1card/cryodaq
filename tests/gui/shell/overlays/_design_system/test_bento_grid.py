from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays._design_system import BentoGrid


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_bento_grid_add_tile_places_widget(app):
    grid = BentoGrid()
    tile = QLabel("A")
    grid.add_tile(tile, col=2, row=1, col_span=3, row_span=2)

    index = grid._layout.indexOf(tile)
    row, col, row_span, col_span = grid._layout.getItemPosition(index)
    assert (row, col, row_span, col_span) == (1, 2, 2, 3)


def test_bento_grid_auto_flow_advances_columns(app):
    grid = BentoGrid(columns=4)
    first = QLabel("A")
    second = QLabel("B")
    grid.add_tile(first)
    grid.add_tile(second)

    index_first = grid._layout.indexOf(first)
    index_second = grid._layout.indexOf(second)
    assert grid._layout.getItemPosition(index_first)[:2] == (0, 0)
    assert grid._layout.getItemPosition(index_second)[:2] == (0, 1)


def test_bento_grid_col_span_validation(app):
    grid = BentoGrid(columns=4)
    with pytest.raises(ValueError):
        grid.add_tile(QLabel("bad"), col=3, row=0, col_span=2)


def test_bento_grid_rejects_negative_coordinates(app):
    grid = BentoGrid(columns=4)
    with pytest.raises(ValueError):
        grid.add_tile(QLabel("bad"), col=-1, row=0)


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


def test_bento_grid_gap_defaults_to_theme_spacing(app):
    grid = BentoGrid()
    assert grid._layout.horizontalSpacing() == theme.SPACE_3
    assert grid._layout.verticalSpacing() == theme.SPACE_3


def test_bento_grid_gap_override_respected(app):
    grid = BentoGrid(gap=20)
    assert grid._layout.horizontalSpacing() == 20
    assert grid._layout.verticalSpacing() == 20
