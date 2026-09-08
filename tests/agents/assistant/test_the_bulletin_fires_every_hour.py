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
@pytest.mark.parametrize("jump", [600.0, 3599.0, 3600.0, 3720.0, 7200.0])
async def test_a_clock_jump_forward_does_not_publish_twice(
    monkeypatch: pytest.MonkeyPatch, jump: float
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
            # A WHOLE INTERVAL, not ten minutes. A small step leaves the chosen
            # boundary the nearest one and hides the defect; a step of about an
            # interval lands the cycle on a boundary already served and the one
            # after it already due.
            clock.now += jump

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


@pytest.mark.asyncio
async def test_two_starts_a_second_apart_do_not_both_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """astra's second finding: the cold-start rule and the arrival tolerance
    disagree. `_next_boundary` treats a target as unserved while the delay is
    still positive, and the loop publishes as soon as the delay is inside five
    seconds — so a process started in that five-second window publishes at
    once, and a restart a second later publishes the same bulletin again.
    """

    interval = 3600.0
    lead = assistant_main._tick_lead(interval)
    # Four seconds before the target: inside the arrival tolerance.
    just_before_target = 1_757_002_800.0 - lead - 4.0

    # Both starts wait for the SAME boundary, so their absolute fire times
    # coincide — that is correct, not a duplicate. What must not happen is
    # either of them publishing the moment it starts, which is what makes a
    # restart inside the window send the bulletin a second time.
    for offset in (0.0, 1.0):
        start = just_before_target + offset
        clock = _Clock(start)
        monkeypatch.setattr(assistant_main.time, "time", clock.time)
        bus = _Bus(clock, wanted=1)
        with pytest.raises(_StopAfterEnough):
            await assistant_main._periodic_report_tick(
                _Config(), bus, _Cache(), sleep=clock.sleep
            )
        waited = bus.fired_at[0] - start
        assert waited >= interval / 2.0, (
            f"a start {offset:.0f} s into the arrival window published after "
            f"{waited:.0f} s; a restart would send the same bulletin again"
        )


@pytest.mark.parametrize("step_back", [60.0, 1800.0, 3600.0])
@pytest.mark.asyncio
async def test_a_clock_step_backwards_does_not_publish_twice(
    monkeypatch: pytest.MonkeyPatch, step_back: float
) -> None:
    """There was a test for this that never called the tick.

    It ran a private copy of the delay arithmetic and counted sleeps, so it
    stayed green against any tick at all — astra checked by replacing the real
    one with a function that raises, and it still passed. Drive the real loop
    and count what reached the bus.
    """

    interval = 3600.0
    clock = _Clock(1_757_000_000.0)
    stepped = {"done": False}

    async def stepping_sleep(seconds: float) -> None:
        clock.now += seconds
        if not stepped["done"]:
            stepped["done"] = True
            clock.now -= step_back

    monkeypatch.setattr(assistant_main.time, "time", clock.time)
    bus = _Bus(clock, wanted=2)

    with pytest.raises(_StopAfterEnough):
        await assistant_main._periodic_report_tick(
            _Config(), bus, _Cache(), sleep=stepping_sleep
        )

    gap = bus.fired_at[1] - bus.fired_at[0]
    assert gap >= interval / 2.0, (
        f"two bulletins {gap:.0f} s apart after the clock stepped back "
        f"{step_back:.0f} s; the same hour was reported twice"
    )
