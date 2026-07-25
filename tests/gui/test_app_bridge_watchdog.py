"""Bridge watchdog restart-storm regression tests.

Reproduces the defect an external reviewer found statically in
``gui/app.py``'s per-tick bridge watchdog: whenever ``bridge.is_healthy()``
is False, the watchdog called ``bridge.shutdown()`` + ``bridge.start()``
unconditionally, every tick, with no cap on consecutive failures and no
``try/except`` around ``start()`` (which raises on persistent failure per
``gui/zmq_client.py``). After a failed start the bridge is neither alive nor
healthy, so the next tick repeats the whole spawn-and-rollback cycle
forever (4 mp.Queues + a safe-IPC bundle + a process spawn, per tick).

The fix, ``gui.app._BridgeWatchdog``, mirrors
``LauncherWindow._latch_bridge_watchdog_hold`` /
``_replace_bridge_from_watchdog`` in ``launcher.py``: bound the number of
consecutive restart failures and latch HOLD once the bound is hit, never
retrying again, and never reporting the latched bridge as healthy.

This ``50 ticks, 50 calls`` figure is static analysis of the parent commit
``526c2f24``'s ``gui/app.py``, not an observed failing run. That parent had
no module-level watchdog -- the per-tick restart path was a nested ``_tick()``
closure defined inside ``main()`` (it closes over ``main()``'s locals, so it
cannot be imported or unit-tested in isolation). Read straight off that nested
``_tick``: when ``bridge.is_healthy()`` is False it calls ``bridge.shutdown()``
+ ``bridge.start()`` and returns, with no cap on consecutive failures and no
``try/except`` around ``start()`` -- so a dead bridge would be
spawn-and-rollbacked once per tick for as long as ``main()``'s QTimer fires.
There is no reproducible 50-for-50 red to rerun against the committed parent;
the regression guard is
``test_bridge_watchdog_restart_attempts_are_bounded_when_start_always_fails``
below, run against the current module-level ``_BridgeWatchdog`` (bound by
``_BRIDGE_RESTART_ATTEMPT_LIMIT``).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from cryodaq.gui import app as gui_app


def _make_dead_bridge(*, start_error: Exception | None) -> MagicMock:
    bridge = MagicMock()
    bridge.is_healthy.return_value = False
    bridge.is_alive.return_value = False
    if start_error is not None:
        bridge.start.side_effect = start_error
    return bridge


def test_bridge_watchdog_restart_attempts_are_bounded_when_start_always_fails() -> None:
    """A bridge whose start() always raises must not be retried forever."""
    bridge = _make_dead_bridge(start_error=RuntimeError("persistent start failure"))
    window = MagicMock()
    snapshot_ingress = MagicMock()
    watchdog = gui_app._BridgeWatchdog()

    for _ in range(50):
        watchdog.tick(bridge=bridge, window=window, snapshot_ingress=snapshot_ingress)

    # The whole point of a settlement latch: restart attempts must plateau
    # at the bound, not grow 1:1 with the number of ticks (50 here).
    assert bridge.start.call_count == gui_app._BRIDGE_RESTART_ATTEMPT_LIMIT
    assert watchdog.latched is True

    # Further ticks must not attempt any more restarts at all.
    for _ in range(50):
        watchdog.tick(bridge=bridge, window=window, snapshot_ingress=snapshot_ingress)
    assert bridge.start.call_count == gui_app._BRIDGE_RESTART_ATTEMPT_LIMIT


def test_bridge_watchdog_recovers_on_second_attempt() -> None:
    """A bridge that fails once then succeeds must still be restarted normally."""
    bridge = MagicMock()
    bridge.is_alive.return_value = False
    call_count = {"n": 0}

    def _start_side_effect() -> None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("transient start failure")

    bridge.start.side_effect = _start_side_effect
    # Health flips to healthy only after the successful (second) start.
    bridge.is_healthy.side_effect = lambda: call_count["n"] >= 2
    bridge.data_flow_stalled.return_value = False
    window = MagicMock()
    snapshot_ingress = MagicMock()
    watchdog = gui_app._BridgeWatchdog()

    watchdog.tick(bridge=bridge, window=window, snapshot_ingress=snapshot_ingress)  # fails
    watchdog.tick(bridge=bridge, window=window, snapshot_ingress=snapshot_ingress)  # recovers

    assert bridge.start.call_count == 2
    assert watchdog.latched is False

    # Healthy now -- a further tick must not restart again.
    watchdog.tick(bridge=bridge, window=window, snapshot_ingress=snapshot_ingress)
    assert bridge.start.call_count == 2


def test_latched_bridge_watchdog_never_reports_healthy() -> None:
    """Fail-closed: once latched, the watchdog must never say the bridge is healthy."""
    bridge = _make_dead_bridge(start_error=RuntimeError("persistent start failure"))
    window = MagicMock()
    snapshot_ingress = MagicMock()
    watchdog = gui_app._BridgeWatchdog()

    for _ in range(gui_app._BRIDGE_RESTART_ATTEMPT_LIMIT):
        watchdog.tick(bridge=bridge, window=window, snapshot_ingress=snapshot_ingress)
    assert watchdog.latched is True

    # Even if the underlying bridge mock is flipped to claim healthy (e.g. a
    # stale/lying heartbeat), the watchdog's own view must stay fail-closed.
    bridge.is_healthy.return_value = True
    assert watchdog.is_healthy(bridge) is False
