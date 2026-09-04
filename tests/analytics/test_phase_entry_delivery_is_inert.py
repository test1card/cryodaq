"""Handing a phase entry to a plugin must run no plugin code, and must not
reach a plugin that was not there for the transition.

Two P1 findings, same delivery path:

1. `hasattr` + `setattr` go through `__getattribute__` / `__setattr__`. A
   plugin declaring `pending_phase_event` as a property — or overriding
   attribute access at all — therefore ran its own code inside the pipeline, on
   the shared engine event loop. Reproduced with a blocking descriptor.

2. The pipeline retained the latest entry indefinitely, so a plugin loaded or
   hot-reloaded afterwards was handed a transition from before it existed,
   treated it as fresh, and could re-base its baseline on a phase it never saw.

Both are about the same mistake in different clothing: delivery was doing more
than delivering.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from cryodaq.analytics.plugin_loader import PluginPipeline
from cryodaq.core.phase_event import PhaseEntry


def _entry(phase: str = "cooldown", started_at: float = 1_000.0) -> PhaseEntry:
    return PhaseEntry(experiment_id="exp-1", phase=phase, started_at=started_at)


def _pipeline() -> PluginPipeline:
    return PluginPipeline(MagicMock(), Path("plugins"))


def _register(pipeline: PluginPipeline, plugin_id: str, plugin: object) -> None:
    """Register a plugin exactly as the loader does, generation and all.

    Tests that poke `_plugins` directly would not exercise the receiver capture
    or the generation bump, and it is the generation that closes the reload
    window — so the harness has to do what the real load path does.
    """

    pipeline._next_plugin_generation += 1
    generation = pipeline._next_plugin_generation
    pipeline._plugins[plugin_id] = plugin  # type: ignore[assignment]
    pipeline._plugin_generations[plugin_id] = generation
    receiver = pipeline._capture_phase_receiver(plugin_id, plugin, generation)  # type: ignore[arg-type]
    if receiver is None:
        pipeline._phase_receivers.pop(plugin_id, None)
    else:
        pipeline._phase_receivers[plugin_id] = receiver


class _OptedIn:
    """An ordinary consumer: declares the slot in __init__, like the real one."""

    def __init__(self) -> None:
        self.pending_phase_event: PhaseEntry | None = None


class _NotOptedIn:
    """Declares nothing; must never grow the attribute."""


class _BlockingDescriptor:
    """The reviewer's reproduction, as a class-level property.

    If delivery uses `hasattr`/`setattr`, both the getter and the setter run
    here — on the engine loop — and this records that they did. The sleep is
    what made it a P1 rather than a curiosity: it stalls acquisition.
    """

    touched: list[str] = []

    def __init__(self) -> None:
        self._value: PhaseEntry | None = None

    @property
    def pending_phase_event(self) -> PhaseEntry | None:
        type(self).touched.append("get")
        time.sleep(0.15)
        return self._value

    @pending_phase_event.setter
    def pending_phase_event(self, value: PhaseEntry | None) -> None:
        type(self).touched.append("set")
        time.sleep(0.15)
        self._value = value


class _HostileDict:
    """A blocking data descriptor named __dict__.

    This is what defeated the previous correction. `object.__getattribute__`
    bypasses an overridden `__getattribute__`, but `__dict__` is itself looked
    up on the TYPE, so a class-level property named `__dict__` still runs — and
    a blocking one stalls the engine loop exactly as the original `hasattr`
    did. The lesson is that there is no safe question to ask a plugin object on
    the publication path, which is why the destination is captured at load.
    """

    touched: list[str] = []

    def __init__(self) -> None:
        object.__setattr__(self, "_real", {"pending_phase_event": None})

    @property
    def __dict__(self):  # type: ignore[override]
        type(self).touched.append("dict")
        time.sleep(0.15)
        return object.__getattribute__(self, "_real")


class _HostileAttributeAccess:
    """Overrides attribute access itself, not just one name."""

    seen: list[str] = []

    def __init__(self) -> None:
        object.__setattr__(self, "pending_phase_event", None)

    def __getattribute__(self, name: str):
        if not name.startswith("__"):
            type(self).seen.append(f"get:{name}")
        return object.__getattribute__(self, name)

    def __setattr__(self, name: str, value) -> None:
        type(self).seen.append(f"set:{name}")
        object.__setattr__(self, name, value)


def test_delivery_reaches_a_plugin_that_opted_in() -> None:
    """The feature still has to work."""

    pipeline = _pipeline()
    plugin = _OptedIn()
    _register(pipeline, "p", plugin)

    entry = _entry()
    pipeline.notify_phase_change(entry)
    pipeline._publish_phase_entry()

    assert plugin.pending_phase_event is entry


def test_a_plugin_that_did_not_opt_in_is_untouched() -> None:
    pipeline = _pipeline()
    plugin = _NotOptedIn()
    _register(pipeline, "p", plugin)

    pipeline.notify_phase_change(_entry())
    pipeline._publish_phase_entry()

    assert "pending_phase_event" not in vars(plugin)


def test_a_blocking_descriptor_is_never_executed() -> None:
    """The P1, reproduced: no getter, no setter, no 0.15 s on the loop."""

    _BlockingDescriptor.touched = []
    pipeline = _pipeline()
    plugin = _BlockingDescriptor()
    _register(pipeline, "p", plugin)

    pipeline.notify_phase_change(_entry())
    started = time.monotonic()
    pipeline._publish_phase_entry()
    elapsed = time.monotonic() - started

    assert _BlockingDescriptor.touched == [], f"delivery executed plugin descriptor code: {_BlockingDescriptor.touched}"
    assert elapsed < 0.05, f"delivery blocked the caller for {elapsed:.3f}s — a plugin descriptor ran"


def test_a_hostile_dict_descriptor_executes_zero_times_during_publication() -> None:
    """The control the previous correction failed.

    Capture happens on the load path, where plugin code already runs, so the
    descriptor may fire there. What must never happen is a descriptor running
    during PUBLICATION — that is the engine loop, mid-batch.
    """

    pipeline = _pipeline()
    plugin = _HostileDict()
    _register(pipeline, "p", plugin)

    _HostileDict.touched = []  # ignore whatever capture cost at load time
    pipeline.notify_phase_change(_entry())
    started = time.monotonic()
    pipeline._publish_phase_entry()
    elapsed = time.monotonic() - started

    assert _HostileDict.touched == [], f"a __dict__ descriptor ran during publication: {_HostileDict.touched}"
    assert elapsed < 0.05, f"publication blocked for {elapsed:.3f}s on a __dict__ descriptor"


def test_hostile_attribute_access_is_not_invoked() -> None:
    """A plugin may override __getattribute__ entirely; delivery still must not
    become an execution path into it."""

    _HostileAttributeAccess.seen = []
    pipeline = _pipeline()
    plugin = _HostileAttributeAccess()
    _HostileAttributeAccess.seen = []  # ignore construction
    _register(pipeline, "p", plugin)

    pipeline.notify_phase_change(_entry())
    pipeline._publish_phase_entry()

    assert _HostileAttributeAccess.seen == [], (
        f"delivery went through the plugin's attribute hooks: {_HostileAttributeAccess.seen}"
    )
    # ...and the value still arrived, read without triggering the hook.
    assert object.__getattribute__(plugin, "__dict__")["pending_phase_event"] is not None


def test_a_slotted_plugin_is_skipped_rather_than_raising() -> None:
    class _Slotted:
        __slots__ = ()

    pipeline = _pipeline()
    _register(pipeline, "p", _Slotted())
    pipeline.notify_phase_change(_entry())
    pipeline._publish_phase_entry()  # must not raise


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def test_notify_then_reload_then_publish_does_not_reach_the_replacement() -> None:
    """The dangerous order, driven through the real load path.

    The previous test exercised `notify -> publish -> reload`, which is the SAFE
    sequence — the entry is already delivered and cleared before the reload. It
    asserted the wrong thing while claiming to cover the hazard.

    The hazard is `notify -> reload -> publish`: a transition is recorded, the
    plugin is hot-reloaded before the batch that would deliver it, and the fresh
    instance is handed a phase it was never there for. `plugins/*.py` is watched
    by mtime and reloaded into the running engine, so this window is ordinary.
    """

    pipeline = _pipeline()
    original = _OptedIn()
    _register(pipeline, "p", original)

    entry = _entry()
    pipeline.notify_phase_change(entry)  # transition recorded...
    replacement = _OptedIn()
    _register(pipeline, "p", replacement)  # ...plugin reloaded before delivery
    pipeline._publish_phase_entry()

    assert replacement.pending_phase_event is None, (
        "a plugin loaded between the transition and its delivery was handed a historical phase entry"
    )
    assert original.pending_phase_event is None, "the retired instance must not be written to either"


def test_an_unchanged_recipient_still_receives_across_that_window() -> None:
    """The guard must not be so strict that ordinary delivery stops working."""

    pipeline = _pipeline()
    plugin = _OptedIn()
    _register(pipeline, "p", plugin)

    entry = _entry()
    pipeline.notify_phase_change(entry)
    pipeline._publish_phase_entry()

    assert plugin.pending_phase_event is entry


def test_publishing_twice_does_not_redeliver() -> None:
    pipeline = _pipeline()
    plugin = _OptedIn()
    _register(pipeline, "p", plugin)

    pipeline.notify_phase_change(_entry())
    pipeline._publish_phase_entry()
    plugin.pending_phase_event = None  # the plugin consumed it in process()
    pipeline._publish_phase_entry()

    assert plugin.pending_phase_event is None, "a consumed entry was delivered again"


def test_a_genuinely_new_transition_still_arrives_after_a_reload() -> None:
    """Clearing must not make the pipeline deaf — only forgetful of the past."""

    pipeline = _pipeline()
    _register(pipeline, "p", _OptedIn())
    pipeline.notify_phase_change(_entry("vacuum", 1_000.0))
    pipeline._publish_phase_entry()

    reloaded = _OptedIn()
    _register(pipeline, "p", reloaded)

    later = _entry("cooldown", 2_000.0)
    pipeline.notify_phase_change(later)
    pipeline._publish_phase_entry()

    assert reloaded.pending_phase_event is later


@pytest.mark.parametrize("phase", ["vacuum", "cooldown", "vacuum"])
def test_re_entry_to_the_same_phase_is_a_distinct_entry(phase: str) -> None:
    """Identity is the whole triple, so vacuum -> cooldown -> vacuum is three."""

    first = PhaseEntry("exp-1", phase, 1_000.0)
    second = PhaseEntry("exp-1", phase, 2_000.0)
    assert first.identity() != second.identity()
