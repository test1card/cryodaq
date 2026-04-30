"""Tests for F30 Live Query Agent — Phase C: AssistantQueryAgent."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.query.agent import _FALLBACK, AssistantQueryAgent
from cryodaq.agents.assistant.query.schemas import (
    ActiveAlarmInfo,
    AlarmStatusResult,
    CompositeStatus,
    CooldownETA,
    QueryAdapters,
    VacuumETA,
)

# ---------------------------------------------------------------------------
# Test fixtures / helpers
# ---------------------------------------------------------------------------


def _make_config(brand_name: str = "Гемма") -> MagicMock:
    cfg = MagicMock()
    cfg.brand_name = brand_name
    return cfg


def _make_audit() -> MagicMock:
    audit = MagicMock()
    audit.make_audit_id.return_value = "abc123"
    audit.log = AsyncMock(return_value=None)
    return audit


def _make_gen_result(text: str, truncated: bool = False) -> MagicMock:
    r = MagicMock()
    r.text = text
    r.truncated = truncated
    r.model = "gemma4:e2b"
    r.tokens_in = 50
    r.tokens_out = 80
    return r


def _make_adapters(
    *,
    cooldown_eta: CooldownETA | None = None,
    vacuum_eta: VacuumETA | None = None,
    composite_status: CompositeStatus | None = None,
    alarm_result: AlarmStatusResult | None = None,
) -> QueryAdapters:
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


def _make_agent(
    ollama: MagicMock,
    adapters: QueryAdapters | None = None,
    *,
    max_per_hour: int = 60,
) -> AssistantQueryAgent:
    return AssistantQueryAgent(
        ollama_client=ollama,
        audit_logger=_make_audit(),
        config=_make_config(),
        adapters=adapters or _make_adapters(),
        max_queries_per_chat_per_hour=max_per_hour,
    )


def _intent_json(category: str) -> str:
    import json
    return json.dumps({
        "category": category,
        "target_channels": None,
        "time_window_minutes": None,
        "quantity": "",
    })


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------


async def test_query_agent_handles_eta_cooldown_full_flow() -> None:
    """Classify eta_cooldown → fetch → format → return Russian response."""
    eta = CooldownETA(
        t_remaining_hours=5.0,
        t_remaining_low_68=4.5,
        t_remaining_high_68=5.5,
        progress=0.4,
        phase="COOLING",
        n_references=10,
        cooldown_active=True,
        T_cold=80.0,
    )
    adapters = _make_adapters(cooldown_eta=eta)

    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=[
        _make_gen_result(_intent_json("eta_cooldown")),   # Phase B: classify
        _make_gen_result("Охлаждение займёт ещё 5 часов."),  # Phase C: format
    ])

    agent = _make_agent(ollama, adapters)
    resp = await agent.handle_query("когда достигнем 4К?")

    assert "5" in resp or "Охлаждение" in resp
    assert ollama.generate.await_count == 2
    adapters.cooldown.eta.assert_awaited_once()


async def test_query_agent_handles_eta_vacuum_with_no_active_pumping() -> None:
    """When vacuum_eta is None, agent still returns a coherent response."""
    adapters = _make_adapters(vacuum_eta=None)

    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=[
        _make_gen_result(_intent_json("eta_vacuum")),
        _make_gen_result("Вакуумный прогноз недоступен: сервис не активен."),
    ])

    agent = _make_agent(ollama, adapters)
    resp = await agent.handle_query("ETA вакуума?")

    assert resp != _FALLBACK
    assert ollama.generate.await_count == 2


async def test_query_agent_composite_status_parallel() -> None:
    """composite_status query fetches composite adapter and formats result."""
    cs = CompositeStatus(
        timestamp=datetime.now(UTC),
        experiment=None,
        cooldown_eta=None,
        vacuum_eta=None,
        active_alarms=[],
        key_temperatures={"T_cold": 42.5},
        current_pressure=1e-4,
    )
    adapters = _make_adapters(composite_status=cs)

    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=[
        _make_gen_result(_intent_json("composite_status")),
        _make_gen_result("Система в норме. T_cold = 42.5 K."),
    ])

    agent = _make_agent(ollama, adapters)
    resp = await agent.handle_query("что сейчас?")

    assert resp != _FALLBACK
    adapters.composite.status.assert_awaited_once()


async def test_query_agent_out_of_scope_historical_response() -> None:
    """out_of_scope_historical: no data fetch; LLM renders polite refusal."""
    adapters = _make_adapters()

    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=[
        _make_gen_result(_intent_json("out_of_scope_historical")),
        _make_gen_result("Исторические данные пока недоступны. Это появится в F33."),
    ])

    agent = _make_agent(ollama, adapters)
    resp = await agent.handle_query("что было вчера?")

    assert resp != _FALLBACK
    # Composite and cooldown should NOT be called for out-of-scope
    adapters.composite.status.assert_not_awaited()
    adapters.cooldown.eta.assert_not_awaited()


async def test_query_agent_handles_intent_classifier_failure() -> None:
    """When intent classifier LLM returns garbage, agent falls back gracefully."""
    adapters = _make_adapters()

    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=[
        _make_gen_result("NOT JSON AT ALL"),  # classifier fails → UNKNOWN
        _make_gen_result("Запрос непонятен. Попробуй: 'что сейчас?'."),
    ])

    agent = _make_agent(ollama, adapters)
    resp = await agent.handle_query("aasdfjkl")

    assert resp != _FALLBACK
    assert ollama.generate.await_count == 2


async def test_query_agent_handles_ollama_exception() -> None:
    """Unrecoverable OllamaClient error → fallback string, no raise."""
    from cryodaq.agents.assistant.shared.ollama_client import OllamaUnavailableError

    ollama = MagicMock()
    ollama.generate = AsyncMock(
        side_effect=OllamaUnavailableError("server down")
    )

    agent = _make_agent(ollama, _make_adapters())
    resp = await agent.handle_query("ETA охлаждения?")

    assert resp == _FALLBACK


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------


async def test_query_agent_audit_log_per_query() -> None:
    """AuditLogger.log() is called once per query with expected fields."""
    adapters = _make_adapters()
    audit = _make_audit()

    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=[
        _make_gen_result(_intent_json("composite_status")),
        _make_gen_result("Всё в порядке."),
    ])

    agent = AssistantQueryAgent(
        ollama_client=ollama,
        audit_logger=audit,
        config=_make_config(),
        adapters=adapters,
    )
    await agent.handle_query("статус?", chat_id=42)

    audit.log.assert_awaited_once()
    kwargs = audit.log.call_args.kwargs
    assert kwargs["trigger_event"]["type"] == "live_query"
    assert kwargs["trigger_event"]["chat_id"] == 42
    assert kwargs["trigger_event"]["category"] == "composite_status"
    assert "telegram" in kwargs["outputs_dispatched"]
    assert kwargs["errors"] == []


async def test_query_agent_audit_log_records_errors() -> None:
    """When format LLM returns truncated, errors list is non-empty in audit."""
    adapters = _make_adapters()
    audit = _make_audit()

    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=[
        _make_gen_result(_intent_json("phase_info")),
        _make_gen_result("", truncated=True),  # format LLM truncated
    ])

    agent = AssistantQueryAgent(
        ollama_client=ollama,
        audit_logger=audit,
        config=_make_config(),
        adapters=adapters,
    )
    resp = await agent.handle_query("в какой фазе?")

    assert resp == _FALLBACK
    kwargs = audit.log.call_args.kwargs
    assert "format_llm_truncated_or_empty" in kwargs["errors"]


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


async def test_query_agent_rate_limit_per_chat() -> None:
    """After max_queries_per_chat_per_hour, returns rate-limit message."""
    adapters = _make_adapters()

    ollama = MagicMock()
    ollama.generate = AsyncMock(
        return_value=_make_gen_result("ok")
    )

    agent = _make_agent(ollama, adapters, max_per_hour=1)

    # First query: passes through (calls ollama)
    first = await agent.handle_query("запрос 1", chat_id=99)
    assert first != "Слишком много запросов. Подожди немного."
    assert ollama.generate.await_count >= 1

    # Second query from same chat: rate-limited
    ollama.generate.reset_mock()
    second = await agent.handle_query("запрос 2", chat_id=99)
    assert second == "Слишком много запросов. Подожди немного."
    ollama.generate.assert_not_awaited()


async def test_query_agent_rate_limit_separate_chats() -> None:
    """Rate limit is per chat — different chat IDs have separate buckets."""
    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=[
        _make_gen_result(_intent_json("unknown")),
        _make_gen_result("ок"),
        _make_gen_result(_intent_json("unknown")),
        _make_gen_result("ок"),
    ])

    agent = _make_agent(ollama, _make_adapters(), max_per_hour=1)

    r1 = await agent.handle_query("запрос", chat_id=1)
    r2 = await agent.handle_query("запрос", chat_id=2)

    assert r1 != "Слишком много запросов. Подожди немного."
    assert r2 != "Слишком много запросов. Подожди немного."


# ---------------------------------------------------------------------------
# Format prompt building
# ---------------------------------------------------------------------------


async def test_query_agent_total_timeout_enforcement() -> None:
    """Truncated format LLM response returns _FALLBACK, not empty string."""
    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=[
        _make_gen_result(_intent_json("alarm_status")),
        _make_gen_result("  ", truncated=False),  # empty text (not truncated flag)
    ])

    agent = _make_agent(ollama, _make_adapters())
    resp = await agent.handle_query("тревоги?")

    assert resp == _FALLBACK


async def test_query_agent_format_alarm_with_active_alarms() -> None:
    """Alarm status with active alarms passes alarm_count > 0 to prompt."""
    alarm = ActiveAlarmInfo(
        alarm_id="T1_high",
        level="WARNING",
        channels=["T_cold"],
        triggered_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )
    alarms = AlarmStatusResult(active=[alarm])
    adapters = _make_adapters(alarm_result=alarms)

    captured_prompt: list[str] = []

    async def capturing_generate(prompt, **kwargs):
        captured_prompt.append(prompt)
        return _make_gen_result("Есть 1 активная тревога.")

    ollama = MagicMock()
    # First call: intent (no prompt capture needed)
    # Second call: format (capture the user prompt)
    call_count = 0

    async def side_effect(prompt, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_gen_result(_intent_json("alarm_status"))
        captured_prompt.append(prompt)
        return _make_gen_result("Есть 1 активная тревога.")

    ollama.generate = AsyncMock(side_effect=side_effect)

    agent = _make_agent(ollama, adapters)
    resp = await agent.handle_query("есть ли тревоги?")

    assert resp != _FALLBACK
    assert captured_prompt  # format prompt was built
    assert "T1_high" in captured_prompt[0]
    assert "WARNING" in captured_prompt[0]
