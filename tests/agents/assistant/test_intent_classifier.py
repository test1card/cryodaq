"""Tests for F30 Live Query Agent — Phase B: intent classifier + router."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.query.intent_classifier import (
    IntentClassifier,
    _parse_intent,
)
from cryodaq.agents.assistant.query.router import QueryRouter
from cryodaq.agents.assistant.query.schemas import (
    AlarmStatusResult,
    CompositeStatus,
    CooldownETA,
    QueryAdapters,
    QueryCategory,
    QueryIntent,
    RangeStats,
    VacuumETA,
)


def _j(
    category: str,
    channels: list[str] | None = None,
    window: int | None = None,
    quantity: str = "",
) -> str:
    return json.dumps({
        "category": category,
        "target_channels": channels,
        "time_window_minutes": window,
        "quantity": quantity,
    })


# ---------------------------------------------------------------------------
# _parse_intent unit tests
# ---------------------------------------------------------------------------


def test_parse_intent_eta_vacuum() -> None:
    intent = _parse_intent(_j("eta_vacuum", quantity="ETA вакуума"))
    assert intent.category == QueryCategory.ETA_VACUUM


def test_parse_intent_current_value_with_channels() -> None:
    intent = _parse_intent(_j("current_value", ["T_cold", "T_warm"], quantity="температура"))
    assert intent.category == QueryCategory.CURRENT_VALUE
    assert intent.target_channels == ["T_cold", "T_warm"]


def test_parse_intent_range_stats_with_window() -> None:
    intent = _parse_intent(_j("range_stats", ["P_main"], window=30, quantity="диапазон"))
    assert intent.category == QueryCategory.RANGE_STATS
    assert intent.time_window_minutes == 30


def test_parse_intent_strips_code_fence() -> None:
    inner = _j("composite_status", quantity="статус")
    raw = f"```json\n{inner}\n```"
    intent = _parse_intent(raw)
    assert intent.category == QueryCategory.COMPOSITE_STATUS


def test_parse_intent_extracts_json_from_surrounding_text() -> None:
    inner = _j("phase_info", quantity="фаза")
    raw = f"Вот JSON: {inner} конец."
    intent = _parse_intent(raw)
    assert intent.category == QueryCategory.PHASE_INFO


def test_parse_intent_returns_unknown_on_empty() -> None:
    intent = _parse_intent("")
    assert intent.category == QueryCategory.UNKNOWN


def test_parse_intent_returns_unknown_on_malformed_json() -> None:
    intent = _parse_intent("{not json at all")
    assert intent.category == QueryCategory.UNKNOWN


def test_parse_intent_returns_unknown_on_invalid_category() -> None:
    intent = _parse_intent(_j("totally_made_up"))
    assert intent.category == QueryCategory.UNKNOWN


def test_parse_intent_handles_non_list_channels() -> None:
    raw = '{"category": "current_value", "target_channels": "T_cold",'
    raw += ' "time_window_minutes": null, "quantity": ""}'
    intent = _parse_intent(raw)
    assert intent.target_channels is None


def test_parse_intent_handles_non_int_window() -> None:
    raw = '{"category": "range_stats", "target_channels": null,'
    raw += ' "time_window_minutes": "не число", "quantity": ""}'
    intent = _parse_intent(raw)
    assert intent.time_window_minutes is None


# ---------------------------------------------------------------------------
# IntentClassifier.classify() — mocked OllamaClient
# ---------------------------------------------------------------------------


def _make_ollama_result(text: str, truncated: bool = False) -> MagicMock:
    r = MagicMock()
    r.text = text
    r.truncated = truncated
    return r


def _make_ollama(text: str, truncated: bool = False) -> MagicMock:
    client = MagicMock()
    client.generate = AsyncMock(
        return_value=_make_ollama_result(text, truncated)
    )
    return client


async def test_intent_classifier_categorizes_eta_vacuum_query() -> None:
    ollama = _make_ollama(_j("eta_vacuum", quantity="ETA вакуума"))
    clf = IntentClassifier(ollama)
    intent = await clf.classify("когда вакуум достигнет 1е-6?")
    assert intent.category == QueryCategory.ETA_VACUUM


async def test_intent_classifier_handles_misspelled_query() -> None:
    """Classifier still returns valid intent even if the query has typos."""
    resp = _j("current_value", ["T_cold"], quantity="температура")
    ollama = _make_ollama(resp)
    clf = IntentClassifier(ollama)
    intent = await clf.classify("какая темпертура Т_колд?")  # typo
    assert intent.category == QueryCategory.CURRENT_VALUE


async def test_intent_classifier_returns_unknown_on_gibberish() -> None:
    ollama = _make_ollama(_j("unknown"))
    clf = IntentClassifier(ollama)
    intent = await clf.classify("asdf qwerty zxcv 123")
    assert intent.category == QueryCategory.UNKNOWN


async def test_intent_classifier_handles_json_parse_failure() -> None:
    """Falls back to UNKNOWN when LLM returns unparseable output."""
    ollama = _make_ollama("Извините, я не могу ответить на это.")
    clf = IntentClassifier(ollama)
    intent = await clf.classify("какой-то запрос")
    assert intent.category == QueryCategory.UNKNOWN


async def test_intent_classifier_handles_llm_timeout() -> None:
    """Falls back to UNKNOWN when OllamaClient raises."""
    client = MagicMock()
    client.generate = AsyncMock(side_effect=TimeoutError("connection timed out"))
    clf = IntentClassifier(client)
    intent = await clf.classify("ETA охлаждения")
    assert intent.category == QueryCategory.UNKNOWN


async def test_intent_classifier_handles_truncated_response() -> None:
    """Falls back to UNKNOWN on truncated LLM response."""
    ollama = _make_ollama('{"category": "eta_co', truncated=True)
    clf = IntentClassifier(ollama)
    intent = await clf.classify("ETA охлаждения")
    assert intent.category == QueryCategory.UNKNOWN


async def test_intent_classifier_handles_empty_response() -> None:
    ollama = _make_ollama("   ")
    clf = IntentClassifier(ollama)
    intent = await clf.classify("что сейчас?")
    assert intent.category == QueryCategory.UNKNOWN


# ---------------------------------------------------------------------------
# QueryRouter.fetch() — mocked QueryAdapters
# ---------------------------------------------------------------------------


def _make_adapters(
    *,
    cooldown_eta: CooldownETA | None = None,
    vacuum_eta: VacuumETA | None = None,
    composite_status: CompositeStatus | None = None,
    alarm_result: AlarmStatusResult | None = None,
) -> QueryAdapters:
    from datetime import UTC, datetime

    snap = MagicMock()
    snap.latest = AsyncMock(return_value=None)
    snap.latest_age_s = AsyncMock(return_value=None)
    snap.latest_all = AsyncMock(return_value={})

    cooldown = MagicMock()
    cooldown.eta = AsyncMock(return_value=cooldown_eta)

    vacuum = MagicMock()
    vacuum.eta_to_target = AsyncMock(return_value=vacuum_eta)

    sqlite = MagicMock()
    sqlite.range_stats = AsyncMock(return_value=None)

    alarms = MagicMock()
    alarms.active = AsyncMock(return_value=alarm_result or AlarmStatusResult())

    experiment = MagicMock()
    experiment.status = AsyncMock(return_value=None)

    composite = MagicMock()
    composite.status = AsyncMock(
        return_value=composite_status
        or CompositeStatus(
            timestamp=datetime.now(UTC),
            experiment=None,
            cooldown_eta=None,
            vacuum_eta=None,
            active_alarms=[],
            key_temperatures={},
            current_pressure=None,
        )
    )

    return QueryAdapters(
        broker_snapshot=snap,
        cooldown=cooldown,
        vacuum=vacuum,
        sqlite=sqlite,
        alarms=alarms,
        experiment=experiment,
        composite=composite,
    )


async def test_router_dispatches_eta_cooldown_to_cooldown_adapter() -> None:
    eta = CooldownETA(
        t_remaining_hours=4.0,
        t_remaining_low_68=3.5,
        t_remaining_high_68=4.5,
        progress=0.5,
        phase="COOLING",
        n_references=10,
        cooldown_active=True,
    )
    adapters = _make_adapters(cooldown_eta=eta)
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.ETA_COOLDOWN)
    result = await router.fetch(intent, "когда 4К?")

    assert "cooldown_eta" in result
    assert result["cooldown_eta"] is eta
    adapters.cooldown.eta.assert_awaited_once()


async def test_router_dispatches_composite_status_to_composite() -> None:
    adapters = _make_adapters()
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.COMPOSITE_STATUS)
    result = await router.fetch(intent, "что сейчас?")

    assert "composite_status" in result
    adapters.composite.status.assert_awaited_once()


async def test_router_handles_out_of_scope_historical() -> None:
    adapters = _make_adapters()
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.OUT_OF_SCOPE_HISTORICAL)
    result = await router.fetch(intent, "что было вчера?")

    assert result == {}
    adapters.cooldown.eta.assert_not_awaited()


async def test_router_handles_out_of_scope_general() -> None:
    adapters = _make_adapters()
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.OUT_OF_SCOPE_GENERAL)
    result = await router.fetch(intent, "как работает вакуум?")
    assert result == {}


async def test_router_handles_unknown_category() -> None:
    adapters = _make_adapters()
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.UNKNOWN)
    result = await router.fetch(intent, "???")
    assert result == {}


async def test_router_dispatches_alarm_status() -> None:
    adapters = _make_adapters()
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.ALARM_STATUS)
    result = await router.fetch(intent, "есть ли тревоги?")

    assert "alarm_result" in result
    adapters.alarms.active.assert_awaited_once()


async def test_router_dispatches_phase_info() -> None:
    adapters = _make_adapters()
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.PHASE_INFO)
    result = await router.fetch(intent, "в какой фазе?")

    assert "experiment_status" in result
    adapters.experiment.status.assert_awaited_once()


async def test_router_dispatches_eta_vacuum() -> None:
    adapters = _make_adapters()
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.ETA_VACUUM)
    result = await router.fetch(intent, "ETA вакуума")

    assert "vacuum_eta" in result
    adapters.vacuum.eta_to_target.assert_awaited_once()


async def test_router_dispatches_current_value() -> None:
    snap = MagicMock()
    snap.latest = AsyncMock(return_value=MagicMock(value=12.5))
    snap.latest_age_s = AsyncMock(return_value=5.0)
    snap.latest_all = AsyncMock(return_value={})

    adapters = _make_adapters()
    adapters.broker_snapshot = snap

    router = QueryRouter(adapters)
    intent = QueryIntent(
        category=QueryCategory.CURRENT_VALUE,
        target_channels=["T_cold"],
    )
    result = await router.fetch(intent, "какая T_cold?")

    assert "readings" in result
    assert "ages_s" in result
    assert "T_cold" in result["readings"]


async def test_router_dispatches_range_stats() -> None:
    stats = RangeStats(
        channel="T_cold",
        window_minutes=60,
        n_samples=100,
        min_value=10.0,
        max_value=15.0,
        mean_value=12.5,
        std_value=1.0,
    )
    adapters = _make_adapters()
    adapters.sqlite.range_stats = AsyncMock(return_value=stats)

    router = QueryRouter(adapters)
    intent = QueryIntent(
        category=QueryCategory.RANGE_STATS,
        target_channels=["T_cold"],
        time_window_minutes=60,
    )
    result = await router.fetch(intent, "диапазон T_cold за час?")

    assert "range_stats" in result
    assert "T_cold" in result["range_stats"]


async def test_router_never_raises_on_adapter_exception() -> None:
    """Router swallows adapter exceptions and returns {}."""
    adapters = _make_adapters()
    adapters.cooldown.eta = AsyncMock(side_effect=RuntimeError("service down"))

    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.ETA_COOLDOWN)
    result = await router.fetch(intent, "ETA охлаждения?")
    assert result == {}
