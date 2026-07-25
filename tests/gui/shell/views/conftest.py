"""Analytics-view test isolation.

The analytics widgets (``analytics_widgets.py``) own ``ZmqCommandWorker``
QThreads started from their ``_load_*`` / poll-timer refresh paths to fetch
history/stats/alarms over ZMQ. In the unit tests these workers can never reach
a real engine, and the rendered behaviour under test is exercised by calling
the widgets' ``_on_*_loaded`` slots directly with synthetic payloads — the
background QThread is pure transport, not the behaviour being asserted.

Left real, each refresh creates and starts a short-lived QThread. pytest can
GC the owning widget (and its worker) between the ``.start()`` and a
deterministic join, so the QThread's C++ object is destroyed while the thread
object is still being torn down — Qt then aborts the whole process with a fatal
"QThread: Destroyed while thread is still running". Individually the files pass;
run together the churn crosses the abort threshold (a real, reproducible
process abort, not a logical failure).

Replacing ``ZmqCommandWorker`` with a synchronous no-op stub removes the
QThread entirely. The fetch becomes a no-op; tests that need data still inject
it through the ``_on_*_loaded`` slots exactly as before. This is consistent
with the shell conftest, which already stubs ``zmq_client.send_command``.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal


class _SyncCommandWorkerStub(QObject):
    """Drop-in for ZmqCommandWorker that never spawns a real QThread."""

    finished = Signal(dict)

    def __init__(self, cmd: dict, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._cmd = cmd

    def start(self) -> None:
        # No-op: the real ZMQ fetch cannot reach an engine in tests, and the
        # rendered behaviour under test is driven via the ``_on_*_loaded``
        # slots directly. Emitting nothing keeps construction side-effect-free.
        return None

    def isRunning(self) -> bool:  # noqa: N802 (Qt API name)
        return False

    def isFinished(self) -> bool:  # noqa: N802 (Qt API name)
        return True

    def requestInterruption(self) -> None:  # noqa: N802 (Qt API name)
        return None

    def wait(self, _msecs: int = 0) -> bool:
        return True

    def quit(self) -> None:
        return None

    def terminate(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _stub_command_worker(monkeypatch):
    import cryodaq.gui.zmq_client as zc

    monkeypatch.setattr(zc, "ZmqCommandWorker", _SyncCommandWorkerStub)
    yield
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    for widget in QApplication.topLevelWidgets():
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            pass
    for _ in range(5):
        app.processEvents()
    import gc

    gc.collect()
    app.processEvents()
