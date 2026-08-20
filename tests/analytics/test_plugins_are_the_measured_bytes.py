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


class _Broker:
    async def subscribe(self, _name: str, **_kwargs: object) -> asyncio.Queue:
        return asyncio.Queue()

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
    pipeline._refuse_unmeasured_plugins()  # must not raise


def test_a_qualified_run_accepts_the_bytes_that_were_measured(tree: Path) -> None:
    pipeline = PluginPipeline(
        _Broker(),
        tree / "plugins",
        hot_reload=False,
        measured_artifact_sha256=source_artifact_digest(tree),
        project_root=tree,
    )
    pipeline._refuse_unmeasured_plugins()  # must not raise


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
        pipeline._refuse_unmeasured_plugins()


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
        pipeline._refuse_unmeasured_plugins()


def test_the_refusal_happens_before_any_plugin_is_imported() -> None:
    """Order is the whole point: refusing after the import would refuse nothing."""

    import inspect

    body = inspect.getsource(PluginPipeline._start_locked)
    assert "_refuse_unmeasured_plugins()" in body
    assert body.index("_refuse_unmeasured_plugins()") < body.index("self._load_plugin(path)")
