"""Shell test fixtures.

MainWindowV2 eagerly constructs every overlay panel. Several existing
panels (vacuum_trend, sensor_diag, archive, overview) schedule
``QTimer.singleShot(500 ms, _poll)`` callbacks in their constructors.
If those fire on the global event loop AFTER the test that created the
panel exits, they spawn ZmqCommandWorker QThreads which call
``cryodaq.gui.zmq_client.send_command``. Subsequent tests
(test_keithley_panel_contract) monkeypatch ``send_command`` and the
zombie workers then call the mock, breaking unrelated assertions.

Drain pending Qt events at the end of every shell test so any pending
singleShot fires *during* the shell test (with the harmless no-op stub
applied here), not during the next test.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_shell_test(monkeypatch):
    import cryodaq.gui.zmq_client as zc

    monkeypatch.setattr(zc, "send_command", lambda _cmd: {"ok": False, "stub": True})
    yield
    # Drain pending Qt events so any QTimer.singleShot scheduled during
    # the test fires here (under the stubbed send_command) instead of
    # leaking into the next test.
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return

    # Wait long enough for any QTimer.singleShot scheduled by panel
    # constructors to fire under the stubbed send_command, then wait for
    # the spawned QThread workers to finish so they cannot leak into the
    # next test under a different mock.
    import time

    from PySide6.QtCore import QThread

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)

    # Drain any QThread that's still running (worker leaks).
    for obj in app.findChildren(QThread):
        try:
            if obj.isRunning():
                obj.wait(2000)
        except RuntimeError:
            # C++ object already deleted
            pass

    # Final flush so finished signals are processed.
    for _ in range(20):
        app.processEvents()
