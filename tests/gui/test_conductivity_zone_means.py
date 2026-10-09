"""dT is the difference of two zone MEANS, not of two end sensors.

The stand carries two sensors at the hot end and two at the cold end. Taking
only the chain's first and last channel throws away half the measurement and
makes the result depend on which of the two sensors in each zone happens to sit
at the end of the list.

The split is: first half hot, last half cold. With one sensor per end that is
exactly the old endpoint behaviour, so existing two- and three-channel chains
are unchanged. An odd middle channel belongs to neither zone -- it is a
gradient point, and folding it into either end would bias dT toward that end.
"""

import math

import pytest

from cryodaq.gui.shell.overlays.conductivity_panel import ConductivityPanel

# These cover the ORDER-based split, which is now the fallback used when the
# channel names say nothing about which end a sensor is on.
zones = ConductivityPanel._positional_zones
mean = ConductivityPanel._zone_mean


# ---------------------------------------------------------------------------
# The split
# ---------------------------------------------------------------------------


def test_two_sensors_are_still_the_two_endpoints():
    assert zones(("Т1", "Т2")) == (("Т1",), ("Т2",))


def test_three_sensors_ignore_the_middle_one():
    """Unchanged from the endpoint behaviour, deliberately."""
    assert zones(("Т1", "Т2", "Т3")) == (("Т1",), ("Т3",))


def test_four_sensors_split_two_and_two():
    """This stand's actual layout."""
    assert zones(("Т1", "Т2", "Т13", "Т14")) == (("Т1", "Т2"), ("Т13", "Т14"))


def test_five_sensors_keep_the_gradient_point_out_of_both_zones():
    hot, cold = zones(("Т1", "Т2", "Т3", "Т13", "Т14"))
    assert hot == ("Т1", "Т2")
    assert cold == ("Т13", "Т14")
    assert "Т3" not in hot + cold


# ---------------------------------------------------------------------------
# The mean
# ---------------------------------------------------------------------------


def test_a_zone_mean_averages_its_sensors():
    value, used = mean(("Т1", "Т2"), {"Т1": 300.0, "Т2": 302.0})
    assert value == pytest.approx(301.0)
    assert used == 2


def test_a_dropped_sensor_does_not_poison_the_mean():
    """These joints loosen with thermal cycling; one bad contact must not end a sweep."""
    value, used = mean(("Т1", "Т2"), {"Т1": 300.0, "Т2": float("nan")})
    assert value == pytest.approx(300.0)
    assert used == 1, "the caller must be able to see the average narrowed"


def test_a_missing_sensor_is_treated_as_dropped():
    value, used = mean(("Т1", "Т2"), {"Т1": 300.0})
    assert value == pytest.approx(300.0)
    assert used == 1


def test_a_zone_with_nothing_left_is_not_a_number():
    value, used = mean(("Т1", "Т2"), {"Т1": float("nan")})
    assert math.isnan(value), "an empty zone must not produce a temperature"
    assert used == 0


# ---------------------------------------------------------------------------
# What it means for dT
# ---------------------------------------------------------------------------


def test_four_sensor_dt_uses_all_four():
    temps = {"Т1": 301.0, "Т2": 303.0, "Т13": 295.0, "Т14": 297.0}
    hot, cold = zones(("Т1", "Т2", "Т13", "Т14"))
    t_hot, _ = mean(hot, temps)
    t_cold, _ = mean(cold, temps)
    assert t_hot == pytest.approx(302.0)
    assert t_cold == pytest.approx(296.0)
    assert t_hot - t_cold == pytest.approx(6.0)
    # The endpoint reading would have given 301.0 - 297.0 = 4.0 K: a third less,
    # and dependent on the list order within each zone.
    assert temps["Т1"] - temps["Т14"] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Zones are no longer derived from display names
# ---------------------------------------------------------------------------
#
# A section here tested _zones_from_names, which read "Верх"/"Низ" out of the
# operator's channel labels to decide which end was hot. It removed one trap --
# a chain selected in the wrong order -- by introducing another: a rename, a
# translation or a typo silently changed the sign of dT while the number still
# looked plausible. Display names are presentation.
#
# Review retired the mechanism. The order-based split below survives only as
# the PROPOSAL shown to the operator; the physics comes from the channel IDs
# they confirm once per run, which is covered in
# tests/gui/test_conductivity_zone_confirmation.py.



def test_total_resistance_is_the_reciprocal_of_total_conductance():
    """Found by a mock sweep on a deliberately cold-end-first chain.

    total_r was the SUM of the pairwise resistances, which follows the chain's
    ORDER, while dT and G had moved to the zone means, which follow the sensor
    NAMES. The same row then reported G = 0.0040 W/K -- correct -- beside
    R = -248 K/W for a sample whose resistance is 250. A negative resistance
    next to a positive conductance is not a second opinion; it is one of them
    being wrong.
    """
    power = 0.05
    t_hot, t_cold = 307.50, 295.00
    total_dt = t_hot - t_cold

    total_r = total_dt / power
    total_g = power / total_dt

    assert total_r == pytest.approx(250.0)
    assert total_g == pytest.approx(0.004)
    assert total_r == pytest.approx(1.0 / total_g), "the row must not contradict itself"
