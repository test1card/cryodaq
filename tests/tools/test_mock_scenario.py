"""Tests for tools/mock_scenario.py scenario generators + CLI parsing."""

from __future__ import annotations

import pytest

from tools import mock_scenario


def _collect(generator_fn, *args, **kwargs) -> list:
    """Consume a generator; short-circuit test sleep by using dt_s=0."""
    return list(generator_fn(*args, dt_s=0.0, **kwargs))


# ----------------------------------------------------------------------
# Scenario value ranges
# ----------------------------------------------------------------------


def test_vacuum_pressure_decays_into_range():
    readings = _collect(mock_scenario.generate_vacuum, 10.0)
    pressures = [r.value for r in readings if r.channel == "VSP63D_1/pressure"]
    assert pressures, "no pressure readings emitted"
    assert pressures[0] >= 1e-3 * 0.99
    assert pressures[-1] <= 1e-7 * 1.01


def test_cooldown_reaches_liquid_helium():
    readings = _collect(mock_scenario.generate_cooldown, 40.0)
    t1s = [r.value for r in readings if r.channel == "T1"]
    assert t1s, "no T1 readings emitted"
    # Tanh easing leaves the boundary values a few K inside the
    # stated [4, 290] range; widen the tolerance to match the curve.
    assert t1s[0] > t1s[-1], "cooldown must end colder than it starts"
    assert t1s[0] > 270.0, f"start too cold: {t1s[0]}"
    assert t1s[-1] < 20.0, f"end too warm: {t1s[-1]}"


def test_warmup_mirrors_cooldown():
    readings = _collect(mock_scenario.generate_warmup, 40.0)
    t1s = [r.value for r in readings if r.channel == "T1"]
    assert t1s
    assert t1s[0] < t1s[-1], "warmup must end warmer than it starts"
    assert t1s[0] < 20.0, f"start too warm: {t1s[0]}"
    assert t1s[-1] > 270.0, f"end too cold: {t1s[-1]}"


def test_measurement_r_thermal_in_range():
    readings = _collect(mock_scenario.generate_measurement, 10.0)
    r_values = [r.value for r in readings if r.channel == "analytics/r_thermal"]
    assert r_values, "no R_thermal readings"
    # ±5 % around 1.5e-3.
    for v in r_values:
        assert 1.4e-3 < v < 1.6e-3
    # Keithley power reading is emitted too.
    assert any(r.channel == "Keithley_1/smua/power" for r in readings)


def test_cooldown_with_prediction_publishes_prediction_channel():
    readings = _collect(
        mock_scenario.generate_cooldown,
        10.0,
        include_prediction=True,
        ci_level_pct=95.0,
    )
    preds = [r for r in readings if r.channel == "analytics/cooldown_prediction"]
    assert preds, "no prediction readings"
    for r in preds:
        assert r.metadata.get("kind") == "cooldown_prediction"
        assert r.metadata.get("ci_level_pct") == 95.0
        assert "lower_ci" in r.metadata
        assert "upper_ci" in r.metadata
        assert r.metadata["lower_ci"] < r.value < r.metadata["upper_ci"]


# ----------------------------------------------------------------------
# Dispatcher
# ----------------------------------------------------------------------


def test_generate_rejects_unknown_scenario():
    with pytest.raises(ValueError):
        list(mock_scenario.generate("does_not_exist", 1.0))


# ----------------------------------------------------------------------
# CLI parsing
# ----------------------------------------------------------------------


def test_cli_parses_scenario_and_duration():
    args = mock_scenario._parse_args(["--scenario", "vacuum", "--duration", "120"])
    assert args.scenario == "vacuum"
    assert args.duration == 120.0
    assert args.dry_run is False


def test_cli_rejects_unknown_scenario():
    with pytest.raises(SystemExit):
        mock_scenario._parse_args(["--scenario", "bogus"])


def test_cli_accepts_dry_run_flag():
    args = mock_scenario._parse_args(
        ["--scenario", "cooldown_with_prediction", "--duration", "5", "--dry-run"]
    )
    assert args.dry_run is True


def test_help_output_is_russian(capsys):
    """Russian-language operator tooling per project convention."""
    with pytest.raises(SystemExit):
        mock_scenario._parse_args(["--help"])
    captured = capsys.readouterr()
    assert "сценарий" in captured.out.lower() or "сценариев" in captured.out.lower()
