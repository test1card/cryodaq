"""Analytics overlay — B.8 rebuild of the legacy analytics panel.

Full-screen ModalCard overlay surfacing computed metrics from analytics
plugins: cooldown ETA + trajectory, thermal resistance, vacuum trend.

See `docs/design-system/cryodaq-primitives/analytics-panel.md`.

Legacy v1 at `src/cryodaq/gui/widgets/analytics_panel.py` preserves the
domain logic and stays alive until Block B.13. The v2 panel below
inherits ModalCard chrome (focus trap, focus restoration, Escape to
close) and composes its body on a canonical 8-column `BentoGrid` per
AD-001. Data flows in via `set_cooldown` / `set_r_thermal` /
`set_fault` — the panel does not subscribe to ZMQ directly; the shell
(`main_window_v2.py`) owns the subscription and pushes snapshots.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui._plot_style import (
    apply_plot_style,
    series_pen,
    warn_region_brush,
)
from cryodaq.gui.shell.overlays._design_system.bento_grid import BentoGrid
from cryodaq.gui.shell.overlays._design_system.modal_card import ModalCard

# ─── Data models (from spec §API) ─────────────────────────────────────


@dataclass
class CooldownData:
    """Snapshot of cooldown predictor output."""

    t_hours: float
    ci_hours: float
    phase: str  # "phase1" | "transition" | "phase2" | "stabilizing" | "complete"
    progress_pct: float  # 0..100, overall cooldown progress
    actual_trajectory: list[tuple[float, float]] = field(default_factory=list)
    predicted_trajectory: list[tuple[float, float]] = field(default_factory=list)
    ci_trajectory: list[tuple[float, float, float]] = field(default_factory=list)
    phase_boundaries_hours: list[float] = field(default_factory=list)


@dataclass
class RThermalData:
    """Thermal resistance snapshot."""

    current_value: float | None
    delta_per_minute: float | None
    last_updated_ts: float
    history: list[tuple[float, float]] = field(default_factory=list)


# ─── Phase labels + ETA formatter (preserved from legacy v1) ──────────

_PHASE_LABELS: dict[str, str] = {
    "phase1": "Фаза 1 (295K→50K)",
    "transition": "Переход (S-bend)",
    "phase2": "Фаза 2 (50K→4K)",
    "stabilizing": "Стабилизация",
    "complete": "Завершено",
}


def _format_eta(t_hours: float, ci_hours: float) -> str:
    """Format ETA as «Nч Mмин ±Kмин» — same semantics as legacy v1."""
    hours = int(t_hours)
    mins = int(round((t_hours - hours) * 60))
    ci_mins = int(round(ci_hours * 60))
    return f"{hours}ч {mins}мин ±{ci_mins}мин"


_R_THERMAL_STALE_S = 60.0

# Fixed Y range for cooldown plot (invariant: no autoscale).
# Start temperature ~300 K, target ~1 K. Overshoots past these bounds
# are informative and rendered as-is.
_COOLDOWN_Y_RANGE = (1.0, 320.0)


class AnalyticsPanel(ModalCard):
    """Full-screen analytics overlay (B.8).

    Single-instance invariant (spec #2) is enforced at the shell level
    (`main_window_v2.py`) — it tracks whether this panel is already
    open and avoids creating duplicates on repeated Ctrl+A.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cooldown: CooldownData | None = None
        self._r_thermal: RThermalData | None = None
        self._faulted = False
        self._fault_reason = ""

        self._content = QWidget(self)
        self._grid = BentoGrid(parent=self._content)
        root = QVBoxLayout(self._content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._grid)

        # Cache the base chrome string so set_fault can toggle between
        # default BORDER and STATUS_FAULT border-left without losing
        # the baseline styling of the card chrome.
        self._hero: _HeroCard | None = None
        self._cooldown_plot: pg.PlotWidget | None = None
        self._rthermal_tile: _RThermalTile | None = None
        self._rthermal_mini: pg.PlotWidget | None = None
        self._vacuum_host: _VacuumHost | None = None

        self._build_tiles()
        self.set_content(self._content)

        # Initial empty state
        self.set_cooldown(None)
        self.set_r_thermal(None)

    # ------------------------------------------------------------------
    # Tile construction
    # ------------------------------------------------------------------

    def _build_tiles(self) -> None:
        # Row 0 (col 0..8): Hero ETA card
        self._hero = _HeroCard(self._content)
        self._grid.add_tile(self._hero, row=0, col=0, col_span=8, row_span=1)

        # Row 1..3 (col 0..5): Cooldown trajectory plot
        self._cooldown_plot, self._cooldown_curves = self._build_cooldown_plot()
        self._grid.add_tile(
            self._cooldown_plot, row=1, col=0, col_span=5, row_span=3
        )

        # Row 1 (col 5..8): R_thermal metric tile
        self._rthermal_tile = _RThermalTile(self._content)
        self._grid.add_tile(
            self._rthermal_tile, row=1, col=5, col_span=3, row_span=1
        )

        # Row 2..3 (col 5..8): R_thermal mini plot
        self._rthermal_mini, self._rthermal_curve = self._build_rthermal_mini_plot()
        self._grid.add_tile(
            self._rthermal_mini, row=2, col=5, col_span=3, row_span=2
        )

        # Row 4 (col 0..8): Vacuum trend host
        self._vacuum_host = _VacuumHost(self._content)
        self._grid.add_tile(
            self._vacuum_host, row=4, col=0, col_span=8, row_span=1
        )

    def _build_cooldown_plot(self) -> tuple[pg.PlotWidget, dict]:
        plot = pg.PlotWidget()
        apply_plot_style(plot)
        pi = plot.getPlotItem()
        pi.setLabel(
            "left",
            "Температура",
            units="K",
            color=theme.PLOT_LABEL_COLOR,
        )
        pi.setLabel(
            "bottom",
            "Время от старта",
            units="ч",
            color=theme.PLOT_LABEL_COLOR,
        )

        # Invariant: fixed Y range, not autoscale. Overshoots render
        # as-is because they are informative (spec common-mistake #3).
        pi.getViewBox().setYRange(*_COOLDOWN_Y_RANGE, padding=0)
        pi.getViewBox().enableAutoRange(axis=pg.ViewBox.YAxis, enable=False)

        pi.addLegend(offset=(-10, 10))

        # Actual: solid PLOT_LINE_PALETTE[0]
        actual_curve = pi.plot([], [], pen=series_pen(0), name="Измерено")

        # Predicted: dashed PLOT_LINE_PALETTE[1]
        predicted_curve = pi.plot(
            [], [], pen=series_pen(1, style=Qt.PenStyle.DashLine), name="Прогноз"
        )

        # CI band: lower + upper invisible lines, FillBetweenItem across them.
        ci_lower = pi.plot([], [], pen=pg.mkPen(color=theme.PLOT_GRID_COLOR, width=0))
        ci_upper = pi.plot([], [], pen=pg.mkPen(color=theme.PLOT_GRID_COLOR, width=0))
        ci_fill = pg.FillBetweenItem(ci_lower, ci_upper, brush=warn_region_brush())
        pi.addItem(ci_fill)

        return plot, {
            "actual": actual_curve,
            "predicted": predicted_curve,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "phase_lines": [],
        }

    def _build_rthermal_mini_plot(self) -> tuple[pg.PlotWidget, pg.PlotDataItem]:
        plot = pg.PlotWidget()
        apply_plot_style(plot)
        pi = plot.getPlotItem()
        pi.setLabel("left", "R", units="K/W", color=theme.PLOT_LABEL_COLOR)
        pi.setLabel("bottom", "t", units="мин", color=theme.PLOT_LABEL_COLOR)
        # Smaller tick font for compact plot.
        tick_size = max(theme.FONT_LABEL_SIZE - 2, 9)
        tick_font = QFont(theme.FONT_BODY, tick_size)
        for ax_name in ("left", "bottom"):
            pi.getAxis(ax_name).setStyle(tickFont=tick_font)
        curve = pi.plot([], [], pen=series_pen(0))
        return plot, curve

    # ------------------------------------------------------------------
    # Public setters (shell pushes state)
    # ------------------------------------------------------------------

    def set_cooldown(self, data: CooldownData | None) -> None:
        self._cooldown = data
        self._hero.set_cooldown(data)
        self._apply_cooldown_plot(data)

    def set_r_thermal(self, data: RThermalData | None) -> None:
        self._r_thermal = data
        self._rthermal_tile.set_data(data)
        self._apply_rthermal_mini(data)

    def set_fault(self, faulted: bool, reason: str = "") -> None:
        self._faulted = faulted
        self._fault_reason = reason if faulted else ""
        self._hero.set_fault(faulted)
        self._apply_plot_fault_chrome(self._cooldown_plot, faulted)

    # ------------------------------------------------------------------
    # Plot update helpers
    # ------------------------------------------------------------------

    def _apply_cooldown_plot(self, data: CooldownData | None) -> None:
        curves = self._cooldown_curves
        if data is None:
            curves["actual"].setData([], [])
            curves["predicted"].setData([], [])
            curves["ci_lower"].setData([], [])
            curves["ci_upper"].setData([], [])
            self._clear_phase_lines()
            return

        if data.actual_trajectory:
            xs = [pt[0] for pt in data.actual_trajectory]
            ys = [pt[1] for pt in data.actual_trajectory]
            curves["actual"].setData(xs, ys)
        else:
            curves["actual"].setData([], [])

        if data.predicted_trajectory:
            xs = [pt[0] for pt in data.predicted_trajectory]
            ys = [pt[1] for pt in data.predicted_trajectory]
            curves["predicted"].setData(xs, ys)
        else:
            curves["predicted"].setData([], [])

        if data.ci_trajectory:
            xs = [pt[0] for pt in data.ci_trajectory]
            lower_ys = [pt[1] for pt in data.ci_trajectory]
            upper_ys = [pt[2] for pt in data.ci_trajectory]
            curves["ci_lower"].setData(xs, lower_ys)
            curves["ci_upper"].setData(xs, upper_ys)
        else:
            curves["ci_lower"].setData([], [])
            curves["ci_upper"].setData([], [])

        self._render_phase_lines(data.phase_boundaries_hours)

    def _clear_phase_lines(self) -> None:
        pi = self._cooldown_plot.getPlotItem()
        for line in self._cooldown_curves["phase_lines"]:
            pi.removeItem(line)
        self._cooldown_curves["phase_lines"] = []

    def _render_phase_lines(self, boundaries_hours: list[float]) -> None:
        """Vertical dashed lines at phase transitions. Sourced from the
        predictor meta — no hardcoded boundary temperatures."""
        self._clear_phase_lines()
        if not boundaries_hours:
            return
        pi = self._cooldown_plot.getPlotItem()
        pen = pg.mkPen(
            color=theme.PLOT_GRID_COLOR, width=1, style=Qt.PenStyle.DashLine
        )
        for hours in boundaries_hours:
            line = pg.InfiniteLine(pos=hours, angle=90, pen=pen)
            pi.addItem(line)
            self._cooldown_curves["phase_lines"].append(line)

    def _apply_rthermal_mini(self, data: RThermalData | None) -> None:
        if data is None or not data.history:
            self._rthermal_curve.setData([], [])
            return
        # Convert (unix_ts, value) history to minutes-ago x axis so the
        # mini plot reads "last 10 minutes" with 0 = now on the right.
        now = time.time()
        xs = [(ts - now) / 60.0 for ts, _ in data.history]
        ys = [v for _, v in data.history]
        self._rthermal_curve.setData(xs, ys)

    def _apply_plot_fault_chrome(
        self, plot_widget: pg.PlotWidget | None, faulted: bool
    ) -> None:
        if plot_widget is None:
            return
        # pyqtgraph PlotWidget has setStyleSheet via QWidget; apply a
        # named border so set_fault(False) reverts cleanly.
        plot_widget.setObjectName("analyticsPlot")
        if faulted:
            plot_widget.setStyleSheet(
                f"#analyticsPlot {{ border: 2px solid {theme.STATUS_FAULT}; }}"
            )
        else:
            plot_widget.setStyleSheet("")


# ─── Hero ETA card ────────────────────────────────────────────────────


class _HeroCard(QFrame):
    """Top-row hero: ETA big-font + phase label + progress bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsHero")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._faulted = False
        self._build_ui()
        self._apply_chrome(faulted=False)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5
        )
        root.setSpacing(theme.SPACE_3)

        # Top row: ETA (big) left, phase label right.
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(theme.SPACE_4)

        self._eta_label = QLabel("—", self)
        eta_font = QFont(theme.FONT_DISPLAY, theme.FONT_DISPLAY_SIZE)
        eta_font.setWeight(QFont.Weight(theme.FONT_DISPLAY_WEIGHT))
        self._eta_label.setFont(eta_font)
        self._eta_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent;"
        )
        top_row.addWidget(self._eta_label, 1)

        self._phase_label = QLabel("—", self)
        phase_font = QFont(theme.FONT_BODY, theme.FONT_TITLE_SIZE)
        phase_font.setWeight(QFont.Weight(theme.FONT_TITLE_WEIGHT))
        self._phase_label.setFont(phase_font)
        self._phase_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._phase_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        top_row.addWidget(self._phase_label, 0)
        root.addLayout(top_row)

        # Progress bar — 0..100 overall cooldown progress.
        self._progress = QProgressBar(self)
        self._progress.setObjectName("analyticsHeroProgress")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(8)
        self._progress.setStyleSheet(
            f"#analyticsHeroProgress {{"
            f"background: {theme.SURFACE_SUNKEN};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_SM}px;"
            f"}}"
            f"#analyticsHeroProgress::chunk {{"
            f"background: {theme.ACCENT};"
            f"border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )
        root.addWidget(self._progress)

    # ------------------------------------------------------------------

    def set_cooldown(self, data: CooldownData | None) -> None:
        if data is None:
            self._eta_label.setText("Охлаждение не активно")
            self._phase_label.setText("—")
            self._progress.setValue(0)
            return
        self._eta_label.setText(_format_eta(data.t_hours, data.ci_hours))
        self._phase_label.setText(_PHASE_LABELS.get(data.phase, data.phase))
        self._progress.setValue(int(round(max(0.0, min(100.0, data.progress_pct)))))

    def set_fault(self, faulted: bool) -> None:
        if faulted == self._faulted:
            return
        self._faulted = faulted
        self._apply_chrome(faulted=faulted)

    def _apply_chrome(self, *, faulted: bool) -> None:
        base = (
            f"#analyticsHero {{"
            f"background-color: {theme.SURFACE_CARD};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_LG}px;"
        )
        if faulted:
            base += f"border-left: 3px solid {theme.STATUS_FAULT};"
        base += "}"
        self.setStyleSheet(base)


# ─── R_thermal metric tile ────────────────────────────────────────────


class _RThermalTile(QFrame):
    """Side tile: current R_thermal value + delta per minute."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsRThermal")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()
        self._apply_chrome()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4
        )
        root.setSpacing(theme.SPACE_2)

        caption = QLabel("R_тепл", self)
        cap_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        cap_font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
        caption.setFont(cap_font)
        caption.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        root.addWidget(caption)

        self._value_label = QLabel("—", self)
        val_font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
        val_font.setWeight(QFont.Weight(theme.FONT_MONO_VALUE_WEIGHT))
        try:
            val_font.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError, ValueError):
            pass
        self._value_label.setFont(val_font)
        self._value_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent;"
        )
        root.addWidget(self._value_label)

        self._delta_label = QLabel("—", self)
        delta_font = QFont(theme.FONT_MONO, theme.FONT_LABEL_SIZE)
        try:
            delta_font.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError, ValueError):
            pass
        self._delta_label.setFont(delta_font)
        self._delta_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        root.addWidget(self._delta_label)

    def _apply_chrome(self) -> None:
        self.setStyleSheet(
            f"#analyticsRThermal {{"
            f"background-color: {theme.SURFACE_CARD};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_LG}px;"
            f"}}"
        )

    # ------------------------------------------------------------------

    def set_data(self, data: RThermalData | None) -> None:
        if data is None or data.current_value is None:
            self._value_label.setText("—")
            self._value_label.setStyleSheet(
                f"color: {theme.FOREGROUND}; background: transparent;"
            )
            self._delta_label.setText("—")
            return

        # 3-decimal precision per RULE-DATA-004; unit is K/W.
        text = f"{data.current_value:.3f} K/W"
        age = time.time() - data.last_updated_ts
        stale = age > _R_THERMAL_STALE_S
        if stale:
            text += " (устар.)"
            color = theme.STATUS_STALE
        else:
            color = theme.FOREGROUND
        self._value_label.setText(text)
        self._value_label.setStyleSheet(
            f"color: {color}; background: transparent;"
        )

        if data.delta_per_minute is None:
            self._delta_label.setText("—")
        else:
            sign = "+" if data.delta_per_minute > 0 else ""
            self._delta_label.setText(
                f"Δ {sign}{data.delta_per_minute:.3f} K/W · мин"
            )


# ─── Vacuum host ──────────────────────────────────────────────────────


class _VacuumHost(QFrame):
    """Frame hosting the legacy VacuumTrendPanel.

    Per spec §Vacuum trend section / §B.8 scope note: VacuumTrendPanel
    itself is NOT rewritten in B.8. This host just frames the existing
    widget so it sits correctly inside the BentoGrid. Token alignment
    inside VacuumTrendPanel (apply_plot_style, Cyrillic мбар axis, log
    Y) is tracked as a separate follow-up per the B.8 scope note.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsVacuumHost")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._panel: QWidget | None = None
        self._missing_panel_label: QLabel | None = None
        self._build_ui()
        self._apply_chrome()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4
        )
        root.setSpacing(theme.SPACE_2)

        caption = QLabel("Прогноз вакуума", self)
        cap_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        cap_font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
        caption.setFont(cap_font)
        caption.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        root.addWidget(caption)

        # Lazy-import VacuumTrendPanel to avoid a hard dependency at
        # module-import time — the legacy panel brings heavy Qt setup
        # which we don't need during unit tests that don't exercise
        # the embed.
        try:
            from cryodaq.gui.widgets.vacuum_trend_panel import VacuumTrendPanel

            self._panel = VacuumTrendPanel()
            root.addWidget(self._panel, 1)
        except Exception as exc:  # pragma: no cover — fallback path
            self._missing_panel_label = QLabel(
                f"[VacuumTrendPanel недоступен: {exc!s}]", self
            )
            self._missing_panel_label.setStyleSheet(
                f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
            )
            root.addWidget(self._missing_panel_label, 1)

    def _apply_chrome(self) -> None:
        self.setStyleSheet(
            f"#analyticsVacuumHost {{"
            f"background-color: {theme.SURFACE_CARD};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_LG}px;"
            f"}}"
        )
