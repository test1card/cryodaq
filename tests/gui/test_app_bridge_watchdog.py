"""Bridge watchdog restart-storm regression tests.

``_BridgeWatchdog`` latches after repeated ``start()`` exceptions, while a
non-raising start that never regains engine health is retried on a monotonic
60-second cooldown. The latter preserves automatic recovery after an engine
restart without allowing a spawnable-but-disconnected engine to churn bridge
processes on every GUI tick.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cryodaq.gui import app as gui_app


def _make_dead_bridge(*, start_error: Exception | None) -> MagicMock:
    bridge = MagicMock()
    bridge.is_healthy.return_value = False
    bridge.is_alive.return_value = False
    if start_error is not None:
        bridge.start.side_effect = start_error
    return bridge


class _FakeMonotonic:
    """Wall-clock-independent monotonic source for watchdog cooldown tests."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


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


def test_bridge_watchdog_does_not_respawn_a_spawnable_but_unhealthy_engine_every_tick() -> None:
    """A non-raising start without a heartbeat is retried only after cooldown."""
    bridge = _make_dead_bridge(start_error=None)
    window = MagicMock()
    snapshot_ingress = MagicMock()
    clock = _FakeMonotonic()
    watchdog = gui_app._BridgeWatchdog(monotonic=clock)

    for _ in range(50):
        watchdog.tick(bridge=bridge, window=window, snapshot_ingress=snapshot_ingress)

    assert bridge.start.call_count == 1
    assert watchdog.latched is False

    clock.advance(gui_app._BRIDGE_SUCCESSFUL_RESTART_COOLDOWN_S - 1.0)
    watchdog.tick(bridge=bridge, window=window, snapshot_ingress=snapshot_ingress)
    assert bridge.start.call_count == 1

    clock.advance(1.0)
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


def test_bridge_watchdog_attempts_window_cut_when_snapshot_cut_fails() -> None:
    """A failed passive cut cannot skip independent GUI authority retirement."""
    calls: list[str] = []
    failure = RuntimeError("snapshot retirement failed")
    bridge = _make_dead_bridge(start_error=None)
    window = MagicMock()
    snapshot_ingress = MagicMock()

    def fail_snapshot() -> None:
        calls.append("snapshot")
        raise failure

    snapshot_ingress.invalidate_transport.side_effect = fail_snapshot
    window.invalidate_descriptor_transport.side_effect = lambda: calls.append("window")
    watchdog = gui_app._BridgeWatchdog()

    with pytest.raises(RuntimeError, match="snapshot retirement failed") as captured:
        watchdog._restart(
            bridge,
            window,
            snapshot_ingress,
            shutdown_first=False,
        )

    assert captured.value is failure
    assert calls == ["snapshot", "window"]
    bridge.shutdown.assert_not_called()
    bridge.start.assert_not_called()


def test_bridge_watchdog_groups_two_cut_failures_before_replacement() -> None:
    """Every invalidation error survives and no replacement work begins."""
    calls: list[str] = []
    snapshot_failure = RuntimeError("snapshot retirement failed")
    window_failure = ValueError("window retirement failed")
    bridge = _make_dead_bridge(start_error=None)
    window = MagicMock()
    snapshot_ingress = MagicMock()

    def fail_snapshot() -> None:
        calls.append("snapshot")
        raise snapshot_failure

    def fail_window() -> None:
        calls.append("window")
        raise window_failure

    snapshot_ingress.invalidate_transport.side_effect = fail_snapshot
    window.invalidate_descriptor_transport.side_effect = fail_window
    watchdog = gui_app._BridgeWatchdog()

    with pytest.raises(
        ExceptionGroup,
        match="multiple standalone GUI authority invalidations failed",
    ) as captured:
        watchdog._restart(
            bridge,
            window,
            snapshot_ingress,
            shutdown_first=True,
        )

    assert calls == ["snapshot", "window"]
    assert captured.value.exceptions[0] is snapshot_failure
    assert captured.value.exceptions[1] is window_failure
    bridge.shutdown.assert_not_called()
    bridge.start.assert_not_called()
