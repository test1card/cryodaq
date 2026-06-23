# Batch 33 — tier 2 — overview/plot-style/preflight/shift/theme (98 tests, 8 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 3 HIGH / 11 MED / 4 LOW. 3 files clean.
FIND pass only. theme_tokens/theme_loader/plot_style are LEGITIMATE token/governance value tests
(alias-equality encodes backwards-compat contracts) — CLEAN.

## HIGH (3) — preflight safety gate not proven
- test_preflight_dialog.py:67 `error_disables_start` — PREFLIGHT-SAFETY/TIMING: `_start_btn` is disabled
  by DEFAULT (preflight_dialog.py:220), and `_process_workers()` can return without proving completion —
  so the test doesn't prove an ERROR keeps start disabled. Fix: fail if `_pending_checks != 0`, assert the
  Engine/Safety error row + failure summary + start disabled BECAUSE of the error.
- test_preflight_dialog.py:74 `all_ok_enables_start` — MOCK-BYPASS: manually overwrites `_checks` + calls
  private `_rebuild_checks_ui()`, bypassing the real async safety/alarm/diagnostic/disk paths. Fix: feed
  successful command responses + disk state, assert the real gate enables start.
- test_preflight_dialog.py:88 `warnings_allow_start` — MOCK-BYPASS: same manual `_checks` injection. Fix:
  create a warning via mocked alarm/disk/diagnostic response, assert summary + enabled start.

## MED (11)
- test_overview_all_preset.py:93/114/131/147 (all_preset uses_experiment_start / fallback / invalid_start_time
  / minimum_window) — WIDGET-CONTRACT: call private `_on_all_clicked()` directly; the "Всё" button wiring
  (overview_panel.py:1160) could break. Fix: `_btn_all.click()`, assert history/window.
- test_preflight_dialog.py:62 `checks_list_not_empty` — PREFLIGHT-SAFETY: `len(_checks)>0` doesn't prove the
  required safety/disk/alarm checks rendered or gated. Fix: assert named checks + statuses + summary + start state.
- test_shift_handover.py:112/139/178/380 (start accepts / periodic submits / end summary / end saves markdown)
  — WIDGET-CONTRACT: manually enable `_start_btn` + call private `_on_accept()`/`_on_submit()`/`_on_end()`,
  bypassing the QDialogButtonBox/accept wiring (shift_handover.py:152/292/656). Fix: drive the accept button,
  assert payload.
- test_shift_modal.py:12 `periodic_prompt_reentrant_guard` / :25 `periodic_missed_auto_dismisses_dialog` —
  SOURCE-GREP: `inspect.getsource()` text-order / `"reject()"` substring, not runtime behavior. Fix: patch
  ShiftPeriodicPrompt / attach a fake dialog with a reject spy, call `_on_periodic_due()`/`_on_periodic_missed()`,
  assert no-dialog / reject + log payload.

## LOW (4)
- test_overview_all_preset.py:45 `child_status_widget_caches_experiment` — GUARDED-PASS: permanently skipped,
  no live coverage of the child-cache path (overview_panel.py:1606). Fix: delete stale test or rewrite vs
  current `_OrphanedStub` contract.
- test_overview_contract.py:105 `keithley_strip_is_monitoring_only` — absence of private method names doesn't
  prove no start/stop/emergency buttons exist. Fix: assert no rendered QPushButton children/actions.
- test_overview_contract.py:180 `compact_temp_card_emits_toggled_signal` — `mousePressEvent(None)` bypasses Qt
  dispatch. Fix: `QTest.mouseClick(card, LeftButton)`, assert signal.
- test_preflight_dialog.py:57 `creates_without_crash` — `dialog is not None` only. Fix: assert title/loading
  text/disabled start/checklist state.

Clean: test_plot_style.py, test_theme_loader.py, test_theme_tokens.py (legitimate token/governance value tests).
