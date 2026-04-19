"""Phase III.B — shared PredictionWidget tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.widgets.shared.prediction_widget import (
    _HORIZON_OPTIONS_HOURS,
    PredictionWidget,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _history(n: int = 5, step: float = 60.0) -> list[tuple[float, float]]:
    return [(i * step, 100.0 - i * 2.0) for i in range(n)]


def _forecast(start_t: float, horizon_s: float, step: float = 600.0) -> dict:
    steps = int(horizon_s / step) + 1
    central = [(start_t + i * step, 50.0 + i * 0.1) for i in range(steps)]
    lower = [(t, v - 1.0) for t, v in central]
    upper = [(t, v + 1.0) for t, v in central]
    return {"central": central, "lower": lower, "upper": upper}


def test_widget_constructs_linear_y(app):
    w = PredictionWidget("Cooldown", "Температура", "K", log_y=False)
    assert w._horizon_hours == 24.0


def test_widget_constructs_log_y(app):
    w = PredictionWidget("Vacuum", "Давление", "мбар", log_y=True)
    assert w._log_y is True


def test_horizon_selector_has_six_buttons(app):
    w = PredictionWidget("Cooldown", "T", "K")
    assert set(w._horizon_buttons.keys()) == set(_HORIZON_OPTIONS_HOURS)


def test_set_history_populates_curve(app):
    w = PredictionWidget("Cooldown", "T", "K")
    w.set_history(_history(5))
    xs, ys = w._history_curve.getData()
    assert len(xs) == 5


def test_set_prediction_populates_all_three_curves(app):
    w = PredictionWidget("Cooldown", "T", "K")
    w.set_history(_history(5))
    f = _forecast(start_t=240.0, horizon_s=24 * 3600.0)
    w.set_prediction(f["central"], f["lower"], f["upper"], ci_level_pct=67.0)
    cx, _ = w._central_curve.getData()
    lx, _ = w._lower_curve.getData()
    ux, _ = w._upper_curve.getData()
    assert len(cx) > 0
    assert len(lx) == len(cx)
    assert len(ux) == len(cx)


def test_horizon_change_emits_signal(app):
    w = PredictionWidget("Cooldown", "T", "K")
    seen: list[float] = []
    w.horizon_changed.connect(seen.append)
    w.set_horizon(12.0)
    assert seen == [12.0]
    assert w.get_horizon() == 12.0


def test_horizon_change_same_value_is_noop(app):
    w = PredictionWidget("Cooldown", "T", "K")
    seen: list[float] = []
    w.horizon_changed.connect(seen.append)
    w.set_horizon(24.0)  # default
    assert seen == []


def test_horizon_change_updates_readout_caption(app):
    w = PredictionWidget("Cooldown", "T", "K")
    w.set_horizon(3.0)
    assert "3" in w._horizon_caption_label.text()
    assert "ч" in w._horizon_caption_label.text()


def test_readout_value_reflects_central_at_horizon(app):
    w = PredictionWidget("Cooldown", "T", "K")
    now = 1000.0
    w.set_history([(now, 77.0)])
    # Forecast: linear from (now, 50) to (now + 24h, 60).
    central = [(now, 50.0), (now + 24 * 3600.0, 60.0)]
    lower = [(now, 48.0), (now + 24 * 3600.0, 58.0)]
    upper = [(now, 52.0), (now + 24 * 3600.0, 62.0)]
    w.set_prediction(central, lower, upper, ci_level_pct=67.0)
    w.set_horizon(24.0)
    text = w._predicted_value_label.text()
    assert "60" in text and "K" in text


def test_ci_band_brush_uses_status_info_not_status_ok(app):
    w = PredictionWidget("Cooldown", "T", "K")
    # FillBetweenItem brush: pull the color back out.
    brush = w._ci_band.brush()
    color = brush.color()
    status_info = theme.STATUS_INFO.lstrip("#")
    hex_from_color = color.name().lstrip("#")
    assert hex_from_color.lower() == status_info.lower()
    # Alpha ≈ 64 (semi-transparent); definitely not opaque.
    assert 0 < color.alpha() < 255


def test_log_y_readout_uses_scientific_notation(app):
    w = PredictionWidget("Vacuum", "P", "мбар", log_y=True)
    now = 1000.0
    w.set_history([(now, 1e-5)])
    horizon_s = 24.0 * 3600.0
    central = [(now, 1e-5), (now + horizon_s, 3.8e-6)]
    lower = [(now, 0.5e-5), (now + horizon_s, 1e-6)]
    upper = [(now, 2e-5), (now + horizon_s, 6.5e-6)]
    w.set_prediction(central, lower, upper, ci_level_pct=95.0)
    w.set_horizon(24.0)
    text = w._predicted_value_label.text()
    assert "e" in text  # scientific notation
    assert "мбар" in text


def test_does_not_import_global_window_controller():
    """Prediction widget is forward-looking; must NOT subscribe."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "cryodaq"
        / "gui"
        / "widgets"
        / "shared"
        / "prediction_widget.py"
    )
    text = src.read_text(encoding="utf-8")
    assert "get_time_window_controller" not in text
    assert "window_changed" not in text
