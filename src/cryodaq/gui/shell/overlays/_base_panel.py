"""OverlayPanelBase — shared overlay-panel machinery (roadmap B4).

Survey of the existing overlay panels (alarm/archive/instruments/keithley/
multiline/...) found the same things hand-rolled in every one of them:

1. A Python-side list of in-flight ``ZmqCommandWorker`` instances,
   appended to on dispatch and pruned (``[w for w in ... if
   w.isRunning()]``) inside the ``finished`` handler — Qt's QThread GC
   would otherwise race the reply, so the panel keeps a strong ref
   until the worker reports done.
2. A ``_connected: bool`` flag toggled by the shell via
   ``set_connected()``, in most panels guarded so a repeated call with
   the same value is a no-op.
3. A stale-data test — "has more than N seconds passed since the last
   update" (``docs/design-system/patterns/real-time-data.md`` — stale
   detection) — computed identically (module math, not visuals) in
   more than one panel.

This module factors #1/#2 into ``OverlayPanelBase`` and #3 into the
standalone ``is_stale`` function.

Deliberately NOT included: a wrapper for the "poll timer + skip if a
previous poll is still in flight" dance, and no sound-hook API. Every
panel guards a *different* in-flight flag name under a *different`
connected/active gating rule (one polls only while connected, another
only while a server-side mode is active, another gates on both) — a
generic wrapper would need per-call configuration that ends up no
shorter than the 3-4 lines it replaces, so each panel keeps its own
``_poll_x`` method wired directly to a ``QTimer``. Sound hooks
(``gui/shell/alarm_sound.py``) currently exist only on
``TopWatchBar``/``BottomStatusBar`` — zero overlay panels beep today,
so adding a hook for it here would be speculative; add it to this base
when the first overlay panel actually grows one.

``OverlayPanelBase`` is a plain mixin (no ``QObject`` base) so it drops
into both top-level ``QWidget`` overlay panels and internal ``QFrame``
row/card widgets without hitting PySide6's single-QObject-base rule:

    class AlarmPanel(OverlayPanelBase, QWidget):
        def __init__(self, parent=None) -> None:
            super().__init__(parent)  # sets self._connected, self._workers
            ...
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol


class _Worker(Protocol):
    """Shape this module needs from a worker — matches ``ZmqCommandWorker``.

    No import of ``ZmqCommandWorker`` here on purpose: panel tests
    monkeypatch *their own module's* ``ZmqCommandWorker`` name to a
    stub, so panels must keep constructing the worker themselves (with
    their own import) and only hand the already-built instance to
    ``_register_worker``.
    """

    finished: Any

    def start(self) -> None: ...
    def isRunning(self) -> bool: ...  # noqa: N802 — Qt method name


class OverlayPanelBase:
    """Mixin: worker retention/pruning + a guarded connected flag."""

    _connected: bool
    _workers: list[_Worker]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._connected = False
        self._workers = []

    def _register_worker(
        self, worker: _Worker, on_result: Callable[[dict], None]
    ) -> None:
        """Track ``worker``, start it, prune finished workers on completion.

        Centralizes the ``self._workers.append(worker); worker.start()``
        pair plus the ``self._workers = [w for w in self._workers if
        w.isRunning()]`` line every panel repeats inside its own
        ``finished`` handler. The caller still constructs the worker
        (``ZmqCommandWorker(cmd, parent=self)``) — this only wires
        retention + pruning + the result callback.
        """

        def _handle(result: dict) -> None:
            self._workers = [w for w in self._workers if w.isRunning()]
            on_result(result)

        worker.finished.connect(_handle)
        self._workers.append(worker)
        worker.start()

    def set_connected(self, connected: bool) -> bool:
        """Update ``_connected``; return whether it actually changed.

        Subclasses whose ``set_connected`` body should only run when
        the value actually flips call ``if not super().set_connected(
        connected): return`` first — this is the ``if connected ==
        self._connected: return`` guard nearly every panel opens with.
        Subclasses whose body must always run (e.g. idempotent label
        re-render) skip the base call and manage ``self._connected``
        themselves.
        """
        connected = bool(connected)
        if connected == self._connected:
            return False
        self._connected = connected
        return True


def is_stale(
    last_update_ts: float | None, timeout_s: float, *, now: float | None = None
) -> bool:
    """True if more than ``timeout_s`` has elapsed since ``last_update_ts``.

    ``last_update_ts=None`` means "never had data yet" — per
    ``docs/design-system/patterns/real-time-data.md`` that is the
    distinct "initial empty" state, not stale, so this returns False.
    """
    if last_update_ts is None:
        return False
    if now is None:
        now = time.monotonic()
    return (now - last_update_ts) > timeout_s
