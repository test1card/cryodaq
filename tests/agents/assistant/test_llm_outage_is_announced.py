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
    GenerationResult,
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


def _agent(tmp_path: Path, telegram=None, max_concurrent: int = 1):
    cfg = _make_config()
    cfg.output_telegram = True
    cfg.output_gui_insight = False
    # The shared helper pins this to 1, but the semaphore wraps the WHOLE
    # handler, so a test that holds one handler open while running another
    # deadlocks at 1. Production defaults to 2, which is the concurrency the
    # interleaving defect needs.
    cfg.max_concurrent_inferences = max_concurrent
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


# ---------------------------------------------------------------------------
# The three interactions review reproduced in 599a2f69. Ordinary success and
# failure were already covered; these were not.
# ---------------------------------------------------------------------------


def _timeout_result() -> GenerationResult:
    """Exactly what OllamaClient.generate() returns on timeout.

    It does not raise. Empty text, no tokens, truncated=True — which is why
    "a result came back" was never evidence that the model answered.
    """
    return GenerationResult(
        text="",
        tokens_in=0,
        tokens_out=0,
        latency_s=280.0,
        model="qwen3.8:27b",
        truncated=True,
    )


@pytest.mark.asyncio
async def test_a_generation_timeout_is_not_a_recovery(tmp_path: Path) -> None:
    """Review passed this production timeout result through the real handler
    and watched the outage flag clear."""
    agent = _agent(tmp_path)
    agent._llm_unavailable_announced = True
    agent._ollama.generate = AsyncMock(return_value=_timeout_result())

    async def _times_out(event, **kwargs):
        await agent._generate_tracked(system_prompt="", user_prompt="x", model="qwen3.8:27b")

    agent._handle_periodic_report = _times_out

    await agent._safe_handle(_event())

    assert agent._llm_unavailable_announced is True, "a timed-out generation was treated as the model answering again"


@pytest.mark.asyncio
async def test_a_concurrent_handler_cannot_erase_another_s_answer(tmp_path: Path) -> None:
    """Two handlers interleaved as review had them.

    A generates successfully, then waits in audit settlement. B resets the
    marker and takes the no-inference path. A must still see its OWN answer.
    """
    agent = _agent(tmp_path, max_concurrent=2)
    agent._llm_unavailable_announced = True

    a_generated = asyncio.Event()
    b_finished = asyncio.Event()

    async def _handler_a(event, **kwargs):
        await agent._generate_tracked(system_prompt="", user_prompt="a", model="test-model")
        a_generated.set()
        await b_finished.wait()  # stands in for the audit settlement wait

    async def _handler_b(event, **kwargs):
        return None  # the real periodic-report early return: no inference

    agent._handle_periodic_report = _handler_a
    task_a = asyncio.create_task(agent._safe_handle(_event()))
    await asyncio.wait_for(a_generated.wait(), timeout=2.0)

    agent._handle_periodic_report = _handler_b
    await agent._safe_handle(_event())
    b_finished.set()
    await asyncio.wait_for(task_a, timeout=2.0)

    assert agent._llm_unavailable_announced is False, (
        "handler A generated successfully, but a concurrent handler's reset erased the marker before A could act on it"
    )


@pytest.mark.asyncio
async def test_cancellation_after_delivery_keeps_the_delivery(tmp_path: Path) -> None:
    """Review cancelled during audit completion, AFTER the router reported a
    successful Telegram send. The warning was then sent a second time."""
    telegram = _working_telegram()
    agent = _agent(tmp_path, telegram=telegram)

    hung = asyncio.Event()

    async def _hang_after_delivery(*args, **kwargs):
        hung.set()
        await asyncio.Event().wait()  # never completes; the task is cancelled

    agent._audit.complete = _hang_after_delivery

    task = asyncio.create_task(agent._announce_llm_unavailable(_event(), OllamaUnavailableError("refused")))
    await asyncio.wait_for(hung.wait(), timeout=2.0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    sends = [c for c in telegram.mock_calls if "модель недоступна" in str(c)]
    assert sends, "the router never actually delivered; the test would prove nothing"
    assert agent._llm_unavailable_announced is True, (
        "the operator was told, but cancellation lost the record — the next "
        "outage repeats a warning they have already read"
    )


# ---------------------------------------------------------------------------
# Both orderings, driven through the real handlers. NOTHING below assigns
# _llm_unavailable_announced: review of 2026-09-06 showed the previous version
# of the first test set it by hand while delivery was blocked, which supplies
# exactly the condition production lacks. The outage must be created the way
# production creates one — by the model failing.
# ---------------------------------------------------------------------------


def _blocking_telegram() -> tuple[AsyncMock, asyncio.Event, list]:
    release = asyncio.Event()
    sent: list = []

    async def _slow(text):
        sent.append(text)
        await release.wait()
        return True

    tg = AsyncMock()
    tg._send_to_all = AsyncMock(side_effect=_slow)
    return tg, release, sent


async def _fail_once_then(agent, exc, handler):
    """Install a handler whose inference raises, i.e. a real outage."""
    agent._ollama.generate = AsyncMock(side_effect=exc)
    agent._handle_periodic_report = handler


@pytest.mark.asyncio
async def test_a_success_during_delivery_invalidates_the_in_flight_warning(
    tmp_path: Path,
) -> None:
    """Review's reproduction, without seeding the flag.

    1. the model fails; its warning starts sending and blocks
    2. another inference genuinely succeeds
    3. the old warning lands and must NOT mark the outage announced
    4. the model fails again -> that outage must reach the operator
    """
    tg, release, sent = _blocking_telegram()
    agent = _agent(tmp_path, telegram=tg, max_concurrent=2)

    async def _fails(event, **kwargs):
        await agent._generate_tracked(system_prompt="", user_prompt="x", model="m")

    await _fail_once_then(agent, OllamaUnavailableError("refused"), _fails)

    warn = asyncio.create_task(agent._safe_handle(_event()))
    for _ in range(400):
        if sent:
            break
        await asyncio.sleep(0.001)
    assert sent, "the warning never reached the transport"
    assert agent._llm_unavailable_announced is False, "precondition: not yet delivered"

    # 2. a genuine successful inference, observed while delivery is blocked
    agent._ollama.generate = AsyncMock(
        return_value=GenerationResult(text="ответ", tokens_in=5, tokens_out=7, latency_s=1.0, model="m")
    )
    await agent._generate_tracked(system_prompt="", user_prompt="y", model="m")

    # 3. the old warning finally lands
    release.set()
    await asyncio.wait_for(warn, timeout=2.0)
    assert agent._llm_unavailable_announced is False, (
        "a warning about an outage that has since ended marked the state announced"
    )

    # 4. a new outage must be announced
    tg._send_to_all = AsyncMock(return_value=True)
    await _fail_once_then(agent, OllamaUnavailableError("again"), _fails)
    await agent._safe_handle(_event())
    assert agent._llm_unavailable_announced is True, "the new outage reached nobody"


@pytest.mark.asyncio
async def test_an_older_success_cannot_clear_a_newer_outage(tmp_path: Path) -> None:
    """The inverse ordering review also exercised.

    1. an inference succeeds; its handler then waits in settlement
    2. a LATER inference fails and its warning is delivered
    3. the older handler finishes and must not clear that newer outage
    """
    tg = _working_telegram()
    agent = _agent(tmp_path, telegram=tg, max_concurrent=2)

    held = asyncio.Event()
    proceed = asyncio.Event()

    agent._ollama.generate = AsyncMock(
        return_value=GenerationResult(text="ответ", tokens_in=5, tokens_out=7, latency_s=1.0, model="m")
    )

    async def _succeeds_then_waits(event, **kwargs):
        await agent._generate_tracked(system_prompt="", user_prompt="a", model="m")
        held.set()
        await proceed.wait()

    agent._handle_periodic_report = _succeeds_then_waits
    older = asyncio.create_task(agent._safe_handle(_event()))
    await asyncio.wait_for(held.wait(), timeout=2.0)

    # 2. a later, genuine outage
    async def _fails(event, **kwargs):
        await agent._generate_tracked(system_prompt="", user_prompt="b", model="m")

    await _fail_once_then(agent, OllamaUnavailableError("refused"), _fails)
    await agent._safe_handle(_event())
    assert agent._llm_unavailable_announced is True, "precondition: the outage was announced"

    # 3. the older successful handler finishes
    proceed.set()
    await asyncio.wait_for(older, timeout=2.0)

    assert agent._llm_unavailable_announced is True, (
        "an inference observed BEFORE this outage began cleared it on handler return"
    )
