"""Tests for InterlockEngine — safety interlock logic for cryogenic equipment."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from cryodaq.core.broker import DataBroker
from cryodaq.core.interlock import (
    InterlockCondition,
    InterlockConfigError,
    InterlockEngine,
    InterlockState,
)
from cryodaq.drivers.base import Reading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_condition(
    name: str = "high_temp",
    description: str = "Temperature too high",
    channel_pattern: str = r"T\d+",
    threshold: float = 300.0,
    comparison: str = ">",
    action: str = "emergency_off",
    cooldown_s: float = 0.0,
) -> InterlockCondition:
    return InterlockCondition(
        name=name,
        description=description,
        channel_pattern=channel_pattern,
        threshold=threshold,
        comparison=comparison,
        action=action,
        cooldown_s=cooldown_s,
    )


async def _make_engine(
    *,
    action_name: str = "emergency_off",
    action_fn=None,
) -> tuple[DataBroker, InterlockEngine, list]:
    """Return (broker, engine, called_list) with engine already started."""
    called: list[bool] = []

    async def _default_action() -> None:
        called.append(True)

    broker = DataBroker()
    engine = InterlockEngine(
        broker=broker,
        actions={action_name: action_fn if action_fn is not None else _default_action},
    )
    await engine.start()
    return broker, engine, called


# ---------------------------------------------------------------------------
# 1. ARMED → TRIPPED when condition is met; action is called
# ---------------------------------------------------------------------------


async def test_armed_to_tripped() -> None:
    broker, engine, called = await _make_engine()
    engine.add_condition(_make_condition(threshold=300.0, comparison=">"))

    await broker.publish(Reading.now("T1", 350.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)

    states = engine.get_state()
    assert states["high_temp"] == InterlockState.TRIPPED
    assert len(called) == 1

    await engine.stop()


# ---------------------------------------------------------------------------
# 2. TRIPPED → ARMED after acknowledge()
# ---------------------------------------------------------------------------


async def test_tripped_to_acknowledged() -> None:
    broker, engine, called = await _make_engine()
    engine.add_condition(_make_condition(threshold=300.0, comparison=">"))

    await broker.publish(Reading.now("T1", 350.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)

    assert engine.get_state()["high_temp"] == InterlockState.TRIPPED

    engine.acknowledge("high_temp")

    assert engine.get_state()["high_temp"] == InterlockState.ARMED

    await engine.stop()


# ---------------------------------------------------------------------------
# 3. Cooldown dedups the notification but the protective action still runs
# ---------------------------------------------------------------------------


async def test_cooldown_dedups_notification_but_still_protects(caplog) -> None:
    """Interlocks are latching (TRIPPED → ARMED only via operator acknowledge).
    If the operator acknowledges while the value is STILL in breach, the
    protection must re-trip and re-run the action — it must NOT go blind for the
    rest of the cooldown window. The cooldown only deduplicates the loud
    operator-facing CRITICAL announcement, not the protective action."""
    import logging

    broker, engine, called = await _make_engine()
    # Very long cooldown so the second breach definitely falls within it.
    engine.add_condition(_make_condition(threshold=300.0, comparison=">", cooldown_s=60.0))

    # First trip → action runs, loud CRITICAL announcement emitted.
    await broker.publish(Reading.now("T1", 350.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)
    assert engine.get_state()["high_temp"] == InterlockState.TRIPPED
    assert len(called) == 1

    # Operator acknowledges but the cause is NOT fixed (value still > threshold).
    engine.acknowledge("high_temp")
    assert engine.get_state()["high_temp"] == InterlockState.ARMED

    caplog.clear()
    with caplog.at_level(logging.CRITICAL, logger="cryodaq.core.interlock"):
        await broker.publish(Reading.now("T1", 400.0, "K", instrument_id="test"))
        await asyncio.sleep(0.05)

    # MUST re-trip: protection is not blinded by the cooldown.
    assert engine.get_state()["high_temp"] == InterlockState.TRIPPED
    assert len(called) == 2, "protective action must run again on the persisting breach"
    # ...but the loud trip announcement is deduplicated within the cooldown window.
    assert "БЛОКИРОВКА СРАБОТАЛА" not in caplog.text

    await engine.stop()


async def test_cooldown_does_not_suppress_first_announcement(caplog) -> None:
    """Sanity: the FIRST trip (no prior last_trip_time) is never suppressed."""
    import logging

    broker, engine, called = await _make_engine()
    engine.add_condition(_make_condition(threshold=300.0, comparison=">", cooldown_s=60.0))

    caplog.clear()
    with caplog.at_level(logging.CRITICAL, logger="cryodaq.core.interlock"):
        await broker.publish(Reading.now("T1", 350.0, "K", instrument_id="test"))
        await asyncio.sleep(0.05)

    assert len(called) == 1
    assert "БЛОКИРОВКА СРАБОТАЛА" in caplog.text

    await engine.stop()


# ---------------------------------------------------------------------------
# 4. Action callable is awaited (async)
# ---------------------------------------------------------------------------


async def test_action_called_async() -> None:
    """Prove the check loop SERIALLY AWAITS each action before processing any further reading.

    Production code (_check_loop): a single ``async for`` loop over the subscriber
    queue; each trip does ``await self._trip(...)`` which does ``await action_callable()``.
    While one action is blocked, the loop cannot dequeue ANY subsequent reading —
    including readings for DIFFERENT conditions on DIFFERENT channels.

    Strategy — two independent conditions on separate channels:

    1. Condition A on channel "T1" with action_a that blocks on ``action_a_gate``.
       Condition B on channel "T2" with action_b that sets ``action_b_started`` on entry.
    2. Publish T1 reading → wait until action_a is running (deterministic via Event).
    3. While action_a is gated, publish T2 reading.
       Assert action_b has NOT started via a BOUNDED NEGATIVE wait (0.2 s timeout).
       If prod were fire-and-forget, action_b would start immediately and this
       bounded-wait would NOT raise — proving the test has teeth.
    4. Release action_a_gate → the loop drains.
       Assert action_b DOES start (positive wait, 1.0 s timeout).
    """
    action_a_started = asyncio.Event()
    action_a_gate = asyncio.Event()
    action_b_started = asyncio.Event()

    async def action_a() -> None:
        action_a_started.set()
        await action_a_gate.wait()

    async def action_b() -> None:
        action_b_started.set()

    broker = DataBroker()
    engine = InterlockEngine(
        broker=broker,
        actions={"action_a": action_a, "action_b": action_b},
    )
    # Condition A: T1 channel, threshold 300, action_a
    engine.add_condition(
        InterlockCondition(
            name="cond_a",
            description="Condition A on T1",
            channel_pattern=r"T1",
            threshold=300.0,
            comparison=">",
            action="action_a",
        )
    )
    # Condition B: T2 channel, threshold 300, action_b
    engine.add_condition(
        InterlockCondition(
            name="cond_b",
            description="Condition B on T2",
            channel_pattern=r"T2",
            threshold=300.0,
            comparison=">",
            action="action_b",
        )
    )
    await engine.start()

    try:
        # Step 1 — trip condition A and wait until action_a is running and blocked
        await broker.publish(Reading.now("T1", 999.0, "K", instrument_id="test"))
        await asyncio.wait_for(action_a_started.wait(), timeout=1.0)

        # Step 2 — while action_a is gated, enqueue a T2 reading for condition B
        await broker.publish(Reading.now("T2", 999.0, "K", instrument_id="test"))

        # Step 3 — NEGATIVE assertion: action_b must NOT start while action_a is blocked.
        # A fire-and-forget implementation would start action_b immediately and this
        # would NOT raise TimeoutError — so a raise here is the proof of serial awaiting.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(action_b_started.wait(), timeout=0.2)

        # Step 4 — release action_a; the loop now processes the queued T2 reading
        action_a_gate.set()

        # Positive assertion: action_b MUST start once the loop is unblocked
        await asyncio.wait_for(action_b_started.wait(), timeout=1.0)

    finally:
        # Ensure gate is released so action_a coroutine can finish before stop()
        action_a_gate.set()
        await engine.stop()


# ---------------------------------------------------------------------------
# 5. Regex channel_pattern matches correct channels
# ---------------------------------------------------------------------------


async def test_regex_channel_matching() -> None:
    broker, engine, called = await _make_engine()
    # Pattern matches T1 through T8
    engine.add_condition(
        _make_condition(channel_pattern=r"T[1-8]", threshold=300.0, comparison=">")
    )

    await broker.publish(Reading.now("T5", 350.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)

    assert engine.get_state()["high_temp"] == InterlockState.TRIPPED
    assert len(called) == 1

    await engine.stop()


# ---------------------------------------------------------------------------
# 6. Non-matching channel does not trigger interlock
# ---------------------------------------------------------------------------


async def test_regex_no_match_ignored() -> None:
    broker, engine, called = await _make_engine()
    engine.add_condition(
        _make_condition(channel_pattern=r"T[1-8]", threshold=300.0, comparison=">")
    )

    # "PRESSURE_1" does not match T[1-8]
    await broker.publish(Reading.now("PRESSURE_1", 9999.0, "Pa", instrument_id="test"))
    await asyncio.sleep(0.05)

    assert engine.get_state()["high_temp"] == InterlockState.ARMED
    assert len(called) == 0

    await engine.stop()


# ---------------------------------------------------------------------------
# 7. Greater-than comparison triggers when value > threshold
# ---------------------------------------------------------------------------


async def test_greater_than_comparison() -> None:
    broker, engine, called = await _make_engine()
    engine.add_condition(_make_condition(threshold=100.0, comparison=">"))

    # Value exactly at threshold — should NOT trip
    await broker.publish(Reading.now("T1", 100.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)
    assert engine.get_state()["high_temp"] == InterlockState.ARMED

    # Value above threshold — should trip
    await broker.publish(Reading.now("T1", 100.001, "K", instrument_id="test"))
    await asyncio.sleep(0.05)
    assert engine.get_state()["high_temp"] == InterlockState.TRIPPED
    assert len(called) == 1

    await engine.stop()


# ---------------------------------------------------------------------------
# 8. Less-than comparison triggers when value < threshold
# ---------------------------------------------------------------------------


async def test_less_than_comparison() -> None:
    broker, engine, called = await _make_engine()
    engine.add_condition(_make_condition(threshold=2.0, comparison="<", channel_pattern=r"T\d+"))

    # Value above threshold — should NOT trip
    await broker.publish(Reading.now("T1", 3.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)
    assert engine.get_state()["high_temp"] == InterlockState.ARMED

    # Value below threshold — should trip
    await broker.publish(Reading.now("T1", 1.5, "K", instrument_id="test"))
    await asyncio.sleep(0.05)
    assert engine.get_state()["high_temp"] == InterlockState.TRIPPED
    assert len(called) == 1

    await engine.stop()


# ---------------------------------------------------------------------------
# 9. Events are recorded in get_events()
# ---------------------------------------------------------------------------


async def test_event_history() -> None:
    broker, engine, called = await _make_engine()
    engine.add_condition(_make_condition(threshold=300.0, comparison=">"))

    await broker.publish(Reading.now("T1", 350.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)

    events = engine.get_events()
    assert len(events) == 1
    ev = events[0]
    assert ev.interlock_name == "high_temp"
    assert ev.channel == "T1"
    assert ev.value == 350.0
    assert ev.threshold == 300.0
    assert ev.action_taken == "emergency_off"

    await engine.stop()


# ---------------------------------------------------------------------------
# 10. Event history is bounded at 1000 events
# ---------------------------------------------------------------------------


async def test_event_history_bounded() -> None:
    broker = DataBroker()
    trip_count = 0

    async def counting_action() -> None:
        nonlocal trip_count
        trip_count += 1

    engine = InterlockEngine(broker=broker, actions={"emergency_off": counting_action})
    # Use cooldown_s=0 so every reading can trip; interlock re-arms each time
    engine.add_condition(_make_condition(threshold=300.0, comparison=">", cooldown_s=0.0))
    await engine.start()

    # Publish 1100 readings that all exceed the threshold.
    # After each trip we acknowledge so the interlock goes back to ARMED.
    for _ in range(1100):
        await broker.publish(Reading.now("T1", 350.0, "K", instrument_id="test"))
        await asyncio.sleep(0.001)
        engine.acknowledge("high_temp")

    await asyncio.sleep(0.05)

    events = engine.get_events()
    assert len(events) <= 1000, f"Expected at most 1000 events, got {len(events)}"

    await engine.stop()


# ---------------------------------------------------------------------------
# 11. load_config reads from a YAML file
# ---------------------------------------------------------------------------


async def test_load_config_yaml(tmp_path: Path, caplog) -> None:
    """load_config must parse threshold, comparison, channel_pattern, action, and cooldown_s.

    All fields are verified BEHAVIORALLY — no private internals accessed:
    1. A reading that matches the pattern AND exceeds the threshold trips the interlock
       and fires the action.
    2. A reading on a non-matching channel does NOT trip.
    3. After acknowledging and re-arming, a second matching reading within the cooldown
       window still PROTECTS (re-trips + re-runs the action) but the loud trip
       announcement is deduplicated — proving cooldown_s was loaded and is active.
    """
    config_data = {
        "interlocks": [
            {
                "name": "overheat",
                "description": "Overheating protection",
                "channel_pattern": r"T\d+",
                "threshold": 400.0,
                "comparison": ">",
                "action": "emergency_off",
                "cooldown_s": 60.0,  # long cooldown — second trip must be blocked
            }
        ]
    }
    config_file = tmp_path / "interlocks.yaml"
    config_file.write_text(yaml.dump(config_data), encoding="utf-8")

    action_count: list[int] = [0]

    async def _action() -> None:
        action_count[0] += 1

    broker = DataBroker()
    engine = InterlockEngine(broker=broker, actions={"emergency_off": _action})
    engine.load_config(config_file)

    # Interlock must be registered and start ARMED
    states = engine.get_state()
    assert "overheat" in states, "Interlock 'overheat' not registered after load_config"
    assert states["overheat"] == InterlockState.ARMED

    await engine.start()
    try:
        # --- Behavioral check 1: matching channel + above threshold → TRIPPED, action fired ---
        await broker.publish(Reading.now("T5", 450.0, "K", instrument_id="test"))
        await asyncio.sleep(0.05)
        assert engine.get_state()["overheat"] == InterlockState.TRIPPED, (
            "Interlock loaded from YAML did not trip on T5=450 > 400 (threshold not loaded)"
        )
        assert action_count[0] == 1, (
            "YAML-loaded action was not called on first trip"
        )

        # --- Behavioral check 2: non-matching channel does NOT trip ---
        # acknowledge() transitions TRIPPED → ARMED (not a separate ACKNOWLEDGED state)
        engine.acknowledge("overheat")
        await asyncio.sleep(0.01)
        assert engine.get_state()["overheat"] == InterlockState.ARMED, (
            "Expected ARMED after acknowledge()"
        )
        # "PRESSURE_1" does not match r"T\d+" — must stay ARMED (not re-tripped)
        await broker.publish(Reading.now("PRESSURE_1", 9999.0, "Pa", instrument_id="test"))
        await asyncio.sleep(0.05)
        assert engine.get_state()["overheat"] == InterlockState.ARMED, (
            "Non-matching channel 'PRESSURE_1' unexpectedly tripped 'overheat' "
            "(channel_pattern may not have been loaded)"
        )

        # --- Behavioral check 3: cooldown_s loaded → re-trip within the window
        #     still protects (action runs) but the loud announcement is deduped ---
        # After acknowledge, state is ARMED with last_trip_time set.
        import logging

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="cryodaq.core.interlock"):
            await broker.publish(Reading.now("T5", 450.0, "K", instrument_id="test"))
            await asyncio.sleep(0.05)
        # Protection is NOT blinded by the cooldown — it re-trips and re-acts.
        assert engine.get_state()["overheat"] == InterlockState.TRIPPED, (
            "Interlock must re-trip on a persisting breach after acknowledge"
        )
        assert action_count[0] == 2, (
            f"Action fired {action_count[0]} times; the protective action must run "
            "again on the persisting breach (protection not blinded by cooldown)"
        )
        # cooldown_s=60 loaded & active → the loud trip announcement is deduped,
        # and a cooldown-dedup WARNING is emitted instead.
        assert "БЛОКИРОВКА СРАБОТАЛА" not in caplog.text, (
            "loud trip announcement must be deduplicated within cooldown_s "
            "(cooldown_s may not have been loaded)"
        )
        assert "кулдаун" in caplog.text.lower()
    finally:
        await engine.stop()


# ---------------------------------------------------------------------------
# 12. add_condition with unknown action raises ValueError
# ---------------------------------------------------------------------------


async def test_missing_action_rejected() -> None:
    broker = DataBroker()
    engine = InterlockEngine(broker=broker, actions={"emergency_off": lambda: None})

    with pytest.raises(ValueError, match="неизвестное действие"):
        engine.add_condition(_make_condition(name="bad", action="nonexistent_action"))


# ---------------------------------------------------------------------------
# 13. Duplicate interlock name raises ValueError
# ---------------------------------------------------------------------------


async def test_duplicate_name_rejected() -> None:
    broker = DataBroker()
    engine = InterlockEngine(broker=broker, actions={"emergency_off": lambda: None})

    engine.add_condition(_make_condition(name="duplicate"))
    with pytest.raises(ValueError, match="уже зарегистрирована"):
        engine.add_condition(_make_condition(name="duplicate"))


# ---------------------------------------------------------------------------
# 14. get_state returns dict of all interlock states
# ---------------------------------------------------------------------------


async def test_get_state() -> None:
    broker = DataBroker()
    engine = InterlockEngine(
        broker=broker, actions={"emergency_off": lambda: None, "stop_source": lambda: None}
    )
    engine.add_condition(_make_condition(name="lock_a", action="emergency_off"))
    engine.add_condition(_make_condition(name="lock_b", action="stop_source"))

    states = engine.get_state()
    assert set(states.keys()) == {"lock_a", "lock_b"}
    assert states["lock_a"] == InterlockState.ARMED
    assert states["lock_b"] == InterlockState.ARMED


# ---------------------------------------------------------------------------
# 15. Multiple interlocks — only matching ones trip
# ---------------------------------------------------------------------------


async def test_detector_warmup_pattern_matches_full_channel() -> None:
    """The Cyrillic '\u042212 .*' interlock pattern (from interlocks.yaml) is driven
    through the REAL InterlockEngine, not a standalone `re` call: an over-threshold
    reading on the full Cyrillic channel name trips and fires the action, while a
    Latin 'T12 ...' channel does not match the Cyrillic pattern and must not trip."""
    full_name = "\u042212 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2"

    broker, engine, called = await _make_engine()
    engine.add_condition(
        _make_condition(
            name="detector_warmup",
            channel_pattern="\u042212 .*",
            threshold=300.0,
            comparison=">",
        )
    )

    # Latin 'T12 ...' must NOT match the Cyrillic pattern \u2192 no trip, no action.
    await broker.publish(Reading.now("T12 Something", 350.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)
    assert engine.get_state()["detector_warmup"] == InterlockState.ARMED
    assert called == []

    # The full Cyrillic channel name matches \u2192 trips and fires the action exactly once.
    await broker.publish(Reading.now(full_name, 350.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)
    assert engine.get_state()["detector_warmup"] == InterlockState.TRIPPED
    assert len(called) == 1

    await engine.stop()


async def test_multiple_interlocks() -> None:
    called_a: list[bool] = []
    called_b: list[bool] = []

    async def action_a() -> None:
        called_a.append(True)

    async def action_b() -> None:
        called_b.append(True)

    broker = DataBroker()
    engine = InterlockEngine(broker=broker, actions={"action_a": action_a, "action_b": action_b})

    # lock_a monitors T-channels and trips above 300 K
    engine.add_condition(
        InterlockCondition(
            name="lock_a",
            description="High T",
            channel_pattern=r"T\d+",
            threshold=300.0,
            comparison=">",
            action="action_a",
        )
    )
    # lock_b monitors PRESSURE channels and trips below 1e-5
    engine.add_condition(
        InterlockCondition(
            name="lock_b",
            description="Low pressure",
            channel_pattern=r"PRESSURE_\d+",
            threshold=1e-5,
            comparison="<",
            action="action_b",
        )
    )

    await engine.start()

    # Publish a temperature reading that exceeds lock_a threshold
    await broker.publish(Reading.now("T3", 400.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)

    states = engine.get_state()
    assert states["lock_a"] == InterlockState.TRIPPED
    assert states["lock_b"] == InterlockState.ARMED  # unaffected
    assert len(called_a) == 1
    assert len(called_b) == 0

    # Publish a pressure reading that falls below lock_b threshold
    engine.acknowledge("lock_a")
    await broker.publish(Reading.now("PRESSURE_1", 1e-7, "Pa"))
    await asyncio.sleep(0.05)

    states = engine.get_state()
    assert states["lock_b"] == InterlockState.TRIPPED
    assert len(called_b) == 1

    await engine.stop()


# ---------------------------------------------------------------------------
# Phase 2d C-1.1: fail-closed interlock loading
# ---------------------------------------------------------------------------


def test_interlock_missing_file_raises(tmp_path):
    """C-1.1: missing interlocks.yaml must raise InterlockConfigError."""
    from cryodaq.core.interlock import InterlockEngine

    engine = InterlockEngine(broker=None, actions={"emergency_off": lambda: None})
    with pytest.raises(InterlockConfigError, match="not found"):
        engine.load_config(tmp_path / "nonexistent.yaml")


def test_interlock_malformed_yaml_raises(tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("not: valid: [yaml")
    from cryodaq.core.interlock import InterlockEngine

    engine = InterlockEngine(broker=None, actions={"emergency_off": lambda: None})
    with pytest.raises(InterlockConfigError, match="YAML parse error"):
        engine.load_config(cfg)


def test_interlock_valid_config_loads(tmp_path):
    cfg = tmp_path / "ok.yaml"
    cfg.write_text(
        yaml.dump(
            {
                "interlocks": [
                    {
                        "name": "test_lock",
                        "description": "test",
                        "channel_pattern": "Т1 .*",
                        "threshold": 350.0,
                        "comparison": ">",
                        "action": "emergency_off",
                        "cooldown_s": 10.0,
                    }
                ],
            }
        )
    )
    from cryodaq.core.interlock import InterlockEngine

    engine = InterlockEngine(
        broker=None,
        actions={"emergency_off": lambda: None},
    )
    engine.load_config(cfg)
    assert len(engine.get_state()) == 1
