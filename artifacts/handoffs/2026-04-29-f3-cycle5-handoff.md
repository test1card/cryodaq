# F3 Cycle 5 (Integration + W4 polish + docs) — architect review

## Status
COMPLETE-PASSED (3493833)

## Branch
feat/f3-cycle5-integration at 3493833
Pushed: yes (force-pushed with experiment_id bug fix)
Merged: NO — architect reviews in morning per runner §1

## Tests
9 new integration tests in `tests/integration/test_analytics_view_lifecycle.py`
Full suite: PASSED on Cycle 4 branch after same fix.

## Implementation summary

### W4 — r_thermal_placeholder text update (spec §4.4)
`PlaceholderCard` extended with optional `subtitle: str | None = None` parameter.
When passed, replaces the default `"{title} — данные появятся при переходе фазы."` text.
`_r_thermal_placeholder()` passes `subtitle="данные источника ожидают (зависит от F8)"`.
Comment in factory references F8 as the unblock criterion.

### Cross-widget integration tests (spec §7.3)
New `tests/integration/test_analytics_view_lifecycle.py` (9 tests):
1. Full lifecycle phase widget checks (preparation → cooldown → measurement → disassembly)
2. Phase sequence doesn't carry over stale widgets
3. Temperature reading forwarding in fallback
4. Temperature cache replayed after phase round-trip
5. Pressure forwarded in preparation top_right
6. set_experiment_status forwarded to ExperimentSummaryWidget on disassembly
7. set_experiment_status cached in `_last_experiment_status`
8. set_experiment_status replayed into fresh ExperimentSummaryWidget on phase swap
9. r_thermal_placeholder has F8 title text

### Bug fix (inherited from Cycle 4 audit)
Applied same HIGH fix as Cycle 4: `active.get("id")` → `active.get("experiment_id")`
at `main_window_v2.py:628` and `main_window_v2.py:665`.
Same test dict key fix: `"id":` → `"experiment_id":` in all invalidation test dicts.

### Documentation
- **CHANGELOG.md**: F3 five-cycle batch summary under `[Unreleased]`
- **ROADMAP.md**: F3 → ✅ DONE; F4 → ✅ DONE; F3 section narrative updated

## Spec deviations
- None. This cycle implements exactly spec §4.4, §7.3, runner §7.

## Architect decisions needed (morning)
- None for Cycle 5 itself.
- See Cycle 4 handoff for open decisions (channel min/max, top-3 alarms, T1 fallback).

## Files changed
| File | LOC delta | Notes |
|---|---|---|
| src/cryodaq/gui/shell/views/analytics_widgets.py | +7 | PlaceholderCard subtitle + r_thermal text |
| src/cryodaq/gui/shell/main_window_v2.py | -2 | experiment_id bug fix (inherited) |
| tests/gui/shell/test_main_window_v2_f4_lazy_replay.py | -9 | experiment_id fix in test dicts |
| tests/integration/__init__.py | new | Directory init |
| tests/integration/test_analytics_view_lifecycle.py | +185 | 9 integration tests |
| CHANGELOG.md | +25 | F3 batch entry |
| ROADMAP.md | +10 | F3/F4 status update |

## Commits on branch
| SHA | Subject |
|---|---|
| 3493833 | feat(analytics): F3-Cycle5 — W4 placeholder polish + lifecycle integration tests + docs |
