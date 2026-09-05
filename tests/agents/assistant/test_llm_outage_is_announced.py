"""An unreachable model must reach the operator — and only if it truly did.

Inference runs on the owner's server over a NetBird overlay, so "unreachable"
is a real state that can last hours, and the failure it produces is silence:
the hourly report simply does not arrive, with the reason only in
`logs/assistant.log`. The operator reads Telegram, not the logs.

Rewritten 2026-09-05 after review, because the previous version of this file
tested the announcement with `_dispatch_unavailable_context` replaced by an
AsyncMock. That never exercised the delivery path, which is precisely where
both defects lived — and one test here actively PINNED one of them, asserting
that a notification which failed to send still counts as announced.

These tests build a real AssistantLiveAgent with a real OutputRouter and a real
AuditLogger, mocking only the transport, so "delivered" means the router said
so.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from cryodaq.agents.assistant.shared.ollama_client import (
    OllamaUnavailableError,
)
from cryodaq.core.event_bus import EngineEvent
from tests.agents.assistant.test_alarm_flow import _make_agent, _make_config


def _event() -> EngineEvent:
    return EngineEvent(
        event_type="periodic_report_request",
        timestamp=datetime.now(UTC),
        payload={"window_minutes": 60},
    )


def _working_telegram() -> AsyncMock:
    """A transport that actually reports delivery.

    OutputRouter treats anything that is not ``True`` or a dict of per-chat
    states as a failed send, so a bare AsyncMock (which returns a MagicMock)
    reads as undelivered. That is correct of the router and a trap for tests.
    """
    telegram = AsyncMock()
    telegram._send_to_all = AsyncMock(return_value=True)
    return telegram


def _agent(tmp_path: Path, telegram=None):
    cfg = _make_config()
    cfg.output_telegram = True
    cfg.output_gui_insight = False
    agent, _bus = _make_agent(config=cfg, telegram=telegram or _working_telegram(), tmp_path=tmp_path)
    return agent


# ---------------------------------------------------------------------------
# The announcement reaches the operator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_outage_is_announced_to_the_operator(tmp_path: Path) -> None:
    telegram = _working_telegram()
    agent = _agent(tmp_path, telegram=telegram)

    await agent._announce_llm_unavailable(_event(), OllamaUnavailableError("connection refused"))

    assert telegram.method_calls or telegram.await_args_list, "nothing was sent"
    sent = " ".join(str(c) for c in telegram.mock_calls)
    assert "модель недоступна" in sent
    assert "connection refused" in sent


@pytest.mark.asyncio
async def test_the_announcement_does_not_certify_acquisition_and_recording(
    tmp_path: Path,
) -> None:
    """Removed 2026-09-05 after review.

    The message used to assure the operator that "сбор и запись данных
    продолжаются в обычном режиме". The model being unreachable establishes
    nothing whatever about the health of the engine's sampling and writing, and
    this text is read at the exact moment someone is deciding whether to trust
    the stand. CryoDAQ informs; it does not certify services it cannot see.
    """
    telegram = _working_telegram()
    agent = _agent(tmp_path, telegram=telegram)

    await agent._announce_llm_unavailable(_event(), OllamaUnavailableError("refused"))

    sent = " ".join(str(c) for c in telegram.mock_calls)
    assert "Сбор и запись данных продолжаются" not in sent
    assert "продолжаются в обычном режиме" not in sent


@pytest.mark.asyncio
async def test_a_long_outage_announces_once_not_once_per_event(
    tmp_path: Path,
) -> None:
    telegram = _working_telegram()
    agent = _agent(tmp_path, telegram=telegram)

    for _ in range(5):
        await agent._announce_llm_unavailable(_event(), OllamaUnavailableError("refused"))

    sends = [c for c in telegram.mock_calls if "модель недоступна" in str(c)]
    assert len(sends) == 1, f"announced {len(sends)} times"


# ---------------------------------------------------------------------------
# An attempt is not a delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_failed_send_does_not_spend_the_one_shot(tmp_path: Path) -> None:
    """Reversed 2026-09-05 after review.

    This test previously asserted `_llm_unavailable_announced is True` after
    the notification raised — it pinned the defect. Review exercised the real
    dispatch path with audit preparation failing: no transport send happened,
    but the next outage event announced nothing, because an ATTEMPT had been
    recorded as a DELIVERY. A one-shot warning that can be silently spent is
    worse than none, because nobody is waiting for a message they were never
    told to expect.
    """
    telegram = _working_telegram()
    telegram._send_to_all = AsyncMock(side_effect=RuntimeError("telegram down"))
    agent = _agent(tmp_path, telegram=telegram)

    # Must not raise into the handler...
    await agent._announce_llm_unavailable(_event(), OllamaUnavailableError("refused"))

    # ...and must not be marked as told.
    assert agent._llm_unavailable_announced is False, (
        "a notification that never reached the operator was recorded as delivered"
    )


@pytest.mark.asyncio
async def test_the_retry_happens_on_the_next_outage_event(tmp_path: Path) -> None:
    """Leaving the one-shot un-spent is only useful if it is actually retried."""
    telegram = _working_telegram()
    telegram._send_to_all = AsyncMock(side_effect=RuntimeError("telegram down"))
    agent = _agent(tmp_path, telegram=telegram)

    await agent._announce_llm_unavailable(_event(), OllamaUnavailableError("refused"))
    assert agent._llm_unavailable_announced is False

    # Transport comes back; the next outage event must try again.
    telegram._send_to_all = AsyncMock(return_value=True)
    await agent._announce_llm_unavailable(_event(), OllamaUnavailableError("refused"))

    assert agent._llm_unavailable_announced is True


# ---------------------------------------------------------------------------
# A handler returning is not a recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_requires_the_model_to_have_actually_answered(
    tmp_path: Path,
) -> None:
    """Reproduces the review finding directly.

    `_handle_periodic_report` returns early when its context is unavailable and
    never reaches the model. The outage flag used to clear on any handler
    returning, so the agent announced recovery after zero generation calls.
    """
    agent = _agent(tmp_path)
    agent._llm_unavailable_announced = True

    # A handler that returns without ever calling the model.
    async def _returns_without_inference(event, **kwargs):
        return None

    agent._handle_periodic_report = _returns_without_inference

    await agent._safe_handle(_event())

    assert agent._llm_unavailable_announced is True, "recovery was announced although the model was never called"
    assert agent._ollama.generate.await_count == 0


@pytest.mark.asyncio
async def test_a_real_answer_does_clear_the_outage(tmp_path: Path) -> None:
    """The counterpart: genuine inference must still re-arm the announcement."""
    agent = _agent(tmp_path)
    agent._llm_unavailable_announced = True

    async def _actually_infers(event, **kwargs):
        await agent._generate_tracked(system_prompt="", user_prompt="x", model="test-model")

    agent._handle_periodic_report = _actually_infers

    await agent._safe_handle(_event())

    assert agent._llm_unavailable_announced is False
    assert agent._inference_answered is True


@pytest.mark.asyncio
async def test_the_announcement_path_makes_no_inference_call(
    tmp_path: Path,
) -> None:
    """Behavioural now, not a source-string scan.

    The point of the deterministic path is that it cannot need the thing that
    just failed. The old version of this test read the method's source with
    `inspect.getsource` and grepped it, which would pass for any refactor that
    moved the call one frame away.
    """
    agent = _agent(tmp_path)

    await agent._announce_llm_unavailable(_event(), OllamaUnavailableError("refused"))

    assert agent._ollama.generate.await_count == 0


@pytest.mark.asyncio
async def test_concurrent_outage_events_announce_once(tmp_path: Path) -> None:
    """The in-flight guard must hold when two events race."""
    telegram = _working_telegram()
    agent = _agent(tmp_path, telegram=telegram)

    await asyncio.gather(
        agent._announce_llm_unavailable(_event(), OllamaUnavailableError("a")),
        agent._announce_llm_unavailable(_event(), OllamaUnavailableError("b")),
    )

    sends = [c for c in telegram.mock_calls if "модель недоступна" in str(c)]
    assert len(sends) == 1, f"announced {len(sends)} times"
