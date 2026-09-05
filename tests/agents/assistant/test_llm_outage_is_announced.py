"""An unreachable model must reach the operator, not just the log.

Until 2026-09-05 the assistant's model ran on loopback and could not be
unreachable, so `OllamaUnavailableError` was answered with a single
`logger.warning` and nothing else. Inference now runs on the owner's server
over a NetBird overlay, behind a firewall rule that Amnezia rebuilds away on
reconnect, relayed through Frankfurt. "Unreachable" became a real state that
can last hours.

The failure that produces is silence: the hourly report simply does not
arrive, with the reason only in `logs/assistant.log`. The operator has said
plainly that they read the Telegram reports and not the logs, so silence is the
worst available behaviour.

Announced once per outage, deterministically — the notification cannot use the
model it is reporting unreachable — and re-armed on recovery so a second outage
is announced again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from cryodaq.agents.assistant.shared.ollama_client import OllamaUnavailableError
from cryodaq.core.event_bus import EngineEvent


def _event() -> EngineEvent:
    return EngineEvent(
        event_type="periodic_report_request",
        timestamp=datetime.now(UTC),
        payload={"window_minutes": 60},
    )


class _Agent:
    """The announcement logic, exercised through the real methods.

    Constructed without __init__ so the test does not have to stand up an
    Ollama client, an audit logger and a context builder to check a branch —
    the same double style `test_shutdown_settlement` uses.
    """

    def __init__(self) -> None:
        from cryodaq.agents.assistant.live.agent import AssistantLiveAgent

        self.agent = object.__new__(AssistantLiveAgent)
        self.agent._llm_unavailable_announced = False
        self.agent._dispatch_unavailable_context = AsyncMock()
        self.agent._audit = type("A", (), {"make_audit_id": staticmethod(lambda: "audit-1")})()


@pytest.mark.asyncio
async def test_an_outage_is_announced_to_the_operator() -> None:
    a = _Agent()
    await a.agent._announce_llm_unavailable(_event(), OllamaUnavailableError("connection refused"))

    a.agent._dispatch_unavailable_context.assert_awaited_once()
    kwargs = a.agent._dispatch_unavailable_context.await_args.kwargs
    assert kwargs["kind"] == "llm_unavailable"
    # The operator must learn three things: narration stopped, acquisition did
    # not, and why.
    assert "модель недоступна" in kwargs["message"]
    assert "Сбор и запись данных продолжаются" in kwargs["message"]
    assert "connection refused" in kwargs["message"]


@pytest.mark.asyncio
async def test_a_long_outage_announces_once_not_once_per_event() -> None:
    """One outage, one message — otherwise a notification stops being read."""

    a = _Agent()
    for _ in range(5):
        await a.agent._announce_llm_unavailable(_event(), OllamaUnavailableError("refused"))

    assert a.agent._dispatch_unavailable_context.await_count == 1


@pytest.mark.asyncio
async def test_recovery_re_arms_the_announcement() -> None:
    """A second, later outage must be announced again, not swallowed."""

    a = _Agent()
    await a.agent._announce_llm_unavailable(_event(), OllamaUnavailableError("refused"))
    assert a.agent._dispatch_unavailable_context.await_count == 1

    a.agent._llm_unavailable_announced = False  # what a successful handler does

    await a.agent._announce_llm_unavailable(_event(), OllamaUnavailableError("refused again"))
    assert a.agent._dispatch_unavailable_context.await_count == 2


@pytest.mark.asyncio
async def test_a_failing_notification_never_masks_the_outage() -> None:
    """If telling the operator fails, that must not raise into the handler."""

    a = _Agent()
    a.agent._dispatch_unavailable_context = AsyncMock(side_effect=RuntimeError("telegram down"))

    await a.agent._announce_llm_unavailable(_event(), OllamaUnavailableError("refused"))
    assert a.agent._llm_unavailable_announced is True


def test_the_announcement_path_makes_no_inference_call() -> None:
    """The point of the deterministic path: it cannot need what just failed."""

    import inspect

    from cryodaq.agents.assistant.live.agent import AssistantLiveAgent

    src = inspect.getsource(AssistantLiveAgent._announce_llm_unavailable)
    assert "_dispatch_unavailable_context" in src
    for forbidden in ("self._ollama", ".generate(", "_format_model"):
        assert forbidden not in src, f"announcement must not call the model: {forbidden}"
