"""Tests for InterlockEngine — safety interlock logic for cryogenic equipment."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from cryodaq.core.broker import DataBroker
from cryodaq.core.interlock import InterlockCondition, InterlockEngine, InterlockState
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
# 3. Cooldown prevents re-trip within cooldown window
# ---------------------------------------------------------------------------


async def test_cooldown_prevents_retrip() -> None:
    broker, engine, called = await _make_engine()
    # Use a very long cooldown so the second publish definitely falls within it
    engine.add_condition(
        _make_condition(threshold=300.0, comparison=">", cooldown_s=60.0)
    )

    # First trip
    await broker.publish(Reading.now("T1", 350.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)
    assert engine.get_state()["high_temp"] == InterlockState.TRIPPED

    # Acknowledge to return to ARMED so the cooldown logic is exercised
    engine.acknowledge("high_temp")
    assert engine.get_state()["high_temp"] == InterlockState.ARMED

    # Publish again — still within cooldown, should NOT trip
    await broker.publish(Reading.now("T1", 400.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)

    # Still ARMED because cooldown is active
    assert engine.get_state()["high_temp"] == InterlockState.ARMED
    assert len(called) == 1  # action called only once

    await engine.stop()


# ---------------------------------------------------------------------------
# 4. Action callable is awaited (async)
# ---------------------------------------------------------------------------


async def test_action_called_async() -> None:
    awaited: list[bool] = []

    async def async_action() -> None:
        await asyncio.sleep(0)  # yields control — proves it is truly awaited
        awaited.append(True)

    broker = DataBroker()
    engine = InterlockEngine(broker=broker, actions={"emergency_off": async_action})
    engine.add_condition(_make_condition(threshold=300.0, comparison=">"))
    await engine.start()

    await broker.publish(Reading.now("T1", 999.0, "K", instrument_id="test"))
    await asyncio.sleep(0.05)

    assert len(awaited) == 1, "Async action was not awaited"

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
    engine.add_condition(
        _make_condition(threshold=2.0, comparison="<", channel_pattern=r"T\d+")
    )

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
    engine.add_condition(
        _make_condition(threshold=300.0, comparison=">", cooldown_s=0.0)
    )
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


async def test_load_config_yaml(tmp_path: Path) -> None:
    config_data = {
        "interlocks": [
            {
                "name": "overheat",
                "description": "Overheating protection",
                "channel_pattern": r"T\d+",
                "threshold": 400.0,
                "comparison": ">",
                "action": "emergency_off",
                "cooldown_s": 5.0,
            }
        ]
    }
    config_file = tmp_path / "interlocks.yaml"
    config_file.write_text(yaml.dump(config_data), encoding="utf-8")

    broker = DataBroker()
    engine = InterlockEngine(broker=broker, actions={"emergency_off": lambda: None})
    engine.load_config(config_file)

    states = engine.get_state()
    assert "overheat" in states
    assert states["overheat"] == InterlockState.ARMED


# ---------------------------------------------------------------------------
# 12. add_condition with unknown action raises ValueError
# ---------------------------------------------------------------------------


async def test_missing_action_rejected() -> None:
    broker = DataBroker()
    engine = InterlockEngine(broker=broker, actions={"emergency_off": lambda: None})

    with pytest.raises(ValueError, match="неизвестное действие"):
        engine.add_condition(
            _make_condition(name="bad", action="nonexistent_action")
        )


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
    """Regex pattern '\u042212 .*' from interlocks.yaml matches full channel name."""
    import re
    pattern = "\u042212 .*"
    full_name = "\u042212 \u0422\u0435\u043f\u043b\u043e\u043e\u0431\u043c\u0435\u043d\u043d\u0438\u043a 2"
    assert re.fullmatch(pattern, full_name), (
        f"Pattern {pattern!r} should match {full_name!r}"
    )
    # Also verify it does NOT match Latin T12
    assert not re.fullmatch(pattern, "T12 Something"), (
        "Cyrillic pattern should not match Latin T"
    )


async def test_multiple_interlocks() -> None:
    called_a: list[bool] = []
    called_b: list[bool] = []

    async def action_a() -> None:
        called_a.append(True)

    async def action_b() -> None:
        called_b.append(True)

    broker = DataBroker()
    engine = InterlockEngine(
        broker=broker, actions={"action_a": action_a, "action_b": action_b}
    )

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
