"""OC-004 — a dead producer's last analytics value must stop reading as current.

MEASURED, not assumed. `_cached_eta_s`, `_cached_r_thermal` and
`_cached_pressure` were assigned on every matching reading and cleared in
exactly two places: when the experiment ID changes, and when the widget goes
inactive. Neither fires while ONE experiment stays active and its analytics
producer dies -- so the last number kept rendering as current, unmarked, for as
long as the window stayed open.

That is OC-004's stated consequence word for word: "an operator can read a
frozen temperature, pressure or source value after its producer has died."

MARKED, NOT HIDDEN. The stale value stays on screen with a mark rather than
disappearing. A metric that silently vanishes is no better than one that
silently lies -- a vanished readout is what caused revert `0bea0449`.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.core.channel_manager import ChannelManager
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.dashboard import DashboardView
from cryodaq.gui.dashboard import phase_aware_widget as module

STALE_MARK = "устарело"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _set_clock(monkeypatch, now: float) -> None:
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now), raising=False)


def _configured_dashboard(tmp_path, monkeypatch, *, cadence_s: float) -> DashboardView:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "cooldown.yaml").write_text(
        f"cooldown:\n  predict_interval_s: {cadence_s}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CRYODAQ_ROOT", str(tmp_path))
    view = DashboardView(ChannelManager())
    view._phase_widget.on_status_update(
        {
            "active_experiment": {"experiment_id": "exp-1"},
            "current_phase": "cooldown",
            "phase_started_at": 1.0,
            "phases": [],
        }
    )
    return view


def _eta_reading(timestamp: datetime, value: float = 2.0) -> Reading:
    return Reading(
        timestamp=timestamp,
        instrument_id="cooldown_predictor",
        channel="analytics/cooldown_predictor/cooldown_eta",
        value=value,
        unit="h",
    )


def test_a_delayed_source_sample_arrives_already_marked_stale(app, tmp_path, monkeypatch) -> None:
    """A broker/UI backlog must not reset a dead sample's source age."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(_eta_reading(datetime.now(UTC) - timedelta(seconds=181.0)))

    text = view._phase_widget._context_label.text()
    assert "ETA" in text, "the production dashboard route did not render the cooldown ETA"
    assert STALE_MARK in text, (
        "a source-aged cooldown ETA was blessed as fresh when it arrived through the dashboard route"
    )


def test_stale_metric_uses_canonical_chrome_and_shape(app, tmp_path, monkeypatch) -> None:
    """Stale analytics pair legible text with STATUS_STALE shape/color chrome."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(_eta_reading(datetime.now(UTC) - timedelta(seconds=181.0)))

    text = view._phase_widget._context_label.text()
    assert "2ч" in text, "stale chrome hid the retained cooldown ETA"
    assert "◇ устарело" in text, "stale analytics have no static shape/text cue"
    assert f"border:1px solid {theme.STATUS_STALE}" in text, "stale analytics do not use canonical STATUS_STALE chrome"


def test_configured_slow_healthy_predictor_is_not_marked_before_next_publication(app, tmp_path, monkeypatch) -> None:
    """A healthy 180 s producer remains current 181 s after publication."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=180.0)
    view.on_reading(_eta_reading(datetime.now(UTC)))

    _set_clock(monkeypatch, 1181.0)
    view._phase_widget._duration_timer.timeout.emit()

    text = view._phase_widget._context_label.text()
    assert "ETA" in text, "the production dashboard route did not render the cooldown ETA"
    assert STALE_MARK not in text, (
        "a healthy 180 s cooldown predictor was marked stale before its next dashboard publication"
    )


def test_the_mark_is_per_value_not_per_widget(app, tmp_path, monkeypatch) -> None:
    """One dead producer must not make another producer's live value read stale."""

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="thermal_calculator",
            channel="analytics/thermal_calculator/R_thermal",
            value=4.5,
            unit="K/W",
        )
    )

    _set_clock(monkeypatch, 1181.0)
    view.on_reading(_eta_reading(datetime.now(UTC)))

    text = view._phase_widget._context_label.text()
    assert text.count(STALE_MARK) == 1, (
        f"expected exactly the dead feed to be marked, got {text.count(STALE_MARK)} marks in {text!r}"
    )
    assert "ETA" in text and "R" in text, "both metrics must stay visible; marking is not hiding"


def test_a_fresh_analytics_value_is_not_marked(app, tmp_path, monkeypatch) -> None:
    """RESTORED. A registered guard, deleted while unrelated findings were fixed.

    `STALE-ANALYTICS-RENDERED-AS-CURRENT-344` names this node. Without it the
    mark has no negative case at all, so a change that marked EVERYTHING stale
    would satisfy every remaining node — and a mark that fires on healthy data
    teaches an operator to ignore the mark, which is its own harm.
    """

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(_eta_reading(datetime.now(UTC)))

    text = view._phase_widget._context_label.text()
    assert "ETA" in text, "the production dashboard route did not render the cooldown ETA"
    assert STALE_MARK not in text, "a value that has just arrived was rendered stale"


def test_a_value_whose_producer_died_is_marked_while_the_experiment_stays_active(app, tmp_path, monkeypatch) -> None:
    """RESTORED, and this one guards OC-004's actual defect.

    `STALE-ANALYTICS-RENDERED-AS-CURRENT-344` names it. The cached value was
    revoked only when the EXPERIMENT changed, so a producer that died inside a
    live experiment left its last number rendering as current for as long as the
    operator's window stayed open. Deleting this node left the defect this PR
    exists to fix with no guard on its own behaviour.

    Time advances past the horizon while the experiment stays active and no
    further reading arrives — the death path, as distinct from the delayed
    arrival path the sibling node covers.
    """

    _set_clock(monkeypatch, 1000.0)
    view = _configured_dashboard(tmp_path, monkeypatch, cadence_s=30.0)
    view.on_reading(_eta_reading(datetime.now(UTC)))
    assert STALE_MARK not in view._phase_widget._context_label.text(), "premise: it must start unmarked"

    # The producer stops. Nothing changes except the clock, and the experiment
    # is never switched — which is precisely the case the old code missed.
    _set_clock(monkeypatch, 1000.0 + 3.0 * 30.0 + 1.0)
    view._phase_widget._refresh_context_label()

    text = view._phase_widget._context_label.text()
    assert "ETA" in text, "the retained value vanished instead of being marked"
    assert STALE_MARK in text, (
        "a producer died inside a live experiment and its last value is still presented as current: "
        "this is the frozen readout OC-004 names"
    )
