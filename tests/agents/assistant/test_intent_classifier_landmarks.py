"""F-ChannelLandmarks: IntentClassifier prompt builder honors landmark map.

These tests pin the deterministic prompt-construction surface — `_build_channel_hint`
reads `channel_manager.get_landmarks()` and emits a two-tier listing with explicit
priority text. The actual LLM behavior on those prompts is operator-tested via
the smoke-test path in the spec; what we lock down here is what the classifier
SENDS to Ollama.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from cryodaq.agents.assistant.query.intent_classifier import (
    _build_channel_hint,
    _build_landmark_hint,
)


def _make_manager(
    *,
    channels: dict[str, dict] | None = None,
    landmarks: dict[str, dict] | None = None,
) -> MagicMock:
    """Build a ChannelManager double exposing exactly the methods the
    classifier reads."""
    mgr = MagicMock()
    mgr.get_all.return_value = channels or {}
    mgr.is_visible.side_effect = lambda ch_id: (channels or {}).get(ch_id, {}).get("visible", True)
    mgr.get_landmarks.return_value = landmarks or {}
    return mgr


_T11_LANDMARKS = {
    "Т11": {
        "role": "warm_stage",
        "physical": "1-я ступень GM-cooler, ~40K при работе",
        "aliases": [
            "азотная плита",
            "плита",
            "первая ступень",
            "т warm",
        ],
    },
    "Т12": {
        "role": "cold_stage",
        "physical": "2-я ступень GM-cooler, ~2.9K при работе",
        "aliases": [
            "вторая ступень",
            "холодная точка",
            "холодный палец",
            "т cold",
        ],
    },
}


# ---------------------------------------------------------------------------
# _build_landmark_hint
# ---------------------------------------------------------------------------


def test_landmark_hint_empty_when_no_landmarks() -> None:
    mgr = _make_manager(landmarks={})
    assert _build_landmark_hint(mgr) == ""


def test_landmark_hint_lists_aliases_under_each_channel() -> None:
    mgr = _make_manager(landmarks=_T11_LANDMARKS)
    hint = _build_landmark_hint(mgr)
    # First-alias headline plus parenthetical physical description
    assert "Т11 — азотная плита (1-я ступень GM-cooler, ~40K при работе)" in hint
    # Remaining aliases joined as a "также может называться:" tail
    assert "плита" in hint
    assert "первая ступень" in hint
    # Т12 path
    assert "Т12 — вторая ступень" in hint
    assert "холодная точка" in hint


def test_landmark_hint_deterministic_channel_order() -> None:
    """Channels emitted in sorted order so prompt diffs stay stable."""
    mgr = _make_manager(landmarks=_T11_LANDMARKS)
    hint = _build_landmark_hint(mgr)
    assert hint.index("Т11") < hint.index("Т12")


# ---------------------------------------------------------------------------
# _build_channel_hint integration
# ---------------------------------------------------------------------------


def test_build_channel_hint_emits_landmarks_and_experiment_separately() -> None:
    mgr = _make_manager(
        channels={
            "Т1": {"name": "Криостат верх", "visible": True},
            "Т5": {"name": "Экран 77К", "visible": True},
        },
        landmarks=_T11_LANDMARKS,
    )
    hint = _build_channel_hint(mgr)
    assert "КАНАЛЫ-LANDMARKS" in hint
    assert "КАНАЛЫ ТЕКУЩЕГО ЭКСПЕРИМЕНТА" in hint
    # Landmark section comes before experiment section.
    assert hint.index("КАНАЛЫ-LANDMARKS") < hint.index("КАНАЛЫ ТЕКУЩЕГО ЭКСПЕРИМЕНТА")
    # Experiment channel data still rendered.
    assert 'Т1 → "Криостат верх"' in hint
    # Landmark aliases present.
    assert "азотная плита" in hint


def test_build_channel_hint_explicit_priority_note() -> None:
    """Prompt explicitly tells the model that landmarks beat experiment names."""
    mgr = _make_manager(
        channels={"Т5": {"name": "Азотный экран", "visible": True}},
        landmarks=_T11_LANDMARKS,
    )
    hint = _build_channel_hint(mgr)
    assert "приоритетнее" in hint


def test_build_channel_hint_no_landmarks_falls_back_to_legacy_section() -> None:
    """Backward compat: when landmarks are not installed, the prompt keeps the
    pre-F-ChannelLandmarks 'Доступные каналы' header so the v0.53.x behavior
    is preserved."""
    mgr = _make_manager(
        channels={"Т1": {"name": "Криостат верх", "visible": True}},
        landmarks={},
    )
    hint = _build_channel_hint(mgr)
    assert "Доступные каналы" in hint
    assert "КАНАЛЫ-LANDMARKS" not in hint
    assert "приоритетнее" not in hint


def test_build_channel_hint_handles_none_manager() -> None:
    assert _build_channel_hint(None) == ""


def test_build_channel_hint_skips_invisible_experiment_channels() -> None:
    mgr = _make_manager(
        channels={
            "Т1": {"name": "Visible", "visible": True},
            "Т2": {"name": "Hidden", "visible": False},
        },
        landmarks=_T11_LANDMARKS,
    )
    hint = _build_channel_hint(mgr)
    assert 'Т1 → "Visible"' in hint
    assert "Hidden" not in hint


# ---------------------------------------------------------------------------
# Runtime resolution — landmark aliases beat experiment names in the router
# ---------------------------------------------------------------------------


def test_find_by_landmark_alias_resolves_to_landmark_id() -> None:
    """ChannelManager.find_by_landmark_alias matches aliases case-insensitively
    and returns the canonical landmark channel_id."""
    from cryodaq.core.channel_manager import ChannelManager

    mgr = ChannelManager()
    mgr.set_landmarks(_T11_LANDMARKS)
    assert mgr.find_by_landmark_alias("азотная плита") == "Т11"
    assert mgr.find_by_landmark_alias("  АЗОТНАЯ ПЛИТА  ") == "Т11"
    assert mgr.find_by_landmark_alias("холодная точка") == "Т12"
    # Direct landmark channel_id also resolves (no-op safety).
    assert mgr.find_by_landmark_alias("Т11") == "Т11"
    # Non-matching phrase returns None — caller falls through to experiment names.
    assert mgr.find_by_landmark_alias("криостат верх") is None


def test_query_router_resolves_landmark_alias_over_experiment_name() -> None:
    """Production-bug regression: even if an experiment-level channel name
    collides with a landmark alias, the router returns the landmark."""
    from cryodaq.agents.assistant.query.router import QueryRouter
    from cryodaq.agents.assistant.query.schemas import (
        QueryCategory,
        QueryIntent,
    )
    from cryodaq.core.channel_manager import ChannelManager

    mgr = ChannelManager()
    # Experiment-level Т5 happens to share the alias text — pre-fix, find_by_name
    # would return Т5 because it walked channels.yaml only.
    mgr.set_name("Т5", "Азотная плита")
    mgr.set_landmarks(_T11_LANDMARKS)

    router = QueryRouter(adapters=MagicMock(), channel_manager=mgr)
    intent = QueryIntent(
        category=QueryCategory.CURRENT_VALUE,
        target_channels=["азотная плита"],
    )
    resolved = router._resolve_target_channels(intent)
    assert resolved == ["Т11"], (
        f"Landmark alias must beat experiment name on collision; got {resolved}"
    )


def test_query_router_canonical_id_still_wins_first_pass() -> None:
    """When the LLM emits the canonical channel_id, direct-ID match returns
    it without going through the alias path."""
    from cryodaq.agents.assistant.query.router import QueryRouter
    from cryodaq.agents.assistant.query.schemas import (
        QueryCategory,
        QueryIntent,
    )
    from cryodaq.core.channel_manager import ChannelManager

    mgr = ChannelManager()
    mgr.set_landmarks(_T11_LANDMARKS)
    router = QueryRouter(adapters=MagicMock(), channel_manager=mgr)
    intent = QueryIntent(
        category=QueryCategory.CURRENT_VALUE,
        target_channels=["Т12"],
    )
    assert router._resolve_target_channels(intent) == ["Т12"]


def test_query_router_falls_through_to_experiment_name_without_landmarks() -> None:
    """Backward compat: with no landmarks installed, the resolver still
    delegates to experiment-name matching unchanged."""
    from cryodaq.agents.assistant.query.router import QueryRouter
    from cryodaq.agents.assistant.query.schemas import (
        QueryCategory,
        QueryIntent,
    )
    from cryodaq.core.channel_manager import ChannelManager

    mgr = ChannelManager()
    mgr.set_name("Т7", "Болометр")
    # No set_landmarks call — get_landmarks() stays empty.
    router = QueryRouter(adapters=MagicMock(), channel_manager=mgr)
    intent = QueryIntent(
        category=QueryCategory.CURRENT_VALUE,
        target_channels=["Болометр"],
    )
    assert router._resolve_target_channels(intent) == ["Т7"]
