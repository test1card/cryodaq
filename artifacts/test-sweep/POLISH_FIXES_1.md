# Polish Fixes — Batch 1 (2026-06-24)

Source: `artifacts/test-sweep/POLISH_ASSESSMENT.md` items MED #6, LOW #7, LOW #8 (two sites).
Out of scope (untouched): command/setpoint safety path, interlock cooldown.

All changes are TDD where behavior is testable. Not committed — left for review.

---

## MED — alarm_v2 fail-closed config validation

**Problem:** `alarm_v2._check_threshold_channel` (`alarm_v2.py:224-233`) reads
`cfg["threshold"]` / `cfg["range"]` / `cfg["setpoint_source"]` with hard subscripts at
*evaluate* time. A YAML alarm missing the key → `KeyError` → caught at
`alarm_v2.py:152-154` → `evaluate` returns `None` → the (possibly safety-relevant)
alarm silently NEVER FIRES, leaving only an ERROR log.

**Prod change:** `src/cryodaq/core/alarm_config.py`
- Added `import math`.
- New `_validate_required_keys(alarm_id, cfg)` helper + `_is_number(value)` predicate.
  Called from `_expand_alarm` BEFORE channel-group expansion.
- Validation is **check-driven** (mirrors `alarm_v2._check_threshold_channel` exactly),
  only for `alarm_type: threshold`:
  - `check: above` / `below` → numeric `threshold` required
  - `check: outside_range` → 2-element numeric `range` required
  - `check: deviation_from_setpoint` → non-empty str `setpoint_source` + numeric `threshold`
  - `check: fault_count_in_window` → intentionally skipped (reads neither key)
  - composite / rate / stale alarm_types → skipped (do not index those keys here)
- Raises the existing `AlarmConfigError` (RuntimeError subclass → maps to config exit
  code, not generic crash). The evaluate-time `except` in alarm_v2 is left intact as a
  runtime backstop.

**Test:** `tests/core/test_alarm_config_validation.py` (new)
- `above`/`below` missing `threshold` → raises
- `above` non-numeric `threshold` → raises
- `outside_range` missing / wrong-length / non-numeric `range` → raises
- `deviation_from_setpoint` missing `setpoint_source` → raises
- well-formed `above` / `outside_range` / `deviation` each still load
- `fault_count_in_window` loads WITHOUT a `threshold` (no false positive)
- shipped `config/alarms_v3.yaml` still loads

**Status: PASS** (16/16 in the new file; 112/112 in the alarm/config regression set).

---

## LOW — alarm_config numeric range checks

**Problem:** `_parse_engine_config` coerced `default`, `poll_interval_s`,
`rate_window_s`, `rate_min_points` with bare `float()/int()`. Negative
`poll_interval_s` or zero `rate_window_s` loaded cleanly and misbehaved later.

**Prod change:** `src/cryodaq/core/alarm_config.py` `_parse_engine_config`
- `poll_interval_s` must be finite and `> 0` → else `AlarmConfigError`.
- `rate_window_s` must be finite and `> 0` → else `AlarmConfigError`.
- `rate_min_points` must be `>= 1` → else `AlarmConfigError`.
- each setpoint `default` must be finite (`math.isfinite`) → else `AlarmConfigError`.

**Test:** in `tests/core/test_alarm_config_validation.py`
- negative `poll_interval_s` → raises
- zero `rate_window_s` → raises
- zero `rate_min_points` → raises
- `.nan` setpoint `default` → raises

**Status: PASS.**

---

## LOW — log swallowed parse failures (behavior unchanged, add WARNING)

### alarm_providers.py
**Prod change:** `src/cryodaq/core/alarm_providers.py`
- Added module `logger = logging.getLogger("cryodaq.core.alarm_providers")`.
- `ExperimentPhaseProvider.get_phase_elapsed_s`: `logger.warning(...)` on both the
  falsy `started_at` branch and the `(ValueError, TypeError)` parse-failure branch.
  The `return 0.0` fallback is preserved in both.

### engine.py
**Prod change:** `src/cryodaq/engine.py` `experiment_phase_status` action (~line 1600)
- Replaced `except Exception: pass` with `except Exception as exc: logger.warning(...)`.
  `elapsed = 0.0` fallback preserved (display-only status reply).

**Test:** none added — pure logging additions, no behavior change. Verified no
regression via existing `test_phase_provider_*` tests and the broad sweep.

**Status: PASS** (no behavior change; existing tests green).

---

## Verification

- ruff (line-length 120, E/F/W/I/UP/ASYNC) on all 4 touched files: **All checks passed!**
- `pytest tests/core/test_alarm_config*.py test_alarm_v2*.py test_physical_alarms*.py
  test_housekeeping_alarms_v3.py`: **112 passed.**
- Broad sweep `pytest -k "alarm or phase_status or alarm_providers"`:
  **390 passed, 1 skipped** (pre-existing FastAPI deprecation skip, unrelated).

## Files

- `src/cryodaq/core/alarm_config.py` (modified)
- `src/cryodaq/core/alarm_providers.py` (modified)
- `src/cryodaq/engine.py` (modified)
- `tests/core/test_alarm_config_validation.py` (new, extended in Codex amend)

---

## Codex Amend — Extended fail-closed validation (rate / composite / additional_condition)

**Gap identified:** the initial `_validate_required_keys` only covered `alarm_type:
threshold`. alarm_v2 also hard-subscripts `cfg["threshold"]` / `cond["threshold"]` in
the rate and composite paths, so a misconfigured rate or composite safety alarm could
still KeyError → evaluate() catch → silently never fire.

**Prod change:** `src/cryodaq/core/alarm_config.py`

`_validate_required_keys` refactored into three focused helpers:

### `_validate_threshold_check(alarm_id, cfg)`
Mirrors `alarm_v2._check_threshold_channel` (alarm_v2.py:224-233) — unchanged logic.

### `_validate_condition(alarm_id, cond, context)`
New helper. Mirrors `alarm_v2._eval_condition` hard subscripts (alarm_v2.py:284-330):
- L286: `cond["threshold"]` when `check == "any_below"`
- L293: `cond["threshold"]` when `check == "any_above"`
- L305/307: `cond["threshold"]` when `check == "above"` (phase_elapsed_s and state paths)
- L314: `cond["threshold"]` when `check == "below"`
- L322: `cond["threshold"]` when `check == "rate_above"`
- L330: `cond["threshold"]` when `check == "rate_below"`
- `rate_near_zero` (L338): uses `.get("rate_threshold", 0.1)` — **exempt**, no hard read

### `_validate_required_keys` — extended to cover rate + composite
- `alarm_type: rate` (alarm_v2.py:362-365):
  - `check in {rate_above, rate_below}` → numeric `threshold` required
  - `rate_near_zero` / `relative_rate_near_zero` → exempt (`.get("rate_threshold", …)`)
  - `additional_condition` (alarm_v2.py:376-378): validated via `_validate_condition`
    because `_eval_rate` calls `_eval_condition(add_cond)` which has the same subscripts
- `alarm_type: composite`:
  - each element of `conditions` validated via `_validate_condition`
- `alarm_type: stale` → no hard subscripts, exempt

**No false rejections:** the shipped `config/alarms_v3.yaml` loads cleanly (verified
by `test_shipped_alarms_v3_still_loads` and `test_real_config_still_loads`).
`rate_near_zero` composite sub-conditions load without `threshold` (pinned by
`test_composite_sub_condition_rate_near_zero_no_threshold_needed`).

**Tests added** (12 new, in `tests/core/test_alarm_config_validation.py`):
- rate `rate_above` / `rate_below` missing `threshold` → raises
- rate `rate_near_zero` without `threshold` → loads (exempt)
- rate well-formed → loads
- `additional_condition` missing `threshold` → raises
- `additional_condition` well-formed → loads
- composite `any_below` missing `threshold` → raises
- composite `above` (first condition) missing `threshold` → raises
- composite `rate_above` missing `threshold` → raises
- composite `rate_near_zero` without `threshold` → loads (exempt)
- composite well-formed → loads
- `test_shipped_alarms_v3_still_loads` → loads (redundant with `test_real_config_still_loads`, belt-and-suspenders)

**Verification:**
- ruff: `All checks passed!`
- `pytest tests/core/test_alarm_config_validation.py tests/core/test_alarm_v2.py`: **70 passed**
- Full alarm+config regression (7 test files): **124 passed** (112 original + 12 new)
