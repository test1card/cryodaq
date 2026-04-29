# F28 Cycle 0 Audit — EventBus Foundation

## Verdict: CONDITIONAL

Four findings require remediation before merge; one is critical for a safety-critical context.

---

### Finding 1 — Duplicate `subscribe` silently orphans consumer tasks

- **Severity: CRITICAL**
- **Location:** `src/cryodaq/core/event_bus.py:33-36`
- **Description:** `subscribe()` overwrites any existing queue for the same name without warning. If an agent restarts and re-subscribes with the same name, or two independent subsystems choose the same name, the first queue is silently replaced. Any task `await`ing `q.get()` on the old queue will block forever — no more events arrive, no exception is raised. In a safety-critical context this means an alarm-monitoring agent silently stops receiving `alarm_fired` events.

  ```python
  async def subscribe(self, name: str, *, maxsize: int = 1000) -> asyncio.Queue[EngineEvent]:
      q: asyncio.Queue[EngineEvent] = asyncio.Queue(maxsize=maxsize)
      self._subscribers[name] = q  # silently replaces
      return q
  ```

- **Recommended fix:** Raise `ValueError` on duplicate name, or at minimum log a warning and close the old queue (e.g., push a sentinel). Add a test for the duplicate-name case.

---

### Finding 2 — Alarm events silently dropped with no observability

- **Severity: HIGH**
- **Location:** `src/cryodaq/core/event_bus.py:43-49`
- **Description:** `publish()` drops events on `QueueFull` with only a `logger.warning`. For a cryogenic DAQ system, `alarm_fired` is safety-critical. A slow subscriber (e.g., Гемма LLM inference lagging) causes alarm events to be silently discarded with no metric, no counter, and no callback. Operators cannot detect this failure mode from dashboards or health checks.

  ```python
  except asyncio.QueueFull:
      logger.warning(
          "EventBus: subscriber '%s' queue full, dropping %s",
          name, event.event_type,
      )
  ```

- **Recommended fix:** Add a `dropped: dict[str, int]` counter per subscriber. Expose it via a property/method so health monitors can detect drops. At minimum, consider a callback hook or elevated log level (`ERROR`) for safety-critical event types (`alarm_fired`, `alarm_cleared`). Add a test for the QueueFull path (currently untested).

---

### Finding 3 — `event_logged` fires *before* `phase_transition` for the same logical operation

- **Severity: MEDIUM**
- **Location:** `src/cryodaq/engine.py:1653-1665` (phase_advance handler) and `src/cryodaq/core/event_logger.py:48-59`
- **Description:** When a phase transition occurs, `event_logger.log_event()` is called first, which internally publishes `event_logged` to the bus. Then engine.py publishes `phase_transition`. Subscribers thus see: (1) `event_logged` for a phase they haven't been notified about yet, then (2) `phase_transition`. This inverted causality can confuse agent logic — an agent sees a log about "→ COOL" before seeing the actual `phase_transition` event.

  ```python
  # engine.py — phase advance handler
  await event_logger.log_event("phase", f"Фаза: → {phase}")   # publishes event_logged
  _active = experiment_manager.active_experiment
  await event_bus.publish(EngineEvent(event_type="phase_transition", ...))  # second
  ```

- **Recommended fix:** Swap the order: publish `phase_transition` first, then call `log_event`. Or decouple `log_event` from the bus (remove the internal publish from `log_event`) and have the engine publish both events in the correct causal order. Document the intended ordering contract.

---

### Finding 4 — `experiment_stop` maps to `experiment_finalize` event_type, losing semantic distinction

- **Severity: MEDIUM**
- **Location:** `src/cryodaq/engine.py:1640-1651`
- **Description:** Both `experiment_stop` and `experiment_finalize` actions produce `event_type="experiment_finalize"`. These are semantically different operations in the existing engine — stop may be graceful early termination, finalize is end-of-experiment data sealing. Agents cannot distinguish them from the event alone.

  ```python
  event_type="experiment_finalize"
  if action != "experiment_abort"
  else "experiment_abort",
  ```

  Also, the actual `action` is stored in `payload["action"]`, but event_type is the primary routing key subscribers will filter on.

- **Recommended fix:** Use distinct event types: `experiment_stop`, `experiment_finalize`, `experiment_abort`. Alternatively
