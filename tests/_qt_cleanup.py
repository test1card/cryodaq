"""Shared Qt teardown helper for GUI test isolation.

GUI tests share one session ``QApplication``. Widgets, their owned ``QTimer``s,
and worker ``QThread``s (e.g. ``ZmqCommandWorker(parent=widget)``) leak across
tests unless explicitly cleaned up. On Windows CI the accumulation segfaults or
hangs — a leaked timer fires its slot on a mid-deletion widget, a leaked running
thread is destroyed with its parent ("QThread: Destroyed while thread is still
running"), and a full ``processEvents()`` over the mess raises an access
violation.

``drain_gui`` cleans one test's Qt objects safely: stop every timer (walking
widget trees, not just the app), join worker threads, delete top-level widgets,
then flush ONLY ``DeferredDelete`` events so the widgets are destroyed without
running arbitrary paint/timer handlers.
"""

from __future__ import annotations

from typing import Any


def drain_gui(app: Any) -> None:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    top_level = list(QApplication.topLevelWidgets())

    # Stop every timer (walking widget trees, not just app children) so a leaked
    # widget can't fire a timeout slot on a mid-deletion widget. Deliberately do
    # NOT enumerate/join QThreads here: poking leaked QThreads during teardown
    # proved more crash-prone than leaving them (process exit reaps them). Tests
    # that spawn real worker threads patch the worker (see test_shift_handover).
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

    # Flush the queue so deleteLater actually runs before the next test.
    for _ in range(5):
        try:
            app.processEvents()
        except RuntimeError:
            break
