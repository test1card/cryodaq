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
from PySide6.QtCore import QObject, Signal


class _SyncCommandWorkerStub(QObject):
    finished = Signal(dict)

    def __init__(self, cmd: dict, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._cmd = cmd

    def start(self) -> None:
        return None

    def isRunning(self) -> bool:  # noqa: N802
        return False

    def isFinished(self) -> bool:  # noqa: N802
        return True

    def requestInterruption(self) -> None:  # noqa: N802
        return None

    def wait(self, _msecs: int = 0) -> bool:
        return True

    def quit(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _isolate_shell_test(monkeypatch):
    import cryodaq.gui.zmq_client as zc

    monkeypatch.setattr(
        zc,
        "send_command",
        lambda _cmd, *, cancellation_requested=None: {"ok": False, "stub": True},
    )
    monkeypatch.setattr(zc, "ZmqCommandWorker", _SyncCommandWorkerStub)
    yield
    from PySide6.QtCore import QThread, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return

    import time

    # Stop timers first so nothing new gets scheduled while teardown is
    # draining the event queue.
    for timer in app.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass

    # Close and delete any top-level widgets created by the test. Their
    # child widgets/timers will be cleaned up with them. Closing also fires
    # closeEvent, where overlays stop their own owned timers/workers.
    for widget in QApplication.topLevelWidgets():
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            pass

    # Process pending deleteLater calls and any immediate finished
    # signals from no-op worker stubs.
    import gc

    gc.collect()
    for _ in range(5):
        app.processEvents()

    # Wait briefly for any already-running QThread to finish. Keep the
    # wait bounded so teardown cost scales with actual work, not with a
    # fixed sleep per test.
    deadline = time.monotonic() + 0.5
    idle_rounds = 0
    while time.monotonic() < deadline:
        app.processEvents()
        running = False
        for obj in app.findChildren(QThread):
            try:
                if obj.isRunning():
                    running = True
                    obj.wait(25)
            except RuntimeError:
                # C++ object already deleted
                pass
        if not running:
            idle_rounds += 1
            if idle_rounds >= 3:
                break
        else:
            idle_rounds = 0
        time.sleep(0.01)

    # Final flush so finished signals are processed.
    for _ in range(10):
        app.processEvents()
