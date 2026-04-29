 ```markdown
# F23 — RateEstimator Measurement Timestamp Fix
## Spec v1.0

---

### §0 Mandate
Fix `SafetyManager._collect_loop` to forward the true instrument measurement time to `RateEstimator.push()` by passing `reading.timestamp.timestamp()` instead of the dequeue wall-clock `time.monotonic()`. This eliminates queue-latency bias from rate calculations.

---

### §1 Scope

**In scope**
- `core/safety_manager.py`: `_collect_loop` method only.
- Unit & integration tests proving temporal fidelity.

**Out of scope**
- Driver-side timestamp generation (contract already requires UTC-aware `datetime`).
- Changes to `RateEstimator.push()` signature or internals.
- `_latest` freshness/liveness tracking.
- Reordering/buffering of out-of-order readings.
- UI, alerting, or serialization layers.

---

### §2 Architecture

**Current state**
1. Drivers emit `Reading` with `timestamp: datetime` (UTC, set at instrument ADC read).
2. `SafetyManager` dequeues the `Reading` and captures `now = time.monotonic()`.
3. `now` is forwarded to `RateEstimator.push(channel, now, value)`.
4. `RateEstimator` computes `cutoff = timestamp - window_s` and evicts old points.

Because `now` reflects dequeue time, any queue backlog or asyncio scheduler jitter compresses timestamps into a burst. `RateEstimator` sees near-zero intervals and produces rate spikes (or, under burst consumption, discards valid window data).

**Target state**
- `SafetyManager` extracts the POSIX epoch float from `reading.timestamp` and sends that to `RateEstimator`.
- `RateEstimator` now operates on the measurement timeline, so the window `cutoff` correctly reflects the age of *physical samples*.
- `_latest` continues to use `time.monotonic()` to track local freshness independently.

**Epoch invariant**
`RateEstimator` instances in this codebase are owned exclusively by `SafetyManager`. Unifying the pushed timestamps from monotonic to epoch is safe **only** if no other caller pushes monotonic values into the same instance. This invariant must be verified before merge (see §7).

---

### §3 Implementation

**File:** `core/safety_manager.py`  
**Function:** `async def _collect_loop(self)`  

**Current code**
```python
            now = time.monotonic()
            self._latest[reading.channel] = (now, reading.value, reading.status.value)
            if reading.unit == "K":
                self._rate_estimator.push(reading.channel, now, reading.value)
```

**Target code**
```python
            now = time.monotonic()
            self._latest[reading.channel] = (now, reading.value, reading.status.value)
            if reading.unit == "K":
                # UTC-aware datetime → POSIX float (seconds since epoch)
                measurement_ts = reading.timestamp.timestamp()
                self._rate_estimator.push(reading.channel, measurement_ts, reading.value)
```

**Why `.timestamp()`**
`Reading.timestamp` is a timezone-aware `datetime` in UTC. Calling `.timestamp()` yields a `float` representing seconds since the Unix epoch, satisfying the existing `timestamp: float` parameter contract of `RateEstimator.push()`.

**Edge-case notes**
- **Late readings:** A reading arriving late carries an old timestamp. Its `cutoff` will be old, so it does not incorrectly evict newer left-side points. It may still be dropped by `maxlen` if the deque is full; `SafetyManager` does not reorder.
- **Future skew:** A reading with a future timestamp yields a future `cutoff`, which may purge the entire buffer. This is acceptable fault behaviour; clock skew correction belongs in the driver/NTP layer, not here.
- **Naive datetime:** Out of scope. Drivers must provide aware UTC datetimes per contract.

---

### §4 Acceptance Criteria (≥5)

1. **Correct argument:** For `unit == "K"`, `RateEstimator.push()` receives `reading.timestamp.timestamp()`, never `time.monotonic()`.
2. **Liveness isolation:** `_latest[reading.channel]` continues to be populated with `time.monotonic()` for freshness tracking.
3. **Quantitative verification:** A unit test asserts that the float passed to `push()` equals the expected POSIX timestamp of the injected `Reading` within `abs_tol=1e-6`.
4. **Backlog immunity:** An integration test with a 5-second queue backlog demonstrates that RateEstimator buffer spacing reflects the instrument sampling interval (e.g., 1.0 s), not the dequeue burst interval.
5. **Bypass preserved:** Readings with `unit != "K"` must not invoke `RateEstimator.push()`.
6. **Zero interface drift:** `RateEstimator.push()` signature remains unchanged; no downstream call sites are broken.

---

### §5 Tests

**Unit — Timestamp forwarding (Mocked)**
- Arrange: `reading = Reading(timestamp=datetime(2023, 6, 15, 12, 0, 0, tzinfo=timezone.utc), unit="K", channel="th1", value=300.0, ...)`
- Act: Pump reading through a single `_collect_loop` iteration.
- Assert: `mock_rate_estimator.push.assert_called_once_with("th1", 1686826800.0, 300.0)`
- Assert: `_latest["th1"][0]` is within `0.1` of `time.monotonic()` (unchanged liveness path).

**Integration — Temporal fidelity**
- Generate 10 `Reading`s with timestamps spaced exactly `2.0` s apart, enqueue them, then burst-dequeue.
- Assert: Internal deque timestamps in `RateEstimator` differ by `2.0 ± 0.05` s, not `< 0.1` s.

**Edge — Late arrival (60 s old)**
- Inject reading with `timestamp = now_utc - 60 s`.
- Assert: `SafetyManager` forwards it without exception; no infinite loops.

**Edge — Future clock skew (+1 hr)**
- Inject reading with future timestamp.
- Assert: Forwarded correctly; `RateEstimator` may empty its window (documented).

---

### §6 Phases

| Phase | Work | Est. |
|-------|------|------|
| 1 | Code change in `safety_manager.py` + unit test | 0.5 dev-day |
| 2 | Integration tests, staging rate-curve validation | 0.5 dev-day |
| 3 | PR review, merge, canary on hardware loop | 0.5 dev-day |

---

### §7 Hard Stops

- **Do not** modify `_latest` to use `reading.timestamp`; keep `time.monotonic()` for liveness.
- **Do not** change `RateEstimator.push()` signature or semantics.
- **Do not** add reordering, buffering, or clamping logic inside `SafetyManager`.
- **Block merge** if audit reveals another component pushes monotonic timestamps into the same `_rate_estimator` instance. Epoch mixing would silently corrupt every window calculation.
```
