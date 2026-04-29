# Spec Writing — F23 RateEstimator Measurement Timestamp Fix

Write a complete implementation spec for F23: fix SafetyManager to pass
reading.timestamp.timestamp() to RateEstimator.push() instead of time.monotonic().

## Background

```python
# From drivers/base.py
@dataclass
class Reading:
    timestamp: datetime  # measurement time (UTC, captured at instrument read)
    instrument_id: str
    channel: str
    value: float
    unit: str
    status: ChannelStatus = ChannelStatus.OK

# From core/rate_estimator.py
def push(self, channel: str, timestamp: float, value: float) -> None:
    """Add a point. Auto-removes points older than the window."""
    buf = self._buffers.setdefault(channel, deque(maxlen=self._maxlen))
    buf.append((timestamp, value))
    cutoff = timestamp - self._window_s
    while buf and buf[0][0] < cutoff:
        buf.popleft()

# From core/safety_manager.py — _collect_loop (THE BUG IS HERE)
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

The fix is ~2-3 lines in _collect_loop. The spec must cover correctness,
test plan, and edge cases.

## Required sections
§0 Mandate / §1 Scope (in/out) / §2 Architecture (current state + target) /
§3 Implementation (specific line change) / §4 Acceptance criteria (≥5 items) /
§5 Tests / §6 Phases / §7 Hard stops

## Output format
Complete spec markdown, approximately 100-200 lines.
Demonstrate understanding: note that reading.timestamp is a datetime (UTC),
so .timestamp() is needed. Note edge cases like clock skew or late readings.

Hard cap 3000 words.
