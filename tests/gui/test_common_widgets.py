from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QTableWidget

from cryodaq.gui.widgets.common import (
    StatusBanner,
    add_form_rows,
    build_action_row,
    setup_standard_table,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_setup_standard_table_applies_shared_selection_policy() -> None:
    _app()
    table = QTableWidget()

    setup_standard_table(table, ["A", "B"])

    assert table.columnCount() == 2
    assert table.horizontalHeaderItem(0).text() == "A"
    assert table.selectionBehavior() == QTableWidget.SelectionBehavior.SelectRows
    assert table.selectionMode() == QTableWidget.SelectionMode.SingleSelection


def test_build_action_row_keeps_widgets_and_optional_stretch() -> None:
    _app()
    left = QLabel("left")
    right = QLabel("right")

    layout = build_action_row(left, right, add_stretch=True)

    assert layout.count() == 3
    assert layout.itemAt(0).widget() is left
    assert layout.itemAt(1).widget() is right
    assert layout.itemAt(2).spacerItem() is not None


def test_status_banner_switches_levels() -> None:
    _app()
    banner = StatusBanner()

    banner.show_error("Ошибка")
    assert banner.text() == "Ошибка"
    assert "#FF4136" in banner.styleSheet()

    banner.show_success("Готово")
    assert banner.text() == "Готово"
    assert "#2ECC40" in banner.styleSheet()


def test_add_form_rows_adds_widgets_in_order() -> None:
    _app()
    from PySide6.QtWidgets import QFormLayout, QWidget

    host = QWidget()
    form = QFormLayout(host)
    first = QLabel("one")
    second = QLabel("two")

    add_form_rows(form, [("Первый:", first), ("Второй:", second)])

    assert form.rowCount() == 2
    assert form.itemAt(0, QFormLayout.ItemRole.LabelRole).widget().text() == "Первый:"
    assert form.itemAt(1, QFormLayout.ItemRole.FieldRole).widget() is second
