# Test-sweep FIX pass (Codex paused; Claude fixing)

Strengthening the false-confidence tests found in batches 0-21. One findings-batch per
iteration. Each fix must leave the touched test files GREEN (pytest) and ruff-clean.
Per-batch detail in `fix-batch-NN.md`. Product-code changes are NOT made here (test-quality
only); the ZMQ timeout CRITICAL is held for architect.

| Batch | Findings | Fixed | Deferred | pytest | Notes |
|------:|---------:|------:|---------:|:------:|-------|
| 00 | 7 | 7 | 0 | 68 pass | alarm core; verified independently |
| 01 | 6 | 6 | 0 | 54 pass | storage/calib/channel; stale test_sqlite_filters_inf fixed to match prod (persists OVERRANGE/UNDERRANGE inf) |
| 02 | 6 | 5 | 1 | 48 pass | cooldown/engine/event; agent missed 2 (deep_review, event_logger) → fixed manually. DEFERRED: leak_rate copied _dispatch needs prod extraction (engine.py monolith) |
| 03 | 5 | 5 | 0 | 43 pass | experiment/photos; +bonus: fixed pre-existing isolation bug (test_finalize_builds_archive_snapshot only passed via env-var leakage → now sets CRYODAQ_ALLOW_BROKEN_SQLITE itself). Agent infra hit a transient 403 on 1st try; retry OK |
| 04 | 10 | 10 | 0 | 54 pass | interlock/memory-leaks/p0-p1/persistence. ⭐ persistence_ordering rewritten to gate-the-write: now DETERMINISTIC (3/3 @0.12s, was the flaky 2.0s test that broke Windows CI) AND proves write-before-publish |
| 05 | 17 | 17 | 0 | 77 pass | SAFETY-CRITICAL. rate-limiter now feeds >=60 samples (estimator actually computes); RUN_PERMITTED→FAULT_LATCHED; sequential-connect overlap counter. ZERO prod bugs — production confirmed correct |
| -- | -- | -- | -- | -- | **COMMIT 64590b0: batches 0-5 (full suite 3244 pass), local, push held** |
| 06 | 4 | 4 | 0 | 35 pass | sqlite/sensor-diag/user-prefs; WAL-crash-recovery now real subprocess+os._exit |
| 07 | 19 | 10 | 2 | 58 pass | ZMQ; source-greps→behavioral, vacuum_guard unconditional, is_healthy stale fixed. DEFERRED: CRITICAL timeout-inversion (architect) + shutdown-during-timeout (needs src/ instrumentation). 4 NOT-A-BUG (slow but adequate-slack timeout tests) |
| 08 | 9 | 9 | 0 | 59 pass | drivers keithley/gpib/etalon; _last_v stop/all siblings now non-mock seeded (match cycle-5 single); gpib RM-cache + no-IDN behavioral |
| 09 | 13 | 13 | 0 | 69 pass | lakeshore/thyracont/visa/archive; visa usbtmc/close/rm-lock source-greps→behavioral spy (cycle-5 pattern); lakeshore curve values; archive exact (ts,val) sequences |
| 10 | 9 | 9 | 0 | 59 pass | END tier-0. storage exports/replay + alarm-flow; multiline parquet/cold-rotation +runtime export tests; alarm-flow sleeps→deterministic. parquet exact rows |
| -- | -- | -- | -- | -- | **COMMIT c548d34: batches 6-10 (full suite 3246 pass), local, push held** |
| 11 | 6 | 6 | 0 | 59 pass | tier-1 agents; chart/diagnostic sleeps→deterministic waits; 2-sig-fig test renamed to match prod; display_name concurrent narrowed (executor hit session-limit mid-run, finished after reset) |
| 12 | 16 | 14 | 0 | 71 pass | intent-classifier; mocked-Ollama tests renamed + assert query reached generate; router dispatch sentinels/awaited-args; 1 NOT-A-BUG |
| 13 | 9 | 7 | 2 | 65 pass | ollama/periodic-report/query-agent. ⚠️ 2 NEW DEFERRED-PRODUCTION-BUGS: (1) query format_timeout_s stored but generate() awaited unwrapped → never fires (agent.py:142-148); (2) periodic report hardcodes "(отчёт за час)" ignoring window_minutes (live/agent.py:865) |
| 14 | 8 | 8 | 0 | 78 pass | rag-adapter/report/russification/telegram; engine-construct renamed to config-parse, rag sorted-with-unsorted-input, report mean asserted, exact human timestamp |
| 15 | 10 | 9 | 0 | 40 pass | RAG indexer/searcher/cli/loaders; indexer mock now 1024d (real path not fallback), cli Ollama-error exit codes, cached-miss reconnect, knowledge-loaders source_kind asserted |
