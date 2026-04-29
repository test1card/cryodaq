"""Tests for GemmaAgent alarm flow — Slice A end-to-end (mock Ollama)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.audit import AuditLogger
from cryodaq.agents.context_builder import ContextBuilder
from cryodaq.agents.gemma import GemmaAgent, GemmaConfig, _format_age
from cryodaq.agents.ollama_client import GenerationResult, OllamaUnavailableError
from cryodaq.agents.output_router import OutputRouter
from cryodaq.core.event_bus import EngineEvent, EventBus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _alarm_event(
    alarm_id: str = "test_alarm",
    level: str = "WARNING",
    experiment_id: str | None = "exp-001",
) -> EngineEvent:
    return EngineEvent(
        event_type="alarm_fired",
        timestamp=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        payload={
            "alarm_id": alarm_id,
            "level": level,
            "channels": ["T1", "T2"],
            "values": {"T1": 4.5, "T2": 4.8},
            "message": "Temperature above threshold",
        },
        experiment_id=experiment_id,
    )


def _make_config(**overrides) -> GemmaConfig:
    cfg = GemmaConfig(
        enabled=True,
        max_concurrent_inferences=1,
        max_calls_per_hour=60,
        alarm_min_level="WARNING",
        output_telegram=True,
        output_operator_log=True,
        output_gui_insight=False,
        audit_enabled=False,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_mock_ollama(text: str = "🤖 Тест: температура T1 4.5K выше порога.") -> MagicMock:
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(
            text=text, tokens_in=80, tokens_out=25, latency_s=3.5, model="gemma4:e4b"
        )
    )
    ollama.close = AsyncMock()
    return ollama


def _make_mock_em() -> MagicMock:
    em = MagicMock()
    em.active_experiment_id = "exp-001"
    em.get_current_phase = MagicMock(return_value="COOL")
    em.get_phase_history = MagicMock(return_value=[])
    return em


def _make_context_builder(em) -> ContextBuilder:
    reader = MagicMock()
    return ContextBuilder(reader, em)


def _make_audit(tmp_path: Path) -> AuditLogger:
    return AuditLogger(tmp_path / "audit", enabled=False)


def _make_output_router(telegram=None, event_logger=None, event_bus=None) -> OutputRouter:
    if telegram is None:
        telegram = AsyncMock()
        telegram._send_to_all = AsyncMock()
    if event_logger is None:
        event_logger = AsyncMock()
        event_logger.log_event = AsyncMock()
    if event_bus is None:
        event_bus = EventBus()
    return OutputRouter(
        telegram_bot=telegram,
        event_logger=event_logger,
        event_bus=event_bus,
    )


def _make_agent(
    *,
    config: GemmaConfig | None = None,
    ollama=None,
    telegram=None,
    event_logger=None,
    tmp_path: Path,
) -> tuple[GemmaAgent, EventBus]:
    bus = EventBus()
    cfg = config or _make_config()
    em = _make_mock_em()
    ctx = _make_context_builder(em)
    audit = _make_audit(tmp_path)
    router = _make_output_router(telegram=telegram, event_logger=event_logger, event_bus=bus)
    agent = GemmaAgent(
        config=cfg,
        event_bus=bus,
        ollama_client=ollama or _make_mock_ollama(),
        context_builder=ctx,
        audit_logger=audit,
        output_router=router,
    )
    return agent, bus


# ---------------------------------------------------------------------------
# GemmaConfig
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    cfg = GemmaConfig()
    assert cfg.enabled is True
    assert cfg.alarm_min_level == "WARNING"
    assert cfg.max_concurrent_inferences == 2
    assert cfg.slice_a_notification is True
    assert cfg.slice_b_suggestion is False


def test_config_from_dict() -> None:
    raw = {
        "enabled": True,
        "ollama": {
            "base_url": "http://localhost:11434",
            "default_model": "gemma4:e4b",
            "timeout_s": 30,
        },
        "rate_limit": {"max_calls_per_hour": 60, "max_concurrent_inferences": 2},
        "triggers": {"alarm_fired": {"min_level": "WARNING"}},
        "outputs": {"telegram": True, "operator_log": True, "gui_insight_panel": True},
        "slices": {"a_notification": True, "b_suggestion": False},
        "audit": {"enabled": True, "retention_days": 90},
    }
    cfg = GemmaConfig.from_dict(raw)
    assert cfg.enabled is True
    assert cfg.default_model == "gemma4:e4b"
    assert cfg.alarm_min_level == "WARNING"
    assert cfg.max_calls_per_hour == 60


# ---------------------------------------------------------------------------
# GemmaAgent — start / stop
# ---------------------------------------------------------------------------


async def test_agent_start_subscribes_to_bus(tmp_path: Path) -> None:
    agent, bus = _make_agent(tmp_path=tmp_path)
    await agent.start()
    assert bus.subscriber_count == 1
    await agent.stop()
    assert bus.subscriber_count == 0


async def test_agent_disabled_does_not_subscribe(tmp_path: Path) -> None:
    agent, bus = _make_agent(config=_make_config(enabled=False), tmp_path=tmp_path)
    await agent.start()
    assert bus.subscriber_count == 0
    await agent.stop()


# ---------------------------------------------------------------------------
# GemmaAgent — alarm_fired → LLM → dispatch
# ---------------------------------------------------------------------------


async def test_alarm_fired_triggers_ollama_generate(tmp_path: Path) -> None:
    ollama = _make_mock_ollama()
    agent, bus = _make_agent(ollama=ollama, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_alarm_event())
    await asyncio.sleep(0.05)

    ollama.generate.assert_awaited_once()
    await agent.stop()


async def test_alarm_fired_dispatches_to_telegram(tmp_path: Path) -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    agent, bus = _make_agent(telegram=telegram, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_alarm_event())
    await asyncio.sleep(0.05)

    telegram._send_to_all.assert_awaited_once()
    sent_text = telegram._send_to_all.call_args[0][0]
    assert "🤖 Гемма:" in sent_text
    await agent.stop()


async def test_alarm_fired_dispatches_to_operator_log(tmp_path: Path) -> None:
    event_logger = AsyncMock()
    event_logger.log_event = AsyncMock()
    agent, bus = _make_agent(event_logger=event_logger, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_alarm_event())
    await asyncio.sleep(0.05)

    event_logger.log_event.assert_awaited_once()
    args = event_logger.log_event.call_args
    assert args[0][0] == "gemma"
    await agent.stop()


async def test_info_level_alarm_not_handled(tmp_path: Path) -> None:
    ollama = _make_mock_ollama()
    agent, bus = _make_agent(
        config=_make_config(alarm_min_level="WARNING"), ollama=ollama, tmp_path=tmp_path
    )
    await agent.start()

    await bus.publish(_alarm_event(level="INFO"))
    await asyncio.sleep(0.05)

    ollama.generate.assert_not_awaited()
    await agent.stop()


async def test_critical_level_alarm_is_handled(tmp_path: Path) -> None:
    ollama = _make_mock_ollama()
    agent, bus = _make_agent(ollama=ollama, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_alarm_event(level="CRITICAL"))
    await asyncio.sleep(0.05)

    ollama.generate.assert_awaited_once()
    await agent.stop()


# ---------------------------------------------------------------------------
# GemmaAgent — error resilience
# ---------------------------------------------------------------------------


async def test_ollama_unavailable_does_not_crash_agent(tmp_path: Path) -> None:
    ollama = AsyncMock()
    ollama.generate = AsyncMock(side_effect=OllamaUnavailableError("connection refused"))
    ollama.close = AsyncMock()
    agent, bus = _make_agent(ollama=ollama, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_alarm_event())
    await asyncio.sleep(0.05)

    assert agent._task is not None
    assert not agent._task.done()
    await agent.stop()


async def test_rate_limit_drops_excess_calls(tmp_path: Path) -> None:
    ollama = _make_mock_ollama()
    agent, bus = _make_agent(
        config=_make_config(max_calls_per_hour=1), ollama=ollama, tmp_path=tmp_path
    )
    await agent.start()

    await bus.publish(_alarm_event(alarm_id="a1"))
    await bus.publish(_alarm_event(alarm_id="a2"))
    await asyncio.sleep(0.1)

    assert ollama.generate.await_count == 1
    await agent.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_format_age_none() -> None:
    assert _format_age(None) == "неизвестно"


def test_format_age_seconds() -> None:
    assert _format_age(45) == "45с"


def test_format_age_minutes() -> None:
    assert _format_age(150) == "2м 30с"


def test_format_age_hours() -> None:
    assert _format_age(7260) == "2ч 1м"
