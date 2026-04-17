"""Analytics primary view (B.8 revision 2) — QWidget, not ModalCard.

Hosted as a page in the shell's main content stack (OverlayContainer).
Activated from ToolRail Ctrl+A. No backdrop, no close button, no focus
trap, no Escape-to-dismiss — primary-view invariants per
docs/design-system/cryodaq-primitives/analytics-panel.md (revision 2).

Layout is plot-dominant. The cooldown trajectory plot receives the
largest continuous block of screen space; hero strip (ETA + phase +
progress) and vacuum trend strip are thin chrome, R_thermal tile +
mini plot occupy a compact right column.

Data flow (preserved from B.8 follow-up 53232ea):
- `set_cooldown(CooldownData | None)`
- `set_r_thermal(RThermalData | None)`
- `set_fault(faulted: bool, reason: str)`

The view does not import zmq or subscribe directly. The shell
(`main_window_v2.py`) adapts `analytics/cooldown_predictor/cooldown_eta`
readings into `CooldownData` via `_cooldown_reading_to_data()` and
pushes via the setters.
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

# ─── Data models (preserved from B.8 follow-up 53232ea) ───────────────


@dataclass
class CooldownData:
    """Snapshot of cooldown predictor output.

    The shell-side adapter `MainWindowV2._cooldown_reading_to_data()`
    translates the live broker reading (channel
    `analytics/cooldown_predictor/cooldown_eta`, metadata shape
    documented in `src/cryodaq/analytics/cooldown_service.py:400-433`)
    into this dataclass before pushing into `AnalyticsView.set_cooldown`.
    """

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
    """Thermal resistance snapshot. No plugin publishes this today;
    `set_r_thermal()` remains part of the contract for future wiring."""

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

# Fixed Y range for cooldown plot per spec invariant #8 (never autoscale).
_COOLDOWN_Y_RANGE = (0.0, 310.0)

# Fixed pixel heights per spec anatomy (B.8 revision 2).
_HERO_STRIP_HEIGHT_PX = 56
_VACUUM_STRIP_HEIGHT_PX = 140
_RTHERMAL_TILE_HEIGHT_PX = 72


class AnalyticsView(QWidget):
    """Analytics primary view — plot-dominant page hosted in the shell
    main content stack.

    Instance lifecycle: constructed once by the shell on first Ctrl+A;
    stays alive across switches. `set_cooldown` / `set_r_thermal` /
    `set_fault` are idempotent — safe to call repeatedly with the same
    payload.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsView")
        self._cooldown: CooldownData | None = None
        self._r_thermal: RThermalData | None = None
        self._faulted = False
        self._fault_reason = ""

        # Tile handles — populated in _build_layout().
        self._hero: _HeroStrip | None = None
        self._cooldown_plot: pg.PlotWidget | None = None
        self._cooldown_curves: dict = {}
        self._rthermal_tile: _RThermalTile | None = None
        self._rthermal_mini: pg.PlotWidget | None = None
        self._rthermal_curve: pg.PlotDataItem | None = None
        self._vacuum_strip: _VacuumStrip | None = None

        self._build_layout()

        # Initial empty state.
        self.set_cooldown(None)
        self.set_r_thermal(None)

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Hero strip — compact fixed height, stretch 0.
        self._hero = _HeroStrip(self)
        self._hero.setFixedHeight(_HERO_STRIP_HEIGHT_PX)
        root.addWidget(self._hero, 0)

        # Middle region — stretch 1, plot + right column.
        middle = QWidget(self)
        middle_row = QHBoxLayout(middle)
        middle_row.setContentsMargins(
            theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3
        )
        middle_row.setSpacing(theme.SPACE_3)

        # Cooldown plot — dominant width (stretch 5).
        self._cooldown_plot, self._cooldown_curves = self._build_cooldown_plot()
        middle_row.addWidget(self._cooldown_plot, 5)

        # Right column — stretch 2.
        right_col_wrap = QWidget(middle)
        right_col = QVBoxLayout(right_col_wrap)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(theme.SPACE_2)

        self._rthermal_tile = _RThermalTile(right_col_wrap)
        self._rthermal_tile.setFixedHeight(_RTHERMAL_TILE_HEIGHT_PX)
        right_col.addWidget(self._rthermal_tile, 0)

        self._rthermal_mini, self._rthermal_curve = self._build_rthermal_mini()
        right_col.addWidget(self._rthermal_mini, 1)

        middle_row.addWidget(right_col_wrap, 2)
        root.addWidget(middle, 1)

        # Vacuum trend strip — compact fixed height, stretch 0.
        self._vacuum_strip = _VacuumStrip(self)
        self._vacuum_strip.setFixedHeight(_VACUUM_STRIP_HEIGHT_PX)
        root.addWidget(self._vacuum_strip, 0)

    def _build_cooldown_plot(self) -> tuple[pg.PlotWidget, dict]:
        plot = pg.PlotWidget()
        plot.setObjectName("analyticsCooldownPlot")
        apply_plot_style(plot)

        # Compact tick fonts — spec: FONT_LABEL_SIZE - 2.
        small_tick_size = max(theme.FONT_LABEL_SIZE - 2, 8)
        small_tick_font = QFont(theme.FONT_BODY, small_tick_size)
        for axis_name in ("left", "bottom"):
            plot.getAxis(axis_name).setStyle(tickFont=small_tick_font)

        pi = plot.getPlotItem()
        pi.setLabel("left", "T", units="K", color=theme.PLOT_LABEL_COLOR)
        pi.setLabel(
            "bottom", "Время от старта", units="ч", color=theme.PLOT_LABEL_COLOR
        )

        # Fixed Y range per invariant #8 — do not autoscale.
        pi.getViewBox().setYRange(*_COOLDOWN_Y_RANGE, padding=0)
        pi.getViewBox().enableAutoRange(axis=pg.ViewBox.YAxis, enable=False)

        pi.addLegend(offset=(-10, 10))

        actual = pi.plot([], [], pen=series_pen(0), name="Измерено")
        predicted = pi.plot(
            [], [], pen=series_pen(1, style=Qt.PenStyle.DashLine), name="Прогноз"
        )
        ci_lower = pi.plot(
            [], [], pen=pg.mkPen(color=theme.PLOT_GRID_COLOR, width=0)
        )
        ci_upper = pi.plot(
            [], [], pen=pg.mkPen(color=theme.PLOT_GRID_COLOR, width=0)
        )
        ci_fill = pg.FillBetweenItem(ci_lower, ci_upper, brush=warn_region_brush())
        pi.addItem(ci_fill)

        return plot, {
            "actual": actual,
            "predicted": predicted,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "phase_lines": [],
        }

    def _build_rthermal_mini(self) -> tuple[pg.PlotWidget, pg.PlotDataItem]:
        plot = pg.PlotWidget()
        plot.setObjectName("analyticsRThermalMini")
        apply_plot_style(plot)
        small_tick_size = max(theme.FONT_LABEL_SIZE - 2, 8)
        small_tick_font = QFont(theme.FONT_BODY, small_tick_size)
        pi = plot.getPlotItem()
        pi.setLabel("left", "R", units="K/W", color=theme.PLOT_LABEL_COLOR)
        pi.setLabel("bottom", "t", units="мин", color=theme.PLOT_LABEL_COLOR)
        for axis_name in ("left", "bottom"):
            pi.getAxis(axis_name).setStyle(tickFont=small_tick_font)
        curve = pi.plot([], [], pen=series_pen(0))
        return plot, curve

    # ------------------------------------------------------------------
    # Public setters
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
        self._apply_cooldown_fault_chrome(faulted)

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
        now = time.time()
        xs = [(ts - now) / 60.0 for ts, _ in data.history]
        ys = [v for _, v in data.history]
        self._rthermal_curve.setData(xs, ys)

    def _apply_cooldown_fault_chrome(self, faulted: bool) -> None:
        """Spec: cooldown plot gets STATUS_FAULT outer border on fault."""
        if faulted:
            self._cooldown_plot.setStyleSheet(
                f"#analyticsCooldownPlot "
                f"{{ border: 2px solid {theme.STATUS_FAULT}; }}"
            )
        else:
            self._cooldown_plot.setStyleSheet("")


# ─── Hero strip ───────────────────────────────────────────────────────


class _HeroStrip(QFrame):
    """Thin horizontal chrome at the top of AnalyticsView.

    Three items in a row: ETA (FONT_TITLE_SIZE), phase label
    (FONT_LABEL_SIZE muted), progress bar (flex width). No card
    background; a bottom 1px BORDER (or STATUS_FAULT in fault state)
    serves as the separator.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsHero")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._faulted = False
        self._build_ui()
        self._apply_chrome(faulted=False)

    def _build_ui(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(
            theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2
        )
        row.setSpacing(theme.SPACE_4)

        # ETA label — title-size, bold.
        self._eta_label = QLabel("—", self)
        eta_font = QFont(theme.FONT_BODY, theme.FONT_TITLE_SIZE)
        eta_font.setWeight(QFont.Weight(theme.FONT_TITLE_WEIGHT))
        try:
            eta_font.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError, ValueError):
            pass
        self._eta_label.setFont(eta_font)
        self._eta_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent;"
        )
        row.addWidget(self._eta_label, 0)

        # Phase label — label-size, muted foreground.
        self._phase_label = QLabel("—", self)
        phase_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        phase_font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
        self._phase_label.setFont(phase_font)
        self._phase_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        row.addWidget(self._phase_label, 0)

        # Progress bar — flex width, thin.
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
        row.addWidget(self._progress, 1)

    def set_cooldown(self, data: CooldownData | None) -> None:
        if data is None:
            self._eta_label.setText("Охлаждение не активно")
            self._phase_label.setText("")
            self._progress.setValue(0)
            self._progress.setVisible(False)
            return
        self._progress.setVisible(True)
        self._eta_label.setText(_format_eta(data.t_hours, data.ci_hours))
        self._phase_label.setText(_PHASE_LABELS.get(data.phase, data.phase))
        self._progress.setValue(int(round(max(0.0, min(100.0, data.progress_pct)))))

    def set_fault(self, faulted: bool) -> None:
        if faulted == self._faulted:
            return
        self._faulted = faulted
        self._apply_chrome(faulted=faulted)

    def _apply_chrome(self, *, faulted: bool) -> None:
        """Hero has no card background — just a bottom border separator.
        Fault flips the separator to STATUS_FAULT (spec §States)."""
        border_color = theme.STATUS_FAULT if faulted else theme.BORDER
        self.setStyleSheet(
            f"#analyticsHero {{"
            f"background-color: transparent;"
            f"border: none;"
            f"border-bottom: 1px solid {border_color};"
            f"}}"
        )


# ─── R_thermal metric tile ────────────────────────────────────────────


class _RThermalTile(QFrame):
    """Compact card: current R_thermal + delta per minute.

    Stale state uses BORDER color change («STATUS_STALE») + «(устар.)»
    text suffix; value text stays FOREGROUND per RULE-DATA-005.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsRThermalTile")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._stale = False
        self._build_ui()
        self._apply_chrome()

    def _build_ui(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(
            theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2
        )
        col.setSpacing(theme.SPACE_1)

        caption = QLabel("R_тепл", self)
        cap_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        cap_font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
        caption.setFont(cap_font)
        caption.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        col.addWidget(caption)

        self._value_label = QLabel("—", self)
        val_font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
        val_font.setWeight(QFont.Weight(theme.FONT_MONO_VALUE_WEIGHT))
        try:
            val_font.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError, ValueError):
            pass
        self._value_label.setFont(val_font)
        # RULE-DATA-005: value text never dims — stays FOREGROUND even
        # when stale. Stale is signalled via border + text suffix.
        self._value_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent;"
        )
        col.addWidget(self._value_label)

        self._delta_label = QLabel("", self)
        delta_font = QFont(theme.FONT_MONO, theme.FONT_LABEL_SIZE)
        try:
            delta_font.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError, ValueError):
            pass
        self._delta_label.setFont(delta_font)
        self._delta_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        col.addWidget(self._delta_label)

    def _apply_chrome(self) -> None:
        border = theme.STATUS_STALE if self._stale else theme.BORDER
        self.setStyleSheet(
            f"#analyticsRThermalTile {{"
            f"background-color: {theme.SURFACE_CARD};"
            f"border: 1px solid {border};"
            f"border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )

    # ------------------------------------------------------------------

    def set_data(self, data: RThermalData | None) -> None:
        if data is None or data.current_value is None:
            self._value_label.setText("—")
            self._delta_label.setText("")
            if self._stale:
                self._stale = False
                self._apply_chrome()
            return

        # 3-decimal precision per RULE-DATA-004.
        text = f"{data.current_value:.3f} K/W"
        age = time.time() - data.last_updated_ts
        stale_now = age > _R_THERMAL_STALE_S
        if stale_now:
            text += " (устар.)"
        self._value_label.setText(text)

        if data.delta_per_minute is None:
            self._delta_label.setText("")
        else:
            sign = "+" if data.delta_per_minute > 0 else ""
            self._delta_label.setText(
                f"Δ {sign}{data.delta_per_minute:.3f} K/W/мин"
            )

        if stale_now != self._stale:
            self._stale = stale_now
            self._apply_chrome()


# ─── Vacuum trend strip ───────────────────────────────────────────────


class _VacuumStrip(QFrame):
    """Bottom chrome strip hosting the legacy VacuumTrendPanel.

    VacuumTrendPanel is NOT rewritten in B.8 revision 2 — bringing it
    into design-system alignment (apply_plot_style, Cyrillic мбар axis
    label, log-Y) is a separate follow-up per the spec §Vacuum trend
    B.8 scope note. This wrapper just provides the fixed-height frame
    and top-border separator.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsVacuumStrip")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._panel: QWidget | None = None
        self._build_ui()
        self._apply_chrome()

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setContentsMargins(
            theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2
        )
        lay.setSpacing(0)
        try:
            from cryodaq.gui.widgets.vacuum_trend_panel import VacuumTrendPanel

            self._panel = VacuumTrendPanel()
            lay.addWidget(self._panel, 1)
        except Exception as exc:  # pragma: no cover — fallback path
            fallback = QLabel(f"[VacuumTrendPanel недоступен: {exc!s}]", self)
            fallback.setStyleSheet(
                f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
            )
            lay.addWidget(fallback, 1)

    def _apply_chrome(self) -> None:
        self.setStyleSheet(
            f"#analyticsVacuumStrip {{"
            f"background-color: {theme.SURFACE_CARD};"
            f"border: none;"
            f"border-top: 1px solid {theme.BORDER};"
            f"}}"
        )
