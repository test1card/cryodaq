"""Top-level GUI test isolation.

Most ``tests/gui/*.py`` tests create QWidgets without tearing them down, so they
accumulate on the shared session ``QApplication``. By the time
``tests/gui/test_app_palette.py`` calls an application-global
``app.setStyleSheet(...)``, Qt must re-polish every leaked widget — which on
Windows CI raises a fatal access violation (the original ~78%-through crash).

This autouse fixture deletes each test's widgets so nothing leaks across tests.
It stops every timer first (walking widget trees, since a ``QTimer(self)`` on a
widget is not an app child) — closing widgets also fires ``closeEvent``, where
overlays such as ConductivityPanel stop their own owned timers. Kept
deliberately minimal: enumerating/joining QThreads or using
``sendPostedEvents``/``shiboken6.delete`` here all proved more crash-prone than
a plain ``deleteLater`` + ``processEvents`` flush.
"""

from __future__ import annotations

import pytest

from tests._widget_cleanup import drain_gui_widgets


@pytest.fixture(autouse=True)
def _cleanup_top_level_widgets():
    yield
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        drain_gui_widgets(app)
