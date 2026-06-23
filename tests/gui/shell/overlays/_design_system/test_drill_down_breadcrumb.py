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


# LOW: assert _overlay_label.text() equals the full name on wide widget
def test_breadcrumb_overlay_name_updates_display(app):
    """Wide widget (500 px) — short name must fit without elision."""
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
    # At 500 px the short name "Новое имя" fits — label must equal the full name.
    label_text = breadcrumb._overlay_label.text()
    assert label_text == new_name, (
        f"At width=500 the full name must fit without elision, "
        f"got {label_text!r} (expected {new_name!r})"
    )


def test_breadcrumb_overlay_name_elided_when_narrow(app):
    """Narrow widget (80 px) — long name must be elided via QFontMetrics.elidedText."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetrics

    breadcrumb = DrillDownBreadcrumb("Архив")
    breadcrumb.resize(80, 32)
    long_name = "Очень длинное название оверлея для теста элизии"
    breadcrumb.set_overlay_name(long_name)
    app.processEvents()

    # tooltip still carries the full name
    assert long_name in breadcrumb._overlay_label.toolTip()

    label_text = breadcrumb._overlay_label.text()
    # Prod: available = max(40, width - reserved); label = fm.elidedText(name, ElideRight, available)
    # Recompute the same way prod does (theme.SPACE_5 = 24).
    reserved = (
        breadcrumb._back_button.sizeHint().width()
        + breadcrumb._separator.sizeHint().width()
        + (breadcrumb._close_button.sizeHint().width() if breadcrumb._close_button.isVisible() else 0)
        + 24  # theme.SPACE_5
    )
    available = max(40, 80 - reserved)
    fm = QFontMetrics(breadcrumb._overlay_label.font())
    expected = fm.elidedText(long_name, Qt.TextElideMode.ElideRight, available)
    assert label_text == expected, (
        f"At width=80 label must match elidedText({long_name!r}, ElideRight, {available}); "
        f"expected {expected!r}, got {label_text!r}"
    )


def test_breadcrumb_back_label_updates_button(app):
    breadcrumb = DrillDownBreadcrumb("Архив")
    breadcrumb.set_back_label("Аналитика")
    assert "Аналитика" in breadcrumb._back_button.text()


def test_breadcrumb_can_hide_close_button(app):
    breadcrumb = DrillDownBreadcrumb("Архив", show_close_button=False)
    assert breadcrumb._close_button.isHidden()
