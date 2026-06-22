# Fix Report — Batch 20

## Per-Finding Table

| # | File:line | Finding | Status | Action |
|---|-----------|---------|--------|--------|
| 1 | `tests/sinks/test_engine_shutdown_drains_dispatch.py:45` | Tests local copy of drain block, not engine.py | DEFERRED-PRODUCTION-BUG/needs-extraction | Cannot reach engine.py drain path without extracting it to a helper (src/ change). Test verifies the copy is correct but divergence from production is the real risk. |
| 2 | `tests/sinks/test_engine_shutdown_drains_dispatch.py:65` | `assert t.cancelled() or t.done()` — completion passes, hides broken timeout | FIXED | Changed to `assert t.cancelled()` with message. Completion-path false positive eliminated. |
| 3 | `tests/sinks/test_engine_summary_metadata_key.py:10` | Hand-builds ExperimentExport; never drives engine.py:2545 finalize path | DEFERRED-PRODUCTION-BUG/needs-extraction | Driving real engine finalize requires a running engine instance — major entanglement without a src/ shim. Test still verifies the dict-get expression is correct; divergence from production usage is the bug risk. |
| 4 | `tests/test_frozen_entry.py:32` | AST check skips `_dispatch` — the actual `__main__` entry | FIXED | Expanded selector to `n.name.startswith("main_") or n.name == "_dispatch"`. `_dispatch` now verified to have `freeze_support()` before heavy imports. |
| 5 | `tests/replay_engine/test_replay_phases.py:302` | `ok is False` passes for unknown cmd too; denylist could be broken | FIXED | Added `assert _is_command_blocked("safety_acknowledge") is True` before the command dispatch, proving the `safety_*` prefix is in the denylist. |
| 6 | `tests/reporting/test_report_generator.py:180` | Live DB left open during generate(); could read live not archive | FIXED | Added `monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")`, delete live DB before `generate()`, assert `"4.30 К"` in doc text (proves T_STAGE read from archive CSV not deleted DB). |
| 7 | `tests/reporting/test_report_generator.py:268` | Only asserts docx/CSV exist; no content assertion | FIXED | Added `monkeypatch` param + env var, assert `"4.30 К"` in doc, assert K1/smua/power, P_MAIN/pressure, T_STAGE in archive CSV text. |
| 8 | `tests/test_instance_lock.py:36` | No assertion — accepts both success and failure | FIXED | Renamed to `test_double_acquire_same_process`, added platform-aware assertion. Empirically verified on Darwin 25.x that macOS flock also fails same-process double-acquire (not per-fd as expected), so asserts `fd2 is None` unconditionally on all platforms. |
| 9 | `tests/sinks/test_rag_index_sink.py:85` | `fake_rebuild` does not record cfg; only asserts success | FIXED | Added `seen: list[dict] = []`, capture in stub, assert `seen == [{}]` to verify empty config fallback path is exercised. |
| 10 | `tests/replay_engine/test_replay_predictor.py:316` | `sleep(0.1)` slow-joiner; no readiness handshake | DEFERRED | Proper handshake requires adding a ready-signal to ReplayEngine (src/ change). Not touched. |

## Files Changed

- `tests/sinks/test_engine_shutdown_drains_dispatch.py` — line 79: `t.cancelled() or t.done()` → `t.cancelled()`
- `tests/test_frozen_entry.py` — lines 41-49: expand `main_funcs` selector to include `_dispatch`
- `tests/replay_engine/test_replay_phases.py` — line 302: add `_is_command_blocked` assertion before dispatch call
- `tests/reporting/test_report_generator.py` — lines 180 and 268: add `monkeypatch`, env var, delete live DB, assert seeded values in doc/CSV
- `tests/test_instance_lock.py` — line 36: rename + assert `fd2 is None` on all platforms (empirically verified on Darwin 25.x)
- `tests/sinks/test_rag_index_sink.py` — line 85: capture cfg in stub, assert `seen == [{}]`

## Pytest Command and Result

```
CRYODAQ_ALLOW_BROKEN_SQLITE=1 pytest \
  tests/sinks/test_engine_shutdown_drains_dispatch.py \
  tests/sinks/test_engine_summary_metadata_key.py \
  tests/sinks/test_rag_index_sink.py \
  tests/replay_engine/test_replay_phases.py \
  tests/reporting/test_report_generator.py::test_report_generation_for_cooldown_template_uses_archive_tables \
  tests/reporting/test_report_generator.py::test_report_generation_can_use_archived_measured_values_without_live_db \
  tests/test_frozen_entry.py \
  tests/test_instance_lock.py \
  -q --no-header
```

Result (non-report tests): `52 passed in 0.60s`
Result (report tests separately): `2 passed in 217.97s`
Combined: all touched tests pass.

## Ruff

```
ruff check <all touched files>  →  All checks passed!
```
