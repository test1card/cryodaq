# Batch 13 — tier 1 — agents: ollama/periodic-report/query-agent (98 tests, 9 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 1 HIGH / 7 MED / 1 LOW. 4 files clean.

## HIGH
- test_query_agent.py:359 `test_query_agent_total_timeout_enforcement` — exercises NO
  timeout; mocks blank formatter + verifies fallback. Production stores _format_timeout_s
  but may NOT enforce it in handle_query (possible minor prod gap). Fix: hang
  ollama.generate under short timeout, assert bounded fallback; implement enforcement if
  required. (lower stakes than batch-07 CRITICAL)

## MED
- test_ollama_client.py:246 `test_smoke_real_ollama` — asserts non-empty/non-truncated;
  any output passes. Fix: assert text.strip()=="PASS".
- test_periodic_report_handler.py:131,148,164,187,202,252 — async sleep(0.05/0.1) races.
  Fix: wait_for on mock await count/state.
- test_periodic_report_handler.py:227 `..._does_not_hardcode_hour_window` — checks prompt
  constants only; production still sends prefix "(отчёт за час)" (agent.py:865) even for
  window_minutes=30/120. Fix: handler test with window_minutes=30 asserting "30 минут";
  derive suffix from window_minutes in prod.
- test_query_adapters.py:152 `test_vacuum_adapter_target_format` — never asserts
  eta_seconds==3600.0. Fix: assert eta_seconds + target/trend/confidence.
- test_query_adapters.py:355 `test_composite_adapter_parallel_fetch` — type+1 temp+empty
  alarms only; doesn't assert each adapter awaited. Fix: keep mocks, assert awaited +
  non-empty merged fields.
- test_query_agent.py:199 `..._out_of_scope_historical_response` — only asserts 2 adapters
  not awaited. Fix: assert NO service adapter called across all.
- test_query_agent_archive.py:131 `..._renders_not_found` — accepts "—" which appears in
  ordinary placeholders. Fix: explicit not-found marker + assert it.

## LOW
- test_query_adapters.py:63 (3 snapshot tests) — fixed sleeps for consume loop. Fix:
  wait_for poll.

Clean: test_output_router_markdown, test_periodic_report_config,
test_periodic_report_context, test_query_agent_knowledge.
