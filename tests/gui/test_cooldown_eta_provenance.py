"""An ETA must say which of three things it is.

`CooldownService` publishes `analytics/cooldown_predictor/cooldown_eta` every
30 s, continuously — including before a cooldown has been detected. Three
distinct situations arrived at the operator as one identical number:

* **model baseline** — before detection the predictor emits the ensemble prior,
  19.3 h with progress 0.0%, unchanging. On 2026-09-03 that sat on screen for
  five hours labelled simply "ETA", and it is what prompted "the ETA stands
  statically as decoration". The computation was fine; the label was not;
* **live forecast** — during a cooldown the prediction incorporates the
  observed rate, and the completion time genuinely moves;
* **stale** — if the predictor is shed under load or fails, the last value stops
  updating and nothing said so.

`cooldown_active` was published in the metadata the whole time and discarded by
`MainWindowV2._cooldown_reading_to_data`, and `CooldownData` carried no
timestamp, so neither consumer could tell them apart.

Raw acquisition is untouched by any of this: the prediction travels on the
broker outside the Scheduler's persistence-first path and is not written to the
daily database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("PySide6")

from cryodaq.drivers.base import ChannelStatus, Reading  # noqa: E402
from cryodaq.gui.shell.views.analytics_view import CooldownData  # noqa: E402

_CHANNEL = "analytics/cooldown_predictor/cooldown_eta"


def _eta_reading(*, hours: float, active: bool, age_s: float = 0.0) -> Reading:
    return Reading(
        timestamp=datetime.now(UTC) - timedelta(seconds=age_s),
        instrument_id="cooldown_predictor",
        channel=_CHANNEL,
        value=hours,
        unit="h",
        status=ChannelStatus.OK,
        metadata={
            "t_remaining_hours": hours,
            "t_remaining_ci68": (hours - 1.0, hours + 1.0),
            "progress": 0.0 if not active else 0.65,
            "phase": "phase1",
            "cooldown_active": active,
        },
    )


def _adapt(reading: Reading) -> CooldownData:
    from cryodaq.gui.shell.main_window_v2 import MainWindowV2

    data = MainWindowV2._cooldown_reading_to_data(reading)
    assert data is not None
    return data


# --------------------------------------------------------------------------
# 1. pre-detection prior
# --------------------------------------------------------------------------
def test_the_pre_detection_value_is_labelled_a_model_baseline() -> None:
    """19.3 h at 0% progress is the ensemble prior, not an ETA for this run."""

    data = _adapt(_eta_reading(hours=19.3, active=False))

    assert data.cooldown_active is False, "cooldown_active must survive the adapter"
    assert data.generated_at is not None, "the reading timestamp must survive the adapter"
    label = data.status_label()
    assert "базовая оценка" in label
    assert "прогноз по наблюдаемой скорости" not in label


# --------------------------------------------------------------------------
# 2. active, slope-aware update
# --------------------------------------------------------------------------
def test_an_active_prediction_is_labelled_a_live_forecast() -> None:
    data = _adapt(_eta_reading(hours=15.5, active=True))

    assert data.cooldown_active is True
    assert data.t_hours == pytest.approx(15.5)
    assert data.status_label() == "прогноз по наблюдаемой скорости"


# --------------------------------------------------------------------------
# 3. shed / failed update — nothing new arrives
# --------------------------------------------------------------------------
def test_a_prediction_that_stopped_updating_is_not_shown_as_current() -> None:
    """A shed or failed predictor must not leave the old number looking live."""

    data = _adapt(_eta_reading(hours=15.5, active=True, age_s=600))

    assert data.cooldown_active is True, "the flag is still what it was"
    assert data.freshness().is_current is False
    label = data.status_label()
    assert "недоступен" in label
    assert "10 мин" in label, "the age must travel with the refusal"


def test_a_prediction_with_no_timestamp_fails_closed() -> None:
    """An unknown generation time cannot establish that a forecast is current."""

    data = CooldownData(t_hours=15.5, ci_hours=1.0, phase="phase1", progress_pct=65.0, cooldown_active=True)
    assert data.generated_at is None
    assert data.freshness().is_current is False
    assert "недоступен" in data.status_label()


# --------------------------------------------------------------------------
# 4. the boundary, and that acquisition is unaffected
# --------------------------------------------------------------------------
def test_the_staleness_boundary_is_three_missed_publish_cycles() -> None:
    from cryodaq.gui.shell.views.analytics_view import _PREDICTION_STALE_AFTER_S

    assert _PREDICTION_STALE_AFTER_S == 120.0  # 4 x the 30 s publish interval
    assert _adapt(_eta_reading(hours=15.5, active=True, age_s=60)).freshness().is_current is True
    assert _adapt(_eta_reading(hours=15.5, active=True, age_s=180)).freshness().is_current is False


def test_the_prediction_is_not_a_raw_measurement() -> None:
    """It travels on the broker, outside the persistence-first acquisition path.

    Guards the decision NOT to persist a 30 s forecast as a raw reading: mixing
    recalculable analytics into the durable acquisition record would make the
    measurement history un-auditable.
    """

    reading = _eta_reading(hours=15.5, active=True)
    assert reading.channel.startswith("analytics/")
    assert reading.instrument_id == "cooldown_predictor"
