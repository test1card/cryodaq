# CryoDAQ full test-suite adversarial sweep (Codex, batches of ~100)

Goal: review ALL 3251 tests across 297 files for false-confidence (the prior
hardening loop only touched ~20). 35 batches, priority-ordered: tier 0
core/storage/drivers (0-10), tier 1 analytics/agents/replay/etc (11-22),
tier 2 GUI (23-34).

Process per batch: Codex gpt-5.5 high, read-only adversarial review → findings
written to `batch-NN-findings.md` → progress.json advanced. Findings get
verified against code and fixed in a separate pass after the sweep.

Manifest: `manifest.json`. Progress: `progress.json`.

## Findings ledger

| Batch | Tier | Tests | CRIT | HIGH | MED | LOW | Notes |
|------:|:----:|------:|----:|----:|---:|---:|-------|
| 00 | 0 | 98 | 0 | 0 | 4 | 3 | alarm core; 3/7 files clean |
| 01 | 0 | 92 | 0 | 1 | 1 | 4 | HIGH=stale test_sqlite_filters_inf; 5/9 clean |
| 02 | 0 | 100 | 0 | 3 | 2 | 1 | HIGH=leak_rate copied _dispatch (stale), force_kill grep, cooldown latch; 5/10 clean |
| 03 | 0 | 90 | 0 | 1 | 2 | 2 | HIGH=experiment WAL grep; 5/7 clean |
| 04 | 0 | 99 | 0 | 3 | 4 | 3 | HIGH=persistence-ordering race(+flaky), alarm-count-on-clear, broadcast-queue; 6/10 clean |
| 05 | 0 | 93 | 0 | 6 | 8 | 3 | SAFETY: HIGH=rate-limiter 20<60 samples x2, fault-latch contract, RUN_PERMITTED, gpib-seq, graceful-drain; 2/9 clean |
| 06 | 0 | 91 | 0 | 0 | 2 | 2 | MED=WAL-crash-recovery refcount, alarm-clear; 3/6 clean |
| 07 | 0 | 96 | **1** | 4 | 9 | 5 | **CRIT=req-timeout<server-cap CONFIRMED prod bug (architect)**; many ZMQ source-greps + 35s real-timeout flakes; 2/9 clean |
| 08 | 0 | 82 | 0 | 0 | 4 | 5 | drivers; cycle-5 fixes held; MED=_last_v stop/all siblings, idn/source-off mock; 2/7 clean |
| 09 | 0 | 94 | 0 | 2 | 8 | 3 | HIGH=visa usbtmc/rm-lock source-greps (cycle-5 siblings); lakeshore calib value-blind, archive-reader value-blind; 3/8 clean |
| 10 | 0 | 96 | 0 | 0 | 6 | 3 | END tier-0. storage value-blind + multiline grep siblings; agent-flow sleep races; 6/12 clean |
| **T0** | **0** | **1031** | **1** | **20** | **50** | **34** | **tier-0 complete (11 batches): 105 findings; 1 CRIT prod bug** |
| 11 | 1 | 96 | 0 | 0 | 4 | 2 | agents; async-sleep flakes + 2-sig-fig contradiction; 3/8 clean |
| 12 | 1 | 86 | 0 | 5 | 6 | 5 | HIGH=classifier tests w/ unconditional-mock Ollama (semantics untested); router dispatch value-blind; 2/7 clean |
| 13 | 1 | 98 | 0 | 1 | 7 | 1 | HIGH=query-agent timeout-enforcement tests nothing (maybe prod gap); value-blind adapters; 4/9 clean |
| 14 | 1 | 88 | 0 | 1 | 2 | 5 | HIGH=telegram engine-construct = config-parse only; value-blind rag/report; 2/8 clean |
| 15 | 1 | 96 | 0 | 4 | 5 | 1 | HIGH=indexer mock 384d≠prod 1024d (runs fallback not normal path), cli-error imports-only, cached-miss reconnect; 5/11 clean |
| 16 | 1 | 96 | 0 | 3 | 6 | 3 | HIGH=calib atomic-write grep, downsample near-tautology, string-phases if-chunks; 4/8 clean |
| 17 | 1 | 98 | 0 | 3 | 9 | 4 | vacuum_trend hotspot: fit/eta value-blind; cooldown no-model needs T_warm; config all clean; 10/14 clean |
| 18 | 1 | 99 | 0 | 3 | 9 | 5 | HIGH=secret_str token-leak guards source-grep (SECURITY-relevant); launcher source-greps; 1/9 clean |
| 19 | 1 | 96 | 0 | 3 | 2 | 1 | HIGH=replay-predictor mocks thing-under-test, escalation-cancel 0.05s; telegram allowlist+SSL CLEAN; 7/10 clean |
| 20 | 1 | 100 | 0 | 3 | 5 | 2 | HIGH=engine-shutdown-drain copy-of-prod, summary-metadata hand-built, frozen-entry AST misses _dispatch; 7/15 clean |
| 21 | 1 | 92 | 0 | 3 | 10 | 4 | HIGH=web-dashboard stale patch target, launcher-signals assert non-prod _restart_engine; many launcher/zmq source-greps; 4/12 clean |
| 22 | 1 | 82 | 0 | 5 | 4 | 5 | **GUI FIND begins.** HIGH=web XSS-escaping 4x source-grep (SECURITY) + sensor-grid routing guarded-pass; value-blind dashboard widgets; 3/12 clean |
| 23 | 2 | 87 | 0 | 15 | 13 | 6 | GUI widgets: pervasive WIDGET-CONTRACT-WEAK (private-handler calls + private-attr asserts vs rendered text/enabled/stylesheet); phase_aware 14, sensor_cell 6, phase_stepper 3; 2/11 clean |
| 24 | 2 | 60 | **1** | 12 | 8 | 1 | alarm-panel overlay (safety-adjacent). **CRIT=NaN value not coerced→0 (test hides potential prod gap, architect — ledger item 11)**; ACK tests call private _acknowledge vs clicking button; private-state vs rendered cells |
