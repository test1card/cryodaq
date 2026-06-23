# Verify (amend cycle) — Batch 19 — notifications/telegram + replay

NOTE: Codex hit its usage limit mid-batch; this review was done INLINE by Claude (read each
strengthened test, checked the original findings were addressed, hunted for fix-introduced problems),
then independently re-ran. Same criteria as the Codex batches.

VERDICT: **VERIFY PASS — 0 fix-introduced problems.** The fix pass for batch 19 was thorough.

## Reviewed (all CLEAN)
- **test_replay_predictor.py nominal (89) + stuck_plateau (125)** — both now run the REAL
  `_predictor_fires`: they patch `cooldown_predictor.predict` to return a controlled progress (and
  `_try_load_predictor` to a fake model), so the real fire logic executes. nominal → newly_fired==0;
  stuck plateau → newly_fired>0 AND fired records assert channel=="Т11", phase=="cooldown", timestamps
  present. (HIGH findings — _predictor_fires no longer patched to a constant, newly_fired>=0 tautology gone.)
- **test_telegram.py escalation_cancel_stops (376)** — proves the cancel: asserts task in _pending after
  escalate(), then `cancel()` → `task_ref.cancelled()` True + key removed from _pending. No longer a 0.05s
  wait where a no-op cancel passes (the 60-min-delay event is genuinely cancelled).
- **test_telegram.py escalation_chain_sends (346)** — gathers all _pending tasks directly
  (`await asyncio.gather(*pending_tasks)`) instead of sleep(0.05).
- **test_replay_engine first_reading_pub (155)** — honestly RENAMED from "heartbeat" (it asserts the
  first-reading PUB multipart, the precondition for heartbeats). The sleep(0.05) is a ZMQ slow-joiner
  connect-settle, not the assertion sync (data wait uses wait_for, 2s).
- **test_replay_engine curve_data_pub (294)** — requires `{Т12,Т11} <= channels` (both, not one-OR),
  uses a deadline readiness loop (poll until both seen) instead of a fixed sleep, AND asserts decoded
  values: each reading has numeric "v" in [4, 305] K.

Independently re-verified: 38 pass (3 files, -m "not ollama") + ruff-clean. No fixes needed, no DEFERRALS.
(Security tests test_telegram_allowlist + test_telegram_ssl_verification were already CLEAN per the FIND pass.)
