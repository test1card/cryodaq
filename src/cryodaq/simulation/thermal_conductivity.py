"""A specimen whose thermometers answer the heater, so a run exercises the measurement.

WHY THIS EXISTS. The conductivity measurement this laboratory performs is a chain of
thermometers along a specimen, a known heater power ``P``, and for each adjacent pair the
quantities the operator's panel already computes:

    dT = T_hot - T_cold        R = dT / P        G = P / dT

Every part of that already exists in this repository. What did not exist is a specimen for
it to measure. Measured 2026-08-23: the mock instrument returns eight FIXED temperatures
with plus or minus half a percent of noise, unrelated to the heater. So ``dT`` is a
constant, ``R`` and ``G`` are constants, the settling predictor has nothing to settle, and
a week-long run exercises the plumbing without ever exercising the measurement.

This module supplies the missing half: a one-dimensional chain of specimen segments with
real heat capacity, so a change in heater power moves the thermometers, and moves them with
a time constant rather than instantly.

WHAT IT IS NOT. It is not a material datum. The default property curves below are smooth
stand-ins with the right SHAPE for cryogenic solids -- a conductivity that falls as the
specimen cools and a heat capacity that falls much faster -- and they are not measurements
of anything. Pass ``conductivity_w_per_m_k`` and ``specific_heat_j_per_kg_k`` to model a
real material. Nothing here should ever be quoted as a property of a real specimen.

The model owns no thread, timer, socket or task. It is advanced by an explicit call with an
explicit time step, so a test and a soak see the same arithmetic.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from types import MappingProxyType

#: Below this the model refuses to divide: a segment with no conductance is not a specimen.
_MIN_CONDUCTANCE_W_PER_K = 1e-12

#: How far a node may move towards its neighbours in one substep. This is an ACCURACY
#: bound, not a stability one: the update below is a per-node exponential relaxation, which
#: cannot overshoot however long the step. What the bound buys is that a node's neighbours
#: do not drift far while it is being advanced.
_RELAXATION_FRACTION = 0.25

#: The internal grid `advance` integrates on. Fixed, so that the way a CALLER slices time
#: cannot change the answer: one call of four thousand seconds and four thousand calls of
#: one second take the identical sequence of substeps. Measured before this was fixed: the
#: two paths disagreed by six millikelvin, which in a soak reads as instrument drift.
_FINE_STEP_S = 0.5

#: A ceiling on substeps per advance so a pathological call cannot spin for minutes. When
#: it binds, the step taken is reported, so a caller can see it happened.
_MAX_SUBSTEPS = 100_000


def default_conductivity_w_per_m_k(temperature_k: float) -> float:
    """A stand-in k(T) with the shape of a cryogenic solid. NOT a material datum.

    Rises roughly linearly from near zero at absolute zero, flattening above about 60 K.
    Chosen only so that a colder specimen shows a larger temperature drop for the same
    heater power, which is the behaviour that makes a simulated sweep worth looking at.
    """

    if temperature_k <= 0.0:
        return _MIN_CONDUCTANCE_W_PER_K
    return 20.0 * temperature_k / (temperature_k + 60.0)


def default_specific_heat_j_per_kg_k(temperature_k: float) -> float:
    """A stand-in c_p(T) with the shape of a cryogenic solid. NOT a material datum.

    Cubic at low temperature, saturating towards a Dulong-Petit-like plateau. The cubic
    region is what makes a cold specimen settle quickly and a warm one settle slowly, which
    is the property a settling predictor is there to handle.
    """

    if temperature_k <= 0.0:
        return _MIN_CONDUCTANCE_W_PER_K
    return 400.0 * temperature_k**3 / (temperature_k**3 + 120.0**3)


@dataclass(frozen=True, slots=True)
class SpecimenNode:
    """One thermometer position and the specimen mass whose temperature it reads."""

    channel: str
    mass_kg: float

    def __post_init__(self) -> None:
        if not self.channel:
            raise ValueError("a specimen node needs a channel identity")
        if not (math.isfinite(self.mass_kg) and self.mass_kg > 0.0):
            raise ValueError(f"node {self.channel!r} needs a positive finite mass, got {self.mass_kg!r}")


@dataclass(frozen=True, slots=True)
class SpecimenSegment:
    """The specimen between two adjacent thermometer positions."""

    length_m: float
    area_m2: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.length_m) and self.length_m > 0.0):
            raise ValueError(f"a segment needs a positive finite length, got {self.length_m!r}")
        if not (math.isfinite(self.area_m2) and self.area_m2 > 0.0):
            raise ValueError(f"a segment needs a positive finite area, got {self.area_m2!r}")


@dataclass(frozen=True, slots=True)
class SpecimenState:
    """One cut of the specimen: what every thermometer would read, and what drove it."""

    elapsed_s: float
    heater_power_w: float
    sink_temperature_k: float
    temperatures_k: MappingProxyType
    substeps: int
    substep_limited: bool

    def pair_conductance_w_per_k(self, hot: str, cold: str) -> float:
        """``G = P / dT`` for one pair, the same arithmetic the operator's panel performs.

        Returns NaN when the pair is isothermal, because a conductance is not defined
        there -- and returning a large number instead would be a fabricated measurement.
        """

        delta = self.temperatures_k[hot] - self.temperatures_k[cold]
        if delta == 0.0:
            return math.nan
        return self.heater_power_w / delta


class ThermalConductivitySpecimen:
    """A chain of specimen segments between a heater and a cold sink.

    Node 0 takes the heater power. The last node is held at the sink temperature, which is
    what a cold head does to the end it is bolted to. Every interior node exchanges heat
    with its two neighbours through the segment between them.
    """

    __slots__ = (
        "_conductances",
        "_conductivity",
        "_elapsed_s",
        "_nodes",
        "_pending_s",
        "_segments",
        "_specific_heat",
        "_temperatures",
    )

    def __init__(
        self,
        nodes: Sequence[SpecimenNode],
        segments: Sequence[SpecimenSegment],
        *,
        initial_temperature_k: float,
        conductivity_w_per_m_k: Callable[[float], float] = default_conductivity_w_per_m_k,
        specific_heat_j_per_kg_k: Callable[[float], float] = default_specific_heat_j_per_kg_k,
    ) -> None:
        if len(nodes) < 2:
            raise ValueError("a specimen needs at least two thermometer positions")
        if len(segments) != len(nodes) - 1:
            raise ValueError(f"{len(nodes)} nodes need {len(nodes) - 1} segments, got {len(segments)}")
        channels = [node.channel for node in nodes]
        if len(set(channels)) != len(channels):
            raise ValueError(f"every node needs its own channel; got {channels}")
        if not (math.isfinite(initial_temperature_k) and initial_temperature_k > 0.0):
            raise ValueError(f"the initial temperature must be positive and finite, got {initial_temperature_k!r}")

        self._nodes = tuple(nodes)
        self._segments = tuple(segments)
        self._conductivity = conductivity_w_per_m_k
        self._specific_heat = specific_heat_j_per_kg_k
        self._temperatures = [float(initial_temperature_k)] * len(self._nodes)
        self._conductances = [0.0] * len(self._segments)
        self._elapsed_s = 0.0
        self._pending_s = 0.0

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(node.channel for node in self._nodes)

    def state(self, *, heater_power_w: float = 0.0, sink_temperature_k: float | None = None) -> SpecimenState:
        """The present cut, without advancing time."""

        sink = self._temperatures[-1] if sink_temperature_k is None else float(sink_temperature_k)
        return SpecimenState(
            elapsed_s=self._elapsed_s,
            heater_power_w=float(heater_power_w),
            sink_temperature_k=sink,
            temperatures_k=MappingProxyType(
                {node.channel: self._temperatures[index] for index, node in enumerate(self._nodes)}
            ),
            substeps=0,
            substep_limited=False,
        )

    def advance(self, duration_s: float, *, heater_power_w: float, sink_temperature_k: float) -> SpecimenState:
        """Carry the specimen forward by ``duration_s`` under a constant heater and sink."""

        if not (math.isfinite(duration_s) and duration_s >= 0.0):
            raise ValueError(f"the step must be a non-negative finite number of seconds, got {duration_s!r}")
        if not math.isfinite(heater_power_w):
            raise ValueError(f"the heater power must be finite, got {heater_power_w!r}")
        if not (math.isfinite(sink_temperature_k) and sink_temperature_k > 0.0):
            raise ValueError(f"the sink temperature must be positive and finite, got {sink_temperature_k!r}")

        self._temperatures[-1] = float(sink_temperature_k)
        self._pending_s += float(duration_s)
        substeps = 0
        limited = False
        while True:
            step = min(_FINE_STEP_S, self._accuracy_step_s())
            if self._pending_s < step:
                break
            if substeps >= _MAX_SUBSTEPS:
                limited = True
                break
            self._step(step, heater_power_w=heater_power_w, sink_temperature_k=sink_temperature_k)
            self._pending_s -= step
            self._elapsed_s += step
            substeps += 1

        return SpecimenState(
            elapsed_s=self._elapsed_s,
            heater_power_w=float(heater_power_w),
            sink_temperature_k=float(sink_temperature_k),
            temperatures_k=MappingProxyType(
                {node.channel: self._temperatures[index] for index, node in enumerate(self._nodes)}
            ),
            substeps=substeps,
            substep_limited=limited,
        )

    def settle(
        self,
        *,
        heater_power_w: float,
        sink_temperature_k: float,
        tolerance_k: float = 1e-6,
        max_seconds: float = 1e6,
    ) -> SpecimenState:
        """Run until nothing moves by more than ``tolerance_k``, or ``max_seconds`` passes.

        The returned state's ``substep_limited`` says which of the two ended it, so a caller
        never mistakes a timeout for a settled specimen.
        """

        if not (math.isfinite(tolerance_k) and tolerance_k > 0.0):
            raise ValueError(f"the tolerance must be positive and finite, got {tolerance_k!r}")
        self._temperatures[-1] = float(sink_temperature_k)
        elapsed = 0.0
        while elapsed < max_seconds:
            before = list(self._temperatures)
            step = min(self._accuracy_step_s() * 64.0, max_seconds - elapsed)
            self._step(step, heater_power_w=heater_power_w, sink_temperature_k=sink_temperature_k)
            elapsed += step
            self._elapsed_s += step
            if max(abs(a - b) for a, b in zip(before, self._temperatures, strict=True)) <= tolerance_k:
                return SpecimenState(
                    elapsed_s=self._elapsed_s,
                    heater_power_w=float(heater_power_w),
                    sink_temperature_k=float(sink_temperature_k),
                    temperatures_k=MappingProxyType(
                        {node.channel: self._temperatures[index] for index, node in enumerate(self._nodes)}
                    ),
                    substeps=0,
                    substep_limited=False,
                )
        return SpecimenState(
            elapsed_s=self._elapsed_s,
            heater_power_w=float(heater_power_w),
            sink_temperature_k=float(sink_temperature_k),
            temperatures_k=MappingProxyType(
                {node.channel: self._temperatures[index] for index, node in enumerate(self._nodes)}
            ),
            substeps=0,
            substep_limited=True,
        )

    # -- the arithmetic -----------------------------------------------------------------

    def _refresh_conductances(self) -> None:
        for index, segment in enumerate(self._segments):
            mean_temperature = 0.5 * (self._temperatures[index] + self._temperatures[index + 1])
            conductivity = self._conductivity(mean_temperature)
            conductance = conductivity * segment.area_m2 / segment.length_m
            self._conductances[index] = max(conductance, _MIN_CONDUCTANCE_W_PER_K)

    def _heat_capacity_j_per_k(self, index: int) -> float:
        capacity = self._nodes[index].mass_kg * self._specific_heat(self._temperatures[index])
        return max(capacity, _MIN_CONDUCTANCE_W_PER_K)

    def _accuracy_step_s(self) -> float:
        """A step over which no node relaxes more than ``_RELAXATION_FRACTION`` of the way."""

        self._refresh_conductances()
        fastest = 0.0
        for index in range(len(self._nodes) - 1):
            coupling = self._conductances[index]
            if index > 0:
                coupling += self._conductances[index - 1]
            fastest = max(fastest, coupling / self._heat_capacity_j_per_k(index))
        if fastest <= 0.0:
            return _FINE_STEP_S
        return _RELAXATION_FRACTION / fastest

    def _step(self, dt_s: float, *, heater_power_w: float, sink_temperature_k: float) -> None:
        """Relax every node towards the temperature its frozen neighbours imply.

        Each node obeys ``C dT/dt = Q + sum G (T_neighbour - T)``. Holding the neighbours
        still for the substep leaves a first-order lag with an exact solution, so the node
        is moved along that exponential rather than along its tangent. Two consequences
        that matter here: a long step can never overshoot into oscillation, and a single
        segment relaxes with EXACTLY its own time constant, which is the number a settling
        predictor is built to recover.
        """

        self._refresh_conductances()
        updated = list(self._temperatures)
        for index in range(len(self._nodes) - 1):
            coupling = 0.0
            driven = float(heater_power_w) if index == 0 else 0.0
            if index > 0:
                coupling += self._conductances[index - 1]
                driven += self._conductances[index - 1] * self._temperatures[index - 1]
            coupling += self._conductances[index]
            driven += self._conductances[index] * self._temperatures[index + 1]

            target = driven / coupling
            tau_s = self._heat_capacity_j_per_k(index) / coupling
            decay = math.exp(-dt_s / tau_s) if dt_s < 700.0 * tau_s else 0.0
            moved = target + (self._temperatures[index] - target) * decay
            # A solid cannot be driven below absolute zero by arithmetic. A floor here keeps
            # a caller's own units mistake visible as a floor rather than as a NaN cascade
            # three layers away.
            updated[index] = max(moved, _MIN_CONDUCTANCE_W_PER_K)
        updated[-1] = float(sink_temperature_k)
        self._temperatures = updated
