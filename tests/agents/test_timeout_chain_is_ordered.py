"""Nested timeouts must be ordered innermost-shortest.

The assistant wraps one Telegram question in four deadlines:

    ZMQ transport (HANDLER_TIMEOUT_LLM_S)
      > handler budget (intent + format + retrieval)
        > format stage (query.format_timeout_s)
          > HTTP client (agent.ollama.timeout_s)

On 2026-09-05 the model moved from a 2.6B local one to qwen3.8:27b and only the
outer budgets were re-tuned. `ollama.timeout_s` stayed at 120 s — sized for the
old model — so it fired first on the first real question after the deploy. The
client returned an empty truncated result, the query agent fell back, and the
operator was told "Произошла внутренняя ошибка" for a question the model was
still answering.

The failure was not that a timeout was too short in isolation. It was that the
INNERMOST bound became the smallest by accident, so the outer budgets could
never be reached and the generous 300 s format allowance was unreachable.

This pins the ordering, not the numbers: raise or lower them freely, but the
inner bound must stay under the stage that wraps it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]


def _agent_config() -> dict:
    return yaml.safe_load((_ROOT / "config" / "agent.yaml").read_text(encoding="utf-8"))["agent"]


def test_the_http_client_bound_is_under_the_format_stage() -> None:
    cfg = _agent_config()
    client = float(cfg["ollama"]["timeout_s"])
    fmt = float(cfg["query"]["format_timeout_s"])
    assert client < fmt, (
        f"ollama.timeout_s={client} >= query.format_timeout_s={fmt}: the client would "
        "cut the answer before the stage that wraps it, making the format budget "
        "unreachable."
    )


def test_the_intent_bound_is_under_the_format_bound() -> None:
    """Classification is one word; it must never outlast the answer stage."""

    cfg = _agent_config()
    assert float(cfg["query"]["intent_timeout_s"]) < float(cfg["query"]["format_timeout_s"])


def test_the_handler_budget_fits_inside_the_transport_cap() -> None:
    """The wrapper must fire inside the transport envelope.

    Otherwise the REP server's cap expires first and the operator gets
    "outcome may be unknown" instead of a plain Russian "took too long".
    """

    from cryodaq.agents.assistant_main import _QUERY_TRANSPORT_MARGIN_S
    from cryodaq.core.zmq_bridge import HANDLER_TIMEOUT_LLM_S

    assert _QUERY_TRANSPORT_MARGIN_S > 0
    assert HANDLER_TIMEOUT_LLM_S - _QUERY_TRANSPORT_MARGIN_S > float(
        _agent_config()["query"]["format_timeout_s"]
    ), "the format stage cannot outlast the transport that carries its answer"


def test_the_client_bound_can_actually_produce_the_configured_tokens() -> None:
    """A budget smaller than the work it authorises is a guaranteed timeout.

    Uses a deliberately conservative 30 tok/s — well under the 48 tok/s measured
    on qwen3.8:27b — so this fails only when the numbers are genuinely
    impossible, not when hardware is merely slower than the day it was tuned.
    """

    from cryodaq.agents.assistant.query.agent import _FORMAT_MAX_TOKENS

    client = float(_agent_config()["ollama"]["timeout_s"])
    floor_s = _FORMAT_MAX_TOKENS / 30.0
    assert client >= floor_s, (
        f"ollama.timeout_s={client}s cannot emit _FORMAT_MAX_TOKENS={_FORMAT_MAX_TOKENS} "
        f"even at 30 tok/s ({floor_s:.0f}s needed). Either lower the token budget or "
        "raise the timeout."
    )
