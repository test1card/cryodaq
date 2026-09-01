"""Pressure forecast at fixed horizons.

An ETA answers "when do we reach X" and is undefined whenever X is unreachable
— which, on a stand whose gauge bottoms out above the interesting range, is
most of the time. The horizon forecast answers "where will we be", which is
always defined, and is what an operator reads to decide whether to wait.
"""

import math

import pytest

from cryodaq.analytics.vacuum_trend import VacuumTrendPredictor


def _pumping_predictor(**overrides):
    config = {
        "window_s": 21600,
        "update_interval_s": 0,
        "min_points": 60,
        "targets_mbar": [1e-1, 1e-2],
        **overrides,
    }
    predictor = VacuumTrendPredictor(config=config)
    # A decelerating pump-down: 1000 mbar, then an outgassing tail.
    predictor.push(0.0, 1000.0)
    for index in range(1, 4000):
        t = index * 5.0
        pressure = 0.05 + 40.0 * (t + 600.0) ** -1.0
        predictor.push(t, pressure)
    predictor.update()
    return predictor


def test_forecast_is_reported_at_the_configured_horizons():
    prediction = _pumping_predictor().get_prediction()
    assert list(prediction.horizon_forecast) == ["1", "3", "6", "12", "24", "48"]


def test_horizons_are_configurable():
    prediction = _pumping_predictor(forecast_horizons_h=[2, 8]).get_prediction()
    assert list(prediction.horizon_forecast) == ["2", "8"]


def test_forecast_pressures_are_finite_and_positive():
    prediction = _pumping_predictor().get_prediction()
    values = list(prediction.horizon_forecast.values())
    assert values
    assert all(math.isfinite(v) and v > 0 for v in values)


def test_forecast_decreases_while_pumping_down():
    prediction = _pumping_predictor().get_prediction()
    values = [prediction.horizon_forecast[h] for h in ("1", "3", "6", "12", "24", "48")]
    assert values == sorted(values, reverse=True)


def test_forecast_exists_even_when_no_target_is_reachable():
    # The whole point: targets far below the achievable floor report no ETA,
    # and the operator still needs to know where the pressure is heading.
    predictor = _pumping_predictor(targets_mbar=[1e-9])
    prediction = predictor.get_prediction()
    assert all(eta is None for eta in prediction.eta_targets.values())
    assert prediction.horizon_forecast


def test_insufficient_data_reports_no_forecast():
    predictor = VacuumTrendPredictor(config={"update_interval_s": 0, "min_points": 60})
    predictor.push(0.0, 1000.0)
    predictor.update()
    assert predictor.get_prediction().horizon_forecast == {}


@pytest.mark.parametrize("bad", [[0], [-1], ["x"], [True]])
def test_invalid_horizons_are_rejected(bad):
    predictor = VacuumTrendPredictor(config={"forecast_horizons_h": bad})
    assert predictor.forecast_horizons_h == []
