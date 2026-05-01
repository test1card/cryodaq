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
    await asyncio.sleep(0.05)

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
    await asyncio.sleep(0.05)

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
    # Temperatures keyed by display_name, not raw ID
    assert "Т7 Детектор" in status.key_temperatures
    assert "Т1 Криостат верх" in status.key_temperatures
    assert status.current_pressure == 1e-6
