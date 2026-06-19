"""Top-level GUI test isolation.

Most ``tests/gui/*.py`` tests create QWidgets without tearing them down, so
they accumulate on the shared session ``QApplication``. A later test that calls
an application-global ``app.setStyleSheet(...)`` — notably
``tests/gui/test_app_palette.py`` — then forces Qt to re-polish *every* leaked
widget, which on Windows CI hangs or segfaults mid-repaint.

This autouse fixture deletes per-test widgets so nothing leaks across tests.
See ``tests/_qt_cleanup.drain_gui`` for the (Windows-safe) teardown details.
"""

from __future__ import annotations

import pytest

from tests._qt_cleanup import drain_gui


@pytest.fixture(autouse=True)
def _cleanup_top_level_widgets():
    yield
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        drain_gui(app)
