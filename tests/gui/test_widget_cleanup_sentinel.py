"""Leak sentinel for the GUI test-teardown invariant.

``tests/gui/test_app_palette.py`` mutates the *global* QApplication stylesheet,
which forces Qt to re-polish every live top-level widget. If GUI tests leak
widgets across the suite, that re-polish access-violates under the Windows
offscreen platform — which is why app_palette is run in its own process. The
defence that keeps the rest of the suite safe is the per-test teardown in
``tests/gui/conftest.py`` that deletes top-level widgets.

This sentinel exercises the ACTUAL cleanup the suite uses — it imports
``tests/_widget_cleanup.drain_gui_widgets``, the same helper the autouse
``tests/gui/conftest.py`` fixture calls — so a future change that breaks the real
teardown (or a PySide upgrade that changes QTimer/processEvents semantics) fails
here as a clear assertion instead of an opaque Windows crash 2500 tests later.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from tests._widget_cleanup import drain_gui_widgets


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_teardown_stops_leaked_widget_timers(app):
    # The crash mode app_palette triggers is a *running* timer (e.g. an overlay's
    # auto-tick) firing while the global setStyleSheet re-polishes its widget —
    # not widget count. So the protective invariant is: after teardown, no leaked
    # widget is left with a running timer. (deleteLater+processEvents does not
    # reliably *delete* widgets — Qt DeferredDelete semantics — so asserting that
    # would be testing the wrong thing.)
    leaked = []
    for _ in range(5):
        w = QWidget()
        timer = QTimer(w)  # parented to the widget, like ConductivityPanel._auto_timer
        timer.start(10)
        w.show()
        leaked.append((w, timer))

    assert any(t.isActive() for _, t in leaked), "test setup failed to start timers"

    drain_gui_widgets(app)  # the real cleanup the conftest runs after every test

    for _w, timer in leaked:
        try:
            assert not timer.isActive(), (
                "GUI teardown left a running timer on a leaked widget; it would fire "
                "during app_palette's global setStyleSheet re-polish and crash on Windows"
            )
        except RuntimeError:
            # Timer's C++ object was deleted outright — also a safe outcome.
            pass
