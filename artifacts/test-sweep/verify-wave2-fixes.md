# VERIFY-WAVE2 Test Sweep Report

Date: 2026-06-23

## Per-Finding Changes

### HIGH-1 — `test_keithley_panel.py`: Replace `_spy_dispatch` with module-level ZmqCommandWorker patch

**Change:** Replaced the old `_spy_dispatch` that monkeypatched the private `_dispatch_command` boundary with a module-level patch of `cryodaq.gui.shell.overlays.keithley_panel.ZmqCommandWorker`. Introduced `_FakeWorker` (captures cmd dict, records `start()` call, exposes `finished.connect`), `_CmdList` (list[dict] subclass that also holds `workers`), and `_spy_by_block` registry so multiple blocks (smua + smub in A+B tests) share one module patch without stomping each other's restore stash. Added `_restore_spy()` to undo the patch in `finally` blocks.

**Prod seam verified:** `_dispatch_command` at line 630 of `keithley_panel.py` constructs `ZmqCommandWorker(cmd, parent=self)`, connects `finished`, appends to `_workers`, calls `.start()`. The fake intercepts at class construction level — `.start()` is verified on every worker, cmd dict content is exactly what the button handler builds.

**All call sites updated:** start (default spins), start (adjusted spins), stop, emergency (ok + cancel), p_spin debounce, limits debounce, suppressed-off, suppressed-fault, A+B start, A+B stop, A+B emergency, teeth-wrong-channel, teeth-wrong-cmd.

**Teeth check:** `test_teeth_wrong_channel_fails` and `test_teeth_wrong_cmd_name_fails` explicitly assert that wrong dicts do NOT match. Cancelling emergency produces `dispatched.workers == []` — confirms no worker created on cancel.

**Result:** 46/46 passed.

---

### MED-2 — `test_main_window_v2_alarms_wiring.py`: ACK button loops non-vacuous

**Change:** In both `test_tick_sets_alarm_connected_true_when_recent` and `test_tick_sets_alarm_connected_false_when_stale`, inject a real v1 alarm via `panel._handle_reading(_alarm_reading("test_alarm_..."))` before checking ACK buttons. Added `assert len(v1_btns) > 0` guard to fail if the button list is still empty after injection. The "stale" test now first creates alarm while connected (so buttons exist), then sets stale/disconnected and checks they are disabled.

**Prod seam verified:** `_handle_reading` in `alarm_panel.py` builds `_AlarmRow(state="active")` and calls `_refresh_table()`, which at line 684 creates a `QPushButton` and appends to `_v1_ack_buttons` when `alarm.state == "active"`. `_alarm_reading()` already present in the file sets `event_type="activated"` which maps to state `"active"`.

**Result:** 7/7 passed.

---

### MED-3 — `test_experiment_overlay.py`: Abort via `_show_more_menu()` not `_on_abort_clicked()` directly

**Change:** `test_overlay_abort_in_more_menu` now patches `QMenu.exec` to capture the menu object, calls `overlay._show_more_menu()`, finds the "Прервать" action in `menu.actions()`, and triggers it. Only then does the ZMQ command land. This proves `_show_more_menu()` actually adds and wires the abort action.

**Prod seam verified:** `_show_more_menu()` at line 922 creates `QMenu`, calls `menu.addAction("Прервать эксперимент")`, connects `abort_action.triggered` to `_on_abort_clicked`. The test now exercises this entire chain.

**Result:** 20/20 passed (experiment overlay file).

---

### MED-4 — `test_main_window_v2_conductivity_wiring.py`: Assert rendered table cells

**Change:** `test_temperature_reading_reaches_overlay` now injects TWO channels (Т1 + Т2) so `_chain` has ≥2 elements and `_update_table` produces at least one data row. After dispatching both readings and calling `_refresh()`, asserts `table.rowCount() >= 1`, then `table.item(0, 1).text() == f"{77.3:.4f}"` (t_hot, col 1) and `table.item(0, 2).text() == f"{4.2:.4f}"` (t_cold, col 2).

**Prod seam verified:** `_update_table` at line 998-1000 of `conductivity_panel.py` sets `_cell(f"{t_hot:.4f}")` at col 1 and `_cell(f"{t_cold:.4f}")` at col 2. Channel pair is (Т1→Т2) since `_chain = ["Т1", "Т2"]`.

**Result:** 8/8 passed.

---

### MED-5 — `test_v0_55_15_audit_fixes.py`: Chat worker-leak uses real `send_query` + real signal emission

**Change:** `test_chat_panel_worker_list_does_not_grow_unbounded` now creates `_FakeWorker(ZmqCommandWorker)` — a proper subclass that calls `super().__init__()` (so shiboken is satisfied), overrides `run()` and `start()` to no-op. Uses `patch(..., side_effect=_fake_worker_cls)` inside `send_query()` so the real prod path runs. After `send_query()`, emits `worker.finished.emit({...})` directly, letting Qt signal system deliver to `_on_response` with correct `self.sender()`. Verifies `_workers == []`, `_inflight is None`, `_input.isEnabled()`, and `len(delete_later_calls) == 3`.

**Prod seam verified:** `_on_response` at line 280-293 of `_assistant_chat_widget.py` calls `isinstance(sender, ZmqCommandWorker)` — passes because `_FakeWorker` is a real subclass. `sender in self._workers` — passes because `send_query` appended the worker. `_workers.remove(sender)` and `sender.deleteLater()` are the cleanup paths under test.

**Result:** 14/14 passed (full v0_55_15 file).

---

### MED-6 — `test_analytics_widget_cooldown_history.py`: Full X series assertion

**Change:** `test_twenty_cooldowns_all_rendered` now asserts the complete X array via `list(xs) == pytest.approx(expected_xs)` where `expected_xs` is all 20 parsed timestamps. Added a full zip loop asserting each `(x, y)` point matches its expected values — a wrong date or reordered entry in any position fails immediately.

**Prod seam verified:** `_on_history_loaded` in `analytics_widgets.py` at line 1377 calls `_dt.fromisoformat(started_at).timestamp()` for each entry's `cooldown_started_at`. Order preserved from input list.

**Result:** 11/11 passed.

---

### LOW-7 — `test_accent_decoupling.py`: Remove fragile `hit_count >= 5` count

**Change:** Removed the `hit_count >= 5` file-count loop from `test_status_ok_still_used_in_status_display_contexts`. The live widget assertion (`assert theme.STATUS_OK in bar._engine_label.styleSheet()`) is sufficient to prove STATUS_OK is still used in status-display contexts. A token rename that removes it from all status labels would still fail this test.

**Result:** 10/10 passed, 2 skipped.

---

### LOW-8 — `test_tool_rail.py`: Assert specific `border-left` declaration

**Change:** `test_set_active_marks_one_button` now asserts `f"border-left: 3px solid {theme.ACCENT_400}"` (the exact declaration set by `_apply_style()`) for active buttons, and `"border-left: 3px solid transparent"` for inactive buttons. This prevents a false positive if ACCENT_400 appeared in hover/background instead of the active indicator.

**Prod seam verified:** `_apply_style()` at line 225-233 of `tool_rail.py` sets exactly `f"border-left: {border}"` where `border = f"3px solid {theme.ACCENT_400}"` when active.

**Result:** 11/11 passed.

---

### LOW-9 — `test_v0_55_6_1_chat_unification.py`: Specific `border-left` for knowledge_base

**Change:** Same fix as LOW-8 — replaced `assert theme.ACCENT_400 in ss` with `assert f"border-left: 3px solid {theme.ACCENT_400}" in ss`.

**Result:** 6/6 passed.

---

### LOW-10 — `test_top_watch_bar.py`: `bar.show()` before `QTest.mouseClick`

**Change:** Both `test_experiment_click_emits_signal` and `test_alarms_click_emits_signal` now call `bar.show()`, assert the target label `isVisible()` and `isEnabled()`, then click. Added `bar.hide()` for cleanup. Without `show()`, Qt does not deliver mouse events to off-screen unparented widgets, making these tests vacuous.

**Result:** 18/18 passed.

---

## Teeth-Checks

- **Keithley HIGH**: `test_teeth_wrong_channel_fails` and `test_teeth_wrong_cmd_name_fails` explicitly assert wrong dict does NOT match. Cancel path asserts `dispatched.workers == []`. Emergency cancel asserts no command created.
- **ACK MED**: `assert len(v1_btns) > 0` guard fails the test if injection doesn't produce buttons.
- **Abort MED**: Asserts menu has the "Прервать" action; fails if `_show_more_menu()` doesn't add it.
- **Conductivity MED**: `assert table.rowCount() >= 1` fails if `_chain` is too short to produce rows.
- **Chat MED**: `assert len(delete_later_calls) == 3` fails if cleanup isn't called.
- **Cooldown MED**: Full zip loop fails on any single point mismatch.

---

## PROD-GAP Section

None. All fixes read production source to identify exact seams and verify expected values.

---

## Per-File Pass/Fail

| File | Result |
|------|--------|
| `tests/gui/shell/overlays/test_keithley_panel.py` | 46 passed |
| `tests/gui/shell/test_main_window_v2_alarms_wiring.py` | 7 passed |
| `tests/gui/shell/test_experiment_overlay.py` | 20 passed |
| `tests/gui/shell/test_main_window_v2_conductivity_wiring.py` | 8 passed |
| `tests/gui/shell/test_v0_55_15_audit_fixes.py` | 14 passed |
| `tests/gui/shell/views/test_analytics_widget_cooldown_history.py` | 11 passed |
| `tests/gui/shell/test_accent_decoupling.py` | 10 passed, 2 skipped |
| `tests/gui/shell/test_tool_rail.py` | 11 passed |
| `tests/gui/shell/test_v0_55_6_1_chat_unification.py` | 6 passed |
| `tests/gui/shell/test_top_watch_bar.py` | 18 passed |

**Total: 151 passed, 2 skipped, 0 failed**

All files ruff-clean (`ruff check` → `All checks passed!`).

All-together exit code: individual processes (Qt segfault on combined run is a known PySide6/macOS teardown artifact unrelated to test logic — each file passes in its own process per task instructions).
