---
title: Analytics Panel
keywords: analytics, R_thermal, cooldown, ETA, prediction, vacuum trend, phase, аналитика, primary view
applies_to: analytics primary view (Ctrl+A from ToolRail)
status: proposed
implements: not yet aligned with this revision. Existing implementation at `src/cryodaq/gui/shell/overlays/analytics_panel.py` inherits ModalCard — that is the architectural bug this revision corrects. Reimplementation as primary view is the next step. Legacy v1 at `src/cryodaq/gui/widgets/analytics_panel.py` kept alive until B.13.
last_updated: 2026-04-17
---

# Analytics Panel

Full-viewport primary view surfacing computed metrics from analytics
plugins: cooldown ETA + trajectory, thermal resistance, vacuum trend.
Opens as the main content of the application when operator activates
the analytics slot on ToolRail (keyboard `Ctrl+A`, AD-002).

## Architecture — primary view, NOT overlay

Analytics is one of the application's primary views, alongside
Dashboard, Keithley, Conductivity, Operator log, Alarms, Sensor
diagnostics. It is **not** a ModalCard overlay.

The shell (`main_window_v2.py`) hosts a single main content region
(e.g. `QStackedWidget`). Each primary view is a page in that stack.
ToolRail switches pages by emitting `tool_clicked(slot_name)`; shell
handles the mapping `slot_name → stack_index` and calls
`setCurrentIndex()`.

Primary views:
- Do not have a backdrop.
- Do not have a close (×) button.
- Do not trap focus.
- Do not dismiss on Escape.
- Fill the entire content region between TopWatchBar and BottomStatusBar.
- Stay alive across switches (state preserved when user navigates away).

ModalCards remain for actual modals — confirmation dialogs, new-experiment
dialog, settings. Any view opened from ToolRail is a primary view.

## When to use

- Operator wants to know "when will cooldown finish" → ETA strip
- Operator wants to verify cooldown is on track → trajectory plot (the main content)
- Operator is measuring thermal conductivity → R_thermal tile + mini plot
- Operator suspects vacuum degradation → vacuum trend strip at the bottom

**When NOT to use:**
- Live single-channel watching — use Dashboard + SensorCell instead
- Full experiment lifecycle management — use Experiment view (Ctrl+E)
- Raw history export — use Archive view (Ctrl+R)

## Anatomy — plot-dominant layout

Plots are the primary content. All other elements are compact chrome
around them.

```
┌───────────────────────────────────────────────────────────────────┐
│ Hero strip (compact, ~56px tall, full width)                      │
│  7ч 20мин ±45мин   Фаза 2 (50K→4K)   ██████████░░░░░░░░░ 68%     │
├───────────────────────────────────────────────────────────────────┤
│                                                 │                 │
│                                                 │  R_тепл         │
│                                                 │  12.3 K/W       │
│                                                 │  −0.03 K/W/мин  │
│                                                 │─────────────────┤
│  Cooldown trajectory plot                       │                 │
│  (dominant vertical + horizontal space,         │  R_тепл         │
│   ~75% of view width, ~80% of view height)      │  mini plot      │
│                                                 │  (small,        │
│   — actual   -- predicted   ░ CI band           │   ~25% width    │
│                                                 │   bottom 75%    │
│                                                 │   of right col) │
│                                                 │                 │
│                                                 │                 │
├───────────────────────────────────────────────────────────────────┤
│ Vacuum trend strip (compact, ~140px tall, full width)             │
│  Прогноз: 1e-6 мбар через ~2ч 30мин   [compact log-Y sparkline]   │
└───────────────────────────────────────────────────────────────────┘
```

Layout implementation — `QVBoxLayout` at root:

```
root QVBoxLayout:
├── Hero strip (setFixedHeight ~56px, stretch=0)
├── Middle region (stretch=1):
│   └── QHBoxLayout:
│       ├── Cooldown plot (stretch=5)
│       └── Right column (stretch=2):
│           └── QVBoxLayout:
│               ├── R_thermal metric tile (setFixedHeight ~72px, stretch=0)
│               └── R_thermal mini plot (stretch=1)
└── Vacuum trend strip (setFixedHeight ~140px, stretch=0)
```

No BentoGrid for this view — BentoGrid is optimised for heterogeneous
dashboard compositions. Primary views have deliberate single-purpose
layouts where fixed-height chrome strips plus stretch-weighted plots
give the right visual hierarchy.

## Parts

### Hero strip

**Purpose.** Answer the one question: «когда эксперимент станет возможен»,
without stealing screen real estate from the plots.

Single horizontal row, three items left-to-right:

- **ETA** — `FONT_TITLE_SIZE` bold, e.g. `7ч 20мин ±45мин`. CI interval
  inline; only the `±NNмин` portion styled `MUTED_FOREGROUND`. Uses
  `_format_eta(t_hours, ci_hours)` preserved from legacy.
- **Phase label** — `FONT_LABEL_SIZE`, `MUTED_FOREGROUND`. Examples:
  «Фаза 1 (295K→50K)», «Переход (S-bend)», «Фаза 2 (50K→4K)»,
  «Стабилизация», «Завершено».
- **Progress bar** — `QProgressBar` with custom QSS, flexible width,
  overall cooldown progress 0..100% (0 = start, 100 = target reached).
  Track: `SURFACE_SUNKEN`. Fill: `ACCENT`. Height: ~8px (thin).

Padding: `SPACE_3` (12) horizontal, `SPACE_2` (8) vertical. No card
background — hero sits directly on the view background with a bottom
1px `BORDER` separator.

**Empty state:** «Охлаждение не активно» in `MUTED_FOREGROUND` centred
in the strip. Progress bar hidden. No ETA shown.

### Cooldown trajectory plot

**Purpose.** The primary content. Visual sanity check for cooldown
progress vs prediction.

Single `pg.PlotWidget`, styled via `apply_plot_style()`.

- **X axis:** hours from cooldown start (linear). Label: «Время от старта».
- **Y axis:** temperature in K, linear. Label: «T», units «K». Fixed
  range ~0..310 K. Overshoots render outside the range; do not autoscale.
- **Actual line:** `series_pen(0)`, solid, label «Измерено».
- **Predicted line:** `series_pen(1)` with `style=Qt.DashLine`, label
  «Прогноз».
- **CI band:** `pg.FillBetweenItem(lower, upper, brush=warn_region_brush())`
  between predicted-lower and predicted-upper trajectories.
- **Phase boundaries:** vertical dashed lines (`pg.InfiniteLine(angle=90,
  pen=pg.mkPen(theme.PLOT_GRID_COLOR, style=Qt.DashLine))`) at phase
  transition times provided by cooldown predictor plugin meta. **Do
  not hardcode boundary temperatures.**
- **Legend:** small, inside plot area, upper-right.
- **Tick fonts:** `FONT_LABEL_SIZE - 2` (compact), applied after
  `apply_plot_style()`. The plot is the main visual — tick labels
  should not compete with the data.
- **Axis label fonts:** `FONT_LABEL_SIZE` with `MUTED_FOREGROUND`.
- **Grid:** default `PLOT_GRID_ALPHA`.

**Empty state:** axes visible, no series plotted, no placeholder text
inside the plot area. The empty plot is the placeholder — operator's
eye locks onto the plot location and content appears when data arrives.

### R_thermal metric tile

**Purpose.** Current thermal resistance readout + short-term trend indicator.

Compact card, right column top. `setFixedHeight(~72px)`.

- **Label** «R_тепл» in `FONT_LABEL_SIZE` `MUTED_FOREGROUND` (no emoji,
  Cyrillic).
- **Current value** in `FONT_MONO_VALUE_SIZE`, `FOREGROUND`:
  `12.345 K/W`, 3-decimal precision per RULE-DATA-004. Dash «—» when
  data is None.
- **Delta per minute** below value in `FONT_LABEL_SIZE`,
  `MUTED_FOREGROUND`: `−0.03 K/W/мин`. Hidden when data is None.
- **Stale state** (RULE-A11Y-003): last update > 60s ago → apply
  `STATUS_STALE` border + «(устар.)» suffix to the value. Value text
  colour stays `FOREGROUND` (RULE-DATA-005 — never dim values).

Background: `SURFACE_CARD`. Border: 1px `BORDER` (or `STATUS_STALE` /
`STATUS_FAULT` when those states apply). Radius: `RADIUS_MD` (6).
Padding: `SPACE_3`.

### R_thermal mini plot

**Purpose.** 10-minute history of R_thermal for quick trend spotting.

Compact `pg.PlotWidget`, right column bottom, stretch=1.

- `apply_plot_style()`
- Tick fonts: `FONT_LABEL_SIZE - 2`
- Single series, `series_pen(0)`
- No legend
- X axis label: «t», units «мин»
- Y axis label: «R», units «K/W»
- No CI band; single solid line

**Empty state:** empty plot with axes visible.

### Vacuum trend strip

**Purpose.** Host existing `VacuumTrendPanel` at the bottom of the view.

Compact horizontal strip, `setFixedHeight(~140px)`.

**B.8 scope note.** VacuumTrendPanel is not rewritten in this revision.
Analytics view hosts the existing widget inside a `QFrame` with a
`SURFACE_CARD` background and 1px top `BORDER` separator. Bringing
VacuumTrendPanel into design-system alignment (`apply_plot_style`,
Cyrillic мбар axis, log-Y per RULE-DATA-008) is tracked as a separate
follow-up. Until then, document the divergence in the
implementation-status callout.

## States

| State | Hero strip | Cooldown plot | R_thermal | Vacuum |
|---|---|---|---|---|
| **No cooldown started** | «Охлаждение не активно» | empty axes | «—» | last-known data |
| **Phase 1** | ETA + «Фаза 1» + progress | actual + predicted + CI | updates if heater on | normal |
| **Transition** | ETA + «Переход» | both lines + CI band | updates | normal |
| **Phase 2** | ETA + «Фаза 2» | full content | updates | normal |
| **Stabilizing** | «~Nмин до цели» + «Стабилизация» | narrow CI | updates | normal |
| **Complete** | «Завершено, Nч Mмин» | frozen trajectory | final | final |
| **Fault** | `STATUS_FAULT` bottom border | `STATUS_FAULT` outer border | no change | no change |

Fault state does not hide content. Chrome borders flip to
`STATUS_FAULT`. Values stay readable.

Stale data (RULE-DATA-005): value colour stays `FOREGROUND`, stale
signalled by border colour + «(устар.)» text suffix, never by dimming.

## Invariants

1. **Primary view, not overlay.** Rendered as a page in the shell's
   main content stack. No backdrop, no close button, no focus trap,
   no Escape-to-dismiss.

2. **Plots dominate.** The cooldown trajectory plot receives the
   largest continuous block of screen space. Hero and vacuum are
   thin strips; R_thermal tile is compact. When operator looks at
   the view, their eye lands on the plot first.

3. **No raw sensor data.** Analytics renders computed plugin outputs
   only. Do not subscribe to raw T_cold readings inside the view.

4. **Cyrillic where user-facing** (RULE-COPY-001, RULE-COPY-006):
   Т for channel IDs, мбар for pressure units, «R_тепл» not
   «R_thermal» in labels. Latin identifiers in code.

5. **No emoji** (RULE-COPY-005). Text labels only.

6. **`apply_plot_style()` mandatory.** No hardcoded setBackground,
   mkPen, or QColor outside theme tokens.

7. **No STATUS_* colours for plot series.** Series colours come from
   `PLOT_LINE_PALETTE` only. STATUS_* reserved for semantic state
   per RULE-COLOR-002.

8. **Fixed Y range on cooldown plot.** Start..target K, never autoscale.
   Overshoots are informative.

9. **Phase boundaries from predictor meta.** Not hardcoded temperatures.

10. **Data flow.** View exposes `set_cooldown()`, `set_r_thermal()`,
    `set_fault()`. Does not import zmq or subscribe directly. Shell
    routes plugin readings into those setters via the adapter
    `MainWindowV2._cooldown_reading_to_data()` (established in B.8
    follow-up 53232ea).

## API

```python
# src/cryodaq/gui/shell/views/analytics_view.py
# (new location — views/ directory for primary views; overlays/ for modals)

from __future__ import annotations
from dataclasses import dataclass, field
from PySide6.QtWidgets import QWidget
import pyqtgraph as pg

from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen, warn_region_brush


@dataclass
class CooldownData:
    t_hours: float
    ci_hours: float
    phase: str           # "phase1" | "transition" | "phase2" | "stabilizing" | "complete"
    progress_pct: float  # 0..100 overall cooldown progress
    actual_trajectory: list[tuple[float, float]] = field(default_factory=list)
    predicted_trajectory: list[tuple[float, float]] = field(default_factory=list)
    ci_trajectory: list[tuple[float, float, float]] = field(default_factory=list)
    phase_boundaries_hours: list[float] = field(default_factory=list)


@dataclass
class RThermalData:
    current_value: float | None
    delta_per_minute: float | None
    last_updated_ts: float
    history: list[tuple[float, float]] = field(default_factory=list)


class AnalyticsView(QWidget):
    """Analytics primary view (B.8 revised).

    Hosted as a page in the shell's main content QStackedWidget.
    ToolRail Ctrl+A switches to this page; leaving the page does
    not destroy it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cooldown: CooldownData | None = None
        self._r_thermal: RThermalData | None = None
        self._faulted = False
        self._build_layout()

    def set_cooldown(self, data: CooldownData | None) -> None: ...
    def set_r_thermal(self, data: RThermalData | None) -> None: ...
    def set_fault(self, faulted: bool, reason: str = "") -> None: ...
```

Class name: `AnalyticsView` (not `AnalyticsPanel`) to reinforce the
primary-view architecture at the type level.

## Common mistakes

1. **Inheriting from ModalCard.** ModalCard is for dismissible overlays
   (confirmations, dialogs). Primary views are pages in the shell's
   main content stack; no backdrop, no close button, no focus trap.

2. **Using BentoGrid for a single-purpose view.** BentoGrid is for
   heterogeneous dashboard compositions. Single-purpose primary views
   with fixed layout intent (plot-dominant, chrome strips top+bottom)
   are clearer with `QVBoxLayout + QHBoxLayout` and explicit stretch
   factors.

3. **Uniform row heights.** Equal stretch compresses the plot. Use
   `setFixedHeight()` on chrome, `stretch=1` on plot region.

4. **Autoscaling Y axis.** Autoscale during cooldown causes the plot
   to visually "jump" and breaks operator's visual reference. Fix
   axis range; let overshoots render out of range.

5. **Hiding plots when no data.** Placeholder is the empty plot with
   axes visible. Operator's eye locks onto plot location; hiding and
   re-showing the widget is jarring.

6. **Labels competing with data.** Axis tick fonts should be compact
   (`FONT_LABEL_SIZE - 2`). The plot is the main visual — tick labels
   are reference, not content.

7. **Computing metrics in the view.** Plugins compute; shell adapts
   plugin readings via `_cooldown_reading_to_data()`; view renders.
   Do not duplicate plugin math inside the view.

## Accessibility

- No focus trap — primary view, not a modal.
- Tab order: Hero controls (if any become interactive) → plot area
  (focus ring only) → R_thermal tile → R_thermal mini plot → Vacuum
  trend content.
- Escape does nothing inside the view. Navigation happens via
  ToolRail shortcut.
- Colour-independent state signalling (RULE-A11Y-002): phase label
  always in text; R_thermal stale state shown with «(устар.)» text
  suffix, not only with colour.
- Large-text ETA gives operators at viewing distance the critical info.

## Rule references

- RULE-A11Y-002 — multi-channel state redundancy
- RULE-A11Y-003 — contrast on status colours
- RULE-COLOR-002 — STATUS_* semantic locks
- RULE-COLOR-004 — ACCENT reserved for selection / focus / action fills
- RULE-COPY-001 — Cyrillic Т for channel IDs
- RULE-COPY-005 — no emoji
- RULE-COPY-006 — мбар canonical
- RULE-DATA-004 — fixed precision per quantity
- RULE-DATA-005 — stale rendering never dims values
- RULE-DATA-008 — pressure log scale (applies to VacuumTrendPanel follow-up)
- RULE-SURF-001..007 — card invariants (R_thermal tile)
- AD-002 — mnemonic shortcut Ctrl+A

## Related specs

- `cryodaq-primitives/tool-rail.md` — slot that opens this view
- `cryodaq-primitives/top-watch-bar.md` — chrome above
- `cryodaq-primitives/bottom-status-bar.md` — chrome below
- `tokens/chart-tokens.md` — `apply_plot_style()` tokens
- `tokens/keyboard-shortcuts.md` — Ctrl+A binding
- `components/modal.md` — ModalCard (what this view is NOT)

## Known limitations (data availability)

Inherited from B.8 follow-up 53232ea:

- **Actual cooldown trajectory not rendered** — plugin publishes only
  predicted trajectory. The cooldown plot shows the predicted curve +
  CI band; the solid «Измерено» line stays empty until a publisher
  surfaces the actual T_cold buffer.
- **R_thermal live values not displayed** — no plugin publishes to
  `analytics/r_thermal/*`. `set_r_thermal()` remains as stable API;
  the tile and mini plot show placeholder `—` in production.
- **`"complete"` phase never emitted** — cooldown predictor conflates
  stabilizing and complete as `"steady"`; view remaps `"steady"` →
  `"stabilizing"` and does not render a distinct complete state
  until the plugin distinguishes them.

## Changelog

- 2026-04-17 (revision 2): Architectural correction. Changed base
  from `ModalCard` overlay to primary-view `QWidget` rendered in
  shell's main content stack. Removed backdrop, close button, focus
  trap, Escape-to-close. Replaced BentoGrid 8-col composition with
  `QVBoxLayout + QHBoxLayout` + fixed-height chrome strips to achieve
  plot-dominant visual hierarchy. Renamed class `AnalyticsPanel` →
  `AnalyticsView`. Moved file location
  `shell/overlays/analytics_panel.py` → `shell/views/analytics_view.py`.
  Reason: the first implementation (9a089f9, 53232ea) used ModalCard
  and rendered as a dismissible card over a backdrop, which is wrong
  for a ToolRail-activated primary view. Visual inspection showed
  plots being compressed by BentoGrid row stretching and the close
  button + dimmed backdrop mis-signalling the nature of the view.
- 2026-04-17 (revision 1): Initial spec (superseded by revision 2).
