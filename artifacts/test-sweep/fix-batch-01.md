# fix-batch-01

Batch 01 — tier 0 — core: storage/calibration/channel-state

## Results

| # | Severity | File:Line | Test | Verdict | Reason |
|---|----------|-----------|------|---------|--------|
| 1 | HIGH | test_audit_fixes.py:226 | `test_sqlite_filters_inf` | FIXED | Renamed to `test_sqlite_ok_nonfinite_filtered`; status set explicitly; added `test_sqlite_overrange_inf_persists` (+inf, OVERRANGE persists) and `test_sqlite_underrange_neg_inf_persists` (-inf, UNDERRANGE persists) |
| 2 | MED | test_calibration_commands.py:59 | `test_calibration_curve_export_import` | FIXED | Assert `json_path.stat().st_size > 0`, `table_path.stat().st_size > 0`; parse JSON and assert `sensor_id` + `curve_id`; assert imported `curve_id` matches original; assert `evaluate()` returns positive T |
| 3 | LOW | test_calibration_commands.py:88 | `test_calibration_curve_list_and_lookup` | FIXED | Assert `listed_curve["curve_id"] == curve_id` and `listed_curve["sensor_id"] == "sensor-lookup"`; same for lookup |
| 4 | LOW | test_channel_state.py:88 | `test_fault_recording_and_count` | FIXED | `>= 1` → `== 1` |
| 5 | LOW | test_channel_state.py:176 | `test_resolve_fault_count` | FIXED | `>= 1` → `== 1` |
| 6 | LOW | test_channel_taxonomy.py:52 | `test_get_channels_in_zone_disconnected_reserve` | FIXED | `set(reserves) == {f"Т{i}" for i in range(17, 25)}` (exact membership) |

## Verification

```
pytest tests/core/test_audit_fixes.py tests/core/test_calibration_commands.py \
       tests/core/test_channel_state.py tests/core/test_channel_taxonomy.py \
       -q --no-header
54 passed in 0.48s
```

```
ruff check tests/core/test_audit_fixes.py tests/core/test_calibration_commands.py \
           tests/core/test_channel_state.py tests/core/test_channel_taxonomy.py
All checks passed!
```

## Files changed

- `tests/core/test_audit_fixes.py` — added `ChannelStatus` import; replaced stale `test_sqlite_filters_inf` with three targeted tests
- `tests/core/test_calibration_commands.py` — strengthened export/import assertions (non-empty, identity, evaluate); strengthened list+lookup assertions
- `tests/core/test_channel_state.py` — two `>= 1` → `== 1`
- `tests/core/test_channel_taxonomy.py` — exact set membership for disconnected_reserve
