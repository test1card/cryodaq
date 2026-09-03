"""Canonical Keithley safety-gate design-system contract."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_ROOT = REPO_ROOT / "docs" / "design-system"


def test_keithley_contract_distinguishes_missing_authority_from_current_blocker() -> None:
    spec = (DESIGN_ROOT / "cryodaq-primitives" / "keithley-panel.md").read_text(encoding="utf-8")
    version = (DESIGN_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    changelog = (DESIGN_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    assert "SafetyGateCause.AUTHORITY_UNAVAILABLE" in spec
    assert "SafetyGateCause.AUTHORITATIVE_NOT_READY" in spec
    assert "ReadinessTruth.BLOCKED" in spec
    assert "SafetyLifecycle.SAFE_OFF" in spec
    assert "operator_warning_choice" in spec

    assert tuple(map(int, version.split("."))) >= (4, 2, 0)
    # The contract is recorded in the 4.2.0 entry and stays true for every later
    # release. Asserting it appears in the *newest* entry pinned this test to
    # 4.2.0 remaining the top of the changelog, so the next unrelated release
    # broke it — 4.3.0 (theme reduction) did exactly that on 2026-09-04. What
    # matters is that the contract is recorded at or after the version that
    # introduced it, not that it is the most recent thing to have happened.
    keithley_release = re.search(
        r"^## \[(?P<v>\d+\.\d+\.\d+)\][^\n]*\n(?P<body>.*?)(?=^## \[|\Z)",
        changelog,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert keithley_release is not None
    releases = re.findall(
        r"^## \[(\d+\.\d+\.\d+)\][^\n]*\n(.*?)(?=^## \[|\Z)",
        changelog,
        flags=re.MULTILINE | re.DOTALL,
    )
    documented = [v for v, body in releases if "Keithley" in body]
    assert documented, "the Keithley channel-state contract must be recorded in the changelog"
    assert max(tuple(map(int, v.split("."))) for v in documented) >= (4, 2, 0)
