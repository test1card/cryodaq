"""Reviewed long-soak profiles keep exact identity and fault structure."""

from __future__ import annotations

from dataclasses import replace

import pytest

from scripts import soak_mock_stack as soak

COMPRESSED_DURATION_S = 120.0


def _compressed_12h_rehearsal() -> soak.SoakProfile:
    """Preserve the reviewed 12-hour fault structure in a two-minute rehearsal."""

    source = soak.PROFILES["12h"]
    scale = COMPRESSED_DURATION_S / source.duration_s
    return replace(
        source,
        name="rehearsal-12h",
        duration_s=COMPRESSED_DURATION_S,
        warmup_s=max(1.0, source.warmup_s * scale),
        events=tuple(soak.FaultEvent(event.target, event.at_s * scale) for event in source.events),
    )


def test_the_rehearsal_preserves_the_reviewed_12h_fault_structure() -> None:
    """Compression changes when faults arrive, never which faults or how many."""

    source = soak.PROFILES["12h"]
    rehearsal = _compressed_12h_rehearsal()

    assert len(rehearsal.events) == len(source.events)
    assert tuple(event.target for event in rehearsal.events) == tuple(event.target for event in source.events)
    assert tuple(event.at_s for event in rehearsal.events) != tuple(event.at_s for event in source.events)
    assert rehearsal.duration_s < source.duration_s


def test_the_weekly_profile_extends_the_reviewed_72h_fault_schedule() -> None:
    """The weekly run preserves the 72-hour prefix before later daily faults."""

    profile_72h = soak.PROFILES["72h"]
    profile_168h = soak.PROFILES["168h"]
    assert profile_168h.events[: len(profile_72h.events)] == profile_72h.events
    assert profile_168h.duration_s == 7 * 24 * 3600


def test_runner_rejects_a_caller_built_profile_even_when_its_name_is_reviewed() -> None:
    """Only the exact immutable profile objects can start a qualification."""

    from scripts import soak_mock_stack_runner as runner

    runner._PosixSoakRunner(soak.PROFILES["12h"])
    fabricated = replace(soak.PROFILES["12h"], duration_s=60)
    with pytest.raises(TypeError, match="exact reviewed profile"):
        runner._PosixSoakRunner(fabricated)
