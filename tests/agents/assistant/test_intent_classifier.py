"""Tests for F30 Live Query Agent — Phase B: intent classifier + router."""

from __future__ import annotations

import asyncio
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
    return json.dumps(
        {
            "category": category,
            "target_channels": channels,
            "time_window_minutes": window,
            "quantity": quantity,
        }
    )


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
    client.generate = AsyncMock(return_value=_make_ollama_result(text, truncated))
    return client


async def test_intent_classifier_parses_mocked_eta_vacuum_response() -> None:
    """Parser extracts eta_vacuum from a mocked generate() response.

    Ollama is unconditionally mocked — classification semantics are not
    tested here.  What IS tested: the query text reaches generate() (so a
    broken prompt-construction path would be caught), and the response JSON
    is correctly parsed into ETA_VACUUM.
    """
    query = "когда вакуум достигнет 1е-6?"
    ollama = _make_ollama(_j("eta_vacuum", quantity="ETA вакуума"))
    clf = IntentClassifier(ollama)
    intent = await clf.classify(query)
    assert intent.category == QueryCategory.ETA_VACUUM
    # Verify the query text actually reached generate() — catches broken
    # prompt-construction paths without relying on live LLM semantics.
    call_kwargs = ollama.generate.call_args
    assert query in str(call_kwargs)


async def test_intent_classifier_parses_mocked_current_value_response() -> None:
    """Parser extracts current_value from a mocked generate() response.

    Renamed from 'handles_misspelled_query': the typo has no effect on a
    mock — this test only verifies parser correctness and that the query
    text (typo included) was forwarded to generate().
    """
    query = "какая темпертура Т_колд?"  # intentional typo in original test
    resp = _j("current_value", ["T_cold"], quantity="температура")
    ollama = _make_ollama(resp)
    clf = IntentClassifier(ollama)
    intent = await clf.classify(query)
    assert intent.category == QueryCategory.CURRENT_VALUE
    call_kwargs = ollama.generate.call_args
    assert query in str(call_kwargs)


async def test_intent_classifier_parses_mocked_unknown_response() -> None:
    """Parser returns UNKNOWN when generate() yields an 'unknown' category JSON.

    Renamed from 'returns_unknown_on_gibberish': the mock returns unknown
    regardless of the query, so this is a parser test, not a semantic one.
    The query text reaching generate() is verified to catch prompt-path bugs.
    """
    query = "asdf qwerty zxcv 123"
    ollama = _make_ollama(_j("unknown"))
    clf = IntentClassifier(ollama)
    intent = await clf.classify(query)
    assert intent.category == QueryCategory.UNKNOWN
    call_kwargs = ollama.generate.call_args
    assert query in str(call_kwargs)


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


async def test_intent_classifier_applies_configured_timeout() -> None:
    """The query-specific timeout must win over a slower Ollama client bound."""
    cancelled = asyncio.Event()

    async def _slow_generate(*_args, **_kwargs):
        try:
            await asyncio.sleep(3600)
        finally:
            cancelled.set()

    client = MagicMock()
    client.generate = AsyncMock(side_effect=_slow_generate)
    classifier = IntentClassifier(client, timeout_s=0.01)

    intent = await asyncio.wait_for(classifier.classify("ETA охлаждения"), timeout=0.2)

    assert intent.category == QueryCategory.UNKNOWN
    assert cancelled.is_set(), "timed-out generate coroutine was not cancelled"


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
    adapters.cooldown.eta.assert_awaited_once_with()


async def test_router_dispatches_composite_status_to_composite() -> None:
    from datetime import UTC, datetime

    sentinel_composite = CompositeStatus(
        timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        experiment=None,
        cooldown_eta=None,
        vacuum_eta=None,
        active_alarms=[],
        key_temperatures={},
        current_pressure=None,
    )
    adapters = _make_adapters(composite_status=sentinel_composite)
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.COMPOSITE_STATUS)
    result = await router.fetch(intent, "что сейчас?")

    assert "composite_status" in result
    assert result["composite_status"] is sentinel_composite
    adapters.composite.status.assert_awaited_once_with()


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
    sentinel_alarm = AlarmStatusResult()
    adapters = _make_adapters(alarm_result=sentinel_alarm)
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.ALARM_STATUS)
    result = await router.fetch(intent, "есть ли тревоги?")

    assert "alarm_result" in result
    assert result["alarm_result"] is sentinel_alarm
    adapters.alarms.active.assert_awaited_once_with()


async def test_router_dispatches_phase_info() -> None:
    from cryodaq.agents.assistant.query.schemas import ExperimentStatus

    sentinel_status = ExperimentStatus(
        experiment_id="exp-sentinel",
        phase="COOLING",
        phase_started_at=None,
        experiment_age_s=0.0,
    )
    adapters = _make_adapters()
    adapters.experiment.status = AsyncMock(return_value=sentinel_status)
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.PHASE_INFO)
    result = await router.fetch(intent, "в какой фазе?")

    assert "experiment_status" in result
    assert result["experiment_status"] is sentinel_status
    adapters.experiment.status.assert_awaited_once_with()


async def test_router_dispatches_eta_vacuum() -> None:
    sentinel = VacuumETA(
        current_mbar=5e-5,
        eta_seconds=3600.0,
        target_mbar=1e-6,
        trend="falling",
        confidence=0.9,
    )
    adapters = _make_adapters(vacuum_eta=sentinel)
    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.ETA_VACUUM)
    result = await router.fetch(intent, "ETA вакуума")

    assert "vacuum_eta" in result
    assert result["vacuum_eta"] is sentinel
    # Router must pass exactly 1e-6 as the target pressure — a wrong/None
    # argument would silently produce a useless ETA for the wrong threshold.
    adapters.vacuum.eta_to_target.assert_awaited_once_with(1e-6)


async def test_router_dispatches_current_value() -> None:
    reading = MagicMock(value=12.5)
    snap = MagicMock()
    snap.latest = AsyncMock(return_value=reading)
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
    assert result["readings"]["T_cold"] is reading
    assert result["ages_s"]["T_cold"] == 5.0
    snap.latest.assert_awaited_once_with("T_cold")
    snap.latest_age_s.assert_awaited_once_with("T_cold")


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
    assert result["range_stats"]["T_cold"] is stats
    assert result["window_minutes"] == 60
    # Router must pass the resolved channel and the exact window — wrong window
    # or wrong channel would silently return stats for a different time range.
    adapters.sqlite.range_stats.assert_awaited_once_with("T_cold", 60)


async def test_router_never_raises_on_adapter_exception() -> None:
    """Router swallows adapter exceptions and returns {}."""
    adapters = _make_adapters()
    adapters.cooldown.eta = AsyncMock(side_effect=RuntimeError("service down"))

    router = QueryRouter(adapters)
    intent = QueryIntent(category=QueryCategory.ETA_COOLDOWN)
    result = await router.fetch(intent, "ETA охлаждения?")
    assert result == {}
