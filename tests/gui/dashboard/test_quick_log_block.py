"""Tests for QuickLogBlock (B.7)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton

from cryodaq.gui.dashboard.quick_log_block import QuickLogBlock


# LOW: assert composer input, send button, empty label text
def test_constructs(app):
    w = QuickLogBlock()
    assert w is not None
    assert w.objectName() == "QuickLogBlock"
    # composer input exists and is a QLineEdit
    assert isinstance(w._input, QLineEdit), "QuickLogBlock must have a _input QLineEdit"
    # send button exists
    assert isinstance(w._send_btn, QPushButton), "QuickLogBlock must have a _send_btn QPushButton"
    # empty label is visible initially (use isHidden() — reflects explicit setVisible calls)
    assert not w._empty_label.isHidden(), "_empty_label must be visible when no entries"
    empty_text = w._empty_label.text()
    assert empty_text, "_empty_label must have non-empty text"
    # empty label text contains "Журнал пуст" or similar
    assert "пуст" in empty_text or "журнал" in empty_text.lower() or "заметк" in empty_text.lower()


def test_widget_height_capped(app):
    w = QuickLogBlock()
    assert w.maximumHeight() <= 70


def test_empty_state_shown_when_no_entries(app):
    w = QuickLogBlock()
    w.set_entries([])
    labels = w.findChildren(QLabel)
    texts = [lbl.text() for lbl in labels]
    assert any(
        "Пуст" in t or "пуст" in t or "добавить" in t or "Добавить" in t
        for t in texts
    )


def test_single_entry_shown(app):
    w = QuickLogBlock()
    w.set_entries(
        [
            {"timestamp": "2026-04-15T17:00:00", "message": "Test entry one"},
        ]
    )
    labels = w.findChildren(QLabel)
    texts = [lbl.text() for lbl in labels]
    assert any("Test entry one" in t for t in texts)


# HIGH: assert exactly newest two messages present, no third
def test_max_2_entries_visible(app):
    w = QuickLogBlock()
    entries = [
        {"timestamp": f"2026-04-15T17:{i:02d}:00", "message": f"Entry {i}"} for i in range(20)
    ]
    w.set_entries(entries)
    # The widget shows newest-first (entries[0] is newest)
    # _entry_labels must have exactly 2 items
    assert len(w._entry_labels) == 2, (
        f"Expected exactly 2 entry labels, got {len(w._entry_labels)}"
    )
    # The two rendered labels must be for the first two entries (newest)
    first_text = w._entry_labels[0].text()
    second_text = w._entry_labels[1].text()
    assert "Entry 0" in first_text, (
        f"First label must show newest (Entry 0), got: {first_text!r}"
    )
    assert "Entry 1" in second_text, (
        f"Second label must show second-newest (Entry 1), got: {second_text!r}"
    )
    # No third entry label
    all_entry_texts = [lbl.text() for lbl in w.findChildren(QLabel) if "Entry 2" in lbl.text()]
    assert len(all_entry_texts) == 0, (
        "Entry 2 (third oldest) must not be visible"
    )


def test_submit_emits_signal(app):
    w = QuickLogBlock()
    received = []
    w.entry_submitted.connect(lambda msg: received.append(msg))
    w._input.setText("Тестовая заметка")
    w._on_submit()
    assert received == ["Тестовая заметка"]
    assert w._input.text() == ""  # cleared after submit


def test_empty_submit_ignored(app):
    w = QuickLogBlock()
    received = []
    w.entry_submitted.connect(lambda msg: received.append(msg))
    w._input.setText("")
    w._on_submit()
    assert received == []


# HIGH: collect matching labels, assert exact truncated text + tooltip
def test_long_message_truncated_in_display(app):
    w = QuickLogBlock()
    long_msg = "A" * 100
    w.set_entries([{"timestamp": "2026-04-15T17:00:00", "message": long_msg}])

    # Collect all labels that contain 'A' in text
    all_labels = w.findChildren(QLabel)
    matching = [lbl for lbl in all_labels if "A" in lbl.text()]
    assert len(matching) >= 1, "Must find at least one label with 'A' for long message"

    # The entry label must truncate to 57 chars + ellipsis (…)
    entry_label = matching[0]
    label_text = entry_label.text()
    # The text is rich HTML — find the span containing the message
    # The truncated message is the first 57 'A's + '…'
    expected_truncated = "A" * 57 + "…"
    assert expected_truncated in label_text, (
        f"Expected truncated text '{expected_truncated}' in label, got: {label_text!r}"
    )
    # Full message must NOT appear (would be 100 A's without ellipsis)
    assert "A" * 100 not in label_text, "Full 100-char message must not appear untruncated"
    # Tooltip shows the full original message
    assert entry_label.toolTip() == long_msg, (
        f"Tooltip must be the full message, got: {entry_label.toolTip()!r}"
    )
