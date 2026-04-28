# F3 — Analytics widgets data wiring (overnight Opus batch)

> **Spec authored 2026-04-28 by architect (Claude Opus 4.7 web).**  
> Authoritative for the F3 implementation batch.  
> CC reads ROADMAP.md F3 entry first, then this spec, then begins.

---

## 0. Mandate and shape

This is a **multi-cycle Opus implementation batch** designed to consume
a full quota window with deep reviewer participation. Per widget:
implement → test → Codex audit → Gemini audit → fix findings → commit.
Then a final cross-widget integration audit. **5 review cycles
expected over the night**.

Goal: ship F3 (analytics placeholder widgets → real data wiring) at
production quality, with each individual widget fully reviewed by both
verifiers before integration.

CC discipline: ORCHESTRATION v1.2 fully applies. Each phase's
session-start `git status` + `git log -1 --format='%h %P %s' HEAD`
reset. Use `git rev-list --left-right --count` before any merge.

---

## 1. F3 scope (per ROADMAP.md, refined)

Four placeholder widgets in `src/cryodaq/gui/shell/views/analytics_widgets.py`,
displayed by `AnalyticsView` per phase via `config/analytics_layout.yaml`.

| ID | Widget class | Phase slot | F3 disposition |
|---|---|---|---|
| W1 | `temperature_trajectory` | warmup/main | **WIRE — full implementation** |
| W2 | `cooldown_history` | warmup/bottom_right | **WIRE — full implementation, requires new engine cmd** |
| W3 | `experiment_summary` | disassembly/main | **WIRE — full implementation** |
| W4 | `r_thermal_placeholder` | cooldown/bottom_right | **LEAVE PLACEHOLDER** — depends on F8 (cooldown ML) for R_thermal predictor source. Document explicitly that this is intentional in F3. |

**Plus mandatory dependency:**

| W5 | F4 lazy-open snapshot replay | shell-level | **WIRE — required for non-broken UX of W1/W2/W3.** Without F4, opening Analytics mid-experiment shows empty widgets until next snapshot push. |

F4 is rolled into F3 as a non-optional sub-task. Without it, the
three wired widgets ship broken from the user's perspective.

---

## 2. Out of scope (DO NOT touch)

- F8 cooldown ML predictor upgrade — separate research item
- `r_thermal_placeholder` substantive wiring (W4) — defer to F8
- New engine services beyond `cooldown_history_get` (Section 5)
- AnalyticsView phase routing logic — already shipped in Phase III.C
- `analytics_layout.yaml` schema changes — leave as-is
- Phase II/III other overlay polish — separate backlog

If CC sees an obvious adjacent issue (e.g., bug in
`_PHASE_ALIASES` mapping) — flag it in handoff, don't fix it in
this batch. Scope-fence discipline.

---

## 3. Architectural principles

### 3.1 Setter pattern — preserve

`AnalyticsView` already documents setter pattern (B.8 contract +
III.C additions). Each new widget receives data via:

- A new setter on `AnalyticsView` (e.g., `set_temperature_history()`)
- That setter iterates active widget instances and forwards to those
  exposing a matching method (duck-typing)
- Inactive widgets discarded on layout swap

**Do NOT** change this contract. Do NOT introduce dependency
injection or signal-slot connections that bypass this pattern.
Reason: existing wiring tests rely on it.

### 3.2 Snapshot-then-stream pattern

Each wired widget gets data in two flows:

1. **Initial snapshot** — full historical fetch on widget construction
   (e.g., readings_history call, cooldown_history_get call)
2. **Live stream** — incremental updates as new data arrives via
   normal broker subscriptions (already in MainWindowV2)

For F4 lazy-open replay: shell caches last-known snapshot per
widget ID. New widget instances get cached snapshot + then live
stream attaches.

### 3.3 No engine refactor

Engine receives ONE new command: `cooldown_history_get`. Otherwise
engine is read-only this batch. All other widget data flows from
existing commands (`readings_history`, `experiment_status`).

---

## 4. Per-widget specs

### 4.1 W1 — `temperature_trajectory`

**Phase slot:** warmup / main (1/2 screen).

**Purpose:** Display all temperature channels on a single shared
time axis, full-experiment time window. Read-only. Operator uses
this to visually correlate sample warmup curves across stages.

**Data source:**

- Existing engine command: `readings_history(channels=<all_T>, from=<exp_start>, to=<now>)`
  - Already used elsewhere (e.g., archive overlay). Reuse signature.
- Live stream: existing readings broker subscription forwards to
  `set_temperature_readings()` which already exists per AnalyticsView
  docstring.

**Widget responsibilities:**

- Construct: empty plot canvas, fetch initial snapshot from shell
  cache (via F4 replay), populate plot
- Live update: append-only on each new reading
- Channel selection: show all temperature channels by default. Optional
  toggle in widget header to hide individual channels (deferred — out
  of scope unless trivial).
- Time window: full experiment from start to now. Auto-scale Y per
  channel via channel grouping (cryostat / compressor / detector
  groups already defined).
- Empty state: when no data yet, show "Ожидание данных…" with subtle
  background. Not loud.

**Acceptance criteria:**

1. Widget shows all temperature channels' history when opened
   mid-experiment (F4 dependency)
2. New readings append within 2 seconds of arrival (broker latency
   acceptable)
3. Y-axis scales sensibly per channel group (no single channel
   dominating the plot)
4. Plot is read-only (no zoom/pan unless trivially preserved from
   pyqtgraph default — decision: KEEP default pyqtgraph interactions,
   they're standard scientific plot UX)
5. Tests cover: construction with no data, snapshot replay, live
   append, channel grouping, layout swap discarding instance

**Effort estimate:** ~150 LOC widget + ~30 LOC AnalyticsView setter
delta + ~80 LOC tests.

---

### 4.2 W2 — `cooldown_history`

**Phase slot:** warmup / bottom_right (1/4 screen).

**Purpose:** Show past cooldown durations and trajectories for
comparison. Operator looks at "is this cooldown progressing as
typical for this configuration?".

**Data source:**

- **NEW engine command:** `cooldown_history_get` (Section 5 spec)
- No live stream (historical only — past completed experiments)
- One-shot fetch on widget construction

**Widget responsibilities:**

- Display: scatter or compact bar of past cooldown durations
  (X = experiment date, Y = cooldown duration in hours)
- Optional: overlay current experiment's cooldown progress on the
  same axes if W2 is showing during cooldown phase (CHECK: phase
  slot is warmup, not cooldown — so this overlay is optional polish,
  may defer)
- Click on a past entry: show summary tooltip (date, duration, start
  T, end T)
- Empty state: "Нет завершённых охлаждений" (no past data scenario)
- Limit: most recent N=20 cooldowns, configurable via widget
  constructor

**Acceptance criteria:**

1. Widget fetches `cooldown_history_get` on construction
2. Result list rendered as visual comparison
3. Empty state handled (no past cooldowns)
4. Error state handled (engine command fails — show error banner,
   not crash)
5. Tests: empty result, N=1 result, N=20 result, error response,
   construction without engine connection (uses cached or empty)

**Effort estimate:** ~120 LOC widget + ~40 LOC engine command
+ ~60 LOC tests.

---

### 4.3 W3 — `experiment_summary`

**Phase slot:** disassembly / main (1/2 screen).

**Purpose:** Final summary card after experiment completes. Shows
total duration, phase breakdown, min/max values per critical
channel, alarm count, artifact links. Operator sees this as the
"experiment is over, here's what happened" view.

**Data source:**

- Existing engine commands:
  - `experiment_status` — phase transitions, current phase, start time
  - `readings_history` — for min/max calculation per channel
  - Alarm count: derive from alarm_v2 events log (need to check if
    there's a `get_alarm_history` command; if not, fall back to
    parsing `event_logger` if accessible from GUI)
- One-shot fetch on widget construction
- No live stream (post-experiment view)

**Widget responsibilities:**

- Display sections:
  - Header: experiment ID, sample name, operator name, date
  - Duration: total wall-clock + per-phase breakdown
  - Channel min/max: table of critical channels (T1..T8 cryostat,
    pressure, Keithley power) with min, max, mean over experiment
  - Alarm summary: count by severity (warning/critical), top 3
    alarm names
  - Artifact links: report DOCX path, Parquet path, JSON metadata
    path (if exists, clickable to open file)
- Layout: vertical stack of sections, scrollable if overflow
- Empty state: "Эксперимент не завершён" if entered the slot before
  experiment finalized
- Print/export button: optional, defer if not trivial

**Acceptance criteria:**

1. Widget fetches all required data on construction
2. All sections populated correctly for a finalized experiment
3. Empty state when experiment not yet finalized
4. Artifact links open files via system handler (Qt `QDesktopServices`)
5. Tests: full populated state, empty state, partial data (e.g.,
   no Parquet file), alarm count edge cases (0 alarms, 100+ alarms)

**Effort estimate:** ~200 LOC widget + ~80 LOC tests.

If `get_alarm_history` command absent, add minimal one in this
batch (~30 LOC engine).

---

### 4.4 W4 — `r_thermal_placeholder`

**LEAVE AS PLACEHOLDER.**

**Why:** R_thermal predictor depends on either (a) F8 cooldown ML
upgrade (research item), or (b) new engine service that doesn't
exist yet. Either path is its own separate feature, not part of F3.

**F3 action for W4:**

1. Verify the placeholder still renders (no regression from F3 work
   on W1/W2/W3 setter pattern changes)
2. Update the placeholder text to clarify "data source pending
   (depends on F8)" so operator doesn't think it's broken
3. Add docstring comment in `analytics_widgets.py` referencing F8
   as the unblock criterion

**Tests:** existing placeholder tests should still pass; no new
tests needed.

---

### 4.5 W5 — F4 lazy-open snapshot replay (mandatory dependency)

**Scope:** shell-level snapshot caching, not a widget itself.

**Purpose:** When operator opens AnalyticsView mid-experiment, the
widgets receive zero data because all `set_*` calls happened before
overlay existed. Result: empty widgets until next live update.
Unacceptable UX.

**Implementation:**

- Shell-level cache: dict keyed by setter method name (or widget ID),
  value = last argument passed to that setter
- On AnalyticsView construction (or phase swap creating new widget
  instance), shell replays cached snapshots into the new instance
- Pattern already exists for `set_experiment` per F4 description in
  ROADMAP — extend to other setters

**Affected setters (must replay):**

- `set_cooldown`
- `set_temperature_readings` (new for W1)
- `set_pressure_reading`
- `set_keithley_readings`
- `set_instrument_health`
- `set_vacuum_prediction`
- `set_experiment_status` (used by W3)

**NOT replayed:**

- `set_fault` — fault state is one-shot, replay would be misleading
  if fault has cleared

**Acceptance criteria:**

1. Opening AnalyticsView mid-experiment populates all wired widgets
   with their most recent snapshot
2. Closing and reopening preserves state (cache persists at shell
   level, not view level)
3. Cache invalidates correctly on experiment finalize / new
   experiment start
4. No memory leak: cache holds only most recent snapshot per setter,
   not history
5. Tests: open mid-cooldown shows cooldown progress, close and reopen
   replays, new experiment clears cache

**Effort estimate:** ~120 LOC shell delta + ~70 LOC tests.

---

## 5. New engine command: `cooldown_history_get`

**Source-of-truth:** `src/cryodaq/engine.py` (action handler dispatch).
Pattern: similar to existing `experiment_history_get` if that exists,
or to `archive_query` pattern.

### 5.1 Request

```json
{
  "cmd": "cooldown_history_get",
  "limit": 20,
  "before_timestamp": null
}
```

- `limit` — max entries to return, default 20
- `before_timestamp` — optional, for pagination (reserved for future,
  initial implementation can ignore)

### 5.2 Response

```json
{
  "ok": true,
  "cooldowns": [
    {
      "experiment_id": "exp_2026-04-15_001",
      "sample_name": "carbon-carbon-strap-3",
      "started_at": "2026-04-15T10:23:45+03:00",
      "cooldown_started_at": "2026-04-15T10:31:12+03:00",
      "cooldown_ended_at": "2026-04-15T16:48:09+03:00",
      "duration_hours": 6.28,
      "start_T_kelvin": 295.1,
      "end_T_kelvin": 4.5,
      "phase_transitions": [
        {"phase": "cooldown", "ts": "2026-04-15T10:31:12+03:00"},
        {"phase": "measurement", "ts": "2026-04-15T16:48:09+03:00"}
      ]
    }
  ]
}
```

### 5.3 Implementation source

Mine experiment metadata + phase transition events from existing
SQLite tables (whatever schema captures phase transitions — likely
`event_log` or `experiment_phases` or similar; CC verifies).

**Constraints:**

- Must use existing connection patterns (don't open new connections)
- Must respect WAL mode (SQLite 3.50.4 bug already noted in
  `sqlite_writer.py` warning — read-only access is safe)
- Must filter to experiments where cooldown phase actually completed
  (skip aborted experiments)
- Channel for primary T sensor (start_T_kelvin / end_T_kelvin):
  use Т1 (cryostat top) by convention; if absent, first available
  T channel

### 5.4 Test coverage

- 0 past cooldowns → empty list
- 1 past cooldown → single entry
- 20+ past cooldowns → limited to 20
- Aborted experiment in DB → excluded from response
- Pagination param accepted but unused (returns same result)

---

## 6. Implementation order (5 review cycles)

Sequence designed for reviewer-friendly granularity. Each cycle
ends with Codex+Gemini audit + architect approval before proceeding
to next cycle. **Do not batch multiple cycles** — review per cycle.

### Cycle 1 — F4 lazy-open snapshot replay (foundation)

**Why first:** Other widgets depend on F4 for non-broken UX. If
F4 wrong, all widget tests are misleading.

**Branch:** `feat/f3-cycle1-lazy-replay`

**Scope:** Section 4.5 only (W5).

**Audit triggers:** dual-verifier (full Codex + full Gemini per
ORCHESTRATION §14.2 — public API change to AnalyticsView, new
shell-level cache, multiple file impact).

**Acceptance gate:** all Section 4.5 acceptance criteria pass +
audit findings resolved. Then merge to master before Cycle 2.

---

### Cycle 2 — W1 temperature_trajectory

**Branch:** `feat/f3-cycle2-temperature-trajectory`

**Scope:** Section 4.1 only.

**Depends on:** Cycle 1 merged.

**Audit triggers:** dual-verifier (new widget + new setter on
public API).

---

### Cycle 3 — W2 cooldown_history + new engine command

**Branch:** `feat/f3-cycle3-cooldown-history`

**Scope:** Section 4.2 + Section 5 (engine command).

**Depends on:** Cycle 1 merged.

**Audit triggers:** dual-verifier (new engine action + new widget
+ SQLite read pattern).

**Risk note:** SQLite query design needs Gemini structural review
specifically. Codex will verify literal correctness; Gemini checks
whether the query actually captures "cooldown completed" semantically
(no abort, no engine crash mid-experiment).

---

### Cycle 4 — W3 experiment_summary (and possibly `get_alarm_history` engine command)

**Branch:** `feat/f3-cycle4-experiment-summary`

**Scope:** Section 4.3.

**Depends on:** Cycle 1 merged.

**Audit triggers:** dual-verifier.

**Architect decision point at start of Cycle 4:** does
`get_alarm_history` command exist? If yes, use it. If no, decide
whether to add it in this cycle (recommended — keeps scope local)
or defer (riskier — leaves W3 with placeholder alarm count).
Recommendation in spec: ADD it, ~30 LOC engine.

---

### Cycle 5 — Final integration audit + W4 placeholder polish + docs

**Branch:** `feat/f3-cycle5-integration`

**Scope:**
- Section 4.4 (W4 placeholder text update)
- Cross-widget integration test (open AnalyticsView through full
  experiment lifecycle: cooldown → measurement → warmup → disassembly,
  verify all widgets show correct data per phase)
- CHANGELOG.md entry for F3
- ROADMAP.md F3 entry update (✅ DONE)
- Vault sync trigger (separate session note)

**Depends on:** Cycles 1–4 all merged.

**Audit triggers:** dual-verifier on integration test + docs sync.
Lighter than per-widget cycles since no new code paths.

---

## 7. Test infrastructure expectations

### 7.1 Unit tests per widget

Each widget gets its own test file:
- `tests/gui/shell/views/test_analytics_widget_temperature_trajectory.py`
- `tests/gui/shell/views/test_analytics_widget_cooldown_history.py`
- `tests/gui/shell/views/test_analytics_widget_experiment_summary.py`

Plus updated `test_analytics_view.py` for new setter delegation.

### 7.2 Engine command tests

`tests/test_engine_cooldown_history.py` (new) — covers Section 5.4
test matrix.

### 7.3 Integration test (Cycle 5)

`tests/integration/test_analytics_view_lifecycle.py` (new):
- Mock engine returning realistic phase progression
- Open AnalyticsView at various phases
- Verify correct widgets shown + populated per phase
- Verify F4 replay on mid-experiment open

### 7.4 Pre-existing tests

All 1518+ existing tests must continue passing. Any regression =
STOP, investigate.

---

## 8. Rollback discipline

Each cycle on its own branch. If Cycle N fails review or shows
regression after merge:

- Revert merge commit on master
- Branch retained for fix iteration
- Subsequent cycles wait until rollback resolved

Per ORCHESTRATION v1.2 §13.5, force-push on `feat/f3-cycleN-*`
branches IS allowed during active development. Master is sacred.

---

## 9. Architect review touchpoints

5 architect approval gates (one per cycle). Architect available
synchronously during Vladimir's working hours; async during night
work. CC writes handoff per cycle and STOPS waiting for architect
disposition before merging or proceeding.

Handoffs go to:
`artifacts/handoffs/2026-04-29-f3-cycle{1,2,3,4,5}-handoff.md`
(date assumed; CC adjusts to actual session date).

---

## 10. CHANGELOG and vault expectations

### CHANGELOG.md

Each cycle appends to [Unreleased]:
- Cycle 1: F4 lazy-open snapshot replay
- Cycle 2: F3.W1 temperature_trajectory wired
- Cycle 3: F3.W2 cooldown_history wired + new engine command
- Cycle 4: F3.W3 experiment_summary wired
- Cycle 5: F3 integration + W4 placeholder doc clarification

When all 5 cycles merged, [Unreleased] section will have F3 done.
Architect later promotes [Unreleased] to a tagged release (separate
session, not part of F3).

### Vault sync (deferred to separate session after F3 closes)

- `60 Roadmap/F3 Analytics widgets.md` — new note
- `10 Subsystems/Analytics view.md` — refresh post-F3
- `60 Roadmap/Versions.md` — F3 entry on next release

Vault refresh is NOT part of F3 batch. Triggered by architect after
F3 closes.

---

## 11. Hard stops (any cycle)

- Test regression in any pre-existing test → STOP, investigate
- Engine command schema mismatch with existing patterns → STOP,
  architect re-aligns
- Setter pattern violation suggested by audit → STOP, architect
  decides
- SQLite read pattern conflicts with WAL writer → STOP, architect
  decides
- W4 (R_thermal placeholder) accidentally wired with placeholder
  data source → STOP, this is F8 not F3
- Cycle exceeds 4 hours wall-clock → STOP, present partial state

---

## 12. Final report shape (per cycle)

Each cycle's final report:

```
## Cycle N — <feature> — Final Report

Branch: feat/f3-cycleN-<slug> at <SHA> — pushed, NOT merged.

Commits:
| SHA | Description |
|---|---|
| <SHA> | <subject> |

Tests: <pass>/<total> green.

Files changed: <count>.

Audit verdicts (after Phase 1 audit dispatch):
- Codex: <verdict> — <finding count>
- Gemini: <verdict> — <finding count>

Findings addressed: <list>.
Architect handoff at: <path>.

Open for architect review. DO NOT merge.
```

After architect approval:
- Apply requested fixes (if any)
- Merge with §14.4 divergence check
- Final per-cycle report

---

## 13. Style and discipline reminders

- `# Russian comments` for user-facing strings; English for code
- Type hints mandatory on new public API (setters, engine action handler)
- Docstrings on new widget classes mirror existing analytics_widgets
  patterns
- pyqtgraph for plotting (not matplotlib — already in use)
- pytest fixtures from `tests/conftest.py` (no new fixture frameworks)
- ORCHESTRATION v1.2 fully applies; reference §14 verification
  practices in every CC session start

---

## 14. End of spec

Spec self-contained. CC reads ROADMAP.md F3 entry first, then this
spec, then dispatches Cycle 1 prompt at architect's signal.

Cycle 1 trigger prompt is a separate document (architect issues at
session start time). Do not auto-start Cycle 1 from this spec alone.

---

*Architect: Vladimir Fomenko + Claude Opus 4.7 (web).*  
*F3 batch designed for ~5 review cycles, ~6-9 hours of CC implementation
time, deep Codex+Gemini participation per cycle.*  
*2026-04-28.*
