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
    # 2026-05-08 (v0.56.2): aligned with landmark v3 prompt reformat —
    # headlines are now "▶ {ch_id} ({physical})" with aliases listed as
    # bullet points underneath ("    • «alias»"). Substring matches on
    # alias text still hold against the bullet-formatted lines.
    assert "▶ Т11 (1-я ступень GM-cooler, ~40K при работе)" in hint
    # Aliases rendered as bullet rows
    assert "плита" in hint
    assert "первая ступень" in hint
    # Т12 path
    assert "▶ Т12 (2-я ступень GM-cooler, ~2.9K при работе)" in hint
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
    # 2026-05-08 (v0.56.2): v3 prompt header renamed
    # "КАНАЛЫ-LANDMARKS:" → "═══ ВАЖНЕЙШЕЕ ПРАВИЛО — LANDMARK КАНАЛЫ ═══"
    assert "LANDMARK КАНАЛЫ" in hint
    assert "КАНАЛЫ ТЕКУЩЕГО ЭКСПЕРИМЕНТА" in hint
    # Landmark section comes before experiment section.
    assert hint.index("LANDMARK КАНАЛЫ") < hint.index("КАНАЛЫ ТЕКУЩЕГО ЭКСПЕРИМЕНТА")
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
    assert resolved == ["Т11"], f"Landmark alias must beat experiment name on collision; got {resolved}"


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


def test_the_pressure_gauge_is_offered_to_the_classifier() -> None:
    """Reported by the operator's own test question, 2026-09-07.

    Asked "какое сейчас давление и куда оно идёт", the assistant answered
    "давление не вижу — данных по каналу нет" while the gauge was writing a
    value every second. No warning, no error: the pipeline ran and honestly
    reported nothing.

    The cause was upstream of every adapter. The classifier's channel hint was
    built only from channels.yaml, which describes the operator's thermometer
    set and contains `VSP63D_1/pressure` exactly zero times — so the model was
    told about 24 temperatures and nothing else, and could not map the word to
    a channel. `BrokerSnapshot.latest` already resolves ids AND display names,
    and its docstring records the same symptom from an earlier incident; the
    resolution was never the problem, the naming was.
    """
    from cryodaq.agents.assistant.query.intent_classifier import _build_live_channel_hint
    from cryodaq.core.channel_manager import ChannelManager

    hint = _build_live_channel_hint(
        {
            "VSP63D_1/pressure": {"unit": "mbar", "display_name": "VSP63D_1/pressure"},
            "Keithley_1/smua/voltage": {"unit": "V", "display_name": "Keithley_1/smua/voltage"},
        },
        ChannelManager(),
    )

    assert "VSP63D_1/pressure" in hint, "the classifier is still not told the gauge exists"
    assert "[mbar]" in hint, "the unit is how the model tells a pressure from a temperature"
    assert "Keithley_1/smua/voltage" in hint


def test_channels_already_named_in_the_config_are_not_repeated(tmp_path) -> None:
    """The experiment's own thermometers are listed by the other hint."""
    from cryodaq.agents.assistant.query.intent_classifier import _build_live_channel_hint
    from cryodaq.core.channel_manager import ChannelManager

    config = tmp_path / "channels.yaml"
    config.write_text("channels:\n  Т12:\n    name: 2-я ступень\n    visible: true\n", encoding="utf-8")

    hint = _build_live_channel_hint(
        {
            "Т12 2-я ступень": {"unit": "K", "display_name": "Т12 2-я ступень"},
            "VSP63D_1/pressure": {"unit": "mbar", "display_name": "VSP63D_1/pressure"},
        },
        ChannelManager(config_path=config),
    )

    assert "Т12" not in hint, "a configured channel was listed twice"
    assert "VSP63D_1/pressure" in hint


def test_no_live_channels_costs_nothing() -> None:
    """The hint is additive: without a snapshot the classifier works as before."""
    from cryodaq.agents.assistant.query.intent_classifier import _build_live_channel_hint
    from cryodaq.core.channel_manager import ChannelManager

    assert _build_live_channel_hint(None, ChannelManager()) == ""
    assert _build_live_channel_hint({}, ChannelManager()) == ""
