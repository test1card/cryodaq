"""F4 lazy-open snapshot replay — shell-level cache tests (F3-Cycle1).

Covers spec §4.5 acceptance criteria:
1. Opening AnalyticsView mid-experiment populates wired widgets with the
   most recent snapshot.
2. Closing and reopening preserves state (shell cache, not view cache).
3. Cache invalidates on experiment finalize / new experiment start.
4. Cache holds only the most recent snapshot per setter (no history leak).
5. set_fault is never replayed.

These tests exercise MainWindowV2._push_analytics + _ensure_overlay replay.
They do NOT test the within-view phase-swap replay (see
test_analytics_view_phase_aware.py for that).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import UTC, datetime

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.shell.main_window_v2 import MainWindowV2
from cryodaq.gui.shell.views.analytics_view import CooldownData
from cryodaq.gui.state.time_window import reset_time_window_controller


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _stop_timers(w: MainWindowV2) -> None:
    for timer in w.findChildren(QTimer):
        try:
            timer.stop()
        except RuntimeError:
            pass


def _cooldown_reading(t_hours: float = 5.0) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="cooldown_predictor",
        channel="analytics/cooldown_predictor/cooldown_eta",
        value=t_hours,
        unit="h",
        status=ChannelStatus.OK,
        metadata={
            "t_remaining_hours": t_hours,
            "t_remaining_ci68": (t_hours - 0.5, t_hours + 0.5),
            "progress": 0.4,
            "phase": "phase1",
        },
    )


def _pressure_reading(value: float = 1e-5) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="VSP63D_1",
        channel="VSP63D_1/pressure",
        value=value,
        unit="мбар",
        status=ChannelStatus.OK,
        metadata={},
    )


def _keithley_reading(measurement: str = "voltage", value: float = 1.5) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="KEITHLEY_2604B_1",
        channel=f"KEITHLEY_2604B_1/smua/{measurement}",
        value=value,
        unit="В",
        status=ChannelStatus.OK,
        metadata={},
    )


# ──────────────────────────────────────────────────────────────────────────────
# §4.5 criterion 1 — snapshot cached before view is opened
# ──────────────────────────────────────────────────────────────────────────────


def test_cooldown_cache_populated_before_view_opened():
    """Dispatching a cooldown reading while the analytics overlay is still
    closed must populate the shell-level cache so it is available for replay
    when the view is first constructed."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    assert w._analytics_view is None
    w._dispatch_reading(_cooldown_reading(t_hours=7.0))

    assert "set_cooldown" in w._analytics_snapshot
    snap_args = w._analytics_snapshot["set_cooldown"]
    assert len(snap_args) == 1
    assert isinstance(snap_args[0], CooldownData)
    assert snap_args[0].t_hours == 7.0


def test_cooldown_replayed_into_view_on_first_open():
    """Opening AnalyticsView after a cooldown reading has been dispatched
    must result in the view's internal cache being populated via replay."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    w._dispatch_reading(_cooldown_reading(t_hours=3.5))
    assert w._analytics_view is None

    w._ensure_overlay("analytics")
    assert w._analytics_view is not None
    assert w._analytics_view._last_cooldown is not None
    assert w._analytics_view._last_cooldown.t_hours == 3.5


def test_phase_replayed_into_view_on_first_open():
    """If a phase has been received before AnalyticsView is opened, the
    phase must be applied during replay so the correct widget layout is shown."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    w._on_experiment_status_received({
        "active_experiment": {"id": "exp_001"},
        "current_phase": "cooldown",
    })
    assert w._analytics_view is None

    w._ensure_overlay("analytics")
    assert w._analytics_view is not None
    assert w._analytics_view.current_phase() == "cooldown"


# ──────────────────────────────────────────────────────────────────────────────
# §4.5 criterion 2 — close and reopen replays from shell cache
# ──────────────────────────────────────────────────────────────────────────────


def test_close_and_reopen_replays_from_shell_cache():
    """Closing the AnalyticsView (nulling the reference) and reopening it
    must replay the shell-level snapshot, not rely on the now-destroyed
    view instance's internal cache."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    # Open view and receive cooldown data while it is open.
    w._ensure_overlay("analytics")
    w._dispatch_reading(_cooldown_reading(t_hours=6.0))
    assert w._analytics_view._last_cooldown.t_hours == 6.0

    # Simulate view close: null the reference (shell cache persists).
    w._analytics_view = None

    # Reopen: factory creates a fresh AnalyticsView; replay must repopulate it.
    w._ensure_overlay("analytics")
    assert w._analytics_view is not None
    assert w._analytics_view._last_cooldown is not None
    assert w._analytics_view._last_cooldown.t_hours == 6.0


def test_shell_cache_not_view_cache_survives_close():
    """The shell cache must still hold data even when _analytics_view is None,
    so that the next open gets the replay."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    w._dispatch_reading(_cooldown_reading(t_hours=2.0))
    # Cache populated before view opens.
    assert "set_cooldown" in w._analytics_snapshot

    # No view constructed; cache is solely in the shell.
    assert w._analytics_view is None
    assert w._analytics_snapshot["set_cooldown"][0].t_hours == 2.0


# ──────────────────────────────────────────────────────────────────────────────
# §4.5 criterion 3 — cache invalidation on experiment boundary
# ──────────────────────────────────────────────────────────────────────────────


def test_new_experiment_clears_cooldown_cache():
    """Starting a new experiment must clear the cooldown snapshot so the
    new experiment's view does not show stale cooldown data."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    w._dispatch_reading(_cooldown_reading(t_hours=4.0))
    assert "set_cooldown" in w._analytics_snapshot

    # New experiment arrives with a different ID.
    w._on_experiment_status_received({
        "active_experiment": {"id": "exp_002"},
        "current_phase": "preparation",
    })
    assert "set_cooldown" not in w._analytics_snapshot


def test_experiment_end_clears_cooldown_cache():
    """Finishing an experiment (no active_experiment) must also clear
    the cooldown cache so a subsequent open shows no stale data."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    # Start experiment + cooldown data.
    w._on_experiment_status_received({
        "active_experiment": {"id": "exp_abc"},
        "current_phase": "cooldown",
    })
    w._dispatch_reading(_cooldown_reading(t_hours=1.5))
    assert "set_cooldown" in w._analytics_snapshot

    # Experiment ends.
    w._on_experiment_status_received({"active_experiment": None})
    assert "set_cooldown" not in w._analytics_snapshot


def test_experiment_id_change_clears_all_scoped_caches():
    """Starting a NEW experiment while a prior one was running must clear
    all experiment-scoped caches (cooldown + accumulating temperature/keithley)
    so that the new experiment's view does not receive stale data from the
    previous run."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    # Establish exp_old and populate all experiment-scoped caches.
    w._on_experiment_status_received({
        "active_experiment": {"id": "exp_old"},
        "current_phase": "cooldown",
    })
    w._dispatch_reading(_cooldown_reading(t_hours=5.0))
    w._analytics_temperature_snapshot["Т1"] = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LS218S_1",
        channel="Т1",
        value=150.0,
        unit="K",
        status=ChannelStatus.OK,
        metadata={},
    )
    w._dispatch_reading(_keithley_reading(measurement="voltage", value=0.9))

    assert "set_cooldown" in w._analytics_snapshot
    assert w._analytics_temperature_snapshot
    assert w._analytics_keithley_snapshot

    # New experiment starts — exp_new replaces exp_old.
    w._on_experiment_status_received({
        "active_experiment": {"id": "exp_new"},
        "current_phase": "preparation",
    })

    assert "set_cooldown" not in w._analytics_snapshot, "cooldown must clear on exp change"
    assert not w._analytics_temperature_snapshot, "temperature snapshot must clear on exp change"
    assert not w._analytics_keithley_snapshot, "keithley snapshot must clear on exp change"


def test_same_experiment_id_does_not_clear_cache():
    """Repeated status pushes from the same experiment must NOT clear
    the cache — only a change in experiment ID triggers invalidation."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    w._on_experiment_status_received({
        "active_experiment": {"id": "exp_keep"},
        "current_phase": "warmup",
    })
    w._dispatch_reading(_cooldown_reading(t_hours=9.0))

    # Same experiment, different phase — cache must survive.
    w._on_experiment_status_received({
        "active_experiment": {"id": "exp_keep"},
        "current_phase": "measurement",
    })
    assert "set_cooldown" in w._analytics_snapshot
    assert w._analytics_snapshot["set_cooldown"][0].t_hours == 9.0


def test_temperature_cache_cleared_on_experiment_change():
    """Accumulating temperature snapshot must be cleared on experiment change
    so mid-experiment temperature history from a past run is not replayed."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    # Manually seed the temperature snapshot (routing added in Cycle 2).
    from cryodaq.gui.shell.views.analytics_view import AnalyticsView  # noqa: F401

    fake_reading = Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LS218S_1",
        channel="Т1",
        value=77.0,
        unit="K",
        status=ChannelStatus.OK,
        metadata={},
    )
    w._analytics_temperature_snapshot["Т1"] = fake_reading
    assert w._analytics_temperature_snapshot

    w._on_experiment_status_received({
        "active_experiment": {"id": "new_exp"},
        "current_phase": "cooldown",
    })
    assert not w._analytics_temperature_snapshot


def test_keithley_cache_cleared_on_experiment_change():
    """Accumulating keithley snapshot must also clear on experiment boundary."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    # Establish an active experiment so the ID transition is tracked.
    w._on_experiment_status_received({
        "active_experiment": {"id": "exp_keithley"},
        "current_phase": "measurement",
    })
    w._analytics_keithley_snapshot["KEITHLEY_2604B_1/smua/voltage"] = _keithley_reading()
    assert w._analytics_keithley_snapshot

    # Experiment ends → keithley snapshot must be cleared.
    w._on_experiment_status_received({"active_experiment": None})
    assert not w._analytics_keithley_snapshot


# ──────────────────────────────────────────────────────────────────────────────
# §4.5 criterion 4 — no history leak (last value only)
# ──────────────────────────────────────────────────────────────────────────────


def test_cooldown_cache_holds_only_last_value():
    """Multiple cooldown readings must not accumulate in the shell cache —
    only the most recent value is kept."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    for t in (8.0, 7.5, 7.0, 6.5):
        w._dispatch_reading(_cooldown_reading(t_hours=t))

    assert len(w._analytics_snapshot) == 1
    assert w._analytics_snapshot["set_cooldown"][0].t_hours == 6.5


def test_pressure_cache_holds_only_last_value():
    """Multiple pressure readings must not accumulate in the shell cache."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    for v in (1e-3, 1e-4, 1e-5):
        w._dispatch_reading(_pressure_reading(value=v))

    assert "set_pressure_reading" in w._analytics_snapshot
    assert w._analytics_snapshot["set_pressure_reading"][0].value == 1e-5


# ──────────────────────────────────────────────────────────────────────────────
# Pressure and keithley routing
# ──────────────────────────────────────────────────────────────────────────────


def test_pressure_reading_cached_and_forwarded_to_open_view():
    """Pressure reading must be cached and forwarded to an already-open view."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    w._ensure_overlay("analytics")
    w._dispatch_reading(_pressure_reading(value=5e-6))

    assert "set_pressure_reading" in w._analytics_snapshot
    assert w._analytics_view._last_pressure_reading is not None
    assert w._analytics_view._last_pressure_reading.value == 5e-6


def test_pressure_replayed_on_view_open():
    """Pressure reading dispatched before view is opened must be replayed
    into the freshly-constructed view."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    w._dispatch_reading(_pressure_reading(value=2e-5))
    assert w._analytics_view is None

    w._ensure_overlay("analytics")
    assert w._analytics_view._last_pressure_reading is not None
    assert w._analytics_view._last_pressure_reading.value == 2e-5


def test_keithley_voltage_cached_when_view_not_open():
    """A smua/voltage reading must be added to the keithley snapshot even
    when the analytics view has not been opened yet."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    r = _keithley_reading(measurement="voltage", value=2.1)
    w._dispatch_reading(r)

    assert w._analytics_view is None
    assert "KEITHLEY_2604B_1/smua/voltage" in w._analytics_keithley_snapshot
    assert w._analytics_keithley_snapshot["KEITHLEY_2604B_1/smua/voltage"].value == 2.1


def test_keithley_snapshot_replayed_on_view_open():
    """Accumulated Keithley readings must be replayed into the analytics view
    when it is first opened."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    for measurement, value in [("voltage", 1.0), ("current", 0.01), ("power", 0.01)]:
        w._dispatch_reading(_keithley_reading(measurement=measurement, value=value))

    w._ensure_overlay("analytics")
    # View's keithley cache must contain all three channel readings.
    assert w._analytics_view._last_keithley_readings
    assert "KEITHLEY_2604B_1/smua/voltage" in w._analytics_view._last_keithley_readings


# ──────────────────────────────────────────────────────────────────────────────
# §4.5 — set_fault is never replayed
# ──────────────────────────────────────────────────────────────────────────────


def test_set_fault_never_added_to_snapshot():
    """The F4 replay cache must never contain set_fault — fault state replay
    would be misleading if the fault has cleared since it was recorded."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    # Simulate all normal dispatch paths.
    w._dispatch_reading(_cooldown_reading())
    w._dispatch_reading(_pressure_reading())
    w._dispatch_reading(_keithley_reading())

    assert "set_fault" not in w._analytics_snapshot


def test_snapshot_replay_skips_missing_setter_gracefully():
    """If a setter name in the cache does not exist on AnalyticsView,
    the replay must not crash."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    # Manually plant a setter name that does not exist on AnalyticsView.
    w._analytics_snapshot["set_nonexistent_setter"] = ({"data": "x"},)

    # Opening the view must not raise even though the setter doesn't exist.
    w._ensure_overlay("analytics")
    assert w._analytics_view is not None


# ──────────────────────────────────────────────────────────────────────────────
# F3-Cycle4 — set_experiment_status routing
# ──────────────────────────────────────────────────────────────────────────────

_EXPERIMENT_STATUS = {
    "active_experiment": {
        "experiment_id": "exp_001",
        "sample": "Si",
        "operator": "Иванов",
        "start_time": "2026-04-15T10:00:00+00:00",
        "end_time": None,
        "artifact_dir": "",
        "status": "RUNNING",
    },
    "current_phase": "cooldown",
    "phases": [],
}


def test_experiment_status_cached_in_analytics_snapshot():
    """_on_experiment_status_received must store status in set_experiment_status
    snapshot entry so the ExperimentSummaryWidget gets it on lazy open."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    w._on_experiment_status_received(_EXPERIMENT_STATUS)

    assert "set_experiment_status" in w._analytics_snapshot
    cached = w._analytics_snapshot["set_experiment_status"][0]
    assert cached["active_experiment"]["experiment_id"] == "exp_001"


def test_experiment_status_forwarded_to_analytics_view_when_open():
    """When AnalyticsView is open, _on_experiment_status_received must
    forward the status to analytics_view.set_experiment_status."""
    _app()
    reset_time_window_controller()
    w = MainWindowV2()
    _stop_timers(w)

    w._ensure_overlay("analytics")
    w._on_experiment_status_received(_EXPERIMENT_STATUS)

    assert w._analytics_view._last_experiment_status is not None
    assert (
        w._analytics_view._last_experiment_status["active_experiment"]["experiment_id"]
        == "exp_001"
    )
