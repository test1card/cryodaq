"""No plugin code runs on any path the phase change introduced.

The first attempt executed plugin hooks directly in the experiment-phase command
handler. The correction moved them to the analytics task — which is the SAME
asyncio event loop, so a `time.sleep(0.15)` hook still blocked it for 0.15 s.
Moving blocking work between asyncio tasks is not isolation.

So the hook is gone. The pipeline stores one immutable `PhaseEntry` and hands it
over by plain attribute assignment; plugins that care consume it inside their own
`process()`, which is plugin code the pipeline already runs and already accounts
for. These tests hold that line: no method on a plugin is called by either step.
"""

from __future__ import annotations

from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.core.phase_event import PhaseEntry


class _Landmine:
    """Every callable on it fails the test if the pipeline touches it."""

    plugin_id = "landmine"

    def __init__(self) -> None:
        self.pending_phase_event = None

    def notify_phase_change(self, *_a, **_k):
        raise AssertionError("the pipeline must not call plugin methods to deliver a phase")

    def process(self, *_a, **_k):
        raise AssertionError("process() must only be called by the batch loop")


class _Opted:
    plugin_id = "opted"

    def __init__(self) -> None:
        self.pending_phase_event = None


class _NotOpted:
    plugin_id = "not_opted"


def _pipeline() -> PluginPipeline:
    from pathlib import Path
    from unittest.mock import MagicMock

    return PluginPipeline(MagicMock(), Path("plugins"))


def _entry(phase: str = "cooldown", started_at: float = 1000.0) -> PhaseEntry:
    return PhaseEntry(experiment_id="exp", phase=phase, started_at=started_at)


def _register(pipe, plugin_id: str, plugin: object) -> None:
    """Register a plugin the way the loader does.

    Recipients are captured on the plugin-load path now, not discovered by
    introspecting plugin objects at publication time — that introspection was
    itself the execution path into plugin code these tests exist to forbid. A
    harness that assigns `_plugins` directly therefore registers no recipient
    and would show "nothing delivered" for the wrong reason.
    """

    pipe._next_plugin_generation += 1
    generation = pipe._next_plugin_generation
    pipe._plugins[plugin_id] = plugin
    pipe._plugin_generations[plugin_id] = generation
    receiver = pipe._capture_phase_receiver(plugin_id, plugin, generation)
    if receiver is not None:
        pipe._phase_receivers[plugin_id] = receiver


def test_the_command_handler_call_touches_no_plugin() -> None:
    """This is the blocker: the sync call must do nothing but store a value."""

    pipe = _pipeline()
    mine = _Landmine()
    _register(pipe, "landmine", mine)

    pipe.notify_phase_change(_entry())

    assert mine.pending_phase_event is None, "not even the attribute is written yet"


def test_publishing_calls_no_plugin_method_either() -> None:
    """Plain attribute assignment. A hook could block; an assignment cannot."""

    pipe = _pipeline()
    mine = _Landmine()
    _register(pipe, "landmine", mine)

    pipe.notify_phase_change(_entry())
    pipe._publish_phase_entry()

    assert mine.pending_phase_event is not None, "delivered without calling anything"


def test_a_plugin_that_does_not_opt_in_is_left_alone() -> None:
    pipe = _pipeline()
    plain = _NotOpted()
    opted = _Opted()
    _register(pipe, "plain", plain)
    _register(pipe, "opted", opted)

    pipe.notify_phase_change(_entry())
    pipe._publish_phase_entry()

    assert not hasattr(plain, "pending_phase_event")
    assert opted.pending_phase_event is not None


def test_only_the_latest_entry_is_published() -> None:
    """Latest-only is sufficient BECAUSE the entry carries its own identity."""

    pipe = _pipeline()
    opted = _Opted()
    _register(pipe, "opted", opted)

    pipe.notify_phase_change(_entry("vacuum", 1000.0))
    pipe.notify_phase_change(_entry("cooldown", 2000.0))
    pipe._publish_phase_entry()

    assert opted.pending_phase_event.phase == "cooldown"


def test_a_re_entry_is_distinguishable_from_a_duplicate() -> None:
    """`vacuum -> cooldown -> vacuum` must not collapse into "no change".

    A bare latest-only string lost this; the identity triple keeps it.
    """

    first = _entry("vacuum", 1000.0)
    again = _entry("vacuum", 3000.0)

    assert first.identity() != again.identity()
    assert first.phase == again.phase


def test_publishing_before_any_entry_does_nothing() -> None:
    pipe = _pipeline()
    opted = _Opted()
    _register(pipe, "opted", opted)

    pipe._publish_phase_entry()

    assert opted.pending_phase_event is None
