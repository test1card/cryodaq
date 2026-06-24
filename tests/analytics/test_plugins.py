"""Tests for PluginPipeline: loading, configuration, isolation, and broker integration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import Reading

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
    timeout: float = 2.0,  # noqa: ASYNC109
) -> Reading:
    """Drain *queue* until a Reading whose channel starts with *expected_prefix* is found."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            pytest.fail(f"No analytics reading with prefix '{expected_prefix}' within timeout")
        try:
            reading = await asyncio.wait_for(queue.get(), timeout=remaining)
        except TimeoutError:
            pytest.fail(f"No analytics reading with prefix '{expected_prefix}' within timeout")
        if reading.channel.startswith(expected_prefix):
            return reading


async def test_bad_plugin_isolated(tmp_path: Path, caplog):
    """A plugin that raises in process() is isolated — error is logged and the pipeline continues."""  # noqa: E501
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
    except TimeoutError:
        pytest.fail("No reading from good companion published within timeout")
    finally:
        await pipeline.stop()
        await broker.unsubscribe("test_results")

    # The good companion produced its metric
    assert result.channel == "analytics/good_companion/companion_metric"

    # The bad plugin's error was logged
    error_records = [
        r for r in caplog.records if r.levelno >= logging.ERROR and "bad_plugin" in r.message
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
    except TimeoutError:
        pytest.fail("Derived metric was not published to broker within timeout")
    finally:
        await pipeline.stop()
        await broker.unsubscribe("test_results")

    assert reading.channel == "analytics/simple_plugin/test_metric"
    assert reading.value == pytest.approx(42.0)
    assert reading.unit == "arb"
    assert reading.metadata.get("source") == "analytics"
    assert reading.metadata.get("plugin_id") == "simple_plugin"


# ---------------------------------------------------------------------------
# Hot-reload teardown + TOCTOU (POLISH_FIXES_2)
# ---------------------------------------------------------------------------

_TEARDOWN_PLUGIN_SRC = """\
from pathlib import Path

from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric


class TeardownPlugin(AnalyticsPlugin):
    plugin_id = "teardown_plugin"

    def __init__(self):
        super().__init__(self.plugin_id)

    def teardown(self):
        # Record teardown by touching a sentinel file next to the plugin.
        sentinel = Path(__file__).with_name("teardown_called.flag")
        sentinel.write_text("1", encoding="utf-8")

    async def process(self, readings):
        return [DerivedMetric.now(self.plugin_id, "m", 1.0, "arb")]
"""

_BAD_TEARDOWN_PLUGIN_SRC = """\
from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric


class BadTeardownPlugin(AnalyticsPlugin):
    plugin_id = "bad_teardown_plugin"

    def __init__(self):
        super().__init__(self.plugin_id)

    def teardown(self):
        raise RuntimeError("teardown boom")

    async def process(self, readings):
        return [DerivedMetric.now(self.plugin_id, "m", 1.0, "arb")]
"""


async def test_teardown_called_on_unload(tmp_path: Path):
    """_unload_plugin invokes the plugin's teardown() hook before removal."""
    plugin_file = tmp_path / "teardown_plugin.py"
    plugin_file.write_text(_TEARDOWN_PLUGIN_SRC, encoding="utf-8")
    sentinel = tmp_path / "teardown_called.flag"

    broker = DataBroker()
    pipeline = PluginPipeline(broker, tmp_path, batch_interval_s=0.05)
    await pipeline.start()
    try:
        assert "teardown_plugin" in pipeline._plugins
        assert not sentinel.exists()
        pipeline._unload_plugin("teardown_plugin")
        assert "teardown_plugin" not in pipeline._plugins
        assert sentinel.exists(), "teardown() should have run on unload"
    finally:
        await pipeline.stop()


async def test_bad_teardown_does_not_break_unload(tmp_path: Path, caplog):
    """A plugin whose teardown() raises is still unloaded; the error is logged."""
    plugin_file = tmp_path / "bad_teardown_plugin.py"
    plugin_file.write_text(_BAD_TEARDOWN_PLUGIN_SRC, encoding="utf-8")

    broker = DataBroker()
    pipeline = PluginPipeline(broker, tmp_path, batch_interval_s=0.05)
    await pipeline.start()
    try:
        assert "bad_teardown_plugin" in pipeline._plugins
        pipeline._unload_plugin("bad_teardown_plugin")
        # Unload must complete despite the teardown exception.
        assert "bad_teardown_plugin" not in pipeline._plugins
        error_records = [
            r
            for r in caplog.records
            if r.levelno >= logging.ERROR and "teardown" in r.message.lower()
        ]
        assert error_records, "Expected a logged error for the failing teardown()"
    finally:
        await pipeline.stop()


def test_default_teardown_is_noop():
    """The ABC default teardown() exists and is a no-op (does not raise)."""
    from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric

    class _Tmp(AnalyticsPlugin):
        async def process(self, readings):
            return [DerivedMetric.now(self.plugin_id, "m", 1.0, "arb")]

    p = _Tmp("tmp")
    assert p.teardown() is None  # no-op, no exception


async def test_watch_loop_skips_unstable_file(tmp_path: Path, monkeypatch):
    """The real _watch_loop must NOT load a file whose mtime keeps shifting.

    Simulates a half-written file (editor save-in-progress): while its mtime
    changes between scans the plugin is deferred; only once the mtime repeats
    across two consecutive scans is it loaded. This avoids registering a
    partially-written plugin.
    """
    import cryodaq.analytics.plugin_loader as pl

    broker = DataBroker()
    pipeline = PluginPipeline(broker, tmp_path, batch_interval_s=0.05)
    pipeline._plugins_dir.mkdir(parents=True, exist_ok=True)
    pipeline._running = True

    # Speed up the watch interval so the loop iterates fast.
    monkeypatch.setattr(pl, "_WATCH_INTERVAL_S", 0.01)

    loaded: list[str] = []
    monkeypatch.setattr(
        pipeline, "_load_plugin", lambda path: loaded.append(Path(path).name)
    )

    # Scan sequence: initial (empty) → new mtime → shifted mtime → stable.
    scans = iter(
        [
            {},  # initial known_files snapshot (taken before the loop body)
            {"simple_plugin.py": 100.0},  # first sighting — defer
            {"simple_plugin.py": 200.0},  # mtime shifted — still defer
            {"simple_plugin.py": 200.0},  # mtime stable — load now
        ]
    )
    snapshots_after_load: list[list[str]] = []

    def _scan() -> dict[str, float]:
        try:
            return next(scans)
        except StopIteration:
            # After the load-triggering scan, capture state and stop the loop.
            snapshots_after_load.append(list(loaded))
            pipeline._running = False
            return {"simple_plugin.py": 200.0}

    monkeypatch.setattr(pipeline, "_scan_plugins", _scan)

    await pipeline._watch_loop()

    assert loaded == ["simple_plugin.py"], (
        "file must load exactly once, only after its mtime stabilised"
    )
