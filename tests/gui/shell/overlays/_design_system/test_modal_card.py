from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from cryodaq.gui import theme
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


def test_modal_card_default_max_width_is_spacious(app):
    card = ModalCard()
    wide = QWidget()
    wide.setMinimumWidth(2000)
    card.resize(1600, 900)
    card.set_content(wide)
    card.show()
    app.processEvents()

    assert card.card_widget().width() <= 1280
    assert card.card_widget().width() > 1100


def test_modal_card_leaves_backdrop_visible_on_sides(app):
    card = ModalCard()
    card.resize(1600, 900)
    card.set_content(QLabel("content"))
    card.show()
    app.processEvents()

    card_rect = card.card_widget().geometry()
    assert card_rect.left() >= theme.SPACE_5
    assert card_rect.right() <= card.width() - theme.SPACE_5


def test_modal_card_respects_max_height_vh_pct_default(app):
    card = ModalCard(max_height_vh_pct=80)
    card.resize(1600, 1000)
    card.set_content(QLabel("content"))
    card.show()
    app.processEvents()

    assert card.card_widget().height() <= 800


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


def _is_descendant_of(root: QWidget, w: QWidget | None) -> bool:
    """True if `w` is `root` or any descendant."""
    if w is None:
        return False
    node: QWidget | None = w
    while node is not None:
        if node is root:
            return True
        node = node.parentWidget()
    return False


def test_modal_card_focus_trap_never_escapes(app):
    # RULE-A11Y-001 / RULE-INTER-002 — Tab must not move focus outside
    # the modal. With the close button + two content buttons, cycling
    # forward and backward should always land inside the modal subtree.
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    card = ModalCard()
    card.resize(800, 600)

    content = QWidget()
    layout = QVBoxLayout(content)
    btn1 = QPushButton("A", content)
    btn2 = QPushButton("B", content)
    layout.addWidget(btn1)
    layout.addWidget(btn2)
    card.set_content(content)
    card.show()
    app.processEvents()

    btn1.setFocus()
    # Tab forward several times — every hop must stay inside the modal.
    for _ in range(6):
        card.focusNextPrevChild(True)
        assert _is_descendant_of(card, QApplication.focusWidget())

    # Shift+Tab backward several times — same invariant.
    for _ in range(6):
        card.focusNextPrevChild(False)
        assert _is_descendant_of(card, QApplication.focusWidget())


def test_modal_card_focus_trap_wraps(app):
    # Cycling Tab N times through N focusable descendants returns to start.
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    card = ModalCard()
    card.resize(800, 600)
    content = QWidget()
    layout = QVBoxLayout(content)
    btn1 = QPushButton("A", content)
    btn2 = QPushButton("B", content)
    layout.addWidget(btn1)
    layout.addWidget(btn2)
    card.set_content(content)
    card.show()
    app.processEvents()

    # Enumerate focusable descendants of the shown modal.
    from cryodaq.gui.shell.overlays._design_system.modal_card import (
        _is_focusable_descendant,
    )

    focusable = [w for w in card.findChildren(QWidget) if _is_focusable_descendant(w)]
    assert len(focusable) >= 2, "modal should expose at least 2 focusable descendants"

    focusable[0].setFocus()
    for _ in range(len(focusable)):
        card.focusNextPrevChild(True)
    assert QApplication.focusWidget() is focusable[0]


def test_modal_card_restores_focus_to_opener_on_close(app):
    # RULE-INTER-002 — on programmatic close(), focus returns to the
    # widget that held focus when the modal opened.
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    parent = QWidget()
    parent.resize(400, 300)
    parent_layout = QVBoxLayout(parent)
    opener = QPushButton("Open", parent)
    parent_layout.addWidget(opener)
    parent.show()
    parent.activateWindow()
    app.processEvents()
    opener.setFocus()
    app.processEvents()
    assert opener.hasFocus()

    card = ModalCard(parent)
    card.resize(800, 600)
    card.set_content(QLabel("content"))
    card.show()
    app.processEvents()
    card.close()
    app.processEvents()

    assert opener.hasFocus(), "opener should regain focus after modal closes"


def test_modal_card_restores_focus_on_closed_signal_path(app):
    # Backdrop / close-button / Escape mechanisms only emit `closed`
    # (they don't call close()). The restoration is wired via that
    # signal so focus still returns to the opener.
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    parent = QWidget()
    parent.resize(400, 300)
    parent_layout = QVBoxLayout(parent)
    opener = QPushButton("Open", parent)
    parent_layout.addWidget(opener)
    parent.show()
    parent.activateWindow()
    app.processEvents()
    opener.setFocus()
    app.processEvents()

    card = ModalCard(parent)
    card.resize(800, 600)
    card.set_content(QLabel("content"))
    card.show()
    app.processEvents()
    # Simulate the Escape / close-button path: emit closed directly.
    card.closed.emit()
    app.processEvents()

    assert opener.hasFocus(), "opener should regain focus after closed signal"
