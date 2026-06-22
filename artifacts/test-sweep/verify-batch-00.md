# Verify (amend cycle) — Batch 00 — alarm core

Codex gpt-5.5 high, READ-ONLY, over the FIX-pass-strengthened files. Hunting only for
problems the FIX pass INTRODUCED (over-fit / over-mock / residual false-confidence /
tautology / weakened test). Codex raised 5; adjudicated against actual code below.

## ACTION = FIX (test-only)
- **F1 (residual false-confidence) — `test_alarm.py:353` `test_event_history_bounded`.**
  VALID. The activated==500 / cleared==500 split is invariant whether or not the deque
  actually evicted: front-eviction preserves the activate/clear alternation, so 1000
  retained from cycles 0-499 (no eviction, only 1000 processed) and 1000 retained from
  cycles 100-599 (200 evicted) both yield 500/500. The test therefore never proves the
  cap was hit. Fix: give each cycle a distinct activated value (e.g. `60.0 + i*0.01`, all
  > threshold 50; clear stays 40.0 < 50), then assert the retained activated events'
  minimum value corresponds to a LATE cycle (>= cycle 100), proving early events were
  evicted. Test-only.
- **F5 (residual false-confidence) — `test_alarm_v2_legacy_cleanup.py:48`
  `test_measurement_thresholds_removed_from_t11_t12`.** VALID. Only inspects top-level
  `cfg["check"]`; production composite alarms nest checks under `cfg["conditions"]`
  (`any_below`/`any_above`, see `alarm_v2.py` composite path), so a measurement composite
  targeting Т11/Т12 would pass undetected. Fix: also walk each `cfg.get("conditions", [])`
  entry, collecting its channel(s) + check, and flag calibrated channels under absolute
  threshold checks there too. Test-only.

## ACTION = FIX (minor de-brittle, optional, keep behavioral)
- **F2 (over-fit to private state) — `test_alarm_v2.py:217`
  `test_threshold_sustained_fires_after_delay`.** PARTIAL. The test correctly uses a fake
  clock and asserts the real behavior (first process()→None, second→"TRIGGERED"); those
  behavioral asserts are the actual proof. Line 217 `assert "drift" in
  state_mgr._sustained_since` is a redundant private-attr assert. Low stakes (a sibling,
  `test_threshold_sustained_resets_on_clear`, also touches `_sustained_since`). Drop line
  217 only; keep the behavioral asserts. Do NOT weaken anything else.

## ACTION = DEFER (needs prod change — NOT auto-fixed)
- **F3 (tautology) — `test_alarm_v2_integration.py:224` `test_alarm_v2_status_shape`** and
  **F4 — `:274` `test_alarm_v2_ack`.** VALID but un-fixable test-only. Both exercise the
  real `AlarmStateManager` (process/get_active/acknowledge) — good — but neither reaches
  the engine command path. F3 in particular RE-IMPLEMENTS the engine's serialization dict
  inside the test and asserts on its own reconstruction (a tautology; comment even says
  "Reproduce the exact serialization the engine handler performs"). The real handlers are
  `_handle_gui_command` `action == "alarm_v2_status"` (engine.py:2347) / `"alarm_v2_ack"`
  (engine.py:2392) — a NESTED CLOSURE inside the engine bootstrap, not importable/callable
  without standing up the full engine. Same monolith-closure pattern already deferred in
  batch 02 (leak-rate `_dispatch`) and batch 18 (`_sensor_diag_tick`). Deferring per the
  TEST-FILES-ONLY guardrail; will NOT deepen the tautology. → added to deferred ledger.

## Clean (Codex concurs)
- `test_phase_alarm_fires_in_correct_phase` — exercises real `tick_alarm()`.
- `test_calibrated_sensor_fault_retained` — retained-rule semantics are the contract.
- `test_advance_phase_command`, `test_alarm_config`, `test_alarm_v2_diagnostic_rule`.

Verdict: 2 test-only fixes (F1, F5) + 1 minor de-brittle (F2); F3/F4 DEFERRED (engine
closure extraction).
