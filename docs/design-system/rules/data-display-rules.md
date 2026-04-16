---
title: Data Display Rules
keywords: data, numeric, live, update, jitter, rate, stale, precision, units, log-scale, plot, pressure, sensor
applies_to: all widgets displaying real-time numeric data
enforcement: strict
priority: critical
last_updated: 2026-04-17
status: canonical
---

# Data Display Rules

Rules for displaying real-time numeric data — sensor readings, pressure, temperature, voltage, current. This is the domain core of CryoDAQ. Violations degrade operator trust in the readings, which is catastrophic for a safety-critical lab system.

Enforce in code via `# DESIGN: RULE-DATA-XXX` comment marker.

**Rule index:**
- RULE-DATA-001 — Data updates are atomic (snap, no interpolation)
- RULE-DATA-002 — Update rate ≤ 2Hz for human-readable values
- RULE-DATA-003 — No horizontal jitter on live numeric displays
- RULE-DATA-004 — Fixed numeric precision per quantity
- RULE-DATA-005 — Standard sensor reading format
- RULE-DATA-006 — Units always displayed next to values
- RULE-DATA-007 — Multi-series plots use PLOT_LINE_PALETTE with wrapping
- RULE-DATA-008 — Pressure plots mandatory log-scale
- RULE-DATA-009 — No animation on live data updates
- RULE-DATA-010 — Standard pyqtgraph setup pattern

---

## RULE-DATA-001: Data updates are atomic (snap, no interpolation)

**TL;DR:** Live sensor readings change INSTANTLY from old value to new value. No tweening, no smooth transitions, no "counting up." Snap.

**Statement:** When a sensor reading updates from 4.21 K to 4.30 K, the displayed value changes in one frame. Do not animate the transition through 4.22, 4.23, 4.24... Live data is discrete measurements, not continuous state.

**Rationale:** Animated number-counting (common in dashboard marketing UIs) is lying in a lab context. Operator seeing "4.27 K" during the animation might record or act on that value — but it was never actually measured. Only 4.21 and 4.30 existed as real measurements. Interpolation invents data that didn't exist.

Operator trust: once an operator sees Claude's UI animate numbers, they permanently doubt every reading is real vs animated.

**Applies to:** SensorCell, Keithley value displays, pressure readout, all numeric live data

**Example (good):**

```python
# DESIGN: RULE-DATA-001
def update_sensor_value(self, value: float):
    # Instant snap — no animation
    self._value_label.setText(f"{value:.2f}")
```

**Example (bad):**

```python
# Counting animation — lies about intermediate values
def update_sensor_value(self, value: float):
    start = self._current_value
    anim = QPropertyAnimation(self, b"animated_value")
    anim.setStartValue(start)
    anim.setEndValue(value)
    anim.setDuration(500)
    anim.valueChanged.connect(
        lambda v: self._value_label.setText(f"{v:.2f}")
    )
    anim.start()  # WRONG — displays fake intermediate values
```

**Exception:** Chart line segments MAY draw smoothly between data points (pyqtgraph default behavior) — the line is visually connecting two known points, not inventing between-point values. The numeric readout next to the plot snaps; the line interpolates visually.

**Related rules:** RULE-DATA-009 (no animation), RULE-INTER-006 (faults instant)

---

## RULE-DATA-002: Update rate ≤ 2Hz for human-readable values

**TL;DR:** Don't refresh displayed numbers faster than 2 times per second. Human eye can't read faster; more is noise.

**Statement:** Live numeric displays refresh at most at 2Hz (every 500ms). Backend may poll sensors at higher rates (LakeShore supports 10Hz), but GUI display is throttled. Charts may update at higher rate (line drawing perception tolerates 10Hz+), but their associated numeric readouts throttle.

**Rationale:** At rates above ~3Hz, digits change faster than human eye tracks. Operator sees a blur, not a value. Also wasteful: a 2Hz update of 30 sensor cells is 60 repaint ops/sec; 10Hz is 300 ops/sec for no perceptible benefit.

Charts are different: the line has shape; a shape updating at 10Hz is still readable as trend.

**Applies to:** SensorCell, numeric readouts, TopWatchBar values, Keithley displays

**Example (good):**

```python
# DESIGN: RULE-DATA-002
# GUI-side throttle: backend may push at any rate, GUI renders at 2Hz
class SensorCell(QWidget):
    MIN_UPDATE_INTERVAL_MS = 500  # 2Hz max
    
    def __init__(self):
        super().__init__()
        self._pending_value: float | None = None
        self._last_update_time = 0
    
    def receive_value(self, value: float):
        """Called from backend — may be 10Hz, throttles here."""
        self._pending_value = value
        now = time.monotonic() * 1000
        if now - self._last_update_time >= self.MIN_UPDATE_INTERVAL_MS:
            self._apply_pending()
    
    def _apply_pending(self):
        if self._pending_value is not None:
            self._value_label.setText(f"{self._pending_value:.2f}")
            self._last_update_time = time.monotonic() * 1000
            self._pending_value = None
```

**Example (bad):**

```python
# Every backend message → immediate repaint, 10Hz+
def receive_value(self, value: float):
    self._value_label.setText(f"{value:.2f}")  # WRONG — no throttle
```

**Exception:** Chart widgets (pyqtgraph) may update at up to `PLOT_UPDATE_RATE_HZ` (see `tokens/chart-tokens.md`) — trend shape perception tolerates higher rates than digit reading.

**Related rules:** RULE-DATA-009 (no animation), RULE-DATA-010 (plot setup)

---

## RULE-DATA-003: No horizontal jitter on live numeric displays

**TL;DR:** Live numeric display MUST use tabular figures (`tnum`) so "4.21" → "4.30" doesn't shift adjacent content horizontally by 1-2px.

**Statement:** Widgets displaying live-updating numbers MUST enable OpenType `tnum` feature on the font (see RULE-TYPO-003). This renders all digit glyphs at equal width, preventing layout shift when values change.

Fira Code (FONT_MONO, FONT_DISPLAY) has tnum by default. Fira Sans (FONT_BODY, FONT_LABEL) requires explicit activation.

**Rationale:** Operator scans 20 sensor cells reading values. If each cell's digits twitch horizontally as values update, operator's eye cannot lock onto stable reading point. Tabular digits keep layout rock-steady.

This is RULE-TYPO-003 restated from the data-display perspective — same rule, same enforcement, cross-category critical.

**Applies to:** SensorCell, numeric readouts, timestamps, counters, percentage displays

**Example (good):**

```python
# DESIGN: RULE-DATA-003
# Sensor value using Fira Code — tnum default, safe
value_font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
value_font.setWeight(theme.FONT_MONO_VALUE_WEIGHT)
value_font.setFeature("tnum", 1)  # explicit for safety
value_label.setFont(value_font)
```

```python
# Percentage in body context — explicit tnum on Fira Sans
percent_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_BASE)
percent_font.setWeight(theme.FONT_WEIGHT_MEDIUM)
percent_font.setFeature("tnum", 1)  # MANDATORY for proportional font + numbers
percent_label.setFont(percent_font)
```

**Example (bad):**

```python
# Live value in Fira Sans without tnum
value_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_BASE)
value_label.setFont(value_font)
# Updates every 500ms: "4.21" → "4.30" twitches horizontally
```

**Related rules:** RULE-TYPO-003 (same rule, typography perspective), RULE-DATA-001 (atomic updates)

---

## RULE-DATA-004: Fixed numeric precision per quantity

**TL;DR:** Temperature = 2 decimals ("3.90 K"). Pressure = scientific with 2 mantissa digits ("1.23e-06 мбар"). Voltage = 3 decimals ("1.234 V"). Precision is per-quantity, constant.

**Statement:** Each measured quantity has a fixed display precision that does NOT change based on value magnitude. CryoDAQ convention:

| Quantity | Format | Examples |
|---|---|---|
| Temperature (K) | `{:.2f}` | `3.90`, `77.35`, `292.15`, `4.20` |
| Temperature (mK) for ultra-cold | `{:.1f}` | `15.3`, `4.2` |
| Pressure (мбар) | scientific 2 mantissa | `1.23e-06`, `8.75e-03` |
| Voltage (V) | `{:.3f}` | `0.125`, `12.300`, `-1.523` |
| Current (A) | `{:.6f}` for small, `{:.3f}` for large | `0.000123`, `1.234` |
| Power (W) | `{:.3f}` | `0.025`, `12.500` |
| Resistance (Ω) | `{:.1f}` | `150.0`, `1250.5` |

Use `theme.QUANTITY_FORMAT` dict lookups (proposed) rather than hardcoded format strings.

**Rationale:** Adaptive precision ("3 decimals below 10, 2 decimals above") creates reading ambiguity — "1.23" vs "1.234" looks like different measurements at a glance. Fixed precision is contract: the width of "temperature" column is always the same, scanning is predictable.

**Applies to:** all numeric value displays

**Example (good):**

```python
# DESIGN: RULE-DATA-004
def format_temperature(value_k: float) -> str:
    return f"{value_k:.2f}"  # always 2 decimals

def format_pressure(value_mbar: float) -> str:
    return f"{value_mbar:.2e}"  # always scientific, 2 mantissa digits

# Sensor cell
temperature_label.setText(format_temperature(value))  # "3.90", "77.35", etc
```

**Example (bad):**

```python
# Adaptive precision — inconsistent width
def format_value(value: float) -> str:
    if value < 1:
        return f"{value:.3f}"  # 0.123
    elif value < 100:
        return f"{value:.2f}"  # 45.67
    else:
        return f"{value:.1f}"  # 150.0
# WRONG — column width varies, scanning breaks

# Default str() — unpredictable precision
temperature_label.setText(str(value))  # "3.9", "3.901", "3.9012345" — WRONG
```

**Related rules:** RULE-DATA-005 (sensor reading format), RULE-DATA-006 (units)

---

## RULE-DATA-005: Standard sensor reading format

**TL;DR:** Sensor cell layout: `[Label]\n[Value] [Unit]`. Label in MUTED_FOREGROUND small. Value in FONT_MONO_VALUE. Unit in MUTED_FOREGROUND small.

**Statement:** SensorCell (and Keithley-like readouts) MUST follow standard layout:

```
Т11 (Криостат)
4.20 K
```

Structure:
- **Label row**: channel name in `FONT_LABEL_*` preset, `MUTED_FOREGROUND` color, left-aligned
- **Value row**: number in `FONT_MONO_VALUE_*` preset (15px Fira Code Medium), `FOREGROUND` or domain color (COLD_HIGHLIGHT for cold channels), left-aligned
- **Unit**: inline with value, `FONT_MONO_SMALL_*` preset, `MUTED_FOREGROUND`, single space separator

Variants for status:
- Normal: value in FOREGROUND
- Cold-domain channel: value in COLD_HIGHLIGHT
- Warning: value in FOREGROUND, add border-left in STATUS_WARNING
- Fault: value in FOREGROUND, border-left in STATUS_FAULT
- Stale sensor cells render:
  - Value text stays **FOREGROUND** (preserves contrast per RULE-A11Y-003)
  - Left border or subtle background tint in STATUS_STALE (shape channel)
  - Tooltip: «Данные не обновляются NN секунд» (text channel)
  - Unit text in MUTED_FOREGROUND (secondary text, AA-safe)

  Do NOT color the value itself in STATUS_STALE — it fails WCAG AA body
  contrast (2.94:1). The stale signal is carried by border + tooltip,
  not by value color.

**Rationale:** Consistent layout across 20+ sensor cells allows operator scanning. Eye locks into pattern: "label on top, value in middle, unit suffix." Breaking pattern (value-first, or unit-above-value) forces re-parsing per cell.

**Applies to:** SensorCell, KeithleyChannelReadout, any quantity-readout widget

**Example (good):**

```python
# DESIGN: RULE-DATA-005
class SensorCell(QFrame):
    def __init__(self, channel_id: str, channel_label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("sensorCell")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            theme.CARD_PADDING, theme.CARD_PADDING,
            theme.CARD_PADDING, theme.CARD_PADDING
        )
        layout.setSpacing(theme.SPACE_1)
        
        # Label row
        self._label = QLabel(f"{channel_id} ({channel_label})")
        label_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        label_font.setWeight(theme.FONT_LABEL_WEIGHT)
        self._label.setFont(label_font)
        self._label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        
        # Value + unit row
        value_row = QHBoxLayout()
        value_row.setSpacing(theme.SPACE_1)
        
        self._value = QLabel("—")
        value_font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
        value_font.setWeight(theme.FONT_MONO_VALUE_WEIGHT)
        value_font.setFeature("tnum", 1)
        value_font.setFeature("liga", 0)
        self._value.setFont(value_font)
        self._value.setStyleSheet(f"color: {theme.FOREGROUND};")
        
        self._unit = QLabel("K")
        unit_font = QFont(theme.FONT_MONO, theme.FONT_MONO_SMALL_SIZE)
        self._unit.setFont(unit_font)
        self._unit.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        
        value_row.addWidget(self._value)
        value_row.addWidget(self._unit)
        value_row.addStretch()
        
        layout.addWidget(self._label)
        layout.addLayout(value_row)
```

**Example (bad):**

```python
# Unit before value — nonstandard
layout.addWidget(QLabel("K"))       # unit row
layout.addWidget(QLabel("4.20"))    # value row

# Value without unit
value_label.setText("4.20")  # WRONG — no unit, ambiguous quantity
```

**Related rules:** RULE-DATA-003 (no jitter), RULE-DATA-004 (precision), RULE-DATA-006 (units)

---

## RULE-DATA-006: Units always displayed next to values

**TL;DR:** Every numeric value shown to operator MUST include its unit (K, мбар, V, A, W, Ω). No implicit units. No unit in header/column alone.

**Statement:** A number on screen without its unit is ambiguous. "4.20" means what? Kelvin? Volts? Amperes? CryoDAQ convention: always render unit inline with value.

Specifically forbidden:
- Column header "Temperature (K)" followed by rows of bare "4.20", "77.35", "292.15" — header separated from values breaks when scanning

Accepted simplification: one shared unit label per consistent column/row if visual proximity is tight (e.g., plot Y-axis label).

**Rationale:** Operator under stress scans columns looking for anomalies. Reading "4.20" in isolation requires memory lookup: "what's the unit for this column?" That lookup takes ~200ms under cognitive load — unacceptable for safety-critical scanning.

SI mandatory: K (not Kelvin or °K), мбар (not `mbar` — operator-facing canonical per RULE-COPY-006), V, A, W, Ω (not Ohm).

**Applies to:** all numeric displays — cells, tables, plots (axis labels), exports

**Example (good):**

```python
# DESIGN: RULE-DATA-006
# Sensor cell — unit next to value
value_row.addWidget(self._value)  # "4.20"
value_row.addWidget(self._unit)   # "K"
```

```python
# Inline value in prose
status_label.setText(f"Температура стабилизирована на {temp:.2f} K")

# Plot axis label
plot.getAxis('left').setLabel("Температура", units="K")
```

**Example (bad):**

```python
# Bare value — ambiguous
self._value_label.setText(f"{temp:.2f}")  # "4.20" — K? °C?

# Unit only in column header — breaks when scanning row
column_header.setText("Температура (K)")
for value in temps:
    row.addWidget(QLabel(f"{value:.2f}"))  # WRONG — bare value
```

**Related rules:** RULE-DATA-005 (reading format), RULE-COPY-006 (SI units only)

---

## RULE-DATA-007: Multi-series plots use PLOT_LINE_PALETTE with wrapping

**TL;DR:** Multi-trace plots MUST draw line colors from `theme.PLOT_LINE_PALETTE` (8 desaturated hues). For >8 traces, wrap palette + vary line dash pattern, not introduce new colors.

**Statement:** `PLOT_LINE_PALETTE` contains 8 colors selected for:
- Distinguishable hues at ~60% saturation ceiling
- All pass AA contrast on BACKGROUND
- Consistent with desaturated aesthetic (no bright primaries)

For plots with ≤8 traces, use colors in palette order. For 9+ traces:
1. Wrap palette (trace 9 reuses color 1)
2. Differentiate by line dash pattern (solid → dashed → dotted)
3. NEVER introduce new saturated colors to "get more distinction"

**Rationale:** Palette is calibrated for perceptual balance. Adding a bright pure color to reach trace 9 destroys balance — one trace visually dominates. Wrapping + dash distinction is the industry-standard approach (see matplotlib/seaborn conventions).

**Applies to:** pyqtgraph plots with multiple traces, custom multi-series charts

**Example (good):**

```python
# DESIGN: RULE-DATA-007
from cryodaq.gui import theme

def add_trace(self, plot: pg.PlotItem, index: int, data):
    palette = theme.PLOT_LINE_PALETTE  # 8 colors
    color = palette[index % len(palette)]
    # Dash pattern cycles every full palette wrap
    dash_cycle = index // len(palette)
    pen_styles = [Qt.PenStyle.SolidLine, Qt.PenStyle.DashLine, Qt.PenStyle.DotLine]
    style = pen_styles[dash_cycle % len(pen_styles)]
    
    pen = pg.mkPen(color=color, width=2, style=style)
    plot.plot(data, pen=pen, name=f"Т{index + 1}")
```

**Example (bad):**

```python
# Ad-hoc bright colors for additional traces
palette = theme.PLOT_LINE_PALETTE + ["#FF0000", "#00FF00", "#0000FF"]
# WRONG — introduces over-saturated primaries, breaks palette coherence
# ALSO violates RULE-COLOR-001 (raw hex)

# Single color for all traces — cannot distinguish
for i, trace in enumerate(traces):
    plot.plot(trace, pen=pg.mkPen(color=theme.FOREGROUND))  # WRONG — all same
```

**Related rules:** RULE-COLOR-001 (no raw hex), `tokens/chart-tokens.md`

---

## RULE-DATA-008: Pressure plots mandatory log-scale

**TL;DR:** Vacuum pressure plots MUST use logarithmic Y-axis (`log_y=True`). Raw linear scale makes low-pressure spans invisible.

**Statement:** Pressure measurements in CryoDAQ span 10+ orders of magnitude (atmospheric ~1000 mbar down to ultra-vacuum ~1e-9 mbar). On linear Y-axis, everything below 1 mbar compresses into a single pixel — entire vacuum regime invisible.

All pressure visualizations MUST:
1. Use pyqtgraph `setLogMode(y=True)` on the plot
2. Display Y-axis tick labels in scientific notation (`1e-6`, `1e-3`, etc.)
3. Store underlying data in raw mbar; conversion to log is display-only

Rationale embedded in `tokens/chart-tokens.md`. Vladimir's explicit memory: "Pressure always displayed and fitted in log scale (log₁₀(P), never raw P)."

**Rationale:** Linear pressure is operationally useless for vacuum work. Log-scale reveals the logarithmic decay during pumpdown, shows the flatline at base vacuum, and makes leak-detection visible (small linear changes = large log changes).

**Applies to:** pressure plots (vacuum, partial pressure), any span-wide measurement

**Example (good):**

```python
# DESIGN: RULE-DATA-008
import pyqtgraph as pg

plot = pg.PlotWidget()
plot.setLogMode(x=False, y=True)  # Y log, X linear time axis
plot.getAxis('left').setLabel("Давление", units="мбар")
plot.plot(timestamps, pressures_mbar, pen=pg.mkPen(theme.COLD_HIGHLIGHT))
```

**Example (bad):**

```python
# Linear Y — vacuum regime invisible
plot.setLogMode(x=False, y=False)  # WRONG — default linear
plot.plot(timestamps, pressures_mbar)
# Result: 1000 mbar plotted at top, 1e-6 mbar indistinguishable from 0

# Pre-converting data to log in storage — wrong layer
pressures_log = [math.log10(p) for p in pressures_mbar]
plot.plot(timestamps, pressures_log)  # WRONG — mixes display and data
```

**Related rules:** RULE-DATA-006 (units), RULE-DATA-010 (plot setup), `tokens/chart-tokens.md`

---

## RULE-DATA-009: No animation on live data updates

**TL;DR:** Value changes on live-data widgets happen instantly. No fade between values, no slide, no pulse unless signaling a distinct event (e.g., success echo).

**Statement:** Live numeric displays MUST NOT animate value transitions. When value changes from X to Y, widget repaints in one frame. Specifically forbidden:

- Opacity fade on value label during update
- Scale pulse when new value arrives
- Color transition (e.g., brief flash) on every update

ALLOWED exceptions (signaling distinct events, not ongoing data):
- One-time success echo on operator action (RULE-INTER-007)
- One-time fault indicator appearance (RULE-INTER-006) — but instant, not animated
- Chart line segment drawing between two real data points

**Rationale:** Data updating continuously at 2Hz with fade-animation = constant visual noise. Operator's eye attracted to every update regardless of whether value actually meaningful changed. Destroys ability to focus on anomalies.

Also: animations cost CPU. 30 sensor cells × 2Hz × opacity animation = ~60 animation frames/sec rendering work for no information gain.

**Applies to:** SensorCell, numeric readouts, any live-updating value display

**Example (good):**

```python
# DESIGN: RULE-DATA-009
def update_value(self, value: float):
    self._value_label.setText(f"{value:.2f}")  # instant
    # No animation, no effect
```

**Example (bad):**

```python
# Fade animation on every update
def update_value(self, value: float):
    anim = QPropertyAnimation(self._value_label, b"opacity")
    anim.setDuration(200)
    anim.setStartValue(0.5)
    anim.setEndValue(1.0)
    self._value_label.setText(f"{value:.2f}")
    anim.start()
# WRONG — constant visual noise

# Color flash on every update
def update_value(self, value: float):
    self._value_label.setText(f"{value:.2f}")
    self._value_label.setStyleSheet(f"color: {theme.ACCENT};")  # flash
    QTimer.singleShot(
        200,
        lambda: self._value_label.setStyleSheet(f"color: {theme.FOREGROUND};")
    )
# WRONG — every 500ms update becomes a flash
```

**Related rules:** RULE-DATA-001 (atomic snap), RULE-INTER-007 (success echo exception)

---

## RULE-DATA-010: Standard pyqtgraph setup pattern

**TL;DR:** All CryoDAQ plots use a shared setup helper applying theme tokens (background, grid color, label color, axis pen) consistently. Don't configure pyqtgraph widget from scratch each time.

**Statement:** New plot widgets MUST call `cryodaq.gui.plots.apply_cryodaq_theme(plot)` (proposed helper) rather than individually configuring background color, axis pen, tick font, grid alpha. Helper enforces:

- `setBackground(theme.PLOT_BG)` (matches BACKGROUND)
- Axis pen color `theme.PLOT_TICK_COLOR`
- Label color `theme.PLOT_LABEL_COLOR`
- Grid alpha `theme.PLOT_GRID_ALPHA`
- Tick font: FONT_MONO small
- Antialiasing on (pyqtgraph default; confirm)

For pressure plots specifically, helper also applies log-scale per RULE-DATA-008 when flagged.

**Rationale:** Three plots configured independently drift apart — one has black background, another dark-blue; one has 14px ticks, another 12px. Visual inconsistency even at subpixel level erodes professional appearance. Single helper enforces uniformity.

**Applies to:** any new pyqtgraph widget, any plot configuration

**Example (good):**

```python
# DESIGN: RULE-DATA-010
from cryodaq.gui.plots import apply_cryodaq_theme

plot = pg.PlotWidget()
apply_cryodaq_theme(plot)  # background, axis, grid, fonts — all from theme
plot.getAxis('left').setLabel("Температура", units="K")
plot.plot(timestamps, values, pen=pg.mkPen(theme.PLOT_LINE_PALETTE[0]))
```

**Example (good — helper implementation pattern):**

```python
# cryodaq/gui/plots.py
def apply_cryodaq_theme(plot: pg.PlotWidget, log_y: bool = False) -> None:
    plot.setBackground(theme.PLOT_BG)
    plot.showGrid(x=True, y=True, alpha=theme.PLOT_GRID_ALPHA)
    
    for axis_name in ('left', 'bottom'):
        axis = plot.getAxis(axis_name)
        axis.setPen(pg.mkPen(color=theme.PLOT_TICK_COLOR, width=1))
        axis.setTextPen(pg.mkPen(color=theme.PLOT_LABEL_COLOR))
        tick_font = QFont(theme.FONT_MONO, theme.FONT_MONO_SMALL_SIZE)
        axis.setTickFont(tick_font)
    
    if log_y:
        plot.setLogMode(x=False, y=True)  # RULE-DATA-008
```

**Example (bad):**

```python
# Each plot configured ad-hoc
plot1 = pg.PlotWidget()
plot1.setBackground("#000000")  # ad-hoc, violates RULE-COLOR-001

plot2 = pg.PlotWidget()
plot2.setBackground(theme.BACKGROUND)  # different from plot1
plot2.getAxis('left').setTextPen(pg.mkPen(color="#808080"))  # ad-hoc hex

# Result: two visually inconsistent plots in one dashboard
```

**Related rules:** RULE-COLOR-001 (no raw hex), RULE-DATA-008 (log-scale), `tokens/chart-tokens.md`

---

## Changelog

- 2026-04-17: Initial version. 10 rules covering atomic updates, rate throttling, no jitter, fixed precision, standard sensor format, mandatory units, palette discipline, log-scale for pressure, no-animation policy, plot setup helper.
- 2026-04-17 (v1.0.1): Switched operator-facing pressure unit examples from `mbar` to `мбар` (RULE-DATA-004 TL;DR, table row, RULE-DATA-006 TL;DR + SI line, RULE-DATA-008 axis-label code example). Code identifiers (`pressures_mbar`, `value_mbar` parameter) and English-prose explanations of the magnitude-span rationale stay as-is. (FR-016)
