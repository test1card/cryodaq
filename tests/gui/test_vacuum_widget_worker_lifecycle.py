"""VacuumPredictionWidget must not outlive, orphan, or stack its poll workers.

Reviewed at `ba5457af`. Four things were wrong together:

* the initial poll was a static ``QTimer.singleShot(500, ...)`` — owned by
  nobody, so destroying the widget inside that window left the callback armed;
* every poll built a local ``ZmqCommandWorker(parent=self)`` and kept no
  reference to it;
* nothing checked whether the previous poll had finished, so a slow engine let
  the 10 s timer stack workers;
* the worker stays alive after settlement as a child of the widget.

The real disposal path is ``AnalyticsView`` phase replacement —
``setParent(None)`` then ``deleteLater()`` at `analytics_view.py:283-284` — not
``closeEvent``. So a phase swap could delete the widget while a child QThread
was still running.

These tests drive that production boundary. A ``widget.close()`` test or a
MagicMock phase swap would exercise neither the real ``deleteLater()`` nor a
real QThread, which is why neither is used here.
"""

from __future__ import annotations

import threading
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture
def app():
    application = QApplication.instance() or QApplication([])
    yield application
    # Every worker these tests start MUST be settled before the test returns.
    # A real QThread left in flight outlives the test and can be torn down by a
    # later one's application teardown, which crashes the interpreter — the
    # first version of this file did exactly that and destabilised the whole
    # analytics partition. Draining a fixed interval is not enough; wait for
    # actual settlement.
    _settle_all(application)


def _settle_all(application, timeout_s: float = 5.0) -> None:
    """Drain until no worker this module started is in flight, or FAIL.

    Fail-closed on purpose. The previous version waited five seconds and then
    cleared the tracking list regardless, so a worker still running at teardown
    was silently forgotten — which could both manufacture a crash in a later
    test and conceal that this file was the origin. A real QThread left alive is
    a defect in the test, and the test must say so rather than leave it for the
    next file to trip over.
    """

    from cryodaq.gui.zmq_client import gui_worker_poll_in_flight

    tracked = list(_STARTED)
    _STARTED.clear()
    deadline = time.monotonic() + timeout_s
    alive: list = []
    while time.monotonic() < deadline:
        alive = [w for w in tracked if gui_worker_poll_in_flight(w)]
        if not alive:
            break
        application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        time.sleep(0.01)
    _drain(application, ms=150)
    if alive:
        raise AssertionError(
            f"{len(alive)} worker(s) still in flight after {timeout_s:.0f}s of bounded cleanup; "
            "a live QThread must not escape this test"
        )


_STARTED: list = []


def _drain(application, ms: int = 400) -> None:
    """Run the Qt loop long enough for deleteLater and thread settlement.

    Two things matter here.

    ``processEvents()`` alone does NOT deliver ``DeferredDelete``, so a
    ``deleteLater()`` widget stays alive through it — the first version of this
    helper missed that and the "destroyed before its timer" test failed because
    the widget had never actually been destroyed.

    The deadline is wall-clock rather than a ``QTimer.singleShot`` stop flag.
    The ``_pump`` helpers elsewhere in this suite drive a nested
    ``QEventLoop.exec()`` whose only exit is a timer, so once an earlier test
    has torn down the application object the timer never fires and the pump
    blocks forever — that is what wedges the full GUI partition. A wall-clock
    bound cannot do that.
    """

    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        application.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        time.sleep(0.005)


@pytest.fixture
def widget(app):
    from cryodaq.gui.shell.views.analytics_widgets import VacuumPredictionWidget

    created = VacuumPredictionWidget()
    yield created
    try:
        created.setParent(None)
        created.deleteLater()
        _drain(app)
    except RuntimeError:
        pass


class _Gate:
    """A send_command that blocks until released, so a poll stays in flight."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        self.entered.set()
        self.release.wait(timeout=10)
        return {"ok": True, "status": "no_data"}


def test_a_second_poll_is_refused_while_the_first_is_in_flight(widget, app, monkeypatch) -> None:
    """The 10 s timer must not stack workers on a slow engine."""

    import cryodaq.gui.zmq_client as zmq_client

    gate = _Gate()
    monkeypatch.setattr(zmq_client, "send_command", gate, raising=False)

    widget._trend_worker = None
    widget._poll_trend()
    assert gate.entered.wait(timeout=5), "the first poll should have started"
    first = widget._trend_worker
    assert first is not None
    _STARTED.append(first)

    widget._poll_trend()
    assert widget._trend_worker is first, "a second poll must not replace the in-flight worker"
    assert gate.calls == 1, "only one worker may run at a time"

    gate.release.set()
    _drain(app)


def test_polling_resumes_after_the_first_finishes(widget, app, monkeypatch) -> None:
    import cryodaq.gui.zmq_client as zmq_client

    gate = _Gate()
    monkeypatch.setattr(zmq_client, "send_command", gate, raising=False)

    widget._trend_worker = None
    widget._poll_trend()
    assert gate.entered.wait(timeout=5)
    _STARTED.append(widget._trend_worker)
    gate.release.set()
    _drain(app)

    assert widget._trend_worker is None, "the terminal path must clear the retained reference"

    gate2 = _Gate()
    gate2.release.set()
    monkeypatch.setattr(zmq_client, "send_command", gate2, raising=False)
    widget._poll_trend()
    _drain(app)
    assert gate2.calls >= 1, "polling must resume once the previous worker settled"


def test_destroying_the_widget_before_its_initial_timer_starts_no_work(app, monkeypatch) -> None:
    """The initial poll must die with the widget, not fire into a deleted object."""

    import cryodaq.gui.zmq_client as zmq_client
    from cryodaq.gui.shell.views.analytics_widgets import VacuumPredictionWidget

    started = {"n": 0}

    def _counting(*args, **kwargs):
        started["n"] += 1
        return {"ok": True, "status": "no_data"}

    monkeypatch.setattr(zmq_client, "send_command", _counting, raising=False)

    doomed = VacuumPredictionWidget()
    # Destroyed well inside the 500 ms initial window, via the production path.
    doomed.setParent(None)
    doomed.deleteLater()
    _drain(app, ms=900)

    assert started["n"] == 0, "a static singleShot survives its widget; the initial poll must be owned by it"


def test_a_phase_swap_while_a_poll_is_running_settles_cleanly(app, monkeypatch) -> None:
    """The production disposal path, with a real worker genuinely blocked.

    AnalyticsView replaces phase widgets with setParent(None) + deleteLater().
    If the running QThread were still a child of the widget, this is where it
    would be destroyed underneath itself.
    """

    import cryodaq.gui.zmq_client as zmq_client
    from cryodaq.gui.shell.views.analytics_widgets import VacuumPredictionWidget

    gate = _Gate()
    monkeypatch.setattr(zmq_client, "send_command", gate, raising=False)

    swapped = VacuumPredictionWidget()
    swapped._trend_worker = None
    swapped._poll_trend()
    assert gate.entered.wait(timeout=5), "the poll should be in flight"
    worker = swapped._trend_worker
    assert worker is not None
    _STARTED.append(worker)

    # Phase replacement while the worker is still blocked.
    swapped.setParent(None)
    swapped.deleteLater()
    _drain(app, ms=200)

    # Now let the engine reply. Nothing may crash and the thread must settle.
    gate.release.set()
    _drain(app, ms=800)

    # gui_worker_poll_in_flight, not isRunning(): once the registry has
    # destroyed a settled worker its C++ object is gone, and touching it raises
    # "Internal C++ object already deleted" — which is the CORRECT outcome, not
    # a failure. The helper exists precisely to answer this safely.
    from cryodaq.gui.zmq_client import gui_worker_poll_in_flight

    assert not gui_worker_poll_in_flight(worker), "the worker must reach terminal settlement"
