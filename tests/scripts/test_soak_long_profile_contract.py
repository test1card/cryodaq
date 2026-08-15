"""Long-profile synthetic soak-evidence contract tests.

The negatives mutate, respectively, an identity inside one epoch, a replacement
epoch, and a fault recovery time above the validator ceiling.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "soak_mock_stack.py"
_SPEC = importlib.util.spec_from_file_location("soak_mock_stack", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
soak = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = soak
_SPEC.loader.exec_module(soak)


def _samples(profile: soak.SoakProfile) -> list[dict[str, object]]:
    role_indexes = {role: index for index, role in enumerate(soak.ROLES)}
    result = []
    for elapsed_s in range(0, int(profile.duration_s) + 1, int(soak.SAMPLE_INTERVAL_S)):
        rows = {}
        for role, index in role_indexes.items():
            restart_count = sum(event.target == role and elapsed_s > event.at_s for event in profile.events)
            rows[role] = (
                restart_count,
                soak.ProcessSnapshot(
                    soak.ProcessIdentity(
                        10 + index + restart_count * 100,
                        100 + index + restart_count * 100,
                    ),
                    1 if role == "launcher" else 10,
                    (role,),
                    "python",
                    100,
                    1,
                    2,
                    True,
                ),
            )
        result.append(soak.stack_sample(float(elapsed_s), rows))
    return result


def _faults(profile: soak.SoakProfile) -> list[dict[str, object]]:
    role_indexes = {role: index for index, role in enumerate(soak.ROLES)}
    restart_counts = {role: 0 for role in soak.ROLES}
    records = []
    for event in profile.events:
        index = role_indexes[event.target]
        before = restart_counts[event.target]
        restart_counts[event.target] += 1
        after = restart_counts[event.target]
        records.append(
            {
                "target": event.target,
                "signal": soak.FAULT_SIGNAL,
                "injection_method": soak.FAULT_INJECTION_METHOD,
                "scheduled_s": float(event.at_s),
                "observed_s": float(event.at_s),
                "pre_pid": 10 + index + before * 100,
                "pre_started_ns": 100 + index + before * 100,
                "recheck_pid": 10 + index + before * 100,
                "recheck_started_ns": 100 + index + before * 100,
                "replacement_pid": 10 + index + after * 100,
                "replacement_started_ns": 100 + index + after * 100,
                "ready": True,
                "recovery_s": float(soak.SAMPLE_INTERVAL_S),
                "bridge_data_resumed": event.target == "engine",
                "newer_h3_health": event.target == "assistant",
            }
        )
    return records


@pytest.mark.parametrize("profile_name", ("12h", "72h"))
def test_long_profile_resources_and_faults_cover_real_schedule(profile_name: str) -> None:
    """The production hour-scale events pass both evidence validators."""

    profile = soak.PROFILES[profile_name]
    samples = _samples(profile)
    assert soak.evaluate_resources(samples, profile) == []
    assert soak._validate_faults(_faults(profile), profile, samples) == []


@pytest.mark.parametrize("profile_name", ("12h", "72h"))
def test_long_profile_contract_rejects_each_mutation(profile_name: str) -> None:
    """Reject the identity, epoch, and recovery-ceiling mutations described above."""

    profile = soak.PROFILES[profile_name]
    samples = _samples(profile)
    faults = _faults(profile)

    identity_changed = copy.deepcopy(samples)
    identity_changed[-1]["roles"]["engine"]["pid"] += 1
    assert any("identity changed within epoch" in error for error in soak.evaluate_resources(identity_changed, profile))

    skipped_epoch = copy.deepcopy(samples)
    event = profile.events[0]
    for sample in skipped_epoch:
        if sample["elapsed_s"] > event.at_s:
            sample["roles"][event.target]["epoch"] += 1
    assert any(
        "replacement epoch is not the next epoch" in error
        for error in soak._validate_faults(faults, profile, skipped_epoch)
    )

    excessive_recovery = copy.deepcopy(faults)
    excessive_recovery[0]["recovery_s"] = soak.RECOVERY_CEILING_S + soak.SAMPLE_INTERVAL_S
    assert any(
        "recovery exceeded ceiling" in error for error in soak._validate_faults(excessive_recovery, profile, samples)
    )
