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

    # Test in panel context — assert exact rendered label texts.
    # eta_targets sorted ascending by float(key):
    #   "0.001"  → 0.0     → "✓"        → label "1.0e-03: ✓"
    #   "1e-05"  → 3600.0  → "1ч 0мин"  → label "1.0e-05: 1ч 0мин"
    #   "1e-08"  → None    → "—"        → label "1.0e-08: —"
    _app()
    panel = VacuumTrendPanel()
    panel.set_prediction(
        _make_prediction(
            eta_targets={"0.001": 0.0, "1e-05": 3600.0, "1e-08": None},
        )
    )
    assert len(panel._eta_labels) == 3

    # The panel sorts eta_targets ascending by float(key):
    # float("1e-08") < float("1e-05") < float("0.001")
    # So label order is: 1e-8 → "—", 1e-5 → "1ч 0мин", 0.001 → "✓"
    label_texts = [
        panel._eta_labels[k].text()
        for k in sorted(panel._eta_labels.keys(), key=lambda x: float(x))
    ]
    assert label_texts[0] == "1.0e-08: —", f"got {label_texts[0]!r}"
    assert label_texts[1] == "1.0e-05: 1ч 0мин", f"got {label_texts[1]!r}"
    assert label_texts[2] == "1.0e-03: ✓", f"got {label_texts[2]!r}"


# ---------------------------------------------------------------------------
# 5. test_graph_log_scale — Y-axis is log₁₀(P)
# ---------------------------------------------------------------------------


def test_graph_log_scale() -> None:
    _app()
    extrap_t = [100, 200, 300, 400, 500]
    extrap_logP = [-4.0, -4.5, -5.0, -5.5, -6.0]
    # Use two eta_targets so we get exactly two target lines at known positions.
    eta_targets = {"1e-05": 3600.0, "1e-07": None}
    panel = VacuumTrendPanel()
    panel.set_prediction(
        _make_prediction(
            extrap_t=extrap_t,
            extrap_logP=extrap_logP,
            eta_targets=eta_targets,
        )
    )

    # Verify Y-axis label contains log₁₀
    pi = panel._plot.getPlotItem()
    left_axis = pi.getAxis("left")
    label_text = left_axis.labelText
    assert "log" in label_text.lower() or "₁₀" in label_text

    # Verify extrapolation curve has exact x/y arrays.
    extrap_data = panel._extrap_curve.getData()
    assert extrap_data is not None
    xs, ys = extrap_data
    assert list(xs) == [float(t) for t in extrap_t], f"x mismatch: {list(xs)}"
    assert list(ys) == extrap_logP, f"y mismatch: {list(ys)}"

    # Verify target lines are at exact log₁₀ positions.
    expected_log_positions = sorted(
        math.log10(float(k)) for k in eta_targets.keys()
    )
    actual_positions = sorted(line.value() for line in panel._target_lines)
    assert len(actual_positions) == len(expected_log_positions), (
        f"expected {len(expected_log_positions)} target lines, got {len(actual_positions)}"
    )
    for actual, expected in zip(actual_positions, expected_log_positions):
        assert abs(actual - expected) < 1e-10, (
            f"target line at {actual}, expected {expected}"
        )
