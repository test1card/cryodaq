"""Verify adaptive-throttle reads critical channels from alarms_v3.yaml.

Phase 2b Codex H.1.
"""
from __future__ import annotations

import logging
import re

import pytest
import yaml

from cryodaq.core.housekeeping import (
    AdaptiveThrottle,
    load_critical_channels_from_alarms_v3,
)


def test_load_critical_simple_threshold(tmp_path):
    config = tmp_path / "alarms_v3.yaml"
    config.write_text(yaml.safe_dump({
        "global_alarms": {
            "p1_high": {
                "alarm_type": "threshold",
                "channel": "P1",
                "level": "CRITICAL",
            },
            "info_only": {
                "alarm_type": "threshold",
                "channel": "Т20",
                "level": "INFO",
            },
        },
    }, allow_unicode=True), encoding="utf-8")

    patterns = load_critical_channels_from_alarms_v3(config)
    assert re.escape("P1") in patterns
    assert re.escape("Т20") not in patterns, (
        "INFO-level alarm channel must NOT be protected"
    )


def test_load_critical_multi_channel(tmp_path):
    config = tmp_path / "alarms_v3.yaml"
    config.write_text(yaml.safe_dump({
        "global_alarms": {
            "rate_critical": {
                "alarm_type": "rate",
                "channels": ["Т11", "Т12"],
                "level": "CRITICAL",
            },
        },
    }, allow_unicode=True), encoding="utf-8")

    patterns = load_critical_channels_from_alarms_v3(config)
    assert re.escape("Т11") in patterns
    assert re.escape("Т12") in patterns


def test_load_critical_composite_with_nested_conditions(tmp_path):
    config = tmp_path / "alarms_v3.yaml"
    config.write_text(yaml.safe_dump({
        "global_alarms": {
            "vacuum_loss_cold": {
                "alarm_type": "composite",
                "operator": "AND",
                "conditions": [
                    {"channels": ["Т11", "Т12"], "check": "any_below"},
                    {"channel": "P1", "check": "above"},
                ],
                "level": "CRITICAL",
            },
        },
    }, allow_unicode=True), encoding="utf-8")

    patterns = load_critical_channels_from_alarms_v3(config)
    assert re.escape("Т11") in patterns
    assert re.escape("Т12") in patterns
    assert re.escape("P1") in patterns


def test_load_critical_channel_group_expansion(tmp_path):
    config = tmp_path / "alarms_v3.yaml"
    config.write_text(yaml.safe_dump({
        "channel_groups": {
            "calibrated": ["Т11", "Т12"],
            "all_temp": ["Т1", "Т2", "Т3"],
        },
        "interlocks": {
            "overheat_cryostat": {
                "channel_group": "all_temp",
                "action": "emergency_off",
            },
        },
    }, allow_unicode=True), encoding="utf-8")

    patterns = load_critical_channels_from_alarms_v3(config)
    assert re.escape("Т1") in patterns
    assert re.escape("Т2") in patterns
    assert re.escape("Т3") in patterns


def test_all_interlocks_protected_regardless_of_action(tmp_path):
    config = tmp_path / "alarms_v3.yaml"
    config.write_text(yaml.safe_dump({
        "interlocks": {
            "stop_one": {"channel": "smua_power", "action": "stop_source"},
            "kill_one": {"channel": "Т12", "action": "emergency_off"},
        },
    }, allow_unicode=True), encoding="utf-8")

    patterns = load_critical_channels_from_alarms_v3(config)
    assert re.escape("smua_power") in patterns
    assert re.escape("Т12") in patterns


def test_phase_alarms_nested_schema(tmp_path):
    """Phase 2b Codex Block D P1: phase_alarms is nested phase→alarm_id→alarm.

    The previous loader treated phase_alarms as a flat alarm_id→alarm dict
    and silently dropped every entry.
    """
    config = tmp_path / "alarms_v3.yaml"
    config.write_text(yaml.safe_dump({
        "phase_alarms": {
            "measurement": {
                "detector_loss": {
                    "channel": "Т12",
                    "level": "CRITICAL",
                },
                "minor_drift": {
                    "channel": "Т13",
                    "level": "INFO",
                },
            },
            "cooldown": {
                "rate_kill": {
                    "channels": ["Т11", "Т12"],
                    "level": "CRITICAL",
                },
            },
        },
    }, allow_unicode=True), encoding="utf-8")

    patterns = load_critical_channels_from_alarms_v3(config)
    # Critical entries from BOTH phases must be picked up.
    assert re.escape("Т12") in patterns
    assert re.escape("Т11") in patterns
    # INFO must NOT be protected even when nested.
    assert re.escape("Т13") not in patterns


def test_additional_condition_walked(tmp_path):
    """Phase 2b Codex Block D P2: additional_condition carries channel refs
    too. The recursive walker must enter it."""
    config = tmp_path / "alarms_v3.yaml"
    config.write_text(yaml.safe_dump({
        "global_alarms": {
            "vacuum_stall_critical": {
                "alarm_type": "rate",
                "channel": "P2",
                "additional_condition": {
                    "channel": "P3",
                    "check": "above",
                    "threshold": 1e-5,
                },
                "level": "CRITICAL",
            },
        },
    }, allow_unicode=True), encoding="utf-8")

    patterns = load_critical_channels_from_alarms_v3(config)
    assert re.escape("P2") in patterns
    assert re.escape("P3") in patterns, (
        "additional_condition.channel must be walked recursively"
    )


def test_unknown_channel_group_warns(tmp_path, caplog):
    config = tmp_path / "alarms_v3.yaml"
    config.write_text(yaml.safe_dump({
        "channel_groups": {"calibrated": ["Т11"]},
        "interlocks": {
            "missing_group": {
                "channel_group": "nonexistent",
                "action": "emergency_off",
            },
        },
    }, allow_unicode=True), encoding="utf-8")
    caplog.set_level(logging.WARNING)
    patterns = load_critical_channels_from_alarms_v3(config)
    assert patterns == set()
    assert any("unknown channel_group" in r.message for r in caplog.records)


def test_missing_file_returns_empty_set(tmp_path):
    patterns = load_critical_channels_from_alarms_v3(tmp_path / "nonexistent.yaml")
    assert patterns == set()


def test_corrupted_yaml_returns_empty_and_logs(tmp_path, caplog):
    config = tmp_path / "alarms_v3.yaml"
    config.write_text("global_alarms: [unbalanced\n", encoding="utf-8")
    caplog.set_level(logging.ERROR)

    patterns = load_critical_channels_from_alarms_v3(config)
    assert patterns == set()
    assert any("alarms_v3" in r.message for r in caplog.records)


def test_warning_level_NOT_protected(tmp_path):
    """Only critical/high alarms are protected. WARNING is not."""
    config = tmp_path / "alarms_v3.yaml"
    config.write_text(yaml.safe_dump({
        "global_alarms": {
            "warn_only": {
                "channel": "Т20",
                "level": "WARNING",
            },
        },
    }, allow_unicode=True), encoding="utf-8")

    patterns = load_critical_channels_from_alarms_v3(config)
    assert re.escape("Т20") not in patterns


def test_throttle_protects_alarms_v3_channels(tmp_path):
    """End-to-end: AdaptiveThrottle uses the merged patterns to skip thinning."""
    from datetime import datetime, timezone
    from cryodaq.drivers.base import ChannelStatus, Reading

    config = tmp_path / "alarms_v3.yaml"
    config.write_text(yaml.safe_dump({
        "global_alarms": {
            "t11_high": {
                "channel": "Т11",
                "level": "CRITICAL",
            },
        },
    }, allow_unicode=True), encoding="utf-8")

    patterns = list(load_critical_channels_from_alarms_v3(config))
    assert patterns

    throttle = AdaptiveThrottle(
        {
            "enabled": True,
            "stable_duration_s": 0.0,
            "max_interval_s": 60.0,
            "absolute_delta": {"default": 100.0},  # huge → would normally suppress
        },
        protected_patterns=patterns,
    )

    def make(ch: str, value: float = 1.0) -> Reading:
        return Reading(
            channel=ch,
            value=value,
            unit="K",
            instrument_id="ls",
            timestamp=datetime.now(timezone.utc),
            status=ChannelStatus.OK,
            raw=value,
            metadata={},
        )

    # Prime the throttle's per-channel state with a baseline reading.
    throttle.filter_for_archive([make("lakeshore/Т11 верх", 4.0)])
    throttle.filter_for_archive([make("lakeshore/Т20 unused", 4.0)])

    # Now feed identical follow-up readings (delta=0). The huge default
    # threshold + zero stable_duration would normally let suppression kick in,
    # but Т11 is in the protected set so it must always be emitted.
    out_t11 = throttle.filter_for_archive([make("lakeshore/Т11 верх", 4.0)])
    out_t20 = throttle.filter_for_archive([make("lakeshore/Т20 unused", 4.0)])

    assert len(out_t11) == 1, (
        "Т11 should be protected (alarms_v3 critical) and bypass throttling"
    )
    # Т20 may or may not pass — but the key assertion is Т11 protection.
