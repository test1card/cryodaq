# Code Review: GemmaAgent (F28 Cycle 2, Slice A)

## Verdict: **CONDITIONAL**

---

### Finding 1 — MEDIUM: Silent event_type semantic change in engine.py

**File:** `src/cryodaq/engine.py:1661`

```python
# BEFORE — explicit mapping:
event_type="experiment_finalize" if action != "experiment_abort" else "experiment_abort"

# AFTER — raw pass-through:
event_type=action
```

Old code mapped *all* non-abort actions → `"experiment_finalize"`. New code passes the raw action string. This enables granular triggers (`phase_transition_to_finalize`) but **silently breaks any existing subscriber** that relied on the catch-all `"experiment_finalize"`. The config lists both `experiment_finalize` and `phase_transition_to_finalize` as separate triggers — GemmaAgent handles both, but other EventBus subscribers (safety_manager, shift logger) may not.

**Fix:** Either add a whitelist mapping for known action→event_type, or document this as a breaking change and audit all `alarm_fired`/`experiment_finalize` subscribers.

---

### Finding 2 — MEDIUM: Alarm handler may block EventBus publisher

**File:** `src/cryodaq/agents/gemma.py` (truncated, ~line 200–250)

If `GemmaAgent._handle_alarm()` is subscribed as a direct `EventBus.subscribe()` callback and the EventBus `publish()` awaits all handlers sequentially, then a 30-second Ollama timeout **blocks the publisher** — including the safety-critical alarm dispatch path. This is unacceptable in a safety-critical DAQ.

**Fix:** The handler must internally `asyncio.create_task()` and return immediately, or the EventBus must fire subscriptions as detached tasks. Confirm `EventBus.publish` does not await subscriber coroutines inline.

---

### Finding 3 — MEDIUM: OutputRouter calls private method on Telegram bot

**File:** `src/cryodaq/agents/output_router.py:51`

```python
await self._telegram._send_to_all(prefixed)
```

Calling `_send_to_all` (double underscore = private by convention) creates a fragile coupling. If the Telegram bot refactors its internal API, the router silently breaks.

**Fix:** Add a public `send_message(text: str)` method to the Telegram bot interface and call that instead.

---

### Finding 4 — LOW: No validation of `alarm_min_level` → potential KeyError

**File:** `src/cryodaq/agents/gemma.py` (GemmaConfig + level check)

`from_dict` accepts any string for `alarm_min_level`. The runtime lookup `_MIN_LEVELS[level]` raises `KeyError` on an invalid value like `"ERROR"` — caught by the outer `except Exception`, but the agent silently disables instead of failing fast with a clear config error.

**Fix:** Validate in `from_dict`:
```python
if cfg.alarm_min_level not in _MIN_LEVELS:
    raise ValueError(f"alarm_min_level must be one of {list(_MIN_LEVELS)}, got {cfg.alarm_min_level!r}")
```

---

### Finding 5 — LOW: Late imports inside OutputRouter.dispatch hint at circular dependency

**File:** `src/cryodaq/agents/output_router.py:65–68`

```python
elif target == OutputTarget.GUI_INSIGHT:
    from datetime import UTC, datetime
    from cryodaq.core.event_bus import EngineEvent as _EngineEvent
```

Top of file already imports `EngineEvent` under `TYPE_CHECKING`. The runtime late-import + alias suggests a circular dependency that was worked around rather than resolved. `datetime` has no circular risk — move it to the top.

**Fix:** Restructure to avoid the circular import. Consider having `dispatch` accept a factory callable or emit a plain dict that the caller wraps into `EngineEvent`.

---

### Finding 6 — LOW: event_logger.log_event reorder changes audit ordering

**File:** `src/cryodaq/engine.py:1678`

```python
# BEFORE: log first, then publish
# AFTER:  publish first, then log
```

Now the event reaches subscribers (including Гемма) *before* it's persisted to the operator log. If the process crashes between publish and log, the audit trail loses the event while subscribers already acted on it. For a safety-critical system, log-then-publish is the safer order.

**Fix:** Revert to log-then-publish ordering.

---

### Finding 7 — INFO: Init exception missing traceback

**File:** `src/cryodaq/engine.py:1907`

```python
except Exception as _gemma_exc:
    logger.warning("GemmaAgent: ошибка инициализации — %s", _gemma_exc)
```

No `exc_info=True` — the traceback is lost, making Ollama-connection failures hard to diagnose in production.

**Fix:** Add `exc_info=True` to the logger.warning call.

---

### Safety assessment: No engine-state-modification path found ✓

GemmaAgent is read-only w.r.t. engine state. `OutputRouter` publishes a `gemma_insight` event (new type, no known state-mutating subscribers). Prompts explicitly prohibit safety-action suggestions. **No violations detected.**

---

### Must-fix before merge: Findings 1, 2
### Should-fix: Findings 3, 4, 6
