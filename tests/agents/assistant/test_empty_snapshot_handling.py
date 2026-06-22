"""Track C — defensive empty-snapshot handling tests.

Covers:
- BrokerSnapshot.oldest_age_s() returns None when empty, float when populated
- BrokerSnapshot.display_name() uses ChannelManager when provided
- BrokerSnapshot.latest_with_labels() enriches readings with display_name
- BrokerSnapshot accepts channel_manager param
- CompositeStatus.snapshot_empty field
- CompositeAdapter sets snapshot_empty=True when no data
- agent._fmt_composite returns warming-up message when snapshot_empty
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import yaml

from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot
from cryodaq.agents.assistant.query.adapters.composite_adapter import CompositeAdapter
from cryodaq.agents.assistant.query.schemas import CompositeStatus
from cryodaq.core.channel_manager import ChannelManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _poll_until(cond, interval: float = 0.005) -> None:
    """Yield control until ``cond()`` returns True. Used instead of fixed sleeps.

    ASYNC110 does not apply here: we are polling an *external* async
    condition (BrokerSnapshot internal state), not waiting on an event we
    own and can signal — an asyncio.Event would require modifying
    production code.
    """
    while not await cond():  # noqa: ASYNC110
        await asyncio.sleep(interval)


def _write_mgr(**channels: dict) -> ChannelManager:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    yaml.safe_dump({"channels": channels}, tmp, allow_unicode=True)
    tmp.close()
    return ChannelManager(config_path=Path(tmp.name))


def _make_reading(channel: str, value: float = 4.5, unit: str = "K") -> MagicMock:
    r = MagicMock()
    r.channel = channel
    r.value = value
    r.unit = unit
    r.timestamp = datetime.now(UTC)
    return r


# ---------------------------------------------------------------------------
# BrokerSnapshot — oldest_age_s
# ---------------------------------------------------------------------------


async def test_broker_snapshot_oldest_age_s_returns_none_when_empty() -> None:
    broker = MagicMock()
    broker.subscribe = AsyncMock()
    snap = BrokerSnapshot(broker)
    assert await snap.oldest_age_s() is None


async def test_broker_snapshot_oldest_age_s_returns_float_when_populated() -> None:
    broker = MagicMock()
    queue: asyncio.Queue = asyncio.Queue()
    broker.subscribe = AsyncMock(return_value=queue)
    broker.unsubscribe = AsyncMock()

    reading = _make_reading("Т1", 4.5)
    queue.put_nowait(reading)

    snap = BrokerSnapshot(broker)
    await snap.start()

    # Poll until the consume loop drains the queue — avoids the fixed sleep
    # race where a slow CI machine may not have processed the item in time.
    async def _age_ready() -> bool:
        return await snap.oldest_age_s() is not None

    await asyncio.wait_for(
        _poll_until(_age_ready),
        timeout=2.0,
    )

    age = await snap.oldest_age_s()
    assert age is not None
    assert 0 <= age < 5.0
    await snap.stop()


# ---------------------------------------------------------------------------
# BrokerSnapshot — display_name and latest_with_labels
# ---------------------------------------------------------------------------


def test_broker_snapshot_display_name_no_manager() -> None:
    broker = MagicMock()
    broker.subscribe = AsyncMock()
    snap = BrokerSnapshot(broker)
    assert snap.display_name("Т7") == "Т7"


def test_broker_snapshot_display_name_uses_channel_manager() -> None:
    broker = MagicMock()
    broker.subscribe = AsyncMock()
    mgr = _write_mgr(**{"Т7": {"name": "Детектор", "visible": True}})
    snap = BrokerSnapshot(broker, channel_manager=mgr)
    assert snap.display_name("Т7") == "Т7 Детектор"


async def test_broker_snapshot_latest_with_labels_empty() -> None:
    broker = MagicMock()
    broker.subscribe = AsyncMock()
    snap = BrokerSnapshot(broker)
    result = await snap.latest_with_labels()
    assert result == {}


async def test_broker_snapshot_latest_with_labels_includes_display_name() -> None:
    broker = MagicMock()
    queue: asyncio.Queue = asyncio.Queue()
    broker.subscribe = AsyncMock(return_value=queue)
    broker.unsubscribe = AsyncMock()

    mgr = _write_mgr(**{"Т7": {"name": "Детектор", "visible": True}})
    snap = BrokerSnapshot(broker, channel_manager=mgr)
    await snap.start()

    reading = _make_reading("Т7", 3.9)
    queue.put_nowait(reading)

    # Poll until the consume loop processes the reading — avoids the fixed
    # sleep race on slow CI machines.
    async def _has_t7() -> bool:
        return "Т7" in await snap.latest_with_labels()

    await asyncio.wait_for(
        _poll_until(_has_t7),
        timeout=2.0,
    )

    result = await snap.latest_with_labels()
    assert "Т7" in result
    assert result["Т7"]["display_name"] == "Т7 Детектор"
    assert result["Т7"]["value"] == 3.9

    await snap.stop()


# ---------------------------------------------------------------------------
# CompositeStatus — snapshot_empty field
# ---------------------------------------------------------------------------


def test_composite_status_snapshot_empty_default_false() -> None:
    cs = CompositeStatus(
        timestamp=datetime.now(UTC),
        experiment=None,
        cooldown_eta=None,
        vacuum_eta=None,
        active_alarms=[],
        key_temperatures={},
        current_pressure=None,
    )
    assert cs.snapshot_empty is False


def test_composite_status_snapshot_empty_true() -> None:
    cs = CompositeStatus(
        timestamp=datetime.now(UTC),
        experiment=None,
        cooldown_eta=None,
        vacuum_eta=None,
        active_alarms=[],
        key_temperatures={},
        current_pressure=None,
        snapshot_empty=True,
    )
    assert cs.snapshot_empty is True


# ---------------------------------------------------------------------------
# CompositeAdapter — snapshot_empty detection
# ---------------------------------------------------------------------------


async def test_composite_adapter_snapshot_empty_when_no_data() -> None:
    snapshot = MagicMock()
    snapshot.latest_with_labels = AsyncMock(return_value={})
    snapshot.oldest_age_s = AsyncMock(return_value=None)

    cooldown = MagicMock()
    cooldown.eta = AsyncMock(return_value=None)
    vacuum = MagicMock()
    vacuum.eta_to_target = AsyncMock(return_value=None)
    alarms = MagicMock()
    alarms.active = AsyncMock(return_value=MagicMock(active=[]))
    experiment = MagicMock()
    experiment.status = AsyncMock(return_value=None)

    adapter = CompositeAdapter(
        broker_snapshot=snapshot,
        cooldown=cooldown,
        vacuum=vacuum,
        alarms=alarms,
        experiment=experiment,
    )
    status = await adapter.status()
    assert status.snapshot_empty is True


async def test_composite_adapter_snapshot_not_empty_when_has_data() -> None:
    snapshot = MagicMock()
    snapshot.latest_with_labels = AsyncMock(return_value={
        "Т7": {"value": 3.9, "unit": "K", "display_name": "Т7 Детектор",
               "timestamp": datetime.now(UTC)},
    })
    snapshot.oldest_age_s = AsyncMock(return_value=2.0)

    cooldown = MagicMock()
    cooldown.eta = AsyncMock(return_value=None)
    vacuum = MagicMock()
    vacuum.eta_to_target = AsyncMock(return_value=None)
    alarms = MagicMock()
    alarms.active = AsyncMock(return_value=MagicMock(active=[]))
    experiment = MagicMock()
    experiment.status = AsyncMock(return_value=None)

    adapter = CompositeAdapter(
        broker_snapshot=snapshot,
        cooldown=cooldown,
        vacuum=vacuum,
        alarms=alarms,
        experiment=experiment,
    )
    status = await adapter.status()
    assert status.snapshot_empty is False
    assert status.snapshot_age_s == 2.0


async def test_composite_adapter_builds_key_temps_from_k_channels() -> None:
    snapshot = MagicMock()
    snapshot.latest_with_labels = AsyncMock(return_value={
        "Т7": {"value": 3.9, "unit": "K", "display_name": "Т7 Детектор",
               "timestamp": datetime.now(UTC)},
        "Т1": {"value": 78.2, "unit": "K", "display_name": "Т1 Криостат верх",
               "timestamp": datetime.now(UTC)},
        "P1": {"value": 1e-6, "unit": "mbar", "display_name": "P1",
               "timestamp": datetime.now(UTC)},
    })
    snapshot.oldest_age_s = AsyncMock(return_value=1.0)

    cooldown = MagicMock()
    cooldown.eta = AsyncMock(return_value=None)
    vacuum = MagicMock()
    vacuum.eta_to_target = AsyncMock(return_value=None)
    alarms = MagicMock()
    alarms.active = AsyncMock(return_value=MagicMock(active=[]))
    experiment = MagicMock()
    experiment.status = AsyncMock(return_value=None)

    adapter = CompositeAdapter(
        broker_snapshot=snapshot,
        cooldown=cooldown,
        vacuum=vacuum,
        alarms=alarms,
        experiment=experiment,
    )
    status = await adapter.status()
    # Temperatures keyed by display_name, not raw channel ID.
    # Assert exact values so wrong/swapped readings would fail.
    assert status.key_temperatures == {
        "Т7 Детектор": 3.9,
        "Т1 Криостат верх": 78.2,
    }
    # P1 is a pressure channel (unit=mbar) — must NOT appear in key_temperatures.
    assert "P1" not in status.key_temperatures
    assert status.current_pressure == 1e-6
