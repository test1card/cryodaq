from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.agents.assistant.periodic_projection import AlarmProjection
from cryodaq.core.event_bus import EngineEvent
from cryodaq.core.zmq_bridge import _pack_event, _unpack_event
from cryodaq.engine_wiring.runtime_tasks import assistant_event_relay_loop


def test_alarm_cleared_is_relayed_for_periodic_projection() -> None:
    engine_path = Path(__file__).parents[2] / "src" / "cryodaq" / "engine.py"
    tree = ast.parse(engine_path.read_text(encoding="utf-8"))
    relay_types: set[str] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_ASSISTANT_RELAY_EVENT_TYPES" for target in node.targets
        ):
            continue
        assert isinstance(node.value, ast.Call)
        assert len(node.value.args) == 1 and isinstance(node.value.args[0], ast.Set)
        relay_types = {
            element.value
            for element in node.value.args[0].elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        }
        break
    assert relay_types is not None
    assert {"alarm_fired", "alarm_cleared"} <= relay_types


@pytest.mark.asyncio
async def test_fired_and_cleared_cross_real_relay_codec_and_projection() -> None:
    relayed: list[dict[str, object]] = []

    class PackingPublisher:
        async def publish_event(
            self,
            *,
            event_type: str,
            timestamp: datetime,
            payload: dict[str, object],
            experiment_id: str | None,
        ) -> None:
            relayed.append(_unpack_event(_pack_event(event_type, timestamp, payload, experiment_id)))

    now = datetime.now(UTC)
    queue: asyncio.Queue[EngineEvent] = asyncio.Queue()
    task = asyncio.create_task(
        assistant_event_relay_loop(
            queue,
            PackingPublisher(),
            frozenset({"alarm_fired", "alarm_cleared"}),
        )
    )
    await queue.put(
        EngineEvent(
            event_type="alarm_fired",
            timestamp=now,
            payload={
                "alarm_id": "a",
                "level": "WARNING",
                "message": "warm",
                "channels": ["T"],
                "values": {"T": 5.0},
            },
        )
    )
    await queue.put(
        EngineEvent(
            event_type="alarm_cleared",
            timestamp=now,
            payload={"alarm_id": "a"},
        )
    )
    for _ in range(20):
        if len(relayed) == 2:
            break
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert [event["event_type"] for event in relayed] == [
        "alarm_fired",
        "alarm_cleared",
    ]
    projection = AlarmProjection()
    receive_cut = projection.capture_receive_cut()
    projection.buffer_event(relayed[0])
    projection.install_snapshot(
        {"ok": True, "active": {}},
        captured_at=now.timestamp() - 1,
        receive_cut=receive_cut,
    )
    assert [alarm.alarm_id for alarm in projection.freeze(now=now.timestamp())[0]] == ["a"]
    projection.buffer_event(relayed[1])
    assert projection.freeze(now=now.timestamp()) == ((), True)
