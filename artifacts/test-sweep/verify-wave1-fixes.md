# VERIFY-WAVE-1 Fix Report

Date: 2026-06-23

## Summary

10 findings fixed across 10 test files. 147 tests green, 0 failed, 0 prod-gaps.

---

## HIGH Findings

### HIGH #1 — `test_pressure_plot_widget.py` `test_refresh_empty_and_filled`

**Prod value verified:**
`PressurePlot.set_series()` passes raw values to `self._curve.setData(x=..., y=clamped_values)` where `clamped_values = [v if v > 0 else fallback for v in self._last_values]`. However the `PlotWidget` runs in log-Y mode (`setLogMode(y=True)`), so pyqtgraph internally transforms the stored data to log10 when `setData` is called. `getData()` returns the log10-transformed values.

**Teeth-check:** First run asserted `pytest.approx([1e-4, 1e-5])` → FAILED with actual `[-4.0, -5.0]`, confirming the assertion would catch wrong values. Fixed to `pytest.approx([-4.0, -5.0])`.

**Change:** Removed the dual `raw_ok or log_ok` branch. Now asserts:
- `list(xdata) == pytest.approx([1000.0, 1001.0])` — exact paired x
- `list(ydata) == pytest.approx([-4.0, -5.0])` — log10-transformed y (what pyqtgraph actually stores in log-Y mode)

---

### HIGH #2 — `test_conductivity_panel.py` `test_connection_drop_mid_sweep_preserves_stop_button`

**Prod value verified:**
`_on_auto_stop()` dispatches `{"cmd": "keithley_stop", "channel": self._smu_channel()}` where `_smu_channel()` returns `"smua"` (default channel). It also sets `_auto_state = "idle"`, stops `_auto_timer`, and disables `_auto_stop_btn`.

**Change:** Replaced private `panel._on_auto_start()` call with `panel._auto_start_btn.click()`. Extended `_StubWorker.__init__` to capture `cmd` into a `dispatched` list. After `set_connected(False)`, cleared `dispatched` and clicked `_auto_stop_btn`. Now asserts:
- `dispatched == [{"cmd": "keithley_stop", "channel": "smua"}]`
- `panel._auto_state == "idle"`
- `not panel._auto_timer.isActive()`
- `panel._auto_stop_btn.isEnabled() is False`
- `panel._auto_start_btn.isEnabled() is False` (no reconnect)

No PROD-GAP: clicking Stop after disconnect does dispatch `keithley_stop` in prod.

---

## MED Findings

### MED #3 — `test_temp_plot_widget.py` `test_refresh_with_data`

**Prod value verified:**
`TempPlotWidget.refresh()` calls `item.setData(x=xs, y=ys)` with raw values — no transform. TempPlot uses linear Y axis.

**Change:** Replaced independent membership checks with:
- `list(xdata) == pytest.approx([1000.0, 1001.0])`
- `list(ydata) == pytest.approx([77.5, 78.0])`

---

### MED #4 — `test_archive_panel.py` cancel-export "no worker" tests (~:365/:380/:390/:400)

**Prod value verified:**
`_export_workers: list[_ExportWorker]` is a list kept for QThread lifetime management. `_start_export_worker` appends to it; on cancel (empty path returned from dialog), `_start_export_worker` is never reached.

**Change:** Added `assert panel._export_workers == []` to all four cancel tests:
- `test_export_csv_click_cancel_no_worker`
- `test_export_hdf5_click_cancel_no_worker`
- `test_export_xlsx_click_cancel_no_worker`
- `test_export_parquet_click_cancel_no_worker`

---

### MED #5 — `test_mock_scenario.py` `test_vacuum_pressure_decays_into_range`

**Prod value verified:**
`_exp_decay(0, 1e-3, 1e-7) = 1e-3` (exact start), `_exp_decay(1, 1e-3, 1e-7) = 1e-7` (exact end). Both endpoints are mathematically exact from the formula.

**Change:** Bounded BOTH sides within 1% tolerance:
- `1e-3 * 0.99 <= pressures[0] <= 1e-3 * 1.01`
- `1e-7 * 0.99 <= pressures[-1] <= 1e-7 * 1.01`

---

### MED #6 — `test_dynamic_sensor_grid.py` `test_grid_refresh_calls_each_cell`

**Prod value verified:**
`SensorCell.refresh_from_buffer()` calls `self._buffer.get_last(channel_id)`, checks age < 30s, then sets `self._value_widget.setText(f"{value:.2f}")` for values in 0.01..1000 range. Seeds: Т1=77.5 → "77.50", Т2=55.3 → "55.30", Т3=42.1 → "42.10".

**Change:** Seeded `buffer_store` with fresh `time.time()` timestamps and values `{Т1: 77.5, Т2: 55.3, Т3: 42.1}` before the spy loop. After `grid.refresh()` and spy verification, asserts each cell's `_value_widget.text()` contains the formatted value. Keeps the spy call-count check.

---

### MED #7 — `test_quick_log_block.py` `test_max_2_entries_visible`

**Prod value verified:**
`set_entries(entries)` takes the list as-is (no sort) and shows `entries[:2]`. The API contract is "caller provides newest-first".

**Change:** Fixed the timestamp generation from ascending (`17:00..17:19`) to descending (`17:19..17:00`), so Entry 0 genuinely has the latest timestamp and the test proves real newest-first ordering:
```python
{"timestamp": f"2026-04-15T17:{19 - i:02d}:00", "message": f"Entry {i}"}
```

---

## LOW Findings

### LOW #8 — `test_drill_down_breadcrumb.py` `test_breadcrumb_overlay_name_updates_display`

**Prod value verified:**
`_refresh_labels()` computes `available = max(40, self.width() - reserved)` then calls `fm.elidedText(self._overlay_name, Qt.TextElideMode.ElideRight, available)`.

**Change:** Renamed existing test to assert `label_text == new_name` exactly at width=500 (short name fits without elision). Added new test `test_breadcrumb_overlay_name_elided_when_narrow` at width=80 with a long name, computing `expected = fm.elidedText(long_name, ElideRight, max(40, 80 - reserved))` (with `theme.SPACE_5 = 24`) and asserting `label_text == expected`.

---

### LOW #9 — `test_cooldown_footer_v0_55_6_1.py` `test_cooldown_footer_no_arm_handler_attributes`

**Change:** Dropped the three `hasattr` private-attribute checks (`_on_cooldown_arm_clicked`, `_on_cooldown_disarm_clicked`, `_cooldown_arm_btn`). Kept only the widget-tree assertion: no `QPushButton` matching arm/disarm keywords in the cooldown groupbox.

---

### LOW #10 — `test_experiment_card.py` `test_experiment_card_phase_stepper_reflects_current_phase`

**Change:** Removed `assert stepper._current_phase == "measurement"` (private-state line at ~:177). The rendered/style checks on pills already cover the contract.

---

## PROD-GAP Section

None. All findings were fixable to green test assertions matching real prod behavior.

---

## Per-file Results

| File | Tests | Result |
|------|-------|--------|
| `tests/gui/dashboard/test_pressure_plot_widget.py` | 2 | PASS |
| `tests/gui/dashboard/test_temp_plot_widget.py` | 3 | PASS |
| `tests/gui/shell/overlays/test_conductivity_panel.py` | 43 | PASS |
| `tests/gui/shell/overlays/test_archive_panel.py` | 43 | PASS |
| `tests/tools/test_mock_scenario.py` | 8 | PASS |
| `tests/gui/dashboard/test_dynamic_sensor_grid.py` | 5 | PASS |
| `tests/gui/dashboard/test_quick_log_block.py` | 5 | PASS |
| `tests/gui/shell/overlays/_design_system/test_drill_down_breadcrumb.py` | 6 | PASS |
| `tests/gui/shell/overlays/test_cooldown_footer_v0_55_6_1.py` | 11 | PASS |
| `tests/gui/dashboard/test_experiment_card.py` | 21 | PASS |

**All-together exit code: 0** (147 passed, `pytest -q -p no:cacheprovider`)
