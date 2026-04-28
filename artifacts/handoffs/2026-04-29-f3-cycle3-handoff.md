# F3 Cycle 3 (W2 cooldown_history + engine command) — architect review

## Status
COMPLETE-PASSED (audit resolved, 827863a)

## Branch
feat/f3-cycle3-cooldown-history at 827863a
Pushed: yes (force-pushed after audit amend)
Merged: NO — architect reviews in morning per runner §1

## Tests
21 new (8 engine + 13 widget) + 2 updated (test_analytics_widgets.py)
Full suite: 1860 passed, 0 new failures (pre-amend baseline)
Pre-existing failures: timezone-drift (test_experiment_overlay.py) +
  flaky ZMQ timing test (passes in isolation — resource contention in suite)

## Audit results (Codex + Gemini)

### CRITICAL — RESOLVED
**Gemini #1**: `list_archive_entries()` called sync inside async handler.
Fix: wrapped in `await asyncio.to_thread(experiment_manager.list_archive_entries, ...)`
at engine.py where it was previously called inline.

### MEDIUM — DEFERRED TO ARCHITECT
**Codex #1**: Spec §5.3 says "if T1 absent, use first available T channel".
Current implementation returns `None` on missing T1. Current test at
`tests/test_engine_cooldown_history.py::test_t1_missing_returns_none_not_crash`
asserts `None` and passes. Two options:
  a) Clarify spec §5.3 to say "missing T1 → None" (minimal change)
  b) Implement first-available-T fallback + add tests (spec-literal)
Recommendation: accept option (a) — fallback adds noise with negligible value.

### LOW — RESOLVED
**Codex #2**: `CooldownHistoryWidget` hard-coded `limit=20` in `_fetch_history()`.
Fix: added `limit: int = 20` kwarg to `__init__`, stored as `self._limit`, used
in the ZMQ command payload. Two new tests:
`test_construction_limit_kwarg_forwarded_to_cmd` + `test_construction_default_limit_is_20`.

## Implementation summary

### Architecture discovery
Spec §5.3 assumed phase transitions live in SQLite tables. Reality:
phase history is stored in JSON metadata files at
`data_dir/experiments/{experiment_id}/metadata.json` — same files
that `list_archive_entries()` reads. Implementation correctly uses
this pattern rather than SQLite queries for phase data.

### What changed

**src/cryodaq/engine.py** (+92 LOC)
- Added `_run_cooldown_history_command(cmd, experiment_manager, writer)`:
  module-level async function per the codebase's pattern (see
  `_run_experiment_command`, `_run_operator_log_command`, etc.)
- Dispatched from `_handle_gui_command` via one-line delegation
- `list_archive_entries` wrapped in `asyncio.to_thread` (post-audit fix)
- Reads metadata JSON per experiment, filters to COMPLETED with cooldown.ended_at
- Gets T1 readings from writer.read_readings_history (WAL-safe per spec §5.3)

**src/cryodaq/gui/shell/views/analytics_widgets.py** (+93 LOC)
- Added `CooldownHistoryWidget` (one-shot fetch, scatter plot, empty/error states)
- `limit` constructor kwarg forwarded to ZMQ command (post-audit fix)
- Changed `register(WIDGET_COOLDOWN_HISTORY, ...)` from placeholder to real widget

**tests/test_engine_cooldown_history.py** (new, +249 LOC)
- 8 tests covering spec §5.4 matrix exactly

**tests/gui/shell/views/test_analytics_widget_cooldown_history.py** (new, +207 LOC)
- 13 widget tests (10 original + 2 limit tests added post-audit)

**tests/gui/shell/views/test_analytics_widgets.py** (updated)
- Removed cooldown_history from placeholder parametrize
- Added type check for CooldownHistoryWidget

## Spec deviations
- Phase data from JSON not SQLite (per discovery — architecture clarified).
  This satisfies the spec's intent; JSON is the actual storage mechanism.
- T1 fallback: spec §5.3 implies "use first available T if T1 absent".
  Implementation returns None. Deferred to architect (see MEDIUM above).

## Architect decisions needed (morning)
1. T1 fallback (MEDIUM/Codex): accept None-on-missing-T1 or implement fallback?
   Recommendation: accept None, update spec §5.3 note.
2. Cycle 3 merge order: independent of Cycle 2. Can be merged in any order.

## Files changed
| File | LOC delta | Notes |
|---|---|---|
| src/cryodaq/engine.py | +92 | _run_cooldown_history_command + asyncio.to_thread fix |
| src/cryodaq/gui/shell/views/analytics_widgets.py | +93 | CooldownHistoryWidget + limit kwarg fix |
| tests/test_engine_cooldown_history.py | +249 | Engine tests |
| tests/gui/shell/views/test_analytics_widget_cooldown_history.py | +207 | Widget tests (13 total) |
| tests/gui/shell/views/test_analytics_widgets.py | +17 / -5 | Updated |

## Commits on branch
| SHA | Subject |
|---|---|
| 827863a | feat(analytics): W2 cooldown_history widget + cooldown_history_get engine cmd (F3-Cycle3) |
