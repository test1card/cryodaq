"""The answer stage's context and token budget must be configurable.

They were module constants in query/agent.py, and their comment sized them
"against num_ctx (8192)". This deployment asks for 32768 in agent.yaml — but
that value only ever reached the LIVE agent, so the interactive answer stage
silently used a quarter of it and no config change could touch it.

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

from cryodaq.agents.assistant.live.agent import AssistantConfig


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


def test_the_query_agent_no_longer_hardcodes_the_budget() -> None:
    """The call sites must read config, not the module fallbacks."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[3] / "src/cryodaq/agents/assistant/query/agent.py").read_text(
        encoding="utf-8"
    )
    assert "max_tokens=_FORMAT_MAX_TOKENS," not in src
    assert "num_ctx=_FORMAT_NUM_CTX," not in src
    assert "query_format_max_tokens" in src
    assert "query_format_num_ctx" in src
