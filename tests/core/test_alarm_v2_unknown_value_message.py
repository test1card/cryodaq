"""Alarm messages must not substitute 0.0 for a value the evaluator never had.

Two paths passed a literal ``0.0`` into the ``{value}`` slot of the operator
message template:

* ``_eval_stale`` — the channel is stale/unusable, so there IS no current
  reading, yet the message read "Датчик X: 0.0 K".
* ``_rate_event`` — reached when the rate is unknown (too few points, or the
  channel is unusable), yet the message read "... (0.0 K/мин)".

Both alarms are correct to fire. Firing behaviour is unchanged; an unavailable
rate is omitted from ``values`` so downstream consumers cannot mistake it for
a measured zero.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from cryodaq.core.alarm_config import SetpointDef
from cryodaq.core.alarm_providers import ExperimentPhaseProvider, ExperimentSetpointProvider
from cryodaq.core.alarm_v2 import AlarmEvaluator
from cryodaq.core.channel_state import ChannelStateTracker
from cryodaq.core.rate_estimator import RateEstimator
from cryodaq.drivers.base import Reading

_CH = "T12"


def _reading(value: float, ts: float | None = None) -> Reading:
    return Reading(
        timestamp=datetime.fromtimestamp(ts if ts is not None else time.time(), tz=UTC),
        instrument_id="LS218",
        channel=_CH,
        value=value,
        unit="K",
    )


def _evaluator() -> tuple[ChannelStateTracker, RateEstimator, AlarmEvaluator]:
    state = ChannelStateTracker()
    rate = RateEstimator(window_s=120.0, min_points=2)
    mgr = MagicMock()
    mgr.get_current_phase.return_value = None
    mgr.get_active_experiment.return_value = None
    mgr.get_phase_history.return_value = []
    evaluator = AlarmEvaluator(
        state,
        rate,
        ExperimentPhaseProvider(mgr),
        ExperimentSetpointProvider(mgr, dict[str, SetpointDef]()),
    )
    return state, rate, evaluator


# ---------------------------------------------------------------------------
# stale
# ---------------------------------------------------------------------------


def test_stale_message_does_not_claim_the_sensor_read_zero() -> None:
    state, _rate, ev = _evaluator()
    # Last sample arrived 10 minutes ago at 77 K — the channel is stale now.
    state.update(_reading(77.0, ts=time.time() - 600))

    event = ev.evaluate(
        "sensor_stale",
        {
            "alarm_type": "stale",
            "channel": _CH,
            "timeout_s": 30.0,
            "level": "WARNING",
            "message": "Датчик {channel}: {value} K — данные устарели.",
        },
    )

    assert event is not None, "stale alarm must still fire"
    assert "0.0" not in event.message, f"stale message claims a zero reading: {event.message!r}"
    assert event.message == "Датчик T12: — K — данные устарели."


def test_stale_message_with_format_spec_still_renders_template() -> None:
    """A template using {value:.2f} must degrade to the dash, not to '0.00'."""
    state, _rate, ev = _evaluator()
    state.update(_reading(77.0, ts=time.time() - 600))

    event = ev.evaluate(
        "sensor_stale",
        {
            "alarm_type": "stale",
            "channel": _CH,
            "timeout_s": 30.0,
            "message": "{channel} = {value:.2f} K (устарело)",
        },
    )

    assert event is not None
    assert "0.00" not in event.message, f"format spec re-introduced a fake zero: {event.message!r}"
    assert event.message == "T12 = — K (устарело)"


def test_stale_alarm_still_reports_staleness_age() -> None:
    """Firing behaviour and the values payload are unchanged."""
    state, _rate, ev = _evaluator()
    state.update(_reading(77.0, ts=time.time() - 600))

    event = ev.evaluate(
        "sensor_stale",
        {"alarm_type": "stale", "channel": _CH, "timeout_s": 30.0, "message": "stale {channel}"},
    )

    assert event is not None
    assert event.channels == [_CH]
    assert event.values[_CH] == pytest.approx(600.0, abs=5.0)


# ---------------------------------------------------------------------------
# rate (keep-active on unknown rate)
# ---------------------------------------------------------------------------


def _rate_cfg() -> dict:
    return {
        "alarm_type": "rate",
        "channel": _CH,
        "check": "rate_above",
        "threshold": 5.0,
        "level": "WARNING",
        "message": "Скорость охлаждения {channel} > 5 K/мин ({value} K/мин).",
    }


def test_unknown_rate_keep_active_message_does_not_claim_zero_rate() -> None:
    state, _rate, ev = _evaluator()
    # One sample only → RateEstimator (min_points=2) cannot produce a rate.
    state.update(_reading(80.0))

    event = ev.evaluate("cooldown_rate", _rate_cfg(), is_active=True)

    assert event is not None, "an active rate alarm must be held, not cleared, on unknown rate"
    assert "0.0" not in event.message, f"message claims a measured rate: {event.message!r}"
    assert event.message == "Скорость охлаждения T12 > 5 K/мин (— K/мин)."


def test_unknown_rate_does_not_fire_an_inactive_alarm() -> None:
    """Unchanged firing behaviour: ignorance never fires a fresh alarm."""
    state, _rate, ev = _evaluator()
    state.update(_reading(80.0))

    assert ev.evaluate("cooldown_rate", _rate_cfg(), is_active=False) is None


def test_known_rate_message_still_prints_the_number() -> None:
    state, rate, ev = _evaluator()
    now = time.time()
    # Two samples 60 s apart, +10 K → +10 K/min, above the 5 K/min threshold.
    for offset, value in ((-60.0, 80.0), (0.0, 90.0)):
        r = _reading(value, ts=now + offset)
        state.update(r)
        rate.push(r.channel, r.timestamp.timestamp(), r.value)

    event = ev.evaluate("cooldown_rate", _rate_cfg(), is_active=False)

    assert event is not None, "a real threshold breach must still fire"
    assert "—" not in event.message, f"a known rate was suppressed: {event.message!r}"
    assert event.values[_CH] > 5.0
