"""Tests for ChannelManager cold-channel classification (B.4)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from cryodaq.core.channel_manager import ChannelManager


def _write_test_config(channels_dict: dict) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    )
    yaml.safe_dump({"channels": channels_dict}, tmp, allow_unicode=True)
    tmp.close()
    return Path(tmp.name)


def test_get_cold_channels_returns_only_cold():
    config = _write_test_config({
        "\u04221": {"name": "Cold one", "visible": True,
                    "is_cold": True, "group": "test"},
        "\u04222": {"name": "Warm one", "visible": True,
                    "is_cold": False, "group": "test"},
        "\u04223": {"name": "Another cold", "visible": True,
                    "is_cold": True, "group": "test"},
    })
    mgr = ChannelManager(config_path=config)
    cold = mgr.get_cold_channels()
    assert "\u04221" in cold
    assert "\u04223" in cold
    assert "\u04222" not in cold


def test_get_cold_channels_default_true_when_field_missing():
    config = _write_test_config({
        "\u04221": {"name": "No flag", "visible": True, "group": "test"},
    })
    mgr = ChannelManager(config_path=config)
    assert "\u04221" in mgr.get_cold_channels()


def test_get_visible_cold_channels_intersection():
    config = _write_test_config({
        "\u04221": {"name": "Cold visible", "visible": True,
                    "is_cold": True, "group": "test"},
        "\u04222": {"name": "Cold hidden", "visible": False,
                    "is_cold": True, "group": "test"},
        "\u04223": {"name": "Warm visible", "visible": True,
                    "is_cold": False, "group": "test"},
    })
    mgr = ChannelManager(config_path=config)
    visible_cold = mgr.get_visible_cold_channels()
    assert "\u04221" in visible_cold
    assert "\u04222" not in visible_cold
    assert "\u04223" not in visible_cold


def test_get_cold_channels_uses_real_config():
    """Verify the production channels.yaml loads with is_cold fields."""
    mgr = ChannelManager()
    cold = mgr.get_cold_channels()
    # T1-T14 should be cold per Vladimir's classification
    assert "\u04221" in cold
    assert "\u042214" in cold
    # T15 (Вакуумный кожух) should NOT be cold
    assert "\u042215" not in cold
