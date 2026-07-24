"""Top-level GUI test lifecycle ownership and isolation.

Most ``tests/gui/*.py`` tests create QWidgets without tearing them down, so they
accumulate on the shared session ``QApplication``. By the time
``tests/gui/test_app_palette.py`` calls an application-global
``app.setStyleSheet(...)``, Qt must re-polish every leaked widget — which on
Windows CI raises a fatal access violation (the original ~78%-through crash).

The autouse root stops scheduling sources, revokes the exact process-wide GUI
worker epoch, settles registered workers, then drains widgets and queued events.
The live bridge fixture separately exercises the real bridge startup/shutdown
state machine without operating a real subprocess or reply-consumer thread.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from tests._widget_cleanup import drain_gui_widgets

_ADMISSION_OWNER_MARKER = "owns_gui_command_worker_admission"
_ADMISSION_OWNER_NODEIDS = frozenset(
    {
        (
            "tests/gui/test_zmq_client_mutation_handshake.py"
            "::test_actual_qt_command_worker_cancels_without_late_callback"
        ),
        (
            "tests/gui/test_zmq_client_mutation_handshake.py"
            "::test_queued_completion_from_prior_session_cannot_cross_reopen"
        ),
        (
            "tests/gui/test_zmq_client_mutation_handshake.py"
            "::test_gui_command_worker_base_exception_is_fixed_and_redacted"
        ),
        ("tests/gui/test_zmq_client_shutdown.py::test_application_close_settles_all_real_qthreads"),
        (
            "tests/gui/state/test_operator_snapshot_runtime_roots.py"
            "::test_app_main_runs_one_retained_owner_to_real_pod_and_stops_once"
        ),
        (
            "tests/gui/state/test_operator_snapshot_runtime_roots.py"
            "::test_standalone_close_request_exits_event_loop_for_hold_settlement"
        ),
    }
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Declare the exact tests that deliberately own or replace admission."""

    for item in items:
        if item.nodeid.replace(chr(92), "/") in _ADMISSION_OWNER_NODEIDS:
            item.add_marker(getattr(pytest.mark, _ADMISSION_OWNER_MARKER))


def _stop_gui_scheduling_sources(app: Any) -> None:
    """Stop timers before the process-wide command-worker admission cut."""

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    widgets = list(QApplication.topLevelWidgets())
    timers = list(app.findChildren(QTimer))
    for widget in widgets:
        try:
            timers.extend(widget.findChildren(QTimer))
        except RuntimeError:
            pass
    for timer in timers:
        try:
            timer.stop()
        except RuntimeError:
            pass


@pytest.fixture(autouse=True)
def gui_worker_root_epoch(request: pytest.FixtureRequest) -> Iterator[int | None]:
    """Own one ordinary GUI worker epoch and prove complete teardown."""

    from PySide6.QtWidgets import QApplication

    import cryodaq.gui.zmq_client as zc

    owns_admission = request.node.get_closest_marker(_ADMISSION_OWNER_MARKER) is not None
    session_epoch = None if owns_admission else zc.open_gui_command_worker_admission()
    leaked_or_replaced_admission = False
    try:
        yield session_epoch
    finally:
        app = QApplication.instance()
        if app is not None:
            _stop_gui_scheduling_sources(app)

        if zc.gui_command_worker_admission_open():
            current_epoch = zc.capture_gui_worker_session_token()
            leaked_or_replaced_admission = owns_admission or current_epoch != session_epoch
            zc.revoke_gui_command_worker_admission(current_epoch)

        workers_settled = zc.settle_registered_gui_command_workers()
        if app is not None:
            drain_gui_widgets(app)

        remaining_workers = zc.registered_gui_command_workers()
        assert not zc.gui_command_worker_admission_open()
        assert workers_settled
        assert remaining_workers == ()
        assert not leaked_or_replaced_admission


class _LiveProcess:
    """Process-shaped owner that settles only after the real stop signal."""

    pid = 42_001

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._args = kwargs.get("args", args[1] if len(args) > 1 else ())
        self._alive = False
        self._started = False
        self.exitcode: int | None = None

    def start(self) -> None:
        assert not self._started
        self._started = True
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        del timeout
        shutdown_event = self._args[5]
        if shutdown_event.is_set():
            self._alive = False
            self.exitcode = 0

    def terminate(self) -> None:
        self._alive = False
        self.exitcode = -15

    def kill(self) -> None:
        self._alive = False
        self.exitcode = -9


class _LiveThread:
    """Thread-shaped owner that settles only after the real reply stop cut."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._target = kwargs.get("target", args[0] if args else None)
        self._alive = False
        self._started = False

    def start(self) -> None:
        assert not self._started
        self._started = True
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        del timeout
        owner = getattr(self._target, "__self__", None)
        stop_event = getattr(owner, "_reply_stop", None)
        if stop_event is not None and stop_event.is_set():
            self._alive = False


@pytest.fixture
def live_zmq_bridge(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Start a real bridge lifecycle around stateful process/thread owners."""

    import cryodaq.gui.zmq_client as zc

    real_process_constructor = zc.mp.Process
    real_thread_constructor = zc.threading.Thread
    bridge = zc.ZmqBridge()
    with monkeypatch.context() as startup_patch:
        startup_patch.setattr(zc.mp, "Process", _LiveProcess)
        startup_patch.setattr(zc.threading, "Thread", _LiveThread)
        bridge.start()

    assert zc.mp.Process is real_process_constructor
    assert zc.threading.Thread is real_thread_constructor
    assert isinstance(bridge._process, _LiveProcess)
    assert isinstance(bridge._reply_consumer, _LiveThread)
    assert isinstance(bridge._safe_reply_consumer, _LiveThread)
    assert bridge._process_started
    assert bridge._reply_consumer_started
    assert bridge._safe_reply_consumer_started
    assert bridge._process.is_alive()
    assert bridge._reply_consumer.is_alive()
    assert bridge._safe_reply_consumer.is_alive()
    assert bridge._command_admission_open
    assert not bridge._reply_stop.is_set()
    assert bridge._generation_fatal is None
    bridge_instance_id = bridge.bridge_instance_id
    assert type(bridge_instance_id) is str
    assert len(bridge_instance_id) == 32
    assert all(character in "0123456789abcdef" for character in bridge_instance_id)

    process_owner = bridge._process
    ordinary_owner = bridge._reply_consumer
    safe_owner = bridge._safe_reply_consumer
    try:
        yield bridge
    finally:
        if not bridge._terminal_closed:
            bridge.shutdown()
            bridge.close()

        assert not process_owner.is_alive()
        assert not ordinary_owner.is_alive()
        assert not safe_owner.is_alive()
        assert bridge._terminal_closed
        assert bridge._process is None
        assert bridge._reply_consumer is None
        assert bridge._safe_reply_consumer is None
        assert not bridge._process_started
        assert not bridge._reply_consumer_started
        assert not bridge._safe_reply_consumer_started
        assert not bridge._command_admission_open
        assert bridge._reply_stop.is_set()
        assert bridge.bridge_instance_id is None
