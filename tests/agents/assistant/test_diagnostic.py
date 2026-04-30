"""Tests for GemmaAgent Slice B — diagnostic suggestion flow."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.live.agent import GemmaAgent, GemmaConfig
from cryodaq.agents.assistant.live.context_builder import ContextBuilder
from cryodaq.agents.assistant.live.output_router import OutputRouter
from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant.shared.ollama_client import GenerationResult
from cryodaq.core.event_bus import EngineEvent, EventBus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _alarm_event(experiment_id: str = "exp-001") -> EngineEvent:
    return EngineEvent(
        event_type="alarm_fired",
        timestamp=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        payload={
            "alarm_id": "test_alarm",
            "level": "WARNING",
            "channels": ["T1", "T2"],
            "values": {"T1": 8.5, "T2": 9.1},
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
        slice_b_suggestion=True,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _two_call_ollama(summary_text: str, diag_text: str) -> MagicMock:
    """Ollama mock that returns summary on 1st call, diagnostic on 2nd."""
    responses = iter([
        GenerationResult(text=summary_text, tokens_in=80, tokens_out=30,
                         latency_s=2.0, model="gemma4:e4b"),
        GenerationResult(text=diag_text, tokens_in=120, tokens_out=40,
                         latency_s=2.5, model="gemma4:e4b"),
    ])
    ollama = AsyncMock()
    ollama.generate = AsyncMock(side_effect=lambda *a, **kw: next(responses))
    ollama.close = AsyncMock()
    return ollama


def _make_mock_em() -> MagicMock:
    em = MagicMock()
    em.active_experiment_id = "exp-001"
    em.get_current_phase = MagicMock(return_value="COOL")
    em.get_phase_history = MagicMock(return_value=[])
    return em


def _make_agent(
    *,
    config: GemmaConfig | None = None,
    ollama=None,
    telegram=None,
    event_logger=None,
    reader=None,
    tmp_path: Path,
) -> tuple[GemmaAgent, EventBus]:
    bus = EventBus()
    cfg = config or _make_config()
    em = _make_mock_em()

    if reader is None:
        reader = MagicMock()
        reader.read_readings_history = AsyncMock(return_value={})

    ctx = ContextBuilder(reader, em)
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
    agent = GemmaAgent(
        config=cfg,
        event_bus=bus,
        ollama_client=ollama or _two_call_ollama("Аларм summary.", "Диагноз: проверьте."),
        context_builder=ctx,
        audit_logger=audit,
        output_router=router,
    )
    return agent, bus


# ---------------------------------------------------------------------------
# Diagnostic suggestion — two-call flow
# ---------------------------------------------------------------------------


async def test_diagnostic_suggestion_runs_after_alarm_summary(tmp_path: Path) -> None:
    """slice_b_suggestion=True triggers 2 LLM calls: summary then diagnostic."""
    ollama = _two_call_ollama(
        "Аларм: температура T1 выше нормы.",
        "Диагноз: 1. Проверьте контакты T1. 2. Сравните с T2.",
    )
    agent, bus = _make_agent(ollama=ollama, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_alarm_event())
    await asyncio.sleep(0.15)

    assert ollama.generate.await_count == 2
    calls = ollama.generate.call_args_list
    # First call uses alarm summary system prompt
    first_system = calls[0][1].get("system", "")
    assert "аларм" in first_system.lower() or "аларма" in first_system.lower()
    # Second call uses diagnostic system prompt
    second_system = calls[1][1].get("system", "")
    assert "диагност" in second_system.lower()
    await agent.stop()


async def test_diagnostic_slice_b_disabled_makes_only_one_call(tmp_path: Path) -> None:
    """slice_b_suggestion=False → only summary call, no diagnostic."""
    ollama = _two_call_ollama("Аларм summary.", "Диагноз.")
    agent, bus = _make_agent(
        config=_make_config(slice_b_suggestion=False),
        ollama=ollama,
        tmp_path=tmp_path,
    )
    await agent.start()

    await bus.publish(_alarm_event())
    await asyncio.sleep(0.1)

    assert ollama.generate.await_count == 1
    await agent.stop()


async def test_diagnostic_skipped_for_finalize(tmp_path: Path) -> None:
    """experiment_finalize does not trigger diagnostic suggestion."""
    ollama = _two_call_ollama("Резюме эксперимента.", "Диагноз.")
    agent, bus = _make_agent(
        config=_make_config(experiment_finalize_enabled=True),
        ollama=ollama,
        tmp_path=tmp_path,
    )
    await agent.start()

    event = EngineEvent(
        event_type="experiment_finalize",
        timestamp=datetime(2026, 5, 1, 14, 0, 0, tzinfo=UTC),
        payload={"action": "experiment_finalize", "experiment": {}},
        experiment_id="exp-001",
    )
    await bus.publish(event)
    await asyncio.sleep(0.1)

    # Only 1 call — no diagnostic for finalize
    assert ollama.generate.await_count == 1
    await agent.stop()


async def test_diagnostic_handles_missing_history_gracefully(tmp_path: Path) -> None:
    """SQLite reader failure → diagnostic still runs with 'нет данных' fallback."""
    failing_reader = MagicMock()
    failing_reader.read_readings_history = AsyncMock(side_effect=Exception("DB error"))

    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    ollama = _two_call_ollama("Аларм summary.", "Диагноз: недостаточно данных.")
    agent, bus = _make_agent(
        ollama=ollama,
        telegram=telegram,
        reader=failing_reader,
        tmp_path=tmp_path,
    )
    await agent.start()

    await bus.publish(_alarm_event())
    await asyncio.sleep(0.15)

    # Both LLM calls still happen despite DB error
    assert ollama.generate.await_count == 2
    # Both dispatched to Telegram
    assert telegram._send_to_all.await_count == 2
    await agent.stop()


async def test_diagnostic_skipped_on_truncated_summary(tmp_path: Path) -> None:
    """Truncated summary (partial text) must not trigger diagnostic call."""
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(
            text="partial...",
            tokens_in=50,
            tokens_out=10,
            latency_s=30.0,
            model="gemma4:e4b",
            truncated=True,
        )
    )
    ollama.close = AsyncMock()
    agent, bus = _make_agent(ollama=ollama, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_alarm_event())
    await asyncio.sleep(0.1)

    # Only 1 attempt — truncated summary suppresses diagnostic
    assert ollama.generate.await_count == 1
    await agent.stop()


async def test_diagnostic_counts_toward_rate_limit(tmp_path: Path) -> None:
    """Each diagnostic call records a timestamp — both count toward hourly budget."""
    ollama = _two_call_ollama("Summary.", "Диагноз.")
    agent, bus = _make_agent(
        config=_make_config(max_calls_per_hour=60),
        ollama=ollama,
        tmp_path=tmp_path,
    )
    await agent.start()

    before = len(agent._call_timestamps)
    await bus.publish(_alarm_event())
    await asyncio.sleep(0.15)

    # summary + diagnostic = 2 timestamps recorded
    assert len(agent._call_timestamps) - before == 2
    await agent.stop()


async def test_diagnostic_prompt_contains_alarm_values(tmp_path: Path) -> None:
    """Diagnostic prompt is built with alarm channel values from payload."""
    ollama = _two_call_ollama("Аларм summary.", "Диагноз.")
    agent, bus = _make_agent(ollama=ollama, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_alarm_event())
    await asyncio.sleep(0.15)

    assert ollama.generate.await_count == 2
    diag_prompt = ollama.generate.call_args_list[1][0][0]
    # Alarm values must appear in diagnostic user prompt
    assert "T1" in diag_prompt
    assert "8.5" in diag_prompt
    await agent.stop()
