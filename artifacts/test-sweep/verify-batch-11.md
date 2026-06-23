# Verify (amend cycle) — Batch 11 — agents/assistant tier-1 (chart/diagnostic/display-name)

Codex gpt-5.5 high, READ-ONLY. 4 findings, all test-only. Codex confirmed CLEAN: PNG test
(asserts \x89PNG + PIL decode + dims), the renamed sig-format test ("two decimal places",
matches {v:.2e}), main chart routing (no fixed sleeps).

## FIXED (test-only)
- **F1 `test_diagnostic.py:29` _drain_handler_tasks helper** — used `sleep(0)` (proves nothing
  if no task yet) + `gather(return_exceptions=True)` (hides handler failures). Now a bounded
  yield-loop until handler tasks exist, then `gather(*tasks)` WITHOUT return_exceptions so a
  handler exception surfaces as a test failure. Fixes all 7 diagnostic event-flow tests.
- **F2 `test_chart_dispatch.py:156` test_log_task_exception_logs_on_error** — `_log_task_exception`
  also logs for a PENDING task (task.result()→InvalidStateError), so it passed without the task
  actually failing. Now `with pytest.raises(ValueError): await task` first, then assert logged.
  Teeth: pending task was a false positive.
- **F3 `test_chart_dispatch.py:169` test_log_task_exception_ignores_cancelled** — cancellation was
  gated by sleep(0.01); a still-cancelling task could log. Now `task.cancel()` +
  `suppress(CancelledError): await task` + `assert task.cancelled()`, then assert no log.
- **F4 `test_display_name_resolution.py:220` concurrent-snapshot** — two concurrent reads against an
  UNCHANGED manager proved only static hints, not snapshot coherence. Now a real rename barrier:
  gate the first `fake_generate` after it captures its prompt, `mgr.set_name("Т12", "Криоплита")`
  (public API), release, capture the second; assert prompt[0] = OLD coherent name, prompt[1] = NEW.
  Teeth: swapping to both-post-rename fails the old-name assert.

Independently re-verified: 59 pass (4 files, -m "not ollama") + ruff-clean, 2× stable. No DEFERRALS.
