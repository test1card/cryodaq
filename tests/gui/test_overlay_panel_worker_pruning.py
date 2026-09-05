"""A deleted worker must not break the next worker's completion.

`OverlayPanelBase._register_worker` used to prune with
`[w for w in self._workers if w.isRunning()]`, which inspects EVERY retained
wrapper. Once settled workers began being destroyed, worker A could already be
gone when worker B completed; touching A raised "Internal C++ object already
deleted" inside B's handler, BEFORE `on_result` ran. The panel's in-flight flag
would never clear and its polling would freeze for good.

AlarmPanel drives both alarm_v2_status (3 s) and cooldown_alarm.status (5 s)
through this path, so the freeze would take the operator's alarm view with it.

The regression below is the real A-then-B ordering with real QThreads.
"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from shiboken6 import isValid  # noqa: E402

from cryodaq.gui.shell.overlays._base_panel import OverlayPanelBase  # noqa: E402
from cryodaq.gui.zmq_client import (  # noqa: E402
    ZmqCommandWorker,
    capture_gui_worker_session_token,
    gui_command_worker_admission_open,
    open_gui_command_worker_admission,
    revoke_gui_command_worker_admission,
)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def session_epoch():
    if gui_command_worker_admission_open():
        yield capture_gui_worker_session_token()
        return
    epoch = open_gui_command_worker_admission()
    try:
        yield epoch
    finally:
        revoke_gui_command_worker_admission(epoch)


def _pump(ms: int = 400) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    QCoreApplication.processEvents()


class _Worker(ZmqCommandWorker):
    def run(self) -> None:  # noqa: D102
        self._session_epoch = self._epoch_for_test
        self._result_ready.emit(self._epoch_for_test, {"ok": True, "tag": self._tag})


class _Panel(OverlayPanelBase, QWidget):
    """Minimal panel exercising the shared registration path."""

    def __init__(self) -> None:
        QWidget.__init__(self)
        self._workers: list = []
        self.results: list[str] = []
        self.in_flight = False

    def poll(self, epoch: int, tag: str) -> _Worker:
        self.in_flight = True
        worker = _Worker({"cmd": "alarm_v2_status"}, parent=self, release_on_settle=True)
        worker._epoch_for_test = epoch
        worker._tag = tag

        def _on_result(result: dict) -> None:
            self.results.append(result["tag"])
            self.in_flight = False

        self._register_worker(worker, _on_result)
        return worker


def test_worker_b_completes_after_worker_a_was_deleted(qapp, session_epoch):
    """The exact A-then-B ordering that froze alarm polling."""
    panel = _Panel()

    first = panel.poll(session_epoch, "A")   # _register_worker starts it
    _pump()
    assert panel.results == ["A"]
    assert not isValid(first), "A must be destroyed for this regression to mean anything"

    # B completes while A's wrapper is still in the list and already deleted.
    panel._workers.append(first)
    panel.poll(session_epoch, "B")
    _pump()

    assert panel.results == ["A", "B"], "B's callback did not run"
    assert panel.in_flight is False, "the in-flight flag never cleared — polling would freeze"


def test_the_completed_worker_is_removed_by_identity(qapp, session_epoch):
    panel = _Panel()
    worker = panel.poll(session_epoch, "A")
    _pump()
    assert worker not in panel._workers


def test_a_still_running_worker_is_not_pruned(qapp, session_epoch):
    """Pruning must not drop work that is genuinely in flight."""
    panel = _Panel()
    pending = _Worker({"cmd": "alarm_v2_status"}, parent=panel, release_on_settle=True)
    pending._epoch_for_test = session_epoch
    pending._tag = "pending"
    panel._workers.append(pending)

    panel.poll(session_epoch, "A")
    _pump()

    assert panel.results == ["A"]
    assert pending in panel._workers, "an unstarted/in-flight worker was pruned"
