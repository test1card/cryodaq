# F23: RateEstimator Measurement Timestamp Fix

## §0 Mandate

SafetyManager must pass the **measurement timestamp** (`reading.timestamp.timestamp()`) to `RateEstimator.push()`, not the **dequeue wall-clock** (`time.monotonic()`). The current code computes rates against queue-drain time rather than instrument-read time, producing incorrect rate estimates whenever readings are delayed, batched, or backlogged.

## §1 Scope

### In Scope

- Replace `now` with `reading.timestamp.timestamp()` in the `RateEstimator.push()` call inside `_collect_loop`.
- Update `_latest` to store the measurement timestamp instead of monotonic time, for consistency.
- Update or add unit tests to assert the correct timestamp is forwarded.

### Out of Scope

- Changes to `RateEstimator` internals or its windowing logic.
- Changes to `Reading` dataclass or driver-layer timestamp capture.
- Handling of naive-vs-aware `datetime` normalization (assumed UTC-aware per existing convention).
- Any refactoring of `_collect_loop` beyond the timestamp fix.

## §2 Architecture

### Current State

```
Instrument ──reading──► Queue ──get()──► _collect_loop
                                         │
                                         ├─ now = time.monotonic()   ← dequeue clock
                                         ├─ _latest[ch] = (now, val, status)
                                         └─ rate_estimator.push(ch, now, val)
                                                                    ^^^ BUG
```

`time.monotonic()` is a monotonic clock with an **arbitrary epoch** unrelated to wall-clock time. `RateEstimator` computes `cutoff = timestamp - window_s` and prunes old entries. Because `now` is not a Unix timestamp, the subtraction is meaningless across clock domains, and even within the monotonic domain it reflects dequeue latency rather than measurement spacing.

### Target State

```
Instrument ──reading──► Queue ──get()──► _collect_loop
                                         │
                                         ├─ ts = reading.timestamp.timestamp()  ← UTC Unix float
                                         ├─ _latest[ch] = (ts, val, status)
                                         └─ rate_estimator.push(ch, ts, val)
                                                                    ^^^ FIXED
```

`reading.timestamp` is a `datetime` in UTC. Calling `.timestamp()` produces a POSIX `float` (seconds since 1970-01-01 UTC). This is the same domain `RateEstimator` expects for its window arithmetic.

## §3 Implementation

File: `core/safety_manager.py`, method `_collect_loop`.

```python
# BEFORE (lines ~6-12 of the method)
reading = await self._queue.get()
now = time.monotonic()
self._latest[reading.channel] = (now, reading.value, reading.status.value)
if reading.unit == "K":
    self._rate_estimator.push(reading.channel, now, reading.value)

# AFTER
reading = await self._queue.get()
ts = reading.timestamp.timestamp()  # measurement time as Unix float
self._latest[reading.channel] = (ts, reading.value, reading.status.value)
if reading.unit == "K":
    self._rate_estimator.push(reading.channel, ts, reading.value)
```

Changes:

1. **Line A**: Replace `now = time.monotonic()` with `ts = reading.timestamp.timestamp()`. This converts the UTC `datetime` to a `float` in the same domain `RateEstimator` uses for window arithmetic.
2. **Line B**: Replace `now` with `ts` in the `_latest` assignment.
3. **Line C**: Replace `now` with `ts` in the `RateEstimator.push()` call.
4. **Import cleanup**: If `time.monotonic` was the only use of the `time` module in the file, remove `import time`. Otherwise, leave it.

> **Note on `.timestamp()`**: For timezone-aware `datetime` objects (the project convention is UTC via `datetime.timezone.utc`), `.timestamp()` correctly returns POSIX seconds. For naive datetimes, Python assumes local time, which would be incorrect. This spec assumes the existing convention (UTC-aware) is upheld by drivers.

## §4 Acceptance Criteria

1. **Correct timestamp domain**: `RateEstimator.push()` receives a Unix-epoch `float` derived from `reading.timestamp`, not a `time.monotonic()` value.
2. **Rate accuracy under delay**: When readings experience queue backlog (e.g., 5 readings arriving in a burst 10 s after measurement), the computed rate reflects the **measurement spacing**, not the burst arrival spacing.
3. **_latest consistency**: The first element of each tuple in `self._latest` is a measurement-sourced timestamp, consistent with what `RateEstimator` receives.
4. **No regression in normal flow**: When the queue is drained promptly (sub-millisecond latency), rate estimates remain within tolerance of pre-fix values (the monotonic and Unix clocks advance at the same rate).
5. **Out-of-order readings**: If a late reading has an earlier `reading.timestamp` than the most recent point in the `RateEstimator` buffer, the point is still appended (deque semantics) and naturally falls outside the window on the next push — no crash, no corruption.
6. **No new imports**: The fix removes a dependency on `time.monotonic` from this method (or the `time` module entirely) and introduces no new imports.

## §5 Tests

### 5.1 Unit: timestamp domain forwarded correctly

```python
def test_push_receives_measurement_timestamp(self):
    """RateEstimator.push must be called with reading.timestamp.timestamp(), not time.monotonic()."""
    sm = SafetyManager(...)
    sm._queue = asyncio.Queue()
    dt = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    reading = Reading(timestamp=dt, instrument_id="sim", channel="T1",
                      value=300.0, unit="K", status=ChannelStatus.OK)
    with patch.object(sm._rate_estimator, "push") as mock_push:
        asyncio.get_event_loop().run_until_complete(sm._queue.put(reading))
        # run one iteration of _collect_loop (or factor out the body)
        # ...
        mock_push.assert_called_once_with("T1", dt.timestamp(), 300.0)
```

### 5.2 Unit: rate accuracy under simulated backlog

```python
def test_rate_unchanged_by_queue_delay(self):
    """Two readings 10 s apart must yield ~0.1 K/s regardless of queue delay."""
    re = RateEstimator(window_s=60)
    # Simulate: readings taken at t=0 and t=10, but dequeued simultaneously at t=50
    re.push("T1", 0.0, 100.0)
    re.push("T1", 10.0, 101.0)
    assert abs(re.rate("T1") - 0.1) < 0.01  # measurement-time arithmetic
```

### 5.3 Unit: _latest stores measurement timestamp

```python
def test_latest_uses_measurement_time(self):
    sm = SafetyManager(...)
    dt = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    reading = Reading(timestamp=dt, ...)
    # process reading
    assert sm._latest[reading.channel][0] == dt.timestamp()
```

### 5.4 Edge: out-of-order reading does not crash

```python
def test_out_of_order_reading(self):
    """A reading with earlier timestamp than the latest buffer entry must not raise."""
    re = RateEstimator(window_s=60)
    re.push("T1", 20.0, 200.0)
    re.push("T1", 10.0, 100.0)  # out-of-order
    assert re.rate("T1") is not None  # defined; latest two points
```

### 5.5 Edge: very old reading falls outside window

```python
def test_stale_reading_pruned(self):
    re = RateEstimator(window_s=10)
    re.push("T1", 100.0, 100.0)
    re.push("T1", 200.0, 200.0)  # 100 s gap → first point pruned
    rate = re.rate("T1")
    # Only one point remains; rate should be None or 0.0 per existing convention
    assert rate is None or rate == 0.0
```

### 5.6 Edge: clock skew between instrument and host

> Not directly testable in unit tests. Document in release notes: if the instrument clock is skewed relative to the host, rates will be incorrect proportional to that skew. This is **inherent** — the measurement timestamp is the best available truth. The old behavior (monotonic) masked this by ignoring instrument time entirely, at the cost of always-wrong rates under delay.

## §6 Phases

| Phase | Description | Gate |
|-------|-------------|------|
| **P1** | Apply the 3-line change in `_collect_loop`; remove `time` import if unused. | Diff reviewed; existing tests pass. |
| **P2** | Add tests §5.1–§5.5. | All new tests green; no regression in existing suite. |
| **P3** | Update `CHANGELOG.md`; note the behavioral change (rate domain shifts from monotonic to POSIX). | Changelog entry merged. |

Estimated effort: **≤ 1 hour** including review.

## §7 Hard Stops

1. **Do not** modify `RateEstimator.push()` signature or internals — the fix belongs in the caller.
2. **Do not** add `datetime.now()` or any new wall-clock capture inside `_collect_loop`; the only authoritative time source is `reading.timestamp`.
3. **Do not** merge if any existing `test_safety_manager*` or `test_rate_estimator*` test regresses.
4. **Do not** merge without at least test §5.1 (domain verification) and §5.2 (rate accuracy) passing.
5. **Do not** change the `Reading.timestamp` type or add timezone-coercion logic in this feature — that is a separate concern.
