"""A nonsense `timeout_s` must not silently switch the data-loss guard off.

`_eval_stale` reads `timeout_s` straight out of the alarm YAML and compares
against it. A float NaN compares false against everything, so the guard never
fires and says nothing about why. A string or a null raises `TypeError`, which
`evaluate()` logs and turns into "no event" for an inactive alarm.

Either way the channel can be silent for hours and the CRITICAL that exists to
notice it stays quiet. On this stand that guard is the one that says vacuum
control has been lost.
"""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from cryodaq.core.alarm_v2 import AlarmEvaluator, PhaseProvider, SetpointProvider
from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.drivers.base import Reading


def _evaluator_with_a_channel_silent_for_an_hour() -> AlarmEvaluator:
    state = ChannelStateTracker()
    silent_since = time.time() - 3600.0
    state.update(
        Reading(
            timestamp=datetime.fromtimestamp(silent_since, tz=UTC),
            instrument_id="VSP63D_1",
            channel="P",
            value=2.4,
            unit="mbar",
        )
    )
    return AlarmEvaluator(
        state,
        RateEstimator(window_s=120.0, min_points=2),
        MagicMock(spec=PhaseProvider),
        SetpointProvider({}),
    )


def test_a_sane_timeout_still_fires() -> None:
    """The control: an hour of silence against a 60 s timeout is a data loss."""

    evaluator = _evaluator_with_a_channel_silent_for_an_hour()
    cfg = {"alarm_type": "stale", "channel": "P", "timeout_s": 60.0, "level": "CRITICAL"}

    assert evaluator.evaluate("data_loss_pressure", cfg) is not None


@pytest.mark.parametrize(
    "timeout",
    [math.nan, "60", None, -1.0, 0.0, math.inf],
    ids=["nan", "string", "null", "negative", "zero", "infinite"],
)
def test_a_broken_timeout_still_reports_an_hour_of_silence(timeout: object) -> None:
    evaluator = _evaluator_with_a_channel_silent_for_an_hour()
    cfg = {
        "alarm_type": "stale",
        "channel": "P",
        "timeout_s": timeout,
        "level": "CRITICAL",
    }

    event = evaluator.evaluate("data_loss_pressure", cfg)

    assert event is not None, (
        f"timeout_s={timeout!r} disarmed the guard: an hour of silence raised nothing"
    )
    assert event.level == "CRITICAL"
    assert event.channels == ["P"]


def _evaluator_with_a_channel_silent_for(seconds: float) -> AlarmEvaluator:
    state = ChannelStateTracker()
    state.update(
        Reading(
            timestamp=datetime.fromtimestamp(time.time() - seconds, tz=UTC),
            instrument_id="VSP63D_1",
            channel="P",
            value=2.4,
            unit="mbar",
        )
    )
    return AlarmEvaluator(
        state,
        RateEstimator(window_s=120.0, min_points=2),
        MagicMock(spec=PhaseProvider),
        SetpointProvider({}),
    )


@pytest.mark.parametrize("written", ["120", "120.0", " 120 "])
def test_a_timeout_written_as_a_string_is_still_that_timeout(written: str) -> None:
    """YAML quotes numbers all the time. Refusing the value and falling back to
    the 30 s default turns a 120 s guard into a 30 s one: a channel quiet for
    half a minute then raises a CRITICAL, and the operator's own message text
    may well claim a loss of two minutes that did not happen. A guard that
    cries wolf is the failure this file was written about.
    """

    cfg = {"alarm_type": "stale", "channel": "P", "timeout_s": written, "level": "CRITICAL"}

    quiet_for_a_minute = _evaluator_with_a_channel_silent_for(60.0)
    assert quiet_for_a_minute.evaluate("data_loss_pressure", cfg) is None, (
        f"timeout_s={written!r} fired after 60 s, so it was not read as 120"
    )

    quiet_for_five = _evaluator_with_a_channel_silent_for(300.0)
    assert quiet_for_five.evaluate("data_loss_pressure", cfg) is not None, (
        f"timeout_s={written!r} did not fire after 300 s"
    )


@pytest.mark.parametrize(
    "timeout",
    [math.nan, "abc", None, -1.0, 0.0, math.inf, True],
    ids=["nan", "words", "null", "negative", "zero", "infinite", "boolean"],
)
def test_an_unreadable_timeout_behaves_exactly_like_the_default(timeout: object) -> None:
    """Asserting only that SOMETHING fires after an hour is too weak: -1 and 0
    fired before the fix as well, and an implementation that turned every bad
    value into zero would pass. What the fallback promises is the DEFAULT
    threshold, so check both sides of it — quiet for less than the default is
    not an event, quiet for more is.
    """

    from cryodaq.core.alarm_v2 import _DEFAULT_STALE_TIMEOUT_S

    cfg = {"alarm_type": "stale", "channel": "P", "timeout_s": timeout, "level": "CRITICAL"}

    below = _evaluator_with_a_channel_silent_for(_DEFAULT_STALE_TIMEOUT_S / 2.0)
    assert below.evaluate("data_loss_pressure", cfg) is None, (
        f"timeout_s={timeout!r} fired before the default threshold; a bad value "
        f"became something shorter than the default rather than the default"
    )

    above = _evaluator_with_a_channel_silent_for(_DEFAULT_STALE_TIMEOUT_S * 3.0)
    assert above.evaluate("data_loss_pressure", cfg) is not None, (
        f"timeout_s={timeout!r} did not fire past the default threshold"
    )
