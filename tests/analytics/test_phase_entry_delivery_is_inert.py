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
    pipeline._plugins = {"p": plugin}  # type: ignore[assignment]

    entry = _entry()
    pipeline.notify_phase_change(entry)
    pipeline._publish_phase_entry()

    assert plugin.pending_phase_event is entry


def test_a_plugin_that_did_not_opt_in_is_untouched() -> None:
    pipeline = _pipeline()
    plugin = _NotOptedIn()
    pipeline._plugins = {"p": plugin}  # type: ignore[assignment]

    pipeline.notify_phase_change(_entry())
    pipeline._publish_phase_entry()

    assert "pending_phase_event" not in vars(plugin)


def test_a_blocking_descriptor_is_never_executed() -> None:
    """The P1, reproduced: no getter, no setter, no 0.15 s on the loop."""

    _BlockingDescriptor.touched = []
    pipeline = _pipeline()
    plugin = _BlockingDescriptor()
    pipeline._plugins = {"p": plugin}  # type: ignore[assignment]

    pipeline.notify_phase_change(_entry())
    started = time.monotonic()
    pipeline._publish_phase_entry()
    elapsed = time.monotonic() - started

    assert _BlockingDescriptor.touched == [], (
        f"delivery executed plugin descriptor code: {_BlockingDescriptor.touched}"
    )
    assert elapsed < 0.05, (
        f"delivery blocked the caller for {elapsed:.3f}s — a plugin descriptor ran"
    )


def test_hostile_attribute_access_is_not_invoked() -> None:
    """A plugin may override __getattribute__ entirely; delivery still must not
    become an execution path into it."""

    _HostileAttributeAccess.seen = []
    pipeline = _pipeline()
    plugin = _HostileAttributeAccess()
    _HostileAttributeAccess.seen = []  # ignore construction
    pipeline._plugins = {"p": plugin}  # type: ignore[assignment]

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
    pipeline._plugins = {"p": _Slotted()}  # type: ignore[assignment]
    pipeline.notify_phase_change(_entry())
    pipeline._publish_phase_entry()  # must not raise


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def test_a_plugin_loaded_after_the_transition_is_not_told_about_it() -> None:
    """The second P1: a hot-reloaded plugin must not adopt a historical phase.

    `plugins/*.py` is watched by mtime and reloaded into the RUNNING engine, so
    a fresh instance appearing after a phase change is the normal case, not an
    exotic one. Handing it the old entry made it re-base its baseline on a
    transition it never saw — silently, and at a moment nothing else marked.
    """

    pipeline = _pipeline()
    present = _OptedIn()
    pipeline._plugins = {"p": present}  # type: ignore[assignment]

    entry = _entry()
    pipeline.notify_phase_change(entry)
    pipeline._publish_phase_entry()
    assert present.pending_phase_event is entry

    # The reload: a new instance replaces the old one.
    reloaded = _OptedIn()
    pipeline._plugins = {"p": reloaded}  # type: ignore[assignment]
    pipeline._publish_phase_entry()

    assert reloaded.pending_phase_event is None, (
        "a plugin loaded after the transition was handed a historical phase entry"
    )


def test_publishing_twice_does_not_redeliver() -> None:
    pipeline = _pipeline()
    plugin = _OptedIn()
    pipeline._plugins = {"p": plugin}  # type: ignore[assignment]

    pipeline.notify_phase_change(_entry())
    pipeline._publish_phase_entry()
    plugin.pending_phase_event = None  # the plugin consumed it in process()
    pipeline._publish_phase_entry()

    assert plugin.pending_phase_event is None, "a consumed entry was delivered again"


def test_a_genuinely_new_transition_still_arrives_after_a_reload() -> None:
    """Clearing must not make the pipeline deaf — only forgetful of the past."""

    pipeline = _pipeline()
    pipeline._plugins = {"p": _OptedIn()}  # type: ignore[assignment]
    pipeline.notify_phase_change(_entry("vacuum", 1_000.0))
    pipeline._publish_phase_entry()

    reloaded = _OptedIn()
    pipeline._plugins = {"p": reloaded}  # type: ignore[assignment]

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
