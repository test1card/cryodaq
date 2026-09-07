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
    assert HANDLER_TIMEOUT_LLM_S - _QUERY_TRANSPORT_MARGIN_S > float(_agent_config()["query"]["format_timeout_s"]), (
        "the format stage cannot outlast the transport that carries its answer"
    )


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


# ---------------------------------------------------------------------------
# The whole ladder, and the sum
#
# The pair-wise tests above pin neighbours. They cannot catch the way a nested
# timeout chain actually breaks in practice: every stage individually fits
# inside the budget that wraps it, while their SUM does not. A question that
# uses all four stages then overruns the handler, the transport gives up first,
# and the operator is told the outcome may be unknown for a question that was
# merely slow. Nothing asserted the sum, and nothing asserted the outer rungs —
# GUI, subprocess REQ and engine transport — at all.
# ---------------------------------------------------------------------------


def _ladder() -> list[tuple[str, float]]:
    """Outermost first. Each rung must strictly outlast the next."""
    from cryodaq.core.zmq_bridge import HANDLER_TIMEOUT_LLM_S
    from cryodaq.core.zmq_subprocess import SUBPROCESS_REQ_TIMEOUT_LLM_S
    from cryodaq.gui.zmq_client import _CMD_REPLY_TIMEOUT_LLM_S

    cfg = _agent_config()
    return [
        ("engine transport", _engine_transport_timeout()),
        ("GUI command reply", float(_CMD_REPLY_TIMEOUT_LLM_S)),
        ("subprocess REQ", float(SUBPROCESS_REQ_TIMEOUT_LLM_S)),
        ("handler", float(HANDLER_TIMEOUT_LLM_S)),
        ("stage sum", _stage_sum()),
        ("format stage", float(cfg["query"]["format_timeout_s"])),
        ("http client", float(cfg["ollama"]["timeout_s"])),
    ]


def _engine_transport_timeout() -> float:
    """The engine's assistant-socket deadline, read from its own default.

    Read from the signature rather than copied: a number duplicated in a test is
    a number that stops tracking the code the day someone changes one of them.
    """
    import inspect

    from cryodaq.engine import _RemoteAssistantQueryProxy  # noqa: PLC0415

    return float(inspect.signature(_RemoteAssistantQueryProxy.__init__).parameters["timeout_s"].default)


def _stage_sum() -> float:
    """Everything one question can spend inside the handler, added up."""
    from cryodaq.agents.assistant.query.agent import (
        _RETRIEVAL_DECISION_TIMEOUT_S,
        _RETRIEVAL_SEARCH_TIMEOUT_S,
    )

    cfg = _agent_config()
    return (
        float(cfg["query"]["intent_timeout_s"])
        + float(_RETRIEVAL_DECISION_TIMEOUT_S)
        + float(_RETRIEVAL_SEARCH_TIMEOUT_S)
        + float(cfg["query"]["format_timeout_s"])
    )


def test_every_rung_of_the_ladder_outlasts_the_one_inside_it() -> None:
    rungs = _ladder()
    for (outer_name, outer), (inner_name, inner) in zip(rungs, rungs[1:], strict=False):
        assert outer > inner, (
            f"{outer_name}={outer:g} does not outlast {inner_name}={inner:g}: the inner "
            "stage can never reach its own deadline, so its budget is a fiction"
        )


def test_the_stages_add_up_to_less_than_the_handler_budget() -> None:
    """The failure the pair-wise tests cannot see.

    One question can pay for classification, the decision to search, the search
    and the formatting, one after another. Each fits under the handler on its
    own; what matters is whether all four together do.
    """
    from cryodaq.core.zmq_bridge import HANDLER_TIMEOUT_LLM_S

    total = _stage_sum()
    assert total < float(HANDLER_TIMEOUT_LLM_S), (
        f"the stages sum to {total:g}s inside a {HANDLER_TIMEOUT_LLM_S:g}s handler budget: a "
        "question that uses all of them overruns, and the operator is told the outcome "
        "may be unknown for a question that was only slow"
    )


def test_the_search_stage_is_bounded_at_all() -> None:
    """An unbounded stage makes every budget above it unenforceable.

    The search was the one stage without a deadline, and the one most able to
    hang rather than fail: its LanceDB read runs through `asyncio.to_thread`,
    which cannot be cancelled.
    """
    import inspect

    from cryodaq.agents.assistant.query import agent as module

    source = inspect.getsource(module.AssistantQueryAgent._maybe_retrieve)
    assert "rag.search" in source
    call = source[source.index("rag.search") - 200 : source.index("rag.search") + 120]
    assert "wait_for" in call and "_RETRIEVAL_SEARCH_TIMEOUT_S" in call, "the retrieval search runs without a deadline"


def test_the_margin_is_real_and_not_a_rounding_error() -> None:
    """Adjacent rungs need enough room for the inner one to report its own
    failure, not merely to differ in the last decimal."""
    rungs = _ladder()
    for (outer_name, outer), (inner_name, inner) in zip(rungs, rungs[1:], strict=False):
        assert outer - inner >= 5.0, (
            f"{outer_name} leaves only {outer - inner:g}s over {inner_name}: not enough "
            "for the inner stage to turn its timeout into an answer"
        )
