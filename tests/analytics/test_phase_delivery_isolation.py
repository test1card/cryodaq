"""Phase delivery must not run plugin code on the engine's command handler.

From the 47b6c9ca review: notify_phase_change executed arbitrary duck-typed
plugin code synchronously from the experiment-phase command handler, on the
engine event loop. A slow or blocking hook could stall acquisition, persistence
and safety scheduling. A try/except isolates exceptions; it does not isolate
blocking work.
"""

from __future__ import annotations

from cryodaq.analytics.plugin_loader import PluginPipeline


class _Recorder:
    plugin_id = "recorder"

    def __init__(self) -> None:
        self.seen: list[str | None] = []

    def notify_phase_change(self, phase):
        self.seen.append(phase)


class _Blocking:
    plugin_id = "blocking"

    def __init__(self) -> None:
        self.entered = False

    def notify_phase_change(self, phase):
        self.entered = True
        raise RuntimeError("slow or broken hook")


def _pipeline() -> PluginPipeline:
    from pathlib import Path
    from unittest.mock import MagicMock

    return PluginPipeline(MagicMock(), Path("plugins"))


def test_the_command_handler_call_runs_no_plugin_code() -> None:
    """This is the blocker: the sync call must be O(1)."""

    pipe = _pipeline()
    rec = _Recorder()
    pipe._plugins = {"recorder": rec}

    pipe.notify_phase_change("cooldown")

    assert rec.seen == [], "no plugin may run on the command handler's loop"
    assert pipe._pending_phase == "cooldown"
    assert pipe._pending_phase_set is True


def test_delivery_happens_on_the_analytics_task() -> None:
    pipe = _pipeline()
    rec = _Recorder()
    pipe._plugins = {"recorder": rec}

    pipe.notify_phase_change("vacuum")
    pipe._deliver_pending_phase()

    assert rec.seen == ["vacuum"]
    assert pipe._pending_phase_set is False, "delivered once, not repeatedly"


def test_a_second_delivery_without_a_new_phase_does_nothing() -> None:
    pipe = _pipeline()
    rec = _Recorder()
    pipe._plugins = {"recorder": rec}

    pipe.notify_phase_change("vacuum")
    pipe._deliver_pending_phase()
    pipe._deliver_pending_phase()

    assert rec.seen == ["vacuum"]


def test_one_raising_plugin_does_not_stop_the_others() -> None:
    pipe = _pipeline()
    bad, good = _Blocking(), _Recorder()
    pipe._plugins = {"blocking": bad, "recorder": good}

    pipe.notify_phase_change("cooldown")
    pipe._deliver_pending_phase()

    assert bad.entered is True
    assert good.seen == ["cooldown"], "a raising hook must not swallow the fanout"


def test_only_the_latest_phase_is_delivered() -> None:
    """Rapid transitions collapse: the plugin needs the current phase, not a log."""

    pipe = _pipeline()
    rec = _Recorder()
    pipe._plugins = {"recorder": rec}

    pipe.notify_phase_change("vacuum")
    pipe.notify_phase_change("cooldown")
    pipe._deliver_pending_phase()

    assert rec.seen == ["cooldown"]


def test_a_plugin_without_the_hook_is_skipped() -> None:
    class _Plain:
        plugin_id = "plain"

    pipe = _pipeline()
    pipe._plugins = {"plain": _Plain(), "recorder": (rec := _Recorder())}
    pipe.notify_phase_change("warmup")
    pipe._deliver_pending_phase()
    assert rec.seen == ["warmup"]
