"""Tests for HF v0.47.4 — Option B: BrokerSnapshot channel ID normalization.

Covers:
- _normalize_channel_id static method (various channel ID forms)
- _consume_loop stores readings under short canonical ID
- latest(short_id) returns reading originally received as long form
- latest_with_labels display_name resolution after normalization
- ExperimentAdapter._resolve_display_name (title → name → date → uuid prefix)
- agent._format_dispatch GREETING → FORMAT_GREETING_USER (not FORMAT_UNKNOWN)
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from cryodaq.agents.assistant.query.adapters.broker_snapshot import BrokerSnapshot
from cryodaq.core.channel_manager import ChannelManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reading(channel: str, value: float = 3.89, unit: str = "K") -> MagicMock:
    r = MagicMock()
    r.channel = channel
    r.value = value
    r.unit = unit
    r.timestamp = datetime.now(UTC)
    r.instrument_id = "lakeshore_1"
    return r


def _make_mgr(**channels: dict) -> ChannelManager:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    yaml.safe_dump({"channels": channels}, tmp, allow_unicode=True)
    tmp.close()
    return ChannelManager(config_path=Path(tmp.name))


# ---------------------------------------------------------------------------
# _normalize_channel_id
# ---------------------------------------------------------------------------


def test_normalize_short_id_passthrough() -> None:
    assert BrokerSnapshot._normalize_channel_id("Т7") == "Т7"


def test_normalize_long_id_extracts_short() -> None:
    assert BrokerSnapshot._normalize_channel_id("Т7 Детектор") == "Т7"


def test_normalize_long_id_t12() -> None:
    assert BrokerSnapshot._normalize_channel_id("Т12 Теплообменник 2") == "Т12"


def test_normalize_pressure_channel_unchanged() -> None:
    assert BrokerSnapshot._normalize_channel_id("VSP63D_1/pressure") == "VSP63D_1/pressure"


def test_normalize_keithley_channel_unchanged() -> None:
    ch = "Keithley_1/smua/voltage"
    assert BrokerSnapshot._normalize_channel_id(ch) == ch


def test_normalize_ch_fallback_unchanged() -> None:
    assert BrokerSnapshot._normalize_channel_id("CH3") == "CH3"


def test_normalize_empty_string_unchanged() -> None:
    assert BrokerSnapshot._normalize_channel_id("") == ""


# ---------------------------------------------------------------------------
# _consume_loop stores under short key
# ---------------------------------------------------------------------------


async def test_consume_loop_stores_short_id() -> None:
    broker = MagicMock()
    queue: asyncio.Queue = asyncio.Queue()
    broker.subscribe = AsyncMock(return_value=queue)
    broker.unsubscribe = AsyncMock()

    snap = BrokerSnapshot(broker)
    await snap.start()

    reading = _make_reading("Т7 Детектор")
    await queue.put(reading)
    await asyncio.sleep(0.05)

    async with snap._lock:
        keys = list(snap._latest.keys())

    await snap.stop()

    assert "Т7" in keys, f"Expected 'Т7' in cache, got {keys}"
    assert "Т7 Детектор" not in keys, "Long-form key must not be stored"


async def test_latest_short_id_returns_reading() -> None:
    """snapshot.latest('Т7') returns reading originally received as 'Т7 Детектор'."""
    broker = MagicMock()
    queue: asyncio.Queue = asyncio.Queue()
    broker.subscribe = AsyncMock(return_value=queue)
    broker.unsubscribe = AsyncMock()

    snap = BrokerSnapshot(broker)
    await snap.start()

    reading = _make_reading("Т7 Детектор", value=3.89)
    await queue.put(reading)
    await asyncio.sleep(0.05)

    result = await snap.latest("Т7")
    await snap.stop()

    assert result is not None, "snapshot.latest('Т7') must return reading"
    assert result.value == pytest.approx(3.89)


async def test_latest_long_form_returns_none_after_normalization() -> None:
    """After normalization, the long key is no longer stored."""
    broker = MagicMock()
    queue: asyncio.Queue = asyncio.Queue()
    broker.subscribe = AsyncMock(return_value=queue)
    broker.unsubscribe = AsyncMock()

    snap = BrokerSnapshot(broker)
    await snap.start()

    await queue.put(_make_reading("Т7 Детектор"))
    await asyncio.sleep(0.05)

    result = await snap.latest("Т7 Детектор")
    await snap.stop()

    assert result is None, "Long-form key must not be queryable after normalization"


async def test_latest_with_labels_display_name_resolved_via_channel_manager() -> None:
    """latest_with_labels() uses ChannelManager display name, enabling late-binding renames.

    Driver emits 'Т7 Детектор'; ChannelManager has renamed it to 'Испытательный'.
    After normalization, display_name should reflect the renamed value, not
    the stale driver-emitted label.
    """
    broker = MagicMock()
    queue: asyncio.Queue = asyncio.Queue()
    broker.subscribe = AsyncMock(return_value=queue)
    broker.unsubscribe = AsyncMock()

    mgr = _make_mgr(**{"Т7": {"name": "Испытательный", "visible": True}})
    snap = BrokerSnapshot(broker, channel_manager=mgr)
    await snap.start()

    # Driver still emits long-form "Т7 Детектор" (instruments.yaml frozen)
    await queue.put(_make_reading("Т7 Детектор"))
    await asyncio.sleep(0.05)

    labeled = await snap.latest_with_labels()
    await snap.stop()

    assert "Т7" in labeled, f"Key 'Т7' missing from labeled data: {list(labeled)}"
    # display_name must come from ChannelManager (renamed), not raw driver label
    assert "Испытательный" in labeled["Т7"]["display_name"]
    assert "Детектор" not in labeled["Т7"]["display_name"]


async def test_pressure_channel_stored_unchanged() -> None:
    """Non-Т channels (no space) stored under original key."""
    broker = MagicMock()
    queue: asyncio.Queue = asyncio.Queue()
    broker.subscribe = AsyncMock(return_value=queue)
    broker.unsubscribe = AsyncMock()

    snap = BrokerSnapshot(broker)
    await snap.start()

    await queue.put(_make_reading("VSP63D_1/pressure", value=1.5e-6, unit="mbar"))
    await asyncio.sleep(0.05)

    result = await snap.latest("VSP63D_1/pressure")
    await snap.stop()

    assert result is not None


# ---------------------------------------------------------------------------
# ExperimentAdapter._resolve_display_name
# ---------------------------------------------------------------------------


def test_experiment_display_uses_title_when_set() -> None:
    from cryodaq.agents.assistant.query.adapters.experiment_adapter import ExperimentAdapter

    active = MagicMock()
    active.title = "Измерение образца #42"
    active.name = "exp-2026-05-01"
    active.start_time = None
    label = ExperimentAdapter._resolve_display_name(active, "cc35331d-8c89-0000-0000-000000000000")
    assert label == "Измерение образца #42"


def test_experiment_display_uses_name_when_title_empty() -> None:
    from cryodaq.agents.assistant.query.adapters.experiment_adapter import ExperimentAdapter

    active = MagicMock()
    active.title = ""
    active.name = "exp-2026-05-01"
    active.start_time = None
    label = ExperimentAdapter._resolve_display_name(active, "cc35331d8c89")
    assert label == "exp-2026-05-01"


def test_experiment_display_uses_date_when_no_title_or_name() -> None:
    from cryodaq.agents.assistant.query.adapters.experiment_adapter import ExperimentAdapter

    active = MagicMock()
    active.title = ""
    active.name = ""
    active.start_time = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    label = ExperimentAdapter._resolve_display_name(active, "cc35331d8c89")
    assert label == "эксперимент 2026-05-01"


def test_experiment_display_never_returns_full_uuid() -> None:
    from cryodaq.agents.assistant.query.adapters.experiment_adapter import ExperimentAdapter

    full_uuid = "cc35331d-8c89-4a12-b234-000000000000"
    active = MagicMock()
    active.title = ""
    active.name = ""
    active.start_time = None
    label = ExperimentAdapter._resolve_display_name(active, full_uuid)
    assert full_uuid not in label
    assert len(label) < len(full_uuid) + 15


def test_experiment_display_short_uuid_prefix_fallback() -> None:
    from cryodaq.agents.assistant.query.adapters.experiment_adapter import ExperimentAdapter

    active = MagicMock()
    active.title = None
    active.name = None
    active.start_time = None
    label = ExperimentAdapter._resolve_display_name(active, "cc35331d8c89abcd")
    assert "cc35331d" in label


# ---------------------------------------------------------------------------
# GREETING dispatch → FORMAT_GREETING_USER
# ---------------------------------------------------------------------------


def test_greeting_dispatch_does_not_use_unknown_prompt() -> None:
    """GREETING category must route to FORMAT_GREETING_USER, not FORMAT_UNKNOWN_USER."""
    from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
    from cryodaq.agents.assistant.query.schemas import QueryCategory

    agent = object.__new__(AssistantQueryAgent)
    agent._config = MagicMock()
    agent._config.brand_name = "Гемма"

    result = agent._format_dispatch("Привет!", QueryCategory.GREETING, {})
    has_greeting_content = (
        "Ничего лишнего" in result
        or "приветствие" in result.lower()
        or "поздоровайся" in result.lower()
    )
    assert has_greeting_content, f"Unexpected greeting prompt: {result[:200]}"


def test_greeting_dispatch_result_has_no_unknown_preamble() -> None:
    """GREETING dispatch must not contain 'непонятен' from FORMAT_UNKNOWN_USER."""
    from cryodaq.agents.assistant.query.agent import AssistantQueryAgent
    from cryodaq.agents.assistant.query.schemas import QueryCategory

    agent = object.__new__(AssistantQueryAgent)
    agent._config = MagicMock()
    agent._config.brand_name = "Гемма"

    result = agent._format_dispatch("Привет!", QueryCategory.GREETING, {})
    assert "непонятен" not in result
    assert "выходит за рамки" not in result
