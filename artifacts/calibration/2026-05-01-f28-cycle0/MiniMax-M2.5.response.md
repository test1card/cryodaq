# EventBus Foundation Review (Commit 26d4d162)

## Verdict: CONDITIONAL

The implementation is well-structured for a foundational change, but several safety-critical issues require attention before production deployment.

---

## Findings

### 1. CRITICAL: Missing Error Handling in Engine Publish Calls

**Severity:** CRITICAL  
**Location:** `src/cryodaq/engine.py:12280-12300` and similar publish points

The engine publishes events without try/except wrappers. Unlike `EventLogger.log_event()` which wraps the publish in try/except, the engine direct publishes can raise exceptions:

```python
# engine.py:12280-12300 - alarm_fired case
await event_bus.publish(
    EngineEvent(
        event_type="alarm_fired",
        timestamp=datetime.now(UTC),
        payload={...},
        experiment_id=experiment_manager.active_experiment_id,
    )
)
```

If `EventBus.publish()` raises (e.g., during a future enhancement that makes it blocking), it will propagate into `_alarm_v2_tick`, potentially disrupting the alarm processing loop.

**Recommended fix:** Wrap all engine publish calls in try/except, mirroring the pattern in `event_logger.py:48-55`:
```python
try:
    await event_bus.publish(EngineEvent(...))
except Exception:
    logger.warning("EventBus publish failed for alarm_fired", exc_info=True)
```

---

### 2. HIGH: Publish Not Cancelling-Safe

**Severity:** HIGH  
**Location:** `src/cryodaq/core/event_bus.py:43-52`

The `publish()` method uses `put_nowait()` which is generally safe, but the iteration pattern could be problematic if a subscriber is cancelled mid-publish:

```python
async def publish(self, event: EngineEvent) -> None:
    for name, q in list(self._subscribers.items()):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning(...)
```

If `list(self._subscribers.items())` is created, then a subscriber is unsubscribed, then we try to `put_nowait` — this is fine. However, if a subscriber's queue is in a bad state (e.g., gc'd while we hold reference), this could cause issues. More critically, there's no protection against a subscriber raising an exception during any future async operation added to this method.

**Recommended fix:** Add explicit exception handling per-subscriber and consider adding a "publish_id" to help trace event delivery in logs.

---

### 3. HIGH: No Backpressure Signal to Engine

**Severity:** HIGH  
**Location:** `src/cryodaq/core/event_bus.py:43-52`

When a subscriber queue is full, events are silently dropped with only a warning log:

```python
except asyncio.QueueFull:
    logger.warning(
        "EventBus: subscriber '%s' queue full, dropping %s",
        name,
        event.event_type,
    )
```

In a safety-critical system, silently dropping alarm events is problematic. While the current design is documented as "non-blocking; drops on full," there's no mechanism to:
1. Alert the engine that a critical subscriber is falling behind
2. Distinguish between dropped alarm events vs. non-critical events
3. Recover from queue overflow state

**Recommended fix:** Add a callback or status mechanism to signal queue saturation back to the engine, or consider a circuit-breaker pattern that disconnects overloaded subscribers.

---

### 4. MEDIUM: Subscribe Returns Queue Without Validation

**Severity:** MEDIUM  
**Location:** `src/cryodaq/core/event_bus.py:27-32`

```python
async def subscribe(self, name: str, *, maxsize: int = 1_000) -> asyncio.Queue[EngineEvent]:
    q: asyncio.Queue[EngineEvent] = asyncio.Queue(maxsize=maxsize)
    self._subscribers[name] = q
    return q
```

If a subscriber calls `subscribe("nameA")`, gets queue Q1, then calls `subscribe("nameA")` again (perhaps from different coroutine), the first queue Q1 is silently orphaned — still in memory but no longer referenced by `_subscribers`. While unlikely in practice, this is a memory leak.

**Recommended fix:** Either raise if name already exists, or explicitly warn/log when replacing an existing subscriber.

---

### 5. MEDIUM: Event Ordering Relies on Engine Call Order

**Severity:** MEDIUM  
**Location:** `src/cryodaq/engine.py:12278-12310` (alarm transitions)

The ordering of events is guaranteed only by the sequential execution of publish calls within the same coroutine:

```python
# In _alarm_v2_tick:
if transition == "TRIGGERED":
    await event_bus.publish(alarm_fired)  # First
elif transition == "CLEARED":
    await event_bus.publish(alarm_cleared)  # Second
```

This is correct for single alarm transitions, but if the engine is modified to fire multiple alarms in a loop, the order depends on iteration order. A subscriber cannot rely on any global ordering guarantee — they must handle out-of-order events.

**Recommended fix:** Add sequence numbers to EngineEvent or document this limitation clearly for future subscribers.

---

### 6. LOW: Unused Import in event_logger.py

**Severity:** LOW  
**Location:** `src/cryodaq/core/event_logger.py:6`

```python
from datetime import UTC, datetime
```

The `UTC` import is used, but the `datetime` import appears redundant since `datetime.now()` could use `UTC` directly. However, this is minor.

---

### 7. LOW: Test Coverage Gaps

**Severity:** LOW  
**Location:** `tests/core/test_event_bus.py`

The tests cover basic subscribe/publish but miss:
- Concurrent subscribe from multiple coroutines
- Unsubscribe during publish
- Queue size boundary (maxsize behavior)
- Publishing while no subscribers exist (covered but minimal)
- Error propagation from publish (not tested)

**Recommended fix:** Add tests for:
- `asyncio.gather(bus.subscribe("a"), bus.subscribe("b"))` 
- Subscribe with same name twice
- Verify queue maxsize enforcement

---

## Summary

| Severity | Count |
|----------|-------|
| CRITICAL | 1 |
| HIGH | 2 |
| MEDIUM | 2 |
| LOW | 2 |

The most critical issue is the lack of error handling around publish calls in the engine. A publish failure (e.g., in future modifications) could crash the alarm tick loop. The design is otherwise sound for a Cycle 0 foundation — non-blocking behavior is appropriate for the use case, and the drop-on-full strategy is documented. However, for safety-critical operation, the backpressure issue should be addressed with a signaling mechanism before Cycle 1.
