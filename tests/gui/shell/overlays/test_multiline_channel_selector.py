"""v0.55.16.0.1 (smoke hotfix) — channel selector dialog tests."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication

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
    dialog = MultiLineChannelSelectorDialog(current_selection=[])
    dialog._select_all()
    assert dialog.selected_channels() == list(range(1, 33))


def test_dialog_clear_all_unchecks_every_box(qapp) -> None:
    dialog = MultiLineChannelSelectorDialog(current_selection=list(range(1, 33)))
    dialog._clear_all()
    assert dialog.selected_channels() == []


def test_dialog_selected_channels_returns_sorted(qapp) -> None:
    dialog = MultiLineChannelSelectorDialog(current_selection=[5, 1, 10, 3])
    assert dialog.selected_channels() == [1, 3, 5, 10]


def test_dialog_on_accept_with_empty_selection_blocks_close(qapp) -> None:
    """Empty submission shows the error label and does NOT accept."""
    dialog = MultiLineChannelSelectorDialog(current_selection=[1])
    dialog._clear_all()
    assert not dialog._error_label.text()  # initially empty
    dialog._on_accept()
    # Dialog stays open (rejected → 0; accepted → 1; we expect neither yet)
    assert dialog.result() != dialog.DialogCode.Accepted
    # Error label populated
    assert "хотя бы один" in dialog._error_label.text()


def test_dialog_on_accept_with_valid_selection_accepts(qapp) -> None:
    dialog = MultiLineChannelSelectorDialog(current_selection=[1, 2])
    dialog._on_accept()
    assert dialog.result() == dialog.DialogCode.Accepted
    assert dialog.selected_channels() == [1, 2]
