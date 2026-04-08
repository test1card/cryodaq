"""Verify /phase vocabulary matches ExperimentPhase enum (Phase 2c Codex I.2)."""
from __future__ import annotations

from cryodaq.core.experiment import ExperimentPhase


def test_telegram_phase_vocab_matches_enum():
    """Drift guard — every ExperimentPhase value must be acceptable to
    Telegram /phase, and Telegram must not accept anything that the FSM
    doesn't know."""
    from cryodaq.notifications.telegram_commands import VALID_PHASES

    enum_values = {p.value for p in ExperimentPhase}
    assert VALID_PHASES == enum_values, (
        f"Telegram VALID_PHASES {sorted(VALID_PHASES)} != ExperimentPhase enum "
        f"{sorted(enum_values)}. Drift causes remote operators to get "
        f"'unknown phase' errors for phases that exist locally, and vice versa."
    )


def test_telegram_accepts_all_enum_values():
    from cryodaq.notifications.telegram_commands import VALID_PHASES
    for phase in ExperimentPhase:
        assert phase.value in VALID_PHASES, (
            f"ExperimentPhase.{phase.name}.value={phase.value!r} not in Telegram VALID_PHASES"
        )


def test_legacy_aliases_canonicalize_to_enum():
    """Backwards compat: 'cooling' and 'warming' map to canonical values."""
    from cryodaq.notifications.telegram_commands import _PHASE_ALIASES, VALID_PHASES

    # Aliases must map to real enum values.
    for alias, canonical in _PHASE_ALIASES.items():
        assert canonical in VALID_PHASES, (
            f"alias {alias!r} → {canonical!r} but {canonical!r} not in VALID_PHASES"
        )

    # Documented legacy aliases.
    assert _PHASE_ALIASES.get("cooling") == "cooldown"
    assert _PHASE_ALIASES.get("warming") == "warmup"


def test_vacuum_phase_now_supported():
    """Phase 2c bug fix: 'vacuum' phase from the enum was missing entirely
    from the old hand-maintained list."""
    from cryodaq.notifications.telegram_commands import VALID_PHASES
    assert "vacuum" in VALID_PHASES
