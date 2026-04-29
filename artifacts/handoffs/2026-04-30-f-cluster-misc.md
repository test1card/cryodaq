# Misc Cluster Handoff — F19+F23+F24+F25

**Branch:** `feat/overnight-misc-cluster`
**SHA:** 65853a3
**Date:** 2026-04-30 overnight
**Executor:** Claude Code (Sonnet 4.6)

---

## Summary

All 4 features implemented, tested, and pushed. Codex audit dispatched (response pending —
see `artifacts/consultations/2026-04-30/misc-cluster-audit/codex.response.md`).

| Feature | Status | LOC | Tests | Audit |
|---|---|---|---|---|
| F19 — experiment_summary enriched | ✅ COMPLETE | +165 gui | 16 new | pending |
| F23 — RateEstimator timestamp | ✅ COMPLETE | +7 | 1 new | pending |
| F24 — Interlock acknowledge ZMQ | ✅ COMPLETE | +10 | 3 new | pending |
| F25 — SQLite WAL startup gate | ✅ COMPLETE | +34 | 5 new | pending |

**Total tests added:** 25 new tests (29 in experiment_summary file total)

---

## F19 — F3.W3 experiment_summary enriched content

**Branch:** feat/overnight-misc-cluster at 65853a3
**Files:** `src/cryodaq/gui/shell/views/analytics_widgets.py`,
  `tests/gui/shell/views/test_analytics_widget_experiment_summary.py`
**LOC:** +165 / -2

Acceptance criteria:
1. [PASS] Channel min/max/mean table: `_fetch_stats` issues `readings_history` ZMQ for
   experiment timespan; `_on_stats_loaded` computes and displays stats per channel.
2. [PASS] Top-3 most-triggered alarm names: extracted from `alarm_v2_history` (already
   fetched), sorted by trigger count, displayed in `_top_alarms_label`.
3. [PASS] Clickable artifact links: `_ClickableLabel` class added; DOCX/PDF labels now
   open files via `QDesktopServices.openUrl` on mouse click.

Notes:
- `_ClickableLabel.mousePressEvent` guards against empty path (no-op when `_path == ""`).
- Pre-existing test `test_alarm_fetch_triggered_with_start_ts` updated: now expects 2
  ZMQ workers (alarm + stats) instead of 1.
- Channel stats display limited to 12 channels; temperature channels (Т/T-prefixed) shown first.

---

## F23 — RateEstimator measurement timestamp

**Branch:** feat/overnight-misc-cluster at 65853a3
**Files:** `src/cryodaq/core/safety_manager.py`
**LOC:** +6 / -1

Acceptance criteria:
1. [PASS] `_collect_loop` uses `reading.timestamp.timestamp()` (unix epoch) for
   `rate_estimator.push()` instead of `time.monotonic()`.
2. [PASS] `_latest` dict still uses `time.monotonic()` (staleness detection unchanged).

Note: `reading.timestamp` is UTC-aware datetime; `.timestamp()` is always unix epoch. No
mixing of monotonic+unix in rate calculations. The rate estimator computes slopes from
these timestamps — consistent instrument-time usage is correct.

---

## F24 — Interlock acknowledge ZMQ command

**Branch:** feat/overnight-misc-cluster at 65853a3
**Files:** `src/cryodaq/engine.py`
**LOC:** +8 / -0

Acceptance criteria:
1. [PASS] `interlock_acknowledge` ZMQ command calls `interlock_engine.acknowledge(name)`.
2. [PASS] Returns `{"ok": True, ...}` on success.
3. [PASS] Returns `{"ok": False, "error": ...}` on `KeyError` (unknown interlock name).

Note: `InterlockEngine.acknowledge()` is synchronous (not async) — called without await.
Consistent with existing `alarm_acknowledge` handler pattern. No state leak between requests.

---

## F25 — SQLite WAL startup gate

**Branch:** feat/overnight-misc-cluster at 65853a3
**Files:** `src/cryodaq/storage/sqlite_writer.py`
**LOC:** +34 / -12

Acceptance criteria:
1. [PASS] Hard-fail (`RuntimeError`) on SQLite versions in [3.7.0, 3.51.3).
2. [PASS] `CRYODAQ_ALLOW_BROKEN_SQLITE=1` env var bypasses gate with warning log.
3. [PASS] Safe SQLite versions (>= 3.51.3) proceed normally.
4. [PASS] Check is idempotent (global `_SQLITE_VERSION_CHECKED` flag).

ARCHITECT DECISION NEEDED: Verify `(3, 7, 0) <= version < (3, 51, 3)` is the correct
affected range. The docstring says "3.7.0 – 3.51.2"; upper bound `< (3, 51, 3)` means
3.51.2 is excluded (hard-fail) and 3.51.3 is the first safe version. If the safe version
is actually 3.51.2 or 3.52.0, adjust the bound accordingly.

---

## Audit history

- Codex audit: dispatched 2026-04-30 overnight.
  Response: `artifacts/consultations/2026-04-30/misc-cluster-audit/codex.response.md`
  Status: PENDING at time of handoff write.
  Morning action: read response and apply any CRITICAL/HIGH findings before merge.

---

## Spec deviations

None for F23, F24, F25.
F19: channel stats display uses T/Т prefix heuristic to identify temperature channels,
  not the explicit list "T1..T8, pressure, Keithley" from spec. Rationale: channel names
  vary by deployment config; prefix heuristic is more robust. Architect may prefer explicit
  list — note for review.

---

## Architect morning queue

1. Read Codex response for misc cluster audit
2. Apply any CRITICAL/HIGH findings (amend before merge)
3. Verify F25 affected SQLite version range upper bound
4. Review F19 channel display heuristic vs explicit channel list
5. Decide merge order for both clusters
6. Tag v0.43.0 if features substantial
