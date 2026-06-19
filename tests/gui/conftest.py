"""Top-level GUI test isolation.

Most ``tests/gui/*.py`` tests create QWidgets without tearing them down, so
they accumulate on the shared session ``QApplication``. A later test that calls
an application-global ``app.setStyleSheet(...)`` — notably
``tests/gui/test_app_palette.py`` — then forces Qt to re-polish *every* leaked
widget. That is merely slow on Linux/macOS, but on Windows CI it either blows
the per-test timeout or segfaults mid-repaint (observed as a ~79%-through hang
that produced no traceback).

``tests/gui/shell/conftest.py`` already solves this for the shell subtree; this
mirrors it for the rest of ``tests/gui/`` so widgets do not leak across tests.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _cleanup_top_level_widgets():
    yield
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return

    top_level = list(QApplication.topLevelWidgets())

    # Stop EVERY timer first. app.findChildren(QTimer) only catches timers
    # parented to the QApplication — widget-owned timers (e.g.
    # ConductivityPanel._auto_timer, a QTimer(self)) are descendants of the
    # widget, not the app, so they are missed. A leaked widget whose timer is
    # still running will fire its timeout slot during the processEvents() below,
    # touching child widgets that are mid-deletion → segfault. Walk the widget
    # trees too so nothing is left ticking.
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

    # Close + delete every top-level widget the test created; child widgets
    # and their timers are cleaned up with their parents.
    for widget in top_level:
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            # C++ object already deleted.
            pass

    # Flush the pending deleteLater queue so widgets are gone before the next
    # test (and before any later app-global setStyleSheet has to repaint them).
    for _ in range(5):
        app.processEvents()
