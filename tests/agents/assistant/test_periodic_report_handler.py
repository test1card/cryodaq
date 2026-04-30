"""Tests for AssistantLiveAgent periodic_report_request handler (F29)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.live.agent import AssistantConfig, AssistantLiveAgent
from cryodaq.agents.assistant.live.context_builder import ContextBuilder, PeriodicReportContext
from cryodaq.agents.assistant.live.output_router import OutputRouter
from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant.shared.ollama_client import GenerationResult
from cryodaq.core.event_bus import EngineEvent, EventBus


def _periodic_event(window_minutes: int = 60) -> EngineEvent:
    return EngineEvent(
        event_type="periodic_report_request",
        timestamp=datetime(2026, 5, 1, 13, 0, 0, tzinfo=UTC),
        payload={"window_minutes": window_minutes, "trigger": "scheduled"},
        experiment_id="exp-001",
    )


def _make_config(**overrides) -> AssistantConfig:
    cfg = AssistantConfig(
        enabled=True,
        max_concurrent_inferences=1,
        max_calls_per_hour=60,
        output_telegram=True,
        output_operator_log=True,
        output_gui_insight=False,
        audit_enabled=False,
        periodic_report_enabled=True,
        periodic_report_min_events=1,
        periodic_report_skip_if_idle=True,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_mock_context(total_event_count: int = 3) -> PeriodicReportContext:
    ctx = PeriodicReportContext(
        window_minutes=60,
        active_experiment_id="exp-001",
        active_experiment_phase="COOL",
        total_event_count=total_event_count,
    )
    return ctx


def _make_agent(
    *,
    config: AssistantConfig | None = None,
    ollama=None,
    telegram=None,
    event_logger=None,
    context: PeriodicReportContext | None = None,
    tmp_path: Path,
) -> tuple[AssistantLiveAgent, EventBus]:
    bus = EventBus()
    cfg = config or _make_config()
    em = MagicMock()
    em.active_experiment_id = "exp-001"
    em.get_current_phase = MagicMock(return_value="COOL")
    em.get_phase_history = MagicMock(return_value=[])

    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    ctx_builder = ContextBuilder(reader, em)

    if context is not None:
        ctx_builder.build_periodic_report_context = AsyncMock(return_value=context)

    audit = AuditLogger(tmp_path / "audit", enabled=False)

    if telegram is None:
        telegram = AsyncMock()
        telegram._send_to_all = AsyncMock()
    if event_logger is None:
        event_logger = AsyncMock()
        event_logger.log_event = AsyncMock()

    router = OutputRouter(
        telegram_bot=telegram,
        event_logger=event_logger,
        event_bus=bus,
    )

    if ollama is None:
        ollama = AsyncMock()
        ollama.generate = AsyncMock(
            return_value=GenerationResult(
                text="Всё стабильно. Активный эксперимент в фазе охлаждения.",
                tokens_in=50,
                tokens_out=20,
                latency_s=2.0,
                model="gemma4:e2b",
            )
        )
        ollama.close = AsyncMock()

    agent = AssistantLiveAgent(
        config=cfg,
        event_bus=bus,
        ollama_client=ollama,
        context_builder=ctx_builder,
        audit_logger=audit,
        output_router=router,
    )
    return agent, bus


# ---------------------------------------------------------------------------
# Handler dispatch
# ---------------------------------------------------------------------------


async def test_periodic_report_handler_dispatches_when_active(tmp_path: Path) -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    ctx = _make_mock_context(total_event_count=3)
    agent, bus = _make_agent(telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_periodic_event())
    await asyncio.sleep(0.1)

    telegram._send_to_all.assert_awaited_once()
    sent = telegram._send_to_all.call_args[0][0]
    assert "🤖 Гемма (отчёт за час):" in sent
    await agent.stop()


async def test_periodic_report_handler_skips_when_idle(tmp_path: Path) -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    # total_event_count=0 < min_events=1 → idle skip
    ctx = _make_mock_context(total_event_count=0)
    agent, bus = _make_agent(telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_periodic_event())
    await asyncio.sleep(0.1)

    telegram._send_to_all.assert_not_awaited()
    await agent.stop()


async def test_periodic_report_skip_if_idle_false_dispatches_always(tmp_path: Path) -> None:
    """skip_if_idle=False → dispatch even when no events."""
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    ctx = _make_mock_context(total_event_count=0)
    cfg = _make_config(periodic_report_skip_if_idle=False)
    agent, bus = _make_agent(config=cfg, telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_periodic_event())
    await asyncio.sleep(0.1)

    telegram._send_to_all.assert_awaited_once()
    await agent.stop()


async def test_periodic_report_handler_handles_empty_response(tmp_path: Path) -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    ctx = _make_mock_context(total_event_count=2)
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(
            text="", tokens_in=10, tokens_out=0, latency_s=1.0, model="gemma4:e2b"
        )
    )
    ollama.close = AsyncMock()
    agent, bus = _make_agent(
        ollama=ollama, telegram=telegram, context=ctx, tmp_path=tmp_path
    )
    await agent.start()

    await bus.publish(_periodic_event())
    await asyncio.sleep(0.1)

    telegram._send_to_all.assert_not_awaited()
    await agent.stop()


async def test_periodic_report_disabled_does_not_handle(tmp_path: Path) -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    cfg = _make_config(periodic_report_enabled=False)
    ctx = _make_mock_context(total_event_count=5)
    agent, bus = _make_agent(config=cfg, telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_periodic_event())
    await asyncio.sleep(0.05)

    telegram._send_to_all.assert_not_awaited()
    await agent.stop()


# ---------------------------------------------------------------------------
# OutputRouter prefix_suffix
# ---------------------------------------------------------------------------


def test_periodic_report_prefix_includes_suffix() -> None:
    router = OutputRouter(
        telegram_bot=None,
        event_logger=MagicMock(),
        event_bus=MagicMock(),
        brand_name="Гемма",
        brand_emoji="🤖",
    )
    # Verify brand_base used for suffix variant
    assert router._brand_base == "🤖 Гемма"
    # Verify standard prefix unchanged
    assert router._prefix == "🤖 Гемма:"
