"""Tests for AnalyticsPanel v2 overlay (B.8)."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays._design_system.bento_grid import BentoGrid
from cryodaq.gui.shell.overlays._design_system.modal_card import ModalCard
from cryodaq.gui.shell.overlays.analytics_panel import (
    AnalyticsPanel,
    CooldownData,
    RThermalData,
    _format_eta,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _make_cooldown(**overrides) -> CooldownData:
    defaults = dict(
        t_hours=7.33,
        ci_hours=0.75,
        phase="phase1",
        progress_pct=35.0,
        actual_trajectory=[(0.0, 295.0), (1.0, 250.0), (2.0, 200.0)],
        predicted_trajectory=[(0.0, 295.0), (3.0, 150.0), (7.0, 50.0)],
        ci_trajectory=[
            (0.0, 295.0, 295.0),
            (3.0, 140.0, 160.0),
            (7.0, 45.0, 55.0),
        ],
        phase_boundaries_hours=[3.0],
    )
    defaults.update(overrides)
    return CooldownData(**defaults)


def test_analytics_panel_inherits_modal_card(app):
    # Spec §API + invariant #1: panel inherits ModalCard so that focus
    # trap, focus restoration and Escape-to-close come for free.
    panel = AnalyticsPanel()
    assert isinstance(panel, ModalCard)


def test_analytics_panel_uses_bento_grid_eight_columns(app):
    # AD-001: canonical 8-column grid.
    panel = AnalyticsPanel()
    assert isinstance(panel._grid, BentoGrid)
    assert panel._grid.columns == 8


def test_analytics_panel_no_data_shows_placeholders(app):
    panel = AnalyticsPanel()
    panel.set_cooldown(None)
    panel.set_r_thermal(None)
    assert panel._hero._eta_label.text() == "Охлаждение не активно"
    assert panel._hero._phase_label.text() == "—"
    assert panel._hero._progress.value() == 0
    assert panel._rthermal_tile._value_label.text() == "—"
    assert panel._rthermal_tile._delta_label.text() == "—"


def test_analytics_panel_phase1_renders_labels_and_progress(app):
    panel = AnalyticsPanel()
    panel.set_cooldown(_make_cooldown(phase="phase1", progress_pct=42.5))
    # _format_eta(7.33, 0.75) = "7ч 20мин ±45мин"
    assert panel._hero._eta_label.text() == "7ч 20мин ±45мин"
    assert panel._hero._phase_label.text() == "Фаза 1 (295K→50K)"
    assert panel._hero._progress.value() in (42, 43)


def test_analytics_panel_all_phase_labels(app):
    panel = AnalyticsPanel()
    expected = {
        "phase1": "Фаза 1 (295K→50K)",
        "transition": "Переход (S-bend)",
        "phase2": "Фаза 2 (50K→4K)",
        "stabilizing": "Стабилизация",
        "complete": "Завершено",
    }
    for phase, label in expected.items():
        panel.set_cooldown(_make_cooldown(phase=phase))
        assert panel._hero._phase_label.text() == label, (
            f"phase={phase!r} rendered {panel._hero._phase_label.text()!r}"
        )


def test_analytics_panel_rthermal_renders_three_decimal_precision(app):
    panel = AnalyticsPanel()
    panel.set_r_thermal(
        RThermalData(
            current_value=12.3456,
            delta_per_minute=-0.0321,
            last_updated_ts=time.time(),
            history=[],
        )
    )
    text = panel._rthermal_tile._value_label.text()
    assert "12.346" in text  # RULE-DATA-004: 3 decimals
    assert "K/W" in text
    assert "(устар.)" not in text  # fresh data — no stale marker


def test_analytics_panel_rthermal_stale_shows_suffix_and_status_stale(app):
    panel = AnalyticsPanel()
    panel.set_r_thermal(
        RThermalData(
            current_value=12.3,
            delta_per_minute=0.0,
            last_updated_ts=time.time() - 120,  # 2 min ago > 60s threshold
            history=[],
        )
    )
    text = panel._rthermal_tile._value_label.text()
    ss = panel._rthermal_tile._value_label.styleSheet()
    assert "(устар.)" in text
    assert theme.STATUS_STALE in ss


def test_analytics_panel_rthermal_none_shows_dash(app):
    panel = AnalyticsPanel()
    panel.set_r_thermal(None)
    assert panel._rthermal_tile._value_label.text() == "—"


def test_analytics_panel_cooldown_plot_y_autoscale_disabled(app):
    # Spec invariant: fixed Y range, not autoscale.
    panel = AnalyticsPanel()
    panel.set_cooldown(_make_cooldown())
    vb = panel._cooldown_plot.getViewBox()
    # autoRangeEnabled returns (x_enabled, y_enabled); Y axis must be disabled.
    x_auto, y_auto = vb.autoRangeEnabled()
    assert y_auto is False


def test_analytics_panel_cooldown_plot_uses_plot_bg_background(app):
    # apply_plot_style() must have run — PLOT_BG in effect.
    panel = AnalyticsPanel()
    bg = panel._cooldown_plot.backgroundBrush().color().name()
    assert bg.lower() == theme.PLOT_BG.lower()


def test_analytics_panel_cooldown_actual_trajectory_reaches_curve(app):
    panel = AnalyticsPanel()
    panel.set_cooldown(_make_cooldown())
    # The plot's actual curve should have 3 points from default fixture.
    actual_curve = panel._cooldown_curves["actual"]
    xs, ys = actual_curve.getData()
    assert list(xs) == [0.0, 1.0, 2.0]
    assert list(ys) == [295.0, 250.0, 200.0]


def test_analytics_panel_phase_boundary_lines_rendered(app):
    panel = AnalyticsPanel()
    panel.set_cooldown(_make_cooldown(phase_boundaries_hours=[1.5, 4.0, 6.2]))
    phase_lines = panel._cooldown_curves["phase_lines"]
    assert len(phase_lines) == 3
    # Each line is a pg.InfiniteLine at the supplied hours position.
    positions = sorted(line.value() for line in phase_lines)
    assert positions == [1.5, 4.0, 6.2]


def test_analytics_panel_phase_boundaries_cleared_on_new_data(app):
    # Switching cooldown snapshots must drop the prior phase lines so
    # stale boundaries don't accumulate on the plot.
    panel = AnalyticsPanel()
    panel.set_cooldown(_make_cooldown(phase_boundaries_hours=[1.0, 2.0, 3.0]))
    assert len(panel._cooldown_curves["phase_lines"]) == 3
    panel.set_cooldown(_make_cooldown(phase_boundaries_hours=[5.0]))
    assert len(panel._cooldown_curves["phase_lines"]) == 1
    panel.set_cooldown(None)
    assert panel._cooldown_curves["phase_lines"] == []


def test_analytics_panel_fault_chrome_applies_status_fault(app):
    # Fault chrome adds STATUS_FAULT border on hero + cooldown plot;
    # content itself stays visible (values + plot data unchanged).
    panel = AnalyticsPanel()
    panel.set_cooldown(_make_cooldown())
    panel.set_fault(True, "stale critical channel")
    hero_ss = panel._hero.styleSheet()
    plot_ss = panel._cooldown_plot.styleSheet()
    assert theme.STATUS_FAULT in hero_ss
    assert theme.STATUS_FAULT in plot_ss
    # Content still present — ETA label did not get wiped.
    assert panel._hero._eta_label.text() == "7ч 20мин ±45мин"


def test_analytics_panel_fault_clears_on_reset(app):
    panel = AnalyticsPanel()
    panel.set_fault(True)
    panel.set_fault(False)
    hero_ss = panel._hero.styleSheet()
    plot_ss = panel._cooldown_plot.styleSheet()
    assert theme.STATUS_FAULT not in hero_ss
    # Plot stylesheet fully cleared by set_fault(False).
    assert plot_ss == ""


def test_analytics_panel_progress_clamped_to_range(app):
    panel = AnalyticsPanel()
    panel.set_cooldown(_make_cooldown(progress_pct=-10.0))
    assert panel._hero._progress.value() == 0
    panel.set_cooldown(_make_cooldown(progress_pct=150.0))
    assert panel._hero._progress.value() == 100


def test_analytics_panel_does_not_import_zmq(app):
    # Data flow contract: panel does not subscribe to ZMQ directly.
    # Check module source for zmq imports.
    import cryodaq.gui.shell.overlays.analytics_panel as mod

    src = open(mod.__file__, encoding="utf-8").read()
    assert "import zmq" not in src
    assert "from zmq" not in src
    assert "ZmqBridge" not in src
    assert "ZmqCommandWorker" not in src


def test_format_eta_preserves_legacy_semantics(app):
    # Spec §Hero ETA card: "preserve the existing function" — semantic
    # equivalence with the legacy widgets/analytics_panel.py formatter.
    assert _format_eta(7.33, 0.75) == "7ч 20мин ±45мин"
    assert _format_eta(0.0, 0.0) == "0ч 0мин ±0мин"
    assert _format_eta(1.5, 0.1) == "1ч 30мин ±6мин"


def test_analytics_panel_rthermal_mini_plot_uses_apply_plot_style(app):
    panel = AnalyticsPanel()
    bg = panel._rthermal_mini.backgroundBrush().color().name()
    assert bg.lower() == theme.PLOT_BG.lower()


def test_analytics_panel_rthermal_history_drawn(app):
    panel = AnalyticsPanel()
    now = time.time()
    panel.set_r_thermal(
        RThermalData(
            current_value=12.0,
            delta_per_minute=0.0,
            last_updated_ts=now,
            history=[(now - 300, 11.0), (now - 150, 11.5), (now, 12.0)],
        )
    )
    xs, ys = panel._rthermal_curve.getData()
    # X axis is minutes-ago with 0 = now; three points.
    assert list(ys) == [11.0, 11.5, 12.0]
    assert len(xs) == 3
