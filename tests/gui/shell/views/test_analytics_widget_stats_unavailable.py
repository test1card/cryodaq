"""ExperimentSummaryWidget channel stats must not print "nan".

``_on_stats_loaded`` aggregated min/max/mean over raw history points. One
non-finite sample poisoned the mean, so the summary card reported e.g.
``T_STAGE: 4.20–4.30 (ср nan)`` — and an all-unavailable channel rendered
``nan–nan (ср nan)`` as if those were measurements.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.views.analytics_widgets import ExperimentSummaryWidget
from cryodaq.gui.state.time_window import reset_time_window_controller

NAN = float("nan")


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def widget(app):
    reset_time_window_controller()
    try:
        yield ExperimentSummaryWidget()
    finally:
        reset_time_window_controller()


def test_non_finite_sample_does_not_poison_channel_stats(widget) -> None:
    widget._on_stats_loaded(
        {
            "ok": True,
            "data": {"T_STAGE": [(1.0, 4.2), (2.0, NAN), (3.0, 4.3)]},
        }
    )

    text = widget._stats_label.text()
    assert "nan" not in text.lower(), f"stats label rendered a non-finite aggregate: {text!r}"
    # The finite samples still produce a real range.
    assert "T_STAGE: 4.20–4.30 (ср 4.25)" == text


def test_all_samples_unavailable_renders_dash(widget) -> None:
    widget._on_stats_loaded(
        {
            "ok": True,
            "data": {"T_SHIELD": [(1.0, NAN), (2.0, NAN)]},
        }
    )

    text = widget._stats_label.text()
    assert "nan" not in text.lower(), f"stats label rendered a non-finite aggregate: {text!r}"
    assert text == "T_SHIELD: —"


def test_finite_channel_unaffected(widget) -> None:
    widget._on_stats_loaded(
        {
            "ok": True,
            "data": {"T_STAGE": [(1.0, 4.0), (2.0, 6.0)]},
        }
    )

    assert widget._stats_label.text() == "T_STAGE: 4.00–6.00 (ср 5.00)"
