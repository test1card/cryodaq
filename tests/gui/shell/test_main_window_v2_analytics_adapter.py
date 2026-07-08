"""Regression tests for the B.8 analytics channel adapter in MainWindowV2.

Covers the post-fix: the v2 AnalyticsView exposes setters
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

    import time as _time
    before_ts = _time.time()
    w._dispatch_reading(reading)
    after_ts = _time.time()
    # Panel's stored snapshot matches the translated CooldownData.
    snap = w._analytics_view._last_cooldown
    assert isinstance(snap, CooldownData)
    assert snap.t_hours == 7.33
    # conservative ±: max(7.85 - 7.33, 7.33 - 6.83) = 0.52
    assert abs(snap.ci_hours - 0.52) < 1e-9
    # progress fraction → percent
    assert abs(snap.progress_pct - 42.5) < 1e-9
    assert snap.phase == "phase1"
    # T4 fix: future_t (hours-from-now) is converted to absolute Unix
    # timestamps so the DateAxisItem renders a real date instead of 1970.
    # Predicted trajectory: 3 entries with hours [0.0, 3.0, 7.0] →
    # timestamps [now, now+3h, now+7h] paired with the temperature list.
    assert len(snap.predicted_trajectory) == 3
    for (ts, _v), expected_hours in zip(
        snap.predicted_trajectory, [0.0, 3.0, 7.0]
    ):
        assert before_ts + expected_hours * 3600 - 1 <= ts <= after_ts + expected_hours * 3600 + 1
    assert [v for _, v in snap.predicted_trajectory] == [295.0, 150.0, 50.0]
    # CI trajectory: same time-axis treatment, with lower/upper order.
    assert len(snap.ci_trajectory) == 3
    for (ts, lo, hi), expected_hours, expected_lo, expected_hi in zip(
        snap.ci_trajectory,
        [0.0, 3.0, 7.0],
        [295.0, 140.0, 45.0],
        [295.0, 160.0, 55.0],
    ):
        assert before_ts + expected_hours * 3600 - 1 <= ts <= after_ts + expected_hours * 3600 + 1
        assert lo == expected_lo
        assert hi == expected_hi
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
    — no AttributeError, no set_cooldown, no set_r_thermal, no set_pressure."""
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    w._ensure_overlay("analytics")
    # Prior state: panel was initialised in empty state.
    assert w._analytics_view._last_cooldown is None
    assert w._analytics_view._last_pressure_reading is None

    # Capture snapshot before dispatching unknown channels.
    snapshot_before = dict(w._analytics_snapshot)

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

    # Panel's snapshot is untouched — adapter dropped all unknown readings.
    assert w._analytics_view._last_cooldown is None, (
        "set_cooldown must not be called for unknown analytics channels"
    )
    assert w._analytics_view._last_pressure_reading is None, (
        "set_pressure_reading must not be called for unknown analytics channels"
    )
    # No new setter keys added to the snapshot.
    assert w._analytics_snapshot == snapshot_before, (
        f"Snapshot changed after unknown channels: "
        f"new keys = {set(w._analytics_snapshot) - set(snapshot_before)}"
    )


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


# ── v0.52.5 regression tests ──────────────────────────────────────────


def test_mbar_latin_pressure_reading_reaches_analytics():
    """Regression v0.52.5 Bug A: Thyracont VSP63D publishes unit='mbar'
    (Latin ASCII). The dispatch guard must accept both 'мбар' (Cyrillic)
    and 'mbar' (Latin) — previously only the Cyrillic form was accepted,
    silently dropping every pressure reading before it reached analytics."""
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    w._ensure_overlay("analytics")

    reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="VSP63D_1",
        channel="VSP63D_1/pressure",
        value=1.5e-6,
        unit="mbar",  # Latin — what the driver actually publishes
        status=ChannelStatus.OK,
        metadata={},
    )
    w._dispatch_reading(reading)

    assert "set_pressure_reading" in w._analytics_snapshot, (
        "Pressure reading with unit='mbar' was silently dropped; "
        "main_window_v2.py guard must accept both 'мбар' and 'mbar'"
    )
    # Assert the Reading value that was forwarded is exactly the dispatched one.
    # _analytics_snapshot stores args tuples: {"set_pressure_reading": (reading,)}
    snapshot_args = w._analytics_snapshot["set_pressure_reading"]
    dispatched_reading = snapshot_args[0] if snapshot_args else None
    assert dispatched_reading is not None, "snapshot args must not be empty"
    assert dispatched_reading.value == 1.5e-6, (
        f"Reading value forwarded to analytics: expected 1.5e-6, got {dispatched_reading.value!r}"
    )
    assert dispatched_reading.unit == "mbar", (
        f"Reading unit forwarded to analytics: expected 'mbar', got {dispatched_reading.unit!r}"
    )
    # AnalyticsView stores the last pressure reading; verify it reached the view.
    assert w._analytics_view._last_pressure_reading is not None, (
        "AnalyticsView._last_pressure_reading must be set after dispatch"
    )
    assert w._analytics_view._last_pressure_reading.value == 1.5e-6


def test_temperature_overview_xaxis_scrolls_with_live_readings():
    """Regression v0.52.5 Bug B: TemperatureOverviewWidget._apply_window()
    was called once at __init__, then pyqtgraph's pi.autoRange() disabled
    the autorange by calling setRange() with disableAutoRange=True.
    Live readings (Unix timestamps ~1.7e9) fell outside the frozen
    default range, producing an empty plot.
    After the fix, set_temperature_readings() re-calls _apply_window() on
    every batch, keeping the right X edge at 'now'."""
    import time

    from cryodaq.gui.shell.views.analytics_widgets import TemperatureOverviewWidget

    _app()
    widget = TemperatureOverviewWidget()
    now = time.time()

    reading = Reading(
        timestamp=datetime.fromtimestamp(now, tz=UTC),
        instrument_id="LS218_1",
        channel="Т1 Криостат верх",
        value=77.3,
        unit="K",
        status=ChannelStatus.OK,
        metadata={},
    )
    widget.set_temperature_readings({"Т1 Криостат верх": reading})

    pi = widget._plot.getPlotItem()
    _, xmax = pi.getViewBox().viewRange()[0]
    assert xmax >= now - 10, (
        f"X-axis right edge ({xmax:.1f}) is earlier than reading timestamp "
        f"({now:.1f}); the X-axis is frozen at the default range — "
        "v0.52.5 regression: set_temperature_readings must call _apply_window()"
    )


# ──────────────────────────────────────────────────────────────────────
# F-MockPredictor — cold-stage reading wiring (v0.54.0 cycle 2)
# ──────────────────────────────────────────────────────────────────────


def _t_reading(channel: str, value: float = 4.5) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LS218_1",
        channel=channel,
        value=value,
        unit="K",
        status=ChannelStatus.OK,
        metadata={},
    )


def test_cold_stage_reading_routed_to_analytics_view():
    """Т12 readings (canonical cold-stage landmark) must be pushed into
    AnalyticsView via set_cold_temperature_reading and cached in the
    F4 lazy-replay snapshot, while non-Т12 K-unit readings must NOT
    trigger the cold-stage forwarder.
    """
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    w._ensure_overlay("analytics")
    assert isinstance(w._analytics_view, AnalyticsView)

    # Canonical short-id form.
    short_reading = _t_reading("Т12", value=4.51)
    w._dispatch_reading(short_reading)
    assert w._analytics_view._last_cold_temperature_reading is short_reading
    assert w._analytics_snapshot.get("set_cold_temperature_reading") == (short_reading,)

    # Long-form "Т12 <label>" must also route through the canonical short id.
    long_reading = _t_reading("Т12 Холодная плита", value=4.52)
    w._dispatch_reading(long_reading)
    assert w._analytics_view._last_cold_temperature_reading is long_reading

    # A non-Т12 cold-channel reading must NOT replace the cached cold-stage
    # value — only Т12 feeds the asymptote predictor.
    w._dispatch_reading(_t_reading("Т11 Тёплая плита", value=77.0))
    assert w._analytics_view._last_cold_temperature_reading is long_reading


def test_cold_stage_reading_skipped_when_unit_not_kelvin():
    """Defensive: a Т12-named reading reported in non-K units (sensor fault
    metadata) must not be routed — the K-unit guard already gates this,
    but the dispatch path makes the assumption explicit."""
    _app()
    w = MainWindowV2()
    _stop_timers(w)
    w._ensure_overlay("analytics")

    bogus = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LS218_1",
        channel="Т12",
        value=4.5,
        unit="Ом",  # not K
        status=ChannelStatus.OK,
        metadata={},
    )
    w._dispatch_reading(bogus)
    assert w._analytics_view._last_cold_temperature_reading is None
