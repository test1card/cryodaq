"""Tests for HF v0.47.3 — late-binding display name resolution.

Covers:
- ChannelManager.find_by_name()
- _build_channel_hint() in intent_classifier
- IntentClassifier late-binding (rename mid-session picked up)
- QueryRouter._resolve_target_channels() fallback resolution
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml

from cryodaq.agents.assistant.query.intent_classifier import (
    IntentClassifier,
    _build_channel_hint,
)
from cryodaq.agents.assistant.query.router import QueryRouter
from cryodaq.agents.assistant.query.schemas import (
    QueryAdapters,
    QueryCategory,
    QueryIntent,
)
from cryodaq.core.channel_manager import ChannelManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_config(channels_dict: dict) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    yaml.safe_dump({"channels": channels_dict}, tmp, allow_unicode=True)
    tmp.close()
    return Path(tmp.name)


def _make_manager(**channel_defs: dict) -> ChannelManager:
    """Create a ChannelManager from keyword args mapping ch_id → {name, visible, ...}."""
    cfg = _write_config(channel_defs)
    return ChannelManager(config_path=cfg)


def _ollama_returning(text: str) -> MagicMock:
    result = MagicMock()
    result.text = text
    result.truncated = False
    client = MagicMock()
    client.generate = AsyncMock(return_value=result)
    return client


def _j(category: str, channels: list[str] | None = None) -> str:
    return json.dumps({
        "category": category,
        "target_channels": channels,
        "time_window_minutes": None,
        "quantity": "",
    })


def _make_adapters() -> QueryAdapters:
    snap = MagicMock()
    snap.latest = AsyncMock(return_value=None)
    snap.latest_age_s = AsyncMock(return_value=None)
    snap.latest_all = AsyncMock(return_value={})
    return QueryAdapters(
        broker_snapshot=snap,
        cooldown=MagicMock(),
        vacuum=MagicMock(),
        sqlite=MagicMock(),
        alarms=MagicMock(),
        experiment=MagicMock(),
        composite=MagicMock(),
    )


# ---------------------------------------------------------------------------
# ChannelManager.find_by_name
# ---------------------------------------------------------------------------


def test_find_by_name_exact() -> None:
    mgr = _make_manager(**{"Т7": {"name": "Детектор", "visible": True}})
    assert mgr.find_by_name("Детектор") == "Т7"


def test_find_by_name_case_insensitive() -> None:
    mgr = _make_manager(**{"Т7": {"name": "Детектор", "visible": True}})
    assert mgr.find_by_name("ДЕТЕКТОР") == "Т7"
    assert mgr.find_by_name("детектор") == "Т7"


def test_find_by_name_substring() -> None:
    mgr = _make_manager(**{"Т12": {"name": "Азотная плита", "visible": True}})
    assert mgr.find_by_name("плита") == "Т12"


def test_find_by_name_exact_wins_over_substring() -> None:
    mgr = _make_manager(**{
        "Т11": {"name": "Плита", "visible": True},
        "Т12": {"name": "Азотная плита", "visible": True},
    })
    assert mgr.find_by_name("Плита") == "Т11"


def test_find_by_name_returns_none_no_match() -> None:
    mgr = _make_manager(**{"Т7": {"name": "Детектор", "visible": True}})
    assert mgr.find_by_name("нечто странное") is None


def test_find_by_name_empty_string() -> None:
    mgr = _make_manager(**{"Т7": {"name": "Детектор", "visible": True}})
    assert mgr.find_by_name("") is None


def test_find_by_name_no_name_field() -> None:
    mgr = _make_manager(**{"Т7": {"visible": True}})
    assert mgr.find_by_name("Т7") is None


# ---------------------------------------------------------------------------
# _build_channel_hint
# ---------------------------------------------------------------------------


def test_build_channel_hint_returns_empty_when_no_manager() -> None:
    assert _build_channel_hint(None) == ""


def test_build_channel_hint_includes_visible_channels() -> None:
    mgr = _make_manager(**{
        "Т7": {"name": "Детектор", "visible": True},
        "Т12": {"name": "Азотная плита", "visible": True},
    })
    hint = _build_channel_hint(mgr)
    assert "Т7" in hint
    assert "Детектор" in hint
    assert "Т12" in hint
    assert "Азотная плита" in hint
    assert "Доступные каналы" in hint


def test_build_channel_hint_skips_invisible() -> None:
    mgr = _make_manager(**{
        "Т7": {"name": "Детектор", "visible": True},
        "Т8": {"name": "Скрытый", "visible": False},
    })
    hint = _build_channel_hint(mgr)
    assert "Т7" in hint
    assert "Скрытый" not in hint
    assert "Т8" not in hint


def test_build_channel_hint_empty_when_all_invisible() -> None:
    mgr = _make_manager(**{
        "Т7": {"name": "Детектор", "visible": False},
    })
    assert _build_channel_hint(mgr) == ""


# ---------------------------------------------------------------------------
# IntentClassifier — late-binding prompt rebuild
# ---------------------------------------------------------------------------


async def test_classifier_prompt_includes_channel_hint_when_manager_provided() -> None:
    mgr = _make_manager(**{"Т12": {"name": "Азотная плита", "visible": True}})
    ollama = _ollama_returning(_j("current_value", ["Т12"]))
    clf = IntentClassifier(ollama, channel_manager=mgr)
    await clf.classify("что на азотной плите?")
    call_kwargs = ollama.generate.call_args
    system_arg = call_kwargs.kwargs.get("system") or call_kwargs.args[1] if len(call_kwargs.args) > 1 else call_kwargs.kwargs["system"]
    assert "Азотная плита" in system_arg
    assert "Т12" in system_arg


async def test_classifier_omits_hint_when_no_manager() -> None:
    ollama = _ollama_returning(_j("current_value", ["Т12"]))
    clf = IntentClassifier(ollama, channel_manager=None)
    await clf.classify("что на азотной плите?")
    call_kwargs = ollama.generate.call_args
    system_arg = call_kwargs.kwargs["system"]
    assert "Доступные каналы" not in system_arg


async def test_classifier_picks_up_rename_without_restart() -> None:
    """LATE BINDING: rename Т12 between calls — second call sees new name."""
    mgr = _make_manager(**{"Т12": {"name": "Теплообменник 2", "visible": True}})
    ollama = _ollama_returning(_j("current_value", ["Т12"]))
    clf = IntentClassifier(ollama, channel_manager=mgr)

    # First classify — old name
    await clf.classify("что на теплообменнике 2?")
    first_system = ollama.generate.call_args.kwargs["system"]
    assert "Теплообменник 2" in first_system

    # Rename mid-session (no engine restart)
    mgr.set_name("Т12", "Азотная плита")

    # Second classify — new name must appear without restart
    await clf.classify("что на азотной плите?")
    second_system = ollama.generate.call_args.kwargs["system"]
    assert "Азотная плита" in second_system
    assert "Теплообменник 2" not in second_system


async def test_classifier_concurrent_calls_each_get_consistent_snapshot() -> None:
    """Two concurrent classify() calls each see a consistent ChannelManager snapshot."""
    import asyncio

    mgr = _make_manager(**{
        "Т7": {"name": "Детектор", "visible": True},
        "Т12": {"name": "Азотная плита", "visible": True},
    })
    captured_prompts: list[str] = []

    async def fake_generate(user_prompt, *, model, system, temperature, max_tokens):
        captured_prompts.append(system)
        r = MagicMock()
        r.text = _j("current_value", ["Т7"])
        r.truncated = False
        return r

    client = MagicMock()
    client.generate = fake_generate
    clf = IntentClassifier(client, channel_manager=mgr)

    await asyncio.gather(
        clf.classify("какая T7?"),
        clf.classify("что на азотной плите?"),
    )
    assert len(captured_prompts) == 2
    for prompt in captured_prompts:
        assert "Т7" in prompt
        assert "Т12" in prompt


# ---------------------------------------------------------------------------
# QueryRouter — _resolve_target_channels
# ---------------------------------------------------------------------------


def test_router_resolves_direct_channel_id() -> None:
    mgr = _make_manager(**{"Т7": {"name": "Детектор", "visible": True}})
    router = QueryRouter(_make_adapters(), channel_manager=mgr)
    intent = QueryIntent(category=QueryCategory.CURRENT_VALUE, target_channels=["Т7"])
    assert router._resolve_target_channels(intent) == ["Т7"]


def test_router_resolves_display_name_to_id() -> None:
    mgr = _make_manager(**{"Т12": {"name": "Азотная плита", "visible": True}})
    router = QueryRouter(_make_adapters(), channel_manager=mgr)
    intent = QueryIntent(
        category=QueryCategory.CURRENT_VALUE, target_channels=["Азотная плита"]
    )
    assert router._resolve_target_channels(intent) == ["Т12"]


def test_router_partial_fuzzy_match() -> None:
    mgr = _make_manager(**{"Т12": {"name": "Азотная плита", "visible": True}})
    router = QueryRouter(_make_adapters(), channel_manager=mgr)
    intent = QueryIntent(category=QueryCategory.CURRENT_VALUE, target_channels=["плита"])
    result = router._resolve_target_channels(intent)
    assert result == ["Т12"]


def test_router_picks_up_rename_without_restart() -> None:
    """LATE BINDING: rename mid-session reflected in router resolution."""
    mgr = _make_manager(**{"Т12": {"name": "Теплообменник 2", "visible": True}})
    router = QueryRouter(_make_adapters(), channel_manager=mgr)

    intent_old = QueryIntent(
        category=QueryCategory.CURRENT_VALUE, target_channels=["Теплообменник 2"]
    )
    assert router._resolve_target_channels(intent_old) == ["Т12"]

    mgr.set_name("Т12", "Азотная плита")

    intent_new = QueryIntent(
        category=QueryCategory.CURRENT_VALUE, target_channels=["Азотная плита"]
    )
    assert router._resolve_target_channels(intent_new) == ["Т12"]

    # Old name no longer resolves
    assert router._resolve_target_channels(intent_old) is None


def test_router_drops_unresolvable_logs_warning() -> None:
    mgr = _make_manager(**{"Т7": {"name": "Детектор", "visible": True}})
    router = QueryRouter(_make_adapters(), channel_manager=mgr)
    intent = QueryIntent(
        category=QueryCategory.CURRENT_VALUE, target_channels=["нечто странное"]
    )
    import logging
    with patch.object(logging.getLogger("cryodaq.agents.assistant.query.router"), "warning") as mock_warn:
        result = router._resolve_target_channels(intent)
    assert result is None
    mock_warn.assert_called_once()


def test_router_handles_empty_target_channels() -> None:
    mgr = _make_manager(**{"Т7": {"name": "Детектор", "visible": True}})
    router = QueryRouter(_make_adapters(), channel_manager=mgr)
    intent = QueryIntent(category=QueryCategory.CURRENT_VALUE, target_channels=None)
    assert router._resolve_target_channels(intent) is None


def test_router_passes_through_when_no_channel_manager() -> None:
    router = QueryRouter(_make_adapters(), channel_manager=None)
    intent = QueryIntent(
        category=QueryCategory.CURRENT_VALUE,
        target_channels=["anything", "goes"],
    )
    assert router._resolve_target_channels(intent) == ["anything", "goes"]
