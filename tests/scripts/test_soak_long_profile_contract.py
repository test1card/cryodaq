"""Long-profile synthetic soak-evidence contract tests.

The negatives mutate, respectively, an identity inside one epoch, a replacement
epoch, and a fault recovery time above the validator ceiling.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from dataclasses import replace
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


@pytest.mark.parametrize("profile_name", ("12h", "72h", "168h"))
def test_long_profile_resources_and_faults_cover_real_schedule(profile_name: str) -> None:
    """The production hour-scale events pass both evidence validators."""

    profile = soak.PROFILES[profile_name]
    samples = _samples(profile)
    assert soak.evaluate_resources(samples, profile) == []
    assert soak._validate_faults(_faults(profile), profile, samples) == []


@pytest.mark.parametrize("profile_name", ("12h", "72h", "168h"))
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


def test_72h_profile_rejects_its_own_descriptor_slope_limit() -> None:
    """A slope accepted by 12h is rejected by the stricter 72h aggregate rule."""

    profile = soak.PROFILES["72h"]
    samples = _samples(profile)
    for sample in samples:
        elapsed_s = float(sample["elapsed_s"])
        growth = int((elapsed_s - profile.warmup_s) * 0.1 / 3600) if elapsed_s >= profile.warmup_s else 0
        for role in ("launcher", "engine", "bridge"):
            sample["roles"][role]["descriptors"] += growth

    assert soak.evaluate_resources(_samples(profile), profile) == []
    warmup_ramp = _samples(profile)
    # The ramp rises across the long profile's warm-up and is then HELD. Growth
    # is measured from the first post-warm-up sample to the last, so a bump that
    # returns to baseline nets to zero and trips nothing; only a sustained step
    # distinguishes the two warm-up lengths.
    ramp_start_s = soak.PROFILES["short"].warmup_s
    ramp_bytes = 100 * 1024 * 1024
    for sample in warmup_ramp:
        elapsed_s = float(sample["elapsed_s"])
        if elapsed_s < ramp_start_s:
            continue
        fraction = min(1.0, (elapsed_s - ramp_start_s) / (profile.warmup_s - ramp_start_s))
        sample["roles"]["launcher"]["rss_bytes"] += int(fraction * ramp_bytes)
    assert soak.evaluate_resources(warmup_ramp, profile) == []
    short_warmup = replace(profile, warmup_s=soak.PROFILES["short"].warmup_s)
    assert "launcher epoch 0 RSS growth reached 50 MiB" in soak.evaluate_resources(warmup_ramp, short_warmup)
    errors = soak.evaluate_resources(samples, profile)
    assert "aggregate descriptor slope exceeded profile limit" in errors

    per_role = _samples(profile)
    for sample in per_role:
        elapsed_s = float(sample["elapsed_s"])
        growth = int((elapsed_s - profile.warmup_s) * 0.5 / 3600) if elapsed_s >= profile.warmup_s else 0
        sample["roles"]["launcher"]["descriptors"] += growth
    assert "launcher descriptor slope exceeded profile limit" in soak.evaluate_resources(per_role, profile)


def test_72h_profile_rejects_its_own_rss_slope_limit() -> None:
    profile_12h = soak.PROFILES["12h"]
    profile_72h = soak.PROFILES["72h"]
    assert profile_12h.rss_slope_limit_bytes_per_hour is not None
    assert profile_72h.rss_slope_limit_bytes_per_hour is not None
    assert profile_72h.rss_slope_limit_bytes_per_hour < profile_12h.rss_slope_limit_bytes_per_hour
    growth_per_hour = (profile_72h.rss_slope_limit_bytes_per_hour + profile_12h.rss_slope_limit_bytes_per_hour) / 2
    samples = _samples(profile_72h)
    for sample in samples:
        elapsed_s = float(sample["elapsed_s"])
        if elapsed_s >= profile_72h.warmup_s:
            growth = int((elapsed_s - profile_72h.warmup_s) * growth_per_hour / 3600)
        else:
            growth = 0
        sample["roles"]["launcher"]["rss_bytes"] += growth

    assert soak.evaluate_resources(_samples(profile_72h), profile_72h) == []
    errors_72h = soak.evaluate_resources(samples, profile_72h)
    errors_12h = soak.evaluate_resources(samples, profile_12h)
    assert "aggregate RSS slope exceeded profile limit" in errors_72h
    assert "launcher epoch 0 RSS slope exceeded profile limit" in errors_72h
    assert "aggregate RSS slope exceeded profile limit" not in errors_12h
    assert "launcher epoch 0 RSS slope exceeded profile limit" not in errors_12h


def test_long_profile_contract_rejects_schedule_and_recovery_mutations() -> None:
    """The complete ordered schedule and target-specific recovery receipts are required."""

    profile = soak.PROFILES["72h"]
    samples = _samples(profile)
    faults = _faults(profile)
    assert soak._validate_faults(faults, profile, samples) == []

    missing = copy.deepcopy(faults)
    missing.pop()
    assert "fault schedule is missing, duplicated, reordered, or unscheduled" in soak._validate_faults(
        missing, profile, samples
    )

    duplicated = copy.deepcopy(faults)
    duplicated.append(copy.deepcopy(duplicated[-1]))
    assert "fault schedule is missing, duplicated, reordered, or unscheduled" in soak._validate_faults(
        duplicated, profile, samples
    )

    reordered = copy.deepcopy(faults)
    reordered[0], reordered[1] = reordered[1], reordered[0]
    assert "fault schedule is missing, duplicated, reordered, or unscheduled" in soak._validate_faults(
        reordered, profile, samples
    )

    late = copy.deepcopy(faults)
    late_index = 1
    late[late_index]["observed_s"] += soak.SAMPLE_INTERVAL_S + 1
    assert f"fault {late_index} exceeded schedule tolerance" in soak._validate_faults(late, profile, samples)

    recheck_changed = copy.deepcopy(faults)
    recheck_changed[0]["recheck_pid"] += 1
    assert "fault 0 failed immediate identity recheck" in soak._validate_faults(recheck_changed, profile, samples)

    fabricated_recovery = copy.deepcopy(faults)
    fabricated_recovery[0]["recovery_s"] = 0.0
    assert "fault 0 recovery does not match sample history" in soak._validate_faults(
        fabricated_recovery, profile, samples
    )

    not_ready = copy.deepcopy(faults)
    not_ready[0]["ready"] = False
    assert "fault 0 replacement was not ready" in soak._validate_faults(not_ready, profile, samples)

    engine_unhealthy = copy.deepcopy(faults)
    engine_index = next(index for index, fault in enumerate(engine_unhealthy) if fault["target"] == "engine")
    engine_unhealthy[engine_index]["bridge_data_resumed"] = False
    assert f"fault {engine_index} lacks bridge-data recovery" in soak._validate_faults(
        engine_unhealthy, profile, samples
    )

    assistant_unhealthy = copy.deepcopy(faults)
    assistant_index = next(index for index, fault in enumerate(assistant_unhealthy) if fault["target"] == "assistant")
    assistant_unhealthy[assistant_index]["newer_h3_health"] = False
    assert f"fault {assistant_index} lacks newer H3 health" in soak._validate_faults(
        assistant_unhealthy, profile, samples
    )


def test_long_profile_contract_rejects_a_truncated_sample_tail() -> None:
    """Series coverage must reach the selected profile duration."""

    profile = soak.PROFILES["72h"]
    samples = _samples(profile)
    truncated = [sample for sample in samples if sample["elapsed_s"] < profile.duration_s - soak.SAMPLE_INTERVAL_S]

    assert soak.validate_sample_series(samples, profile) == []
    assert "series does not cover profile duration" in soak.validate_sample_series(truncated, profile)
