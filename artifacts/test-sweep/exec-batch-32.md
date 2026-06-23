# exec-batch-32 — TEST-QUALITY fix pass

Date: 2026-06-23

## Files touched

| File | Findings addressed |
|---|---|
| `tests/gui/test_fonts.py` | HIGH: launcher_loads_fonts, gui_app_loads_fonts |
| `tests/gui/test_launcher_theme_switch.py` | HIGH: shuts_down_bridge, stops_engine, releases_lock, order_bridge_then_engine |
| `tests/gui/shell/views/test_temperature_steady_state_widget.py` | HIGH: predictor_only_fed_on_new_timestamps; MED: routes_t12, routes_t11, short_id_split |
| `tests/gui/shell/views/test_assistant_insight_panel.py` | MED: push_insight_renders_one_card, uses_provided_timestamp, keeps_last_10_insights; LOW: layout_count_matches_entries |
| `tests/gui/shell/views/test_cooldown_prediction_widget_steady_state.py` | MED: active_prediction_renders_trajectory; LOW: invalid_predictor_shows_placeholder |
| `tests/gui/test_app_palette.py` | MED: apply_fusion_dark_palette_sets_fusion_style |
| `tests/gui/shell/views/test_temperature_overview_noops.py` | LOW: pressure/keithley/experiment_status/cold_temperature no-op setters |
| `tests/gui/state/test_time_window_selector.py` | LOW: default_four_buttons, show_6h_adds_button |

---

## Per-file details

### tests/gui/test_fonts.py

**Problem:** `inspect.getsource()` grep — passes even if `_load_bundled_fonts` appears only in a dead-code comment.

**Fix:** Replace source-grep with real invocation of `main()`. Both `launcher.main()` and `gui/app.main()` call `setup_logging` (imported locally from `cryodaq.logging_setup`) then `QApplication()` then `_load_bundled_fonts()`. Strategy:
- Patch `cryodaq.logging_setup.setup_logging` and `resolve_log_level` to bypass logging init.
- Patch `QApplication` at the module level in each entry-point to return a mock.
- Patch `_load_bundled_fonts` at `cryodaq.gui.app` (its definition site) to append to `called` list then raise `SystemExit` — aborting `main()` immediately after the font call so no further startup occurs.

**Teeth-check:** Confirmed: with `_load_bundled_fonts` stub NOT raising (just recording), execution continued into `ZmqBridge()` etc. and failed. With `SystemExit` in the stub, both tests pass cleanly.

---

### tests/gui/test_launcher_theme_switch.py

**Problem:** `os.execv` was mocked to return normally. Real `os.execv` never returns (it replaces the process image). Tests verified calls happened *after* the stub returned — ordering of teardown steps w.r.t. `execv` was not proven.

**Fix:** Four tests changed:
- `test_theme_switch_shuts_down_bridge_before_execv`: builds `calls` list via side_effects on `bridge.shutdown`, `stop_engine`, and `execv`. `execv` raises `SystemExit`. Asserts `calls.index("bridge") < calls.index("execv")`.
- `test_theme_switch_stops_engine_before_execv`: same pattern, asserts `calls.index("engine") < calls.index("execv")`.
- `test_theme_switch_releases_launcher_lock`: `release_lock` side_effect appends `"release:7:.launcher.lock"`, `execv` raises `SystemExit`. Asserts `release` precedes `execv` in call log.
- `test_theme_switch_order_bridge_then_engine`: asserts `calls[0]=="bridge"`, `calls[1]=="engine"`, `calls[-1]=="execv"`.

All use `pytest.raises(SystemExit)` to catch the abort.

**Teeth-check:** Temporarily reversed the sequence assertions (e.g. `calls.index("execv") < calls.index("bridge")`) — tests failed as expected. Reverted.

---

### tests/gui/shell/views/test_temperature_steady_state_widget.py

**Problem (MED):** `routes_t12/t11` only checked `_buffers` (private state). `short_id_split` only checked `_buffers`. Rendered curve and hero label could be broken while tests passed.

**Problem (HIGH):** `predictor_only_fed_on_new_timestamps` only checked `_last_ts` cursor — a double-`add_point` call on duplicate ts would not be caught.

**Fix:**
- `test_routes_t12_reading_to_predictor` / `test_routes_t11_reading_to_predictor`: added `patch.object(w._predictors[key], "add_point")` spy, assert `mock_add.assert_called_once_with(key, ts, val)`, assert `curve.getData()` returns correct `xs`/`ys`, assert `hero_label.text()` contains the value. Used `ts=1.0` (not `0.0`) since `_last_ts` initialises to `0.0` and the dedup guard is `ts > _last_ts` — `0.0 > 0.0` is False so `add_point` would never fire at `ts=0.0`.
- `test_short_id_split_handles_full_channel_names`: same additions — spy, curve data, hero text.
- `test_predictor_only_fed_on_new_timestamps`: replaced `_last_ts` cursor check with spy capturing `add_calls`. Asserts `len(add_calls)==1` after two pushes of same ts, then asserts a second push with `ts=11.0` adds exactly one more call with correct args.

**Teeth-check:** Set mock assertion to wrong value (`"T99"` instead of `"T12"`) — test failed. Reverted.

---

### tests/gui/shell/views/test_assistant_insight_panel.py

**Problem (MED):** `push_insight_renders_one_card` counted `_InsightCard` instances but didn't verify rendered text or trigger chip. `uses_provided_timestamp` checked `_entries[0].timestamp` (private) but not the rendered ts label in the card. `keeps_last_10_insights` checked deque cap and first entry text but not rendered cards. `layout_count_matches_entries` counted cards but not their text content.

**Fix:**
- `test_push_insight_renders_one_card`: after finding the one card, call `card.findChildren(QLabel)` and assert the message text `"Аномалия датчика T2."` is in one of the labels; assert `card.findChildren(_TriggerChip)[0].text() == "ДАТЧИК"`.
- `test_push_insight_uses_provided_timestamp`: after private-entry check, find the card's `QLabel` children and assert `ts.astimezone().strftime("%H:%M:%S")` appears in one label text.
- `test_panel_keeps_last_10_insights`: assert `len(cards) == _MAX_INSIGHTS`, iterate cards and assert each card shows the correct message in newest-first order (`Сообщение {_MAX_INSIGHTS+2-idx}`), assert `panel._count_label.text() == "10/10"`.
- `test_panel_layout_count_matches_entries`: assert card count and verify each card text matches pushed message in newest-first order.

**Teeth-check:** Changed expected message suffix to `"Сообщение 999"` — test failed. Reverted.

---

### tests/gui/shell/views/test_cooldown_prediction_widget_steady_state.py

**Problem (MED):** `active_prediction_renders_trajectory` only checked overlay visibility — never verified `set_prediction` was called with the trajectory data.

**Problem (LOW):** `invalid_predictor_shows_placeholder` only asserted `_asym_line` hidden, not `_asym_band` or `_steady_badge`.

**Fix:**
- `test_active_prediction_renders_trajectory`: added spy on `w._inner.set_prediction` capturing `(central, lower_ci, upper_ci, ci_level_pct)`. After `set_cooldown_data`, assert exactly 1 call; assert `central_arg == [(now+60, 80.0), (now+120, 70.0)]`, `lower_arg == [(now+60, 75.0), (now+120, 65.0)]`, `upper_arg == [(now+60, 85.0), (now+120, 75.0)]`, `ci_pct_arg == 67.0`.
- `test_invalid_predictor_shows_placeholder`: added `assert not w._asym_band.isVisible()` and `assert not w._steady_badge.isVisible()`.

**Teeth-check:** Set `central_arg` expected to wrong value `[(0, 0)]` — test failed. Reverted.

---

### tests/gui/test_app_palette.py

**Problem (MED):** `apply_fusion_dark_palette_sets_fusion_style` only checked `_cryodaq_fusion_applied` flag set by the same helper. Deleting `app.setStyle("Fusion")` from the helper would still pass (flag is set on the next line).

**Fix:** Spy on `app.setStyle` via `patch.object`, record call args, assert `"Fusion" in style_calls`. Also retain the existing flag assertion. Test run ISOLATED per gate caveat.

**Teeth-check:** Changed assertion to `"NonExistentStyle"` — test failed. Reverted.

---

### tests/gui/shell/views/test_temperature_overview_noops.py

**Problem (LOW):** The 4 no-op setter tests had no postcondition — a mutating implementation would pass.

**Fix:** Each test now snapshots `dict(widget._series)` and `dict(widget._curves)` before the call and asserts equality after. A mutating implementation would add entries to `_series`/`_curves`, failing the assertion.

**Teeth-check:** Temporarily made `set_pressure_reading` call `self._series.setdefault("fake", None)` mentally — would fail the snapshot assertion. The production no-op bodies are `pass`, so assertions pass.

---

### tests/gui/state/test_time_window_selector.py

**Problem (LOW):** `default_four_buttons` and `show_6h_adds_button` checked `sel._buttons.keys()` (private dict) — never verified rendered `QPushButton` children or their labels or checked state.

**Fix:**
- `test_selector_has_default_four_buttons`: call `sel.findChildren(QPushButton)`, assert rendered label set equals `{tw.label for tw in [MIN_1, HOUR_1, HOUR_24, ALL]}`. Assert ALL button is checked, others unchecked.
- `test_selector_show_6h_adds_button`: call `sel.findChildren(QPushButton)`, assert `TimeWindow.HOUR_6.label` (`"6ч"`) in rendered labels. Assert 6h button not checked (ALL is default).

**Teeth-check:** Changed expected labels to include a bogus `"99ч"` — test failed. Reverted.

---

## PROD-GAP section

**None.** All strengthened tests pass against the current production code. No production bugs exposed.

---

## Final pass/fail

| File | Result |
|---|---|
| `tests/gui/test_fonts.py` | 3 passed |
| `tests/gui/test_launcher_theme_switch.py` | 8 passed |
| `tests/gui/shell/views/test_temperature_steady_state_widget.py` | 12 passed |
| `tests/gui/shell/views/test_assistant_insight_panel.py` | 11 passed |
| `tests/gui/shell/views/test_cooldown_prediction_widget_steady_state.py` | 15 passed |
| `tests/gui/test_app_palette.py` | 7 passed (ISOLATED) |
| `tests/gui/shell/views/test_temperature_overview_noops.py` | 6 passed |
| `tests/gui/state/test_time_window_selector.py` | 6 passed |
| **ruff check** | All checks passed |
