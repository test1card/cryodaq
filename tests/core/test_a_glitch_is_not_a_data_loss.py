"""A single bad sample must not raise a CRITICAL about a minute of silence.

On 2026-09-08 the pressure channel produced five `sensor_error` readings across
a whole day. Each one instantly fired `data_loss_pressure` — CRITICAL, "Нет
данных давления > 60с. Вакуумный контроль потерян." — and cleared two seconds
later. The persisted record held no gap longer than two seconds all day.

The evaluation was `not state.is_usable or (now - state.timestamp) > timeout`:
the timeout applied to the second branch only, so one unusable sample bypassed
it entirely. A CRITICAL that cries wolf is worse than no alarm, because it
teaches the operator to disbelieve the channel.

The question the alarm exists to ask is how long the channel has been without a
usable value. Silence and a bad status are the same loss; both must outlast the
configured timeout.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime

from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.drivers.base import ChannelStatus, Reading


def _reading(channel: str, value: float, *, when: float, status: ChannelStatus) -> Reading:
    return Reading(
        timestamp=datetime.fromtimestamp(when, tz=UTC),
        instrument_id="VSP63D_1",
        channel=channel,
        value=value,
        unit="mbar",
        status=status,
    )


def test_one_bad_sample_does_not_look_like_a_minute_of_silence() -> None:
    tracker = ChannelStateTracker()
    now = time.time()
    tracker.update(_reading("P", 2.4, when=now - 2.0, status=ChannelStatus.OK))
    tracker.update(_reading("P", math.nan, when=now, status=ChannelStatus.SENSOR_ERROR))

    state = tracker.get("P")

    assert state is not None
    assert now - state.last_usable_ts < 5.0, "a glitch reset the clock; the alarm will claim a minute of lost data"


def test_a_channel_that_stays_bad_still_ages_into_the_alarm() -> None:
    """Not firing on a glitch must not mean never firing."""
    tracker = ChannelStateTracker()
    now = time.time()
    tracker.update(_reading("P", 2.4, when=now - 300.0, status=ChannelStatus.OK))
    for step in range(10):
        tracker.update(_reading("P", math.nan, when=now - 200.0 + step, status=ChannelStatus.SENSOR_ERROR))

    state = tracker.get("P")

    assert state is not None
    assert now - state.last_usable_ts > 250.0, "a persistently broken channel never ages"


def test_a_channel_bad_from_its_very_first_reading_starts_its_clock() -> None:
    """With no usable reading ever, the clock starts at first sight rather than
    at the epoch — otherwise the alarm fires the instant the channel appears."""
    tracker = ChannelStateTracker()
    now = time.time()
    tracker.update(_reading("P", math.nan, when=now, status=ChannelStatus.SENSOR_ERROR))

    state = tracker.get("P")

    assert state is not None
    assert abs(state.last_usable_ts - now) < 5.0


def test_a_good_reading_after_a_glitch_moves_the_clock_forward() -> None:
    tracker = ChannelStateTracker()
    now = time.time()
    tracker.update(_reading("P", 2.4, when=now - 100.0, status=ChannelStatus.OK))
    tracker.update(_reading("P", math.nan, when=now - 50.0, status=ChannelStatus.SENSOR_ERROR))
    tracker.update(_reading("P", 2.5, when=now, status=ChannelStatus.OK))

    state = tracker.get("P")

    assert state is not None
    assert abs(state.last_usable_ts - now) < 5.0


def test_the_alarm_asks_one_question_not_two() -> None:
    """Structural: the two-branch form is what let the timeout be bypassed."""
    import inspect

    from cryodaq.core import alarm_v2

    import ast
    import textwrap

    source = inspect.getsource(alarm_v2.AlarmEvaluator._eval_stale)
    # Parsed, not grepped: the comment explaining the old form CONTAINS the old
    # form, so a substring check fails on its own documentation. That mistake
    # has now been made twice in this repository; this is the fix for it.
    tree = ast.parse(textwrap.dedent(source))
    conditions = [ast.unparse(node.test) for node in ast.walk(tree) if isinstance(node, ast.If)]
    assert any("silent_for > timeout" in c for c in conditions), conditions
    assert not [c for c in conditions if "is_usable" in c and " or " in c], (
        f"the timeout is bypassed again: {conditions}"
    )
    assert "last_usable_ts" in ast.unparse(tree)
