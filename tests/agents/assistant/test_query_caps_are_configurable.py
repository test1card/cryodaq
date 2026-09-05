"""The answer stage's context and token budget must be configurable.

They were module constants in query/agent.py, and their comment sized them
"against num_ctx (8192)". This deployment asks for 32768 in agent.yaml — but
that value only ever reached the LIVE agent, so the interactive answer stage
silently used 12,288 of it — not a quarter, as I first wrote — and no
config change could touch it.

This is the fifth constant found sized for equipment since replaced, after
ollama.timeout_s (120 for a model needing 280), the searcher's expected_dim
(1024 against an index built at 4096), the embed timeout (30 s against calls
taking 34), and keep_alive (release-immediately on a server with room to
hold). The pattern is the point: a number that encodes a fact about hardware
belongs next to the hardware it describes, not in a module constant.

The defaults here deliberately preserve the shipped behaviour. Changing the
VALUES is a separate decision, and one that should follow the measured
behaviour of the current model rather than precede it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cryodaq.agents.assistant.live.agent import AssistantConfig
from cryodaq.agents.assistant.shared.ollama_client import GenerationResult


def test_the_defaults_are_unchanged() -> None:
    """Making something configurable must not quietly change it."""
    cfg = AssistantConfig()
    assert cfg.query_format_num_ctx == 12288
    assert cfg.query_format_max_tokens == 6144


def test_config_overrides_reach_the_field() -> None:
    cfg = AssistantConfig.from_yaml_string(
        "agent:\n  enabled: true\n  query:\n    format_num_ctx: 32768\n    format_max_tokens: 12288\n"
    )
    assert cfg.query_format_num_ctx == 32768
    assert cfg.query_format_max_tokens == 12288


def test_a_silent_config_keeps_the_defaults() -> None:
    cfg = AssistantConfig.from_yaml_string("agent:\n  enabled: true\n  query:\n    enabled: true\n")
    assert cfg.query_format_num_ctx == 12288
    assert cfg.query_format_max_tokens == 6144


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("yaml_extra", "want_ctx", "want_tokens"),
    [
        ("    format_num_ctx: 32768\n    format_max_tokens: 12288\n", 32768, 12288),
        ("", 12288, 6144),
    ],
    ids=["configured", "absent"],
)
async def test_the_configured_budget_reaches_the_generation_call(
    yaml_extra: str, want_ctx: int, want_tokens: int
) -> None:
    """Replaced 2026-09-06 after review.

    This was a source-string test: it read query/agent.py and looked for the
    field NAME. Review put it plainly - finding a configuration field's name in
    a file does not establish that its value reaches inference. It would pass
    for a call passing the wrong value, and for a mention in a comment.

    This drives YAML through the real agent to the generation call and reads
    what actually arrived.
    """
    from tests.agents.assistant.test_query_agent import (
        _intent_json,
        _make_adapters,
        _make_agent,
    )

    cfg = AssistantConfig.from_yaml_string("agent:\n  enabled: true\n  query:\n    enabled: true\n" + yaml_extra)

    seen: list[dict] = []

    async def _generate(*args, **kwargs):
        seen.append(kwargs)
        return GenerationResult(
            text=_intent_json("phase_info") if len(seen) == 1 else "ответ",
            tokens_in=1,
            tokens_out=1,
            latency_s=0.1,
            model="m",
        )

    ollama = MagicMock()
    ollama.generate = AsyncMock(side_effect=_generate)

    agent = _make_agent(ollama, _make_adapters())
    agent._config = cfg

    await agent.handle_query("в какой фазе?", chat_id=1)

    assert len(seen) >= 2, "the answer stage was never reached"
    answer_call = seen[-1]
    assert answer_call.get("num_ctx") == want_ctx
    assert answer_call.get("max_tokens") == want_tokens
