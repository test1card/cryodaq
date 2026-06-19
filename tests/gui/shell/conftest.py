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
    import time

    from PySide6.QtCore import QThread, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return

    top_level = list(QApplication.topLevelWidgets())

    # Collect timers AND threads from the app object *and* every widget tree.
    # app.findChildren() only finds objects parented to the QApplication —
    # widget-owned ones (QTimer(self) on an overlay, ZmqCommandWorker(parent=
    # widget) QThreads) parent to the widget, not the app, so they were missed.
    # A missed timer fires its slot on a mid-deletion widget, and a missed
    # running thread gets destroyed with its parent widget — both segfault on
    # Windows.
    timers = list(app.findChildren(QTimer))
    threads = list(app.findChildren(QThread))
    for widget in top_level:
        try:
            timers.extend(widget.findChildren(QTimer))
            threads.extend(widget.findChildren(QThread))
        except RuntimeError:
            pass

    # Stop timers so nothing reschedules during teardown.
    for timer in timers:
        try:
            timer.stop()
        except RuntimeError:
            pass

    # Drain worker threads BEFORE deleting their parent widgets, else Qt
    # destroys a running QThread with its parent and aborts ("QThread:
    # Destroyed while thread is still running").
    deadline = time.monotonic() + 2.0
    for thread in threads:
        try:
            while thread.isRunning() and time.monotonic() < deadline:
                thread.wait(50)
                app.processEvents()
        except RuntimeError:
            pass

    # Now close + delete top-level widgets; children, timers, and the
    # (finished) threads are cleaned up with them.
    for widget in top_level:
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            pass

    # Final flush so deleteLater and finished signals are processed.
    for _ in range(10):
        app.processEvents()
