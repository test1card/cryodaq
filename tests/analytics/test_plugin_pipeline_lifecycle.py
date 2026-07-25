"""Lifecycle-generation ownership guards for the analytics plugin pipeline."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric
from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import Reading


def _live_pipeline_tasks() -> set[asyncio.Task[object]]:
    return {
        task
        for task in asyncio.all_tasks()
        if not task.done() and task.get_name() in {"analytics_process_loop", "analytics_watch_loop"}
    }


async def test_concurrent_starts_create_one_exact_pipeline_generation(tmp_path: Path) -> None:
    """Concurrent callers share one subscription and one task pair."""

    broker = DataBroker()
    pipeline = PluginPipeline(broker, tmp_path, batch_interval_s=0.01)

    await broker._lock.acquire()
    first = asyncio.create_task(pipeline.start())
    second = asyncio.create_task(pipeline.start())
    await asyncio.sleep(0)
    broker._lock.release()

    try:
        await asyncio.gather(first, second)
        process_tasks = {
            task for task in asyncio.all_tasks() if not task.done() and task.get_name() == "analytics_process_loop"
        }
        watch_tasks = {
            task for task in asyncio.all_tasks() if not task.done() and task.get_name() == "analytics_watch_loop"
        }

        assert process_tasks == {pipeline._process_task}
        assert watch_tasks == {pipeline._watch_task}
        assert pipeline._queue is broker._subscribers["plugin_pipeline"].queue
    finally:
        await asyncio.gather(first, second, return_exceptions=True)
        await pipeline.stop()
        leaked = _live_pipeline_tasks()
        for task in leaked:
            task.cancel()
        await asyncio.gather(*leaked, return_exceptions=True)

    assert _live_pipeline_tasks() == set()


async def test_partial_start_failure_releases_exact_subscription(tmp_path: Path) -> None:
    """A filesystem failure after subscribe cannot retain a hidden generation."""

    plugins_path = tmp_path / "not-a-directory"
    plugins_path.write_text("occupied", encoding="utf-8")
    broker = DataBroker()
    pipeline = PluginPipeline(broker, plugins_path, batch_interval_s=0.01)

    with pytest.raises(FileExistsError):
        await pipeline.start()

    assert "plugin_pipeline" not in broker._subscribers
    assert pipeline._queue is None
    assert pipeline._process_task is None
    assert pipeline._watch_task is None
    assert pipeline._running is False


async def test_successful_stop_tears_down_every_plugin_owner(tmp_path: Path) -> None:
    broker = DataBroker()
    pipeline = PluginPipeline(broker, tmp_path, batch_interval_s=0.01)
    torn_down: list[str] = []
    pipeline._plugins = {
        "first": SimpleNamespace(teardown=lambda: torn_down.append("first")),
        "second": SimpleNamespace(teardown=lambda: torn_down.append("second")),
    }

    await pipeline.stop()

    assert torn_down == ["first", "second"]
    assert pipeline._plugins == {}


def test_failed_plugin_teardown_retains_exact_owner_for_retry(tmp_path: Path) -> None:
    broker = DataBroker()
    pipeline = PluginPipeline(broker, tmp_path, batch_interval_s=0.01)
    attempts = 0

    def teardown() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected ambiguous teardown")

    plugin = SimpleNamespace(teardown=teardown)
    pipeline._plugins = {"owned": plugin}

    with pytest.raises(RuntimeError, match="teardown"):
        pipeline._unload_plugin("owned")
    assert pipeline._plugins == {"owned": plugin}

    pipeline._unload_plugin("owned")
    assert pipeline._plugins == {}
    assert attempts == 2


async def test_partial_start_failure_tears_down_loaded_plugins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.analytics.plugin_loader as plugin_loader

    plugin_path = tmp_path / "owned.py"
    plugin_path.write_text("# discovered plugin\n", encoding="utf-8")
    broker = DataBroker()
    pipeline = PluginPipeline(broker, tmp_path, batch_interval_s=0.01)
    torn_down: list[str] = []
    plugin = SimpleNamespace(teardown=lambda: torn_down.append("owned"))
    monkeypatch.setattr(
        pipeline,
        "_load_plugin",
        lambda _path: pipeline._plugins.__setitem__("owned", plugin),
    )
    real_create = plugin_loader._create_owned_task

    def fail_watch(coroutine, *, name: str):  # noqa: ANN001, ANN202
        if name == "analytics_watch_loop":
            coroutine.close()
            raise RuntimeError("injected watch-task construction failure")
        return real_create(coroutine, name=name)

    monkeypatch.setattr(plugin_loader, "_create_owned_task", fail_watch)

    with pytest.raises(RuntimeError, match="watch-task construction"):
        await pipeline.start()

    assert torn_down == ["owned"]
    assert pipeline._plugins == {}
    assert "plugin_pipeline" not in broker._subscribers
    assert _live_pipeline_tasks() == set()


def test_constructor_body_type_error_is_not_retried_without_plugin_id(tmp_path: Path) -> None:
    plugin_path = tmp_path / "constructor_probe.py"
    plugin_path.write_text(
        """
from pathlib import Path
from cryodaq.analytics.base_plugin import AnalyticsPlugin

class ConstructorProbe(AnalyticsPlugin):
    def __init__(self, plugin_id=None):
        event = "with-id" if plugin_id is not None else "fallback"
        with Path(__file__).with_name("constructor.events").open("a", encoding="utf-8") as stream:
            stream.write(event + "\\n")
        if plugin_id is not None:
            raise TypeError("constructor body failure")
        super().__init__("fallback")

    async def process(self, readings):
        return []
""".lstrip(),
        encoding="utf-8",
    )
    pipeline = PluginPipeline(DataBroker(), tmp_path)

    loaded = pipeline._load_plugin(plugin_path)

    assert loaded is False
    assert pipeline._plugins == {}
    assert (tmp_path / "constructor.events").read_text(encoding="utf-8").splitlines() == ["with-id"]


@pytest.mark.parametrize(
    ("yaml_payload", "expected_events"),
    (
        ("enabled: true\n", ["configure", "teardown"]),
        ("broken: [\n", ["teardown"]),
    ),
)
def test_config_failure_settles_constructed_owner_before_rejection(
    tmp_path: Path,
    yaml_payload: str,
    expected_events: list[str],
) -> None:
    plugin_path = tmp_path / "config_probe.py"
    plugin_path.write_text(
        """
from pathlib import Path
from cryodaq.analytics.base_plugin import AnalyticsPlugin

class ConfigProbe(AnalyticsPlugin):
    def __init__(self, plugin_id):
        super().__init__(plugin_id)

    def _event(self, value):
        with Path(__file__).with_name("config.events").open("a", encoding="utf-8") as stream:
            stream.write(value + "\\n")

    def configure(self, config):
        self._event("configure")
        raise ValueError("configuration body failure")

    def teardown(self):
        self._event("teardown")

    async def process(self, readings):
        return []
""".lstrip(),
        encoding="utf-8",
    )
    plugin_path.with_suffix(".yaml").write_text(yaml_payload, encoding="utf-8")
    pipeline = PluginPipeline(DataBroker(), tmp_path)

    loaded = pipeline._load_plugin(plugin_path)

    assert loaded is False
    assert pipeline._plugins == {}
    assert pipeline._pending_plugin_cleanup == {}
    assert (tmp_path / "config.events").read_text(encoding="utf-8").splitlines() == expected_events


async def test_settled_unload_waits_for_inflight_process_before_teardown(tmp_path: Path) -> None:
    started = asyncio.Event()
    release_process = asyncio.Event()
    publish_started = asyncio.Event()
    release_publish = asyncio.Event()
    events: list[str] = []

    class BlockingBroker:
        async def publish(self, _reading: Reading) -> None:
            events.append("publish-start")
            publish_started.set()
            await release_publish.wait()
            events.append("publish-end")

    class BlockingPlugin(AnalyticsPlugin):
        def __init__(self) -> None:
            super().__init__("owned")
            self.processing = False

        async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
            self.processing = True
            events.append("process-start")
            started.set()
            try:
                await release_process.wait()
                return [DerivedMetric.now("owned", "value", 1.0, "arb")]
            finally:
                self.processing = False
                events.append("process-end")

        def teardown(self) -> None:
            assert self.processing is False
            events.append("teardown")

    pipeline = PluginPipeline(BlockingBroker(), tmp_path, batch_interval_s=0.001)  # type: ignore[arg-type]
    plugin = BlockingPlugin()
    pipeline._plugins = {"owned": plugin}
    pipeline._plugin_generations = {"owned": 1}
    pipeline._next_plugin_generation = 1
    pipeline._queue = asyncio.Queue()
    pipeline._running = True
    process_task = asyncio.create_task(pipeline._process_loop())
    await pipeline._queue.put(Reading.now(channel="raw", value=1.0, unit="K", instrument_id="probe"))

    try:
        await asyncio.wait_for(started.wait(), timeout=1.0)
        unload_task = asyncio.create_task(pipeline._unload_plugin_settled("owned"))
        await asyncio.sleep(0)
        assert unload_task.done() is False
        assert events == ["process-start"]

        release_process.set()
        await asyncio.wait_for(publish_started.wait(), timeout=1.0)
        await asyncio.sleep(0)
        assert unload_task.done() is False
        assert events == ["process-start", "process-end", "publish-start"]

        release_publish.set()
        assert await asyncio.wait_for(unload_task, timeout=1.0) is True
        assert events == ["process-start", "process-end", "publish-start", "publish-end", "teardown"]
        assert pipeline._plugins == {}
        assert process_task.done() is False
    finally:
        release_process.set()
        release_publish.set()
        pipeline._running = False
        process_task.cancel()
        await asyncio.gather(process_task, return_exceptions=True)


async def test_invalid_plugin_result_isolated_without_false_running_state(tmp_path: Path) -> None:
    published = asyncio.Event()
    readings: list[Reading] = []

    class RecordingBroker:
        async def publish(self, reading: Reading) -> None:
            readings.append(reading)
            published.set()

    class InvalidPlugin(AnalyticsPlugin):
        async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
            return None  # type: ignore[return-value]

    class ValidPlugin(AnalyticsPlugin):
        async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
            return [DerivedMetric.now(self.plugin_id, "valid", 2.0, "arb")]

    pipeline = PluginPipeline(RecordingBroker(), tmp_path, batch_interval_s=0.001)  # type: ignore[arg-type]
    pipeline._plugins = {
        "invalid": InvalidPlugin("invalid"),
        "valid": ValidPlugin("valid"),
    }
    pipeline._plugin_generations = {"invalid": 1, "valid": 2}
    pipeline._next_plugin_generation = 2
    pipeline._queue = asyncio.Queue()
    pipeline._running = True
    process_task = asyncio.create_task(pipeline._process_loop())
    await pipeline._queue.put(Reading.now(channel="raw", value=1.0, unit="K", instrument_id="probe"))

    try:
        await asyncio.wait_for(published.wait(), timeout=1.0)
        assert [reading.channel for reading in readings] == ["analytics/valid/valid"]
        assert process_task.done() is False
        assert pipeline._running is True
    finally:
        pipeline._running = False
        process_task.cancel()
        await asyncio.gather(process_task, return_exceptions=True)


async def test_failed_directory_scan_cannot_unload_live_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import cryodaq.analytics.plugin_loader as plugin_loader

    events: list[str] = []
    plugin = SimpleNamespace(plugin_id="owned", teardown=lambda: events.append("teardown"))
    pipeline = PluginPipeline(DataBroker(), tmp_path)
    pipeline._plugins = {"owned": plugin}
    pipeline._plugin_generations = {"owned": 1}
    pipeline._running = True
    scans = 0

    def scan() -> dict[str, float]:
        nonlocal scans
        scans += 1
        if scans == 1:
            return {"owned.py": 1.0}
        pipeline._running = False
        raise PermissionError("transient directory denial")

    monkeypatch.setattr(plugin_loader, "_WATCH_INTERVAL_S", 0.0)
    monkeypatch.setattr(pipeline, "_scan_plugins", scan)

    await pipeline._watch_loop()

    assert scans == 2
    assert pipeline._plugins == {"owned": plugin}
    assert events == []
