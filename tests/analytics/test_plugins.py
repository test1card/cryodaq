"""Tests for PluginPipeline: loading, configuration, isolation, and broker integration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import ChannelStatus, Reading


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIMPLE_PLUGIN_SRC = """\
from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric


class SimplePlugin(AnalyticsPlugin):
    plugin_id = "simple_plugin"

    def __init__(self):
        super().__init__(self.plugin_id)
        self._configured = False
        self._config_value = None

    def configure(self, config):
        super().configure(config)
        self._configured = True
        self._config_value = config.get("test_key")

    async def process(self, readings):
        return [DerivedMetric.now(self.plugin_id, "test_metric", 42.0, "arb")]
"""

_BAD_PLUGIN_SRC = """\
from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric


class BadPlugin(AnalyticsPlugin):
    plugin_id = "bad_plugin"

    def __init__(self):
        super().__init__(self.plugin_id)

    async def process(self, readings):
        raise RuntimeError("intentional failure for testing")
"""

_GOOD_COMPANION_SRC = """\
from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric


class GoodCompanionPlugin(AnalyticsPlugin):
    plugin_id = "good_companion"

    def __init__(self):
        super().__init__(self.plugin_id)

    async def process(self, readings):
        return [DerivedMetric.now(self.plugin_id, "companion_metric", 7.0, "arb")]
"""


def _make_ok_reading() -> Reading:
    return Reading.now(channel="test/ch", value=1.0, unit="K", instrument_id="test")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_load_plugin_from_file(tmp_path: Path):
    """A simple plugin written to a temp file is discovered and loaded by PluginPipeline."""
    plugin_file = tmp_path / "simple_plugin.py"
    plugin_file.write_text(_SIMPLE_PLUGIN_SRC, encoding="utf-8")

    broker = DataBroker()
    pipeline = PluginPipeline(broker, tmp_path, batch_interval_s=0.05)
    await pipeline.start()
    try:
        assert "simple_plugin" in pipeline._plugins
    finally:
        await pipeline.stop()


async def test_yaml_config_applied(tmp_path: Path):
    """When a .yaml file with the same stem exists, configure() is called on the plugin."""
    plugin_file = tmp_path / "simple_plugin.py"
    plugin_file.write_text(_SIMPLE_PLUGIN_SRC, encoding="utf-8")

    yaml_file = tmp_path / "simple_plugin.yaml"
    yaml_file.write_text("test_key: hello_from_yaml\n", encoding="utf-8")

    broker = DataBroker()
    pipeline = PluginPipeline(broker, tmp_path, batch_interval_s=0.05)
    await pipeline.start()
    try:
        plugin = pipeline._plugins["simple_plugin"]
        assert plugin._configured is True
        assert plugin._config_value == "hello_from_yaml"
    finally:
        await pipeline.stop()


async def _drain_for_analytics(
    queue: asyncio.Queue,
    expected_prefix: str,
    timeout: float = 2.0,
) -> "Reading":
    """Drain *queue* until a Reading whose channel starts with *expected_prefix* is found."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            pytest.fail(f"No analytics reading with prefix '{expected_prefix}' within timeout")
        try:
            reading = await asyncio.wait_for(queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            pytest.fail(f"No analytics reading with prefix '{expected_prefix}' within timeout")
        if reading.channel.startswith(expected_prefix):
            return reading


async def test_bad_plugin_isolated(tmp_path: Path, caplog):
    """A plugin that raises in process() is isolated — error is logged and the pipeline continues."""
    bad_file = tmp_path / "bad_plugin.py"
    bad_file.write_text(_BAD_PLUGIN_SRC, encoding="utf-8")

    good_file = tmp_path / "good_companion.py"
    good_file.write_text(_GOOD_COMPANION_SRC, encoding="utf-8")

    broker = DataBroker()
    # Filter: only analytics readings reach this subscriber
    results_queue = await broker.subscribe(
        "test_results",
        filter_fn=lambda r: r.channel.startswith("analytics/"),
    )

    pipeline = PluginPipeline(broker, tmp_path, batch_interval_s=0.05)
    await pipeline.start()

    # Publish a reading so the batch is non-empty and plugins are invoked
    await broker.publish(_make_ok_reading())

    try:
        result = await asyncio.wait_for(results_queue.get(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("No reading from good companion published within timeout")
    finally:
        await pipeline.stop()
        await broker.unsubscribe("test_results")

    # The good companion produced its metric
    assert result.channel == "analytics/good_companion/companion_metric"

    # The bad plugin's error was logged
    error_records = [
        r for r in caplog.records
        if r.levelno >= logging.ERROR and "bad_plugin" in r.message
    ]
    assert error_records, "Expected an error log entry for bad_plugin"


async def test_derived_metric_published_to_broker(tmp_path: Path):
    """DerivedMetric produced by a plugin appears as a Reading in the broker."""
    plugin_file = tmp_path / "simple_plugin.py"
    plugin_file.write_text(_SIMPLE_PLUGIN_SRC, encoding="utf-8")

    broker = DataBroker()
    # Filter: only analytics readings reach this subscriber
    results_queue = await broker.subscribe(
        "test_results",
        filter_fn=lambda r: r.channel.startswith("analytics/"),
    )

    pipeline = PluginPipeline(broker, tmp_path, batch_interval_s=0.05)
    await pipeline.start()

    # Publish a raw reading to trigger a non-empty batch
    await broker.publish(_make_ok_reading())

    try:
        reading = await asyncio.wait_for(results_queue.get(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("Derived metric was not published to broker within timeout")
    finally:
        await pipeline.stop()
        await broker.unsubscribe("test_results")

    assert reading.channel == "analytics/simple_plugin/test_metric"
    assert reading.value == pytest.approx(42.0)
    assert reading.unit == "arb"
    assert reading.metadata.get("source") == "analytics"
    assert reading.metadata.get("plugin_id") == "simple_plugin"
