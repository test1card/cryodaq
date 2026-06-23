# Verify (amend cycle) — Batch 12 — agents intent-classifier / query router

Codex gpt-5.5 high, READ-ONLY. 5 findings, all test-only. Codex confirmed CLEAN: the renamed
classifier mocked-parse tests (honest "parses mocked X" + assert query reached generate + parsed
category/source-kind), knowledge-query parse tests, eta_vacuum/range_stats router (sentinel + exact
args eta_to_target(1e-6)/range_stats("T_cold",60)), key-temps exact values, empty-snapshot consumer
wait_for. The deferred batch-07 timeout-layer CRITICAL was not re-opened.

## FIXED (test-only) — router dispatch: key-existence/non-exact-awaited → sentinel-identity + exact args
- **F1 eta_cooldown (~l284)** — `assert_awaited_once()` ignored args (prod `CooldownAdapter.eta()`
  takes none). Now `result["cooldown_eta"] is eta` + `eta.assert_awaited_once_with()`.
- **F2 composite_status (~l293)** — key-only ({...:None} would pass). Now `is sentinel_composite` +
  `composite.status.assert_awaited_once_with()`.
- **F3 alarm_status (~l329)** — payload propagation untested. Now `result["alarm_result"] is
  sentinel_alarm` + `alarms.active.assert_awaited_once_with()`.
- **F4 phase_info (~l339)** — `_make_adapters` returned None so a hard-coded None passed. Now
  `experiment.status = AsyncMock(return_value=sentinel_status)`, `is sentinel_status` +
  `experiment.status.assert_awaited_once_with()`.
- **F5 current_value (~l379)** — key-only; didn't prove channel propagation. Now
  `result["readings"]["T_cold"] is reading`, `result["ages_s"]["T_cold"] == 5.0`,
  `snap.latest.assert_awaited_once_with("T_cold")` + `latest_age_s.assert_awaited_once_with("T_cold")`.

Independently re-verified: 28 pass (test_intent_classifier.py, -m "not ollama") + ruff-clean. No DEFERRALS.
