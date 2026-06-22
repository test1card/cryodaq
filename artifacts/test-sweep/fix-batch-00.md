# Fix Batch 00 — results

## Per-finding table

| # | Severity | Finding | Status | Reason |
|---|----------|---------|--------|--------|
| 1 | MED | `test_alarm.py:353 test_event_history_bounded` | FIXED | Assert `len == 1000` (cap hit) + activated==500 and cleared==500 (proves old events evicted, not just bounded) |
| 2 | MED | `test_alarm_v2.py:194 test_threshold_sustained_fires_after_delay` | FIXED | Replaced manual `_sustained_since` seed with `unittest.mock.patch("cryodaq.core.alarm_v2.time.time")`; first `process()` returns None (timer starts), second at t0+65s returns TRIGGERED |
| 3 | MED | `test_alarm_v2_integration.py:213 test_alarm_v2_status_shape` | FIXED | Added serialization path: builds `active_payload` dict exactly as engine.py alarm_v2_status handler does; asserts all 7 fields (level, message, triggered_at, channels, acknowledged, acknowledged_at, acknowledged_by) plus history list and ok flag |
| 4 | MED | `test_alarm_v2_legacy_cleanup.py:16 test_measurement_thresholds_removed...` | FIXED | Replaced 3 hard-coded alarm IDs with structural walk via `load_alarm_config()`; rejects any measurement-phase alarm with absolute threshold check (`above/below/outside_range/any_above/any_below/deviation_from_setpoint`) targeting Т11 or Т12, with explicit exemption for `calibrated_sensor_fault` |
| 5 | LOW | `test_alarm_v2_integration.py:99 test_phase_alarm_fires_in_correct_phase` | FIXED | Rewritten to use `AlarmConfig(phase_filter=["measurement"])` + `_simulate_tick(current_phase="measurement")`; phase-filter suppression code path now exercised |
| 6 | LOW | `test_alarm_v2_integration.py:235 test_alarm_v2_ack` | FIXED | Added assertions on returned dict shape (alarm_id, acknowledged_at, operator, reason); asserts `acknowledged=True` and `acknowledged_by` on the active event; verifies idempotent second call returns None |
| 7 | LOW | `test_alarm_v2_legacy_cleanup.py:48 test_calibrated_sensor_fault_retained` | FIXED | Replaced key-exists check with full semantics via `load_alarm_config()`: global scope (phase_filter=None), alarm_type=threshold, check=outside_range, channels={Т11,Т12}, range=[1.0, 350.0], level=CRITICAL |

All 7 findings are FIXED. No DEFERRED. No NOT-A-BUG.

## Pytest result

```
68 passed in 1.79s
```

## Ruff result

```
All checks passed!
```

## Files changed

- `tests/core/test_alarm.py` — Finding 1
- `tests/core/test_alarm_v2.py` — Finding 2
- `tests/core/test_alarm_v2_integration.py` — Findings 3, 5, 6
- `tests/core/test_alarm_v2_legacy_cleanup.py` — Findings 4, 7
