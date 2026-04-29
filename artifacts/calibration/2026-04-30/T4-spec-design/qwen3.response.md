# Spec: Fix F23 — RateEstimator Timestamp Handling

## §0 Mandate  
**Issue ID:** F23  
**Author:** [To be completed]  
**Date:** 2025-04-05  
**Priority:** P1 — High Risk, Data Corruption / Safety Impact  
**Reference:** `drivers/base.py:Reading`, `core/rate_estimator.py`, `core/safety_manager.py`

> **Purpose**: Correct `SafetyManager._collect_loop` to pass the *measurement timestamp* (UTC, from `Reading.timestamp`) to `RateEstimator.push()` instead of `time.monotonic()`.

---

## §1 Scope  

### §1.1 In Scope  
- Change in `core/safety_manager.py` method `_collect_loop`, line ~48: replace `now = time.monotonic()` with `reading.timestamp.timestamp()` when invoking `_rate_estimator.push`.

- Impact:  
  - `RateEstimator` internal buffer and rate computation for `unit == "K"` (Kelvin/s) measurements.  
  - Correctness of rate calculation (K/s) for safety thresholds.

### §1.2 Out of Scope  
- Changes to `Reading` dataclass (already correct).  
- Changes to `RateEstimator` (current implementation is timestamp-agnostic.  
- Clock synchronisation, leap seconds, or NTP/SNTP adjustments.  
- Change of unit, scaling, or unit conversion.  
- UI, logging, or telemetry additions.

---

## §2 Architecture  

### §2.1 Current (Buggy) State  
- `Reading` holds a UTC datetime `timestamp`, captured at instrument sampling.  
- In `_collect_loop`, `now = time.monotonic()` captures wall time of dequeue.  
- When `unit == "K"`, the call is currently:

  ```python
  self._rate_estimator.push(reading.channel, now, reading.value)
  ```

  → **Bug**: passes dequeue time (dequeued, not sampled) instead of sampled time.

**Impact**: rate estimator stores points at dequeue time (possibly seconds/minutes after measurement), causing *artificial flattening of rates, phase lag, and delayed/missed threshold alerts.

### §2.2 Target State  
- `reading.timestamp` (UTC datetime) represents measurement time.  
- `reading.timestamp.timestamp()` yields POSIX timestamp (float, seconds since epoch).  
- Call becomes:

  ```python
  self._rate_estimator.push(reading.channel, reading.timestamp.timestamp(), reading.value)
  ```

- `RateEstimator` now receives true measurement time, preserving time-of-event.

---

## §3 Implementation  

### §3.1 File: `core/safety_manager.py`  
**Method**: `_collect_loop`, inside `try` block, loop:

**Before** (Lines 45–50)

```python
async def _collect_loop(self) -> None:
    assert self._queue is not None
    try:
        while True:
            reading = await self._queue.get()
            now = time.monotonic()         # ← (A) current line
            self._latest[reading.channel] = (now, reading.value, reading.status.value)
            if reading.unit == "K":
                self._rate_estimator.push(reading.channel, now, reading.value)
                # ↑ (B) line to change

```

**After** (Lines 45–50)

```python
async def _collect_loop(self) -> None:
    assert self._queue is not None
    try:
        while True:
            reading = await self._queue.get()
            now = time.monotonic()         # (A) retained for _latest update
            self._latest[reading.channel] = (now, reading.value, reading.status.value)
            if reading.unit == "K":
                self._rate_estimator.push(reading.channel, reading.timestamp.timestamp(), reading.value)
                # ↑ (B) line changed
```

**Change Summary**  
- **Line (B) (previously `self._rate_estimator.push(..., now, ...)`):  
  → Replace `now` with `reading.timestamp.timestamp()`  
  → Result: `self._rate_estimator.push(reading.channel, reading.timestamp.timestamp(), reading.value)`

**Rationale**  
- `reading.timestamp` is UTC `datetime`.  
- `.timestamp()` → POSIX float seconds (UTC epoch), consistent with `RateEstimator`’s expectation.  
- Eliminates dequeue-time drift and maintains measurement-order fidelity.

---

## §4 Acceptance Criteria  

1. **Correct Timestamp Usage**  
   `RateEstimator.push(...)` receives `reading.timestamp.timestamp()`, *not* `time.monotonic()`.

2. **Rate Estimation Integrity**  
   Estimated rate for `unit == "K"` reflects correct temporal gradient of actual measurements.

3. **No Regression on Non-K Units**  
   `reading.timestamp.timestamp()` is used *only* for `unit == "K"` cases; other units unaffected.

4. **Latency Handling**  
   Reading queue latency (queue time) no longer pollutes estimator buffer timestamps.

5. **Backward Compatibility**  
   `RateEstimator`’s API unchanged, backward compatible; existing callers unaffected.

---

## §5 Tests  

### §5.1 Unit Test (mock queue, inject readings with known timestamps)  

```python
def test_rate_estimator_receives_measurement_timestamp():
    estimator = RateEstimator(window_s=60.0)
    sm = SafetyManager(queue_size=10)
    sm._rate_estimator = estimator

    # Patch queue to yield controlled readings
    readings = [
        Reading(timestamp=datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc), channel='A', value=300.0, unit='K', instrument_id='I1'),
        Reading(timestamp=datetime(2023, 1, 1, 0, 0, 1, tzinfo=timezone.utc), channel='A', value=301.5, unit='K', instrument_id='I1'),
    ]

    for r in readings:
        await sm._queue.put(r)

    # Trigger loop briefly, then inspect estimator buffer
    await asyncio.sleep(0.1)

    # Check estimator buffer
    buf = list(estimator._buffers['A'])
    # Expected timestamps: 16725318400.0 (first reading), 16725318401.0 (second)
    assert buf[0][0] == 16725318400.0
    assert buf[1][0] == 16231648401.0  # POSIX seconds for those UTC datetimes
```

### §5.2 Integration Test  
- Inject readings with 10 s apart, measure rate at 10 s window.  
- Verify rate estimate ≈ 0.15 K/s (if delta = 1.5 K / 10 s).  
- If buggy (dequeue time applied), rate estimate would be *lower* due to extra dequeue delay (e.g., if dequeue at 12 s, then estimate = 0.075 K/s).  
- After fix, match true rate.

### §5.3 Edge Cases Tested  
| Case | Expected Timestamp | Action |
|------|------------------|--------|
| `timestamp` is `datetime.max` UTC (far future) | `inf` (large float) | No crash, estimator buffer pushes `inf`, no overflow exception (Python handles large float). |
| `timestamp` is `datetime.min` UTC (far past) | `large negative` | estimator buffer pushes large negative; `RateEstimator` handles large negative (no crash). |
| Timezone-aware UTC (`tzinfo=timezone.utc`) | correct UTC epoch | correct float. |
| Late arrival (dequeue 5 s after measurement) | measurement time still used | estimator gets real measurement time, not 5 s late dequeue. |
| Zero-second measurement | `0.0` | estimator receives `0.0`, correct. |

---

## §6 Phases  

| Phase | Description | Exit Criteria |
|-------|-------------|---------------|
| 1 — Spec Freeze | Final spec review & sign-off | All reviewers approve spec |
| 2 — Code Diff | Implementation in `safety_manager.py` | Code reviewed, merge-ready, passes CI |
| 3 — Test Run | Run unit/integration tests | All tests pass |
| 4 — Deploy | Deploy to staging/test environment | Observability confirms correct rates |
| 5 — Monitors | Observe `RateEstimator` rate outputs for 24h | No anomalous rate behavior |
| 6 — Close | Close issue & archive spec | Stakeholders confirm no issues |

---

## §7 Hard Stops  

- **No code deploy without spec approval (§1 sign-off required).**  
- **No merge without passing unit test (§5) — **block merge if test fails.**  
- **If after deploy (Phase 4), `RateEstimator` reports NaN/Inf in rate, **immediate rollback.**  
- **If `Reading.timestamp` is `None` (violation of data contract), **bug in caller, raise `ValueError` before reaching estimator.**
