"""Shared GUI test teardown.

Imported by ``tests/gui/conftest.py`` (its autouse per-test fixture) AND by the
leak sentinel ``tests/gui/test_widget_cleanup_sentinel.py``, so the sentinel
exercises the *actual* cleanup the suite relies on, not a copy.

The protective invariant for the Windows app_palette crash is that no leaked
widget is left with a *running timer* — a running timer fired during the global
``setStyleSheet`` re-polish is what access-violates. So this stops every timer
(walking widget trees, since a ``QTimer(self)`` is a child of the widget, not the
app), then closes + deleteLaters top-level widgets and flushes the queue. It
deliberately does NOT poke QThreads (that proved more crash-prone than leaving
them; tests that spawn real workers patch them).
"""

from __future__ import annotations

from typing import Any


def drain_gui_widgets(app: Any) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    top_level = list(QApplication.topLevelWidgets())

    timers = list(app.findChildren(QTimer))
    for widget in top_level:
        try:
            timers.extend(widget.findChildren(QTimer))
        except RuntimeError:
            pass
    for timer in timers:
        try:
            timer.stop()
        except RuntimeError:
            pass

    for widget in top_level:
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            pass

    for _ in range(5):
        try:
            app.processEvents()
        except RuntimeError:
            break
