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
from dataclasses import dataclass
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.dashboard import phase_aware_widget as module
from cryodaq.gui.dashboard.phase_aware_widget import PhaseAwareWidget

STALE_MARK = "устарело"


STALE_AFTER_S = 180.0


@dataclass
class _AnalyticsReading:
    channel: str
    value: float


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def widget(app) -> PhaseAwareWidget:
    made = PhaseAwareWidget()
    made._has_active_experiment = True
    made._active_experiment_id = "exp-1"
    made._current_phase = "vacuum"
    return made


def _set_clock(monkeypatch, now: float) -> None:
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now), raising=False)
    monkeypatch.setattr(module, "_ANALYTICS_STALE_AFTER_S", STALE_AFTER_S, raising=False)


def test_a_fresh_analytics_value_is_not_marked(widget: PhaseAwareWidget, monkeypatch) -> None:
    """The premise: without this, a node asserting the MARK could pass because
    the value never rendered at all."""

    _set_clock(monkeypatch, 1000.0)
    widget.on_reading(_AnalyticsReading(channel="analytics/pressure", value=1.2e-5))
    text = widget._context_label.text()
    assert "mbar" in text, "the pressure metric never rendered, so this node measures nothing"
    assert STALE_MARK not in text, "a value that just arrived was marked stale"


def test_a_value_whose_producer_died_is_marked_while_the_experiment_stays_active(
    widget: PhaseAwareWidget, monkeypatch
) -> None:
    """The defect. The experiment does NOT change and the widget does NOT go
    inactive -- the only two paths that previously revoked anything."""

    _set_clock(monkeypatch, 1000.0)
    widget.on_reading(_AnalyticsReading(channel="analytics/pressure", value=1.2e-5))

    # The producer stops. Nothing else about the experiment changes.
    _set_clock(monkeypatch, 1000.0 + STALE_AFTER_S + 1.0)
    widget._duration_timer.timeout.emit()

    text = widget._context_label.text()
    assert "mbar" in text, (
        "the stale pressure vanished from the label instead of being marked; a readout that disappears "
        "is the `0bea0449` failure, not a fix for it"
    )
    assert STALE_MARK in text, (
        "a pressure whose producer died is still presented as current: this is the frozen readout OC-004 names"
    )


def test_the_mark_is_per_value_not_per_widget(widget: PhaseAwareWidget, monkeypatch) -> None:
    """One dead producer must not condemn a live one.

    Marking the whole label would make a working R_thermal read as stale
    because the pressure feed died, which trades one wrong impression for
    another.
    """

    widget._current_phase = "cooldown"
    _set_clock(monkeypatch, 1000.0)
    widget.on_reading(_AnalyticsReading(channel="analytics/R_thermal", value=4.5))

    later = 1000.0 + STALE_AFTER_S + 1.0
    _set_clock(monkeypatch, later)
    widget.on_reading(_AnalyticsReading(channel="analytics/cooldown_eta", value=2.0))
    text = widget._context_label.text()
    assert text.count(STALE_MARK) == 1, (
        f"expected exactly the dead feed to be marked, got {text.count(STALE_MARK)} marks in {text!r}"
    )
    assert "ETA" in text and "R" in text, "both metrics must still be present; marking is not hiding"
