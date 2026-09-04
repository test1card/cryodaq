"""The authoritative record of one experiment-phase entry.

A bare phase string is not enough for a consumer that has to decide whether it
is looking at a NEW entry. `vacuum → cooldown → vacuum` inside one delivery
interval collapses to "vacuum" and reads as no change at all, and a consumer
that needs the moment of transition has to invent one at delivery time — which
is later than the transition, and by an unbounded amount.

`ExperimentManager.advance_phase` already produces both facts. This carries them
unchanged: the experiment that owns the entry, the phase, and the `started_at`
the manager wrote. Consumers compare the whole triple, so a re-entry to the same
phase is a different event, and nobody has to guess when it happened.

Deliberately not a persistence or replay mechanism: one latest value, held in
memory, discarded on restart.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PhaseEntry"]


@dataclass(frozen=True, slots=True)
class PhaseEntry:
    """One phase entry, exactly as the ExperimentManager committed it."""

    experiment_id: str
    phase: str
    started_at: float
    """Epoch seconds, from the manager's own metadata — NOT delivery time."""

    def identity(self) -> tuple[str, str, float]:
        """What makes this entry distinct from another.

        Includes `started_at`, so re-entering a phase is a new entry rather than
        a duplicate of the previous one.
        """

        return (self.experiment_id, self.phase, self.started_at)
