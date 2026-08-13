"""Guard: a prevention cannot be silently deleted or weakened out of the registry.

`validate_registry()` is a single-payload structural validator, so an empty
`false_green_pairs` list is structurally valid and passes — deleting all 302
coverage preventions validates clean. Detecting *removal* inherently requires
comparing against a prior state, which is what
`governance/agent_preventions_baseline.json` and
`validate_against_removal_baseline()` exist for.

Those existed but nothing invoked them, which made them inert. This module is the
invocation. Without it the anti-removal machinery is decorative.

ADR-003 requires rejecting "removal or weakening without an explicit reopened
disposition", and warns that the cheapest way for a weak model to turn a red
strict-guard cut green is to delete the record that failed. That is the exact
attack these tests cover.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml

from tools.governance_contract import (
    GovernanceContractError,
    render_removal_baseline,
    validate_against_removal_baseline,
    validate_registry,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "governance" / "agent_preventions.yaml"
BASELINE_PATH = ROOT / "governance" / "agent_preventions_baseline.json"


def _registry() -> dict:
    return yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))


def _baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_baseline_file_is_tracked_and_parsable() -> None:
    assert BASELINE_PATH.exists(), (
        "governance/agent_preventions_baseline.json is missing; the removal guard cannot run. "
        "Regenerate with: python tools/governance_contract.py --write-baseline"
    )
    assert _baseline().get("digests"), "baseline carries no digests"


def test_live_registry_satisfies_the_removal_baseline() -> None:
    """The live registry must still contain every previously-known prevention."""

    validate_against_removal_baseline(_registry(), _baseline())


def test_baseline_is_in_sync_with_the_live_registry() -> None:
    """A registry edit without regenerating the baseline must fail loudly here.

    Otherwise the baseline silently goes stale and stops protecting anything —
    the same inert-artifact failure this whole module exists to prevent.
    """

    rendered = render_removal_baseline(_registry())
    on_disk = BASELINE_PATH.read_text(encoding="utf-8")
    assert rendered == on_disk, (
        "governance/agent_preventions_baseline.json is out of sync with "
        "governance/agent_preventions.yaml. If the registry change is intended, regenerate with: "
        "python tools/governance_contract.py --write-baseline"
    )


def test_baseline_rendering_is_byte_deterministic() -> None:
    """Required by the publication checklist: generation must be reproducible."""

    payload = _registry()
    assert render_removal_baseline(payload) == render_removal_baseline(copy.deepcopy(payload))


def test_deleting_every_false_green_pair_is_rejected_by_id() -> None:
    """The exact attack: wipe the coverage preventions to turn a red cut green.

    `validate_registry` alone accepts this — an empty list is structurally valid.
    The baseline check is what refuses it, and it must name the missing id so a
    weak model reading the failure understands it cannot simply delete records.
    """

    poisoned = _registry()
    poisoned["false_green_pairs"] = []
    validate_registry(poisoned)  # structurally clean — this is the hole

    with pytest.raises(GovernanceContractError) as excinfo:
        validate_against_removal_baseline(poisoned, _baseline())
    message = str(excinfo.value)
    assert "removed" in message.lower()
    assert any(char.isupper() for char in message), "failure must name the offending id"


def test_deleting_a_single_runtime_record_is_rejected_by_id() -> None:
    poisoned = _registry()
    removed = poisoned["records"].pop()
    with pytest.raises(GovernanceContractError) as excinfo:
        validate_against_removal_baseline(poisoned, _baseline())
    assert removed["id"] in str(excinfo.value)


def test_weakening_an_open_record_without_reopening_is_rejected() -> None:
    """Content may not change under a stable id unless the entry is `reopened`."""

    poisoned = _registry()
    target = next(record for record in poisoned["records"] if record["status"] == "open")
    target["invariant"] = "weakened by an agent chasing a green suite"
    with pytest.raises(GovernanceContractError) as excinfo:
        validate_against_removal_baseline(poisoned, _baseline())
    assert target["id"] in str(excinfo.value)
