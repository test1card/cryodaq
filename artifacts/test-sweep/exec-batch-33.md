# Batch 33 — Execution Report

Date: 2026-06-23

## Files Touched

- `tests/gui/test_preflight_dialog.py`
- `tests/gui/test_overview_all_preset.py`
- `tests/gui/test_overview_contract.py`
- `tests/gui/test_shift_handover.py`
- `tests/gui/test_shift_modal.py`

---

## Per-File Findings Addressed

### `tests/gui/test_preflight_dialog.py`

**Findings addressed:** LOW :57, MED :62, HIGH :67, HIGH :74, HIGH :88

| Test | Before | After |
|------|--------|-------|
| `test_dialog_creates_without_crash` (:57) | `assert dialog is not None` only | Assert `windowTitle`, `_loading_label` hidden after completion, `_start_btn` exists, named checks populated |
| `test_checks_list_not_empty` (:62) | `len(_checks) > 0` | Assert named checks `Engine подключён` + `Тревоги` present, all statuses valid, `_summary_label` non-empty, start enabled for default (ok) path |
| `test_error_disables_start` (:67) | Start disabled by default — test proved nothing | Assert `_pending_checks == 0` (checks completed), `≥1` error check exists, engine check is error, summary contains `❌`/`ошибки`, start disabled BECAUSE of error |
| `test_all_ok_enables_start` (:74) | MOCK-BYPASS: manually set `_checks` + called `_rebuild_checks_ui()` | Real async path via mocked `send_command`: safety ok + no alarms → assert no errors, summary shows `✅`/`⚠️`, start enabled |
| `test_warnings_allow_start` (:88) | MOCK-BYPASS: same injection | Real alarm response with 1 active alarm via `extra_cmds` → assert alarm check is warning, summary shows `⚠️`, start still enabled |

**Removed import:** `PreFlightCheck` (no longer needed after removing manual injection).

**Teeth-check:** Set `safety_result={"ok": True, "state": "fault_latched"}` in `test_all_ok_enables_start` → `error_checks` assertion failed correctly. Reverted.

---

### `tests/gui/test_overview_all_preset.py`

**Findings addressed:** LOW :45, MED :93/:114/:131/:147

| Test | Before | After |
|------|--------|-------|
| `test_child_status_widget_caches_experiment` (:45) | Permanently-skipped — `_OrphanedStub` has no `_on_refresh_result`/`_cached_active_experiment` | **Deleted** (replaced with comment explaining why); dead coverage kept no value |
| `test_all_preset_uses_experiment_start_when_active` (:93) | `panel._on_all_clicked()` direct call | `panel._btn_all.click()` — tests the `clicked → _on_all_clicked` wiring |
| `test_all_preset_falls_back_to_panel_start_when_no_experiment` (:114) | `panel._on_all_clicked()` direct call | `panel._btn_all.click()` |
| `test_all_preset_handles_invalid_start_time` (:131) | `panel._on_all_clicked()` direct call | `panel._btn_all.click()` |
| `test_all_preset_minimum_window_one_hour` (:147) | `panel._on_all_clicked()` direct call | `panel._btn_all.click()` |

**Deletion rationale for :45:** `_OrphanedStub` (overview_panel.py:1606) replaces `ExperimentStatusWidget` in Phase UI-1 v2. It has no `_on_refresh_result` or `_cached_active_experiment`. The test was permanently skipped with `reason="proper fix in Block B"` — Block B never materialized and the stub contract is frozen. Keeping it as a skip is dead code masking incomplete coverage; deleting is correct.

---

### `tests/gui/test_overview_contract.py`

**Findings addressed:** LOW :105, LOW :180

| Test | Before | After |
|------|--------|-------|
| `test_keithley_strip_is_monitoring_only` (:105) | Absence of private method names (`_on_quick_start`, etc.) | `widget.findChildren(QPushButton)` — assert no button with text matching start/stop/emergency keywords is rendered |
| `test_compact_temp_card_emits_toggled_signal` (:180) | `card.mousePressEvent(None)` bypasses Qt dispatch | `QTest.mouseClick(card, Qt.MouseButton.LeftButton)` with `card.show()` for Qt hit-testing |

**Teeth-check for :180:** Temporarily connected to wrong channel id `"Т2"` → assertion `received == ["Т1"]` failed. Reverted.

---

### `tests/gui/test_shift_handover.py`

**Findings addressed:** MED :112, MED :139, MED :178, MED :380

| Test | Before | After |
|------|--------|-------|
| `test_shift_start_dialog_accepts_with_operator` (:112) | `dialog._start_btn.setEnabled(True)` + `dialog._on_accept()` direct | Keep `_start_btn.setEnabled(True)` (needed — checks not run), drive `dialog._btn_box.accepted.emit()` which is the real `QDialogButtonBox.accepted → _on_accept` wiring |
| `test_periodic_prompt_submits_log_entry` (:139) | `dialog._on_submit()` direct | `dialog.findChild(QDialogButtonBox)` + `btn_box.accepted.emit()` — drives `accepted → _on_submit` wiring |
| `test_shift_end_dialog_generates_summary` (:178) | `dialog._on_end()` direct | `dialog.findChild(QDialogButtonBox)` + `btn_box.accepted.emit()` — drives `accepted → _on_end` wiring |
| `test_shift_end_dialog_saves_markdown_body_to_operator_log` (:380) | `dialog._on_end()` direct | Same `findChild(QDialogButtonBox)` + `btn_box.accepted.emit()` |

**Teeth-check for :178:** Removed `dialog._comment.setPlainText(...)` before emit → `"Штатно, система стабильна" in header` failed. Reverted.

---

### `tests/gui/test_shift_modal.py`

**Findings addressed:** MED :12, MED :25

| Test | Before | After |
|------|--------|-------|
| `test_periodic_prompt_reentrant_guard` (:12) | `inspect.getsource()` text search — static check only | Runtime: set `bar._prompt_pending = True`, patch `ShiftPeriodicPrompt`, call `_on_periodic_due()`, assert no dialog created |
| `test_periodic_missed_auto_dismisses_dialog` (:25) | `inspect.getsource()` substring `"reject()"` | Runtime: set `bar._prompt_pending = True`, attach `MagicMock(spec=QDialog)` as `_prompt_dialog`, patch `ZmqCommandWorker`, call `_on_periodic_missed()`, assert `fake_dialog.reject.assert_called_once()` |

**Thread-safety note:** `ShiftBar.__init__` creates `_periodic_timer`/`_missed_timer` connected to methods that spawn real `ZmqCommandWorker` threads. Tests use `_make_bar_active()` which sets state fields directly (no `_activate_shift` call, no timers started). `finally` blocks stop all three timers (`_tick_timer`, `_periodic_timer`, `_missed_timer`) before the bar is GC'd to prevent `QThread: Destroyed while still running` abort. `_on_periodic_missed` spawns a `ZmqCommandWorker` directly (not via `_send_log_fire_and_forget`) — patched via `cryodaq.gui.zmq_client.ZmqCommandWorker`.

---

## PROD-GAP Section

**None found.** All strengthened assertions pass against production. No safety gate anomalies detected:
- `test_error_disables_start`: engine error correctly disables start after real async completion.
- `test_all_ok_enables_start`: successful safety + no alarms correctly enables start.
- `test_warnings_allow_start`: warnings correctly leave start enabled.

---

## Final Pass/Fail Per File

| File | Result | Tests |
|------|--------|-------|
| `test_preflight_dialog.py` | PASS | 7 passed |
| `test_overview_all_preset.py` | PASS | 5 passed (1 deleted) |
| `test_overview_contract.py` | PASS | 12 passed |
| `test_shift_handover.py` | PASS | 18 passed |
| `test_shift_modal.py` | PASS | 2 passed |

## All-Together Exit Code

```
pytest tests/gui/test_preflight_dialog.py tests/gui/test_overview_all_preset.py \
       tests/gui/test_overview_contract.py tests/gui/test_shift_handover.py \
       tests/gui/test_shift_modal.py -p no:cacheprovider -q
44 passed in 0.64s   ← exit 0
```

ruff: `All checks passed!`
