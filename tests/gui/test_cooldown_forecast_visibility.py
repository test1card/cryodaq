"""The two real displays must not present a stale or baseline ETA as live.

`ef839371` gave `CooldownData` its provenance — `cooldown_active` and
`generated_at` — and taught the object to describe itself. It did not teach the
two widgets that actually draw to the operator to *read* that provenance, so
both could still show a confident current forecast when there was none:

* `CooldownPredictionWidget.set_cooldown_data` branched only on whether a
  trajectory was non-empty. A pre-detection ensemble prior and a ten-minute-old
  prediction drew the same ordinary forecast curve as a live one;
* `PhaseAwareWidget` judged freshness only inside `_refresh_context_label`,
  which runs on reading arrival. In the failure it exists to catch — the
  publisher stops — no reading arrives, so nothing re-evaluated the age and the
  last "fresh" ETA stayed on screen indefinitely;
* `_cooldown_reading_to_data` anchored the trajectory to `time.time()`, sliding
  a delayed forecast forward to receipt time so the curve claimed to describe a
  future measured from now while its own text was classified stale.

These tests drive the production widgets and the production timer slot, not the
data object. The pre-existing provenance tests
(`tests/gui/test_cooldown_eta_provenance.py`) cover `CooldownData` itself; the
pre-existing widget tests build their input with `MagicMock`, whose attributes
are all truthy, so they could never have caught any of this.

Raw acquisition, predictor mathematics, storage, alarms and the report schema
are untouched here.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from cryodaq.core.reading_freshness import PREDICTION_STALE_AFTER_S  # noqa: E402
from cryodaq.drivers.base import ChannelStatus, Reading  # noqa: E402
from cryodaq.gui.shell.views.analytics_view import CooldownData  # noqa: E402
from cryodaq.gui.shell.views.analytics_widgets import CooldownPredictionWidget  # noqa: E402

_CHANNEL = "analytics/cooldown_predictor/cooldown_eta"


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _traj(anchor: float) -> tuple[list, list]:
    predicted = [(anchor + 3600.0, 40.0), (anchor + 7200.0, 30.0)]
    ci = [(anchor + 3600.0, 38.0, 42.0), (anchor + 7200.0, 28.0, 32.0)]
    return predicted, ci


def _data(*, active: bool, age_s: float, anchor: float | None = None) -> CooldownData:
    import time as _time

    generated_at = _time.time() - age_s
    predicted, ci = _traj(anchor if anchor is not None else generated_at)
    return CooldownData(
        t_hours=13.3,
        ci_hours=1.0,
        phase="phase1",
        progress_pct=70.8,
        predicted_trajectory=predicted,
        ci_trajectory=ci,
        cooldown_active=active,
        generated_at=generated_at,
    )


# ==========================================================================
# 1. the main cooldown graph
# ==========================================================================
def test_a_fresh_active_forecast_draws_an_unqualified_curve(app) -> None:
    """The one case that really is a live forecast for this run."""

    w = CooldownPredictionWidget()
    w.set_cooldown_data(_data(active=True, age_s=5.0))

    assert w._inner._central, "a live forecast must actually be drawn"
    assert not w._placeholder.isVisible()
    assert not w._steady_badge.isVisible(), "a live forecast needs no qualifier"


def test_a_fresh_baseline_is_drawn_but_named(app) -> None:
    """Before detection the predictor emits the ensemble prior.

    That curve is a model reference, not a forecast for this run. It is worth
    showing — hiding it is its own kind of lie — but it must not be shown as an
    ordinary forecast, which is exactly what it used to be.
    """

    w = CooldownPredictionWidget()
    w.set_cooldown_data(_data(active=False, age_s=5.0))

    assert w._inner._central, "the prior is still worth drawing"
    assert w._steady_badge.isVisible(), "but it must carry its qualifier"
    assert "базовая оценка" in w._steady_badge.toPlainText()
    assert not w._placeholder.isVisible()


def test_a_stalled_predictor_does_not_leave_its_curve_on_the_plot(app) -> None:
    """The regression the reviewer named: stale must CLEAR, not merely relabel.

    Drives a real live forecast in first, so the assertion is that an existing
    drawn curve is removed — not merely that nothing was ever drawn.
    """

    w = CooldownPredictionWidget()
    w.set_cooldown_data(_data(active=True, age_s=5.0))
    assert w._inner._central, "precondition: a live curve is on the plot"

    w.set_cooldown_data(_data(active=True, age_s=600.0))

    assert not w._inner._central, "a stalled forecast must not stay drawn"
    assert w._placeholder.isVisible()
    text = w._placeholder.toPlainText()
    assert "недоступен" in text
    assert "10 мин" in text, "the age must travel with the refusal"
    assert not w._steady_badge.isVisible()


def test_a_prediction_that_cannot_date_itself_is_refused(app) -> None:
    """Fails closed: an unknown generation time cannot establish currency."""

    w = CooldownPredictionWidget()
    predicted, ci = _traj(1_780_000_000.0)
    w.set_cooldown_data(
        CooldownData(
            t_hours=13.3,
            ci_hours=1.0,
            phase="phase1",
            progress_pct=70.8,
            predicted_trajectory=predicted,
            ci_trajectory=ci,
            cooldown_active=True,
            generated_at=None,
        )
    )

    assert not w._inner._central
    assert w._placeholder.isVisible()


def test_recovery_after_a_stall_clears_the_refusal_text(app) -> None:
    """A stale refusal must not become permanent furniture on the plot."""

    w = CooldownPredictionWidget()
    w.set_cooldown_data(_data(active=True, age_s=600.0))
    assert "10 мин" in w._placeholder.toPlainText()

    w.set_cooldown_data(_data(active=True, age_s=5.0))

    assert w._inner._central
    assert not w._placeholder.isVisible()
    # Back to the plain idle text — the age-stamped refusal is gone. (The idle
    # message happens to contain "недоступен" too, so the age is what to check.)
    assert w._placeholder.toPlainText() == w._IDLE_MESSAGE
    assert "10 мин" not in w._placeholder.toPlainText()


# --------------------------------------------------------------------------
# 1b. the graph must age during SILENCE, not only on delivery
# --------------------------------------------------------------------------
def test_the_graph_expires_a_drawn_forecast_when_the_publisher_stops(app, monkeypatch) -> None:
    """The real failure sequence, which rejection-on-delivery does not cover.

    Draw a fresh active forecast, let the predictor stop, let the boundary pass,
    deliver NOTHING, and drive the production timer slot. Judging provenance
    only inside `set_cooldown_data` meant silence — the one thing that actually
    happens when a publisher dies — could never trigger the check, so the curve
    stayed on the plot indefinitely.
    """

    import time as _time

    w = CooldownPredictionWidget()
    w.set_cooldown_data(_data(active=True, age_s=5.0))

    assert w._inner._central, "precondition: a live curve is drawn"
    assert w._inner._lower_ci and w._inner._upper_ci, "precondition: a CI band is drawn"
    assert not w._placeholder.isVisible()

    real_now = _time.time()
    monkeypatch.setattr(_time, "time", lambda: real_now + PREDICTION_STALE_AFTER_S + 30.0)

    w._on_freshness_tick()  # the production timer slot; no second delivery

    assert not w._inner._central, "the central forecast must be cleared"
    assert not w._inner._lower_ci and not w._inner._upper_ci, "and the CI band with it"
    assert w._placeholder.isVisible()
    assert "недоступен" in w._placeholder.toPlainText()


def test_the_graph_freshness_timer_is_one_parented_timer(app) -> None:
    """Guards the shape the reviewer asked for, not just the behaviour.

    A slot nothing invokes would satisfy the test above and change nothing on
    screen; a timer created per refresh would leak one per delivery.
    """

    from PySide6.QtCore import QTimer

    w = CooldownPredictionWidget()
    assert w._freshness_timer.parent() is w, "Qt parent teardown must own it"
    assert w._freshness_timer.isActive()
    assert w._freshness_timer.interval() == w._FRESHNESS_TICK_MS

    before = w.findChildren(QTimer)
    for _ in range(5):
        w.set_cooldown_data(_data(active=True, age_s=1.0))
    assert len(w.findChildren(QTimer)) == len(before), "no per-refresh timers"

    calls: list[str] = []
    w._refuse_cooldown = lambda provenance: calls.append(provenance)  # type: ignore[method-assign]
    w.set_cooldown_data(_data(active=True, age_s=600.0))
    assert len(calls) == 1, "the timer must be connected exactly once"


def test_a_still_fresh_forecast_is_left_alone_by_the_tick(app) -> None:
    """The tick must not disturb a forecast that is still current."""

    w = CooldownPredictionWidget()
    w.set_cooldown_data(_data(active=True, age_s=5.0))
    drawn = list(w._inner._central)

    for _ in range(3):
        w._on_freshness_tick()

    assert list(w._inner._central) == drawn
    assert not w._placeholder.isVisible()


def test_expiry_latches_and_then_releases_on_a_new_forecast(app, monkeypatch) -> None:
    """Refusal is applied once, and a recovered publisher is drawn again."""

    import time as _time

    w = CooldownPredictionWidget()
    w.set_cooldown_data(_data(active=True, age_s=5.0))

    real_now = _time.time()
    monkeypatch.setattr(_time, "time", lambda: real_now + PREDICTION_STALE_AFTER_S + 30.0)
    w._on_freshness_tick()
    assert w._cooldown_expired is True

    calls: list[str] = []
    w._refuse_cooldown = lambda provenance: calls.append(provenance)  # type: ignore[method-assign]
    for _ in range(4):
        w._on_freshness_tick()
    assert calls == [], "an expired snapshot must not be re-refused every second"

    monkeypatch.undo()
    w.set_cooldown_data(_data(active=True, age_s=5.0))
    assert w._cooldown_expired is False, "a new forecast clears the latch"
    assert w._inner._central, "and is drawn again"


# ==========================================================================
# 2. the compact dashboard — the timer path, with no reading arriving
# ==========================================================================
def _cooldown_dashboard():
    from cryodaq.gui.dashboard.phase_aware_widget import PhaseAwareWidget

    w = PhaseAwareWidget()
    w.on_status_update(
        {
            "active_experiment": {"experiment_id": "exp-visibility"},
            "current_phase": "cooldown",
            "phase_started_at": datetime.now(UTC).timestamp() - 3600.0,
            "phases": [],
        }
    )
    return w


def _eta_reading(*, hours: float, active: bool, age_s: float = 0.0) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC) - timedelta(seconds=age_s),
        instrument_id="cooldown_predictor",
        channel=_CHANNEL,
        value=hours,
        unit="h",
        status=ChannelStatus.OK,
        metadata={"cooldown_active": active, "progress": 0.65, "phase": "phase1"},
    )


def test_the_dashboard_goes_stale_on_its_own_timer_with_no_new_reading(app, monkeypatch) -> None:
    """The reviewer's required test.

    Inject a fresh ETA, advance the clock past the boundary WITHOUT sending
    another reading, drive the normal one-second timer slot, and prove the
    visible label changes. Previously nothing re-evaluated the age unless a
    reading arrived — so in the exact failure this guards (the publisher stops)
    the label never changed at all.
    """

    from cryodaq.gui.dashboard import phase_aware_widget as paw

    w = _cooldown_dashboard()
    w.on_reading(_eta_reading(hours=13.3, active=True))

    before = w._context_label.text()
    assert "нет обновления" not in before, "precondition: the ETA starts fresh"
    assert "13" in before, "precondition: the ETA is actually shown"

    class _Clock:
        """Only the widget's view of now moves; no reading is sent."""

        @staticmethod
        def time() -> float:
            import time as _t

            return _t.time() + PREDICTION_STALE_AFTER_S + 30.0

    monkeypatch.setattr(paw, "time", _Clock)

    w._on_duration_tick()  # the production timer slot, not a private helper

    after = w._context_label.text()
    assert "нет обновления" in after, "a stopped publisher must become visible"


def test_the_timer_slot_is_what_the_timer_is_actually_connected_to(app) -> None:
    """Guards the wiring itself.

    The fix is only real if the existing one-second timer calls the slot that
    refreshes the label. A slot that nothing invokes would pass every assertion
    above and change nothing on screen.
    """

    w = _cooldown_dashboard()
    assert w._duration_timer.isActive()

    calls: list[str] = []
    w._refresh_context_label = lambda: calls.append("label")  # type: ignore[method-assign]
    w._duration_timer.timeout.emit()

    assert calls == ["label"], "the 1 s timer must refresh the context label"


def test_a_fresh_dashboard_baseline_is_still_marked_by_model(app) -> None:
    """The timer must not flatten the baseline distinction into staleness."""

    w = _cooldown_dashboard()
    w.on_reading(_eta_reading(hours=19.3, active=False))
    w._on_duration_tick()

    text = w._context_label.text()
    assert "по модели" in text
    assert "нет обновления" not in text


# ==========================================================================
# 3. delayed predictions are plotted at source time
# ==========================================================================
def _adapt(reading: Reading):
    from cryodaq.gui.shell.main_window_v2 import MainWindowV2

    return MainWindowV2._cooldown_reading_to_data(reading)


def _trajectory_reading(*, age_s: float, with_timestamp: bool = True) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC) - timedelta(seconds=age_s),
        instrument_id="cooldown_predictor",
        channel=_CHANNEL,
        value=13.3,
        unit="h",
        status=ChannelStatus.OK,
        metadata={
            "t_remaining_hours": 13.3,
            "t_remaining_ci68": (12.3, 14.3),
            "progress": 0.7,
            "phase": "phase1",
            "cooldown_active": True,
            "future_t": [0.0, 1.0, 2.0],
            "future_T_cold_mean": [54.0, 44.0, 36.0],
            "future_T_cold_upper": [56.0, 46.0, 38.0],
            "future_T_cold_lower": [52.0, 42.0, 34.0],
        },
    )


def test_a_delayed_forecast_is_plotted_where_it_was_made(app) -> None:
    """`future_t` is hours from prediction time, not from receipt time.

    A ten-minute-old forecast anchored to `time.time()` is drawn ten minutes to
    the right of where it belongs — so the curve asserts a future measured from
    now while `status_label()` on the same object calls it stale.
    """

    reading = _trajectory_reading(age_s=600.0)
    data = _adapt(reading)
    assert data is not None

    source_ts = reading.timestamp.timestamp()
    first_t = data.predicted_trajectory[0][0]

    assert first_t == pytest.approx(source_ts, abs=1.0), "anchored to prediction time"
    assert data.generated_at == pytest.approx(source_ts, abs=1.0)
    assert data.predicted_trajectory[1][0] == pytest.approx(source_ts + 3600.0, abs=1.0)
    assert data.ci_trajectory[0][0] == pytest.approx(source_ts, abs=1.0)
    assert data.freshness().is_current is False, "and still classified stale"


def test_the_plot_and_the_label_agree_about_one_prediction(app) -> None:
    """The two must not describe the same object differently.

    This is the defect stated end-to-end: a stale prediction whose curve was
    drawn at receipt time looked current on the plot while its text said
    otherwise. Drives the adapter and the real widget together.
    """

    w = CooldownPredictionWidget()
    data = _adapt(_trajectory_reading(age_s=600.0))
    assert data is not None

    w.set_cooldown_data(data)

    assert not w._inner._central, "stale on the plot"
    assert "недоступен" in w._placeholder.toPlainText(), "and stale in the text"


def test_an_undatable_forecast_draws_no_trajectory_at_all(app) -> None:
    """Fail closed rather than manufacture an anchor from the wall clock."""

    class _NoTimestamp:
        channel = _CHANNEL
        value = 13.3
        timestamp = None
        metadata = {
            "t_remaining_hours": 13.3,
            "progress": 0.7,
            "phase": "phase1",
            "cooldown_active": True,
            "future_t": [0.0, 1.0],
            "future_T_cold_mean": [54.0, 44.0],
            "future_T_cold_upper": [56.0, 46.0],
            "future_T_cold_lower": [52.0, 42.0],
        }

    data = _adapt(_NoTimestamp())
    assert data is not None
    assert data.generated_at is None
    assert data.predicted_trajectory == [], "no anchor, no curve"
    assert data.ci_trajectory == []


def test_the_boundary_has_exactly_one_owner() -> None:
    """P2: the two displays cannot drift apart.

    120 s is FOUR 30 s publish cycles, not three.
    """

    from cryodaq.gui.dashboard import phase_aware_widget as paw
    from cryodaq.gui.shell.views import analytics_view as av

    assert PREDICTION_STALE_AFTER_S == 120.0
    assert av._PREDICTION_STALE_AFTER_S is PREDICTION_STALE_AFTER_S
    assert paw._ETA_STALE_AFTER_S is PREDICTION_STALE_AFTER_S
