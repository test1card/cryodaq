"""Tests for shift handover modal re-entrancy and auto-dismiss."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication, QDialog

import cryodaq.gui.widgets.shift_handover as _mod
from cryodaq.gui.widgets.shift_handover import ShiftBar


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_bar_active() -> ShiftBar:
    """Create a ShiftBar with active-shift state set directly — no timers started."""
    bar = ShiftBar()
    # Set state fields directly instead of calling _activate_shift, which starts
    # _tick_timer and _periodic_timer (those would fire real ZmqCommandWorker
    # threads during teardown and segfault the test process).
    bar._active = True
    bar._operator = "Тест"
    bar._shift_id = "shift-20260101-00"
    return bar


def test_periodic_prompt_reentrant_guard():
    """Second _on_periodic_due is a no-op at runtime when a dialog is already open."""
    _app()
    bar = _make_bar_active()
    try:
        # Simulate a dialog already open: set _prompt_pending = True
        bar._prompt_pending = True

        # _on_periodic_due must return early without spawning a second dialog.
        created: list[object] = []

        class _FakeDialog:
            def __init__(self, *a, **kw):
                created.append(self)

            def exec(self):
                return 0

        with patch.object(_mod, "ShiftPeriodicPrompt", _FakeDialog):
            bar._on_periodic_due()

        assert len(created) == 0, (
            "_on_periodic_due must not open a second dialog while _prompt_pending is True"
        )
    finally:
        # Stop all timers before bar is GC'd to prevent QThread-teardown abort.
        bar._tick_timer.stop()
        bar._periodic_timer.stop()
        bar._missed_timer.stop()


def test_periodic_prompt_opens_and_counts_when_not_pending():
    """Positive control for the reentrant guard: with NO prompt pending, an
    active shift opens exactly one dialog, clears _prompt_pending afterward, and
    an accepted dialog increments _periodic_count. Without this, the guard test
    would also pass if _on_periodic_due were a blanket no-op for active shifts."""
    _app()
    bar = _make_bar_active()
    try:
        bar._prompt_pending = False
        created: list[object] = []

        class _AcceptingDialog:
            def __init__(self, *a, **kw):
                created.append(self)

            def exec(self):
                return QDialog.DialogCode.Accepted

        count_before = bar._periodic_count
        with patch.object(_mod, "ShiftPeriodicPrompt", _AcceptingDialog):
            bar._on_periodic_due()

        assert len(created) == 1, "one dialog must open when no prompt is pending"
        assert bar._prompt_pending is False, "_prompt_pending must be cleared after the dialog closes"
        assert bar._periodic_count == count_before + 1, (
            "an accepted periodic dialog must increment _periodic_count"
        )
    finally:
        bar._tick_timer.stop()
        bar._periodic_timer.stop()
        bar._missed_timer.stop()


def test_periodic_missed_auto_dismisses_dialog():
    """_on_periodic_missed calls reject() on the open dialog at runtime."""
    _app()
    bar = _make_bar_active()
    try:
        # Simulate a pending prompt with a fake dialog attached.
        bar._prompt_pending = True
        fake_dialog = MagicMock(spec=QDialog)
        bar._prompt_dialog = fake_dialog

        # Patch ZmqCommandWorker so no real Qt thread is spawned by _on_periodic_missed
        with patch("cryodaq.gui.zmq_client.ZmqCommandWorker") as mock_worker_cls:
            mock_worker = MagicMock()
            mock_worker.finished = MagicMock()
            mock_worker.finished.connect = MagicMock()
            mock_worker.isRunning = MagicMock(return_value=False)
            mock_worker_cls.return_value = mock_worker
            bar._on_periodic_missed()

        fake_dialog.reject.assert_called_once()
    finally:
        # Stop all timers before bar is GC'd to prevent QThread-teardown abort.
        bar._tick_timer.stop()
        bar._periodic_timer.stop()
        bar._missed_timer.stop()
