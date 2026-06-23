# Verify (amend cycle) — Batch 06 — core sensor-diagnostics/sqlite/user-prefs

Codex gpt-5.5 high, READ-ONLY. 2 findings, both test-only. Codex confirmed the WAL-crash
simulation itself is REAL (child SQLiteWriter on same db path → os._exit(1) → parent reopens,
verifies rows, appends).

## FIXED (test-only)
- **F1 `test_sqlite_writer.py:185` test_wal_recovery_after_crash** — subprocess hang risk: if
  `p.join(timeout=30)` timed out, the live non-daemon child was never reaped → pytest cleanup
  could hang. Added `if p.is_alive(): p.kill(); p.join()` then explicit fail (lines 233-235).
  Crash sim + row-count + append assertions kept. Stress: 3/3 clean, ~0.08s.
- **F2 `test_user_preferences.py:44` test_history_max_limit** — over-fit: drove history via the
  PRIVATE `_add_to_history()`, hiding a regression where the public save path stops recording
  operator history. Now inserts 25 via public `save_last_experiment(operator=...)`, reads
  `get_history("operator")`, asserts exactly `== 20` + newest-first order (Operator-24..05, 04
  evicted).

## Clean (Codex concurs)
- test_sensor_diagnostics_alarm_publishing.py::test_alarm_clears_when_status_returns_to_ok —
  proves no clear during alarm phase, exactly one clear after fresh OK (matches
  sensor_diagnostics.py:349 transition).
- test_user_preferences.py::test_suggest_name_without_map — public fn, exact fallback prefix.

Independently re-verified: 35 pass (3 files) + ruff-clean; WAL subprocess test 3/3 no flake.
No DEFERRALS.
