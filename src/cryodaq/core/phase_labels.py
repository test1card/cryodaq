"""Canonical Russian labels for ExperimentPhase enum members.

Shared between TopWatchBar, PhaseAwareWidget, and ExperimentWorkspace
to eliminate label drift (Strategy §10 R9). Add new phases here, never
in widget files.
"""
from __future__ import annotations

from cryodaq.core.experiment import ExperimentPhase

# Full Russian labels — canonical set (per Codex B.5 alignment).
PHASE_LABELS_RU: dict[str, str] = {
    ExperimentPhase.PREPARATION.value: "\u041f\u043e\u0434\u0433\u043e\u0442\u043e\u0432\u043a\u0430",
    ExperimentPhase.VACUUM.value: "\u041e\u0442\u043a\u0430\u0447\u043a\u0430",
    ExperimentPhase.COOLDOWN.value: "\u0417\u0430\u0445\u043e\u043b\u0430\u0436\u0438\u0432\u0430\u043d\u0438\u0435",
    ExperimentPhase.MEASUREMENT.value: "\u0418\u0437\u043c\u0435\u0440\u0435\u043d\u0438\u0435",
    ExperimentPhase.WARMUP.value: "\u0420\u0430\u0441\u0442\u0435\u043f\u043b\u0435\u043d\u0438\u0435",
    ExperimentPhase.TEARDOWN.value: "\u0420\u0430\u0437\u0431\u043e\u0440\u043a\u0430",
}

# Abbreviated labels — for compact contexts (ExperimentWorkspace stepper).
PHASE_LABELS_RU_SHORT: dict[str, str] = {
    ExperimentPhase.PREPARATION.value: "\u041f\u043e\u0434\u0433\u043e\u0442.",
    ExperimentPhase.VACUUM.value: "\u041e\u0442\u043a\u0430\u0447\u043a\u0430",
    ExperimentPhase.COOLDOWN.value: "\u0417\u0430\u0445\u043e\u043b\u0430\u0436.",
    ExperimentPhase.MEASUREMENT.value: "\u0418\u0437\u043c\u0435\u0440\u0435\u043d.",
    ExperimentPhase.WARMUP.value: "\u0420\u0430\u0441\u0442\u0435\u043f\u043b.",
    ExperimentPhase.TEARDOWN.value: "\u0420\u0430\u0437\u0431\u043e\u0440\u043a\u0430",
}

# Ordered tuple of phase string values — stepper sequence.
PHASE_ORDER: tuple[str, ...] = tuple(p.value for p in ExperimentPhase)


def label_for(phase: ExperimentPhase | str | None) -> str:
    """Return Russian label for a phase, accepting enum, string, or None.

    Returns "\u2014" for None or unknown phase. Never raises.
    """
    if phase is None:
        return "\u2014"
    key = phase.value if isinstance(phase, ExperimentPhase) else phase
    return PHASE_LABELS_RU.get(key, "\u2014")
