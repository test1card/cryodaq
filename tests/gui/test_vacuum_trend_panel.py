"""GUI tests for VacuumTrendPanel — 5 tests per spec."""

from __future__ import annotations

import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui.widgets.vacuum_trend_panel import (
    _COLOR_GREEN,
    _COLOR_RED,
    _COLOR_YELLOW,
    VacuumTrendPanel,
    _fmt_eta,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _make_prediction(
    model_type: str = "exponential",
    trend: str = "pumping_down",
    confidence: float = 0.95,
    p_ult: float = 1e-7,
    eta_targets: dict | None = None,
    extrap_t: list | None = None,
    extrap_logP: list | None = None,
) -> dict:
    return {
        "model_type": model_type,
        "p_ultimate_mbar": p_ult,
        "eta_targets": eta_targets or {"1e-05": 3600.0, "1e-06": 7200.0},
        "trend": trend,
        "confidence": confidence,
        "residual_std": 0.05,
        "fit_params": {"log_p_ult": math.log10(p_ult), "A": 5.0, "tau": 300.0},
        "extrapolation_t": extrap_t or [1000, 2000, 3000, 4000, 5000],
        "extrapolation_logP": extrap_logP or [-5.0, -5.5, -6.0, -6.3, -6.5],
    }


# ---------------------------------------------------------------------------
# 1. test_panel_creates — widget creates without crash
# ---------------------------------------------------------------------------


def test_panel_creates() -> None:
    _app()
    panel = VacuumTrendPanel()
    assert panel is not None
    assert panel._plot is not None
    assert panel._empty_visible


# ---------------------------------------------------------------------------
# 2. test_empty_state_shown — None prediction shows empty state
# ---------------------------------------------------------------------------


def test_empty_state_shown() -> None:
    _app()
    panel = VacuumTrendPanel()
    panel.clear()
    assert panel._empty_visible
    assert panel.trend_text == "Нет данных"


# ---------------------------------------------------------------------------
# 3. test_trend_icon_colors — pumping_down=green, rising=red, etc
# ---------------------------------------------------------------------------


def test_trend_icon_colors() -> None:
    _app()
    panel = VacuumTrendPanel()

    panel.set_prediction(_make_prediction(trend="pumping_down"))
    assert panel.trend_color == _COLOR_GREEN
    assert panel.trend_text == "Откачка"

    panel.set_prediction(_make_prediction(trend="stable"))
    assert panel.trend_color == _COLOR_YELLOW
    assert panel.trend_text == "Стабильно"

    panel.set_prediction(_make_prediction(trend="rising"))
    assert panel.trend_color == _COLOR_RED
    assert panel.trend_text == "Рост!"

    panel.set_prediction(_make_prediction(trend="anomaly"))
    assert panel.trend_color == _COLOR_RED
    assert panel.trend_text == "Аномалия"


# ---------------------------------------------------------------------------
# 4. test_eta_display_format — "2ч 15мин", "—", "✓"
# ---------------------------------------------------------------------------


def test_eta_display_format() -> None:
    # Test the formatting function directly
    assert _fmt_eta(None) == "—"
    assert _fmt_eta(0.0) == "✓"
    assert _fmt_eta(30.0) == "30с"
    assert _fmt_eta(600.0) == "10мин"
    assert _fmt_eta(8100.0) == "2ч 15мин"

    # Test in panel context
    _app()
    panel = VacuumTrendPanel()
    panel.set_prediction(
        _make_prediction(
            eta_targets={"0.001": 0.0, "1e-05": 3600.0, "1e-08": None},
        )
    )
    # Check labels were created
    assert len(panel._eta_labels) == 3


# ---------------------------------------------------------------------------
# 5. test_graph_log_scale — Y-axis is log₁₀(P)
# ---------------------------------------------------------------------------


def test_graph_log_scale() -> None:
    _app()
    panel = VacuumTrendPanel()
    panel.set_prediction(
        _make_prediction(
            extrap_t=[100, 200, 300, 400, 500],
            extrap_logP=[-4.0, -4.5, -5.0, -5.5, -6.0],
        )
    )

    # Verify Y-axis label contains log₁₀
    pi = panel._plot.getPlotItem()
    left_axis = pi.getAxis("left")
    label_text = left_axis.labelText
    assert "log" in label_text.lower() or "₁₀" in label_text

    # Verify extrapolation data is in log scale (values between -10 and 5)
    extrap_data = panel._extrap_curve.getData()
    assert extrap_data is not None
    ys = extrap_data[1]
    assert len(ys) == 5
    assert all(-10 < y < 5 for y in ys)

    # Verify target lines are at log₁₀ positions
    for line in panel._target_lines:
        pos = line.value()
        assert -10 < pos < 0  # log₁₀(mbar) targets are negative
