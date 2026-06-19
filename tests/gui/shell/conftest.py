"""Shell test fixtures.

MainWindowV2 eagerly constructs overlay panels that own timers and
background workers. Shell tests need teardown isolation so one test's
timers, delayed callbacks, or QThreads cannot leak into the next test.

The previous fixture handled this by sleeping for two seconds after
every shell test to let timers fire. That prevented cross-test leaks,
but it also turned the shell suite into an effectively hung run once the
overlay test count grew.

Instead, stop timers/widgets explicitly and only wait briefly for any
already-running QThreads to finish.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_shell_test(monkeypatch):
    import cryodaq.gui.zmq_client as zc

    monkeypatch.setattr(zc, "send_command", lambda _cmd: {"ok": False, "stub": True})
    yield
    from PySide6.QtWidgets import QApplication

    # Windows-safe teardown: stop timers, join worker threads, delete widgets,
    # flush only DeferredDelete events (no processEvents — that fires leaked
    # timer/paint events on mid-deletion widgets → access violation on Windows).
    from tests._qt_cleanup import drain_gui

    app = QApplication.instance()
    if app is not None:
        drain_gui(app)
