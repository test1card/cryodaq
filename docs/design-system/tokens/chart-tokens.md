---
title: Chart Tokens
keywords: chart, plot, pyqtgraph, axis, grid, line, palette, series, region, log-scale
applies_to: all chart widgets using pyqtgraph
enforcement: strict
priority: high
last_updated: 2026-04-17
status: canonical
---

# Chart Tokens

Tokens for pyqtgraph-based plots. These are chart-specific and should NOT be used outside plot contexts. Using `PLOT_BG` as a tile background is wrong — use `SURFACE_CARD` instead (they resolve to different values, but semantic mismatch is the issue).

Total: **12 PLOT_* tokens** — 5 color tokens (`PLOT_BG`, `PLOT_FG`, `PLOT_TICK_COLOR`, `PLOT_LABEL_COLOR`, `PLOT_GRID_COLOR`) + 1 line palette (`PLOT_LINE_PALETTE`, 8 hues) + 3 alpha tokens (`PLOT_GRID_ALPHA`, `PLOT_REGION_WARN_ALPHA`, `PLOT_REGION_FAULT_ALPHA`) + 2 line-width tokens (`PLOT_LINE_WIDTH`, `PLOT_LINE_WIDTH_HIGHLIGHTED`) + 1 layout token (`PLOT_AXIS_WIDTH_PX`). Counted from `src/cryodaq/gui/theme.py`.

## Plot surfaces

| Token | Resolves to | Hex | Use |
|---|---|---|---|
| `PLOT_BG` | `BACKGROUND` | `#0d0e12` | Chart background (same as app viewport — plot blends into dashboard) |
| `PLOT_FG` | `MUTED_FOREGROUND` | `#8a8f9b` | Legend text, default foreground |

Plot background matches viewport background deliberately — charts don't have their own surface elevation, they are part of the dashboard canvas.

## Axis elements

| Token | Resolves to | Hex | Use |
|---|---|---|---|
| `PLOT_TICK_COLOR` | `FOREGROUND` | `#e8eaf0` | Axis tick marks — full contrast for critical readability |
| `PLOT_LABEL_COLOR` | `MUTED_FOREGROUND` | `#8a8f9b` | Axis labels (numeric values) — secondary emphasis |

**Deliberate asymmetry:** tick marks use FOREGROUND (high contrast), labels use MUTED_FOREGROUND (softer). The tick mark is the precise reference point; the label is annotation. Viewer sees the grid clearly, reads labels when needed.

## Grid

| Token | Value | Use |
|---|---|---|
| `PLOT_GRID_COLOR` | `BORDER = #2d3038` | Grid line color |
| `PLOT_GRID_ALPHA` | `0.35` | Grid line opacity |

Combined effective grid line: `#2d3038` at 35% alpha on `#0d0e12` background. Subtle — visible enough to reference, not dominant enough to distract from data.

## Threshold region overlays

For plots that show warning/fault thresholds as colored bands:

| Token | Value | Use |
|---|---|---|
| `PLOT_REGION_WARN_ALPHA` | `0.12` | Warning region overlay opacity (STATUS_WARNING color) |
| `PLOT_REGION_FAULT_ALPHA` | `0.15` | Fault region overlay opacity (STATUS_FAULT color) |

Fault region slightly more opaque (`0.15` vs `0.12`) — fault is more important to see, needs stronger visual presence.

Usage:

```python
import pyqtgraph as pg

# Warning region (temperature above warn threshold)
warn_region = pg.LinearRegionItem(
    values=[warn_threshold, max_plot_value],
    brush=pg.mkBrush(
        QColor(theme.STATUS_WARNING).lighter(),
        alpha=int(255 * theme.PLOT_REGION_WARN_ALPHA)
    ),
    movable=False,
)
plot.addItem(warn_region)

# Fault region (above fault threshold)
fault_region = pg.LinearRegionItem(
    values=[fault_threshold, max_plot_value],
    brush=pg.mkBrush(
        QColor(theme.STATUS_FAULT).lighter(),
        alpha=int(255 * theme.PLOT_REGION_FAULT_ALPHA)
    ),
    movable=False,
)
plot.addItem(fault_region)
```

## Line palette

`PLOT_LINE_PALETTE` — array of 8 hex values for multi-series plots.

| Index | Hex | Visual description | Semantic hint |
|---|---|---|---|
| 0 | `#5b8db8` | Cold blue (COLD_HIGHLIGHT) | Default first series, often temperature |
| 1 | `#9b7bb8` | Dusty purple | Second series |
| 2 | `#5fa090` | Teal green | Third series, cool tone |
| 3 | `#a3b85b` | Olive yellow | Fourth series, warm tone |
| 4 | `#c4862e` | Warning amber (STATUS_WARNING) | Fifth series, reusable for warning context |
| 5 | `#b88a5b` | Ochre brown | Sixth series |
| 6 | `#b87b9b` | Dusty rose | Seventh series |
| 7 | `#7c8cff` | Periwinkle (ACCENT) | Eighth series, cool tone |

All 8 colors share ~60% saturation ceiling — consistent with desaturated palette. No pure primaries.

**Palette supports up to 8 concurrent series.** For plots with >8 series, wrap the palette and differentiate via line dash pattern or marker shape, never by reintroducing primary-saturation colors.

Code pattern:

```python
for i, series_data in enumerate(series_list):
    color = theme.PLOT_LINE_PALETTE[i % len(theme.PLOT_LINE_PALETTE)]
    # If wrapping, use dash pattern for second cycle
    pen_style = Qt.PenStyle.SolidLine if i < 8 else Qt.PenStyle.DashLine
    plot.plot(
        series_data.x, series_data.y,
        pen=pg.mkPen(color, width=2, style=pen_style),
        name=series_data.label,
    )
```

See `rules/data-display-rules.md` RULE-DATA-007 for multi-series color/style rules.

## Axis width

| Token | Value (px) | Use |
|---|---|---|
| `PLOT_AXIS_WIDTH_PX` | `60` | Reserved Y-axis width for numeric labels |

Width accommodates:
- 4-digit temperature (`293.15` — 6 chars + tick padding)
- Scientific notation pressure (`1.2e-6` — 6 chars + tick padding)
- Unit suffix if present (`K`, `мбар`)

Do not reduce below 60px — labels will clip. Do not expand — wastes plot area.

## Log-scale requirement for pressure

**Pressure plots MUST use log₁₀ scale, never linear.** Vacuum pressure spans 10+ orders of magnitude (atmospheric 10³ → UHV 10⁻⁹). Linear scale is uninterpretable.

Required pyqtgraph configuration for any pressure plot:

```python
# DESIGN: RULE-DATA-008 (pressure log scale)
pressure_plot = pg.PlotWidget()
pressure_plot.setLogMode(x=False, y=True)  # Y axis log
pressure_plot.setLabel('left', 'Давление', units='мбар')

# When plotting, pass raw pressure values — pyqtgraph handles log conversion
pressure_plot.plot(time_x, pressure_y, ...)  # NOT log10(pressure_y)
```

Or if manually computing:

```python
# Pressure stored and displayed as log10(P), never raw P in chart data
chart_y = np.log10(pressure_values)
```

See `cryodaq-primitives/` (vacuum-related panels) and `rules/data-display-rules.md` RULE-DATA-008.

## PlotWidget setup pattern

Standard initialization for CryoDAQ plots:

```python
import pyqtgraph as pg
from PySide6.QtGui import QColor
from cryodaq.gui import theme

# DESIGN: RULE-DATA-010 (plot setup)
plot = pg.PlotWidget()

# Background and foreground
plot.setBackground(theme.PLOT_BG)
plot.getAxis('bottom').setPen(pg.mkPen(theme.PLOT_TICK_COLOR))
plot.getAxis('left').setPen(pg.mkPen(theme.PLOT_TICK_COLOR))
plot.getAxis('bottom').setTextPen(pg.mkPen(theme.PLOT_LABEL_COLOR))
plot.getAxis('left').setTextPen(pg.mkPen(theme.PLOT_LABEL_COLOR))

# Grid
plot.showGrid(x=True, y=True, alpha=theme.PLOT_GRID_ALPHA)

# Reserve axis width
plot.getAxis('left').setWidth(theme.PLOT_AXIS_WIDTH_PX)

# Fixed font for labels
font = QFont(theme.FONT_MONO, theme.FONT_MONO_SMALL_SIZE)
font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
plot.getAxis('bottom').setTickFont(font)
plot.getAxis('left').setTickFont(font)
```

This pattern is used by all CryoDAQ plot widgets. Helper function candidate — see `governance/contribution.md` (future utility `cryodaq.gui.plot_utils.configure_plot()`).

## Anti-patterns

- **Using `STATUS_OK` / `STATUS_FAULT` directly as line colors** — status colors carry semantic meaning. Use `PLOT_LINE_PALETTE` for data series.
- **Linear scale for pressure** — uninterpretable, see RULE-DATA-008
- **Chart with own surface elevation** — charts are flat on viewport, no card background
- **Grid alpha > 0.5** — grid dominates data
- **Axis labels at full FOREGROUND contrast** — labels are annotation, not data

See `ANTI_PATTERNS.md#charts`.

## Rule references

- `RULE-DATA-007` — Multi-series color palette wrapping (`rules/data-display-rules.md`)
- `RULE-DATA-008` — Pressure log-scale mandatory (`rules/data-display-rules.md`)
- `RULE-DATA-010` — Standard plot setup pattern (`rules/data-display-rules.md`)

## Related files

- `tokens/colors.md` — base color tokens
- `tokens/typography.md` — `FONT_MONO_SMALL_*` for axis labels
- `rules/data-display-rules.md` — data presentation rules
- `components/chart-tile.md` — ChartTile widget spec
- `cryodaq-primitives/` — domain-specific chart panels

## Changelog

- 2026-04-17: Initial version from theme.py inventory.
- 2026-04-17 (v1.0.1): Recounted PLOT_* tokens against theme.py — total is 12 (5 color + 1 palette + 3 alpha + 2 line-width + 1 layout). Earlier "9 + 1 = 10" undercounted line-width tokens and conflated the line palette with the color set (FR-019). Switched operator-facing axis-label example from `mbar` to `мбар` (FR-016).
