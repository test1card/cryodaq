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
    current_release = re.search(
        rf"^## \[{re.escape(version)}\].*?(?=^## \[|\Z)",
        changelog,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert current_release is not None
    assert "Keithley" in current_release.group(0)
