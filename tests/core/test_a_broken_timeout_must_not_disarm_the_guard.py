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
