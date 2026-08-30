"""A periodic live source that loses authority must name the condition that took it.

WHY THIS MODULE EXISTS. Sixteen places construct `PeriodicLiveDiscontinuity`, and every
one of them produced the same sentence. The supervisor turns that into the health code
`periodic_engine_unavailable` and stops there. So a run whose periodic reporter never
allocates a slot -- and therefore never seals a receipt, and therefore refuses the
assistant fault at the end -- left no evidence of WHICH of the sixteen conditions fired.
That is the difference between a week-long run that can be diagnosed and one that cannot.

Measured on Ubuntu 22.04 on 2026-08-20: the reporter flapped between `ready` and
`degraded_runtime` about once a second for a whole run, `active` never left `null`, and
the only thing the evidence said was `periodic_engine_unavailable`.
"""

from __future__ import annotations

import ast
import logging
import time
from pathlib import Path

import pytest

from cryodaq.agents.assistant import periodic_runtime

_SOURCE_PATH = Path(periodic_runtime.__file__)


def test_the_reason_reaches_the_message_and_the_attribute() -> None:
    failure = periodic_runtime.PeriodicLiveDiscontinuity("the engine barrier produced no cut")

    assert failure.reason == "the engine barrier produced no cut"
    assert "because=the engine barrier produced no cut" in str(failure)


def test_it_is_still_the_exception_the_supervisor_catches() -> None:
    """The supervisor selects on the base class, so the reason must not change the type."""

    failure = periodic_runtime.PeriodicLiveDiscontinuity("anything")
    assert isinstance(failure, periodic_runtime.PeriodicSourceUnavailable)


def test_every_construction_site_names_its_condition() -> None:
    """A new site must not be able to appear unnamed.

    Checked by parsing, not by searching for text: `PeriodicLiveDiscontinuity()` written
    across two lines defeats a substring search, and that is exactly how the next unnamed
    site would arrive.
    """

    tree = ast.parse(_SOURCE_PATH.read_text(encoding="utf-8"))
    unnamed: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "PeriodicLiveDiscontinuity":
            continue
        if not node.args and not node.keywords:
            unnamed.append(node.lineno)

    assert not unnamed, f"these lines construct a discontinuity without naming it: {unnamed}"


def test_the_default_is_visible_rather_than_silent() -> None:
    """If a site ever does arrive unnamed, the evidence must say so in words."""

    assert periodic_runtime.PeriodicLiveDiscontinuity().reason == "unstated"


def test_the_reason_is_written_to_the_log(caplog: pytest.LogCaptureFixture) -> None:
    periodic_runtime._last_discontinuity_log.clear()
    with caplog.at_level(logging.WARNING, logger=periodic_runtime.__name__):
        periodic_runtime.PeriodicLiveDiscontinuity("a held frame is out of sequence")

    assert any("a held frame is out of sequence" in record.getMessage() for record in caplog.records)


def test_one_reason_repeating_does_not_flood_the_log(caplog: pytest.LogCaptureFixture) -> None:
    """The measured flap is about once a second, and a week of that is unreadable."""

    periodic_runtime._last_discontinuity_log.clear()
    with caplog.at_level(logging.WARNING, logger=periodic_runtime.__name__):
        for _ in range(50):
            periodic_runtime.PeriodicLiveDiscontinuity("the same condition every time")

    written = [r for r in caplog.records if "the same condition every time" in r.getMessage()]
    assert len(written) == 1, f"the limiter let {len(written)} lines through"


def test_a_DIFFERENT_reason_is_never_suppressed(caplog: pytest.LogCaptureFixture) -> None:
    """Rate limiting must not hide the reason that changed -- that one is the diagnosis."""

    periodic_runtime._last_discontinuity_log.clear()
    with caplog.at_level(logging.WARNING, logger=periodic_runtime.__name__):
        for _ in range(20):
            periodic_runtime.PeriodicLiveDiscontinuity("the first condition")
        periodic_runtime.PeriodicLiveDiscontinuity("the second condition, which is the new fact")

    assert any("the second condition" in r.getMessage() for r in caplog.records)


def test_the_limiter_lets_the_reason_through_again_after_its_interval(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A run lasting a week must keep saying it, or a stale line reads as one event."""

    periodic_runtime._last_discontinuity_log.clear()
    with caplog.at_level(logging.WARNING, logger=periodic_runtime.__name__):
        periodic_runtime.PeriodicLiveDiscontinuity("a recurring condition")
        # Age the record rather than sleeping for the interval.
        periodic_runtime._last_discontinuity_log["a recurring condition"] = (
            time.monotonic() - periodic_runtime._DISCONTINUITY_LOG_INTERVAL_S - 1.0
        )
        periodic_runtime.PeriodicLiveDiscontinuity("a recurring condition")

    written = [r for r in caplog.records if "a recurring condition" in r.getMessage()]
    assert len(written) == 2, f"the limiter wrote {len(written)} lines, not two"
