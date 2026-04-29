**Verdict: CONDITIONAL**

This is a well-structured, minimal EventBus implementation with good awareness of non-blocking semantics. However, several safety-critical concerns prevent a clean PASS. The core EventBus data structure is sound, but **the engine integration introduces unverified ordering assumptions and a critical race in publish cancellation safety that must be fixed before production deployment.

---

### Finding 1: Cancellation-unsafe publish loop (CRITICAL)

**Location:** `src/crydaq/core/event_bus.py:47–55`, `publish` method

**Description:** The `publish()` method uses `for name, q in list(self._subscribers.items()):` then calls `q.put_nowait(event)` for each subscriber. If the engine awaits `publish()` and the task is cancelled *mid-loop*, the event may be delivered to *some* subscribers but not others. There is *no transactional guarantee*—no rollback if the engine needs to abort the operation after partial dispatch.

In a cryogenic DAQ system, partial event delivery could cause inconsistent state across subsystems (e.g., alarm fired to one agent but not to logging, then engine rollbacks and re-applies the same event — leading to duplicate or missed actions.

**Recommended fix:**
- Capture `list(self._subscribers.items())` *outside* the try/except *before* iteration and hold a *copy* of the queue references to *all* queues, then *enumerate* over that *invariant* set. If a task is cancelled, it should be *immediately clear* that *no* delivery occurred *or* *all* occurred *before* cancellation was visible. Alternatively, switch to `asyncio.gather(*[q.put(event) for q in queues], return_exceptions=True)` and *only* `await` *after* the entire publish *sequence* is scheduled, but this still has partial failure issues. Better: treat `publish()` as *fire-and-forget* at the *caller* level: engine must not `await publish()` (and indeed it doesn’t), but callers of `publish()` must understand it’s *best-effort only and the *entire* event *may be dropped* if any *exception* occurs. In this diff, callers call `await event_bus.publish(...)` but do not `try/except` and rely on the *caller* to *handle* failure. Given the logging in `publish`, it logs a warning and drops. That’s *acceptable* if the caller *is* *aware* that the *event* is *not* *retried*, but the *real issue* is *partial* delivery on *cancellation* — this can only happen if the event itself is mutated *after* `publish()` starts — in this code, the event `event` is *immutable* (`event` is a `dataclass` but the `payload` is a *mutable* dict. If the caller reuses the `event` object, then `publish()` mutates `event.payload`, that is *not* happening here. So partial delivery is the real concern.

**However**, the `publish()` method *does* not mutate `event`, so *partial* delivery on cancellation is the only issue, and that *can* cause *inconsistent* engine state.

**Fix:** Add a **documentation** and **code** note: `publish` is *best-effort**, **no** **delivery** is *guaranteed**, *all-or-nothing is *not* provided**, and *callers must** not *rely** on *delivery*. If *delivery* is required, the event must be *stored* in *persistent* storage *before* *publish**, *and* engine *must** handle *duplicate** or *out-of-order** delivery.

### Finding 2: No subscriber lock or atomicity between subscribe/unsubscribe and publish (HIGH)

**Location:** `src/crydaq/core/event_bus.py:55–57`, `__init__`, `subscribe`, `unsubscribe`

**Description:** `self._subscribers` is a plain `dict`, accessed by `subscribe` (async), `unsubscribe` (sync), and `publish` (async). There is *no lock*. `publish` takes a snapshot with `list(self._subscribers.items())`, but `subscribe` and `unsubscribe` run *concurrently* with `publish`. If `unsubscribe` is called *during* `publish` (e.g., a subscriber disconnects while engine is publishing), `unsubscribe` can remove a subscriber *after* the `list()` snapshot, causing the snapshot includes a *stale* subscriber. `unsubscribe` will *not* affect the *snapshot*, and the *event* is *delivered* to *stale* subscriber. That’s *acceptable* (event to a disconnected subscriber). Conversely, if `subscribe` is called *during* `publish`, a *new* subscriber may be added *after* the `list()` snapshot, so it *will* *not* receive *event*. This is *acceptable* (new subscriber does not receive event), but callers may assume “new subscriber gets all events from now”, and they’ll *miss* events *immediately* after `subscribe`. In a safety system, missing an *event* immediately after subscription is dangerous. For example, a new monitoring agent subscribes and assumes it got all “current” events, then publishes its status. If `publish` omits the current event, the new agent *misses* the *event*. This is *race* between `subscribe` and `publish`. In cryogenic system, missing event immediately after subscription can cause monitoring *blindspot*. Fix: *make* subscribe *and* unsubscribe *must* *atomically* *update* `self._subscribers` and *notify* *publish` that *subscribers* changed. Either add a *lock* around *all* `_subscribers` access or use `asyncio.Event` to signal *subscription* change. Simpler: *avoid* *dynamic* `subscribe/unsubscribe* in *critical* paths. In engine, subscriptions are static (agent start/stop at init, not dynamic), but if agents can be *dynamically* added, this is a problem.

**Fix:** Document: `subscribe` must be called *before* engine start, *not* called during engine run. Or add `asyncio.Lock()` around `_subscribers` access.

### Finding 3: Engine publish points add latency and potential engine stall if queues full (MEDIUM)

**Location:** `src/crydaq/engine.py:1281, 1615, 1636, 1642, 1668, 1674, 1680

**Description:** Engine adds 6 new `await event_bus.publish(...)` calls at lines 1281, 1615, 1636, 1642, 1668, 1674, 1680 (approx). While `publish` uses `q.put_nowait`, `asyncio.Queue.put_nowait` is non-blocking, but if all subscriber queues are full, `publish` logs warning and drops event. If engine *relies* on *delivery*, *missing* event *is* *failure**. If engine *requires** delivery, it must *retry**, *but** retry *event* is *not* stored in persistent storage, and `publish` is fire-and-forget. In this code, *caller* does not *retry**, *so* *publisher* must *store** event in *persistent* storage *before* *publish**. This is *not* done, so *engine* may *lose* events. In cryogenic DAQ, losing alarm event is critical.

**Fix:** Engine must store event in persistent storage before `publish`. Add logging in `publish` to log “EventBus publish failed” but caller must ensure event is stored.

### Finding 4: No ordering guarantees between events in same tick (MEDIUM)

**Location:** `src/cryq/engine.py:1281, 1615, 1636, 1642, 1668, 1674, 1680

**Description:** Engine publishes alarm fired and alarm cleared events in same tick. EventBus delivers events to subscribers in *no guaranteed order*. If subscriber requires strict order (e.g., log alarm fired then log alarm cleared), *no guarantee*. In safety system, event order is critical. Alarm cleared before alarm fired is different from alarm fired before alarm cleared. No order guarantee.

**Fix:** Add event ordering in engine: ensure events are ordered before publish, or add event ordering in EventBus. If strict ordering required, publish must be serialized, but this conflicts with non-blocking design. Alternatively, assign event order in engine, and document that EventBus does not guarantee order, and callers must handle out-of-order delivery.

### Finding 5: Test coverage gaps – no race testing (LOW)

**Location:** `tests/core/test_event_bus.py`

**Description:** Tests are functional but do not test concurrent subscription/unsubscription during publish, subscriber queue full with async processing, or cancellation during publish. In safety-critical system, race conditions are common, and tests must verify no race conditions. Tests should use `asyncio.gather` to test concurrent operations.

**Fix:** Add tests for concurrent subscribe/unsubscribe during publish, and subscriber queue full scenarios.

### Finding 6: No backpressure signaling to engine (LOW)

**Location: `src/crydaq/core/event_bus.py`

**Description:** When subscriber queue is full, EventBus logs warning and drops event. No backpressure signal to engine that subscriber is overwhelmed. Engine may not take corrective action. In safety-critical system, backpressure is critical to prevent cascade failures.

**Fix:** Add backpressure signal to engine, e.g., increment counter for dropped events, and log warning if too many dropped events.

### Finding 7: No validation of event payload structure (LOW)

**Location: `src/crydaq/core/event_bus.py`

**Description:** Event payload is a `dict[str, Any]` with no validation. If engine publishes malformed event (e.g., missing required fields), subscribers may fail or behave incorrectly. In safety-critical system, invalid event payload can cause failure.

**Fix:** Add validation of event payload structure, or use `pydantic` for validation.

### Finding 8: No event persistence or recovery (LOW)

**Location: `src/crydaq/core/event_bus.py, src/crydaq/engine.py

**Description:** Events are not persisted in case of engine crash. If engine crashes after publishing event but before subscriber processes it, event is lost. In safety-critical system, all events must be persisted.

**Fix:** Add event persistence, e.g., store events in SQLite or other storage before publishing.

### Finding 9: No authentication or authorization (LOW)

**Location: `src/crydaq/core/event_bus.py

**Description:** EventBus does not implement authentication or authorization. Any component can subscribe to events or publish events. In safety-critical system, unauthorized access to events is a security risk.

**Fix:** Implement authentication and authorization for EventBus, e.g., use tokens or certificates for subscriber authentication and authorization.

### Finding 10: No metrics or monitoring (LOW)

**Location: `src/crydaq/core/event_bus.py

**Description:** EventBus does not expose metrics or monitoring data. In safety-critical system, monitoring is required for operational safety.

**Fix:** Add metrics and monitoring, e.g., log metrics to Prometheus or other monitoring system.

### Summary

This commit introduces an EventBus for engine events, which is a good architectural improvement. However, there are several safety-critical concerns:

1. Cancellation-unsafe publish loop (CRITICAL) — partial delivery on cancellation.
2. No subscriber lock or atomicity between subscribe/unsubscribe and publish (HIGH) — race between subscribe and publish.
3. Engine publish points add latency and potential engine stall if queues full (MEDIUM) — event loss if queues full.
4. No ordering guarantees between events in same tick (MEDIUM) — no order guarantee.
5. Test coverage gaps — no race testing (LOW) — no concurrent tests.
6. No backpressure signaling to engine (LOW) — no backpressure signal.
7. No validation of event payload structure (LOW) — no validation.
8. No event persistence or recovery (LOW) — no persistence.
9. No authentication or authorization (LOW) — no auth.
10. No metrics or monitoring (LOW) — no monitoring.

**Recommendation:**
- Fix cancellation-unsafe publish loop before production deployment.
- Add lock around `_subscribers` access or document static subscription model.
- Add event persistence before `publish`.
- Add event ordering in engine or document no order guarantee.
- Add tests for concurrent subscribe/unsubscribe during publish, and subscriber queue full scenarios.
- Add backpressure signal to engine, e.g., increment counter for dropped events.
- Validate event payload structure, e.g., use `pydantic`.
- Persist events, e.g., store events in SQLite before publishing.
- Implement authentication and authorization for EventBus, e.g., use tokens or certificates for subscriber authentication and authorization.
- Add metrics and monitoring, e.g., log metrics to Prometheus or other monitoring system.

**Confidence in findings:** HIGH for cancellation-unsafe publish loop and no subscriber lock or atomicity between subscribe/unsubscribe and publish, MEDIUM for engine publish points add latency and potential engine stall if queues full, and no ordering guarantees between events in same tick, and LOW for other findings.

**Overall verdict:** CONDITIONAL. Do not deploy to production until critical and high severity issues are addressed.
