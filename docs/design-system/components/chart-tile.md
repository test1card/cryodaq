---
title: ChartTile
keywords: chart, plot, pyqtgraph, sparkline, time-series, graph, tile, live
applies_to: BentoTile variant displaying pyqtgraph plot content
status: partial
implements: ad-hoc plot widgets in legacy dashboard and experiment overlay
last_updated: 2026-04-17
---

# ChartTile

Specialized `BentoTile` containing a pyqtgraph plot. For live time-series, sparklines, and multi-axis technical charts on the dashboard.

**When to use:**
- Live temperature/pressure trends on dashboard (multi-channel time-series)
- Sparkline summary of a single channel over last N minutes
- Correlation plot between two measured quantities
- Historical replay when reviewing past experiment data

**When NOT to use:**
- Static image or diagram — use `QLabel` with pixmap
- Bar chart / pie chart — pyqtgraph is overkill; use Qt Charts or custom widget
- Table of numeric values — use `QTableView`, not a chart
- Single numeric readout — use `ExecutiveKpiTile` (subclass of BentoTile)
- 3D visualization — pyqtgraph 2D only; for 3D use separate component

## Anatomy

```
┌────────────────────────────────────────────────────────────┐
│ ◀── BentoTile frame (SURFACE_CARD, RADIUS_MD, CARD_PADDING)│
│                                                            │
│  ┌────────────────────────────────────────────────────┐    │
│  │ ДИНАМИКА ТЕМПЕРАТУР     Т1 — Т14  |  последние 60с │    │  ← title + legend/meta
│  └────────────────────────────────────────────────────┘    │
│                                                            │
│  ┌────────────────────────────────────────────────────┐    │
│  │                                                    │    │
│  │  ╱╲                                                │    │
│  │ ╱  ╲__╱╲_                                          │    │
│  │       ╱  ╲___╱╲                                    │    │
│  │                                                    │    │  ← pyqtgraph PlotWidget
│  │ 100 ┼─────────────────────────────                 │    │
│  │  10 ┼─────────────────────────────                 │    │
│  │   1 ┼─────────────────────────────                 │    │
│  │     └──────────────────────────────────────────────│    │
│  │       -60с  -45с  -30с  -15с  сейчас               │    │
│  └────────────────────────────────────────────────────┘    │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Tile frame** | Yes | Inherited from BentoTile (single surface, RADIUS_MD, CARD_PADDING) |
| **Title row** | Yes | UPPERCASE category + optional legend summary / time range hint |
| **PlotWidget** | Yes | `pyqtgraph.PlotWidget` configured per chart-tokens rules |
| **Cursor tooltip** | Optional | On hover, show value at cursor position |
| **Empty state** | Conditional | "Нет данных" placeholder when no series yet |
| **Loading state** | Optional | Skeleton or spinner during initial data fetch |

## Invariants

1. **Inherits BentoTile invariants.** Must be a BentoGrid child; single surface; symmetric CARD_PADDING; RADIUS_MD.
2. **Plot uses standard pyqtgraph setup.** Dark background matching BACKGROUND (not CARD — plot's internal background is the "deeper" surface), FONT_MONO_SMALL axis labels, PLOT_LINE_PALETTE for series. (RULE-DATA-010)
3. **Pressure plots mandatory log scale.** Any plot displaying pressure values MUST use `setLogMode(x=False, y=True)`. (RULE-DATA-008)
4. **Multi-series uses PLOT_LINE_PALETTE with wrapping.** Don't arbitrarily assign colors; iterate through palette. (RULE-DATA-007)
5. **No animation on live data.** Updates snap. No tweening. (RULE-DATA-009, RULE-INTER-006)
6. **Update rate ≤ 2Hz.** (RULE-DATA-002)
7. **Tabular numbers on axis labels.** Monospace axis text to prevent jitter. (RULE-DATA-003, RULE-TYPO-003)
8. **Fixed plot axis width.** `setWidth(PLOT_AXIS_WIDTH_PX)` on y-axis to prevent width drift as value range changes. (RULE-DATA-003)
9. **No interactive pan/zoom on dashboard tiles.** Dashboard plots are summaries. Full interactivity belongs in dedicated analytics view. Set `setMouseEnabled(False, False)` on dashboard chart tiles.
10. **Cursor tooltip uses color-aware readout.** When hovering, show value with appropriate status color if value is in fault range.

## API (proposed)

```python
# src/cryodaq/gui/widgets/chart_tile.py  (proposed)

@dataclass
class PlotSeries:
    key: str                        # unique identifier
    label: str                      # display name ("Т1", "Давление", ...)
    color: str | None = None        # if None, auto from palette
    width: int | None = None        # defaults to PLOT_LINE_WIDTH

class ChartTile(BentoTile):
    """BentoTile containing a pyqtgraph plot."""
    
    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        *,
        y_log: bool = False,        # mandatory True for pressure (RULE-DATA-008)
        y_label: str = "",
        y_unit: str = "",           # "K", "мбар" — displayed on axis
        time_window_s: float = 60,
        max_points: int = 600,      # @ 2Hz, 300s worth
    ) -> None: ...
    
    def register_series(self, series: PlotSeries) -> None: ...
    def push_sample(self, series_key: str, t: float, value: float) -> None:
        """Append a new sample. Drops oldest if exceeds max_points."""
    def clear_series(self, series_key: str) -> None: ...
    def set_empty_message(self, message: str | None) -> None: ...
```

## Variants

### Variant 1: Multi-series temperature trend

Classic dashboard use — 14 temperature channels over 60 seconds.

```python
# DESIGN: RULE-DATA-007, RULE-DATA-010
tile = ChartTile(
    title="ДИНАМИКА ТЕМПЕРАТУР",
    y_log=False,
    y_label="",
    y_unit="K",
    time_window_s=60,
)

# Register 14 channels using palette wrapping
for i, channel in enumerate(cold_channels):  # Т1–Т14
    series = PlotSeries(
        key=channel.id,
        label=channel.display_name,
        color=None,  # auto from PLOT_LINE_PALETTE, wraps after 8
    )
    tile.register_series(series)

# Push samples
tile.push_sample("Т1", time.time(), 4.21)
tile.push_sample("Т2", time.time(), 4.15)
# ... etc
```

### Variant 2: Pressure plot (log scale mandatory)

Vacuum pressure spans ~10 orders of magnitude. Must be log-y.

```python
# DESIGN: RULE-DATA-008 (mandatory log scale for pressure)
tile = ChartTile(
    title="ДАВЛЕНИЕ",
    y_log=True,  # MANDATORY for pressure per RULE-DATA-008
    y_label="P",
    y_unit="мбар",
    time_window_s=300,  # 5 min
)

tile.register_series(PlotSeries(key="pressure_main", label="Основной", color=theme.PLOT_LINE_INFO))
```

### Variant 3: Single-channel sparkline

Compact minimal plot, often inside a LiveTile or next to an ExecutiveKpiTile.

```python
# Smaller chart tile with minimal chrome
tile = ChartTile(
    title="Т11",
    time_window_s=30,
    max_points=120,
)

tile.register_series(PlotSeries(
    key="t11",
    label="Т11",
    color=theme.PLOT_LINE_INFO,
))

# In sparkline mode, hide axes entirely for minimal chrome
plot = tile.get_plot_widget()
plot.getAxis('bottom').hide()
plot.getAxis('left').hide()
plot.setFixedHeight(80)
```

### Variant 4: Historical / archive playback

Plot shows data from past experiment, not live. No auto-scrolling; fixed time range.

```python
# DESIGN: same styling rules, but static data
tile = ChartTile(
    title="ЭКСПЕРИМЕНТ calibration_run_042",
    y_log=False,
    y_unit="K",
)
tile.set_static_mode(True)  # disables auto-scroll, shows full history

# Bulk load historical samples
historical_samples = load_from_archive(experiment_id)
for sample in historical_samples:
    tile.push_sample(sample.channel, sample.t, sample.value)
```

## Reference: pyqtgraph configuration

```python
# DESIGN: RULE-DATA-010 — standard pyqtgraph setup pattern

import pyqtgraph as pg
from cryodaq.gui import theme

def configure_plot_widget(plot: pg.PlotWidget) -> None:
    """Apply CryoDAQ design-language styling to a pyqtgraph PlotWidget."""
    
    # Background — slightly darker than tile surface for visual depth
    plot.setBackground(theme.PLOT_BACKGROUND)  # typically theme.BACKGROUND or specific PLOT_BG token
    
    # Grid — subtle, MUTED_FOREGROUND with low alpha
    plot.showGrid(x=True, y=True, alpha=0.15)
    
    # Axis styling
    for axis_name in ('left', 'bottom'):
        axis = plot.getAxis(axis_name)
        axis.setPen(pg.mkPen(color=theme.BORDER, width=1))
        axis.setTextPen(pg.mkPen(color=theme.MUTED_FOREGROUND))
        # DESIGN: RULE-TYPO-003 (tnum) + RULE-DATA-003 (no jitter)
        font = QFont(theme.FONT_MONO, theme.FONT_MONO_SMALL_SIZE)
        font.setFeature("tnum", 1)
        font.setFeature("liga", 0)
        axis.setStyle(tickFont=font)
    
    # Y-axis fixed width to prevent reflow
    plot.getAxis('left').setWidth(theme.PLOT_AXIS_WIDTH_PX)
    
    # Disable interactive features for dashboard tiles
    plot.setMouseEnabled(x=False, y=False)
    plot.setMenuEnabled(False)
    plot.hideButtons()
    
    # No auto-range drift (we manage range explicitly per update)
    plot.enableAutoRange(axis='y', enable=False)
```

## Palette assignment

```python
# DESIGN: RULE-DATA-007
def _assign_series_color(self, series_index: int) -> str:
    palette = theme.PLOT_LINE_PALETTE  # list of 8 hex strings
    return palette[series_index % len(palette)]
```

Never add arbitrary colors beyond palette. If 10 channels and palette has 8, wrap: channels 9, 10 reuse colors 1, 2 (distinguishable by line style or legend if needed).

## Empty and loading states

```python
class ChartTile(BentoTile):
    def set_empty_message(self, message: str | None) -> None:
        """Show 'no data' placeholder or hide it."""
        if message is None:
            self._empty_label.setVisible(False)
            self._plot.setVisible(True)
        else:
            self._empty_label.setText(message)
            self._empty_label.setVisible(True)
            self._plot.setVisible(False)
    
    def set_loading(self, loading: bool) -> None:
        """Show loading spinner (typically for historical data fetch)."""
        ...
```

Empty state text: sentence case per RULE-COPY-003 — "Нет данных", "Ожидание первого измерения".

## Update flow

```python
# DESIGN: RULE-DATA-001 (atomic), RULE-DATA-002 (≤2Hz), RULE-DATA-009 (no animation)
class _SeriesBuffer:
    """Ring buffer of recent samples per series."""
    def __init__(self, max_points: int):
        self._t = deque(maxlen=max_points)
        self._v = deque(maxlen=max_points)
    
    def append(self, t: float, v: float) -> None:
        self._t.append(t)
        self._v.append(v)
    
    def arrays(self) -> tuple[np.ndarray, np.ndarray]:
        return np.fromiter(self._t, dtype=float), np.fromiter(self._v, dtype=float)

def push_sample(self, series_key: str, t: float, value: float) -> None:
    buffer = self._buffers[series_key]
    buffer.append(t, value)
    self._schedule_redraw()

def _schedule_redraw(self) -> None:
    """Coalesce redraws to ≤2Hz per RULE-DATA-002."""
    if self._redraw_timer.isActive():
        return
    self._redraw_timer.start(500)  # 2Hz = 500ms

def _redraw(self) -> None:
    now = time.time()
    t_cutoff = now - self._time_window_s
    
    for key, buffer in self._buffers.items():
        t_arr, v_arr = buffer.arrays()
        # Only draw points within time window
        mask = t_arr >= t_cutoff
        plot_item = self._plot_items[key]
        plot_item.setData(t_arr[mask] - now, v_arr[mask])  # x = relative seconds
```

## Cursor hover (optional)

```python
def _install_hover(self) -> None:
    self._plot.scene().sigMouseMoved.connect(self._on_mouse_moved)
    self._hover_label = QLabel()
    # position in top-right of plot area

def _on_mouse_moved(self, pos: QPointF) -> None:
    if not self._plot.sceneBoundingRect().contains(pos):
        self._hover_label.setVisible(False)
        return
    mouse_point = self._plot.plotItem.vb.mapSceneToView(pos)
    t = mouse_point.x()
    # Find nearest sample per series, show in hover label
    ...
```

## States

| State | Visual treatment |
|---|---|
| **Live streaming** | Default — plot shows last N seconds, latest on right edge |
| **Empty** | "Нет данных" centered text, plot hidden |
| **Loading historical** | Spinner overlay, plot dimmed |
| **Stale** (no updates for threshold) | Plot shown but dimmed + indicator "Последнее обновление: 14:32" |
| **Fault (channel in fault state)** | Specific series drawn with STATUS_FAULT color override; other series normal |

## Common mistakes

1. **Linear pressure scale.** Pressure spans 10 orders of magnitude. Linear axis makes low vacuum ranges unreadable. RULE-DATA-008 mandatory log.

2. **Animated transitions on data update.** pyqtgraph by default doesn't animate, but custom code can add tweening. Don't. RULE-DATA-009.

3. **Update rate >2Hz.** Calling `setData` on every sample at 50Hz burns CPU and makes values flicker. Coalesce to 2Hz. RULE-DATA-002.

4. **Variable-width y-axis.** Axis labels grow from "4" → "4.2" → "4.21" and plot area shifts horizontally. Fix width via `setWidth(PLOT_AXIS_WIDTH_PX)`. RULE-DATA-003.

5. **Proportional font on axis labels.** Digits shift. Use FONT_MONO with tnum. RULE-TYPO-003.

6. **Enabling mouse pan/zoom on dashboard tiles.** Operator accidentally scrolls, loses sync with other live tiles. Disable for dashboard; enable only in dedicated analytics view.

7. **Legend inside plot area.** pyqtgraph's in-plot legend obscures data. Put legend in tile header row instead ("Т1 — Т14").

8. **Arbitrary series colors.** Hardcoded `"#FF0000"` for channel X instead of using PLOT_LINE_PALETTE index. RULE-DATA-007, RULE-COLOR-001.

9. **No empty state.** Plot renders with no data, looks broken ("did it crash?"). Explicit "Нет данных" or "Ожидание первого измерения" makes state clear.

10. **Title sentence case.** "Динамика температур" — should be UPPERCASE "ДИНАМИКА ТЕМПЕРАТУР" per RULE-TYPO-008 (tile title = category label).

## Related components

- `components/bento-tile.md` — Parent category
- `components/bento-grid.md` — Where chart tiles live
- `tokens/chart-tokens.md` — Plot-specific tokens and pyqtgraph integration rules
- `patterns/real-time-data.md` — When to use charts vs numeric readouts vs sparklines

## Changelog

- 2026-04-17: Initial version. 4 variants (multi-series temperature, pressure log-scale, sparkline, historical). `ChartTile` class proposed — legacy dashboard uses ad-hoc pyqtgraph setup scattered; formalization Phase II follow-up including mandatory log-scale for pressure and standardized pyqtgraph configuration helper.
