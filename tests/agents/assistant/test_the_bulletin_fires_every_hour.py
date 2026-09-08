"""The aligned bulletin must still fire once per interval.

`_seconds_until_next_tick` returns the time to the next boundary minus a lead,
and pushes to the following boundary whenever that value is not strictly
positive.  `asyncio.sleep` never returns early, so on waking the target has
always just been reached or just passed — the push therefore fires every time,
the recheck never sees a delay inside the arrival tolerance, and each of the
three rechecks sleeps another whole interval.

The bulletin then arrives once every three hours while claiming to be hourly.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cryodaq.agents import assistant_main


class _StopAfterEnough(BaseException):
    """Not an Exception: the tick catches those from publish and carries on."""


@dataclass
class _Config:
    periodic_report_interval_minutes: int = 60

    def get_periodic_report_interval_s(self) -> float:
        return float(self.periodic_report_interval_minutes * 60)


class _Bus:
    def __init__(self, clock: _Clock, wanted: int) -> None:
        self._clock = clock
        self._wanted = wanted
        self.fired_at: list[float] = []

    async def publish(self, event: object) -> None:
        self.fired_at.append(self._clock.now)
        if len(self.fired_at) >= self._wanted:
            raise _StopAfterEnough


class _Cache:
    active_experiment_id = "run-1"


class _Clock:
    """A clock that a sleep advances exactly, which is the best case."""

    def __init__(self, start: float) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.now += seconds


@pytest.mark.asyncio
async def test_an_hourly_bulletin_fires_once_an_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    interval = 3600.0
    clock = _Clock(1_757_000_000.0)
    monkeypatch.setattr(assistant_main.time, "time", clock.time)
    bus = _Bus(clock, wanted=4)

    with pytest.raises(_StopAfterEnough):
        await assistant_main._periodic_report_tick(
            _Config(), bus, _Cache(), sleep=clock.sleep
        )

    gaps = [b - a for a, b in zip(bus.fired_at, bus.fired_at[1:])]
    assert gaps, "the bulletin never fired twice"
    # EXACT. The clock here advances by precisely what each sleep asks for, so
    # any slack in this assertion is slack that hides a real drift: at ±60 s a
    # bulletin every 3541 s would still read as hourly.
    assert all(gap == interval for gap in gaps), (
        f"gaps between bulletins are {gaps}, expected exactly {interval} s each"
    )


@pytest.mark.asyncio
async def test_the_bulletin_keeps_the_boundary_it_was_aligned_to(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Firing hourly is not enough: it must fire just before the clock hour."""

    interval = 3600.0
    lead = min(assistant_main._PERIODIC_TICK_LEAD_S, interval / 4.0)
    clock = _Clock(1_757_000_000.0)
    monkeypatch.setattr(assistant_main.time, "time", clock.time)
    bus = _Bus(clock, wanted=3)

    with pytest.raises(_StopAfterEnough):
        await assistant_main._periodic_report_tick(
            _Config(), bus, _Cache(), sleep=clock.sleep
        )

    for fired in bus.fired_at:
        offset = (fired + lead) % interval
        assert min(offset, interval - offset) <= assistant_main._TICK_ARRIVAL_TOLERANCE_S, (
            f"fired at {fired}, which is {offset} s from a boundary minus the lead"
        )


@pytest.mark.asyncio
async def test_the_first_bulletin_does_not_wait_three_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gaps were fixed; the first one was not.

    `served_boundary` is None until something has been published, and the loop
    consults it on every recheck rather than once per cycle. So the cold-start
    rule — which treats a target already reached as belonging to a bulletin
    that went out before the restart — runs again at each of the three
    rechecks, and each pushes the first bulletin another interval away.
    """

    interval = 3600.0
    start = 1_757_000_000.0
    clock = _Clock(start)
    monkeypatch.setattr(assistant_main.time, "time", clock.time)
    bus = _Bus(clock, wanted=1)

    with pytest.raises(_StopAfterEnough):
        await assistant_main._periodic_report_tick(
            _Config(), bus, _Cache(), sleep=clock.sleep
        )

    waited = bus.fired_at[0] - start
    assert waited <= interval, (
        f"the first bulletin waited {waited / 3600.0:.2f} h, which is more than "
        f"the {interval / 3600.0:.0f} h interval it claims"
    )


@pytest.mark.asyncio
async def test_a_clock_jump_forward_does_not_publish_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rechecks must measure the distance to the boundary already chosen.

    They recompute one instead, from the current clock. A step forward during
    the sleep therefore lands the recheck on a LATER boundary than the cycle is
    waiting for, the loop still publishes for the earlier one, and the next
    cycle finds the later one already due — two bulletins back to back, with
    the first hour's report left without its summary.
    """

    interval = 3600.0
    clock = _Clock(1_757_000_000.0)
    jumped = {"done": False}

    async def stepping_sleep(seconds: float) -> None:
        clock.now += seconds
        if not jumped["done"]:
            jumped["done"] = True
            clock.now += 600.0  # the clock steps ten minutes forward mid-sleep

    monkeypatch.setattr(assistant_main.time, "time", clock.time)
    bus = _Bus(clock, wanted=2)

    with pytest.raises(_StopAfterEnough):
        await assistant_main._periodic_report_tick(
            _Config(), bus, _Cache(), sleep=stepping_sleep
        )

    gap = bus.fired_at[1] - bus.fired_at[0]
    assert gap >= interval / 2.0, (
        f"two bulletins {gap:.0f} s apart after a clock step; the second is a duplicate"
    )
