"""Tests for OverlayPanelBase (roadmap B4 — overlay-panel base class).

Pure-Python mixin, no QObject base — these tests need no QApplication.
"""

from __future__ import annotations

from cryodaq.gui.shell.overlays._base_panel import OverlayPanelBase, is_stale


class _FakeSignal:
    """Mirrors the existing panel tests' stub — single slot, sync emit."""

    def __init__(self) -> None:
        self._slot = None

    def connect(self, slot) -> None:
        self._slot = slot

    def emit(self, *args) -> None:
        if self._slot is not None:
            self._slot(*args)


class _FakeWorker:
    """Stand-in for ZmqCommandWorker: records start(), controls isRunning()."""

    def __init__(self) -> None:
        self.finished = _FakeSignal()
        self.started = False
        self._running = True

    def start(self) -> None:
        self.started = True

    def isRunning(self) -> bool:  # noqa: N802 — Qt method name
        return self._running


class _Panel(OverlayPanelBase):
    """Minimal concrete mixin user — no QWidget needed for these tests."""


# ----------------------------------------------------------------------
# __init__
# ----------------------------------------------------------------------


def test_init_sets_disconnected_and_empty_worker_list() -> None:
    panel = _Panel()
    assert panel._connected is False
    assert panel._workers == []


def test_init_forwards_args_to_cooperative_super() -> None:
    """Mixin must not swallow args meant for the next class in the MRO."""

    seen = {}

    class _Tail:
        def __init__(self, x, *, y=None) -> None:
            seen["x"] = x
            seen["y"] = y

    class _Combined(OverlayPanelBase, _Tail):
        pass

    _Combined(1, y=2)
    assert seen == {"x": 1, "y": 2}


# ----------------------------------------------------------------------
# _register_worker
# ----------------------------------------------------------------------


def test_register_worker_starts_and_tracks() -> None:
    panel = _Panel()
    worker = _FakeWorker()

    panel._register_worker(worker, lambda result: None)

    assert worker.started is True
    assert worker in panel._workers


def test_register_worker_prunes_finished_and_calls_on_result() -> None:
    panel = _Panel()
    worker = _FakeWorker()
    received = []

    panel._register_worker(worker, received.append)

    # Worker "finishes": isRunning flips False before the signal fires,
    # matching real ZmqCommandWorker/QThread teardown order.
    worker._running = False
    worker.finished.emit({"ok": True, "value": 42})

    assert received == [{"ok": True, "value": 42}]
    assert panel._workers == []  # pruned


def test_register_worker_keeps_still_running_siblings() -> None:
    panel = _Panel()
    worker_a = _FakeWorker()
    worker_b = _FakeWorker()

    panel._register_worker(worker_a, lambda _r: None)
    panel._register_worker(worker_b, lambda _r: None)

    worker_a._running = False
    worker_a.finished.emit({"ok": True})

    # b is still "running" — must survive the prune triggered by a's finish.
    assert panel._workers == [worker_b]


# ----------------------------------------------------------------------
# set_connected
# ----------------------------------------------------------------------


def test_set_connected_true_on_first_change() -> None:
    panel = _Panel()
    assert panel.set_connected(True) is True
    assert panel._connected is True


def test_set_connected_false_when_value_unchanged() -> None:
    panel = _Panel()
    panel.set_connected(True)
    assert panel.set_connected(True) is False
    assert panel._connected is True


def test_set_connected_coerces_truthy_values() -> None:
    panel = _Panel()
    assert panel.set_connected(1) is True
    assert panel._connected is True
    assert panel.set_connected(1) is False  # bool(1) == True == current


def test_set_connected_true_again_after_flip_back() -> None:
    panel = _Panel()
    panel.set_connected(True)
    assert panel.set_connected(False) is True
    assert panel.set_connected(True) is True


# ----------------------------------------------------------------------
# is_stale
# ----------------------------------------------------------------------


def test_is_stale_none_last_update_is_not_stale() -> None:
    assert is_stale(None, 5.0, now=100.0) is False


def test_is_stale_within_timeout_is_false() -> None:
    assert is_stale(100.0, 5.0, now=104.0) is False


def test_is_stale_exactly_at_timeout_is_false() -> None:
    assert is_stale(100.0, 5.0, now=105.0) is False


def test_is_stale_past_timeout_is_true() -> None:
    assert is_stale(100.0, 5.0, now=105.1) is True


def test_is_stale_defaults_now_to_monotonic() -> None:
    import time

    recent = time.monotonic()
    assert is_stale(recent, 5.0) is False
