# Batch 19 Fix Report

## Per-Finding Table

| # | Severity | File | Location | Finding | Status | Action |
|---|----------|------|----------|---------|--------|--------|
| 1 | HIGH | test_replay_predictor.py | :89 `test_nominal_cooldown_no_predictor_alarms` | Mocked `_predictor_fires` → tautological, predictor branch untested | **FIXED** | Removed mock of `_predictor_fires`; patched `cryodaq.analytics.cooldown_predictor.predict` to return `progress = t/72` (on-track). Real `_predictor_fires` runs with zero deviation → asserts `newly_fired == 0`. |
| 2 | HIGH | test_replay_predictor.py | :111 `test_stuck_plateau_predictor_fires` | Mocked `_predictor_fires`, asserted `newly_fired >= 0` (always true) | **FIXED** | Removed mock of `_predictor_fires`; patched `predict` to return `progress = 0.0` (stuck). Real `_predictor_fires` computes `p_expected = t/72`, deviation > k_p*sigma_p at t>~7.5h → asserts `newly_fired > 0` + all fired records have `channel==Т11`, `phase==cooldown`, timestamps present. |
| 3 | HIGH | test_telegram.py | :369 `test_escalation_cancel_stops` | 60-min delay but waits 0.05s; a no-op cancel passes | **FIXED** | Assert: (1) task key `shift_missed_111` in `_pending` after `escalate()`; (2) task not yet done before cancel; (3) `task.cancelled() is True` after `cancel()`; (4) key removed from `_pending`. No timing dependency. |
| 4 | MED | test_replay_engine.py | :155 `test_replay_engine_heartbeat` | Never started bridge/heartbeat; only checked multipart length | **FIXED** | Renamed to `test_replay_engine_first_reading_pub`; updated docstring. Added msgpack decode + asserts `ch` and `v` fields present with numeric value. |
| 5 | MED | test_replay_engine.py | :286 `test_replay_engine_curve_data_pub` | `Т12 OR Т11` (one channel passes); values unchecked; fixed `sleep(0.05)` | **FIXED** | Changed channel assert to `{"Т12","Т11"} <= channels` (both required). Added per-reading `v` field check + range assertion `4.0 <= v <= 305.0 K`. Replaced `sleep(0.05)` with 5×`sleep(0.01)` readiness loop. Discovered real field name is `v` not `val`. |
| 6 | LOW | test_telegram.py | :346 `test_escalation_chain_sends` | `sleep(0.05)` timing flake | **FIXED** | Replaced sleep with `asyncio.gather(*svc._pending.values())`. Added assertion that exactly 2 tasks were created. Deterministic, no timing dependency. |

## Verification

```
pytest tests/replay/test_replay_predictor.py tests/notifications/test_telegram.py tests/replay_engine/test_replay_engine.py -q --no-header
38 passed in 0.79s
```

```
ruff check tests/replay/test_replay_predictor.py tests/notifications/test_telegram.py tests/replay_engine/test_replay_engine.py
All checks passed!
```

## Files Changed

- `tests/replay/test_replay_predictor.py` — findings 1, 2
- `tests/notifications/test_telegram.py` — findings 3, 6
- `tests/replay_engine/test_replay_engine.py` — findings 4, 5

## Notes

- No src/ changes made.
- Real msgpack field for value is `v` (not `val`) — discovered from live engine output during test run.
- Finding 4 rename from `test_replay_engine_heartbeat` to `test_replay_engine_first_reading_pub` accurately reflects what the test actually proves (PUB socket delivers readings, not watchdog heartbeat logging).
