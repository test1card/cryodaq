# Batch 34 — Execution Report

Date: 2026-06-23  
Executor: claude-sonnet-4-6

---

## Files Touched

1. `tests/gui/test_zmq_client_data_flow_watchdog.py`
2. `tests/gui/test_vacuum_trend_panel.py`
3. `tests/gui/widgets/shared/test_prediction_widget.py`
4. `tests/gui/widgets/shared/test_pressure_plot.py`

---

## Per-File Changes

### 1. `tests/gui/test_zmq_client_data_flow_watchdog.py`

**Removed** unused `import inspect` (ruff F401).

#### `:109 poll_readings_updates_last_reading_time` (MED)
- **Before:** `assert len(readings) == 1` + `assert bridge._last_reading_time > before` — length only.
- **After:** Added `ChannelStatus` import; assert `r.channel == "T1"`, `r.value == 42.0`, `r.unit == "K"`, `r.status == ChannelStatus.OK`. Malformed Reading fields now fail.

#### `:294 command_channel_stalled_after_recent_timeout` (MED)
- **Before:** Assert `_last_cmd_timeout > 0` and `command_channel_stalled() is True` (bridge-level only, no launcher path).
- **After:** Added B1 launcher behavioral coverage: instantiate `_CmdStalledBridge` + `_Dummy`, call `LauncherWindow._poll_bridge_data(dummy)`, assert `shutdown_calls == 1` and `start_calls == 1`. Proves the launcher actually restarts on command stall.

#### `:396 launcher_poll_logs_reason_distinction` (HIGH)
- **Before:** `inspect.getsource` source-grep for "no heartbeat"/"no readings"/"poll_readings".
- **After:** Full behavioral drive. Two fake bridges:
  - `_HeartbeatStaleBridge` (is_healthy=False, is_alive=True) → assert shutdown+start ≥1, assert "heartbeat" in caplog.
  - `_DataStallBridge` (is_healthy=True, data_flow_stalled=True) → assert shutdown+start ≥1, assert "readings" or "stall" in caplog.
  - Assert the two log outputs differ. Catches wrong-reason logging and missing restarts.

---

### 2. `tests/gui/test_vacuum_trend_panel.py`

#### `:107 eta_display_format` (MED)
- **Before:** `assert len(panel._eta_labels) == 3` only.
- **After:** Assert exact rendered label text per key (sorted ascending by float value, matching panel's `_refresh_eta_labels` sort order):
  - `label_texts[0] == "1.0e-08: —"`
  - `label_texts[1] == "1.0e-05: 1ч 0мин"`
  - `label_texts[2] == "1.0e-03: ✓"`

#### `:132 graph_log_scale` (MED)
- **Before:** `all(-10 < y < 5 for y in ys)` — any 5 Y in range passes.
- **After:** Assert exact `list(xs) == [float(t) for t in extrap_t]` and `list(ys) == extrap_logP`. Assert exact `log10(target)` positions for each target line via `sorted(line.value() for line in panel._target_lines)` vs `sorted(math.log10(float(k)) for k in eta_targets)` with `abs(actual - expected) < 1e-10`.

---

### 3. `tests/gui/widgets/shared/test_prediction_widget.py`

#### `:41 widget_constructs_log_y` (LOW)
- **Before:** `assert w._log_y is True` — private flag only.
- **After:** Assert `left_axis.logMode is True` (actual plot axis). Feed `1e-5`; assert `getData()` returns `log10(1e-5) = -5.0` (pyqtgraph log-Y transform verified).

#### `:51 set_history_populates_curve` (MED)
- **Before:** `assert len(xs) == 5`.
- **After:** Assert exact `xs[i]` and `ys[i]` for all 5 points (`_history(5)` → `(i*60, 100-i*2)`).

#### `:58 set_prediction_populates_all_three_curves` (MED)
- **Before:** `len(cx) > 0`, `len(lx) == len(cx)`, `len(ux) == len(cx)`.
- **After:** Assert exact first/last (x,y) for central, lower, upper curves. Assert CI ordering `ly[i] < cy[i] < uy[i]` at every point — catches swapped bands.

#### `:124 log_y_readout_uses_scientific_notation` (LOW)
- **Before:** `"e" in text` and `"мбар" in text` — any scientific notation passes.
- **After:** `assert text == "3.8e-06 мбар"` — exact value. Wrong value (e.g. "1.0e-05 мбар") now fails.

#### `:138 prediction_readout_shows_all_horizons` (MED)
- **Before:** `row["value"].text() != "—"` and `"67% ДИ" in ci_text` only.
- **After:** Assert exact `f"{100.0 - hrs:.2f} K"` per horizon (central linear interpolation), assert `"± 2.00 K"` in CI text (half_ci = 2.0 from ±2 band). Wrong values and wrong CI widths now fail.

#### `:302 does_not_import_global_window_controller` (MED)
- **Before:** Source-grep for absent strings — indirect subscription undetected.
- **After:** Behavioral test: feed history + prediction, capture X-range and readouts, call `get_time_window_controller().set_window(TimeWindow.HOUR_1)`, assert X-range unchanged (< 1.0s delta) and readouts unchanged. `reset_time_window_controller()` in finally.

---

### 4. `tests/gui/widgets/shared/test_pressure_plot.py`

**Note on pyqtgraph log-Y:** `opts["y"]` is always `None` (pyqtgraph does not store the raw array there). `getData()` returns `(x, log10(y))`. All assertions use `getData()` and account for the log10 transform.

#### `:62 subscribes_to_global_window` (MED)
- **Before:** `assert plot.plot_item is not None` — subscription could be missing.
- **After:** Feed series, call `set_window(HOUR_1)`, `processEvents()`, assert X span `3240 ≤ span ≤ 3960` (3600 ± 10%).

#### `:71 forward_looking_skips_subscribe` (MED)
- **Before:** Source-grep `"if not self._forward_looking"` + no-crash check.
- **After:** Record `(x_lo_before, x_hi_before)`, change window twice, assert `|x_lo_after - x_lo_before| < 1.0` and `|x_hi_after - x_hi_before| < 1.0`. Proves non-subscription behaviorally.

#### `:87 non_positive_values_guarded` (HIGH)
- **Before:** `if raw_y is not None:` guard — silently skips if `opts["y"]` is None.
- **After:** Use `getData()` (always populated). Assert `len(ys) == 3`, all values `isfinite`, and all equal `log10(1e-5) = -5.0` (fallback = min positive = 1e-5, log-Y transforms it). No silent skip possible.

#### `:241 dashboard_pressure_uses_shared_component` (MED)
- **Before:** Source-grep `"PressurePlot"` and import string in module source.
- **After:** Instantiate `PressurePlotWidget(ChannelBufferStore())`, assert `isinstance(widget._shared, PressurePlot)`, feed 3 points via `buf.append`, call `refresh()`, assert `getData()` returns 3 finite log-Y values including `log10(1.2e-5)`.

---

## Teeth-Checks

1. **`test_log_y_readout_uses_scientific_notation`**: Confirmed `text == "3.8e-06 мбар"` (exact). Manually verified wrong value `"1.0e-05 мбар"` raises `AssertionError`.
2. **`test_eta_display_format`**: Swapped eta value `"✓"` → `"—"` confirmed `AssertionError` with message showing the mismatch.
3. **`test_non_positive_values_guarded`**: Confirmed `getData()` returns finite values after clamping; manual `-inf` injection would fail `isfinite` check.

---

## PROD-GAP

**None.** All strengthened tests pass against production code. The watchdog `_poll_bridge_data` correctly:
- Logs "no heartbeat" on heartbeat stale, calls shutdown+start.
- Logs "no readings" on data stall, calls shutdown+start.
- Logs "command channel unhealthy" on B1 stall, calls shutdown+start.

---

## Final Results

| File | Tests | Result |
|------|-------|--------|
| `test_zmq_client_data_flow_watchdog.py` | 21 | ✓ PASS |
| `test_vacuum_trend_panel.py` | 5 | ✓ PASS |
| `test_prediction_widget.py` | 24 | ✓ PASS |
| `test_pressure_plot.py` | 13 | ✓ PASS |
| **All together** | **63** | **✓ EXIT 0** |

ruff: **All checks passed** (0 errors, 0 warnings).
