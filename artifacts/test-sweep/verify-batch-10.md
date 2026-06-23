# Verify (amend cycle) — Batch 10 — storage exports/replay + alarm-flow (END tier-0)

Codex gpt-5.5 high, READ-ONLY. 7 findings, all test-only. Codex confirmed CLEAN: parquet
exp_id (exactly 5 ids), runtime parquet/cold-rotation channel-agnostic tests, cold-rotation
index MD5, xlsx truncation-under-patched-cap.

## FIXED (test-only)
- **F1 `test_multiline_persistence.py:41`** — name claimed SCHEDULER write-before-publish
  ordering but only called `SQLiteWriter.write_immediate` directly (reversing scheduler order
  wouldn't fail it). The generic ordering is already proven by
  test_persistence_ordering.py (batch 4, CLEAN). Honestly RENAMED to
  `test_multiline_reading_writes_to_sqlite` + corrected docstring (no false ordering claim).
- **F2/F3 `test_multiline_persistence.py:126/148`** — residual `inspect.getsource` greps;
  real runtime channel-agnostic export (~l167) and rotation (~l233) tests already exist and
  cover the behavior. DELETED both redundant source-grep tests (the sweep's anti-pattern).
- **F4 `test_replay.py:154` test_replay_stop** (tests/storage/) — flaky sleep race + private
  `_running` assert. Now monkeypatches `replay.asyncio.sleep` so the first call sets
  `sleep_started` + blocks on `release`; awaits sleep_started, calls stop() while parked,
  releases, asserts emitted count limited. Teeth: count=1 < 10 unstop.
- **F5 `test_alarm_flow.py:324` test_rate_limit_drops_excess_calls** (tests/agents/assistant/)
  — fixed 10ms sleep hoping 2nd EventBus item drained. Now wraps `_check_rate_limit`, sets a
  `second_dropped` Event on the drop path, wait_for it before asserting await_count.
- **F6 `test_alarm_flow.py:373` test_truncated_response_skips_dispatch** — 50ms sleep then
  assert-not-awaited passed even if handler never ran. Now `generate_called` Event → wait_for →
  assert generate awaited once (handler RAN) → then assert no Telegram dispatch.
- **F7 alarm_flow skip-handling tests (6)** — each had a GOOD `_should_handle(event) is False`
  assertion PLUS a vacuous `publish + sleep(0) + assert_not_awaited` (EventBus drains in a
  separate loop, so it proved nothing). Removed the 6 vacuous blocks; `_should_handle is False`
  retained as the sole, deterministic proof.

Independently re-verified: 57 pass (6 files, -m "not ollama") + ruff-clean, 2× stable (alarm_flow
+ replay determinism holds). Net 2 redundant grep tests deleted. No DEFERRALS.
(Note: my first verification command used a wrong replay path — tests/replay_engine vs the real
tests/storage/test_replay.py — corrected; the executor had edited the right file.)
