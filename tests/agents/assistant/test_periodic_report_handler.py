"""Tests for AssistantLiveAgent periodic_report_request handler (F29)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from cryodaq.agents.assistant.live.agent import (
    AssistantConfig,
    AssistantLiveAgent,
    _report_window_label,
)
from cryodaq.agents.assistant.live.context_builder import ContextBuilder, PeriodicReportContext
from cryodaq.agents.assistant.live.output_router import OutputRouter
from cryodaq.agents.assistant.live.prompts import PERIODIC_REPORT_SYSTEM, PERIODIC_REPORT_USER
from cryodaq.agents.assistant.shared.audit import AuditLogger
from cryodaq.agents.assistant.shared.ollama_client import GenerationResult
from cryodaq.agents.assistant.shared.summary_note import read_summary
from cryodaq.core.event_bus import EngineEvent, EventBus
from cryodaq.core.sensor_diagnostics import SensorDiagnosticsEngine


async def _wait_until(cond_fn, *, deadline_s: float = 1.0) -> None:
    """Deterministic wait: poll cond_fn() until True within deadline_s seconds."""
    await asyncio.wait_for(_poll_cond(cond_fn), timeout=deadline_s)


async def _poll_cond(cond_fn) -> None:
    while not cond_fn():  # noqa: ASYNC110
        await asyncio.sleep(0.005)


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
        audit_enabled=True,
        periodic_report_enabled=True,
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


def _real_critical_with_warm_reference_summary() -> object:
    engine = SensorDiagnosticsEngine()
    engine.set_channel_cold_map({"T1": True, "T16": False})
    for index in range(20):
        engine.push("T1", index * 0.5, 380.0)
        engine.push("T16", index * 0.5, 298.0)
    engine.update()
    return engine.get_summary()


def _make_agent(
    *,
    config: AssistantConfig | None = None,
    ollama=None,
    telegram=None,
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

    audit = AuditLogger(tmp_path / "audit", enabled=True)

    if telegram is None:
        telegram = AsyncMock()
        telegram._send_to_all = AsyncMock()
    router = OutputRouter(
        telegram_bot=telegram,
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
    # The bulletin reaches the operator in the hourly chart's CAPTION now, not
    # as a Telegram message of its own — sending both gave the operator the
    # agent's paragraph and then the same paragraph under the chart.
    await _wait_until(lambda: read_summary(tmp_path) != "")

    telegram._send_to_all.assert_not_awaited()
    assert read_summary(tmp_path), "the summary never reached the caption's note"
    await agent.stop()


def test_report_window_label_matches_window_minutes() -> None:
    """The dispatch label must reflect the requested window, not a hardcoded
    "за час" — with correct Russian numeral agreement."""
    from cryodaq.agents.assistant.live.agent import _report_window_label

    assert _report_window_label(60) == "за час"
    assert _report_window_label(30) == "за 30 минут"
    assert _report_window_label(45) == "за 45 минут"
    assert _report_window_label(90) == "за 90 минут"
    assert _report_window_label(120) == "за 2 часа"
    assert _report_window_label(180) == "за 3 часа"
    assert _report_window_label(300) == "за 5 часов"
    assert _report_window_label(1) == "за 1 минуту"
    assert _report_window_label(2) == "за 2 минуты"


def test_the_window_label_reflects_the_actual_window() -> None:
    """A 30-minute report must say so, not the hardcoded "за час".

    Asserted on the label function itself. It used to be read out of the
    Telegram message, and the periodic bulletin no longer sends one — it reaches
    the operator in the hourly chart's caption. The property under test never
    depended on the delivery channel.
    """
    assert _report_window_label(30) == "за 30 минут"
    assert _report_window_label(60) == "за час"
    assert _report_window_label(120) == "за 2 часа"
    assert _report_window_label(300) == "за 5 часов"
    assert _report_window_label(1) == "за 1 минуту"


async def test_an_empty_log_still_gets_a_bulletin(tmp_path: Path) -> None:
    """This test used to assert the opposite, and the opposite was wrong.

    A quiet log is not a quiet stand: nobody typing for an hour says nothing
    about whether the pressure moved. The bulletin now runs every hour and the
    agent decides what is worth saying — including that nothing is.
    """
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(
            text="Стенд держит уровень.", tokens_in=10, tokens_out=2, latency_s=1.0, model="gemma4:e2b"
        )
    )
    ollama.close = AsyncMock()
    ctx = _make_mock_context(total_event_count=0)
    agent, bus = _make_agent(ollama=ollama, telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_periodic_event())
    await _wait_until(lambda: read_summary(tmp_path) != "")

    ollama.generate.assert_awaited_once()
    telegram._send_to_all.assert_not_awaited()
    await agent.stop()


async def test_periodic_report_critical_sensor_health_is_not_idle(tmp_path: Path) -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(
            text="Проверьте датчик.", tokens_in=10, tokens_out=2, latency_s=1.0, model="gemma4:e2b"
        )
    )
    ollama.close = AsyncMock()
    ctx = _make_mock_context(total_event_count=0)
    ctx.sensor_health_summary = _real_critical_with_warm_reference_summary()
    agent, bus = _make_agent(ollama=ollama, telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_periodic_event())
    await _wait_until(lambda: read_summary(tmp_path) != "")

    ollama.generate.assert_awaited_once()
    telegram._send_to_all.assert_not_awaited()
    await agent.stop()


async def test_periodic_report_valid_dict_critical_bypasses_idle_and_dispatches(tmp_path: Path) -> None:
    """A public wire-format summary follows the same priority path as its producer object."""
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    em = MagicMock()
    em.active_experiment_id = "exp-001"
    em.get_current_phase = MagicMock(return_value="COOL")
    em.get_phase_history = MagicMock(return_value=[])
    context_builder = ContextBuilder(
        reader,
        em,
        sensor_diag_provider=lambda: {
            "total_channels": 2,
            "healthy": 0,
            "warning": 1,
            "critical": 1,
            "worst_channel": "T1",
            "worst_score": 20,
            "worst_flags": ["out_of_range"],
        },
    )
    telegram = MagicMock()
    telegram._send_to_all = AsyncMock()
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(
            text="Check sensor.", tokens_in=10, tokens_out=2, latency_s=1.0, model="gemma4:e2b"
        )
    )
    ollama.close = AsyncMock()
    agent, bus = _make_agent(ollama=ollama, telegram=telegram, tmp_path=tmp_path)
    agent._ctx_builder = context_builder
    await agent.start()

    await bus.publish(_periodic_event())
    await _wait_until(lambda: read_summary(tmp_path) != "")

    ollama.generate.assert_awaited_once()
    telegram._send_to_all.assert_not_awaited()
    await agent.stop()


async def test_periodic_report_handler_handles_empty_response(tmp_path: Path) -> None:
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock()
    ctx = _make_mock_context(total_event_count=2)
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(text="", tokens_in=10, tokens_out=0, latency_s=1.0, model="gemma4:e2b")
    )
    ollama.close = AsyncMock()
    agent, bus = _make_agent(ollama=ollama, telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()

    await bus.publish(_periodic_event())
    # generate is called but _send_to_all must NOT be; wait for handler to finish.
    await _wait_until(lambda: ollama.generate.await_count >= 1)
    await _wait_until(lambda: len(agent._handler_tasks) == 0)

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
    # disabled path skips the handler entirely; wait for handler tasks to drain.
    await _wait_until(lambda: len(agent._handler_tasks) == 0)

    telegram._send_to_all.assert_not_awaited()
    await agent.stop()


# ---------------------------------------------------------------------------
# OutputRouter prefix_suffix
# ---------------------------------------------------------------------------


def test_periodic_report_prefix_includes_suffix() -> None:
    router = OutputRouter(
        telegram_bot=None,
        event_bus=MagicMock(),
        brand_name="Гемма",
        brand_emoji="🤖",
    )
    # Verify brand_base used for suffix variant
    assert router._brand_base == "🤖 Гемма"
    # Verify standard prefix unchanged
    assert router._prefix == "🤖 Гемма:"


def test_periodic_report_prompt_does_not_hardcode_hour_window() -> None:
    """Configured non-hourly windows must not fight a hardcoded system prompt."""
    assert "последний час" not in PERIODIC_REPORT_SYSTEM
    assert "{window_minutes}" in PERIODIC_REPORT_USER


def test_periodic_report_prompt_prohibits_latex() -> None:
    """PERIODIC_REPORT_SYSTEM must explicitly forbid LaTeX (no \\r escape corruption)."""
    assert "LaTeX" in PERIODIC_REPORT_SYSTEM
    assert "$" in PERIODIC_REPORT_SYSTEM
    assert "→" in PERIODIC_REPORT_SYSTEM
    assert "\r" not in PERIODIC_REPORT_SYSTEM


async def test_periodic_report_context_read_failure_dispatches_only_deterministic_unavailable(
    tmp_path: Path,
) -> None:
    """A failed read is visible but never becomes a normal empty report."""
    telegram = MagicMock()
    telegram._send_to_all = AsyncMock()
    ctx = _make_mock_context(total_event_count=0)
    ctx.context_read_failed = True
    ollama = AsyncMock()
    ollama.generate = AsyncMock(
        return_value=GenerationResult(
            text="Нет событий.", tokens_in=10, tokens_out=2, latency_s=1.0, model="gemma4:e2b"
        )
    )
    ollama.close = AsyncMock()
    agent, bus = _make_agent(ollama=ollama, telegram=telegram, context=ctx, tmp_path=tmp_path)
    await agent.start()
    await bus.publish(_periodic_event())
    await _wait_until(lambda: telegram._send_to_all.await_count >= 1)
    telegram._send_to_all.assert_awaited_once()
    ollama.generate.assert_not_awaited()
    assert "не сформирован" in telegram._send_to_all.call_args.args[0]
    await agent.stop()


async def test_periodic_report_missing_log_capability_uses_deterministic_unavailable_fallback(
    tmp_path: Path,
) -> None:
    """Missing log capability preserves no-Ollama and audit-backed fallback behavior."""
    telegram = MagicMock()
    telegram._send_to_all = AsyncMock()
    ollama = AsyncMock()
    ollama.generate = AsyncMock()
    ollama.close = AsyncMock()
    agent, bus = _make_agent(ollama=ollama, telegram=telegram, tmp_path=tmp_path)
    em = MagicMock()
    em.active_experiment_id = None
    agent._ctx_builder = ContextBuilder(object(), em)
    await agent.start()

    await bus.publish(_periodic_event())
    await _wait_until(lambda: telegram._send_to_all.await_count >= 1)

    ollama.generate.assert_not_awaited()
    audit_files = list((tmp_path / "audit").rglob("*.json"))
    assert len(audit_files) == 1
    assert "не сформирован" in telegram._send_to_all.call_args.args[0]
    await agent.stop()


async def test_periodic_report_missing_diagnostics_provider_uses_deterministic_unavailable_fallback(
    tmp_path: Path,
) -> None:
    """Missing diagnostics is unavailable evidence, never an idle empty window."""
    telegram = MagicMock()
    telegram._send_to_all = AsyncMock()
    ollama = AsyncMock()
    ollama.generate = AsyncMock()
    ollama.close = AsyncMock()
    agent, bus = _make_agent(ollama=ollama, telegram=telegram, tmp_path=tmp_path)
    reader = MagicMock()
    reader.get_operator_log = AsyncMock(return_value=[])
    em = MagicMock()
    em.active_experiment_id = None
    agent._ctx_builder = ContextBuilder(reader, em)
    await agent.start()

    await bus.publish(_periodic_event())
    await _wait_until(lambda: telegram._send_to_all.await_count >= 1)

    ollama.generate.assert_not_awaited()
    audit_files = list((tmp_path / "audit").rglob("*.json"))
    assert len(audit_files) == 1
    assert "не сформирован" in telegram._send_to_all.call_args.args[0]
    await agent.stop()
