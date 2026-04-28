# F3 Cycle 1 (F4 lazy-open snapshot replay) — architect review

## Status
COMPLETE-PASSED

## Branch
feat/f3-cycle1-lazy-replay at c66fee2 (final fix-up commit)
Pushed: yes
Merged: YES — merged to master at a0dd5e8 (2026-04-29 overnight run)

## Tests
18/18 green at final commit (new tests).
Pre-existing tests: regression count = 0.
Failing tests (pre-existing, not introduced by this cycle):
  - tests/gui/shell/test_experiment_overlay.py::test_format_time_same_day_returns_hh_mm
    → timezone drift test, fails after local midnight ("вчера 22:17" vs "22:17").
    Verified pre-existing on master before any changes were stashed.

Full suite: 1844 passed, 1 failed (pre-existing), 4 skipped.

## Audit history
| Iteration | Codex verdict | Codex findings | Gemini verdict | Gemini findings | Action |
|---|---|---|---|---|---|
| 1 | FAIL | CRITICAL: keithley guard over-broad; HIGH: missing exp_old→exp_new test | GAPS | INCONSISTENCY: keithley pattern; DEAD-END: dead pop; GAP: health/vacuum deferred | Applied CRITICAL+HIGH fixes; documented INCONSISTENCY justification; removed dead pop |
| 2 | PASS | None | COHERENT | INCONSISTENCY accepted (justified); Issues 2+3 confirmed resolved | Merged to master |

## Implementation summary

### What changed
**src/cryodaq/gui/shell/main_window_v2.py** (+103 LOC, -21 LOC)
- Added shell-level snapshot cache fields in `_build_ui`:
  - `_analytics_snapshot: dict[str, tuple]` — last-value per setter name
  - `_analytics_temperature_snapshot: dict[str, Reading]` — accumulating
  - `_analytics_keithley_snapshot: dict[str, Reading]` — accumulating
  - `_analytics_last_exp_id: str | None` — for invalidation detection
- Added `_push_analytics(setter_name, *args)` helper — caches + forwards
- Added `_ensure_overlay("analytics")` replay block: replays phase +
  all cached setters + accumulating dicts into freshly-created view
- Updated `_adapt_reading_to_analytics`: removed early-return None guard;
  set_cooldown now routed via `_push_analytics` (cache survives no-view state)
- Added pressure routing: `unit=="мбар" and channel.endswith("/pressure")`
  → `_push_analytics("set_pressure_reading", reading)`
- Added keithley routing: `smua|smub` + measurement suffix
  → `_analytics_keithley_snapshot[channel] = reading` + forward
- Added cache invalidation in `_on_experiment_status_received`:
  clears cooldown, temperature, keithley caches on experiment_id change

**tests/gui/shell/test_main_window_v2_f4_lazy_replay.py** (new, +447 LOC)
- 18 tests covering all §4.5 acceptance criteria

**docs/decisions/2026-04-29-session.md** (new)
- Session decision ledger for overnight run

### Spec deviations
- `set_instrument_health` routing: NOT added. Data source channel name
  unknown without runtime observation or engine grep. Deferred.
  ARCHITECT DECISION NEEDED: what channel publishes instrument health dict?
- `set_vacuum_prediction` routing: NOT added. Same reason.
  ARCHITECT DECISION NEEDED: what channel publishes vacuum prediction dict?
- Both deferred widgets (SensorHealthSummaryWidget, VacuumPredictionWidget)
  continue to work as before — they display empty/default state since their
  setters were never called from the shell. This is a pre-existing gap from
  Phase III.C, not a regression.

## Architect decisions needed (morning)

1. **iv7 stale worktree**: `experiment/iv7-ipc-transport` is 5+ days old.
   Abort per ORCHESTRATION §5.3, or keep for later merge? Flagged in
   master summary.

2. **Instrument health channel name**: What channel/mechanism feeds
   `set_instrument_health(health: dict[str, str])` on AnalyticsView?
   Currently no caller exists. Without this knowledge, the health cache
   cannot be populated. SensorHealthSummaryWidget remains unrouted.

3. **Vacuum prediction channel name**: What channel feeds
   `set_vacuum_prediction(prediction: dict)` on AnalyticsView?
   VacuumPredictionWidget remains unrouted.

4. **Cycle 1 merge decision**: If both audits PASS, CC will merge
   feat/f3-cycle1-lazy-replay to master per §1 policy and proceed to
   Cycles 2-4. If not convergent, Cycles 2-4 branch from pre-batch master.

## Files changed
| File | LOC delta | Notes |
|---|---|---|
| src/cryodaq/gui/shell/main_window_v2.py | +103 / -21 | Shell-level cache + routing |
| tests/gui/shell/test_main_window_v2_f4_lazy_replay.py | +447 | New test file |
| docs/decisions/2026-04-29-session.md | +36 | Decision ledger |

## Commits on branch
| SHA | Subject |
|---|---|
| 5aad40d | feat(analytics): F4 lazy-open snapshot replay — shell-level cache (F3-Cycle1) |
