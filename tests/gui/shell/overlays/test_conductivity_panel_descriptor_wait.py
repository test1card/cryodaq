"""The channel-identity wait must be sized to the instrument, not to a constant.

Codex, bound to c9d1326ea: the panel waited a fixed 10 000 ms for channel
identity.  The channel registry permits a poll interval up to 86 400 s, so a
HEALTHY, SUPPORTED instrument slower than ten seconds never supplied its
descriptor in time and the sweep returned itself to idle.

These live in a sibling module rather than in test_conductivity_panel.py on
purpose: four red-reproduction receipts bind that file's whole blob, and
appending to it invalidates evidence that has nothing to do with this change.
"""

from __future__ import annotations

import os
from collections import deque

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.gui.shell.overlays.conductivity_panel import (
    _AUTO_DESCRIPTOR_WAIT_FLOOR_MS,
    ConductivityPanel,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def test_descriptor_wait_is_the_floor_before_any_cadence_is_observed(app) -> None:
    """The first connection has no cadence, so the floor applies unchanged."""

    panel = ConductivityPanel()
    panel._auto_pending_start_temperature_channels = ("Т1", "Т2")
    panel._auto_pending_start_power_channel = None
    panel._auto_cadence_gaps.clear()

    assert panel._auto_descriptor_wait_ms() == int(_AUTO_DESCRIPTOR_WAIT_FLOOR_MS)


def test_descriptor_wait_grows_with_a_slow_instruments_observed_cadence(app) -> None:
    """A healthy slow instrument must not be timed out before its first reading.

    Codex P2 at c9d1326ea: a fixed 10-second bound expires before the first
    descriptor-bearing reading of an instrument whose configured poll_interval_s
    exceeds 10 s - the registry permits up to 86 400 s - so a HEALTHY supported
    configuration returned the sweep to idle instead of starting.

    This is the third fixed 10-second bound in this file, and the two notes above
    it already explain why fixed bounds are wrong here. The wait now scales with
    the slowest channel actually being waited on.
    """

    panel = ConductivityPanel()
    panel._auto_pending_start_temperature_channels = ("Т1", "Т2")
    panel._auto_pending_start_power_channel = None
    panel._auto_cadence_gaps.clear()
    # Т2 is a legitimate 30-second feed; Т1 is fast.
    panel._auto_cadence_gaps["Т1"] = deque([1.0, 1.0, 1.0])
    panel._auto_cadence_gaps["Т2"] = deque([30.0, 30.0, 30.0])

    waited_ms = panel._auto_descriptor_wait_ms()
    assert waited_ms > int(_AUTO_DESCRIPTOR_WAIT_FLOOR_MS), "a 30-second feed was still given the 10-second floor"
    assert waited_ms >= 30_000, f"the wait cannot be shorter than one cadence: {waited_ms}"


def test_an_unrelated_slow_channel_does_not_inflate_the_descriptor_wait(app) -> None:
    """Only channels actually being waited on may widen the bound.

    The sibling helpers in this file make the same restriction, for the same
    reason: an unrelated slow feed must not make every Start wait for it.
    """

    panel = ConductivityPanel()
    panel._auto_pending_start_temperature_channels = ("Т1",)
    panel._auto_pending_start_power_channel = None
    panel._auto_cadence_gaps.clear()
    panel._auto_cadence_gaps["Т1"] = deque([1.0, 1.0, 1.0])
    panel._auto_cadence_gaps["Т9"] = deque([600.0, 600.0, 600.0])  # not bound here

    assert panel._auto_descriptor_wait_ms() == int(_AUTO_DESCRIPTOR_WAIT_FLOOR_MS)


def test_the_descriptor_timer_is_started_with_the_derived_wait_not_the_floor(app) -> None:
    """Pin the CALL SITE, not only the helper.

    The three guards above call `_auto_descriptor_wait_ms()` directly, so they stay
    green against a mutant that reverts line 1760 to the bare floor constant - which
    is the whole defect back in production with a green suite. That is the same
    vacuous shape that four guards in this candidate were caught in, so the wiring
    gets its own guard: seed a slow cadence, drive the real wait path, and read the
    interval off the timer the production code actually starts.
    """

    panel = ConductivityPanel()
    panel._auto_cadence_gaps.clear()
    panel._auto_cadence_gaps["Т1"] = deque([45.0, 45.0, 45.0])  # a legitimate slow feed

    panel._wait_for_auto_descriptors(
        powers=[1.0],
        temperature_channels=("Т1",),
        power_channel="P1",
        stabilization_threshold_pct=1.0,
        minimum_wait_s=1.0,
    )

    assert panel._auto_descriptor_wait_timer.isActive(), "the wait was never started"
    assert panel._auto_descriptor_wait_timer.interval() > int(_AUTO_DESCRIPTOR_WAIT_FLOOR_MS), (
        "the timer was started with the fixed floor, so a slow instrument is still timed out before its first reading"
    )
    panel._auto_descriptor_wait_timer.stop()
