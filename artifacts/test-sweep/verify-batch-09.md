# Verify (amend cycle) — Batch 09 — drivers lakeshore/thyracont/visa + storage/archive

Codex gpt-5.5 high, READ-ONLY. 3 findings, all test-only fixable. Codex confirmed CLEAN (fix-pass
work holds): VISA executor/lock behavioral spies (no residual getsource), archive-reader exact
(timestamp,value) sequences incl. 5-parquet+3-sqlite merge order, KRDG fallback per-channel mapping,
TCP poll/write (Event/wait_for, no sleep flake).

## FIXED (test-only)
- **F1 `test_lakeshore_218s.py:474` ...global_on_uses_curve_and_preserves_metadata** — TAUTOLOGY:
  prod computes the calibrated reading via `store.evaluate(...)` (lakeshore_218s.py:534) and the test
  computed its EXPECTED via the SAME `store.evaluate(...)` → compared prod to itself. Now builds a
  known CalibrationCurve (zone raw[80,90], Chebyshev order 1, coeffs (15.0, 2.0)) and asserts the
  HAND-COMPUTED literal: raw 82.98 → scaled −0.404 → 15.0 + 2.0·(−0.404) = `14.192` (no store.evaluate
  in the assertion). Teeth: +1.0 → FAIL.
- **F2 `test_lakeshore_218s.py:529` ...hybrid_mode_uses_curve_only_for_enabled_channels** — same
  tautology + wrong-raw blind spot (compared value to store.evaluate(reading.raw)). Now asserts CH1
  `raw==82.98`, `raw_source=="SRDG"`, sensor_id, and the independent literal 14.192; non-enabled
  channels not curve-converted. Teeth: +1.0 → FAIL.
- **F3 `test_multiline_reconfigure.py:76` test_reconfigure_refreshes_mock_nominals** — incomplete:
  checked keys 7/14 present + old key 1 absent, but stale keys 2/3/4 could survive. Now
  `assert driver._mock_nominal_lengths_mm == {7: 1350.0, 14: 1700.0}` (whole mapping exact). Teeth:
  stale key → FAIL.

Independently re-verified: 69 pass (5 files, -m "not ollama") + ruff-clean. No DEFERRALS.
