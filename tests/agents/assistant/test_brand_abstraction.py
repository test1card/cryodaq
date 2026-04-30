"""Tests for brand-name abstraction — Phase C of F28 Cycle 6.

Verifies that brand_name and brand_emoji are sourced from config,
not hardcoded; that legacy gemma.* config loads with a deprecation
warning; and that the new agent.* namespace loads cleanly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cryodaq.agents.assistant.live.agent import AssistantConfig
from cryodaq.agents.assistant.live.output_router import OutputRouter
from cryodaq.agents.assistant.live.prompts import (
    ALARM_SUMMARY_SYSTEM,
    format_with_brand,
)
from cryodaq.agents.assistant.shared.audit import AuditLogger

# ---------------------------------------------------------------------------
# format_with_brand
# ---------------------------------------------------------------------------


def test_brand_name_from_config_appears_in_alarm_prompt() -> None:
    """format_with_brand interpolates brand_name into system prompt template."""
    prompt = format_with_brand(ALARM_SUMMARY_SYSTEM, "Минерва")
    assert "Минерва" in prompt
    assert "Гемма" not in prompt


def test_format_with_brand_uses_exact_name() -> None:
    prompt = format_with_brand(ALARM_SUMMARY_SYSTEM, "Афина")
    assert "Афина" in prompt


# ---------------------------------------------------------------------------
# OutputRouter — prefix built from config
# ---------------------------------------------------------------------------


def test_telegram_prefix_uses_brand_emoji() -> None:
    router = OutputRouter(
        telegram_bot=None,
        event_logger=MagicMock(),
        event_bus=MagicMock(),
        brand_name="Минерва",
        brand_emoji="🦉",
    )
    assert router._prefix == "🦉 Минерва:"


def test_telegram_prefix_default_is_gemma() -> None:
    router = OutputRouter(
        telegram_bot=None,
        event_logger=MagicMock(),
        event_bus=MagicMock(),
    )
    assert router._prefix == "🤖 Гемма:"


# ---------------------------------------------------------------------------
# AssistantConfig — new agent.* namespace
# ---------------------------------------------------------------------------


def test_new_agent_config_loads_clean(caplog: pytest.LogCaptureFixture) -> None:
    yaml_content = (
        "agent:\n"
        "  enabled: true\n"
        '  brand_name: "Минерва"\n'
        '  brand_emoji: "🦉"\n'
        "  ollama:\n"
        "    default_model: qwen3:32b\n"
    )
    with caplog.at_level(logging.WARNING):
        config = AssistantConfig.from_yaml_string(yaml_content)

    assert config.brand_name == "Минерва"
    assert config.brand_emoji == "🦉"
    assert config.default_model == "qwen3:32b"
    assert "legacy" not in caplog.text.lower()


def test_legacy_gemma_config_loads_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    yaml_content = (
        "gemma:\n"
        "  enabled: true\n"
        "  ollama:\n"
        "    default_model: gemma4:e4b\n"
    )
    with caplog.at_level(logging.WARNING):
        config = AssistantConfig.from_yaml_string(yaml_content)

    assert config.enabled is True
    assert config.brand_name == "Гемма"  # default preserved
    assert "legacy" in caplog.text.lower()


def test_config_brand_fields_default() -> None:
    config = AssistantConfig()
    assert config.brand_name == "Гемма"
    assert config.brand_emoji == "🤖"


def test_config_from_dict_reads_brand_fields() -> None:
    config = AssistantConfig.from_dict(
        {"brand_name": "Афина", "brand_emoji": "🏛️", "enabled": True}
    )
    assert config.brand_name == "Афина"
    assert config.brand_emoji == "🏛️"


def test_empty_yaml_returns_defaults(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        config = AssistantConfig.from_yaml_string("")
    assert config.brand_name == "Гемма"
    assert config.enabled is True
    assert "legacy" not in caplog.text.lower()


# ---------------------------------------------------------------------------
# AssistantConfig — audit path uses assistant namespace
# ---------------------------------------------------------------------------


def test_audit_path_uses_assistant_namespace() -> None:
    config = AssistantConfig()
    assert "assistant" in str(config.audit_dir)
    assert "gemma" not in str(config.audit_dir)


def test_audit_logger_accepts_assistant_path(tmp_path: Path) -> None:
    audit_dir = tmp_path / "data" / "agents" / "assistant" / "audit"
    logger = AuditLogger(audit_dir, enabled=False)
    assert "assistant" in str(logger._audit_dir)
