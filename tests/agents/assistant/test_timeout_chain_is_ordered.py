"""Four timeouts wrap the same work, and only the innermost may fire.

Raising one alone does not make the assistant patient — it just moves which
bound cancels the work. When the transport gives up first the operator gets
"outcome may be unknown"; when the handler does, a plain-Russian "took too
long"; only the innermost produces a clean truncated answer.

The chain was `transport 450 > handler 420 > format 300 > ollama 280` and is
`1800 > 1740 > 1500 > 1400` since 2026-09-07, when the operator chose quality
over latency until the inference server moves to vLLM. The measured cases that
prompted it ran 236-290 s, with one question cancelled at 290 s having never
returned an answer.

This test exists because the ordering lived only in a comment.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import yaml


def _agent_config() -> dict:
    text = (Path(__file__).resolve().parents[3] / "config" / "agent.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)["agent"]


def test_every_bound_is_wider_than_the_one_it_wraps() -> None:
    import cryodaq.engine as engine
    from cryodaq.core.zmq_bridge import HANDLER_TIMEOUT_LLM_S

    cfg = _agent_config()
    ollama = float(cfg["ollama"]["timeout_s"])
    fmt = float(cfg["query"]["format_timeout_s"])

    source = inspect.getsource(engine)
    transport = max(
        float(value)
        for line in source.splitlines()
        if "timeout_s: float = " in line
        for value in [line.split("timeout_s: float = ")[1].split(",")[0]]
    )

    chain = [
        ("ZMQ transport", transport),
        ("handler", HANDLER_TIMEOUT_LLM_S),
        ("format", fmt),
        ("ollama", ollama),
    ]
    for (outer_name, outer), (inner_name, inner) in zip(chain, chain[1:], strict=False):
        assert outer > inner, (
            f"{outer_name} ({outer}s) must outlast {inner_name} ({inner}s), "
            "or the work is cancelled from outside and the operator is told the "
            "outcome is unknown instead of getting the answer"
        )


def test_the_classifier_is_given_room_for_a_cold_load() -> None:
    """A classification that gets cut takes the whole query with it."""
    cfg = _agent_config()
    assert float(cfg["query"]["intent_timeout_s"]) >= 60.0, (
        "a cold model load was measured at 23.3 s; anything tighter cancels queries that were about to be answered"
    )


def test_the_context_window_holds_a_conversation() -> None:
    """Operator's requirement, 2026-09-07: at least 100k, verified on the server."""
    cfg = _agent_config()
    assert int(cfg["ollama"]["num_ctx"]) >= 100_000
