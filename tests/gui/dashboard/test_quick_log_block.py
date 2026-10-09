"""Tests for QuickLogBlock (B.7)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QLabel

from cryodaq.gui.dashboard.quick_log_block import QuickLogBlock


def test_constructs(app):
    w = QuickLogBlock()
    assert w is not None
    assert w.objectName() == "QuickLogBlock"


def test_widget_height_capped(app):
    w = QuickLogBlock()
    assert w.maximumHeight() <= 70


def test_empty_state_shown_when_no_entries(app):
    w = QuickLogBlock()
    w.set_entries([])
    labels = w.findChildren(QLabel)
    texts = [lbl.text() for lbl in labels]
    assert any(
        "\u041f\u0443\u0441\u0442" in t or "\u0434\u043e\u0431\u0430\u0432\u0438\u0442\u044c" in t
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


def test_max_2_entries_visible(app):
    w = QuickLogBlock()
    entries = [
        {"timestamp": f"2026-04-15T17:{i:02d}:00", "message": f"Entry {i}"} for i in range(20)
    ]
    w.set_entries(entries)
    labels = w.findChildren(QLabel)
    visible_entry_texts = [lbl.text() for lbl in labels if "Entry" in lbl.text()]
    assert len(visible_entry_texts) <= 2


def test_submit_emits_signal(app):
    w = QuickLogBlock()
    received = []
    w.entry_submitted.connect(lambda msg: received.append(msg))
    w._input.setText(
        "\u0422\u0435\u0441\u0442\u043e\u0432\u0430\u044f \u0437\u0430\u043c\u0435\u0442\u043a\u0430"  # noqa: E501
    )
    w._on_submit()
    assert received == [
        "\u0422\u0435\u0441\u0442\u043e\u0432\u0430\u044f \u0437\u0430\u043c\u0435\u0442\u043a\u0430"  # noqa: E501
    ]
    assert w._input.text() == ""  # cleared after submit


def test_empty_submit_ignored(app):
    w = QuickLogBlock()
    received = []
    w.entry_submitted.connect(lambda msg: received.append(msg))
    w._input.setText("")
    w._on_submit()
    assert received == []


def test_long_message_truncated_in_display(app):
    w = QuickLogBlock()
    long_msg = "A" * 100
    w.set_entries([{"timestamp": "2026-04-15T17:00:00", "message": long_msg}])
    labels = w.findChildren(QLabel)
    for lbl in labels:
        if "A" in lbl.text():
            assert "\u2026" in lbl.text()  # ellipsis
            break
