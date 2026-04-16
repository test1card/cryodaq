---
title: Performance Budget
keywords: performance, budget, frame-rate, fps, latency, render-cost, update-rate, input-response
applies_to: visual performance targets, render costs, input latency
status: canonical
references: rules/data-display-rules.md, patterns/real-time-data.md
external_reference: UI UX Pro Max v2.5.0 main-thread-budget + input-latency rules; Core Web Vitals adaptation
last_updated: 2026-04-17
---

# Performance Budget

Visual performance targets. These set ceilings on how much work the UI can do per frame without degrading operator experience — particularly during real-time data streaming where frame drops or latency become visible artifacts.

## Budget at a glance

| Target | Value | Source / rationale |
|---|---|---|
| Frame rate | 60 FPS (16.67ms per frame) | Standard for modern displays; Qt default |
| Main-thread budget per frame | < 16ms | UXPM `main-thread-budget` rule |
| Live data update rate | ≤ 2 Hz | RULE-DATA-002; coalescing (`patterns/real-time-data.md`) |
| Chart replot rate | ≤ 2 Hz | Same |
| Input response latency | < 100ms | UXPM `input-latency` rule |
| Tap/click feedback | < 100ms | UXPM `tap-feedback-speed` |
| Modal/Drawer open animation | ≤ 200ms | RULE-INTER-006 adjacent; UXPM `duration-timing` |
| Fault state render | Instant (< 16ms) | RULE-INTER-006 — one-frame transition |
| App launch to interactive | < 2s | App cold start target |
| ZMQ roundtrip to GUI update | < 500ms typical | Allows user to feel "responsive" |

## Why a performance budget

A design system that doesn't respect performance produces beautiful UI that feels sluggish. Three operator-experience concerns:

1. **Frame drops during live data** — if the UI can't keep up at 60 FPS while 3 LakeShores publish + chart updates + layout reflows, operator sees jank. Reduces trust in readings.
2. **Input latency** — click → feedback delay > 100ms feels broken. Even tasteful UI at 500ms feedback feels inferior to ugly UI at 30ms feedback.
3. **Battery / heat** — lab PC running dashboard for 12h shift at high CPU wastes power and heats the room. Dashboard should idle at low CPU.

## Frame budget breakdown

Per-frame budget of 16ms (for 60 FPS) must cover:

| Activity | Typical budget |
|---|---|
| Qt event processing | 1-2 ms |
| Layout calculation | 1-3 ms (unchanged layouts are near zero) |
| Widget paint | 3-5 ms (depends on complexity) |
| Custom paint (charts) | 3-5 ms (pyqtgraph) |
| ZMQ message dispatch | <1 ms (async, not blocking) |
| Safety margin | 2-4 ms |

If a widget paints in 8ms and chart paints in 8ms on the same frame, the frame is over budget. Charts + widgets on same screen need their paint costs kept low.

## Specific performance rules

### Charts

Per `components/chart-tile.md` + RULE-DATA-010:

- **Max data points per chart** ~ 500-1000 (rolling window pruning)
- **No anti-aliasing on live data** — pyqtgraph default fine; don't enable extra AA
- **Plot update rate ≤ 2 Hz** — setData call once per 500ms max
- **Axis range: don't auto-range during streaming** — fixed axis avoids recomputing layout

### Bento dashboard

- **Max ~12 tiles per screen** — beyond, scroll; layout recalculation cost scales with tile count
- **Tile updates coalesce** — if 8 cells need to update, do them in one `blockSignals` batch, not 8 separate repaints

### Stylesheets

Stylesheet parsing is expensive:
- **Avoid frequent setStyleSheet calls** — set once, then change properties
- **Use objectName + QSS selectors** instead of inline stylesheets per widget
- **Cache stylesheets** where reusable

```python
# BAD — re-parses stylesheet on every update
widget.setStyleSheet(f"background: {color};")

# GOOD — uses property that can be toggled
widget.setProperty("status", "fault")
widget.style().unpolish(widget)
widget.style().polish(widget)
```

Or use QPalette for color changes when supported.

### Signals

- **Use `Qt.QueuedConnection`** for cross-thread signals to avoid blocking the emitter thread
- **Throttle rapid signal emissions** via QTimer-based coalescing (see `patterns/real-time-data.md`)
- **Avoid lambda with captured widgets** in signal connections — cleanup leaks

### Painting

- **paintEvent is on main thread** — don't block (no disk reads, no network)
- **Cache rendered pixmaps** for complex static content
- **Clip to damaged region** (Qt does this by default; don't override with full-rect repaint)

## Input latency budget

From click to visible feedback: < 100ms.

Breakdown:
- Click event arrives: ~10-20ms (OS → Qt)
- Event handler runs: should be < 50ms
- Widget state update: < 10ms
- Repaint triggered: next frame (~16ms)
- Total: ~90ms worst case

**Do NOT block event handler** on:
- ZMQ REQ/REP roundtrip (async)
- File I/O (use `QFileDialog` nonblocking or `QThread`)
- Database queries (SQLite read < 10ms usually OK; writes via persistence-first go through scheduler anyway)

If an action requires > 100ms work, show loading state immediately (< 100ms) then complete asynchronously.

## Memory budget

- **App idle memory:** < 300 MB (baseline Qt + pyqtgraph + plugins)
- **Per-experiment memory growth:** < 50 MB (typical 4-hour experiment with 20-channel data)
- **Chart data retention:** capped at `max_points` per series; older points evicted
- **Widget pool:** re-use widgets across panel switches instead of destroying/recreating where possible

Memory leaks are visible over a 12-hour shift; baseline checks every deploy.

## Startup performance

Cold start → interactive target: < 2s.

Breakdown:
- Python interpreter + imports: ~500ms (hard floor; Python + PyQt)
- ZMQ socket init: ~50ms
- Engine connection + first /status: ~300ms (network + engine response)
- MainWindow construction: ~200ms
- First repaint: ~100ms
- Total: ~1150ms typical; 2s ceiling with headroom

Defer-loading for non-critical panels:
- Dashboard loads first
- Other panels (Analytics, Journal) lazy-loaded on first ToolRail click

## Live-streaming performance case study

Worst-case concurrent load:
- 24 sensor channels updating at 2 Hz (48 updates/s on channel)
- 4 charts updating at 2 Hz
- 1 experiment phase event (rare)
- Operator mouse hover / click events interspersed
- AlarmBadge count updates (rare)

At 2 Hz aggregate → 2 render-triggering events per second → 2 frames per second could be "busy". Other 58 frames/s are idle or handle only mouse events.

If everything fits in budget: dashboard idles at < 5% CPU; steady memory; no visible jank. Verify via Qt profiling (`QElapsedTimer`, `py-spy`).

## Measurement tooling

### Frame timing

```python
# tools/profile_frame.py
from PySide6.QtCore import QElapsedTimer

class FrameTimer:
    def __init__(self):
        self._timer = QElapsedTimer()
    
    def start(self):
        self._timer.start()
    
    def end(self, operation: str):
        elapsed_ms = self._timer.elapsed()
        if elapsed_ms > 16:
            print(f"[FRAME OVER BUDGET] {operation}: {elapsed_ms}ms")
```

Wrap expensive operations (paint, setData, layout) in FrameTimer during profiling.

### Full-app profiling

- `py-spy record -o profile.svg -- python -m cryodaq.launcher` — flamegraph of where time is spent
- Qt's `QLoggingCategory("qt.scenegraph.time")` — scene-graph frame times

### Memory profiling

- `memray` or `tracemalloc` — track allocation growth over a simulated experiment

## Performance regression detection

Per `governance/testing-strategy.md`:

- Baseline metrics captured at each MINOR release
- Automated benchmark script runs a typical 5-minute experiment scenario in mock mode, measures:
  - Peak memory
  - 95th percentile frame time
  - ZMQ queue depth
  - Number of over-budget frames
- Regressions > 20% on any metric → blocked PR or governance review

## Anti-patterns that break the budget

1. **Animating layout** — `setGeometry` in a loop re-triggers layout per frame. Use `QPropertyAnimation` on transform, not geometry.

2. **Frequent setStyleSheet** — parses stylesheet on each call. Batch changes or use property-based styling.

3. **Connecting ZMQ SUB directly to widget.setText** — no coalescing; high-rate publish floods UI.

4. **Auto-range on every chart setData** — recomputes layout every 500ms. Disable during streaming.

5. **Creating new QPixmaps each paint** — allocate once, reuse.

6. **Running non-trivial work in paintEvent** — I/O, database, complex calculations. Move to background thread, cache result.

7. **No batching of dashboard tile updates** — 10 tiles update individually per second. Batch into single atomic update.

8. **Unbounded undo history** — memory growth unbounded. Cap at reasonable number (50 steps) or disable in operator UI (not expected feature).

## Future optimizations (not v1.0.0 scope)

- GPU-accelerated plotting (VisPy or similar)
- WebGL chart rendering
- Virtualized lists in alarm history
- Worker-thread heavy computation (Keithley reading aggregation)
- Multi-process architecture if single-process GUI hits limits

## Rules applied

- **RULE-DATA-002** — update rate cap feeds here
- **RULE-INTER-006** — instant fault = < 16ms fits frame budget
- UXPM `main-thread-budget` — per-frame 16ms reference
- UXPM `input-latency` — 100ms tap response

## Common mistakes

1. **Ignoring budget until jank visible.** Reactive tuning. Start with budget as a target; measure as you build.

2. **Only testing on fast hardware.** Developer's M2 Max handles 3x the load. Test on the lab PC specs (older Intel + integrated GPU).

3. **Optimizing the wrong thing.** Without profile data, intuition picks wrong target. Profile first.

4. **No regression gate.** Performance degrades release-over-release unnoticed. Set up baseline + regression check.

5. **Blocking ZMQ in main thread.** GUI freezes during engine slow response. Always async.

6. **Animating everything.** Fade transitions everywhere look polished but add per-frame cost. Match `patterns/reduced-motion.md` — animations are sparing, justified.

## Related governance

- `governance/testing-strategy.md` — performance tests as part of suite
- `patterns/real-time-data.md` — update-rate discipline
- `rules/data-display-rules.md` — RULE-DATA-002 coalescing

## Changelog

- 2026-04-17: Initial version. Budget table consolidated from multiple rules + UXPM references. Frame breakdown. Specific subsystem rules (charts, stylesheets, signals). Measurement tooling. Future optimizations out of scope.
