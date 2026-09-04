"""The phase-delivery guard, driven through the REAL plugin lifecycle.

The other phase regressions reproduce the loader's registration tail by hand:
they bump the generation, insert into `_plugins` and call
`_capture_phase_receiver` themselves. That is faithful today and was verified
against the loader when written, but it is a copy — and a copy drifts. If
`_load_plugin` ever stops capturing a receiver, or captures it before the
generation is assigned, those tests would keep passing while production silently
lost the guard.

This one writes a real plugin file, loads it with `_load_plugin`, reloads it
with `_unload_plugin` + `_load_plugin`, and drives the delivery around that. No
registration step is simulated.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.core.phase_event import PhaseEntry

_PLUGIN_SOURCE = '''
from cryodaq.analytics.base_plugin import AnalyticsPlugin


class Consumer(AnalyticsPlugin):
    """Opts in the same way the molecular counter does: an instance attribute."""

    def __init__(self, plugin_id: str = "phase_probe") -> None:
        super().__init__(plugin_id)
        self.pending_phase_event = None

    async def process(self, readings):
        return []
'''


@pytest.fixture
def plugins_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "plugins"
    directory.mkdir()
    (directory / "phase_probe.py").write_text(_PLUGIN_SOURCE, encoding="utf-8")
    return directory


def _pipeline(plugins_dir: Path) -> PluginPipeline:
    return PluginPipeline(MagicMock(), plugins_dir)


def _entry(phase: str = "cooldown", started_at: float = 1_000.0) -> PhaseEntry:
    return PhaseEntry(experiment_id="exp-1", phase=phase, started_at=started_at)


def _loaded(pipeline: PluginPipeline) -> object:
    return pipeline._plugins["phase_probe"]


def test_the_real_loader_registers_a_phase_receiver(plugins_dir: Path) -> None:
    """If this fails, every hand-rolled registration in the other tests is a lie."""

    pipeline = _pipeline(plugins_dir)
    assert pipeline._load_plugin(plugins_dir / "phase_probe.py") is True

    assert "phase_probe" in pipeline._phase_receivers
    receiver = pipeline._phase_receivers["phase_probe"]
    assert receiver.plugin is _loaded(pipeline)
    assert receiver.generation == pipeline._plugin_generations["phase_probe"]


def test_delivery_reaches_a_really_loaded_plugin(plugins_dir: Path) -> None:
    pipeline = _pipeline(plugins_dir)
    pipeline._load_plugin(plugins_dir / "phase_probe.py")

    entry = _entry()
    pipeline.notify_phase_change(entry)
    pipeline._publish_phase_entry()

    assert _loaded(pipeline).pending_phase_event is entry


def test_notify_then_real_reload_then_publish_does_not_reach_the_replacement(
    plugins_dir: Path,
) -> None:
    """The hazard, through the real lifecycle rather than a simulated one.

    `plugins/*.py` is watched by mtime and reloaded into the running engine, so
    a replacement instance appearing between a transition and its delivery is
    ordinary. It must not be handed a phase it was never there for.
    """

    pipeline = _pipeline(plugins_dir)
    source = plugins_dir / "phase_probe.py"
    pipeline._load_plugin(source)
    original = _loaded(pipeline)

    entry = _entry()
    pipeline.notify_phase_change(entry)  # transition recorded...

    pipeline._unload_plugin("phase_probe")  # ...real reload before delivery
    pipeline._load_plugin(source)
    replacement = _loaded(pipeline)
    assert replacement is not original, "the reload did not produce a new instance"

    pipeline._publish_phase_entry()

    assert replacement.pending_phase_event is None, (
        "a plugin loaded between the transition and its delivery was handed a "
        "historical phase entry, through the real loader"
    )
    assert original.pending_phase_event is None


def test_a_later_transition_reaches_the_reloaded_plugin(plugins_dir: Path) -> None:
    """Forgetful, not deaf — the replacement still gets what happens next."""

    pipeline = _pipeline(plugins_dir)
    source = plugins_dir / "phase_probe.py"
    pipeline._load_plugin(source)

    pipeline.notify_phase_change(_entry("vacuum", 1_000.0))
    pipeline._unload_plugin("phase_probe")
    pipeline._load_plugin(source)
    pipeline._publish_phase_entry()

    later = _entry("cooldown", 2_000.0)
    pipeline.notify_phase_change(later)
    pipeline._publish_phase_entry()

    assert _loaded(pipeline).pending_phase_event is later


def test_unloading_drops_the_receiver(plugins_dir: Path) -> None:
    pipeline = _pipeline(plugins_dir)
    pipeline._load_plugin(plugins_dir / "phase_probe.py")
    pipeline._unload_plugin("phase_probe")

    assert "phase_probe" not in pipeline._phase_receivers
    assert "phase_probe" not in pipeline._plugins
