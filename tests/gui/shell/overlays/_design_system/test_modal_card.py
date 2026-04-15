from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from cryodaq.gui.shell.overlays._design_system import ModalCard


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_modal_card_centers_on_resize(app):
    card = ModalCard(max_width=500)
    card.resize(1200, 800)
    card.set_content(QLabel("content"))
    card.show()
    app.processEvents()

    rect = card.card_widget().geometry()
    assert rect.center().x() == pytest.approx(card.rect().center().x(), abs=1)
    assert rect.center().y() == pytest.approx(card.rect().center().y(), abs=1)


def test_modal_card_backdrop_click_emits_closed(app):
    card = ModalCard()
    card.resize(800, 600)
    card.set_content(QLabel("content"))
    card.show()
    app.processEvents()

    received: list[bool] = []
    card.closed.connect(lambda: received.append(True))
    QTest.mouseClick(card._backdrop, Qt.MouseButton.LeftButton)
    assert received == [True]


def test_modal_card_escape_emits_closed(app):
    card = ModalCard()
    card.resize(800, 600)
    card.set_content(QLabel("content"))
    card.show()
    card.activateWindow()
    card.setFocus()
    app.processEvents()

    received: list[bool] = []
    card.closed.connect(lambda: received.append(True))
    QTest.keyClick(card, Qt.Key.Key_Escape)
    assert received == [True]


def test_modal_card_close_button_emits_closed(app):
    card = ModalCard()
    card.resize(800, 600)
    card.set_content(QLabel("content"))
    card.show()
    app.processEvents()

    received: list[bool] = []
    card.closed.connect(lambda: received.append(True))
    card._close_button.click()
    assert received == [True]


def test_modal_card_max_width_respected(app):
    card = ModalCard(max_width=420)
    wide = QWidget()
    wide.setMinimumWidth(1200)
    card.resize(1600, 900)
    card.set_content(wide)
    card.show()
    app.processEvents()

    assert card.card_widget().width() <= 420


def test_modal_card_max_height_percentage_respected(app):
    card = ModalCard(max_height_vh_pct=60)
    tall = QWidget()
    tall.setMinimumHeight(2000)
    card.resize(1000, 900)
    card.set_content(tall)
    card.show()
    app.processEvents()

    assert card.card_widget().height() <= 540


def test_modal_card_set_content_swaps_widget(app):
    card = ModalCard()
    first = QLabel("first")
    second = QLabel("second")

    card.set_content(first)
    assert first.parent() is not None
    card.set_content(second)

    assert first.parent() is None
    assert second.parent() is not None
    assert card._content_widget is second

