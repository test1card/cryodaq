from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.overlays._design_system import DrillDownBreadcrumb


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_breadcrumb_back_requested_emitted(app):
    breadcrumb = DrillDownBreadcrumb("Архив")
    received: list[bool] = []
    breadcrumb.back_requested.connect(lambda: received.append(True))

    breadcrumb._back_button.click()
    assert received == [True]


def test_breadcrumb_close_requested_emitted(app):
    breadcrumb = DrillDownBreadcrumb("Архив")
    received: list[bool] = []
    breadcrumb.close_requested.connect(lambda: received.append(True))

    breadcrumb._close_button.click()
    assert received == [True]


# LOW: assert _overlay_label.text() equals/elides the new name (not just tooltip)
def test_breadcrumb_overlay_name_updates_display(app):
    breadcrumb = DrillDownBreadcrumb("Архив")
    breadcrumb.resize(500, 32)
    new_name = "Новое имя"
    breadcrumb.set_overlay_name(new_name)
    app.processEvents()

    # tooltip must always be the full name
    assert new_name in breadcrumb._overlay_label.toolTip(), (
        f"Tooltip must contain full name {new_name!r}, "
        f"got {breadcrumb._overlay_label.toolTip()!r}"
    )
    # _overlay_label.text() must equal or elide the new name
    label_text = breadcrumb._overlay_label.text()
    assert label_text, "_overlay_label.text() must not be empty after set_overlay_name"
    # Either the full name fits, or an elided prefix is shown (ends with "…")
    assert new_name.startswith(label_text.rstrip("…")) or label_text == new_name, (
        f"_overlay_label.text() must equal or elide {new_name!r}, got {label_text!r}"
    )


def test_breadcrumb_back_label_updates_button(app):
    breadcrumb = DrillDownBreadcrumb("Архив")
    breadcrumb.set_back_label("Аналитика")
    assert "Аналитика" in breadcrumb._back_button.text()


def test_breadcrumb_can_hide_close_button(app):
    breadcrumb = DrillDownBreadcrumb("Архив", show_close_button=False)
    assert breadcrumb._close_button.isHidden()
