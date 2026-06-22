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
