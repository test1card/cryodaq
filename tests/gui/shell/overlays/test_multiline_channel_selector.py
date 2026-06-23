"""v0.55.16.0.1 (smoke hotfix) — channel selector dialog tests."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QDialogButtonBox

from cryodaq.gui.shell.overlays.multiline_channel_selector import (
    MultiLineChannelSelectorDialog,
)


@pytest.fixture
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        from PySide6.QtWidgets import QApplication

        app = QApplication([])
    yield app


def _ok_button(dialog: MultiLineChannelSelectorDialog):
    """Return the rendered 'Применить' (OK) button from the dialog's QDialogButtonBox."""
    btn_boxes = dialog.findChildren(QDialogButtonBox)
    assert btn_boxes, "No QDialogButtonBox found in dialog"
    return btn_boxes[0].button(QDialogButtonBox.StandardButton.Ok)


def _cancel_button(dialog: MultiLineChannelSelectorDialog):
    btn_boxes = dialog.findChildren(QDialogButtonBox)
    assert btn_boxes, "No QDialogButtonBox found in dialog"
    return btn_boxes[0].button(QDialogButtonBox.StandardButton.Cancel)


def _select_all_button(dialog: MultiLineChannelSelectorDialog):
    """Return the 'Выбрать все' button."""
    from PySide6.QtWidgets import QPushButton

    btns = dialog.findChildren(QPushButton)
    for b in btns:
        if "все" in b.text().lower() or "all" in b.text().lower():
            return b
    raise AssertionError(f"No 'Выбрать все' button found; found: {[b.text() for b in btns]}")


def _clear_all_button(dialog: MultiLineChannelSelectorDialog):
    """Return the 'Снять все' button."""
    from PySide6.QtWidgets import QPushButton

    btns = dialog.findChildren(QPushButton)
    for b in btns:
        if "снять" in b.text().lower() or "clear" in b.text().lower():
            return b
    raise AssertionError(f"No 'Снять все' button found; found: {[b.text() for b in btns]}")


def test_dialog_pre_checks_current_selection(qapp) -> None:
    dialog = MultiLineChannelSelectorDialog(current_selection=[1, 5, 32])
    assert dialog._checkboxes[1].isChecked()
    assert dialog._checkboxes[5].isChecked()
    assert dialog._checkboxes[32].isChecked()
    # All others stay unchecked
    assert not dialog._checkboxes[2].isChecked()


def test_dialog_filters_invalid_channels_in_pre_check(qapp) -> None:
    """Out-of-range or non-int values in ``current_selection`` should be
    silently dropped — UI shows a clean state."""
    dialog = MultiLineChannelSelectorDialog(current_selection=[0, 33, "foo", 1, 2])  # type: ignore[list-item]
    assert dialog._checkboxes[1].isChecked()
    assert dialog._checkboxes[2].isChecked()
    # 33 doesn't exist as a checkbox; 0 doesn't exist; "foo" silently ignored


def test_dialog_select_all_checks_every_box(qapp) -> None:
    """MED: click the rendered 'Выбрать все' button instead of calling private _select_all."""
    dialog = MultiLineChannelSelectorDialog(current_selection=[])
    btn = _select_all_button(dialog)
    btn.click()
    assert dialog.selected_channels() == list(range(1, 33))


def test_dialog_clear_all_unchecks_every_box(qapp) -> None:
    """MED: click the rendered 'Снять все' button instead of calling private _clear_all."""
    dialog = MultiLineChannelSelectorDialog(current_selection=list(range(1, 33)))
    btn = _clear_all_button(dialog)
    btn.click()
    assert dialog.selected_channels() == []


def test_dialog_selected_channels_returns_sorted(qapp) -> None:
    dialog = MultiLineChannelSelectorDialog(current_selection=[5, 1, 10, 3])
    assert dialog.selected_channels() == [1, 3, 5, 10]


def test_dialog_on_accept_empty_blocks_close(qapp) -> None:
    """MED: click the QDialogButtonBox OK button with empty selection — dialog stays open."""
    dialog = MultiLineChannelSelectorDialog(current_selection=[1])
    # Clear via rendered button.
    btn_clear = _clear_all_button(dialog)
    btn_clear.click()
    assert not dialog._error_label.text()  # initially empty after clear
    # Click the rendered OK button — should be blocked.
    ok_btn = _ok_button(dialog)
    ok_btn.click()
    # Dialog stays open (result is not Accepted).
    assert dialog.result() != dialog.DialogCode.Accepted
    # Error label populated.
    assert "хотя бы один" in dialog._error_label.text()


def test_dialog_on_accept_valid_accepts(qapp) -> None:
    """MED: click the rendered OK button with valid selection — dialog accepts."""
    dialog = MultiLineChannelSelectorDialog(current_selection=[1, 2])
    ok_btn = _ok_button(dialog)
    ok_btn.click()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.selected_channels() == [1, 2]
