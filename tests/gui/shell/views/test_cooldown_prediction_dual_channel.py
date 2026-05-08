"""v0.56.1 (REG-2) — CooldownPredictionWidget dual-channel asymptote.

Architect 2026-05-08: the cooldown / measurement phases share the same
prediction widget. The widget tracks both Т12 (cold stage) and Т11
(warm stage) in parallel, rendering a separate asymptote line + ±sigma
band + steady badge per channel. Settle threshold is per-channel — Т11
typically settles before Т12 because it is a warmer stage.

This module covers the live-data feed contract:
1. set_warm_temperature_reading exists and accepts Reading objects
2. Both predictors accept points independently (dual buffers)
3. The widget exposes per-channel overlay state (asym_line / band /
   steady badge) for both Т12 and Т11
4. set_cooldown_data routes None / settled / trajectory cases without
   crashing on the dual-channel state
"""

from __future__ import annotations

import datetime as dt

import pytest

PySide6 = pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.gui.shell.views.analytics_widgets import CooldownPredictionWidget


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _reading(value: float, ts: float = 100.0) -> Reading:
    return Reading(
        instrument_id="lakeshore",
        channel="Т12 cold",
        value=value,
        unit="K",
        timestamp=dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc),
        status=ChannelStatus.OK,
    )


def test_widget_exposes_dual_channel_overlay_state(app):
    """Both Т12 (existing) and Т11 (v0.56.1) overlay attributes exist."""
    w = CooldownPredictionWidget()
    # Т12 (cold) — preserved from v0.54.0
    assert hasattr(w, "_asym_line")
    assert hasattr(w, "_asym_band")
    assert hasattr(w, "_steady_badge")
    # Т11 (warm) — new in v0.56.1
    assert hasattr(w, "_asym_line_t11")
    assert hasattr(w, "_asym_band_t11")
    assert hasattr(w, "_steady_badge_t11")
    # Both predictors live; state is independent.
    assert w._ss_predictor is not w._ss_predictor_t11


def test_set_warm_temperature_reading_appends_to_warm_buffer(app):
    """Т11 readings populate the warm buffer без touching the cold buffer."""
    w = CooldownPredictionWidget()
    r = _reading(value=50.0, ts=100.0)
    w.set_warm_temperature_reading(r)
    assert len(w._raw_warm_buffer) == 1
    assert w._raw_warm_buffer[0] == (100.0, 50.0)
    assert w._raw_cold_buffer == []
    assert w._last_ts_seen_t11 == 100.0


def test_set_cold_and_warm_buffers_are_independent(app):
    """Cold and warm setters don't cross-contaminate."""
    w = CooldownPredictionWidget()
    w.set_cold_temperature_reading(_reading(value=4.2, ts=100.0))
    w.set_warm_temperature_reading(_reading(value=80.0, ts=100.0))
    assert len(w._raw_cold_buffer) == 1
    assert len(w._raw_warm_buffer) == 1
    assert w._raw_cold_buffer[0] == (100.0, 4.2)
    assert w._raw_warm_buffer[0] == (100.0, 80.0)


def test_set_warm_none_is_no_op(app):
    """set_warm_temperature_reading(None) is safe — does not raise."""
    w = CooldownPredictionWidget()
    w.set_warm_temperature_reading(None)
    assert w._raw_warm_buffer == []
    assert w._last_ts_seen_t11 == 0.0


def test_set_cooldown_data_none_hides_both_channel_overlays(app):
    """data=None hides Т12 and Т11 overlays simultaneously."""
    w = CooldownPredictionWidget()
    # Force both channels' overlays visible (manually) to verify hide logic.
    w._asym_line.setVisible(True)
    w._asym_band.setVisible(True)
    w._steady_badge.setVisible(True)
    w._asym_line_t11.setVisible(True)
    w._asym_band_t11.setVisible(True)
    w._steady_badge_t11.setVisible(True)
    w.set_cooldown_data(None)
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert not w._steady_badge.isVisible()
    assert not w._asym_line_t11.isVisible()
    assert not w._asym_band_t11.isVisible()
    assert not w._steady_badge_t11.isVisible()
    assert w._placeholder.isVisible()


def test_active_trajectory_hides_both_channel_overlays(app):
    """When CooldownService is active с predicted trajectory, both
    channels' asymptote overlays are hidden so the forecast curve owns
    the visual focus."""
    w = CooldownPredictionWidget()

    class _Data:
        predicted_trajectory = [(0.0, 295.0), (3600.0, 100.0)]
        ci_trajectory = [(0.0, 293.0, 297.0), (3600.0, 95.0, 105.0)]

    # Force overlays visible to verify the active-trajectory hide path.
    w._asym_line_t11.setVisible(True)
    w._asym_band_t11.setVisible(True)
    w._steady_badge_t11.setVisible(True)
    w.set_cooldown_data(_Data())
    assert not w._asym_line.isVisible()
    assert not w._asym_band.isVisible()
    assert not w._steady_badge.isVisible()
    assert not w._asym_line_t11.isVisible()
    assert not w._asym_band_t11.isVisible()
    assert not w._steady_badge_t11.isVisible()
    assert not w._placeholder.isVisible()


def test_apply_channel_overlays_returns_false_for_unsettled(app):
    """No predictor data → helper returns False, all overlays hidden."""
    w = CooldownPredictionWidget()
    rendered = w._apply_channel_overlays(
        w._ss_predictor_t11,
        w._PRED_WARM,
        w._WARM_LANDMARK,
        w._asym_line_t11,
        w._asym_band_t11,
        w._steady_badge_t11,
    )
    assert rendered is False
    assert not w._asym_line_t11.isVisible()
    assert not w._asym_band_t11.isVisible()
    assert not w._steady_badge_t11.isVisible()
