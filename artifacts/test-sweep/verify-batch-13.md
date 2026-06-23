# Verify (amend cycle) — Batch 13 — agents ollama/periodic-report/query-agent

Codex gpt-5.5 high, READ-ONLY. 4 findings, all test-only. Codex confirmed CLEAN: vacuum_adapter
(eta_seconds==3600.0 + target/trend/confidence), test_smoke_real_ollama (ollama-marked, excluded by
default), periodic_report async tests (bounded wait_for helper, no naked sleeps). The 2 DEFERRED prod
bugs (query timeout enforcement item 4; periodic hour-window suffix item 5) were not touched.

## FIXED (test-only)
- **F1 `test_query_adapters.py:63` test_broker_snapshot_handles_no_data** — removed a vestigial
  `await asyncio.sleep(0)` (blind yield proving nothing; the no-data → None result is the real check).
- **F2 `test_query_adapters.py:355` test_composite_adapter_parallel_fetch** — value-blind: asserted
  adapters awaited but fed None/empty payloads, so dropped merged fields would survive. Now feeds
  non-empty CooldownETA/VacuumETA/alarm/experiment and asserts each merged field on the result.
- **F3 `test_query_agent.py:199` test_query_agent_out_of_scope_historical_response** — incomplete:
  missed broker_snapshot + archive/rag. Now asserts ALL service adapters not-awaited
  (composite/cooldown/vacuum/alarms/experiment/sqlite), broker_snapshot.latest/latest_all/latest_age_s
  not-awaited, and installs archive+rag mocks asserted not-awaited — proves NO fetch for out-of-scope.
- **F4 `test_query_agent_archive.py:131` test_archive_detail_none_renders_not_found** — old assertion
  `"не найден" in prompt` is tautological (that phrase is in the COMMON archive template for found AND
  not-found). Now asserts the None-branch's unique placeholder sentinels (`"(нет данных)"` phases_text,
  `"(не указано)"` cooldown_text) + the requested id "exp-X", and documents inline why "не найден" is
  not asserted. NOTE: a fully-unique not-found data marker would need a src marker in `_fmt_archive_detail`
  (a prod change) — left as a minor src-side improvement; the placeholder asserts have teeth against
  crash/stale-data regressions in the None branch.

Independently re-verified: 40 pass (3 files, -m "not ollama") + ruff-clean. The 2 batch-13 deferred prod
bugs remain deferred (ledger items 4, 5).
