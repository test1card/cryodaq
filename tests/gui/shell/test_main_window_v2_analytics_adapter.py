"""Regression tests for the B.8 analytics channel adapter in MainWindowV2.

Covers the post-Codex fix: the v2 AnalyticsView exposes setters
(`set_cooldown`, `set_r_thermal`, `set_fault`) instead of the legacy
`on_reading` sink, so the shell must translate specific `analytics/*`
channels into typed snapshots before pushing them at the panel. Any
other `analytics/*` channel must be silently dropped — dispatching one
through the shell while the v2 panel is installed must not raise.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.shell.views.analytics_view import (
    AnalyticsView,
    CooldownData,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(w: MainWindowV2) -> None:
    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def _make_reading(
    channel: str,
    value: float = 0.0,
    *,
    metadata: dict | None = None,
) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="cooldown_predictor",
        channel=channel,
        value=value,
        unit="h",
        status=ChannelStatus.OK,
        metadata=metadata or {},
    )


# ──────────────────────────────────────────────────────────────────────


def test_cooldown_eta_reading_populates_analytics_view():
    """The shell adapter must translate the real plugin payload shape
    from cooldown_service.py:400-433 into a CooldownData and push it to
    the v2 AnalyticsView via set_cooldown()."""
    _app()
    w = MainWindowV2()
    _stop_timers(w)

    # Eagerly construct the analytics overlay so the adapter can push.
    w._ensure_overlay("analytics")
    assert isinstance(w._analytics_view, AnalyticsView)

    reading = _make_reading(
        "analytics/cooldown_predictor/cooldown_eta",
        value=7.33,
        metadata={
            "t_remaining_hours": 7.33,
            # Asymmetric 68% CI — low, high. Adapter must collapse to
            # conservative half-width max(high - t, t - low).
            "t_remaining_ci68": (6.83, 7.85),
            "progress": 0.425,  # fraction, NOT percent
            "phase": "phase1",
            "future_t": [0.0, 3.0, 7.0],
            "future_T_cold_mean": [295.0, 150.0, 50.0],
            "future_T_cold_upper": [295.0, 160.0, 55.0],
            "future_T_cold_lower": [295.0, 140.0, 45.0],
        },
    )

    w._dispatch_reading(reading)
    # Panel's stored snapshot matches the translated CooldownData.
    snap = w._analytics_view._last_cooldown
    assert isinstance(snap, CooldownData)
    assert snap.t_hours == 7.33
    # conservative ±: max(7.85 - 7.33, 7.33 - 6.83) = 0.52
    assert abs(snap.ci_hours - 0.52) < 1e-9
    # progress fraction → percent
    assert abs(snap.progress_pct - 42.5) < 1e-9
    assert snap.phase == "phase1"
    # predicted trajectory zipped from future_t + future_T_cold_mean
    assert snap.predicted_trajectory == [(0.0, 295.0), (3.0, 150.0), (7.0, 50.0)]
    # CI trajectory zipped with lower/upper order
    assert snap.ci_trajectory == [
        (0.0, 295.0, 295.0),
        (3.0, 140.0, 160.0),
        (7.0, 45.0, 55.0),
    ]
    # actual_trajectory stays empty — plugin doesn't publish it.
    assert snap.actual_trajectory == []
    # phase_boundaries — plugin doesn't publish them either.
    assert snap.phase_boundaries_hours == []


def test_cooldown_eta_phase_steady_remaps_to_stabilizing():
    """Plugin emits 'steady' when p >= 0.98. Spec uses 'stabilizing'.
    The adapter is the translation boundary."""
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    w._ensure_overlay("analytics")

    reading = _make_reading(
        "analytics/cooldown_predictor/cooldown_eta",
        value=0.05,
        metadata={
            "t_remaining_hours": 0.05,
            "t_remaining_ci68": (0.0, 0.1),
            "progress": 0.99,
            "phase": "steady",
        },
    )
    w._dispatch_reading(reading)
    assert w._analytics_view._last_cooldown is not None
    assert w._analytics_view._last_cooldown.phase == "stabilizing"
    # 'complete' is never emitted today — plugin can't distinguish it.


def test_cooldown_eta_without_future_trajectory_stays_empty():
    """Cooldown readings published before the prediction buffer has
    filled may arrive without the optional future_* fields. The adapter
    must treat them as missing, not crash."""
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    w._ensure_overlay("analytics")

    reading = _make_reading(
        "analytics/cooldown_predictor/cooldown_eta",
        value=2.0,
        metadata={
            "t_remaining_hours": 2.0,
            "t_remaining_ci68": (1.8, 2.2),
            "progress": 0.75,
            "phase": "phase2",
            # no future_t / future_T_cold_*
        },
    )
    w._dispatch_reading(reading)
    snap = w._analytics_view._last_cooldown
    assert snap is not None
    assert snap.predicted_trajectory == []
    assert snap.ci_trajectory == []


def test_unknown_analytics_channel_is_silently_dropped():
    """The v2 panel has no generic sink. Any analytics/* channel that
    isn't cooldown_predictor/cooldown_eta must be a no-op on the panel
    — no AttributeError, no set_cooldown, no set_r_thermal."""
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    w._ensure_overlay("analytics")
    # Prior state: panel was initialised in empty state.
    assert w._analytics_view._last_cooldown is None

    for channel in (
        "analytics/safety_state",
        "analytics/alarm_count",
        "analytics/keithley_channel_state/smua",
        "analytics/operator_log_entry",
        "analytics/some_future_plugin/whatever",
    ):
        # Must not raise.
        w._dispatch_reading(
            _make_reading(channel, value=1.0, metadata={"state": "safe_off"})
        )

    # Panel's snapshot is untouched — adapter dropped the readings.
    assert w._analytics_view._last_cooldown is None


def test_analytics_reading_without_panel_opened_does_not_crash():
    """If the operator never opens the analytics overlay, the panel is
    never lazily constructed. The adapter must short-circuit cleanly."""
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    assert w._analytics_view is None  # lazy factory hasn't fired

    w._dispatch_reading(
        _make_reading(
            "analytics/cooldown_predictor/cooldown_eta",
            value=5.0,
            metadata={
                "t_remaining_hours": 5.0,
                "t_remaining_ci68": (4.5, 5.5),
                "progress": 0.2,
                "phase": "phase1",
            },
        )
    )
    # Still no panel; no exception.
    assert w._analytics_view is None


def test_cooldown_adapter_tolerates_malformed_metadata():
    """Plugin upgrades / partial-fill scenarios shouldn't break the
    adapter — missing numeric fields default sensibly or drop the
    reading rather than crashing the shell."""
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    w._ensure_overlay("analytics")

    # Missing t_remaining_hours falls back to reading.value.
    w._dispatch_reading(
        _make_reading(
            "analytics/cooldown_predictor/cooldown_eta",
            value=3.3,
            metadata={"progress": 0.5, "phase": "phase1"},
        )
    )
    snap = w._analytics_view._last_cooldown
    assert snap is not None and snap.t_hours == 3.3
    assert snap.ci_hours == 0.0  # missing CI → zero, not crash

    # Non-tuple ci64 should degrade to zero, not raise.
    w._dispatch_reading(
        _make_reading(
            "analytics/cooldown_predictor/cooldown_eta",
            value=1.1,
            metadata={
                "t_remaining_hours": 1.1,
                "t_remaining_ci68": "not-a-tuple",
                "progress": 0.9,
                "phase": "phase2",
            },
        )
    )
    snap = w._analytics_view._last_cooldown
    assert snap is not None and snap.ci_hours == 0.0


def test_experiment_status_propagates_phase_to_analytics():
    """Phase III.C: the current experiment phase broadcast arriving in
    `_on_experiment_status_received` must be forwarded to the
    AnalyticsView via `set_phase`, driving its dynamic layout."""
    _app()
    w = MainWindowV2()
    try:
        # Force analytics lazy factory before the status tick.
        w._ensure_overlay("analytics")
        w._on_experiment_status_received(
            {"active_experiment": {}, "current_phase": "vacuum"}
        )
        assert w._analytics_view.current_phase() == "vacuum"
    finally:
        w._status_timer.stop()


def test_experiment_status_missing_phase_clears_analytics_phase():
    """No current_phase field → AnalyticsView phase resets to None
    (falls back to the fallback layout)."""
    _app()
    w = MainWindowV2()
    try:
        w._ensure_overlay("analytics")
        w._on_experiment_status_received(
            {"active_experiment": {}, "current_phase": "vacuum"}
        )
        assert w._analytics_view.current_phase() == "vacuum"
        w._on_experiment_status_received({"active_experiment": None})
        assert w._analytics_view.current_phase() is None
    finally:
        w._status_timer.stop()


def test_static_adapter_method_is_pure():
    """`_cooldown_reading_to_data` should be callable without a
    MainWindowV2 instance — it's a pure translator, not shell state."""
    reading = _make_reading(
        "analytics/cooldown_predictor/cooldown_eta",
        value=7.0,
        metadata={
            "t_remaining_hours": 7.0,
            "t_remaining_ci68": (6.5, 7.5),
            "progress": 0.3,
            "phase": "phase1",
        },
    )
    data = MainWindowV2._cooldown_reading_to_data(reading)
    assert data is not None
    assert data.t_hours == 7.0
    assert abs(data.ci_hours - 0.5) < 1e-9
    assert abs(data.progress_pct - 30.0) < 1e-9
