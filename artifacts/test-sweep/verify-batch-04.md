# Verify (amend cycle) — Batch 04 — core interlock/memory-leaks/p0-p1/persistence

Codex gpt-5.5 high, READ-ONLY. 7 findings, all test-only fixable. NOTE: F6 required a second
executor pass — the first fix was plausible-but-wrong (caught by independent review). The
flaky persistence-ordering ⭐ rewrite is CLEAN (holds).

## FIXED (test-only)
- **F1 `test_memory_leaks.py:81` rate_estimator_maxlen_from_window** — over-fit (asserted
  private `_maxlen == formula` as oracle). Now behavioral via public `buffer_size()` for a
  small & large window; no formula re-derivation.
- **F2 `test_memory_leaks.py:143` fault_history_deque_has_maxlen_after_update** — over-fit
  (`hist.maxlen == expected_formula`). Now pushes 15k faults via public `record_fault()` and
  asserts `len(hist) <= hist.maxlen` (deque's own cap as bound, behavioral).
- **F3 `test_memory_leaks.py:220` broadcast_pump_drains_queue** — RESIDUAL: ran a LOCAL
  `_pump_with_sentinel()`, never prod. Now imports & starts the REAL
  `cryodaq.web.server._broadcast_pump` with `_state.broadcast_q=q`, waits (bounded) until
  drained, cancels the task.
- **F4 `test_p0_fixes.py:230` alarm_publishes_alarm_count_on_clear** — residual+timing:
  `0.0 in count_values` trivially true (start() publishes 0.0). Now drains initial count,
  deadline-polls until activation observed (asserts active/non-zero), then clear → waits for
  FINAL count==0.0 + active_names==[].
- **F5 `test_p0_fixes.py:427` safety_publish_failure_does_not_crash** — tautology
  (`await_count>=1` already true from start(); state-set allowed no transition). Now captures
  post-start baseline await_count, feeds safety data, waits for READY, asserts await_count
  INCREASED + no task crash.
- **F6 `test_interlock.py:140` test_action_called_async** — RESIDUAL (fire-and-forget would
  also pass). FIRST FIX WAS WRONG: published a 2nd reading on the SAME channel, but the
  interlock latches TRIPPED so count stayed 1 regardless of await-vs-create_task — did not
  distinguish them. REDONE: prod confirmed serial (`_check_loop`→`await _trip`→`await
  action_callable()`, interlock.py:403/451). Now TWO conditions on T1/T2; gate action_a;
  while gated publish T2; assert `pytest.raises(asyncio.TimeoutError)` on action_b_started
  (timeout 0.2) — a fire-and-forget impl would start action_b → no raise → FAIL; release gate
  → assert action_b starts. Genuinely distinguishes the two implementations.
- **F7 `test_interlock.py:310` test_load_config_yaml** — over-fit (read private
  `_interlocks["overheat"].condition`). Now behavioral: drives readings across the YAML
  threshold/pattern (trip / non-match / cooldown / action), no private internals.

## Clean (Codex concurs)
- test_persistence_ordering.py::test_ordering_guarantee_write_before_zmq (the gate-the-write
  ⭐ rewrite holds — deterministic, proves write-before-publish).
- test_on_reading_callback_no_task_when_no_clients; test_broadcast_queue_bounded.

Independently re-verified: 54 pass (4 files) + ruff-clean. F6 redone after independent review
caught a false-confidence first fix. No DEFERRALS.
