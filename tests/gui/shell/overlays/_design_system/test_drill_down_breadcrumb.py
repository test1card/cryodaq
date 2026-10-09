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
    breadcrumb = DrillDownBreadcrumb("\u0410\u0440\u0445\u0438\u0432")
    received: list[bool] = []
    breadcrumb.back_requested.connect(lambda: received.append(True))

    breadcrumb._back_button.click()
    assert received == [True]


def test_breadcrumb_close_requested_emitted(app):
    breadcrumb = DrillDownBreadcrumb("\u0410\u0440\u0445\u0438\u0432")
    received: list[bool] = []
    breadcrumb.close_requested.connect(lambda: received.append(True))

    breadcrumb._close_button.click()
    assert received == [True]


def test_breadcrumb_overlay_name_updates_display(app):
    breadcrumb = DrillDownBreadcrumb("\u0410\u0440\u0445\u0438\u0432")
    breadcrumb.resize(500, 32)
    breadcrumb.set_overlay_name("\u041d\u043e\u0432\u043e\u0435 \u0438\u043c\u044f")
    app.processEvents()

    assert (
        "\u041d\u043e\u0432\u043e\u0435 \u0438\u043c\u044f" in breadcrumb._overlay_label.toolTip()
    )


def test_breadcrumb_back_label_updates_button(app):
    breadcrumb = DrillDownBreadcrumb("\u0410\u0440\u0445\u0438\u0432")
    breadcrumb.set_back_label("\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430")
    assert (
        "\u0410\u043d\u0430\u043b\u0438\u0442\u0438\u043a\u0430" in breadcrumb._back_button.text()
    )


def test_breadcrumb_can_hide_close_button(app):
    breadcrumb = DrillDownBreadcrumb("\u0410\u0440\u0445\u0438\u0432", show_close_button=False)
    assert breadcrumb._close_button.isHidden()
