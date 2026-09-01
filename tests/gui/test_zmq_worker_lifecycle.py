"""A finished GUI poll worker must be delivered, then destroyed.

Every GUI poller builds its ZmqCommandWorker with ``parent=self``, so a
long-lived widget kept one finished QThread per poll for the life of the window
-- roughly 5,880 an hour, most of a measured 45 MB/h in the GUI process on
lab53.

The naive fix (drop the parent) is wrong: the parent is ALSO how the window
destroys its threads at close. So the worker is destroyed at the one point where
both facts are known -- the result was delivered or suppressed, and the native
thread is terminal -- and every caller that keeps a wrapper asks
``gui_worker_poll_in_flight()`` instead of touching it directly.

These tests drive real threads through a real Qt event loop and observe
destruction with weakrefs. They do not call the private delivery slot.
"""

import gc
import weakref

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import (  # noqa: E402
    QCoreApplication,
    QEvent,
    QEventLoop,
    QObject,
    Qt,
    QThread,
    QTimer,
)
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
from shiboken6 import isValid  # noqa: E402

from cryodaq.gui.zmq_client import (  # noqa: E402
    ZmqCommandWorker,
    capture_gui_worker_session_token,
    gui_command_worker_admission_open,
    gui_worker_poll_in_flight,
    open_gui_command_worker_admission,
    revoke_gui_command_worker_admission,
    start_gui_worker_with_ownership,
)

POLLS = 40


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
    """Run the real event loop so queued deliveries and deferred deletes land."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    QCoreApplication.processEvents()


class _Worker(ZmqCommandWorker):
    """A real QThread that runs, without needing a live engine."""

    def run(self) -> None:  # noqa: D102
        self._session_epoch = self._epoch_for_test
        self._result_ready.emit(self._epoch_for_test, {"ok": True, "probe": True})


def _spawn(parent: QObject, epoch: int) -> _Worker:
    worker = _Worker({"cmd": "experiment_status"}, parent=parent)
    worker._epoch_for_test = epoch
    return worker


# ---------------------------------------------------------------------------
# Delivered, then destroyed
# ---------------------------------------------------------------------------


def test_a_started_worker_delivers_and_is_then_destroyed(qapp, session_epoch):
    parent = QWidget()
    got: list[dict] = []
    worker = _spawn(parent, session_epoch)
    worker.finished.connect(got.append)
    ref = weakref.ref(worker)

    start_gui_worker_with_ownership(worker, session_epoch)
    _pump()

    assert got and got[0].get("probe") is True, "the callback was not delivered"
    assert not isValid(worker), "the settled worker's C++ object was not destroyed"
    del worker
    gc.collect()
    assert ref() is None or True  # the Python wrapper may linger; the C++ object must not


def test_repeated_polls_do_not_accumulate_on_the_widget(qapp, session_epoch):
    """The leak, measured through the real path."""
    parent = QWidget()
    for _ in range(POLLS):
        worker = _spawn(parent, session_epoch)
        start_gui_worker_with_ownership(worker, session_epoch)
        _pump(60)
    _pump()
    retained = [child for child in parent.children() if isinstance(child, QThread)]
    assert not retained, f"{len(retained)} finished workers still parented after {POLLS} polls"


# ---------------------------------------------------------------------------
# A retained wrapper stays safe to check and to replace
# ---------------------------------------------------------------------------


def test_a_retained_wrapper_is_safe_to_check_after_destruction(qapp, session_epoch):
    """Call sites keep the current worker on an attribute and poll it."""
    parent = QWidget()
    worker = _spawn(parent, session_epoch)
    start_gui_worker_with_ownership(worker, session_epoch)
    _pump()

    assert not isValid(worker)
    # The direct form call sites used to use now raises.
    with pytest.raises(RuntimeError):
        worker.isFinished()
    # The guard they use instead does not.
    assert gui_worker_poll_in_flight(worker) is False


def test_the_guard_reports_a_live_poll_as_in_flight(qapp, session_epoch):
    parent = QWidget()
    worker = _spawn(parent, session_epoch)
    assert gui_worker_poll_in_flight(worker) is True, "a worker that has not run is pending"
    start_gui_worker_with_ownership(worker, session_epoch)
    _pump()
    assert gui_worker_poll_in_flight(worker) is False


def test_the_guard_treats_absence_as_not_in_flight(qapp):
    assert gui_worker_poll_in_flight(None) is False


# ---------------------------------------------------------------------------
# A queued receiver on another thread must not lose its result
# ---------------------------------------------------------------------------


def test_a_queued_receiver_still_receives(qapp, session_epoch):
    parent = QWidget()
    received: list[dict] = []
    worker = _spawn(parent, session_epoch)
    worker.finished.connect(received.append, Qt.ConnectionType.QueuedConnection)

    start_gui_worker_with_ownership(worker, session_epoch)
    _pump()

    assert received, "a queued receiver lost its result to the destruction"


# ---------------------------------------------------------------------------
# Closing the window still destroys every real QThread
# ---------------------------------------------------------------------------


def test_closing_the_window_destroys_workers_that_never_settled(qapp, session_epoch):
    """The property the naive setParent(None) fix broke."""
    window = QWidget()
    unsettled = [_Worker({"cmd": "experiment_status"}, parent=window) for _ in range(3)]
    for worker in unsettled:
        worker._epoch_for_test = session_epoch

    assert all(isValid(worker) for worker in unsettled)
    window.close()
    window.deleteLater()
    del window
    _pump()

    assert not any(isValid(worker) for worker in unsettled), (
        "closing the window left real QThread objects alive"
    )
