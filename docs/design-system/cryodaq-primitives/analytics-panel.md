---
title: Analytics Panel
keywords: analytics, R_thermal, cooldown, ETA, prediction, vacuum trend, phase, аналитика
applies_to: analytics overlay panel (Ctrl+A from ToolRail)
status: active
implements: src/cryodaq/gui/shell/overlays/analytics_panel.py (Phase B.8); legacy src/cryodaq/gui/widgets/analytics_panel.py retained until Block B.13
last_updated: 2026-04-17
---

# Analytics Panel

Full-screen overlay surfacing derived metrics computed by analytics
plugins — thermal resistance, cooldown trajectory with prediction,
vacuum trend. Operator opens it via `Ctrl+A` (canonical mnemonic per
AD-002) or from ToolRail slot 5 (analytics).

> **Implementation status.** The shipped AnalyticsPanel at
> `src/cryodaq/gui/shell/overlays/analytics_panel.py` is aligned
> with this spec: inherits `ModalCard` (focus trap + restoration +
> Escape to close), composes its body on a canonical 8-column
> `BentoGrid` matching the anatomy table (Hero ETA at row 0 col 0..8,
> Cooldown plot at row 1..3 col 0..5, R_thermal tile at row 1 col
> 5..8, R_thermal mini plot at row 2..3 col 5..8, Vacuum host at
> row 4 col 0..8 — BentoGrid validates no-overlap). Hero ETA uses
> `FONT_DISPLAY_*` typography with an `ACCENT` / `SURFACE_SUNKEN`
> progress bar; `_format_eta` and `_PHASE_LABELS` preserve the legacy
> v1 semantics verbatim. Both plots run through `apply_plot_style()`;
> the cooldown plot has `enableAutoRange(y, False)` with fixed Y
> range per spec common-mistake #3, dashed predicted line via
> `series_pen(1, style=Qt.DashLine)`, CI band via
> `warn_region_brush()` on `pg.FillBetweenItem`, and phase
> boundaries rendered from `CooldownData.phase_boundaries_hours`
> (no hardcoded temperatures). R_thermal tile uses 3-decimal
> precision per RULE-DATA-004 and applies `(устар.)` +
> `STATUS_STALE` colour when `last_updated_ts > 60s` ago per
> RULE-A11Y-003. Fault chrome via `set_fault(True)` adds
> `STATUS_FAULT` border on hero + cooldown plot without hiding
> content. Data flow: the shell (`main_window_v2.py`) subscribes to
> engine analytics output and calls `set_cooldown()` /
> `set_r_thermal()` / `set_fault()` on this panel — the panel does
> not import `zmq` or subscribe directly.
>
> **Follow-ups tracked.**
> - `VacuumTrendPanel` (embedded via `_VacuumHost`) still uses its
>   own pre-design-system styling — `apply_plot_style()` alignment,
>   Cyrillic мбар axis label (RULE-COPY-006), and explicit log-Y
>   (RULE-DATA-008) are tracked as a separate follow-up per spec's
>   §Vacuum trend B.8 scope note.
> - Single-instance enforcement (spec invariant #2) lives at the
>   ToolRail / shell level — the lazy-construct factory in
>   `main_window_v2.py._OVERLAY_FACTORIES` creates at most one
>   `AnalyticsPanel` per MainWindow, and `_on_tool_clicked("analytics")`
>   re-uses it on subsequent Ctrl+A presses. The panel itself does
>   not guard against duplicate construction.

## Known limitations (data availability)

The shell (`main_window_v2._adapt_reading_to_analytics`) today
translates exactly one analytics channel into a panel setter call:

- **`analytics/cooldown_predictor/cooldown_eta`** → `set_cooldown()`.
  Plugin output shape is documented in
  `src/cryodaq/analytics/cooldown_service.py:400-433`; the adapter
  handles asymmetric `t_remaining_ci68` by collapsing to a
  conservative symmetric half-width and converts `progress` from a
  `[0, 1]` fraction into the panel's `0..100` percent.

Current consequences the operator sees:

- **Actual cooldown trajectory is not rendered** (cooldown plot's
  «Измерено» line stays empty). The predictor keeps the raw buffer
  internal and does not publish the time-series back onto the broker;
  adding a publisher (e.g. a downsampled `analytics/.../t_cold_history`
  channel) is a separate analytics-side change.

- **R_thermal tile + mini plot show the placeholder «—»** indefinitely.
  Nothing in `src/cryodaq/analytics/` publishes an
  `analytics/*/r_thermal` (or similar) channel today. The panel's
  `set_r_thermal()` method is part of the B.8 API contract and stays
  callable, but no consumer is wired to it. Adding an R_thermal
  publisher is the prerequisite.

- **Cooldown phase label «Завершено» never appears.** The predictor
  emits `"phase1" / "transition" / "phase2" / "steady"` (see
  `cooldown_predictor.py:518-524`); the adapter remaps `"steady"` to
  spec's `"stabilizing"`. The spec's `"complete"` is not distinguishable
  from plugin output. A predictor update that emits a terminal `"complete"`
  phase when progress pins at 1.0 would unlock it.

All three are analytics-layer changes, not UI changes — the v2 panel
itself is ready to render the data the moment a publisher exists.

Distinct from the Dashboard's live sensor grid: Analytics shows
**computed** values, not raw readings. The values update at lower
cadence (typically 1 Hz or slower) because the underlying plugins
batch and smooth their inputs.

**When to use:**
- Operator wants to know "when will cooldown finish" → ETA card
- Operator wants to verify cooldown is on track → trajectory plot
- Operator is measuring thermal conductivity → R_thermal card + mini plot
- Operator suspects vacuum degradation → vacuum trend section

**When NOT to use:**
- Live single-channel watching — use Dashboard + SensorCell instead
- Full experiment lifecycle management — use ExperimentCard + overlay
- Raw history export — use Archive panel (Ctrl+R)

## Anatomy

Full-screen overlay rendered in a `BentoGrid` (8 columns canonical per
AD-001). Four composition zones:

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Back ← Analytics                                                       │  ← DrillDownBreadcrumb (chrome)
├─────────────────────────────────────────────────────────────────────────┤
│  row 0 (col 0..8):  HERO — ETA + phase + progress bar                   │
│  ╔═══════════════════════════════════════════════════════════════════╗  │
│  ║  7ч 20мин ±45мин                          Фаза 2 (50K→4K)         ║  │
│  ║  ──────────────────────────────────────                           ║  │
│  ║  ███████████████████████░░░░░░░░░░░░░░░░░░ 68%                    ║  │
│  ╚═══════════════════════════════════════════════════════════════════╝  │
│                                                                         │
│  row 1..3 (col 0..5):  Cooldown trajectory plot                         │
│  ╔═══════════════════════════════════════════════════╗                  │
│  ║  T_cold (K) vs time (hours from start)            ║  row 1 (col 5..8) │
│  ║  ── actual   ── predicted   ░░ CI band            ║  R_thermal tile  │
│  ║                                                    ║  ╔════════════╗ │
│  ║   Phase 1     │ Transition │  Phase 2              ║  ║ 12.3 K/W   ║ │
│  ║               ⋮            ⋮                       ║  ║ −0.03 Δ/мин║ │
│  ║               ⋮            ⋮                       ║  ╚════════════╝ │
│  ║                                                    ║                  │
│  ║                                                    ║  row 2..3 (col 5..8) │
│  ║                                                    ║  R_thermal mini plot │
│  ║                                                    ║  ╔════════════╗ │
│  ║                                                    ║  ║ [mini plot]║ │
│  ╚═══════════════════════════════════════════════════╝  ╚════════════╝ │
│                                                                         │
│  row 4 (col 0..8):  Vacuum trend section                                │
│  ╔═══════════════════════════════════════════════════════════════════╗  │
│  ║  Прогноз вакуума — 10⁻⁶ мбар через ~2ч 30мин                      ║  │
│  ║  [compact log-Y plot]                                             ║  │
│  ╚═══════════════════════════════════════════════════════════════════╝  │
└─────────────────────────────────────────────────────────────────────────┘
```

BentoGrid placement table:

| Tile | `row` | `col` | `row_span` | `col_span` |
|---|---|---|---|---|
| Hero ETA+phase+progress | 0 | 0 | 1 | 8 |
| Cooldown trajectory plot | 1 | 0 | 3 | 5 |
| R_thermal metric tile | 1 | 5 | 1 | 3 |
| R_thermal mini plot | 2 | 5 | 2 | 3 |
| Vacuum trend section | 4 | 0 | 1 | 8 |

Total grid: 5 rows × 8 columns. No overlaps (validated by BentoGrid
per AD-001).

## Parts

### Hero ETA card

**Purpose.** Answer the one question the operator opens Analytics for:
«когда эксперимент станет возможен».

- **ETA value** (`FONT_DISPLAY_*`): 7ч 20мин ±45мин. Format from
  `_format_eta(t_hours, ci_hours)` — preserve the existing function.
- **Phase label** (`FONT_TITLE_*`): Фаза 1 (295K→50K) / Переход (S-bend) /
  Фаза 2 (50K→4K) / Стабилизация / Завершено.
- **Progress bar** (`QProgressBar` with custom QSS): overall cooldown
  progress 0..100% (0% = cooldown start, 100% = target temperature
  reached). Use `ACCENT` fill, `SURFACE_SUNKEN` track.
- **Confidence interval** rendered inline with ETA as `±NNмин` in
  `MUTED_FOREGROUND`.

Background: `SURFACE_CARD`. Border: 1px `BORDER`. Radius: `RADIUS_LG` (8).
Padding: `SPACE_5` (24).

### Cooldown trajectory plot

**Purpose.** Visual sanity check — is cooldown going as predicted?

Single `pg.PlotWidget`, styled via `apply_plot_style()`.

- **X axis:** hours from cooldown start (linear).
- **Y axis:** temperature in K, linear. Fixed axis range from start
  temperature (~300 K) down to target (~4 K). Overshoots outside this
  range are informative and rendered as-is — do not autoscale.
- **Actual line:** `PLOT_LINE_PALETTE[0]`, width `PLOT_LINE_WIDTH`,
  label «Измерено».
- **Predicted line:** `PLOT_LINE_PALETTE[1]`, width `PLOT_LINE_WIDTH`,
  dashed style (`Qt.DashLine`), label «Прогноз».
- **CI band:** filled region between `T_pred - ci` and `T_pred + ci`,
  using `warn_region_brush()` helper (PLOT_REGION_WARN_ALPHA).
- **Phase boundaries:** vertical dashed lines at phase transition
  times provided by the cooldown predictor meta. Style:
  `PLOT_GRID_COLOR`, `Qt.DashLine`. Do not hardcode boundary
  temperatures — predictor defines them.
- **Legend:** in upper-right, inside plot area.
- **Grid:** default `PLOT_GRID_ALPHA`.

No hover tooltips in v1 (deferred). Plot is display-only.

### R_thermal metric tile

**Purpose.** Current thermal resistance readout + short-term trend indicator.

- **Current value** (`FONT_MONO_VALUE_SIZE`): `12.3 K/W` or dash if
  not computed yet. 3-decimal precision per RULE-DATA-004.
- **Delta indicator** (`FONT_LABEL_SIZE`, `MUTED_FOREGROUND`): Δ per
  minute. Positive = warming, negative = cooling.
- **Stale state:** if last R_thermal computation > 60s ago, show
  `STATUS_STALE` color and suffix «(устар.)» per RULE-A11Y-003.

### R_thermal mini plot

**Purpose.** 10-minute history of R_thermal for quick regression spotting.

Small `pg.PlotWidget` styled via `apply_plot_style()`. Single series,
`PLOT_LINE_PALETTE[0]`. No legend (single series). Smaller axis tick
fonts (use `FONT_LABEL_SIZE - 2`).

### Vacuum trend section

**Purpose.** Reuse / re-embed `VacuumTrendPanel` — vacuum prediction
is a distinct analytics output, not part of cooldown.

**B.8 scope note.** VacuumTrendPanel itself is not rewritten in B.8;
AnalyticsPanel simply hosts the existing widget inside a tile frame.
Bringing VacuumTrendPanel into design-system alignment
(`apply_plot_style()`, Cyrillic мбар axis label per RULE-COPY-006,
log Y per RULE-DATA-008) is tracked as a separate follow-up within
Phase II. Until then, document the temporary divergence in the B.8
implementation-status callout.

## States

| State | Hero ETA | Cooldown plot | R_thermal | Vacuum |
|---|---|---|---|---|
| **No cooldown started** | «Охлаждение не активно» | empty plot + placeholder | «—» | last-known data + «Ожидание» overlay |
| **Phase 1 (295→50 K)** | ETA + «Фаза 1» | actual line + predicted | updates if heater on | normal |
| **Transition (S-bend)** | ETA + «Переход» | both lines + CI band | updates | normal |
| **Phase 2 (50→4 K)** | ETA + «Фаза 2» | full content | updates | normal |
| **Stabilizing** | «~5мин до цели» + «Стабилизация» | narrow CI | updates | normal |
| **Complete** | «Завершено, Nч Mмин» | full trajectory frozen | final value | final value |
| **Fault** | ETA + border STATUS_FAULT | plot + border STATUS_FAULT | no change | no change |

The **Fault** state does not hide analytics — operators need to see
what the system was doing when the fault happened. Only chrome changes
(border color per RULE-COLOR-002).

Stale data rendering per RULE-DATA-005: value stays in `FOREGROUND`,
stale signal via border + «(устар.)» suffix, never by dimming the
value itself (fails AA contrast).

## Invariants

1. **Full-screen overlay.** Analytics is always opened as a modal
   overlay via ModalCard, never as a dashboard tile embedded in the
   main view. Opened from ToolRail slot «analytics» (Ctrl+A).

2. **Single instance.** Only one Analytics overlay open at a time.
   Ctrl+A while already open does nothing (focus the existing one).

3. **No raw sensor data.** Analytics displays computed metrics only.
   Raw T_cold trajectory displayed is the output of a smoothing pass
   in the plugin, not direct sensor readings.

4. **мбар in operator-facing prose** (RULE-COPY-006). Axis label,
   hero text for vacuum. Latin `mbar` allowed in code identifiers
   (`value_mbar`).

5. **Cyrillic Т for channel references** (RULE-COPY-001). R_thermal
   is computed from a channel pair defined by the experiment template
   (typically a stage temperature channel and a heater path reference);
   the source channels are surfaced only in tooltips / extended details,
   not the main tile.

6. **Respect STATUS_OK/WARNING/CAUTION/FAULT semantics** per RULE-COLOR-002.
   No STATUS_* colors used for plot series — plot uses `PLOT_LINE_PALETTE`.

7. **Plots use `apply_plot_style()`** — no hardcoded colors or widths.

8. **Keyboard navigation.** Tab cycles: Back breadcrumb → hero card
   (if interactive) → plot area (focus ring only) → R_thermal → vacuum.
   Escape closes the overlay (RULE-INTER-002).

9. **No emoji** in status indicators (RULE-COPY-005). Text labels only.

10. **Hero card is the dominant visual anchor.** ETA readout uses
    `FONT_DISPLAY_SIZE` (largest). Operator reading from across the
    room must see the time remaining.

## API (proposed)

```python
# src/cryodaq/gui/shell/overlays/analytics_panel.py

from dataclasses import dataclass
from collections import deque
from PySide6.QtCore import Signal
from cryodaq.gui.shell.overlays._design_system.modal_card import ModalCard
from cryodaq.gui._plot_style import apply_plot_style, series_pen, warn_region_brush


@dataclass
class CooldownData:
    """Snapshot of cooldown predictor output."""
    t_hours: float          # ETA in hours
    ci_hours: float         # Confidence interval ±hours
    phase: str              # "phase1" | "transition" | "phase2" | "stabilizing" | "complete"
    progress_pct: float     # 0..100
    actual_trajectory: list[tuple[float, float]]  # [(hours_elapsed, T_K), ...]
    predicted_trajectory: list[tuple[float, float]]
    ci_trajectory: list[tuple[float, float, float]]  # [(h, T_lower, T_upper), ...]


@dataclass
class RThermalData:
    """Thermal resistance snapshot."""
    current_value: float | None      # K/W, None if not computed yet
    delta_per_minute: float | None
    last_updated_ts: float           # unix timestamp
    history: list[tuple[float, float]]  # 10-min [(ts, K/W), ...]


class AnalyticsPanel(ModalCard):
    """Full-screen analytics overlay (B.8)."""

    def set_cooldown(self, data: CooldownData | None) -> None: ...
    def set_r_thermal(self, data: RThermalData | None) -> None: ...
    def set_fault(self, faulted: bool, reason: str = "") -> None: ...

    # Inherited from ModalCard: focus trap, focus restoration, Escape to close
```

Data flow: engine publishes cooldown + R_thermal snapshots via ZMQ;
parent shell (main_window_v2.py) subscribes and calls `set_cooldown()`
/ `set_r_thermal()` on the panel instance. Panel does not subscribe
to ZMQ directly.

## Variants

**Dashboard tile variant (deferred).** A compact 2-col × 2-row tile
showing only ETA + phase could live on the main dashboard for
at-a-glance info. Would reuse Hero ETA rendering logic. Not in B.8
scope — revisit if operators ask for it.

## Common mistakes

1. **Computing metrics in the widget.** Analytics displays results
   from `analytics/` plugins. Do not compute R_thermal or cooldown
   prediction inside `AnalyticsPanel`. The widget is presentation only.

2. **Using STATUS_OK for "cooldown normal" chrome.** Cooldown running
   as expected is the default state — don't green-light it. Reserve
   STATUS_OK for confirmed-healthy indicators (heater-off, safety SAFE).

3. **Scaling Y axis on every update.** Axis autoscale during active
   cooldown causes the plot to "jump" and breaks operator's visual
   comparison. Fix Y axis to the expected range (start..target) and
   let actual data exceed it if it does; the overshoot is informative.

4. **Hiding the plot when no data yet.** Placeholder should be the
   empty plot with axis labels visible, not a replaced widget. The
   operator's eye locks onto the plot location; hiding and later
   re-showing is jarring.

5. **Putting vacuum trend at the top.** Vacuum is tertiary info.
   Hero + cooldown + R_thermal before vacuum — F-pattern reading order.

6. **Adding hover tooltips that show raw numbers.** Tooltip text
   under pyqtgraph is hard to style consistently with design system
   tokens. Defer to v2 iteration.

## Accessibility

- Focus trap: inherited from `ModalCard` (A.5 commit).
- Tab order: breadcrumb → hero card → plot area → R_thermal → vacuum.
- Escape closes overlay; focus returns to ToolRail slot that opened it
  (RULE-INTER-002 via ModalCard).
- Plot focus ring: 2px `ACCENT` border when focused (per RULE-A11Y-001).
  Keyboard users can tab to plot area but cannot interact with series
  inside (display-only).
- Color-independent state signaling per RULE-A11Y-002: phase label
  always shown in text, never just color; R_thermal stale state shown
  with «(устар.)» text suffix, not only color.
- Large-text readout (hero ETA) gives poor-vision operators the
  critical info at distance.

## Rule references

- RULE-A11Y-001 — focus indicators
- RULE-A11Y-002 — multi-channel redundancy
- RULE-A11Y-003 — contrast on status colors
- RULE-COLOR-002 — STATUS_* semantic locks
- RULE-COLOR-004 — ACCENT reserved for selection/focus
- RULE-COPY-001 — Cyrillic Т for channel IDs
- RULE-COPY-005 — no emoji
- RULE-COPY-006 — мбар canonical
- RULE-DATA-004 — fixed precision per quantity
- RULE-DATA-005 — stale rendering never dims value
- RULE-DATA-008 — pressure log scale
- RULE-INTER-002 — focus restoration
- RULE-SURF-001..007 — card invariants
- AD-001 — BentoGrid 8 columns canonical
- AD-002 — mnemonic shortcut Ctrl+A

## Related specs

- `components/modal.md` — overlay chrome base
- `components/bento-grid.md` — 8-col composition
- `cryodaq-primitives/phase-stepper.md` — phase concept (related but not reused here)
- `tokens/chart-tokens.md` — all 12 PLOT_* tokens
- `tokens/keyboard-shortcuts.md` — Ctrl+A binding

## Changelog

- 2026-04-17: Initial spec. Written for B.8 rebuild. Legacy v1 at
  `src/cryodaq/gui/widgets/analytics_panel.py` (518 lines) preserves
  domain logic and is the reference implementation for the plugin
  integration patterns referenced above. v2 replaces the QVBoxLayout
  + side-by-side cards layout with BentoGrid 8-col composition,
  adopts design-system tokens via `apply_plot_style()`, switches axis
  labels to мбар (Cyrillic), and integrates into the ModalCard
  overlay system instead of being a dashboard tab.
