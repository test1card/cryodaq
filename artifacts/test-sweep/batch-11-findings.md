# Batch 11 — tier 1 — agents/assistant (96 tests, 8 files)

Codex gpt-5.5 high, read-only. 0 CRIT / 0 HIGH / 4 MED / 2 LOW. 3 files clean.

## MED
- test_chart_dispatch.py:80 `..._fires_for_composite_status` — sleep(0.1) then assert
  mock called; matplotlib import on slow CI flakes. Fix: await created task / wait_for
  dispatcher._tasks drain.
- test_chart_dispatch.py:94,112,129,143,156 (skip/logging) — fixed sleeps; negative
  asserts can pass before delayed task misbehaves. Fix: await asyncio.gather(*tasks).
- test_diagnostic.py:134,159,182,206,233,252,266 (event-flow) — sleep(0.1/0.15) after
  EventBus publish; queue+background handler races. Fix: wait_for agent._handler_tasks
  or call handler directly.
- test_display_name_resolution.py:220 `..._concurrent_calls_consistent_snapshot` — runs
  2 concurrent calls against unchanged manager; no mutation barrier; doesn't prove
  snapshot coherence. Fix: narrow name OR add controlled rename barrier.

## LOW
- test_chart_dispatch.py:33 `..._returns_bytes_for_valid_data` — only bytes + len>100;
  any blob passes. Fix: assert PNG signature, decode with PIL, check dims/bars.
- test_context_builder_formatting.py:30 `..._two_sig_fig_scientific` — expected
  "1.86e-06" is THREE sig figs ({v:.2e}=2 decimals); contradicts its own claim. Fix:
  rename to "two decimal places" OR use {v:.1e} for true 2 sig figs.

Clean: test_archive_adapter, test_brand_abstraction, test_broker_snapshot
(test_chart_dispatcher_strong_ref: no findings).
