# Batch 04 Fix Report

## Per-Finding Table

| # | Severity | Test | Finding | Status | Fix Applied |
|---|----------|------|---------|--------|-------------|
| 1 | HIGH | `test_p0_fixes.py::test_alarm_publishes_alarm_count_on_clear` | `start()` emits initial 0.0; `0.0 in count_values` passes even if clear never fires | **FIXED** | Drain queue after `start()` to consume initial 0.0; assert `count_values[-1] == 0.0` (last, not any); assert `get_active_alarms() == []` |
| 2 | HIGH | `test_persistence_ordering.py::test_ordering_guarantee_write_before_zmq` | Only checks row exists; publish-before-write race passes; 2.0s timeout flaky on slow CI | **FIXED** | Gate `write_immediate` on `asyncio.Event`; assert subscriber queue is empty while write blocked; release gate; assert exact channel+value (`CH1`, `4.2`) after publish; replaced 2.0s timeout with deterministic event wait; added `monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")` |
| 3 | HIGH | `test_memory_leaks.py::test_broadcast_queue_bounded` | Never called `_on_reading_callback`; cleared clients before overflow; overflow branch never exercised | **FIXED** | Install fake WebSocket client; pre-fill queue to maxsize=5; call `_on_reading_callback(reading)` with client present; assert qsize ≤ 5 |
| 4 | MED | `test_memory_leaks.py::test_on_reading_callback_no_task_when_no_clients` | Only asserts queue empty; fire-and-forget task returning early would also leave queue empty | **FIXED** | Patch `asyncio.create_task`; assert `mock_create_task.assert_not_called()` |
| 5 | MED | `test_p0_fixes.py::test_safety_publish_failure_does_not_crash` | Never asserts failing publish was awaited; couldn't distinguish silent skip from proper error handling | **FIXED** | Assert `failing_broker.publish.await_count >= 1`; kept state transition assertions |
| 6 | MED | `test_interlock.py::test_action_called_async` | Side-effect after `sleep(0)` passes even with `create_task` fire-and-forget | **FIXED** | Block action on `asyncio.Event` (`action_gate`); assert `awaited == []` while gate closed (proves action was entered but not completed = truly awaited); release gate; assert `awaited == [True]` |
| 7 | MED | `test_interlock.py::test_load_config_yaml` | Only checked name exists + ARMED; threshold/comparison/action/pattern/cooldown could be silently ignored | **FIXED** | Assert all `InterlockCondition` fields directly (`threshold=400.0`, `comparison=">"`, `channel_pattern=r"T\d+"`, `action="emergency_off"`, `cooldown_s=5.0`); drive a matching reading through engine; assert TRIPPED + action called |
| 8 | LOW | `test_memory_leaks.py::test_rate_estimator_maxlen_computed_from_window` | Re-derives production formula; single case cannot detect hardcoded constant | **FIXED** | Two independent cases (`window_s=120` and `window_s=10`); assert different maxlen values (would both be wrong if hardcoded); behavioral overflow test pushing maxlen+50 points |
| 9 | LOW | `test_memory_leaks.py::test_channel_state_fault_history_deque_has_maxlen_after_update` | Formula re-derivation only; no behavioral bound proof | **FIXED** | Kept formula assertion; added behavioral proof: push `2 × maxlen` faults, assert `len(hist) <= expected_maxlen` |
| 10 | LOW (reliability) | `test_memory_leaks.py::test_broadcast_pump_drains_queue` | Fixed `sleep(0.05)` flakes on slow CI | **FIXED** | Sentinel-event pattern: enqueue 10 items + sentinel object; inner pump sets `asyncio.Event` on sentinel; `wait_for(drained.wait(), timeout=2.0)`; no sleep |

## CRYODAQ_ALLOW_BROKEN_SQLITE

Added `monkeypatch.setenv("CRYODAQ_ALLOW_BROKEN_SQLITE", "1")` to all 5 SQLiteWriter-creating tests in `test_persistence_ordering.py`:
- `test_write_immediate_persists_before_return`
- `test_write_immediate_failure_does_not_publish`
- `test_ordering_guarantee_write_before_zmq`
- `test_write_immediate_timeout_handling`
- `test_backward_compat_queue_mode`
- `test_start_immediate_creates_data_dir`

Pattern matches `tests/storage/test_multiline_persistence.py`.

## Exact pytest line

```
cd /Users/vladimir/Projects/cryodaq && source .venv/bin/activate && \
pytest tests/core/test_p0_fixes.py tests/core/test_persistence_ordering.py \
       tests/core/test_memory_leaks.py tests/core/test_interlock.py \
       -q --no-header
```

Result: **54 passed, 4 warnings in 13.80s**

## Ruff

```
ruff check tests/core/test_p0_fixes.py tests/core/test_persistence_ordering.py \
           tests/core/test_memory_leaks.py tests/core/test_interlock.py
```

Result: **All checks passed!**

## Files Changed

- `tests/core/test_p0_fixes.py` — findings 1, 5
- `tests/core/test_persistence_ordering.py` — finding 2 + CRYODAQ_ALLOW_BROKEN_SQLITE on 6 tests
- `tests/core/test_memory_leaks.py` — findings 3, 4, 8, 9, 10
- `tests/core/test_interlock.py` — findings 6, 7

## Deferred

None. All 10 findings fixed without src/ changes.
