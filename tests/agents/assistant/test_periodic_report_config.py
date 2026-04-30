"""Tests for F29 periodic report configuration fields in AssistantConfig."""

from __future__ import annotations

from cryodaq.agents.assistant.live.agent import AssistantConfig


def test_periodic_report_config_defaults() -> None:
    config = AssistantConfig()
    assert config.periodic_report_enabled is True
    assert config.periodic_report_interval_minutes == 60
    assert config.periodic_report_skip_if_idle is True
    assert config.periodic_report_min_events == 1


def test_periodic_report_config_disabled() -> None:
    config = AssistantConfig.from_dict(
        {"triggers": {"periodic_report": {"enabled": False}}}
    )
    assert config.periodic_report_enabled is False


def test_periodic_report_interval_seconds_calculation() -> None:
    config = AssistantConfig.from_dict(
        {"triggers": {"periodic_report": {"enabled": True, "interval_minutes": 30}}}
    )
    assert config.get_periodic_report_interval_s() == 1800.0


def test_periodic_report_interval_zero_when_disabled() -> None:
    config = AssistantConfig.from_dict(
        {"triggers": {"periodic_report": {"enabled": False, "interval_minutes": 60}}}
    )
    assert config.get_periodic_report_interval_s() == 0.0


def test_periodic_report_min_events_configurable() -> None:
    config = AssistantConfig.from_dict(
        {"triggers": {"periodic_report": {"min_events_for_dispatch": 5}}}
    )
    assert config.periodic_report_min_events == 5


def test_periodic_report_config_from_yaml_string() -> None:
    yaml_content = (
        "agent:\n"
        "  triggers:\n"
        "    periodic_report:\n"
        "      enabled: true\n"
        "      interval_minutes: 120\n"
        "      skip_if_idle: false\n"
        "      min_events_for_dispatch: 3\n"
    )
    config = AssistantConfig.from_yaml_string(yaml_content)
    assert config.periodic_report_enabled is True
    assert config.periodic_report_interval_minutes == 120
    assert config.periodic_report_skip_if_idle is False
    assert config.periodic_report_min_events == 3
    assert config.get_periodic_report_interval_s() == 7200.0
