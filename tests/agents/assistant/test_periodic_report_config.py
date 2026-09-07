"""Tests for F29 periodic report configuration fields in AssistantConfig."""

from __future__ import annotations

from cryodaq.agents.assistant.live.agent import AssistantConfig


def test_the_idle_knobs_are_gone_and_stay_gone() -> None:
    """`skip_if_idle` and `min_events_for_dispatch` decided FOR the agent.

    They gated the hourly bulletin on the operator log, so an hour in which the
    pressure climbed steadily produced nothing because nobody had typed. A knob
    that silences a report based on the wrong signal is worse than no knob, and
    a knob left in the config that no longer does anything is a lie to whoever
    reads it. Both are removed; the bulletin runs every hour.
    """
    config = AssistantConfig.from_dict({})
    assert not hasattr(config, "periodic_report_skip_if_idle")
    assert not hasattr(config, "periodic_report_min_events")


def test_periodic_report_config_defaults() -> None:
    config = AssistantConfig()
    assert config.periodic_report_enabled is True
    assert config.periodic_report_interval_minutes == 60


def test_periodic_report_config_disabled() -> None:
    config = AssistantConfig.from_dict({"triggers": {"periodic_report": {"enabled": False}}})
    assert config.periodic_report_enabled is False


def test_periodic_report_interval_seconds_calculation() -> None:
    config = AssistantConfig.from_dict({"triggers": {"periodic_report": {"enabled": True, "interval_minutes": 30}}})
    assert config.get_periodic_report_interval_s() == 1800.0


def test_periodic_report_interval_zero_when_disabled() -> None:
    config = AssistantConfig.from_dict({"triggers": {"periodic_report": {"enabled": False, "interval_minutes": 60}}})
    assert config.get_periodic_report_interval_s() == 0.0


def test_periodic_report_config_from_yaml_string() -> None:
    yaml_content = "agent:\n  triggers:\n    periodic_report:\n      enabled: true\n      interval_minutes: 120\n"
    config = AssistantConfig.from_yaml_string(yaml_content)
    assert config.periodic_report_enabled is True
    assert config.periodic_report_interval_minutes == 120
    assert config.get_periodic_report_interval_s() == 7200.0
