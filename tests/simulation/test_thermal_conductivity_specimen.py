"""The specimen must answer the heater, and answer with the conductance it was given.

The acceptance test for this whole module is
``test_the_measurement_recovers_the_conductance_it_was_built_from``: put a known k into the
specimen, read the thermometers, run the arithmetic the operator's panel runs, and get that
k back. Everything else here pins one property that test depends on.
"""

from __future__ import annotations

import math

import pytest

from cryodaq.simulation.thermal_conductivity import (
    SpecimenNode,
    SpecimenSegment,
    ThermalConductivitySpecimen,
    default_conductivity_w_per_m_k,
    default_specific_heat_j_per_kg_k,
)

#: Constant properties make the closed forms exact, so a failure is the model's and not the
#: property curve's. The default curves get their own tests below.
_K = 12.0
_CP = 300.0
_AREA = 1.0e-4
_LENGTH = 0.05


def _constant_specimen(node_count: int = 4, *, initial_temperature_k: float = 80.0) -> ThermalConductivitySpecimen:
    nodes = [SpecimenNode(channel=f"T{index}", mass_kg=0.02) for index in range(node_count)]
    segments = [SpecimenSegment(length_m=_LENGTH, area_m2=_AREA) for _ in range(node_count - 1)]
    return ThermalConductivitySpecimen(
        nodes,
        segments,
        initial_temperature_k=initial_temperature_k,
        conductivity_w_per_m_k=lambda _t: _K,
        specific_heat_j_per_kg_k=lambda _t: _CP,
    )


def test_the_measurement_recovers_the_conductance_it_was_built_from() -> None:
    """Put a known k in; read it back through the panel's own arithmetic.

    The operator's panel computes, for one adjacent pair, ``G = P / (T_hot - T_cold)``.
    At steady state every watt the heater puts in crosses every segment, so that quotient
    must equal ``k * A / L`` for the segment between them. If it does not, a simulated
    sweep would teach the operator a number the specimen does not have.
    """

    specimen = _constant_specimen()
    expected_conductance = _K * _AREA / _LENGTH

    # Settled far below what is asserted: a steady-state claim cannot be tighter
    # than the tolerance the specimen was actually settled to.
    state = specimen.settle(heater_power_w=0.02, sink_temperature_k=80.0, tolerance_k=1e-12)
    assert not state.substep_limited, "the specimen must settle, or this measures a transient"

    for hot, cold in zip(specimen.channels[:-1], specimen.channels[1:], strict=True):
        measured = state.pair_conductance_w_per_k(hot, cold)
        assert measured == pytest.approx(expected_conductance, rel=1e-6), (hot, cold, measured)


def test_steady_state_matches_the_series_conductance_of_the_chain() -> None:
    """End to end, the chain is its segments in series, and nothing else."""

    specimen = _constant_specimen(node_count=5)
    power = 0.015
    sink = 60.0
    # Settled far below what is asserted: a steady-state claim cannot be tighter
    # than the tolerance the specimen was actually settled to.
    state = specimen.settle(heater_power_w=power, sink_temperature_k=sink, tolerance_k=1e-12)

    segment_conductance = _K * _AREA / _LENGTH
    expected_total_drop = power * (len(specimen.channels) - 1) / segment_conductance
    measured_total_drop = state.temperatures_k[specimen.channels[0]] - sink

    assert measured_total_drop == pytest.approx(expected_total_drop, rel=1e-6)


def test_doubling_the_heater_doubles_every_gradient() -> None:
    """With properties held constant the specimen is linear, and must behave like it."""

    # Settled far below what is asserted: a steady-state claim cannot be tighter
    # than the tolerance the specimen was actually settled to.
    single = _constant_specimen().settle(heater_power_w=0.01, sink_temperature_k=70.0, tolerance_k=1e-12)
    double = _constant_specimen().settle(heater_power_w=0.02, sink_temperature_k=70.0, tolerance_k=1e-12)

    for hot, cold in zip(single.temperatures_k, list(single.temperatures_k)[1:], strict=False):
        one = single.temperatures_k[hot] - single.temperatures_k[cold]
        two = double.temperatures_k[hot] - double.temperatures_k[cold]
        assert two == pytest.approx(2.0 * one, rel=1e-6), (hot, cold, one, two)


def test_zero_power_leaves_the_specimen_at_the_sink() -> None:
    """No heat in, no gradient. A simulator that drifts here would look like sensor drift."""

    specimen = _constant_specimen(initial_temperature_k=120.0)
    state = specimen.settle(heater_power_w=0.0, sink_temperature_k=40.0)

    for channel in specimen.channels:
        assert state.temperatures_k[channel] == pytest.approx(40.0, abs=1e-4), channel


def test_a_single_segment_relaxes_with_its_own_time_constant() -> None:
    """One mass across one conductance is a first-order lag, and must show it.

    This is the property that makes a run worth watching: the thermometers arrive at the
    answer over a real time, so the settling predictor has something to predict.
    """

    mass_kg = 0.02
    conductance = _K * _AREA / _LENGTH
    tau_s = mass_kg * _CP / conductance

    specimen = ThermalConductivitySpecimen(
        [SpecimenNode(channel="hot", mass_kg=mass_kg), SpecimenNode(channel="cold", mass_kg=mass_kg)],
        [SpecimenSegment(length_m=_LENGTH, area_m2=_AREA)],
        initial_temperature_k=50.0,
        conductivity_w_per_m_k=lambda _t: _K,
        specific_heat_j_per_kg_k=lambda _t: _CP,
    )
    power = 0.01
    final_gap = power / conductance

    state = specimen.advance(tau_s, heater_power_w=power, sink_temperature_k=50.0)
    gap = state.temperatures_k["hot"] - state.temperatures_k["cold"]

    assert gap == pytest.approx(final_gap * (1.0 - math.exp(-1.0)), rel=2e-3), (gap, final_gap)


def test_a_long_step_lands_where_many_short_steps_land() -> None:
    """A caller's step length must not change the physics.

    Without an internal stability bound, a step longer than the fastest node's time
    constant makes the temperatures oscillate -- which in a soak is indistinguishable from
    instrument noise, and is the worst way for this module to fail.
    """

    coarse = _constant_specimen().advance(4000.0, heater_power_w=0.02, sink_temperature_k=75.0)

    fine_specimen = _constant_specimen()
    for _ in range(4000):
        fine = fine_specimen.advance(1.0, heater_power_w=0.02, sink_temperature_k=75.0)

    for channel in fine_specimen.channels:
        assert coarse.temperatures_k[channel] == pytest.approx(fine.temperatures_k[channel], rel=1e-6), channel


def test_the_same_inputs_give_identical_numbers() -> None:
    """Two runs of one recipe must agree bit for bit, or evidence cannot be compared."""

    first = _constant_specimen().advance(500.0, heater_power_w=0.017, sink_temperature_k=64.0)
    second = _constant_specimen().advance(500.0, heater_power_w=0.017, sink_temperature_k=64.0)

    assert dict(first.temperatures_k) == dict(second.temperatures_k)


def test_a_colder_specimen_shows_a_larger_gradient_for_the_same_power() -> None:
    """The default curve exists to make a temperature sweep say something.

    It is a stand-in, not a datum -- but its SHAPE has to be right, or a simulated sweep
    would show a flat conductance and teach the operator the opposite of what cryogenic
    solids do.
    """

    gradients = []
    for sink in (20.0, 200.0):
        specimen = ThermalConductivitySpecimen(
            [SpecimenNode(channel="hot", mass_kg=0.02), SpecimenNode(channel="cold", mass_kg=0.02)],
            [SpecimenSegment(length_m=_LENGTH, area_m2=_AREA)],
            initial_temperature_k=sink,
        )
        state = specimen.settle(heater_power_w=0.005, sink_temperature_k=sink)
        gradients.append(state.temperatures_k["hot"] - state.temperatures_k["cold"])

    cold_gradient, warm_gradient = gradients
    assert cold_gradient > warm_gradient, gradients
    assert default_conductivity_w_per_m_k(20.0) < default_conductivity_w_per_m_k(200.0)
    assert default_specific_heat_j_per_kg_k(20.0) < default_specific_heat_j_per_kg_k(200.0)


def test_an_isothermal_pair_reports_no_conductance_rather_than_a_large_one() -> None:
    """A conductance is not defined across zero difference, and must not be invented.

    Measured while writing this: a specimen relaxed with the heater off does NOT reach an
    exactly equal pair -- it settles to within about two ten-millionths of a kelvin -- and
    the quotient there is a well-defined zero, not the undefined case. The undefined case
    is an exactly equal pair, which is what a freshly built specimen has.
    """

    specimen = _constant_specimen()
    fresh = specimen.state(heater_power_w=0.01)
    assert fresh.temperatures_k["T0"] == fresh.temperatures_k["T1"], "the premise of this test"
    assert math.isnan(fresh.pair_conductance_w_per_k("T0", "T1"))

    relaxed = specimen.settle(heater_power_w=0.0, sink_temperature_k=45.0)
    assert relaxed.pair_conductance_w_per_k("T0", "T1") == 0.0, "no heat in, no conductance measured"


def test_settle_says_when_it_ran_out_of_time_instead_of_settling() -> None:
    """A timeout that reads as a settled specimen would seal a false measurement."""

    specimen = _constant_specimen()
    state = specimen.settle(heater_power_w=0.02, sink_temperature_k=70.0, tolerance_k=1e-12, max_seconds=1.0)

    assert state.substep_limited is True


@pytest.mark.parametrize(
    ("power_w", "sink_k", "max_seconds"),
    [
        (math.nan, 80.0, 1e6),
        (math.inf, 80.0, 1e6),
        (-math.inf, 80.0, 1e6),
        (0.01, 0.0, 1e6),
        (0.01, -40.0, 1e6),
        (0.01, math.nan, 1e6),
        (0.01, math.inf, 1e6),
        (0.01, 80.0, 0.0),
        (0.01, 80.0, -1.0),
        (0.01, 80.0, math.inf),
        (0.01, 80.0, math.nan),
    ],
)
def test_an_impossible_settle_is_refused_without_touching_the_specimen(power_w, sink_k, max_seconds) -> None:
    """``settle`` integrates exactly like ``advance``, so it must refuse like ``advance``.

    A NaN or infinite drive accepted here would poison every thermometer downstream of the
    step -- the same cascade ``advance`` is tested against -- and a non-positive or
    non-finite budget would either spin forever or come back as a fabricated timeout.
    """

    specimen = _constant_specimen()
    before = dict(specimen.state().temperatures_k)
    with pytest.raises(ValueError):
        specimen.settle(heater_power_w=power_w, sink_temperature_k=sink_k, max_seconds=max_seconds)
    assert dict(specimen.state().temperatures_k) == before, "a refused settle must not mutate state"


@pytest.mark.parametrize(
    ("nodes", "segments", "message"),
    [
        ([SpecimenNode(channel="only", mass_kg=1.0)], [], "at least two"),
        (
            [SpecimenNode(channel="a", mass_kg=1.0), SpecimenNode(channel="b", mass_kg=1.0)],
            [],
            "need 1 segments",
        ),
        (
            [SpecimenNode(channel="same", mass_kg=1.0), SpecimenNode(channel="same", mass_kg=1.0)],
            [SpecimenSegment(length_m=_LENGTH, area_m2=_AREA)],
            "its own channel",
        ),
    ],
)
def test_a_specimen_that_cannot_be_measured_is_refused_at_construction(nodes, segments, message) -> None:
    """A geometry error is a programming mistake, and must surface where it was made."""

    with pytest.raises(ValueError, match=message):
        ThermalConductivitySpecimen(nodes, segments, initial_temperature_k=80.0)


@pytest.mark.parametrize(
    ("mass_kg", "length_m", "area_m2"),
    [(0.0, _LENGTH, _AREA), (-1.0, _LENGTH, _AREA), (1.0, 0.0, _AREA), (1.0, _LENGTH, -1.0), (math.nan, 1.0, 1.0)],
)
def test_a_geometry_that_is_not_a_solid_is_refused(mass_kg, length_m, area_m2) -> None:
    with pytest.raises(ValueError):
        SpecimenNode(channel="node", mass_kg=mass_kg)
        SpecimenSegment(length_m=length_m, area_m2=area_m2)


@pytest.mark.parametrize(
    ("duration_s", "power_w", "sink_k"),
    [(-1.0, 0.01, 80.0), (math.nan, 0.01, 80.0), (1.0, math.inf, 80.0), (1.0, 0.01, 0.0), (1.0, 0.01, math.nan)],
)
def test_an_impossible_step_is_refused_rather_than_integrated(duration_s, power_w, sink_k) -> None:
    """Integrating a NaN quietly poisons every reading downstream of it."""

    specimen = _constant_specimen()
    with pytest.raises(ValueError):
        specimen.advance(duration_s, heater_power_w=power_w, sink_temperature_k=sink_k)


def test_sliced_time_that_accumulates_exactly_lands_bit_for_bit_on_whole_time() -> None:
    """The internal grid owes the caller identical arithmetic for exactly-summing slices.

    Four quarters of a second sum exactly in binary floating point, so the pending budget
    crosses every grid boundary on the same substep as one whole-second call, and the two
    runs must agree bit for bit -- not merely to a tolerance.
    """

    sliced = _constant_specimen()
    for _ in range(4):
        sliced.advance(0.25, heater_power_w=0.02, sink_temperature_k=75.0)
    whole = _constant_specimen().advance(1.0, heater_power_w=0.02, sink_temperature_k=75.0)

    assert dict(sliced.state().temperatures_k) == dict(whole.temperatures_k)
    assert sliced.state().elapsed_s == whole.elapsed_s


def test_a_nan_conductivity_floors_instead_of_cascading_into_nan_readings() -> None:
    """A property curve that answers NaN must not fabricate NaN thermometer readings.

    Every other bad number is already floored -- negative conductivity, zero mass share --
    and the floor rather than a NaN cascade three layers away is this module's stated
    failure shape. Before the floor covered it, ``max(nan, floor)`` kept the NaN, every
    interior temperature turned into NaN, and every panel quotient read nan from then on.
    """

    specimen = ThermalConductivitySpecimen(
        [SpecimenNode(channel="hot", mass_kg=0.02), SpecimenNode(channel="cold", mass_kg=0.02)],
        [SpecimenSegment(length_m=_LENGTH, area_m2=_AREA)],
        initial_temperature_k=50.0,
        conductivity_w_per_m_k=lambda _t: math.nan,
        specific_heat_j_per_kg_k=lambda _t: _CP,
    )
    state = specimen.advance(1.0, heater_power_w=0.01, sink_temperature_k=50.0)

    assert all(math.isfinite(value) for value in state.temperatures_k.values())


def test_an_infinite_specific_heat_floors_instead_of_freezing_the_specimen() -> None:
    """An infinite heat capacity would otherwise freeze every thermometer in place.

    ``max(capacity, floor)`` let infinity through, the relaxation factor became exactly
    one forever, and a soak would read a stuck specimen as a settled one. Floored, the
    specimen still answers the heater.
    """

    specimen = ThermalConductivitySpecimen(
        [SpecimenNode(channel="hot", mass_kg=0.02), SpecimenNode(channel="cold", mass_kg=0.02)],
        [SpecimenSegment(length_m=_LENGTH, area_m2=_AREA)],
        initial_temperature_k=50.0,
        conductivity_w_per_m_k=lambda _t: _K,
        specific_heat_j_per_kg_k=lambda _t: math.inf,
    )
    state = specimen.advance(1.0, heater_power_w=0.01, sink_temperature_k=50.0)

    assert all(math.isfinite(value) for value in state.temperatures_k.values())
    assert state.temperatures_k["hot"] > state.temperatures_k["cold"], "a floored specimen must still answer"
