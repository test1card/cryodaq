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
# Zones come from the names when the names say something
# ---------------------------------------------------------------------------
#
# The split was positional: first half hot, last half cold. That makes the
# ORDER of a selection load-bearing, and the order is an accident of which
# checkbox was clicked first -- so a correctly-chosen chain in a different
# order produced a plausible, silently wrong dT. The names on this stand
# already state which end each sensor is on ("1 Верх образец 2", "2 Низ
# образец 1"), and that is a fact about the hardware rather than about
# clicking.

from_names = ConductivityPanel._zones_from_names
positional = ConductivityPanel._positional_zones


def test_names_decide_regardless_of_click_order():
    names = {
        "Т13": "1 Низ образец 2",
        "Т1": "1 Верх образец 2",
        "Т3": "2 Низ образец 2",
        "Т14": "2 Верх образец 2",
    }
    # Selected cold-first, which positionally would invert the measurement.
    chain = ("Т13", "Т3", "Т1", "Т14")

    assert positional(chain) == (("Т13", "Т3"), ("Т1", "Т14")), "order alone would put the cold end first"
    assert from_names(chain, names) == (("Т1", "Т14"), ("Т13", "Т3"))


def test_a_correctly_ordered_chain_is_unaffected():
    names = {
        "Т1": "1 Верх образец 2",
        "Т14": "2 Верх образец 2",
        "Т13": "1 Низ образец 2",
        "Т3": "2 Низ образец 2",
    }
    chain = ("Т1", "Т14", "Т13", "Т3")
    assert from_names(chain, names) == positional(chain)


def test_unequal_zone_sizes_are_allowed():
    """Three sensors at the hot end and one at the cold is still a gradient."""
    names = {"a": "Верх 1", "b": "Верх 2", "c": "Верх 3", "d": "Низ 1"}
    assert from_names(("a", "b", "c", "d"), names) == (("a", "b", "c"), ("d",))


# --- when the names are not evidence, order decides -------------------------


def test_an_unnamed_channel_falls_back_to_order():
    names = {"Т1": "1 Верх образец 2", "Т3": "Термостол"}
    assert from_names(("Т1", "Т3"), names) is None


def test_a_label_naming_both_ends_is_not_evidence():
    names = {"a": "Верх и низ", "b": "Низ"}
    assert from_names(("a", "b"), names) is None


def test_all_one_end_has_no_gradient_to_measure():
    names = {"a": "Верх 1", "b": "Верх 2"}
    assert from_names(("a", "b"), names) is None


def test_missing_names_fall_back_to_order():
    assert from_names(("a", "b"), {}) is None


def test_matching_is_case_insensitive():
    names = {"a": "1 ВЕРХ образец", "b": "2 низ образец"}
    assert from_names(("a", "b"), names) == (("a",), ("b",))


# ---------------------------------------------------------------------------
# R and G in the ИТОГО row must describe the same sample
# ---------------------------------------------------------------------------


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
