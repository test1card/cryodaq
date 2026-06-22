# Batch 08 Fix Report

Executor cycle 6 — 2026-06-22

## Per-Finding Table

| # | Severity | File:Line | Test | Status | Fix summary |
|---|----------|-----------|------|--------|-------------|
| 1 | MED | test_keithley_safety.py:108 | `test_last_v_resets_on_stop` | **FIXED** | Replaced mock=True path with fake non-mock transport (`_FakeKeithleyTransport`). Seeded `_last_v["smua"] = 5.0` before `stop_source`. Asserts both zero-reset and `active=False`. Mock path left `_last_v` at 0.0 always — reset was unobservable. |
| 2 | MED | test_keithley_safety.py:148 | `test_last_v_resets_on_emergency_off_all` | **FIXED** | Same fix pattern as #1. Replaced mock=True with fake transport. Seeded smua=9.0, smub=4.5. Both asserted zero after `emergency_off()`. Added `active=False` assertions for both channels. |
| 3 | MED | test_gpib_bus_lock.py:148 | `test_gpib_connect_does_not_send_idn` | **FIXED** | Replaced `mock=True` (returns before `_blocking_connect`, so assertion was vacuously true) with `mock=False` + `monkeypatch` on `_blocking_connect` that injects a `_FakeResource` recording writes/queries. Asserts no `*IDN?` in writes or queries after `open()`. |
| 4 | MED | test_keithley_2604b.py:94 | `test_keithley_read_source_off` | **FIXED** | Replaced mock=True with fake non-mock path using existing `_FakeOutputStateTransport("0.000000e+00")`. Exercises real OFF branch. Asserts finite, non-NaN, non-Inf values AND that V/I/P == 0.0 on the real path. |
| 5 | LOW | test_keithley_connect_safety.py:60 | `test_connect_skips_force_off_in_mock_mode` | **FIXED** | Added write spy via closure that records all `write()` calls to the mock transport. After `connect()`, asserts no `OUTPUT_OFF` or `levelv = 0` writes were issued — confirming the `if not self.mock:` gate works. |
| 6 | LOW | test_etalon_multiline_continuous.py:107 | `test_read_channels_continuous_emits_first_cycle` | **FIXED** | Added value assertions: each `length_ch` reading == 1234.5678 mm; env readings == 22.5°C / 1013.25 hPa / 45.0% RH. Previously only asserted channel names and count. |
| 7 | LOW | test_etalon_multiline_continuous.py:259 | `test_listener_appends_to_burst_buffer_when_active` | **FIXED** | Added per-cycle value assertions: `lengths[0] == 1.0`, `lengths[1] == 1.1`, `lengths[0] != lengths[1]`. Previously only asserted `len(...) == 2`. |
| 8 | LOW | test_etalon_multiline_continuous.py:338 | `test_burst_stop_persists_parquet_with_full_schema` | **FIXED** | Added cell-value assertions after schema/row-count: `length_mm == 1234.5678`, `temperature_c == 22.5`, `pressure_hpa == 1013.25`, `channel_index in {1, 2}`. |
| 9 | LOW (reliability) | test_etalon_multiline_continuous.py:427 | `test_disconnect_cancels_listener_and_clears_burst` | **FIXED** | Replaced `await asyncio.sleep(0.05)` with `asyncio.Event` (`transport.listening`) set inside `read_lines_async` at its entry point. Test now awaits the event with a 5s timeout instead of a fixed sleep — eliminates the flake on loaded CI boxes. |

## Exact pytest line

```
pytest tests/drivers/test_keithley_safety.py tests/drivers/test_gpib_bus_lock.py tests/drivers/test_keithley_2604b.py tests/drivers/test_keithley_connect_safety.py tests/drivers/test_etalon_multiline_continuous.py -q --no-header
```

Result: **59 passed in 0.26s**

## Ruff

```
ruff check tests/drivers/test_keithley_safety.py tests/drivers/test_gpib_bus_lock.py tests/drivers/test_keithley_2604b.py tests/drivers/test_keithley_connect_safety.py tests/drivers/test_etalon_multiline_continuous.py
```

Result: **All checks passed!**

## Files Changed

- `tests/drivers/test_keithley_safety.py` — findings #1, #2
- `tests/drivers/test_gpib_bus_lock.py` — finding #3
- `tests/drivers/test_keithley_2604b.py` — finding #4
- `tests/drivers/test_keithley_connect_safety.py` — finding #5
- `tests/drivers/test_etalon_multiline_continuous.py` — findings #6, #7, #8, #9

## Deferred

None. All 9 findings fixed. No src/ changes required.
