# Verify (amend cycle) — Batch 01 — core storage/calibration/channel-state

Codex gpt-5.5 high, READ-ONLY. 4 findings, all residual false-confidence the FIX pass left
behind. All test-only fixable, none needed src/. SQLite OVERRANGE/UNDERRANGE-inf premise
confirmed correct against sqlite_writer.py (_STATE_CARRYING_STATUSES persists inf, OK
non-finite skipped).

## FIXED (test-only)
- **F1 `test_audit_fixes.py:282` test_sqlite_overrange_inf_persists** — selected the value
  column but never asserted it (a clamped-to-0.0 prod impl would pass). Now asserts
  `math.isinf(rows[0][1]) and rows[0][1] > 0` (line 289).
- **F2 `test_audit_fixes.py:315` test_sqlite_underrange_neg_inf_persists** — same for -inf;
  now asserts `math.isinf(...) and < 0` (line 326).
- **F3 `test_calibration_commands.py:99` test_calibration_curve_export_import** — old assert
  `evaluated_t > 0.0` would pass for any corrupted curve returning a positive dummy. Now
  evaluates ORIGINAL store curve and IMPORTED curve at the same raw input and asserts
  agreement `abs(imported - original) < 1e-9` + isfinite (lines 103-105) — real round-trip
  fidelity.
- **F4 `test_calibration_commands.py:88` test_calibration_curve_list_and_lookup** — single
  curve meant a lookup that ignored channel_key would pass. Now assigns a SECOND curve to
  LS218:CH2 and asserts lookup returns it + `assignment["channel_key"]=="LS218:CH2"`
  (123/144/157).

## Clean (Codex concurs)
- test_channel_state.py (fault count == 1 tests exercise public update→record→get_fault_count).
- test_channel_taxonomy.py (exact Т17..Т24 membership is a config/data contract).

Independently re-verified: 54 pass + ruff-clean. Teeth confirmed by executor (finite-assert
fails for F1/F2; first-curve-id-for-second-key fails for F4). No DEFERRALS.
