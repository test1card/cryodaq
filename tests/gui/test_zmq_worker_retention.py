"""A finished GUI poll worker must not be retained by the widget that made it.

Every GUI poller builds its worker with ``parent=self``, so a long-lived widget
kept one QThread per poll for the life of the window. At 1 Hz (experiment
status), 3 s (alarm v2), 5 s (cooldown) and 10 s (operator log) that is roughly
5,900 workers an hour, which is the bulk of a measured 45 MB/h leak in the GUI
process on lab53 -- linear, with flat thread and descriptor counts, because the
OS thread exits and only the QObject survives.

The launcher already learned this for its own repeating workers
(launcher.py:8339: "A LauncherWindow parent would retain every replaced worker
for the window's full lifetime"). The GUI widgets never did.

These tests are XFAIL, and the reason is the point of the file.

The obvious fix -- `setParent(None)` in the worker's delivery slot -- was
implemented and measured: 200 polls left 200 retained workers before it and 0
after, with delivery still reaching the receiver. It was then REVERTED, because
it breaks `test_zmq_client_shutdown.py::test_application_close_settles_all_real_qthreads`,
which asserts `all(not isValid(worker) for worker in workers)` after the window
closes.

That assertion is the conflict. The Qt parent is not redundant retention on top
of `_GUI_WORKER_OWNERS`; it is ALSO the destruction mechanism at application
close. Dropping it stops the accumulation and simultaneously stops the C++
objects from ever being destroyed with their window -- trading a bounded-rate
leak for surviving QThread wrappers at interpreter exit.

`deleteLater()` satisfies both properties and is explicitly warned against at
launcher.py:8344: "registry callers may still hold terminal wrappers, and
deleteLater() would invalidate those wrappers before their owners clear them" --
and call sites do poll `isFinished()` on a retained attribute afterwards
(top_watch_bar.py:1124).

So a correct fix must destroy the worker after delivery AND leave every stale
wrapper safe to touch. That is a design task, not a patch. These tests stay as
the executable statement of the defect and its measurement.
"""

import gc

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cryodaq.gui.zmq_client import (  # noqa: E402
    ZmqCommandWorker,
    capture_gui_worker_session_token,
    gui_command_worker_admission_open,
    open_gui_command_worker_admission,
    revoke_gui_command_worker_admission,
)

POLLS = 200

_CONFLICT = (
    "setParent(None) fixes this but breaks test_application_close_settles_all_real_qthreads, "
    "which requires the Qt parent to destroy workers at window close. Needs a fix that both "
    "destroys after delivery and keeps stale wrappers safe."
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def session_epoch():
    """A live worker session, so deliveries count as current.

    `_session_epoch` is only stamped when a worker is STARTED, so a worker
    built but never started delivers nothing -- correctly. These tests drive
    the real admission API instead of faking it.
    """
    if gui_command_worker_admission_open():
        # Another test left a live session; use it rather than a null epoch,
        # which would make every delivery look stale and pass vacuously.
        yield capture_gui_worker_session_token()
        return
    epoch = open_gui_command_worker_admission()
    try:
        yield epoch
    finally:
        revoke_gui_command_worker_admission(epoch)


def _deliver(worker: ZmqCommandWorker, epoch: int) -> None:
    """Run the delivery slot exactly as a queued result would."""
    worker._session_epoch = epoch
    worker._deliver_result_if_current(epoch, {"ok": True})


@pytest.mark.xfail(reason=_CONFLICT, strict=True)
def test_a_delivered_worker_releases_its_parent(qapp, session_epoch):
    parent = QObject()
    worker = ZmqCommandWorker({"cmd": "experiment_status"}, parent=parent)
    assert worker.parent() is parent
    _deliver(worker, session_epoch)
    assert worker.parent() is None, "the widget still owns a finished worker"


@pytest.mark.xfail(reason=_CONFLICT, strict=True)
def test_repeated_polls_do_not_accumulate_on_the_widget(qapp, session_epoch):
    """The signature of the leak: children growing once per poll, forever."""
    parent = QObject()
    for _ in range(POLLS):
        worker = ZmqCommandWorker({"cmd": "alarm_v2_status"}, parent=parent)
        _deliver(worker, session_epoch)
    retained = len(parent.children())
    assert retained == 0, f"{retained} finished workers retained after {POLLS} polls"


@pytest.mark.xfail(reason=_CONFLICT, strict=True)
def test_a_worker_capturing_lambda_does_not_outlive_delivery(qapp, session_epoch):
    """dashboard_view passes `completed_worker=worker` into its lambda.

    That cycle runs through the C++ signal connection, which Python's GC cannot
    traverse, so it leaks even with no parent. Disconnecting breaks it.
    """
    parent = QObject()
    seen: list[object] = []
    workers = []
    for _ in range(POLLS):
        worker = ZmqCommandWorker({"cmd": "log_get", "limit": 2, "log_scope": "all"}, parent=parent)
        worker.finished.connect(
            lambda result, completed_worker=worker: seen.append(completed_worker)
        )
        workers.append(worker)
        _deliver(worker, session_epoch)

    assert len(seen) == POLLS, "delivery must still reach the receiver before release"
    assert len(parent.children()) == 0
    for worker in workers:
        assert worker.parent() is None


def test_delivery_still_reaches_the_receiver(qapp, session_epoch):
    """Releasing must happen after the emit, never instead of it."""
    parent = QObject()
    got: list[dict] = []
    worker = ZmqCommandWorker({"cmd": "experiment_status"}, parent=parent)
    worker.finished.connect(got.append)
    _deliver(worker, session_epoch)
    assert got == [{"ok": True}], "the result was dropped"


def test_the_worker_object_survives_a_stale_wrapper_touch(qapp, session_epoch):
    """Call sites poll `isFinished()` on a retained attribute afterwards.

    The object must be released, not deleted -- deleteLater() here would
    invalidate those wrappers, which is the trap the launcher comment warns of.
    """
    parent = QObject()
    worker = ZmqCommandWorker({"cmd": "experiment_status"}, parent=parent)
    _deliver(worker, session_epoch)
    gc.collect()
    assert worker.isFinished() in (True, False), "the wrapper became unusable"
