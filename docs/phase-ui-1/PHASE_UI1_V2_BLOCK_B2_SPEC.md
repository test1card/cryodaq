# Phase UI-1 v2 — Block B.2: temperature and pressure plot widgets

## Context

Block B.1 + B.1.1 finalized the dashboard skeleton with five labeled
placeholder zones in the order:

1. Phase (10%)
2. Sensor grid (22%)
3. **Temperature plot (44%)** ← B.2 fills this
4. **Pressure plot (20%)** ← B.2 fills this
5. Quick log (4%)

B.2 is the first sub-block where the dashboard gets **real interactive
content**. After B.2 you launch CryoDAQ and see two working pyqtgraph
plots receiving live readings: a multi-channel temperature plot with
clickable legend, and a compact log-Y pressure plot synchronized on the
X axis. The other three zones (phase, sensor grid, quick log) remain
labeled placeholders and will be filled in B.3-B.6.

This block also introduces the **time window picker hybrid pattern**:
the control (button group) lives inside the temperature plot zone, and
its current value is echoed read-only in TopWatchBar zone 2 next to
experiment status, so the time window is visible from any overlay.

## Branch and baseline

- Branch: `feat/ui-phase-1-v2` (continue from current HEAD)
- Last commit: `ui(phase-1-v2): block B.1.1 — reorder dashboard zones (sensors above plots)`
- Baseline tests: **842 passed, 7 skipped**

## Russian language hard rule

All operator-facing text must be Russian. Technical exceptions: `Engine`,
`Telegram`, `SMU`, `Keithley`, `LakeShore`, `GPIB`, `mbar` (unit
abbreviation, kept in original Latin per international SI convention).

Time window button labels: `1мин / 1ч / 6ч / 24ч / Всё`. Y axis toggle
button label: `Lin Y` / `Log Y` (technical abbreviations kept).

## Anti-pattern reminders

Apply `docs/SPEC_AUTHORING_CHECKLIST.md`:

- **QSS selectors via `#objectName`**, never `ClassName { ... }` (A.7)
- **Parent QWidget {} cascades to children** — use `#objectName` to
  scope (A.8)
- **No `setVisible(True)` self-calls** in widgets that should stay
  hidden (A.9)
- **Worker stacking guard** — `if worker is not None and not
  worker.isFinished(): return` (Codex Finding 2)
- **No QTimer.singleShot in widget `__init__`** — use parented `QTimer`
  instances with explicit lifetime
- **Russian language for all operator-facing text**
- **Cyrillic Т vs Latin T** — temperature channels use cyrillic
  `\u0422`, pressure channels use Latin `VSP63D_1/pressure`. Do not
  mix.

## Key facts about CryoDAQ data routing

These were confirmed by grep on the existing codebase before this spec:

- **Temperature channels** arrive as `Reading` with `channel` starting
  with cyrillic Т (`\u0422`). E.g. `"Т1 Криостат верх"`, `"Т11
  Теплообменник 1"`. `unit = "K"`. The short ID before the space is
  what `ChannelManager` indexes.
- **Pressure channel** arrives as `Reading` with `channel ==
  "VSP63D_1/pressure"`. `unit = "mbar"`. Single channel from Thyracont
  driver. Filter via `channel.endswith("/pressure")` is the safest
  pattern.
- **Reading timestamp** is `datetime.datetime` with `tzinfo=timezone.utc`.
  Convert to epoch float via `reading.timestamp.timestamp()` for
  pyqtgraph X axis.
- **MainWindowV2._dispatch_reading** already calls
  `self._overview_panel.on_reading(reading)` for every reading. After
  B.1, `self._overview_panel` is a `DashboardView` instance. B.2
  replaces the no-op `on_reading` with real routing.

---

## Goal

After B.2:

1. Temperature plot zone shows a real `pg.PlotWidget` with one curve
   per visible Т-channel, all curves drawn with palette colors
2. Pressure plot zone shows a real `pg.PlotWidget` with one curve for
   `VSP63D_1/pressure`, log-Y axis
3. Both plots share an X axis (linked via `setXLink`) — pan/zoom one
   pans/zooms the other
4. Time window picker (button group `1мин / 1ч / 6ч / 24ч / Всё`)
   sits at top of temperature plot zone, default `1ч`
5. `Lin Y` / `Log Y` toggle button sits at top-right of temperature
   plot zone, default `Lin Y` (linear)
6. Clicking a legend entry toggles that channel's visibility on the
   temp plot — standard pyqtgraph legend behavior
7. TopWatchBar zone 2 shows time window echo: `▸ окно 1ч` appended
   after experiment status text
8. New `ChannelBufferStore` class manages per-channel deques and is
   shared between temp/pressure plots and (in B.3) sensor grid
9. Tests pass (842 baseline + N new), Codex audit clean

---

## Tasks

### Task 1 — Create ChannelBufferStore module

**File:** `src/cryodaq/gui/dashboard/channel_buffer.py`

Purpose: per-channel rolling history of `(timestamp_epoch, value)`
tuples. Owned by `DashboardView`, consumed by plot widgets in B.2 and
sensor grid in B.3 and phase widget in B.4-B.5.

```python
"""Per-channel reading history storage for the new dashboard.

Owned by DashboardView. Plot widgets, sensor cards, and phase-aware
widgets all read from this single source instead of duplicating
buffers across components.

Buffer maxlen matches the legacy OverviewPanel value (24 hours at
1 Hz nominal) — enough history for the longest time window option
('Всё' acts as 'show whole buffer').
"""

from __future__ import annotations

from collections import deque
from typing import Iterable

# 1 Hz nominal × 24 hours = 86400 samples per channel.
# Memory footprint: ~3 MB per channel for float pairs. Acceptable
# for ~25 channels = ~75 MB worst case.
_BUFFER_MAXLEN = 86400


class ChannelBufferStore:
    """Rolling per-channel deque store with last-value lookup."""

    def __init__(self, maxlen: int = _BUFFER_MAXLEN) -> None:
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        self._last_value: dict[str, tuple[float, float]] = {}
        self._maxlen = maxlen

    def append(self, channel: str, timestamp_epoch: float,
               value: float) -> None:
        """Append a single sample to the channel's buffer."""
        if channel not in self._buffers:
            self._buffers[channel] = deque(maxlen=self._maxlen)
        self._buffers[channel].append((timestamp_epoch, value))
        self._last_value[channel] = (timestamp_epoch, value)

    def get_history(self, channel: str) -> list[tuple[float, float]]:
        """Return a list copy of the channel's buffer for plotting.

        Empty list if channel has no data.
        """
        buf = self._buffers.get(channel)
        if buf is None:
            return []
        return list(buf)

    def get_history_since(self, channel: str,
                          since_epoch: float) -> list[tuple[float, float]]:
        """Return entries newer than since_epoch."""
        buf = self._buffers.get(channel)
        if buf is None:
            return []
        return [(t, v) for (t, v) in buf if t >= since_epoch]

    def get_last(self, channel: str) -> tuple[float, float] | None:
        """Return (timestamp, value) of the most recent sample, or None."""
        return self._last_value.get(channel)

    def known_channels(self) -> Iterable[str]:
        """Return iterable of all channels that have at least one sample."""
        return self._buffers.keys()

    def clear(self, channel: str | None = None) -> None:
        """Clear one channel or all channels."""
        if channel is None:
            self._buffers.clear()
            self._last_value.clear()
        else:
            self._buffers.pop(channel, None)
            self._last_value.pop(channel, None)
```

**Tests:** `tests/gui/dashboard/test_channel_buffer.py` — 4 minimal:
- empty store has no known channels
- append + get_last returns the appended value
- multiple appends preserve order in get_history
- get_history_since filters correctly

No QTimer, no Qt anywhere in this module. Pure Python data structure.

### Task 2 — TimeWindow enum and constants

**File:** `src/cryodaq/gui/dashboard/time_window.py`

Shared enum that both `TempPlotWidget` and `TopWatchBar` echo will
reference. This way the picker control and the watch bar echo display
the same set of options without copy-paste.

```python
"""Time window selector enum for dashboard plots.

Shared between TempPlotWidget (interactive picker) and TopWatchBar
(read-only echo). Modifying this single source updates both surfaces.
"""

from __future__ import annotations

from enum import Enum


class TimeWindow(Enum):
    """Time window options for plot X-axis range."""

    MIN_1 = ("1мин", 60.0)
    HOUR_1 = ("1ч", 3600.0)
    HOUR_6 = ("6ч", 21600.0)
    HOUR_24 = ("24ч", 86400.0)
    ALL = ("Всё", float("inf"))

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def seconds(self) -> float:
        return self.value[1]

    @classmethod
    def default(cls) -> "TimeWindow":
        return cls.HOUR_1

    @classmethod
    def all_options(cls) -> list["TimeWindow"]:
        return [cls.MIN_1, cls.HOUR_1, cls.HOUR_6, cls.HOUR_24, cls.ALL]
```

**Tests:** `tests/gui/dashboard/test_time_window.py` — 2 minimal:
- `default()` is `HOUR_1`
- `all_options()` returns 5 entries in display order

### Task 3 — TempPlotWidget

**File:** `src/cryodaq/gui/dashboard/temp_plot_widget.py`

A `QWidget` (not `QFrame` to avoid object-name conflict with the parent
zone) containing:
- A horizontal toolbar at top: time picker button group on the left,
  Lin/Log toggle button on the right
- A `pg.PlotWidget` below the toolbar that fills remaining space
- Per-channel `pg.PlotDataItem` curves stored in `self._plot_items:
  dict[str, pg.PlotDataItem]`
- A clickable legend that toggles curve visibility on click

#### Constructor

```python
class TempPlotWidget(QWidget):
    """Multi-channel temperature plot for the dashboard.

    Receives data from ChannelBufferStore via refresh() called from
    DashboardView's refresh timer. Time window picker, Lin/Log toggle,
    and clickable legend live entirely inside this widget.
    """

    time_window_changed = Signal(object)  # emits TimeWindow

    def __init__(
        self,
        buffer_store: ChannelBufferStore,
        channel_manager: ChannelManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._buffer = buffer_store
        self._channel_mgr = channel_manager
        self._plot_items: dict[str, pg.PlotDataItem] = {}
        self._current_window = TimeWindow.default()
        self._is_log_y = False
        self._build_ui()
        self._rebuild_curves()
```

#### `_build_ui` structure

```
QVBoxLayout (root)
  HBoxLayout (toolbar)
    QButtonGroup (time picker)
      QPushButton "1мин" (checkable)
      QPushButton "1ч" (checkable, default checked)
      QPushButton "6ч" (checkable)
      QPushButton "24ч" (checkable)
      QPushButton "Всё" (checkable)
    addStretch()
    QPushButton "Lin Y" / "Log Y" (toggle)
  pg.PlotWidget (fills rest)
```

Toolbar height: compact, ~32-36px (calibrate later, do not write
exact pixel constant). Use `self.setFixedHeight` only on the toolbar,
not on the plot.

Buttons styled via theme tokens. Active state of time picker buttons
uses `theme.ACCENT_400` background, inactive uses `theme.SURFACE_PANEL`.
Text colors per state from theme. Reuse the same QSS pattern as
ToolRail buttons in shell — copy the helper if needed but **do not
import shell modules into dashboard** to avoid circular dependency.

#### Plot initialization

```python
def _init_plot(self) -> None:
    self._plot.setBackground(theme.SURFACE_CARD)
    self._plot.showGrid(x=True, y=True, alpha=0.15)
    pi = self._plot.getPlotItem()
    pi.setLabel("left", "Температура", units="K",
                color=theme.TEXT_SECONDARY)
    # X axis is time (epoch float). DateAxisItem renders human times.
    date_axis = pg.DateAxisItem(orientation="bottom")
    self._plot.setAxisItems({"bottom": date_axis})
    pi.getAxis("bottom").setLabel("")  # X label hidden — pressure plot owns it
    # Hide X axis numbers on temp plot — pressure plot below shows them
    # via setXLink
    pi.getAxis("bottom").setStyle(showValues=False)
    pi.addLegend(offset=(10, 10))
```

**Important:** the temperature plot **hides X axis numbers** because
the pressure plot below shows them, and the two are X-linked. This
mimics the legacy OverviewPanel layout which also did this. The link
is set up by `DashboardView` after both plots exist (Task 5), not
inside TempPlotWidget itself.

#### `_rebuild_curves`

Iterate over `self._channel_mgr.get_all_visible()` (returns short IDs
like `Т1`, `Т2`, ...), create one `pg.PlotDataItem` per channel with a
color from `_LINE_PALETTE` (copy palette from old `overview_panel.py`),
and store in `self._plot_items` keyed by **short ID**, not full
display name. Add each item to the plot via `self._plot.plot(...)` so
it ends up in the legend.

Legend entry text uses `self._channel_mgr.get_display_name(short_id)`.

```python
_LINE_PALETTE: list[str] = [
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD",
    "#8C564B", "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF",
    "#AEC7E8", "#FFBB78", "#98DF8A", "#FF9896", "#C5B0D5",
    "#C49C94", "#F7B6D2", "#C7C7C7", "#DBDB8D", "#9EDAE5",
    "#393B79", "#637939", "#8C6D31", "#843C39",
]
```

#### `refresh()` method

Called by `DashboardView`'s refresh `QTimer` at 1 Hz. Steps:

1. Compute X range from current time window:
   - For `TimeWindow.ALL`: no range constraint, use `enableAutoRange`
   - Otherwise: `x_max = time.time()`, `x_min = x_max - window.seconds`,
     `self._plot.setXRange(x_min, x_max, padding=0)`
2. For each channel in `self._plot_items`:
   - Determine the channel ID format used by `Reading.channel`. Per
     fact-find above, temperature readings arrive as
     `"Т1 Криостат верх"` (full display name). The buffer store keys
     by whatever `DashboardView.on_reading` uses as channel ID.
     Decision: **use short ID consistently**. `DashboardView.on_reading`
     normalizes incoming `Reading.channel` to short ID via
     `channel.split(" ")[0]` before storing in the buffer.
   - Get history from buffer: `pts = self._buffer.get_history(short_id)`
   - If `pts` is empty, skip
   - Decimate if too many points (>2000) — copy `_decimate` helper from
     legacy `overview_panel.py` (it's a small standalone function)
   - Set curve data: `item.setData(x=[t for t, v in pts], y=[v for t, v
     in pts])`

#### Time picker handler

```python
def _on_time_window_clicked(self, window: TimeWindow) -> None:
    self._current_window = window
    self.time_window_changed.emit(window)
    self.refresh()
```

#### Lin/Log handler

```python
def _on_log_y_toggled(self, checked: bool) -> None:
    self._is_log_y = checked
    self._plot.getPlotItem().setLogMode(x=False, y=checked)
    self._log_button.setText("Log Y" if checked else "Lin Y")
```

#### Clickable legend

pyqtgraph's legend supports `LegendItem.sigVisibilityChanged` on
`PlotDataItem` indirectly, but the cleanest pattern is:

```python
legend = pi.legend
for sample, label in legend.items:
    label.mousePressEvent = lambda ev, s=sample: self._toggle_curve(s)
```

Where `_toggle_curve(sample)` finds the corresponding `PlotDataItem`
and calls `setVisible(not isVisible())`. **If pyqtgraph version
makes this fragile**, fallback: add a small "checkbox row" above the
plot with one checkbox per channel. Try the legend approach first.

#### Channel manager change subscription

Subscribe to `self._channel_mgr.on_change(self._on_channels_changed)`
so that when YAML config is edited at runtime, `_rebuild_curves` is
called and the plot reflects the new visible set.

`_on_channels_changed` should clear `self._plot_items`, remove items
from plot, and rebuild from current visible list.

### Task 4 — PressurePlotWidget

**File:** `src/cryodaq/gui/dashboard/pressure_plot_widget.py`

Smaller widget than TempPlotWidget. No toolbar (time window comes from
the linked temp plot via `setXLink`). No Lin/Log toggle (always log).

```python
class PressurePlotWidget(QWidget):
    """Compact log-Y pressure plot for the dashboard.

    No toolbar — synchronizes X axis with the temperature plot via
    setXLink in DashboardView. Always uses log Y because cryogenic
    vacuum spans many orders of magnitude.
    """

    def __init__(
        self,
        buffer_store: ChannelBufferStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._buffer = buffer_store
        self._channel_id = "VSP63D_1/pressure"
        self._build_ui()
```

#### `_build_ui` structure

```
QVBoxLayout (root, no margins)
  pg.PlotWidget (fills entire widget)
```

#### Plot initialization

```python
def _init_plot(self) -> None:
    self._plot.setBackground(theme.SURFACE_CARD)
    self._plot.showGrid(x=True, y=True, alpha=0.15)
    pi = self._plot.getPlotItem()
    pi.setLabel("left", "Давление", units="mbar",
                color=theme.TEXT_SECONDARY)
    pi.setLabel("bottom", "Время", color=theme.TEXT_SECONDARY)
    date_axis = pg.DateAxisItem(orientation="bottom")
    self._plot.setAxisItems({"bottom": date_axis})
    pi.setLogMode(x=False, y=True)  # log Y always
    self._curve = self._plot.plot([], [], pen=pg.mkPen("#FF7F0E", width=2))
```

#### `refresh()` method

Called from `DashboardView` refresh timer. Same idea as temp plot:

```python
def refresh(self) -> None:
    pts = self._buffer.get_history(self._channel_id)
    if not pts:
        return
    if len(pts) > 2000:
        pts = _decimate(pts, 2000)
    xs = [t for t, v in pts]
    # Filter out non-positive values for log Y (log10(0) = -inf)
    ys = [v if v > 0 else 1e-12 for _, v in pts]
    self._curve.setData(x=xs, y=ys)
```

The X range is set by the linked temp plot — pressure plot does not
manage its own X range.

### Task 5 — Wire plots into DashboardView

**File:** `src/cryodaq/gui/dashboard/dashboard_view.py`

Replace placeholder labels in `tempPlotZone` and `pressurePlotZone`
with the new widgets. Other zones (`phaseZone`, `sensorGridZone`,
`quickLogZone`) remain placeholder.

#### Constructor changes

```python
def __init__(self, channel_manager, parent=None):
    super().__init__(parent)
    self._channel_mgr = channel_manager
    self._buffer_store = ChannelBufferStore()
    self._temp_plot: TempPlotWidget | None = None
    self._pressure_plot: PressurePlotWidget | None = None
    self._build_ui()
    self._wire_x_link()
    self._start_refresh_timer()
```

#### `_build_ui` zone changes

In `_make_zone` for `tempPlotZone`: instead of adding a `QLabel`
placeholder, instantiate `TempPlotWidget(self._buffer_store,
self._channel_mgr)` and add it to the zone's inner layout. Store as
`self._temp_plot`.

Same for `pressurePlotZone`: instantiate `PressurePlotWidget(self._buffer_store)`,
store as `self._pressure_plot`.

The other three zones keep their placeholder labels unchanged.

#### `_wire_x_link`

```python
def _wire_x_link(self) -> None:
    """Link pressure plot's X axis to the temperature plot."""
    if self._temp_plot is None or self._pressure_plot is None:
        return
    self._pressure_plot._plot.setXLink(self._temp_plot._plot)
```

(Yes, accessing `_plot` is technically private, but both classes live
in the same module hierarchy and this is the cleanest way without
adding a public accessor. Acceptable.)

#### `_start_refresh_timer`

```python
def _start_refresh_timer(self) -> None:
    self._refresh_timer = QTimer(self)
    self._refresh_timer.setInterval(1000)  # 1 Hz
    self._refresh_timer.timeout.connect(self._refresh_plots)
    self._refresh_timer.start()

def _refresh_plots(self) -> None:
    if self._temp_plot is not None:
        self._temp_plot.refresh()
    if self._pressure_plot is not None:
        self._pressure_plot.refresh()
```

#### `on_reading` — replace no-op stub

```python
def on_reading(self, reading: Reading) -> None:
    """Route reading into buffer store. Plots refresh from buffer."""
    channel = reading.channel
    timestamp_epoch = reading.timestamp.timestamp()
    value = reading.value

    if isinstance(value, (int, float)):
        if channel.startswith("\u0422"):  # cyrillic Т
            short_id = channel.split(" ")[0]
            self._buffer_store.append(short_id, timestamp_epoch, float(value))
        elif channel.endswith("/pressure"):
            self._buffer_store.append(channel, timestamp_epoch, float(value))
```

Note: temperature stored under **short ID** (`"Т1"`), pressure stored
under **full channel ID** (`"VSP63D_1/pressure"`). This asymmetry
matches how each plot widget looks them up.

### Task 6 — TopWatchBar time window echo

**File:** `src/cryodaq/gui/shell/top_watch_bar.py`

Add a small read-only label area in zone 2 (experiment status zone)
that shows the current time window. The contol stays in TempPlotWidget;
this is purely a display echo so the operator sees the window from any
overlay.

#### New method on TopWatchBar

```python
def set_time_window_echo(self, label: str) -> None:
    """Set the time window display in zone 2 footer.

    Called by MainWindowV2 when TempPlotWidget emits time_window_changed.
    label is the short text like '1ч' or 'Всё'.
    """
    if hasattr(self, '_time_window_echo_label'):
        self._time_window_echo_label.setText(f"▸ окно {label}")
```

The `_time_window_echo_label` is a `QLabel` constructed in
`_build_ui`'s zone 2 layout, placed after the experiment status text.
Initial text: `▸ окно 1ч` (matches default).

Style: `theme.TEXT_MUTED` color, `theme.FONT_LABEL_SM` size, same
typography as other zone 2 secondary text.

**Important:** zone 2 layout already contains experiment status text
+ phase + elapsed. Adding the time window echo means zone 2 has more
content. Verify text wrapping does not break — use
`QSizePolicy.Preferred` on the new label.

#### Wire from MainWindowV2

**File:** `src/cryodaq/gui/shell/main_window_v2.py`

In `_build_ui`, after constructing both `self._top_bar` and
`self._overview_panel` (which is now `DashboardView`):

```python
# Wire dashboard time window picker → top bar echo
if hasattr(self._overview_panel, '_temp_plot') and \
   self._overview_panel._temp_plot is not None:
    self._overview_panel._temp_plot.time_window_changed.connect(
        lambda window: self._top_bar.set_time_window_echo(window.label)
    )
    # Initialize echo with default
    self._top_bar.set_time_window_echo(
        TimeWindow.default().label
    )
```

Import:
```python
from cryodaq.gui.dashboard.time_window import TimeWindow
```

This is the **only** shell file edited in B.2. The rest of B.2 lives
inside `src/cryodaq/gui/dashboard/`.

### Task 7 — Tests

**Files in `tests/gui/dashboard/`:**

1. `test_channel_buffer.py` — 4 tests as described in Task 1
2. `test_time_window.py` — 2 tests as described in Task 2
3. `test_temp_plot_widget.py` — 3 smoke tests:
   - constructs without error given mock buffer + channel manager
   - `refresh()` does not raise on empty buffer
   - `refresh()` does not raise after appending one sample
4. `test_pressure_plot_widget.py` — 2 smoke tests:
   - constructs without error
   - `refresh()` works on empty + filled buffer
5. `test_dashboard_view.py` — **update existing**: add 2 new tests:
   - `on_reading` with temperature reading appends to buffer under
     short ID
   - `on_reading` with pressure reading appends to buffer under full
     channel ID
6. `test_main_window_v2_time_window_echo.py` (in `tests/gui/shell/`):
   - launch MainWindowV2 with mock bridge
   - assert time window echo label is initialized to `▸ окно 1ч`
   - emit `time_window_changed(TimeWindow.HOUR_6)` from temp plot
   - assert label text becomes `▸ окно 6ч`

All tests should be smoke-level. No need to test pyqtgraph rendering
itself.

Set `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` at the
top of any file that creates `QApplication` (B.1 lesson — CC already
applied this pattern).

## Out of scope

- Do NOT touch `theme.py`
- Do NOT touch `tool_rail.py`, `bottom_status_bar.py`,
  `overlay_container.py`
- Do NOT touch any file in `src/cryodaq/gui/widgets/` — old
  OverviewPanel stays alive untouched until B.7
- Do NOT add sensor cards (B.3)
- Do NOT add phase widget logic (B.4-B.5)
- Do NOT add quick log functionality (B.6)
- Do NOT delete legacy OverviewPanel (B.7)
- Do NOT introduce ZmqCommandWorker — DashboardView gets data via
  `on_reading` from MainWindowV2 which already handles ZMQ
- Do NOT add experiment-phase-aware filtering of channels (that's a
  B.4-B.5 enhancement; B.2 shows all visible channels always)
- Do NOT modify `MainWindowV2._dispatch_reading` — it already calls
  `self._overview_panel.on_reading`. Only add Task 6 wiring in
  `_build_ui`.

## Tests target

```bash
.venv/bin/python -m pytest -q 2>&1 | tail -10
```

Expected: **855-857 passed, 7 skipped** (842 baseline + ~13-15 new
tests across 6 files).

If any existing test breaks, stop and report. The change should be
purely additive at the test suite level.

## Visual verification

Launch via:
```bash
CRYODAQ_MOCK=1 .venv/bin/cryodaq
```

Expected:
- Phase zone at top (placeholder label)
- Sensor grid zone (placeholder label)
- **Temperature plot zone now contains a real plot** with:
  - Time picker buttons at top: `1мин 1ч 6ч 24ч Всё` (1ч highlighted)
  - Lin Y / Log Y toggle button at top right
  - Plot area below with grid
  - Curves appearing for each visible Т-channel as data flows
  - Legend on the right side showing channel names
  - Click on legend entry → that curve toggles visible/hidden
- **Pressure plot zone contains a real log-Y plot** below temp plot
- X axis of pressure plot shows time labels; X axis of temp plot is
  hidden (synchronized via setXLink)
- Pan/zoom on either plot moves both
- Quick log zone at bottom (placeholder label)
- TopWatchBar zone 2 shows experiment status + `▸ окно 1ч` echo
- Click `6ч` button → both plots show 6h window, watch bar updates
  to `▸ окно 6ч`
- Click Lin Y → becomes Log Y, temp plot Y axis switches to log scale

After waiting ~30 seconds, plot should show real curves moving in
real time (mock generates data continuously).

## Codex audit

After all tasks committed, run:

```bash
codex exec -c model="gpt-5.4" "Audit commits implementing Block B.2 (temperature and pressure plot widgets) on branch feat/ui-phase-1-v2 against the spec at docs/phase-ui-1/PHASE_UI1_V2_BLOCK_B2_SPEC.md.

Look specifically for:
- QSS selectors using Python class names instead of #objectName (Block A.7 lesson)
- QSS selectors that cascade to children causing seams (Block A.8 lesson)
- ZMQ workers in widget __init__ (should be none in dashboard module)
- QTimer.singleShot lifetime management (only parented QTimer instances allowed)
- Worker stacking under slow refresh (refresh should be idempotent)
- Russian localization gaps in src/cryodaq/gui/dashboard/
- Embedded mode compatibility — verify MainWindowV2 reading dispatch still routes through self._overview_panel.on_reading
- Cyrillic Т vs Latin T mismatches in temperature channel filtering
- Pressure channel filter correctness (endswith /pressure pattern)
- ChannelBufferStore key consistency between writer (DashboardView.on_reading) and readers (TempPlotWidget.refresh, PressurePlotWidget.refresh)
- pyqtgraph setXLink correctness — pressure plot must follow temp plot, not the other way around
- Log Y handling for non-positive pressure values (log10(0) = -inf would crash)
- Time window picker default value matches TimeWindow.default()
- TopWatchBar zone 2 layout does not break when time window echo is appended
- Test pollution: any worker or QTimer leaked from new dashboard tests
- Memory leak from buffer store (unbounded growth if maxlen ignored)

Report findings in numbered list with severity CRITICAL/HIGH/MEDIUM/LOW. Do not modify any files. Read-only audit."
```

Paste full Codex output verbatim into the CC reply.

## Commit and stop

```bash
git add src/cryodaq/gui/dashboard/ src/cryodaq/gui/shell/top_watch_bar.py \
        src/cryodaq/gui/shell/main_window_v2.py tests/gui/
git commit -m "ui(phase-1-v2): block B.2 — temperature and pressure plot widgets

Replaces tempPlotZone and pressurePlotZone placeholders in
DashboardView with real pyqtgraph widgets:

- TempPlotWidget: multi-channel temp plot, time picker
  (1мин/1ч/6ч/24ч/Всё, default 1ч), Lin/Log Y toggle, clickable
  legend for per-curve visibility
- PressurePlotWidget: compact log-Y pressure plot, X axis linked
  to temp plot via setXLink
- ChannelBufferStore: per-channel deque history shared across
  plot widgets and (future) sensor grid + phase widget
- TimeWindow enum: shared between picker and TopWatchBar echo
- TopWatchBar zone 2 echo: read-only display of current time
  window appended after experiment status

Other dashboard zones (phase, sensor grid, quick log) remain
placeholder until B.3-B.6.

Legacy OverviewPanel unchanged — removed in B.7.
"
```

Print: `BLOCK B.2 COMPLETE — visual fix committed, Codex audit below`
followed by full Codex output.

**Stop. Do not start B.3.** Vladimir reviews the visual result and
Codex findings before B.3 spec arrives.

## Success criteria

- Two new plot widgets visible on the dashboard, real-time data flow
- Time picker works, default 1ч, all 5 options switch X range
- Lin/Log Y toggle works on temp plot
- Legend click toggles per-channel visibility on temp plot
- Pressure plot Y axis is log scale, X axis synchronized to temp
- TopWatchBar zone 2 echoes time window correctly
- All existing tests pass + new dashboard tests
- Codex audit clean (no CRITICAL or HIGH findings)
- Single commit with comprehensive message

## After Vladimir's review

If approved → B.3 spec (DynamicSensorGrid replacing sensorGridZone
placeholder).

If visual or audit reveals issues → B.2.1 micro-fix.
