"""The non-short refusal is bound to the profile's identity, not to its lookup key.

`scripts/soak_mock_stack.py::main` refuses any profile whose own ``name`` is not
``short``. That is stronger than refusing by the ``--profile`` argument: a
profile substituted into the ``PROFILES`` mapping under the ``short`` key is
still refused, so the mapping is not a way to smuggle a long-duration run past
the gate. This module pins that property.

It also records, as an executable statement rather than prose, what the runner
still lacks: a reviewed seam that passes the SELECTED profile through to
``_PosixSoakRunner``. Today ``soak_mock_stack_runner`` calls
``soak.profile("short")`` directly and writes ``"profile": "short"`` into the
manifest unconditionally, so the multi-fault, multi-epoch mechanics that the 12h
profile describes have never been exercised by anything. Closing that is a
separate, reviewed change; this module must not be made to pass by adding a
rehearsal profile to the production choices or by weakening the refusal.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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


def test_the_12h_profile_carries_more_faults_than_the_activated_one() -> None:
    """The multi-fault path the runner has never executed is real, not hypothetical."""

    assert len(soak.PROFILES["12h"].events) > len(soak.PROFILES["short"].events)


def test_the_refusal_follows_the_profile_identity_not_the_lookup_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A long profile substituted under the ``short`` key is still refused.

    ``main`` compares ``selected.name``, so rebinding the mapping does not
    launder a non-short profile into an activated run. Exit 3 is the refusal,
    and no evidence directory is created for it.
    """

    rehearsal = _compressed_12h_rehearsal()
    monkeypatch.setitem(soak.PROFILES, "short", rehearsal)

    evidence_dir = tmp_path / "rehearsal"
    assert soak.main(["--profile", "short", "--evidence-dir", str(evidence_dir)]) == 3
    assert not evidence_dir.exists()
