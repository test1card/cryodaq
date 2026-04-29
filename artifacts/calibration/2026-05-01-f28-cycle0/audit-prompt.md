# F28 Cycle 0 audit — EventBus foundation

## Context

CryoDAQ is a production cryogenic data-acquisition system replacing a 3-year-old LabVIEW VI. Safety-critical, 1992+ tests. Currently v0.44.0 master. Python 3.12+, asyncio, PySide6.

Cycle 0 of F28 (Гемма local LLM agent) adds an EventBus primitive for non-Reading engine events. This is a foundational change touching multiple core subsystems.

Pre-existing event flow:
- AlarmStateManager returns TRIGGERED/CLEARED transitions (called from engine._alarm_v2_tick)
- ExperimentManager advance_phase() — sync method called from async command handler
- EventLogger.log_event() — async, writes to SQLite

The new EventBus is a single subscribe point for all engine event types (alarm transitions, phase transitions, experiment lifecycle, event_logger appends). Future agents (Гемма) will subscribe.

## Files changed

- `src/cryodaq/core/event_bus.py` — NEW (57 LOC)
- `src/cryodaq/core/event_logger.py` — MODIFIED (+35 LOC)
- `src/cryodaq/engine.py` — MODIFIED (+55 LOC)
- `tests/core/test_event_bus.py` — NEW (130 LOC)

## Diff

```
26d4162 feat(f28): Cycle 0 — EventBus foundation (9 minutes ago) <Vladimir Fomenko>
src/cryodaq/core/event_bus.py    |  60 ++++++++++++
 src/cryodaq/core/event_logger.py |  35 ++++++-
 src/cryodaq/engine.py            |  55 ++++++++++-
 tests/core/test_event_bus.py     | 195 +++++++++++++++++++++++++++++++++++++++
 4 files changed, 340 insertions(+), 5 deletions(-)

src/cryodaq/core/event_bus.py
  @@ -0,0 +1,60 @@
  +"""Lightweight pub/sub event bus for engine events (not Reading data)."""
  +
  +from __future__ import annotations
  +
  +import asyncio
  +import logging
  +from dataclasses import dataclass
  +from datetime import datetime
  +from typing import Any
  +
  +logger = logging.getLogger(__name__)
  +
  +
  +@dataclass
  +class EngineEvent:
  +    """An engine-level event published to EventBus subscribers."""
  +
  +    event_type: str  # "alarm_fired", "alarm_cleared", "phase_transition", "experiment_finalize", …
  +    timestamp: datetime
  +    payload: dict[str, Any]
  +    experiment_id: str | None = None
  +
  +
  +class EventBus:
  +    """Lightweight pub/sub for engine events (not Reading data).
  +
  +    Subscribers receive a dedicated asyncio.Queue. Publish is non-blocking:
  +    a full queue logs a warning and drops the event rather than blocking
  +    the engine event loop.
  +    """
  +
  +    def __init__(self) -> None:
  +        self._subscribers: dict[str, asyncio.Queue[EngineEvent]] = {}
  +
  +    async def subscribe(self, name: str, *, maxsize: int = 1000) -> asyncio.Queue[EngineEvent]:
  +        """Register a named subscriber and return its dedicated queue."""
  +        q: asyncio.Queue[EngineEvent] = asyncio.Queue(maxsize=maxsize)
  +        self._subscribers[name] = q
  +        return q
  +
  +    def unsubscribe(self, name: str) -> None:
  +        """Remove a subscriber by name. No-op if not registered."""
  +        self._subscribers.pop(name, None)
  +
  +    async def publish(self, event: EngineEvent) -> None:
  +        """Fan out event to all subscriber queues (non-blocking; drops on full)."""
  +        for name, q in list(self._subscribers.items()):
  +            try:
  +                q.put_nowait(event)
  +            except asyncio.QueueFull:
  +                logger.warning(
  +                    "EventBus: subscriber '%s' queue full, dropping %s",
  +                    name,
  +                    event.event_type,
  +                )
  +
  +    @property
  +    def subscriber_count(self) -> int:
  +        """Number of currently registered subscribers."""
  +        return len(self._subscribers)
  +60 -0

src/cryodaq/core/event_logger.py
  @@ -3,7 +3,11 @@
  -from typing import Any
  +from datetime import UTC, datetime
  +from typing import TYPE_CHECKING, Any
  +
  +if TYPE_CHECKING:
  +    from cryodaq.core.event_bus import EventBus
   
   logger = logging.getLogger(__name__)
   
  @@ -11,9 +15,16 @@ logger = logging.getLogger(__name__)
  -    def __init__(self, writer: Any, experiment_manager: Any) -> None:
  +    def __init__(
  +        self,
  +        writer: Any,
  +        experiment_manager: Any,
  +        *,
  +        event_bus: EventBus | None = None,
  +    ) -> None:
           self._writer = writer
           self._em = experiment_manager
  +        self._event_bus = event_bus
   
       async def log_event(
           self,
  @@ -22,14 +33,30 @@ class EventLogger:
  -        """Write an auto-log entry. Fails silently on error."""
  +        """Write an auto-log entry to SQLite and publish to EventBus."""
  +        experiment_id = self._em.active_experiment_id
           try:
               await self._writer.append_operator_log(
                   message=message,
                   author="system",
                   source="auto",
  -                experiment_id=self._em.active_experiment_id,
  +                experiment_id=experiment_id,
                   tags=["auto", event_type, *(extra_tags or [])],
               )
           except Exception:
               logger.warning("Failed to auto-log event: %s", message, exc_info=True)
  +
  +        if self._event_bus is not None:
  +            from cryodaq.core.event_bus import EngineEvent
  +
  +            try:
  +                await self._event_bus.publish(
  +                    EngineEvent(
  +                        event_type="event_logged",
  +                        timestamp=datetime.now(UTC),
  +                        payload={"event_type": event_type, "message": message},
  +                        experiment_id=experiment_id,
  +                    )
  +                )
  +            except Exception:
  +                logger.warning("EventBus publish failed in log_event", exc_info=True)
  +31 -4

src/cryodaq/engine.py
  @@ -45,6 +45,7 @@ from cryodaq.core.calibration_acquisition import (
  +from cryodaq.core.event_bus import EngineEvent, EventBus
   from cryodaq.core.event_logger import EventLogger
   from cryodaq.core.experiment import ExperimentManager, ExperimentStatus
   from cryodaq.core.housekeeping import (
  @@ -1117,7 +1118,8 @@ async def _run_engine(*, mock: bool = False) -> None:
  -    event_logger = EventLogger(writer, experiment_manager)
  +    event_bus = EventBus()
  +    event_logger = EventLogger(writer, experiment_manager, event_bus=event_bus)
   
       # --- F13: Leak rate estimator ---
       _instruments_raw = yaml.safe_load(instruments_cfg.read_text(encoding="utf-8"))
  @@ -1278,6 +1280,29 @@ async def _run_engine(*, mock: bool = False) -> None:
  +                        await event_bus.publish(
  +                            EngineEvent(
  +                                event_type="alarm_fired",
  +                                timestamp=datetime.now(UTC),
  +                                payload={
  +                                    "alarm_id": event.alarm_id,
  +                                    "level": event.level,
  +                                    "message": event.message,
  +                                    "channels": event.channels,
  +                                    "values": event.values,
  +                                },
  +                                experiment_id=experiment_manager.active_experiment_id,
  +                            )
  +                        )
  +                    elif transition == "CLEARED":
  +                        await event_bus.publish(
  +                            EngineEvent(
  +                                event_type="alarm_cleared",
  +                                timestamp=datetime.now(UTC),
  +                                payload={"alarm_id": alarm_cfg.alarm_id},
  +                                experiment_id=experiment_manager.active_experiment_id,
  +                            )
  +                        )
                   except Exception as exc:
                       logger.error("Alarm v2 tick error %s: %s", alarm_cfg.alarm_id, exc)
   
  @@ -1610,6 +1635,14 @@ async def _run_engine(*, mock: bool = False) -> None:
  +                    await event_bus.publish(
  +                        EngineEvent(
  +                            event_type="experiment_start",
  +                            timestamp=datetime.now(UTC),
  +                            payload={"name": name, "experiment_id": result.get("experiment_id")},
  +                            experiment_id=result.get("experiment_id"),
  +                        )
  +                    )
                   elif result.get("ok") and action in {
                       "experiment_finalize",
                       "experiment_stop",
  @@ -1620,9 +1653,29 @@ async def _run_engine(*, mock: bool = False) -> None:
  +                    _exp_info = result.get("experiment", {})
  +                    await event_bus.publish(
  +                        EngineEvent(
  +                            event_type="experiment_finalize"
  +                            if action != "experiment_abort"
  +                            else "experiment_abort",
  +                            timestamp=datetime.now(UTC),
  +                            payload={"action": action, "experiment": _exp_info},
  +                            experiment_id=_exp_info.get("experiment_id"),
  +                        )
  +                    )
                   elif result.get("ok") and action == "experiment_advance_phase":
                       phase = cmd.get("phase", "?")
                       await event_logger.log_event("phase", f"Фаза: → {phase}")
  +                    _active = experiment_manager.active_experiment
  +                    await event_bus.publish(
  +                        EngineEvent(
  +                            event_type="phase_transition",
  +                            timestamp=datetime.now(UTC),
  +                            payload={"phase": phase, "entry": result.get("phase", {})},
  +                            experiment_id=_active.experiment_id if _active else None,
  +                        )
  +                    )
                   return result
               if action == "calibration_acquisition_status":
                   return {"ok": True, **calibration_acquisition.stats}
  +54 -1

tests/core/test_event_bus.py
  @@ -0,0 +1,195 @@
  +"""Tests for EventBus — pub/sub for engine events."""
  +
  +from __future__ import annotations
  +
  +from datetime import UTC, datetime
  +from unittest.mock import patch
  +
  +from cryodaq.core.event_bus import EngineEvent, EventBus
  +
  +# ---------------------------------------------------------------------------
  +# Helpers
  +# ---------------------------------------------------------------------------
  +
  +
  +def _event(event_type: str = "alarm_fired", experiment_id: str | None = "exp-001") -> EngineEvent:
  +    return EngineEvent(
  +        event_type=event_type,
  +        timestamp=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
  +        payload={"key": "value"},
  +        experiment_id=experiment_id,
  +    )
  +
  +
  +# ---------------------------------------------------------------------------
  +# EngineEvent dataclass
  +# ---------------------------------------------------------------------------
  +
  +
  +def test_engine_event_fields() -> None:
  +    ts = datetime(2026, 5, 1, tzinfo=UTC)
  +    ev = EngineEvent(
  +        event_type="phase_transition",
  +        timestamp=ts,
  +        payload={"phase": "COOL"},
  +        experiment_id="exp-42",
  +    )
  +    assert ev.event_type == "phase_transition"
  +    assert ev.timestamp == ts
  +    assert ev.payload == {"phase": "COOL"}
  +    assert ev.experiment_id == "exp-42"
  +
  +
  +def test_engine_event_experiment_id_defaults_none() -> None:
  +    ev = EngineEvent(
  +        event_type="alarm_cleared",
  +        timestamp=datetime.now(UTC),
  +        payload={},
  +    )
  +    assert ev.experiment_id is None
  +
  +
  +# ---------------------------------------------------------------------------
  +# EventBus — subscribe / publish
  +# ---------------------------------------------------------------------------
  +
  +
  +async def test_subscribe_returns_queue() -> None:
  +    bus = EventBus()
  +    q = await bus.subscribe("test")
  +    assert q is not None
  +    assert q.empty()
  +
  +
  +async def test_publish_delivers_to_subscriber() -> None:
  +    bus = EventBus()
  +    q = await bus.subscribe("consumer")
  +    ev = _event("alarm_fired")
  +
  +    await bus.publish(ev)
  +
  +    assert not q.empty()
  +    received = q.get_nowait()
  +    assert received is ev
  +    assert received.event_type == "alarm_fired"
  +
  +
  +async def test_publish_fanout_to_multiple_subscribers() -> None:
  +    bus = EventBus()
  +    q1 = await bus.subscribe("a")
  +    q2 = await bus.subscribe("b")
  +    q3 = await bus.subscribe("c")
  +    ev = _event("experiment_finalize")
  +
  +    await bus.publish(ev)
  +
  +    assert q1.get_nowait() is ev
  +    assert q2.get_nowait() is ev
  +    assert q3.get_nowait() is ev
  +
  +
  +async def test_publish_no_subscribers_does_not_raise() -> None:
  +    bus = EventBus()
  +    await bus.publish(_event())  # should not raise
  +
  +
  +async def test_publish_multiple_events_ordered() -> None:
  +    bus = EventBus()
  +    q = await bus.subscribe("ordered")
  +
  +    ev1 = _event("alarm_fired")
  ... (95 lines truncated)
  +195 -0
[full diff: rtk git diff --no-compact]

```

## Your task

Review this commit with safety-critical mindset. Look for:

1. **Concurrency issues:** EventBus is async pub/sub. Are queue operations safe? Backpressure handling on slow subscribers? Cancellation safety?
2. **Engine integration breakage:** does adding 6 publish points to engine.py change ordering of existing operations? Could alarm dispatch be delayed by EventBus publish? Could a publish failure crash the engine?
3. **Event ordering guarantees:** when alarm fires AND phase transitions in same tick, do EventBus subscribers see them in correct order?
4. **Memory safety:** unbounded queue growth if no subscribers? Subscriber slow consumer behavior?
5. **Test coverage gaps:** what edge cases are NOT covered by the 130 LOC of new tests?
6. **Additional concerns** specific to safety-critical asyncio engine.

## Output format

Verdict: PASS / CONDITIONAL / FAIL

For each finding:
- Severity: CRITICAL / HIGH / MEDIUM / LOW
- Location: file:line reference
- Description: what is wrong
- Recommended fix

If no findings: brief explanation of why confidence is high.

## Constraints

- Be specific. Vague concerns ("may have issues") are not findings.
- Reference exact lines from the diff. Don't speculate about code not shown.
- Keep response under 2000 words. Quality over quantity.
