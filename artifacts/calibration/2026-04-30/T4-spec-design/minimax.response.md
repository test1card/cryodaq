# F23 RateEstimator Measurement Timestamp Fix — Implementation Specification

**Feature ID:** F23  
**Component:** `core/safety_manager.py`  
**Related:** `core/rate_estimator.py`, `drivers/base.py`  
**Priority:** High (Safety-Critical)  
**Estimated Change:** 2–3 lines  

---

## §0 Mandate

The SafetyManager's `_collect_loop` currently passes `time.monotonic()`—the system monotonic clock representing when the reading was dequeued—to `RateEstimator.push()`. This violates the semantic contract of rate estimation: the system must compute rates based on **when the measurement actually occurred** (as recorded in `reading.timestamp`), not when the reading was processed.

This bug causes incorrect rate-of-change calculations for temperature-controlled safety systems. The fix requires passing `reading.timestamp.timestamp()` to `RateEstimator.push()` instead of the monotonic dequeue time.

---

## §1 Scope

| Category | Included | Excluded |
|----------|----------|----------|
| **Code changes** | `core/safety_manager.py` — `_collect_loop()` method | RateEstimator signature, Reading dataclass, drivers |
| **Testing** | Unit tests for timestamp passing, integration tests with late readings | UI changes, API surface modifications, database schema |
| **Documentation** | Updated docstrings if needed, test documentation | User-facing documentation, migration guides |
| **Scope boundaries** | Single function fix; validation of downstream effects | Refactoring of queue handling, architectural changes to timing model |

**Rationale:** The bug is localized to one method. The Reading dataclass and RateEstimator interface are already correct; only the caller uses the wrong value.

---

## §2 Architecture

### Current State (Bug)

```
┌─────────────────────┐      ┌──────────────────────┐      ┌───────────────────┐
│  Instrument Driver  │─────▶│   SafetyManager      │─────▶│   RateEstimator   │
│  (reading.timestamp)│      │   _collect_loop      │      │   .push()         │
└─────────────────────┘      │   now = time.monotonic()     └───────────────────┘
                             │   push(..., now, ...)  │      Uses: dequeue time
                             └──────────────────────┘      (WRONG for rates)
```

- `Reading.timestamp` — UTC datetime from instrument (correct)
- `time.monotonic()` — monotonic clock at dequeuetime (incorrect for rate calculation)
- RateEstimator receives monotonic timestamps → rates reflect queue latency, not measurement cadence

### Target State (Fix)

```
┌─────────────────────┐      ┌──────────────────────┐      ┌───────────────────┐
│  Instrument Driver  │─────▶│   SafetyManager      │─────▶│   RateEstimator   │
│  (reading.timestamp)│      │   _collect_loop      │      │   .push()         │
└─────────────────────┘      │   ts = reading.      │      └───────────────────�+
                             │       timestamp.     │        Uses: measurement
                             │       timestamp()    │        time (correct)
                             └──────────────────────┘
```

- `reading.timestamp.timestamp()` converts UTC datetime to Unix epoch float
- RateEstimator receives measurement-accurate timestamps
- Rate-of-change calculations reflect true physical dynamics

### Data Type Contract

| Field | Type | Notes |
|-------|------|-------|
| `reading.timestamp` | `datetime` | UTC, set at instrument read time |
| `reading.timestamp.timestamp()` | `float` | Unix epoch seconds (UTC) |
| `RateEstimator.push(ts, ...)` | `float` | Expects epoch seconds |

---

## §3 Implementation

### Location
`core/safety_manager.py` — method `_collect_loop`

### Current Code (Lines 87–96, approximate)

```python
async def _collect_loop(self) -> None:
    assert self._queue is not None
    try:
        while True:
            reading = await self._queue.get()
            now = time.monotonic()  # dequeue time — NOT measurement time
            self._latest[reading.channel] = (now, reading.value, reading.status.value)
            if reading.unit == "K":
                self._rate_estimator.push(reading.channel, now, reading.value)
                # BUG: passes now (monotonic) instead of reading.timestamp.timestamp()
    except asyncio.CancelledError:
        return
```

### Required Change

Replace the monotonic timestamp with the measurement timestamp:

```python
async def _collect_loop(self) -> None:
    assert self._queue is not None
    try:
        while True:
            reading = await self._queue.get()
            measurement_time = reading.timestamp.timestamp()  # UTC epoch seconds
            self._latest[reading.channel] = (measurement_time, reading.value, reading.status.value)
            if reading.unit == "K":
                self._rate_estimator.push(reading.channel, measurement_time, reading.value)
    except asyncio.CancelledError:
        return
```

**Specific modifications:**
1. Replace `now = time.monotonic()` with `measurement_time = reading.timestamp.timestamp()`
2. Update `_latest` assignment to use `measurement_time` (preserves consistency)
3. Pass `measurement_time` to `RateEstimator.push()` instead of `now`

### Type Safety

`reading.timestamp` is a `datetime` object. The `.timestamp()` method returns a `float` representing seconds since Unix epoch (UTC), matching `RateEstimator.push()`'s `timestamp: float` parameter.

---

## §4 Acceptance Criteria

| # | Criterion | Validation Method |
|---|-----------|-------------------|
| 1 | `RateEstimator.push()` receives `reading.timestamp.timestamp()` (float, UTC epoch) for all K-unit readings | Unit test mocks/patches and asserts argument passed |
| 2 | Rate-of-change calculations use measurement timestamps, not dequeuing timestamps | Integration test with delayed readings verifies correct rate |
| 3 | `_latest` dictionary stores measurement time, not monotonic time | Inspect stored tuple's first element |
| 4 | Non-K-unit readings (e.g., pressure, flow) unaffected | Existing tests pass; no regression in other channels |
| 5 | Late readings (> window size) correctly expire from rate buffer | Test with artificial delay between instrument read and queue processing |
| 6 | Clock skew between system clock and instrument clock does not crash | Graceful handling; RateEstimator operates on relative deltas |
| 7 | Monotonic time import can be removed if unused elsewhere | Code search confirms no other `time.monotonic()` use in module |

---

## §5 Tests

### Unit Test: Timestamp Passed to RateEstimator

```python
def test_collect_loop_passes_measurement_timestamp():
    """Verify _collect_loop passes reading.timestamp.timestamp() not monotonic()."""
    # Arrange
    sm = SafetyManager(...)
    mock_estimator = Mock(spec=RateEstimator)
    sm._rate_estimator = mock_estimator
    sm._queue = asyncio.Queue()
    
    # Create reading with known timestamp
    reading = Reading(
        timestamp=datetime(2023, 11, 15, 10, 30, 0, tzinfo=timezone.utc),
        instrument_id="temp_sensor_01",
        channel="channel_a",
        value=300.15,
        unit="K",
        status=ChannelStatus.OK
    )
    
    # Act
    await sm._queue.put(reading)
    await asyncio.sleep(0.05)  # allow _collect_loop to process
    
    # Assert
    mock_estimator.push.assert_called_once()
    call_args = mock_estimator.push.call_args
    assert call_args[0][0] == "channel_a"
    # Timestamp must be reading.timestamp.timestamp(), not monotonic
    expected_ts = reading.timestamp.timestamp()
    assert abs(call_args[0][1] - expected_ts) < 1.0  # allow sub-second delta
    assert call_args[0][2] == 300.15
```

### Integration Test: Late Reading Expiration

```python
async def test_rate_estimator_late_reading_expiration():
    """Late readings (measured long before processing) should expire correctly."""
    # Arrange: simulate reading captured 2 minutes ago
    old_timestamp = datetime.now(timezone.utc) - timedelta(seconds=120)
    reading = Reading(
        timestamp=old_timestamp,
        instrument_id="temp_sensor_01",
        channel="channel_a",
        value=300.0,
        unit="K"
    )
    
    # Act: process reading after 2-minute delay
    await queue.put(reading)
    await asyncio.sleep(0.1)
    
    # Assert: RateEstimator received the old timestamp
    # Buffer should auto-expire points outside window (default 60s)
    estimator.push.assert_called_with(
        "channel_a", 
        old_timestamp.timestamp(),  # NOT now
        300.0
    )
```

### Edge Case: Clock Skew

```python
async def test_handles_instrument_clock_skew():
    """Instrument clock ahead/behind system clock does not crash."""
    # Future timestamp (instrument clock ahead 1 hour)
    future_reading = Reading(
        timestamp=datetime.now(timezone.utc) + timedelta(hours=1),
        instrument_id="temp_sensor_01",
        channel="channel_a",
        value=300.0,
        unit="K"
    )
    # Should not raise; RateEstimator uses relative deltas
    await queue.put(future_reading)
    await asyncio.sleep(0.05)
    # Verify push called with future timestamp (will produce negative deltas)
    # System continues; safety logic may alert on clock skew separately
```

### Regression Test: Non-K Units

```python
async def test_non_k_units_not_pushed_to_estimator():
    """Pressure/flow readings (non-K) should not trigger rate estimation."""
    reading = Reading(
        timestamp=datetime.now(timezone.utc),
        instrument_id="pressure_sensor",
        channel="channel_b",
        value=101325.0,
        unit="Pa"  # Not Kelvin
    )
    await queue.put(reading)
    await asyncio.sleep(0.05)
    
    mock_estimator.push.assert_not_called()
```

---

## §6 Phases

| Phase | Description | Exit Criteria |
|-------|-------------|---------------|
| **1. Implementation** | Apply the 2–3 line change to `_collect_loop()` | Code compiles; no syntax errors |
| **2. Unit Tests** | Write test for timestamp argument verification | Test passes; verifies `.timestamp()` called |
| **3. Integration Tests** | Add late-reading and clock-skew tests | Tests cover edge cases per §5 |
| **4. Regression Suite** | Run full SafetyManager test suite | All existing tests pass |
| **5. Static Analysis** | Run linter, type checker (mypy) | Zero errors; no warnings on changed code |
| **6. Review & Merge** | Peer review of diff | Approved; CI green |

**Timeline estimate:** 2–3 hours for experienced developer (mostly test writing).

---

## §7 Hard Stops

1. **Do not modify `RateEstimator.push()` signature.** The interface is correct; only the caller uses the wrong value.
2. **Do not remove `reading.timestamp` from Reading dataclass.** This is the authoritative measurement time.
3. **Do not introduce new runtime dependencies.** Standard library only (`datetime`, `asyncio`).
4. **Do not bypass tests.** All acceptance criteria (§4) must be demonstrably met.
5. **Do not merge without CI green.** Full test suite must pass.

---

## Summary

This fix corrects a safety-critical timing bug: the RateEstimator must receive the **instrument's measurement timestamp**, not the system's monotonic clock at dequeuetime. The change is minimal (2–3 lines) but requires thorough test coverage to verify correct timestamp flow and handle edge cases such as late readings and clock skew.
