"""Tests for Tracks G (Latin/Cyrillic confusables) and H (anti-hallucination).

Track G: ChannelManager.find_by_name() Latin→Cyrillic fallback,
         classifier prompt has Cyrillic Т (not Latin T) in channel examples.
Track H: ExperimentAdapter populates experiment_started_human,
         anti-hallucination instruction in FORMAT_RESPONSE_SYSTEM.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import yaml

from cryodaq.agents.assistant.query import prompts as p
from cryodaq.core.channel_manager import ChannelManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mgr(**channels: dict) -> ChannelManager:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    yaml.safe_dump({"channels": channels}, tmp, allow_unicode=True)
    tmp.close()
    return ChannelManager(config_path=Path(tmp.name))


# ---------------------------------------------------------------------------
# Track G.1 — INTENT_CLASSIFIER_SYSTEM uses Cyrillic Т for channel examples
# ---------------------------------------------------------------------------


def test_classifier_prompt_no_latin_t_digit_pattern() -> None:
    """INTENT_CLASSIFIER_SYSTEM must not contain Latin 'T<digit>' channel refs."""
    # Strip format placeholders first
    stripped = re.sub(r"\{[^}]+\}", "", p.INTENT_CLASSIFIER_SYSTEM)
    # Find Latin T followed by digit — these should be Cyrillic in channel context
    latin_t_channel = re.findall(r"\bT\d+\b", stripped)
    assert not latin_t_channel, (
        f"Latin T<digit> in INTENT_CLASSIFIER_SYSTEM: {latin_t_channel}"
    )


# ---------------------------------------------------------------------------
# Track G.2 — ChannelManager.find_by_name() Latin→Cyrillic fallback
# ---------------------------------------------------------------------------


def test_normalize_channel_id_latin_t_to_cyrillic() -> None:
    """normalize_channel_id converts Latin T→Cyrillic Т (keyboard layout fix)."""
    mgr = _make_mgr(**{"Т12": {"name": "Азотная плита", "visible": True}})
    assert mgr.normalize_channel_id("T12") == "Т12"
    assert mgr.normalize_channel_id("T7") == "Т7"
    assert mgr.normalize_channel_id("Т7") == "Т7"  # already Cyrillic — no change


def test_find_by_name_resolves_cyrillic_name_directly() -> None:
    """Direct name match works (find_by_name is name-only, not ID lookup)."""
    mgr = _make_mgr(**{"Т7": {"name": "Детектор", "visible": True}})
    assert mgr.find_by_name("Детектор") == "Т7"


def test_find_by_name_latin_id_returns_none() -> None:
    """find_by_name('T7') returns None — ID lookup is router's job via normalize_channel_id."""
    mgr = _make_mgr(**{"Т7": {"name": "Детектор", "visible": True}})
    assert mgr.find_by_name("T7") is None


def test_find_by_name_mixed_latin_cyrillic_returns_none_gracefully() -> None:
    """Non-matching Latin string returns None without crash."""
    mgr = _make_mgr(**{"Т7": {"name": "Детектор", "visible": True}})
    assert mgr.find_by_name("XYZ999") is None


# ---------------------------------------------------------------------------
# Track G.2 — QueryRouter resolves Latin T target_channels
# ---------------------------------------------------------------------------


def test_router_resolves_latin_t_via_channelmanager() -> None:
    """target_channels=['T12'] (Latin T) resolves to 'Т12' (Cyrillic Т)."""
    from unittest.mock import AsyncMock, MagicMock

    from cryodaq.agents.assistant.query.router import QueryRouter
    from cryodaq.agents.assistant.query.schemas import QueryAdapters, QueryCategory, QueryIntent

    mgr = _make_mgr(**{"Т12": {"name": "Азотная плита", "visible": True}})

    snap = MagicMock()
    snap.latest = AsyncMock(return_value=None)
    snap.latest_age_s = AsyncMock(return_value=None)
    adapters = QueryAdapters(
        broker_snapshot=snap,
        cooldown=MagicMock(),
        vacuum=MagicMock(),
        sqlite=MagicMock(),
        alarms=MagicMock(),
        experiment=MagicMock(),
        composite=MagicMock(),
    )
    router = QueryRouter(adapters, channel_manager=mgr)
    intent = QueryIntent(category=QueryCategory.CURRENT_VALUE, target_channels=["T12"])
    resolved = router._resolve_target_channels(intent)
    assert resolved == ["Т12"], f"Expected ['Т12'], got {resolved!r}"


# ---------------------------------------------------------------------------
# Track H — ExperimentAdapter populates experiment_started_human
# ---------------------------------------------------------------------------


async def test_experiment_adapter_populates_started_human() -> None:
    from unittest.mock import MagicMock

    from cryodaq.agents.assistant.query.adapters.experiment_adapter import ExperimentAdapter

    em = MagicMock()
    em.active_experiment_id = "exp-001"
    active = MagicMock()
    active.started_at = 1746100000.0  # some real Unix timestamp
    active.target_temp = 4.0
    active.sample_id = None
    em.active_experiment = active

    adapter = ExperimentAdapter(em)
    status = await adapter.status()
    assert status is not None
    assert status.experiment_started_human is not None
    # Should contain UTC time format
    assert "UTC" in status.experiment_started_human


async def test_experiment_adapter_started_human_none_when_no_start_time() -> None:
    from unittest.mock import MagicMock

    from cryodaq.agents.assistant.query.adapters.experiment_adapter import ExperimentAdapter

    em = MagicMock()
    em.active_experiment_id = "exp-001"
    active = MagicMock()
    active.started_at = None  # no start time
    em.active_experiment = active

    adapter = ExperimentAdapter(em)
    status = await adapter.status()
    assert status is not None
    assert status.experiment_started_human is None


# ---------------------------------------------------------------------------
# Track H — FORMAT_RESPONSE_SYSTEM has anti-hallucination instruction
# ---------------------------------------------------------------------------


def test_response_system_has_anti_hallucination() -> None:
    """FORMAT_RESPONSE_SYSTEM must contain explicit anti-hallucination guidance."""
    assert "НЕ ПРИДУМЫВАЙ" in p.FORMAT_RESPONSE_SYSTEM
    frs = p.FORMAT_RESPONSE_SYSTEM
    assert "null" in frs or "None" in frs or "пусто" in frs


def test_response_system_no_timestamp_hallucination_instruction() -> None:
    """FORMAT_RESPONSE_SYSTEM must warn against inventing timestamps."""
    frs = p.FORMAT_RESPONSE_SYSTEM.lower()
    assert "00:00" in frs or "timestamp" in frs or "время" in frs
