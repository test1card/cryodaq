# F3 Cycle 4 (W3 experiment_summary) — architect review

## Status
COMPLETE-PASSED (audit resolved, 345b6e0)

## Branch
feat/f3-cycle4-experiment-summary at 345b6e0
Pushed: yes (force-pushed after audit amend)
Merged: NO — architect reviews in morning per runner §1

## Tests
21 new widget tests + 2 new routing tests (test_main_window_v2_f4_lazy_replay.py)
Full suite: PASSED (ran after experiment_id fix)

## Audit results (Codex + Gemini)

### HIGH — RESOLVED
**Both auditors**: `active.get("id")` in `_on_experiment_status_received` (line 628)
and `_active_experiment_id` (line 665) always returns `None` — `ExperimentInfo.to_payload()`
emits `"experiment_id"`, not `"id"`. Cache invalidation was broken.
Fix: both sites changed to `active.get("experiment_id")`. All 9 test dicts updated
to use `"experiment_id"` key (they were also testing the wrong key).
Same fix applied to Cycle 5 branch (inherited the bug).

### MEDIUM — DEFERRED / DOCUMENTED
**Codex+Gemini**: Three spec §4.3 completeness gaps:
1. Channel min/max table (requires multiple `readings_history` ZMQ calls + table widget)
2. Top 3 alarm names not rendered alongside count
3. Artifact labels not clickable (`QLabel` shows path, no `QDesktopServices` open)
These are spec-completeness items, not code correctness bugs. All deferred as known gaps
(spec §4.3 says "~200 LOC widget" — full spec would be ~400 LOC). Architect decision:
accept deferral to a dedicated analytics-enrichment task, or scope into Cycle 6.

**Gemini**: ZMQ worker stale-result race on rapid `set_experiment_status` calls.
Deferred — only occurs with sub-second polling intervals, acceptable for operator workflow.

**Gemini**: Replay triggers redundant ZMQ fetch on layout swap.
Deferred — bounded cost per open, not a correctness issue.

### LOW — DEFERRED
- `key.setFixedWidth(140)` hardcoded px — borderline DS violation.
  Deferred (minimal visual impact).
- Content not in `QScrollArea`.
- Two test gaps (double-set, invalid timestamp path).

### MEDIUM — DEFERRED TO ARCHITECT (from initial handoff)
**Codex Cycle 3**: T1 fallback in `cooldown_history_get` (None vs first-available-T).
Recommendation: accept None-on-missing-T1, update spec §5.3 note.

## Implementation summary

### Architecture discovery
`get_alarm_history` command does NOT exist. However, `alarm_v2_history` (line 1281,
engine.py) already serves this purpose: accepts `start_ts`/`end_ts` UNIX timestamps,
filters the `alarm_v2_state_mgr` ring buffer, returns `{"ok": True, "history": [...]}`.
Each entry has `alarm_id`, `transition` ("TRIGGERED"/"CLEARED"), `at` (timestamp),
`level` ("WARNING"/"CRITICAL"), `message` (TRIGGERED only). No new engine code needed.

### What changed

**src/cryodaq/gui/shell/views/analytics_widgets.py** (+163 LOC)
- Added `QHBoxLayout` + `Slot` to imports
- Added `ExperimentSummaryWidget`: header/duration/phase-breakdown/alarm-count/artifacts
- `_fetch_alarms(start_ts)`: `ZmqCommandWorker(cmd, parent=self)` (lifecycle safe)
- `_on_alarms_loaded`: counts TRIGGERED entries by level (WARNING/CRITICAL)
- Replaced `register(WIDGET_EXPERIMENT_SUMMARY, _experiment_summary_placeholder)`
  with `register(WIDGET_EXPERIMENT_SUMMARY, ExperimentSummaryWidget)`

**src/cryodaq/gui/shell/views/analytics_view.py** (+10 LOC)
- `_last_experiment_status: dict | None = None` in `__init__`
- `set_experiment_status(status)` setter: stores + `_forward` to active widgets
- Replay added in `_replay_cached_into`

**src/cryodaq/gui/shell/main_window_v2.py** (+5 LOC, -2 LOC)
- `self._analytics_snapshot.pop("set_experiment_status", None)` in invalidation
- `self._push_analytics("set_experiment_status", status)` in `_on_experiment_status_received`
- **FIX**: `active.get("id")` → `active.get("experiment_id")` at TWO sites (628, 665)

**tests/gui/shell/views/test_analytics_widget_experiment_summary.py** (new, 192 LOC)
**tests/gui/shell/views/test_analytics_widgets.py** (updated)
**tests/gui/shell/test_main_window_v2_f4_lazy_replay.py** (updated)
- 9 test dicts: `"id"` → `"experiment_id"` key (pre-existing test bug, same as code bug)

## Spec deviations
- No `get_alarm_history` engine command added — `alarm_v2_history` already covers use case.
- Channel min/max table, top-3 alarm names, clickable artifact links: deferred (see MEDIUM above).
- T1 fallback in cooldown_history_get: deferred to architect decision (see Cycle 3 handoff).

## Architect decisions needed (morning)
1. Channel min/max + top-3 alarms + clickable links: schedule dedicated task or defer further?
2. T1 fallback (Cycle 3 MEDIUM): accept None-on-missing-T1 → update spec §5.3?
3. Cycle 4 merge order: independent. Can merge before or after Cycles 2 and 3.

## Files changed
| File | LOC delta | Notes |
|---|---|---|
| src/cryodaq/gui/shell/views/analytics_widgets.py | +163 | ExperimentSummaryWidget |
| src/cryodaq/gui/shell/views/analytics_view.py | +10 | set_experiment_status setter |
| src/cryodaq/gui/shell/main_window_v2.py | +5/-2 | routing + experiment_id bug fix |
| tests/gui/shell/views/test_analytics_widget_experiment_summary.py | +192 | 21 tests |
| tests/gui/shell/views/test_analytics_widgets.py | +6/-2 | Updated |
| tests/gui/shell/test_main_window_v2_f4_lazy_replay.py | +50/-9 | 2 new tests + id fix |

## Commits on branch
| SHA | Subject |
|---|---|
| 345b6e0 | feat(analytics): W3 experiment_summary widget + set_experiment_status wiring (F3-Cycle4) |
