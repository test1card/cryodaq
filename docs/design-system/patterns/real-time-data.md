---
title: Real-Time Data
keywords: real-time, live-data, streaming, update-rate, atomic, snap, no-animation, stale-detection, coalesce
applies_to: how live-streaming data updates are displayed
status: canonical
references: rules/data-display-rules.md, cryodaq-primitives/sensor-cell.md, components/chart-tile.md, cryodaq-primitives/top-watch-bar.md
last_updated: 2026-04-17
---

# Real-Time Data

Rules for displaying live data streaming from the engine: temperature readings, pressures, SMU measurements, safety states, heartbeats. Tightly constrained because this data drives operator decisions in seconds, and visual glitches or stale values cost real experiment time.

## The constraint: operator trust

Operator must trust that:
1. The value on the screen is the most recent value received from the engine.
2. If a value is stale or missing, the display says so — does not silently hold old values.
3. The display does not lie by smoothing, interpolating, or tweening between real samples.
4. Visual changes correspond to actual data changes (no decorative animation).

These constraints feel strict because they exist to prevent trust erosion. Each violation is a small erosion; enough erosions and operator starts second-guessing displays, which costs far more time than the "niceness" of a smooth animation saves.

## Five core rules (from rules/data-display-rules.md)

These are the enforcement layer. This pattern doc explains the reasoning.

1. **RULE-DATA-001 — Updates are atomic.** Value + border + status color change together in one frame. No "value updates now, color updates in 100ms".
2. **RULE-DATA-002 — Update rate ≤ 2 Hz.** UI refreshes at most twice per second regardless of engine sample rate. Coalesce faster streams.
3. **RULE-DATA-003 — No jitter.** Digit widths, axis widths, chart areas stable across updates.
4. **RULE-DATA-004 — Fixed precision per quantity.** Temperature `{:.2f}`, pressure `{:.2e}`, voltage `{:.3f}`. Same format every frame.
5. **RULE-DATA-009 — No animation on live data.** Snap to new value. No tween, no count-up, no interpolated smoothing.

## The update pipeline

Engine produces data → GUI consumes and renders. Key stages:

```
Instrument driver (LakeShore/Keithley/Thyracont)
       │ (hardware poll — may be 10 Hz or more)
       ▼
Scheduler (persistence-first: write SQLite BEFORE broker publish)
       │
       ▼
DataBroker (in-engine pub/sub)
       │
       ▼
ZMQ PUB (engine → GUI transport)
       │
       ▼
GUI ZMQ SUB
       │
       ▼
Coalescing layer (max 2 Hz)
       │
       ▼
Widget.set_value(...) — atomic update
```

Each arrow is a potential drift or failure surface. Key invariants at each stage:

- **Persistence-first** (codebase absolute rule): data is in SQLite before GUI ever sees it. If GUI shows X, SQLite has X.
- **Coalescing** at GUI: if engine publishes 10 Hz and UI can render 60 Hz, UI still updates at 2 Hz. See "Coalescing pattern" below.
- **Atomic widget update:** all visual fields (value, color, border, tooltip) update in one Qt event loop tick.

## Coalescing pattern

When data arrives faster than the 2 Hz render budget, coalesce: drop intermediate samples, render only the most recent at the tick boundary.

```python
class CoalescingUpdater:
    """Holds the latest value, emits at ≤ 2 Hz via timer."""
    
    def __init__(self, widget, interval_ms=500):
        self._widget = widget
        self._latest = None
        self._timer = QTimer()
        self._timer.setInterval(interval_ms)  # 500ms = 2 Hz
        self._timer.timeout.connect(self._flush)
        self._timer.start()
    
    def push(self, value):
        # DESIGN: RULE-DATA-002 — keep latest only
        self._latest = value
    
    def _flush(self):
        if self._latest is not None:
            # DESIGN: RULE-DATA-001 atomic widget update
            self._widget.set_value(self._latest)
            self._latest = None
```

Why 2 Hz: operators can notice and read changes at this rate; faster than 2 Hz the eye can't parse individual values, only motion; motion without parseable values is decorative flicker.

Exception: charts update at their own configured rate (typically also 2 Hz for plot data), but the chart widget's setData is itself atomic per update.

## Stale detection

A value is stale if the GUI hasn't received an update in `stale_timeout_s` (default 10s from safety.yaml). Stale handling:

```python
def _check_staleness(self):
    now = time.time()
    if self._last_update_t is None:
        return  # never had data yet — handle separately (disconnected)
    age = now - self._last_update_t
    if age > self._stale_timeout_s:
        self.set_stale(True)
        # DESIGN: RULE-DATA-001 — set_stale atomically updates color + tooltip
    else:
        self.set_stale(False)
```

**Stale visual treatment** (per `patterns/state-visualization.md`):
- Value text color → STATUS_STALE
- Tooltip: «Данные не обновляются NN секунд»
- No change to value itself (still shows last-known)
- Transition ok → stale is instant; no fade

**Never:**
- Hide stale values (operator can't tell if something broke)
- Reset stale values to 0 or «—» (loses last-known context)
- Show "Loading..." for stale (misleading — data isn't loading, just not arriving)

## Initial-load vs empty-data

On app startup, widgets have no data yet. This is NOT stale (stale = had data, now missing); this is **initial empty**.

Empty state treatment:
- Value text: `«—»`
- Color: TEXT_DISABLED
- Tooltip: «Ожидание первого измерения»

First fresh sample arrives → state transitions to ok. If `stale_timeout_s` elapses without any data → state transitions to stale.

## Chart-specific real-time rules

Per `components/chart-tile.md` and RULE-DATA-008 / 009 / 010:

1. **Time window is fixed** (e.g., 60s rolling). New data pushes old data off the left edge.
2. **Y-axis range behavior:**
   - Auto-range allowed on initial load (to get oriented)
   - Auto-range disabled during live streaming (prevents axis jumping as outliers arrive) — value stays in same axis scale
   - Operator can manually zoom via dedicated analytics view (not dashboard tiles)
3. **Pressure plots mandatory log Y-scale** (RULE-DATA-008).
4. **Point density capped** at `max_points` per series. Deque/ring-buffer of latest N samples.
5. **No trend line smoothing** (would misrepresent noise). Show raw samples.

## Historical playback vs live

Live: newest data on right, rolling window, ≤ 2 Hz refresh, no interaction.

Historical (Analytics panel, archive replay): static data range, full interaction (pan / zoom / cursor tooltip), different rules per `patterns/information-hierarchy.md` Tier-2 content.

Never mix modes in one widget. Either live or historical; switching modes is a deliberate user action, not something the widget does on its own.

## Update frequency by element type

| Element | Update rate | Rationale |
|---|---|---|
| TopWatchBar vitals | 2 Hz | Operator at-a-glance; 2 Hz readable |
| SensorCell values | 2 Hz | Same |
| ChartTile live plots | 2 Hz | Same; coalesce on renderer |
| Historical chart | Once per load | Static data |
| BottomStatusBar heartbeat | 1 Hz | Less critical; clock-like |
| BottomStatusBar time | 1 Hz | Wall clock |
| PhaseStepper state | On change | Event-driven (not polling) |
| ExperimentCard elapsed | 10 Hz counter? NO, 1 Hz | Elapsed minute-counter updates once per second visually |
| Alarms | On change | Event-driven |

"On change" = event-driven, updates when engine publishes a change, not on a schedule.

## Data freshness annotation

For critical decisions, display the freshness alongside the value:

- TopWatchBar: tooltip on hover includes «Последнее обновление: 0.4с назад»
- SensorCell: tooltip includes same
- BottomStatusBar: shows heartbeat interval explicitly

This is operator verification — when in doubt, they can check whether the shown value is trustworthy.

## Ordering guarantees

Two data points from different channels arriving in different orders than they were published: this happens in async ZMQ. UI should render both in the order received, not try to reorder to match timestamps. Each channel is independent; cross-channel ordering is not a product guarantee.

Within a single channel, engine guarantees monotonic timestamps. UI should never display an older value on a channel that already showed a newer one.

## Missing-data handling

If a single sample is missing (dropped):
- UI continues to show last-known value
- Chart shows gap (not connected line) if gap exceeds expected cadence

If the whole channel goes silent (stale_timeout exceeded):
- UI transitions to stale state per above
- Chart shows frozen trailing line; new gap appears on right edge as time advances

## Rules applied

- **RULE-DATA-001** — atomic updates
- **RULE-DATA-002** — ≤ 2 Hz
- **RULE-DATA-003** — no jitter (tabular numbers, fixed axis widths)
- **RULE-DATA-004** — fixed precision per quantity
- **RULE-DATA-008** — pressure log scale
- **RULE-DATA-009** — no animation
- **RULE-INTER-006** — instant fault rendering (applies to state transitions driven by data)
- **RULE-TYPO-003** — tabular-nums for all numeric readouts

## Common mistakes

1. **60 Hz updates "because we can".** Digits flicker faster than eye can read. Stick to 2 Hz.

2. **Tweening between old and new values.** "It looks smoother." No — it lies. The displayed value at t=250ms is not what the engine sees. Snap.

3. **Hiding stale values.** Operator can't tell if system is working or display is broken. Show last-known + stale indicator.

4. **Resetting values to 0 on stale.** Same as hiding; worse because it looks like real data.

5. **Auto-zooming Y-axis on every sample.** Y-axis jumps with every outlier. Disable auto-range during live streaming.

6. **"Loading..." for stale.** Misleading; data isn't loading, just isn't arriving.

7. **Different precision across updates.** "4.21" → "4.2" → "4.213". Variable width causes jitter. RULE-DATA-004 fixed precision.

8. **Mixing live and historical in one widget.** Switching modes mid-view loses context. Separate widgets.

9. **Persisting stale state too aggressively.** Clearing stale only when operator clicks "refresh". Stale clears automatically on fresh data; don't require user action.

10. **Updating at Qt event rate instead of throttled.** Connecting ZMQ SUB directly to widget.setText without coalescing. Use a QTimer-based flush.

## Related patterns

- `patterns/state-visualization.md` — how stale state renders visually
- `patterns/numeric-formatting.md` — precision and unit formatting rules
- `patterns/information-hierarchy.md` — Tier-1 vitals get priority in update scheduling

## Changelog

- 2026-04-17: Initial version. Coalescing pattern. Stale / initial-empty / missing-data handling. Update frequency table per element type. Rationale for 2 Hz cap and no-animation rules.
