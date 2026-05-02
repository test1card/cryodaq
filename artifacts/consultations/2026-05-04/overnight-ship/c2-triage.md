# v0.52.4 GUI consolidation — diagnosis
Date: 2026-05-04

## Working widget reference (dashboard temperature)

File: `src/cryodaq/gui/shell/main_window_v2.py`
Data path: engine ZMQ → broker → `_dispatch_reading()` → EAGER SINK:
  `self._top_bar.on_reading(reading)` (line 390) — always fires
Header values (T2ст, TN₂, P) update from eager sinks that bypass
any `_analytics_view is not None` guard.

## Analytics live panels — "broken" claim investigation

### Analytics Temperature panel (TemperatureOverviewWidget)

File: `analytics_widgets.py:TemperatureOverviewWidget`, `set_temperature_readings()` lines 240-254
Expected path: `main_window._dispatch_reading()` → `analytics_view.set_temperature_readings()`
  → `_forward("set_temperature_readings", readings)` → `widget.set_temperature_readings()`
  → `plot.setData()` immediately

Data path is CORRECTLY WIRED per code analysis:
- main_window line 414: `self._analytics_view.set_temperature_readings({channel: reading})`
- AnalyticsView line 194: `self._forward("set_temperature_readings", readings)`
- TemperatureOverviewWidget line 254: `self._curves[ch_id].setData(x=series.xs, y=series.ys)`

CONCLUSION: **NOT BROKEN.** Widget is live-only (confirmed). "Empty for ≤2s on open"
= expected (first reading arrives within one poll cycle, ~2s). Original triage correct.

### Analytics Pressure panel (PressureCurrentWidget)

WIDGET_PRESSURE_CURRENT is in layout for: `no_experiment` and `vacuum` phases.
NOT in `cooldown` layout (cooldown: main=cooldown_prediction, top_right=temperature_overview,
bottom_right=r_thermal_placeholder).

Debug experiment was in cooldown phase → pressure widget NOT mounted during the session.
User complaint was likely phase confusion.

CONCLUSION: **NOT BROKEN.** Layout correctly excludes pressure during cooldown.

### Verdict on CC_PROMPT "actually broken" claim

**DISAGREE.** Code analysis and original triage (both Codex + Gemini) were correct.
Both live panels work correctly. ≤2s empty = expected. CC recommends:
- No live-panel data flow fix
- Document this finding in commit message

## Cooldown widget placeholder

Current form: **QLabel above PredictionWidget in VBoxLayout**
Location: `analytics_widgets.py:529` — `self._idle_label = QLabel("...")`
Problem: QLabel takes vertical space above plot; plot gets less height
Required form: **pg.TextItem on plot canvas, single line, centered**
PredictionWidget exposes `_plot` (pg.PlotWidget) at line 206.

Fix: remove QLabel, add `pg.TextItem` to `_plot.getPlotItem().getViewBox()`.
Position: (xr_center, yr_center) on `sigRangeChanged`, `anchor=(0.5, 0.5)`.

## TemperatureTrajectoryWidget warmup channel ID mismatch

**CONFIRMED BUG.** File: `analytics_widgets.py:329-345`

```python
channels = self._channel_mgr.get_cold_channels() or None  # returns ["Т1", "Т7", ...]
```

`get_cold_channels()` (channel_manager.py:225-231) returns SHORT IDs from `self._channels`.
`readings_history` ZMQ command filters SQLite data by exact channel label match.
SQLite stores readings under FULL LABELS: "Т7 Детектор", "Т1 Криостат верх".

Short ID "Т7" ≠ "Т7 Детектор" → zero results.
Same class as v0.47.4 BrokerSnapshot fix (documented in CHANGELOG).

Fix: resolve short IDs to full labels via `channel_mgr.get_display_name()` before sending:
```python
cold_ids = self._channel_mgr.get_cold_channels()
channels = [self._channel_mgr.get_display_name(ch) for ch in cold_ids] or None
```

## Unified fix or three separate?

Two separate fixes in one commit:
1. Cooldown placeholder: QLabel → pg.TextItem (UX improvement, analytics_widgets.py)
2. TemperatureTrajectoryWidget: channel ID normalization (bug fix, analytics_widgets.py)

Both in same file, same commit. No fix for live-panel data flow (not broken).

## Proposed fix plan

**Fix 1**: `analytics_widgets.py:CooldownPredictionWidget`
- Remove `self._idle_label` QLabel creation (line 529-534) and `root.addWidget(self._idle_label)` (line 538)
- Remove `root.addWidget(self._inner)` and replace both with just `root.addWidget(self._inner)`
- Add `pg.TextItem` to `self._inner._plot.getPlotItem().getViewBox()` with `ignoreBounds=True`
- Connect `vb.sigRangeChanged` to reposition text at viewport center
- Update `set_cooldown_data()` to call `self._placeholder.setVisible(...)` instead

**Fix 2**: `analytics_widgets.py:TemperatureTrajectoryWidget._fetch_history()` (line 335)
- Change `channels = self._channel_mgr.get_cold_channels() or None`
- To `channels = [self._channel_mgr.get_display_name(ch) for ch in (self._channel_mgr.get_cold_channels() or [])] or None`
