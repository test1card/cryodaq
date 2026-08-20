"""A qualified run must not import a plugin whose bytes nobody measured.

WHY THIS MODULE EXISTS. Turning hot reload off stops the WATCH loop; it does not touch the
first import. A plugin edited between the moment qualification measured the tree and the
moment ``_start_locked`` imports it therefore ran unmeasured Python inside the engine while
the receipt still named the measured build -- which is the one thing a qualified run must
never be able to say.

The check is deliberately the WHOLE artifact manifest, not the plugins alone: that is what
the receipt binds, and a narrower comparison would accept a tree the receipt no longer
describes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.core.qualification import source_artifact_digest

_REPO_ROOT = Path(__file__).resolve().parents[2]

_PLUGIN_SOURCE = """from cryodaq.analytics.base_plugin import AnalyticsPlugin


class Example(AnalyticsPlugin):
    MARKER = "{marker}"

    async def process(self, readings):
        return []
"""

_CONFIGURABLE_SOURCE = """from cryodaq.analytics.base_plugin import AnalyticsPlugin


class Configured(AnalyticsPlugin):
    setting = "unset"

    def configure(self, config):
        self.setting = config.get("setting", "unset")

    async def process(self, readings):
        return []
"""


class _Broker:
    async def subscribe(self, _name: str, **_kwargs: object) -> asyncio.Queue:
        return asyncio.Queue()

    async def unsubscribe(self, _name: str, **_kwargs: object) -> bool:
        # The pipeline settles only on an exact release, so the fixture must answer
        # like the real broker rather than merely not raising.
        return True

    def freeze(self) -> None:
        return None


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal project whose artifact manifest can be measured and then changed."""

    package = tmp_path / "src" / "cryodaq"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    return tmp_path


def test_the_digest_covers_the_plugins_as_well_as_the_package(tree: Path) -> None:
    before = source_artifact_digest(tree)
    (tree / "plugins" / "example.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert source_artifact_digest(tree) != before, "a changed plugin must change the digest"


def test_an_unqualified_run_is_not_affected(tree: Path) -> None:
    """Without a receipt there is nothing to bind to, and nothing to refuse."""

    pipeline = PluginPipeline(_Broker(), tree / "plugins", hot_reload=True)
    pipeline._measured_plugin_bytes()  # must not raise


def test_a_qualified_run_accepts_the_bytes_that_were_measured(tree: Path) -> None:
    pipeline = PluginPipeline(
        _Broker(),
        tree / "plugins",
        hot_reload=False,
        measured_artifact_sha256=source_artifact_digest(tree),
        project_root=tree,
    )
    pipeline._measured_plugin_bytes()  # must not raise


def test_a_qualified_run_refuses_a_plugin_changed_after_measurement(tree: Path) -> None:
    """The defect, exactly: edited after the measurement, imported anyway."""

    measured = source_artifact_digest(tree)
    pipeline = PluginPipeline(
        _Broker(),
        tree / "plugins",
        hot_reload=False,
        measured_artifact_sha256=measured,
        project_root=tree,
    )
    (tree / "plugins" / "example.py").write_text("VALUE = 2  # edited after qualification\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after qualification"):
        pipeline._measured_plugin_bytes()


def test_a_qualified_run_refuses_a_plugin_ADDED_after_measurement(tree: Path) -> None:
    """A new file is the easier mistake, and the manifest is a set, not a checksum of one."""

    pipeline = PluginPipeline(
        _Broker(),
        tree / "plugins",
        hot_reload=False,
        measured_artifact_sha256=source_artifact_digest(tree),
        project_root=tree,
    )
    (tree / "plugins" / "sneaked_in.py").write_text("VALUE = 3\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after qualification"):
        pipeline._measured_plugin_bytes()


def test_the_bytes_are_read_before_the_comparison_not_after_it(tree: Path) -> None:
    """The window between the check and the import, closed from the far side.

    Checking the tree and then importing from the PATH leaves a gap: a plugin written
    after the comparison is imported without ever reaching the compared digest. So the
    snapshot is taken first and the import runs from it. Falsify by making
    ``_load_plugin`` read the path again and this test reddens.
    """

    plugin = tree / "plugins" / "example.py"
    plugin.write_text(_PLUGIN_SOURCE.format(marker="measured"), encoding="utf-8")

    pipeline = PluginPipeline(
        _Broker(),
        tree / "plugins",
        hot_reload=False,
        measured_artifact_sha256=source_artifact_digest(tree),
        project_root=tree,
    )
    measured = pipeline._measured_plugin_bytes()
    assert measured is not None and plugin in measured

    # The change lands AFTER the comparison, which is the case a re-read would miss.
    plugin.write_text(_PLUGIN_SOURCE.format(marker="unmeasured"), encoding="utf-8")

    assert pipeline._load_plugin(plugin, measured=measured) is True
    loaded = pipeline._plugins["example"]
    assert type(loaded).MARKER == "measured", "the import executed bytes nobody measured"


def test_a_stale_bytecode_cache_cannot_be_executed_by_a_qualified_run(tree: Path) -> None:
    """The `.pyc` the digest deliberately does not measure must not be reachable.

    A cache entry is selected while the source size and modification time it recorded
    still agree, and a same-size, same-timestamp rewrite preserves both. Through the
    ordinary import machinery that stale bytecode runs while the `.py` comparison passes.
    """

    import importlib.util
    import os

    plugin = tree / "plugins" / "cached.py"
    plugin.write_text(_PLUGIN_SOURCE.format(marker="staleaaa"), encoding="utf-8")

    # Create the cache entry the ordinary way, then remember the stamp it recorded.
    spec = importlib.util.spec_from_file_location("cryodaq_plugin_cached_probe", plugin)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stat = plugin.stat()

    # Same length, same timestamp: the cache still looks valid for the new source.
    fresh = _PLUGIN_SOURCE.format(marker="freshaaa")
    assert len(fresh) == len(_PLUGIN_SOURCE.format(marker="staleaaa"))
    plugin.write_text(fresh, encoding="utf-8")
    os.utime(plugin, (stat.st_atime, stat.st_mtime))

    pipeline = PluginPipeline(
        _Broker(),
        tree / "plugins",
        hot_reload=False,
        measured_artifact_sha256=source_artifact_digest(tree),
        project_root=tree,
    )
    measured = pipeline._measured_plugin_bytes()
    assert measured is not None

    assert pipeline._load_plugin(plugin, measured=measured) is True
    assert type(pipeline._plugins["cached"]).MARKER == "freshaaa", (
        "a qualified run executed cached bytecode instead of the measured source"
    )


def test_the_measured_configuration_is_applied_not_the_current_file(tree: Path) -> None:
    """The plugin's YAML is in the same manifest, so it is bound in the same snapshot."""

    plugin = tree / "plugins" / "configured.py"
    plugin.write_text(_CONFIGURABLE_SOURCE, encoding="utf-8")
    (tree / "plugins" / "configured.yaml").write_text("setting: measured\n", encoding="utf-8")

    pipeline = PluginPipeline(
        _Broker(),
        tree / "plugins",
        hot_reload=False,
        measured_artifact_sha256=source_artifact_digest(tree),
        project_root=tree,
    )
    measured = pipeline._measured_plugin_bytes()
    assert measured is not None

    (tree / "plugins" / "configured.yaml").write_text("setting: unmeasured\n", encoding="utf-8")
    assert pipeline._load_plugin(plugin, measured=measured) is True
    assert pipeline._plugins["configured"].setting == "measured"


def test_measuring_the_tree_does_not_stall_the_engine_loop(tree: Path) -> None:
    """`interlock_engine.start()` has already run, so a blocking scan stalls live work.

    The measurement walks the source tree and reads every artifact, which is slow on a
    large checkout or a slow filesystem. It must therefore happen in a worker thread.
    Driven, not read: a counter coroutine must keep advancing while the scan runs.
    """

    import cryodaq.analytics.plugin_loader as loader_module

    real_digest = loader_module.__dict__  # touched so the import is not flagged unused
    assert real_digest is not None

    (tree / "plugins" / "example.py").write_text(_PLUGIN_SOURCE.format(marker="anything"), encoding="utf-8")
    pipeline = PluginPipeline(
        _Broker(),
        tree / "plugins",
        hot_reload=False,
        measured_artifact_sha256=source_artifact_digest(tree),
        project_root=tree,
    )

    ticks = 0

    def _slow_measurement() -> dict[Path, bytes] | None:
        import time

        time.sleep(0.4)
        return {}

    pipeline._measured_plugin_bytes = _slow_measurement  # type: ignore[method-assign]

    async def _ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    async def _drive() -> None:
        ticker = asyncio.create_task(_ticker())
        try:
            await pipeline._start_locked()
        finally:
            ticker.cancel()
            try:
                await ticker
            except asyncio.CancelledError:
                pass
            await pipeline.stop()

    asyncio.run(_drive())
    assert ticks >= 5, f"the event loop was stalled during the measurement (ticks={ticks})"


def test_the_engine_reads_the_digest_the_receipt_actually_carries() -> None:
    """The engine's own expression, evaluated against a real issued receipt.

    `QualificationReceipt` is a slotted dataclass carrying `context`, so the shorter
    `qualification_receipt.artifact_sha256` raised AttributeError on EVERY qualified
    startup -- the laboratory path -- and the program exited before acquisition began.
    This reads the expression out of `engine.py` and evaluates it, so a return to the
    broken spelling reddens here instead of at the instrument.
    """

    import ast as _ast

    from cryodaq.core.qualification import QualificationContext, QualificationReceipt

    engine_source = (_REPO_ROOT / "src" / "cryodaq" / "engine.py").read_text(encoding="utf-8")
    tree_ = _ast.parse(engine_source)
    expression: _ast.expr | None = None
    for node in _ast.walk(tree_):
        if isinstance(node, _ast.keyword) and node.arg == "measured_artifact_sha256":
            expression = node.value
    assert expression is not None, "engine.py no longer passes measured_artifact_sha256"

    context = QualificationContext(
        commit="a" * 40,
        tree="b" * 40,
        artifact_sha256="sha256:" + "c" * 64,
        configuration_sha256="sha256:" + "d" * 64,
        reviewed_source_binding_sha256="sha256:" + "e" * 64,
        hardware_profile_id="montana-lab-1",
    )
    receipt = QualificationReceipt._issued(
        receipt_id="receipt-1",
        expires_at_unix_s=2**31,
        expires_monotonic_s=1.0,
        context=context,
    )

    evaluated = eval(  # noqa: S307 - the expression comes from our own tracked source
        compile(_ast.Expression(body=expression), "<engine.py>", "eval"),
        {"qualification_receipt": receipt},
    )
    assert evaluated == "sha256:" + "c" * 64, "the engine does not read the digest the receipt carries"
