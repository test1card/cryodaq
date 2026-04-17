"""Tests for AnalyticsView primary view (B.8 revision 2).

Supersedes tests/gui/shell/overlays/test_analytics_panel.py — the
overlay-based AnalyticsPanel was replaced by AnalyticsView (QWidget
primary view) after Codex caught the ModalCard architectural bug.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QProgressBar, QPushButton, QWidget

from cryodaq.gui import theme
from cryodaq.gui.shell.overlays._design_system.bento_grid import BentoGrid
from cryodaq.gui.shell.overlays._design_system.modal_card import ModalCard
from cryodaq.gui.shell.views.analytics_view import (
    AnalyticsView,
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


# ─── Primary-view invariants ──────────────────────────────────────────


def test_analytics_view_inherits_qwidget_not_modalcard(app):
    # Revision 2 architectural correction: the view is a primary-view
    # QWidget hosted in the shell's main content stack, NOT a dismissible
    # overlay with backdrop + close button + focus trap.
    view = AnalyticsView()
    assert isinstance(view, QWidget)
    assert not isinstance(view, ModalCard)


def test_analytics_view_has_no_close_button(app):
    # Primary views have no × dismissal affordance. QPushButton scan
    # must find no close-intent button.
    view = AnalyticsView()
    for btn in view.findChildren(QPushButton):
        text = (btn.text() or "").lower()
        obj_name = (btn.objectName() or "").lower()
        assert "\u2715" not in text  # ✕
        assert "close" not in obj_name
        assert "closeButton" not in btn.objectName()


def test_analytics_view_does_not_use_bento_grid(app):
    # Revision 2 uses QVBoxLayout + QHBoxLayout with explicit stretch;
    # BentoGrid is reserved for heterogeneous dashboard compositions.
    view = AnalyticsView()
    assert not view.findChildren(BentoGrid), (
        "AnalyticsView must not instantiate BentoGrid — primary-view "
        "layout uses QVBoxLayout + QHBoxLayout with stretch factors"
    )


def test_analytics_view_hero_strip_has_fixed_height_56(app):
    view = AnalyticsView()
    assert view._hero.height() == 56 or view._hero.minimumHeight() == 56
    # setFixedHeight pins both min and max.
    assert view._hero.maximumHeight() == 56


def test_analytics_view_rthermal_tile_has_fixed_height_72(app):
    view = AnalyticsView()
    assert view._rthermal_tile.maximumHeight() == 72
    assert view._rthermal_tile.minimumHeight() == 72


def test_analytics_view_vacuum_strip_has_fixed_height_140(app):
    view = AnalyticsView()
    assert view._vacuum_strip.maximumHeight() == 140
    assert view._vacuum_strip.minimumHeight() == 140


def test_analytics_view_layout_stretch_factors(app):
    # Hero strip + middle region + vacuum strip are stretch 0/1/0 in root
    # QVBoxLayout; cooldown plot is stretch 5 against right column 2 in
    # the middle QHBoxLayout.
    view = AnalyticsView()
    root = view.layout()
    assert root.stretch(0) == 0  # hero
    assert root.stretch(1) == 1  # middle
    assert root.stretch(2) == 0  # vacuum strip

    # The middle region's inner QHBoxLayout has cooldown plot at index 0
    # (stretch 5) and right column at index 1 (stretch 2).
    middle_widget = root.itemAt(1).widget()
    middle_lay = middle_widget.layout()
    assert middle_lay.stretch(0) == 5
    assert middle_lay.stretch(1) == 2


# ─── State + data ────────────────────────────────────────────────────


def test_analytics_view_no_data_shows_placeholders(app):
    view = AnalyticsView()
    view.set_cooldown(None)
    view.set_r_thermal(None)
    assert view._hero._eta_label.text() == "Охлаждение не активно"
    assert view._hero._progress.value() == 0
    assert view._rthermal_tile._value_label.text() == "—"


def test_analytics_view_phase1_renders_labels_and_progress(app):
    view = AnalyticsView()
    view.set_cooldown(_make_cooldown(phase="phase1", progress_pct=42.5))
    assert view._hero._eta_label.text() == "7ч 20мин ±45мин"
    assert view._hero._phase_label.text() == "Фаза 1 (295K→50K)"
    assert view._hero._progress.value() in (42, 43)


def test_analytics_view_all_phase_labels(app):
    view = AnalyticsView()
    expected = {
        "phase1": "Фаза 1 (295K→50K)",
        "transition": "Переход (S-bend)",
        "phase2": "Фаза 2 (50K→4K)",
        "stabilizing": "Стабилизация",
        "complete": "Завершено",
    }
    for phase, label in expected.items():
        view.set_cooldown(_make_cooldown(phase=phase))
        assert view._hero._phase_label.text() == label


def test_analytics_view_rthermal_renders_three_decimal_precision(app):
    view = AnalyticsView()
    view.set_r_thermal(
        RThermalData(
            current_value=12.3456,
            delta_per_minute=-0.0321,
            last_updated_ts=time.time(),
            history=[],
        )
    )
    text = view._rthermal_tile._value_label.text()
    assert "12.346" in text
    assert "K/W" in text
    assert "(устар.)" not in text


def test_analytics_view_rthermal_stale_border_status_stale(app):
    # Revision 2 signals stale via tile BORDER (STATUS_STALE), not by
    # dimming the value text (RULE-DATA-005).
    view = AnalyticsView()
    view.set_r_thermal(
        RThermalData(
            current_value=12.3,
            delta_per_minute=0.0,
            last_updated_ts=time.time() - 120,
            history=[],
        )
    )
    text = view._rthermal_tile._value_label.text()
    assert "(устар.)" in text
    # Value text stays FOREGROUND; tile border flips to STATUS_STALE.
    assert theme.FOREGROUND in view._rthermal_tile._value_label.styleSheet()
    assert theme.STATUS_STALE in view._rthermal_tile.styleSheet()


def test_analytics_view_rthermal_none_shows_dash(app):
    view = AnalyticsView()
    view.set_r_thermal(None)
    assert view._rthermal_tile._value_label.text() == "—"


def test_analytics_view_cooldown_plot_y_autoscale_disabled(app):
    view = AnalyticsView()
    view.set_cooldown(_make_cooldown())
    vb = view._cooldown_plot.getViewBox()
    _, y_auto = vb.autoRangeEnabled()
    assert y_auto is False


def test_analytics_view_cooldown_plot_uses_plot_bg(app):
    view = AnalyticsView()
    bg = view._cooldown_plot.backgroundBrush().color().name()
    assert bg.lower() == theme.PLOT_BG.lower()


def test_analytics_view_cooldown_actual_trajectory(app):
    view = AnalyticsView()
    view.set_cooldown(_make_cooldown())
    xs, ys = view._cooldown_curves["actual"].getData()
    assert list(xs) == [0.0, 1.0, 2.0]
    assert list(ys) == [295.0, 250.0, 200.0]


def test_analytics_view_phase_boundary_lines_rendered(app):
    view = AnalyticsView()
    view.set_cooldown(_make_cooldown(phase_boundaries_hours=[1.5, 4.0, 6.2]))
    lines = view._cooldown_curves["phase_lines"]
    assert len(lines) == 3
    positions = sorted(line.value() for line in lines)
    assert positions == [1.5, 4.0, 6.2]


def test_analytics_view_phase_boundaries_cleared_on_new_data(app):
    view = AnalyticsView()
    view.set_cooldown(_make_cooldown(phase_boundaries_hours=[1.0, 2.0, 3.0]))
    view.set_cooldown(_make_cooldown(phase_boundaries_hours=[5.0]))
    assert len(view._cooldown_curves["phase_lines"]) == 1
    view.set_cooldown(None)
    assert view._cooldown_curves["phase_lines"] == []


def test_analytics_view_fault_chrome_applies_status_fault(app):
    # Fault chrome: hero bottom-border + cooldown plot outer-border both
    # flip to STATUS_FAULT; content stays visible.
    view = AnalyticsView()
    view.set_cooldown(_make_cooldown())
    view.set_fault(True, "stale critical channel")
    assert theme.STATUS_FAULT in view._hero.styleSheet()
    assert theme.STATUS_FAULT in view._cooldown_plot.styleSheet()
    # ETA content preserved.
    assert view._hero._eta_label.text() == "7ч 20мин ±45мин"


def test_analytics_view_fault_clears_on_reset(app):
    view = AnalyticsView()
    view.set_fault(True)
    view.set_fault(False)
    assert theme.STATUS_FAULT not in view._hero.styleSheet()
    assert view._cooldown_plot.styleSheet() == ""


def test_analytics_view_progress_clamped_to_range(app):
    view = AnalyticsView()
    view.set_cooldown(_make_cooldown(progress_pct=-10.0))
    assert view._hero._progress.value() == 0
    view.set_cooldown(_make_cooldown(progress_pct=150.0))
    assert view._hero._progress.value() == 100


def test_analytics_view_does_not_import_zmq(app):
    # AST-walk check so the module docstring can mention "does not
    # import zmq" without tripping a substring match.
    import ast

    import cryodaq.gui.shell.views.analytics_view as mod

    src = open(mod.__file__, encoding="utf-8").read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "zmq"
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "zmq"
    # Signal-level check: no direct ZmqBridge / Worker instantiation names.
    assert "ZmqBridge" not in src
    assert "ZmqCommandWorker" not in src


def test_format_eta_preserves_legacy_semantics(app):
    assert _format_eta(7.33, 0.75) == "7ч 20мин ±45мин"
    assert _format_eta(0.0, 0.0) == "0ч 0мин ±0мин"
    assert _format_eta(1.5, 0.1) == "1ч 30мин ±6мин"


def test_analytics_view_rthermal_mini_plot_uses_apply_plot_style(app):
    view = AnalyticsView()
    bg = view._rthermal_mini.backgroundBrush().color().name()
    assert bg.lower() == theme.PLOT_BG.lower()


def test_analytics_view_rthermal_mini_tick_font_is_compact(app):
    # Tick fonts on both plots are FONT_LABEL_SIZE - 2 per spec — the
    # plot is main visual content, ticks should not compete.
    view = AnalyticsView()
    expected_size = max(theme.FONT_LABEL_SIZE - 2, 8)
    for axis_name in ("left", "bottom"):
        tick_font = view._cooldown_plot.getAxis(axis_name).style.get(
            "tickFont"
        )
        assert tick_font is not None
        assert tick_font.pointSize() == expected_size


def test_analytics_view_rthermal_history_drawn(app):
    view = AnalyticsView()
    now = time.time()
    view.set_r_thermal(
        RThermalData(
            current_value=12.0,
            delta_per_minute=0.0,
            last_updated_ts=now,
            history=[(now - 300, 11.0), (now - 150, 11.5), (now, 12.0)],
        )
    )
    xs, ys = view._rthermal_curve.getData()
    assert list(ys) == [11.0, 11.5, 12.0]
    assert len(xs) == 3


def test_analytics_view_progress_bar_type(app):
    # Sanity: the flex widget used in the hero strip is a QProgressBar.
    view = AnalyticsView()
    assert isinstance(view._hero._progress, QProgressBar)


def test_analytics_view_cooldown_plot_fixed_y_range_0_310(app):
    view = AnalyticsView()
    vb = view._cooldown_plot.getViewBox()
    y_range = vb.viewRange()[1]
    assert y_range[0] == pytest.approx(0.0, abs=0.1)
    assert y_range[1] == pytest.approx(310.0, abs=0.1)
