from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import soak_mock_stack as soak

_POSIX_EVIDENCE = pytest.mark.skipif(os.name != "posix", reason="evidence capability is POSIX-only")


@pytest.mark.parametrize(
    ("first", "second"),
    ((signal.SIGINT, signal.SIGTERM), (signal.SIGTERM, signal.SIGINT)),
)
def test_interrupt_handler_latches_first_signal(first: int, second: int) -> None:
    handler = soak._first_signal_interrupt_handler()

    with pytest.raises(soak.RunInterrupted) as caught:
        handler(first, object())
    handler(second, object())

    assert caught.value.signum == first


@pytest.mark.skipif(os.name == "posix", reason="Windows fail-closed contract")
def test_windows_rejects_evidence_without_creating_artifacts(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    with pytest.raises(soak.EvidenceCapabilityError, match="evidence capability is POSIX-only"):
        soak.Evidence(evidence_dir)
    assert not evidence_dir.exists()
    assert soak.main(["--evidence-dir", str(evidence_dir)]) == 2
    assert not evidence_dir.exists()


def _snapshot(
    pid: int,
    started: int,
    parent: int | None,
    argv: tuple[str, ...],
    *,
    rss: int = 100,
    threads: int = 1,
    descriptors: int | None = 2,
    running: bool = True,
) -> soak.ProcessSnapshot:
    return soak.ProcessSnapshot(
        soak.ProcessIdentity(pid, started),
        parent,
        argv,
        "python",
        rss,
        threads,
        descriptors,
        running,
    )


def _sample(
    elapsed: float,
    *,
    descriptor_overrides: dict[str, int | None] | None = None,
    rss_overrides: dict[str, int] | None = None,
    thread_overrides: dict[str, int] | None = None,
    epoch_overrides: dict[str, int] | None = None,
) -> dict[str, object]:
    descriptor_overrides = descriptor_overrides or {}
    rss_overrides = rss_overrides or {}
    thread_overrides = thread_overrides or {}
    epoch_overrides = epoch_overrides or {}
    rows = {
        role: (
            epoch_overrides.get(role, 0),
            _snapshot(
                10 + index,
                100 + index,
                1 if role == "launcher" else 10,
                (role,),
                rss=rss_overrides.get(role, 100),
                threads=thread_overrides.get(role, 1),
                descriptors=descriptor_overrides.get(role, 2),
            ),
        )
        for index, role in enumerate(soak.ROLES)
    }
    return soak.stack_sample(elapsed, rows)


def _full_series(selected: soak.SoakProfile) -> list[dict[str, object]]:
    return [_sample(float(second)) for second in range(0, int(selected.duration_s) + 1, 5)]


def test_profiles_have_exact_schedules_and_healthy_short_baseline() -> None:
    short = soak.profile("short")
    assert (short.duration_s, short.warmup_s) == (900, 180)
    assert [(event.target, event.at_s) for event in short.events] == [
        ("engine", 185),
        ("assistant", 300),
    ]
    assert short.events[0].at_s >= short.warmup_s + soak.SAMPLE_INTERVAL_S
    assert (
        short.recovery_descriptor_delta_per_process,
        short.final_descriptor_delta_per_process,
        short.recovery_descriptor_delta_aggregate,
    ) == (8, 8, 16)
    assert [event.at_s / 3600 for event in soak.profile("72h").events] == [
        1,
        2,
        12,
        18,
        24,
        36,
        48,
        54,
        60,
        66,
    ]


def test_unknown_profile_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown profile"):
        soak.profile("week")


def test_descendants_and_shutdown_survivors_use_exact_identity_after_reparenting() -> None:
    root = soak.ProcessIdentity(10, 100)
    child = soak.ProcessIdentity(11, 110)
    rows = [
        _snapshot(10, 100, 1, ("launcher",)),
        _snapshot(11, 110, 10, ("engine",)),
        _snapshot(12, 120, 999, ("other",)),
    ]
    assert set(soak.descendants(rows, root)) == {root, child}
    reparented = [_snapshot(11, 110, 1, ("engine",))]
    assert soak.surviving_recorded_identities(reparented, {root, child}) == {child}
    reused = [_snapshot(11, 999, 1, ("other",))]
    assert soak.surviving_recorded_identities(reused, {child}) == set()


@pytest.mark.parametrize(
    "argv,expected",
    [
        (("python", "-m", "cryodaq.engine", "--mock"), "engine"),
        (("pythonw.exe", "-m", "cryodaq.engine", "--mock"), "engine"),
        (("CryoDAQ.exe", "--mode=engine", "--mock"), "engine"),
        (("python", "-m", "cryodaq.agents.assistant_bootstrap"), "assistant"),
        (("CryoDAQ.exe", "--mode=assistant"), "assistant"),
        (("python", "-m", "cryodaq.engine-not"), None),
        (("CryoDAQ.exe", "--mode=engine-not"), None),
        (("tool", "--label=cryodaq.engine"), None),
        (("tool", "cryodaq.agents.assistant_bootstrap"), None),
        (("python", "-m", "cryodaq.engine", "--mode=assistant"), None),
    ],
)
def test_exact_argv_role_variants_and_hostile_near_matches(argv: tuple[str, ...], expected: str | None) -> None:
    assert soak.exact_process_role(argv) == expected


def test_classification_requires_positive_bridge_identity() -> None:
    root = soak.ProcessIdentity(10, 100)
    bridge = soak.ProcessIdentity(12, 120)
    rows = [
        _snapshot(10, 100, 1, ("launcher",)),
        _snapshot(11, 110, 10, ("python", "-m", "cryodaq.engine")),
        _snapshot(12, 120, 10, ("inherited-launcher-argv",)),
        _snapshot(13, 130, 10, ("python", "-m", "cryodaq.agents.assistant_bootstrap")),
    ]
    tree = soak.descendants(rows, root)
    with pytest.raises(ValueError, match="positive bridge identity"):
        soak.classify_tree(tree, root, bridge_identity=None)
    assert soak.classify_tree(tree, root, bridge_identity=bridge)["bridge"] == bridge
    with pytest.raises(ValueError, match="collides"):
        soak.classify_tree(tree, root, bridge_identity=soak.ProcessIdentity(11, 110))


def test_recovery_requires_new_identity_readiness_and_health() -> None:
    old = soak.ProcessIdentity(42, 100)
    new = soak.ProcessIdentity(43, 200)
    soak.assert_replacement(old, new, ready=True, newer_health=True)
    with pytest.raises(AssertionError, match="reused"):
        soak.assert_replacement(old, old, ready=True)
    with pytest.raises(AssertionError, match="not ready"):
        soak.assert_replacement(old, new, ready=False)
    with pytest.raises(AssertionError, match="heartbeat"):
        soak.assert_replacement(old, new, ready=True, newer_health=False)


def test_bounded_slope_on_72h_five_second_series() -> None:
    points = [(float(second), float(second) / 3600 * 2) for second in range(0, 72 * 3600 + 1, 5)]
    bounded = soak.bounded_slope_points(points)
    assert len(points) == 51_841
    assert len(bounded) == soak.MAX_SLOPE_POINTS
    assert soak.MAX_SLOPE_PAIRS == 32_896
    assert bounded[0] == points[0]
    assert bounded[-1] == points[-1]
    assert soak.robust_slope(points) == pytest.approx(2.0)


def test_resource_schema_rejects_nan_reverse_gap_short_duration_and_unknown_descriptors() -> None:
    selected = soak.profile("short")
    cases = [
        [_sample(0), _sample(math.nan)],
        [_sample(0), _sample(5), _sample(4)],
        [_sample(0), _sample(10)],
        [_sample(0), _sample(5)],
        [_sample(0), _sample(900, descriptor_overrides={"engine": None})],
    ]
    expected = ["invalid elapsed_s", "not strictly monotonic", "cadence gap", "profile duration", "invalid descriptors"]
    for samples, marker in zip(cases, expected, strict=True):
        assert any(marker in error for error in soak.evaluate_resources(samples, selected))


def test_resource_schema_rejects_identity_change_inside_epoch_and_bad_wall_time() -> None:
    selected = soak.profile("short")
    samples = _full_series(selected)
    samples[1]["roles"]["engine"]["started_ns"] = 999
    samples[2]["wall_time"] = "not-a-time"
    errors = soak.evaluate_resources(samples, selected)
    assert any("identity changed within epoch" in error for error in errors)
    assert any("invalid wall_time" in error for error in errors)


def test_resource_schema_rejects_fractional_counters_and_identity_reused_across_epochs() -> None:
    selected = soak.profile("short")
    samples = _full_series(selected)
    samples[1]["roles"]["engine"]["threads"] = 1.5
    for sample in samples[61:]:
        sample["roles"]["assistant"]["epoch"] = 1
    errors = soak.evaluate_resources(samples, selected)
    assert any("non-integer threads" in error for error in errors)
    assert any("reused one identity across restart epochs" in error for error in errors)


def test_per_role_leak_cannot_be_hidden_by_offsetting_role() -> None:
    selected = soak.profile("short")
    samples = _full_series(selected)
    samples[-1]["roles"]["engine"]["descriptors"] = 21
    samples[-1]["roles"]["assistant"]["descriptors"] = 0
    errors = soak.evaluate_resources(samples, selected)
    assert "engine final descriptor count exceeded envelope" in errors
    assert "engine epoch 0 descriptor count exceeded envelope" in errors
    assert "aggregate recovery descriptor count exceeded profile envelope" in errors


def test_recovery_epoch_is_compared_to_prior_healthy_baseline() -> None:
    selected = soak.profile("short")
    samples = _full_series(selected)
    for sample in samples[61:]:
        sample["roles"]["engine"].update({"epoch": 1, "pid": 99, "started_ns": 999, "descriptors": 20, "threads": 6})
    errors = soak.evaluate_resources(samples, selected)
    assert "engine epoch 1 recovery descriptors exceeded envelope" in errors
    assert "engine epoch 1 recovery threads exceeded envelope" in errors


def test_rss_slope_is_independent_per_role_and_stable_epoch() -> None:
    selected = soak.profile("12h")
    samples = _full_series(selected)
    mebibyte = 1024 * 1024
    for sample in samples:
        elapsed = float(sample["elapsed_s"])
        epoch = 0 if elapsed < 6 * 3600 else 1
        epoch_elapsed = elapsed if epoch == 0 else elapsed - 6 * 3600
        growth = int(epoch_elapsed / 3600 * 5 * mebibyte)
        sample["roles"]["engine"].update(
            {"rss_bytes": 100 + growth, "epoch": epoch, "pid": 11 + epoch * 100, "started_ns": 101 + epoch * 100}
        )
        sample["roles"]["assistant"].update({"rss_bytes": 100 + (30 * mebibyte - growth)})
    errors = soak.evaluate_resources(samples, selected)
    assert "engine epoch 0 RSS slope exceeded profile limit" in errors
    assert "engine epoch 1 RSS slope exceeded profile limit" in errors
    assert "aggregate RSS slope exceeded profile limit" not in errors


def test_missing_role_and_thread_and_rss_epoch_envelopes_fail() -> None:
    selected = soak.profile("short")
    samples = _full_series(selected)
    del samples[1]["roles"]["bridge"]
    assert any("exact stack roles" in error for error in soak.evaluate_resources(samples, selected))

    samples = _full_series(selected)
    samples[-1]["roles"]["engine"]["threads"] = 6
    samples[-1]["roles"]["assistant"]["rss_bytes"] = 60 * 1024 * 1024
    errors = soak.evaluate_resources(samples, selected)
    assert "engine epoch 0 thread count exceeded envelope" in errors
    assert "assistant epoch 0 RSS growth reached 50 MiB" in errors


def test_log_scan_is_level_aware_and_allowlisted() -> None:
    text = "\n".join(
        [
            "INFO │ SENSOR_ERROR is data",
            "ERROR │ known benign",
            "CRITICAL │ unsafe",
            "Traceback (most recent call last):",
        ]
    )
    assert soak.log_violations(text, (r"known benign",)) == [
        "CRITICAL │ unsafe",
        "Traceback (most recent call last):",
    ]


def test_redaction_covers_nested_logs_urls_assignments_bearer_and_adjacent_argv() -> None:
    raw = {
        "log": "Authorization: Bearer super-secret-value",
        "url": "https://host/?token=plainsecret&ok=1",
        "assignment": "password=hunter2",
        "nested": ["123456:ABCDEFGHIJKLMNOPQRST"],
        "command": soak.scrub_command(["tool", "--password", "plainsecret", "--token=value"]),
    }
    redacted = soak.redact(raw)
    encoded = json.dumps(redacted)
    for secret in ("super-secret-value", "plainsecret", "hunter2", "ABCDEFGHIJKLMNOPQRST", "value"):
        assert secret not in encoded


def _source_fixture() -> dict[str, object]:
    files = (
        "agent.yaml",
        "alarms_v3.yaml",
        "channel_descriptors.yaml",
        "channels.yaml",
        "cooldown.yaml",
        "housekeeping.yaml",
        "instruments.yaml",
        "interlocks.yaml",
        "notifications.yaml",
        "physical_alarms.yaml",
        "plugins.yaml",
        "safety.yaml",
    )
    entries = [{"path": "experiment_templates", "kind": "directory"}]
    entries.extend(
        {
            "path": name,
            "kind": "file",
            "bytes": 0,
            "sha256": "sha256:" + hashlib.sha256(b"").hexdigest(),
        }
        for name in files
    )
    entries.sort(key=lambda item: item["path"])
    tree_sha = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(entries, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
    )
    return {
        "schema": "cryodaq-soak-source-fixture/v1",
        "instrument_id": "LS218_1",
        "authority": "passive_measurement",
        "mock": True,
        "descriptor_count": 16,
        "binding_count": 16,
        "expected_readings_per_sample": 8,
        "entries": entries,
        "tree_sha256": tree_sha,
    }


def _manifest(*, dirty: bool = False) -> dict[str, object]:
    selected = soak.profile("short")
    return {
        "profile": "short",
        "git_sha": "a" * 40,
        "dirty": dirty,
        "platform": "test-platform",
        "python": "test-python",
        "source_command": [sys.executable, "-m", "cryodaq.launcher", "--mock", "--tray"],
        "thresholds": soak.effective_thresholds(selected),
        "periodic_schedule": {
            "interval_s": 600,
            "selection_boundary_offset_s": 450,
            "expected_receipts": 2,
        },
        "source_fixture": _source_fixture(),
        "fatal_log_allowlist": [],
        "capture_policy": "allowlisted-test-schema/v1",
    }


def _prerequisites(**exact_overrides: object) -> dict[str, object]:
    exact = {
        "command": list(soak.EXACT_SIX_COMMAND),
        "git_sha": "a" * 40,
        "exit_code": 0,
        "status": "PASS",
        "result_artifact": "exact-six-result.json",
        "result_sha256": "sha256:" + "0" * 64,
        **exact_overrides,
    }
    return {
        "exact_six": exact,
        "observer": {"identity": "psutil", "version": "7.0", "locked": True},
        "local_publisher": {
            "identity": "cryodaq.testing.local_png_sink/v1",
            "reviewed": True,
            "transport": "local-only",
        },
        "bridge_identity": {"capability": "launcher-bridge-handshake/v1", "positive": True},
    }


def _exact_six_result() -> dict[str, object]:
    return {
        "schema": soak.EXACT_SIX_RESULT_SCHEMA,
        "command": list(soak.EXACT_SIX_COMMAND),
        "test_identity": "tests/integration/test_periodic_png_multiprocess.py::exact-six",
        "git_sha": "a" * 40,
        "exit_code": 0,
        "status": "PASS",
    }


def _write_prerequisites(evidence: soak.Evidence, **exact_overrides: object) -> None:
    # Seed schema-valid but explicitly non-authoritative evidence so the
    # remaining fail-closed validators can be exercised in isolation.
    soak.atomic_json(evidence.directory / "exact-six-result.json", _exact_six_result())
    result_hash = soak._sha256(evidence.directory / "exact-six-result.json")
    evidence.write_prerequisites(_prerequisites(result_sha256=result_hash, **exact_overrides))


def _qualification_samples() -> list[dict[str, object]]:
    samples = _full_series(soak.profile("short"))
    for sample in samples:
        elapsed = sample["elapsed_s"]
        if elapsed >= 190:
            sample["roles"]["engine"].update({"pid": 21, "started_ns": 210, "epoch": 1})
        if elapsed >= 305:
            sample["roles"]["assistant"].update({"pid": 23, "started_ns": 230, "epoch": 1})
    return samples


def _faults() -> list[dict[str, object]]:
    return [
        {
            "target": "engine",
            "signal": soak.FAULT_SIGNAL,
            "injection_method": soak.FAULT_INJECTION_METHOD,
            "scheduled_s": 185.0,
            "observed_s": 185.0,
            "pre_pid": 11,
            "pre_started_ns": 101,
            "recheck_pid": 11,
            "recheck_started_ns": 101,
            "replacement_pid": 21,
            "replacement_started_ns": 210,
            "ready": True,
            "recovery_s": 5.0,
            "bridge_data_resumed": True,
            "newer_h3_health": False,
        },
        {
            "target": "assistant",
            "signal": soak.FAULT_SIGNAL,
            "injection_method": soak.FAULT_INJECTION_METHOD,
            "scheduled_s": 300.0,
            "observed_s": 300.0,
            "pre_pid": 13,
            "pre_started_ns": 103,
            "recheck_pid": 13,
            "recheck_started_ns": 103,
            "replacement_pid": 23,
            "replacement_started_ns": 230,
            "ready": True,
            "recovery_s": 5.0,
            "bridge_data_resumed": False,
            "newer_h3_health": True,
        },
    ]


def _shutdown(samples: list[dict[str, object]]) -> dict[str, object]:
    identities = {(record["pid"], record["started_ns"]) for sample in samples for record in sample["roles"].values()}
    return {
        "graceful_requested": True,
        "launcher_exited": True,
        "elapsed_s": 1.0,
        "observed_identities": [{"pid": pid, "started_ns": started} for pid, started in sorted(identities)],
        "survivors": [],
    }


def _write_periodic_artifacts(evidence: soak.Evidence) -> None:
    ledger: list[dict[str, object]] = []
    result: dict[str, object] = {
        "schema": "cryodaq-soak-periodic-delivery-result/v1",
        "status": "PASS",
    }
    for label, generation in (("pre_fault", 1), ("post_fault", 2)):
        artifact = b"\x89PNG\r\n\x1a\nfixture" + bytes((generation,))
        artifact_sha = "sha256:" + hashlib.sha256(artifact).hexdigest()
        artifact_name = f"periodic-g{generation}-s1-{artifact_sha[7:]}.png"
        (evidence.directory / artifact_name).write_bytes(artifact)
        ledger_record = {"receipt_id": f"g{generation}:s1", "assistant_generation": generation}
        ledger.append(ledger_record)
        ledger_sha = (
            "sha256:"
            + hashlib.sha256(
                json.dumps(ledger_record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
            ).hexdigest()
        )
        result[label] = {
            "assistant_pid": 100 + generation,
            "assistant_start_identity": f"fixture-{generation}",
            "assistant_generation": generation,
            "sequence": 1,
            "receipt_id": f"g{generation}:s1",
            "artifact_sha256": artifact_sha,
            "artifact_name": artifact_name,
            "acknowledgement_sha256": "sha256:" + "a" * 64,
            "ledger_record_sha256": ledger_sha,
            "destination_fingerprint": "sha256:" + "b" * 64,
            "state_updated_at": float(generation),
            "health_updated_at": float(generation),
        }
    (evidence.directory / "periodic-receipts.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in ledger),
        encoding="ascii",
    )
    soak.atomic_json(evidence.directory / "periodic-delivery-result.json", result)


def _populate_complete(evidence: soak.Evidence) -> None:
    evidence.write_manifest(_manifest())
    _write_prerequisites(evidence)
    evidence.begin_run()
    samples = _qualification_samples()
    for sample in samples:
        evidence.append("samples.jsonl", sample)
    for fault in _faults():
        evidence.append("faults.jsonl", fault)
    evidence.write_log("log-launcher.txt", "INFO │ healthy\n")
    _write_periodic_artifacts(evidence)
    evidence.record_shutdown(_shutdown(samples))


@_POSIX_EVIDENCE
def test_foundation_cannot_authorize_pass_without_execution_provenance(tmp_path: Path) -> None:
    invalid = soak.Evidence(tmp_path / "invalid")
    assert not hasattr(invalid, "finish")
    with pytest.raises(RuntimeError, match="invalid evidence transition"):
        invalid.finish_pass()
    assert invalid.state == soak.RunState.FAIL

    evidence = soak.Evidence(tmp_path / "complete")
    _populate_complete(evidence)
    with pytest.raises(ValueError, match="execution-produced exact-six runner authority"):
        evidence.seal()
    summary = json.loads((evidence.directory / "summary.json").read_text())
    assert summary["status"] == "FAIL"
    assert summary["state"] == "FAIL"
    assert summary["finished_at"]
    with pytest.raises(RuntimeError, match="invalid evidence transition"):
        evidence.seal()


@_POSIX_EVIDENCE
def test_manifest_is_write_once_and_no_mutation_after_terminal_failure(tmp_path: Path) -> None:
    invalid = soak.Evidence(tmp_path / "manifest-reuse")
    invalid.write_manifest(_manifest())
    with pytest.raises(RuntimeError, match="invalid evidence transition"):
        invalid.write_manifest(_manifest())
    assert invalid.state == soak.RunState.FAIL

    log_reuse = soak.Evidence(tmp_path / "log-reuse")
    log_reuse.write_manifest(_manifest())
    _write_prerequisites(log_reuse)
    log_reuse.begin_run()
    log_reuse.write_log("log-launcher.txt", "INFO │ healthy\n")
    with pytest.raises(RuntimeError, match="write-once"):
        log_reuse.write_log("log-launcher.txt", "INFO │ replacement\n")
    assert (log_reuse.directory / "log-launcher.txt").read_text() == "INFO │ healthy\n"
    assert log_reuse.state == soak.RunState.FAIL

    evidence = soak.Evidence(tmp_path / "authority-blocked")
    _populate_complete(evidence)
    with pytest.raises(ValueError, match="runner authority"):
        evidence.seal()
    with pytest.raises(RuntimeError, match="invalid evidence transition"):
        evidence.write_log("log-late.txt", "late")
    assert evidence.state == soak.RunState.FAIL


@pytest.mark.parametrize(
    "artifact,mutator",
    [
        ("samples.jsonl", lambda path: path.unlink()),
        ("faults.jsonl", lambda path: path.write_text(path.read_text() + path.read_text().splitlines()[0] + "\n")),
        ("log-launcher.txt", lambda path: path.write_text("ERROR │ fatal\n")),
        ("manifest.json", lambda path: path.write_text(path.read_text().replace('"dirty": false', '"dirty": true'))),
        (
            "shutdown.json",
            lambda path: path.write_text(path.read_text().replace('"survivors": []', '"survivors": [{"pid": 1}]')),
        ),
    ],
)
@_POSIX_EVIDENCE
def test_missing_duplicate_or_failed_ledger_section_cannot_pass(tmp_path: Path, artifact: str, mutator: object) -> None:
    evidence = soak.Evidence(tmp_path)
    _populate_complete(evidence)
    mutator(tmp_path / artifact)
    with pytest.raises(ValueError):
        evidence.seal()
    assert json.loads((tmp_path / "summary.json").read_text())["status"] == "FAIL"


@pytest.mark.parametrize(
    "override",
    [
        {"status": "FAIL"},
        {"exit_code": 1},
        {"git_sha": "b" * 40},
    ],
)
@_POSIX_EVIDENCE
def test_failed_or_wrong_sha_prerequisite_cannot_advance(tmp_path: Path, override: dict[str, object]) -> None:
    evidence = soak.Evidence(tmp_path)
    evidence.write_manifest(_manifest())
    with pytest.raises(ValueError):
        _write_prerequisites(evidence, **override)
    assert evidence.state == soak.RunState.FAIL


@_POSIX_EVIDENCE
def test_dirty_sha_and_failed_recovery_cannot_seal(tmp_path: Path) -> None:
    evidence = soak.Evidence(tmp_path / "dirty")
    evidence.write_manifest(_manifest(dirty=True))
    _write_prerequisites(evidence)
    evidence.begin_run()
    samples = _qualification_samples()
    for sample in samples:
        evidence.append("samples.jsonl", sample)
    faults = _faults()
    faults[0]["ready"] = False
    for fault in faults:
        evidence.append("faults.jsonl", fault)
    evidence.write_log("log-launcher.txt", "INFO │ healthy\n")
    evidence.record_shutdown(_shutdown(samples))
    with pytest.raises(ValueError):
        evidence.seal()


@pytest.mark.parametrize("entry_kind", ["directory", "symlink"])
@_POSIX_EVIDENCE
def test_artifact_tree_rejects_nonregular_entries_and_nested_secret(tmp_path: Path, entry_kind: str) -> None:
    evidence = soak.Evidence(tmp_path)
    _populate_complete(evidence)
    outside = tmp_path.parent / f"outside-{tmp_path.name}.txt"
    outside.write_text("Authorization: Bearer nested-raw-secret\n")
    if entry_kind == "directory":
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "raw.log").write_text(outside.read_text())
    else:
        (tmp_path / "linked-secret.txt").symlink_to(outside)
    with pytest.raises(ValueError):
        evidence.seal()
    assert evidence.state == soak.RunState.FAIL
    assert outside.read_text() == "Authorization: Bearer nested-raw-secret\n"
    assert not (tmp_path / "nested").exists()
    assert not (tmp_path / "linked-secret.txt").exists()
    assert not (tmp_path / "linked-secret.txt").is_symlink()
    assert "nested-raw-secret" not in "".join(
        path.read_text(errors="replace") for path in tmp_path.iterdir() if path.is_file() and not path.is_symlink()
    )


@_POSIX_EVIDENCE
def test_symlink_inserted_after_topology_check_is_never_opened(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    evidence = soak.Evidence(tmp_path / "evidence")
    _populate_complete(evidence)
    artifact = evidence.directory / "log-launcher.txt"
    outside = tmp_path / "outside-secret.txt"
    outside_payload = b"Authorization: Bearer external-race-secret\n"
    outside.write_bytes(outside_payload)
    outside_hash = "sha256:" + hashlib.sha256(outside_payload).hexdigest()
    original_remove = evidence._remove_unsafe_entries

    def remove_then_swap() -> list[str]:
        errors = original_remove()
        artifact.unlink()
        artifact.symlink_to(outside)
        return errors

    monkeypatch.setattr(evidence, "_remove_unsafe_entries", remove_then_swap)
    with pytest.raises(ValueError):
        evidence.seal()

    assert evidence.state == soak.RunState.FAIL
    assert outside.read_bytes() == outside_payload
    assert not artifact.exists()
    retained = b"".join(
        path.read_bytes() for path in evidence.directory.iterdir() if path.is_file() and not path.is_symlink()
    )
    assert outside_payload not in retained
    assert outside_hash.encode() not in retained


@pytest.mark.parametrize("phase", ["manifest", "prerequisites", "seal"])
@_POSIX_EVIDENCE
def test_whole_evidence_root_replacement_is_terminal_and_never_touches_external_target(
    tmp_path: Path,
    phase: str,
) -> None:
    run = tmp_path / "run"
    original = tmp_path / "owned-original"
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "marker.bin"
    marker.write_bytes(b"external-authority-must-remain-untouched\x00")
    evidence = soak.Evidence(run)

    if phase == "manifest":
        prerequisite_payload = None
    elif phase == "prerequisites":
        evidence.write_manifest(_manifest())
        soak.atomic_json(run / "exact-six-result.json", _exact_six_result())
        result_hash = soak._sha256(run / "exact-six-result.json")
        prerequisite_payload = _prerequisites(result_sha256=result_hash)
    else:
        _populate_complete(evidence)
        prerequisite_payload = None

    external_before = {path.name: path.read_bytes() for path in external.iterdir()}
    run.rename(original)
    run.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="path no longer names the owned directory"):
        if phase == "manifest":
            evidence.write_manifest(_manifest())
        elif phase == "prerequisites":
            assert prerequisite_payload is not None
            evidence.write_prerequisites(prerequisite_payload)
        else:
            evidence.seal()

    assert evidence.state is soak.RunState.FAIL
    assert run.is_symlink()
    assert {path.name: path.read_bytes() for path in external.iterdir()} == external_before
    summary = json.loads((original / "summary.json").read_text())
    assert summary["status"] == "FAIL"
    assert summary["state"] == "FAIL"
    assert summary["finished_at"]


@_POSIX_EVIDENCE
def test_closed_owned_descriptor_reports_terminal_summary_unavailable_without_io(tmp_path: Path) -> None:
    evidence = soak.Evidence(tmp_path / "run")
    initial_summary = (evidence.directory / "summary.json").read_bytes()
    os.close(evidence._directory_fd)

    with pytest.raises(soak.EvidenceCapabilityError, match="unavailable"):
        evidence.write_manifest(_manifest())

    assert evidence.state is soak.RunState.FAIL
    assert not evidence.terminal_summary_available
    assert (evidence.directory / "summary.json").read_bytes() == initial_summary
    assert evidence.closed
    assert not evidence.close()


@_POSIX_EVIDENCE
def test_reused_descriptor_never_writes_or_closes_external_directory(tmp_path: Path) -> None:
    evidence = soak.Evidence(tmp_path / "run")
    initial_summary = (evidence.directory / "summary.json").read_bytes()
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "marker.bin"
    marker.write_bytes(b"external-directory-is-not-evidence")
    owned_fd = evidence._directory_fd
    os.close(owned_fd)
    external_fd = os.open(external, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    assert external_fd == owned_fd
    external_before = {path.name: path.read_bytes() for path in external.iterdir()}

    try:
        with pytest.raises(soak.EvidenceCapabilityError, match="changed"):
            evidence.write_manifest(_manifest())
        assert evidence.state is soak.RunState.FAIL
        assert not evidence.terminal_summary_available
        assert (evidence.directory / "summary.json").read_bytes() == initial_summary
        assert {path.name: path.read_bytes() for path in external.iterdir()} == external_before
        assert evidence.closed
        assert not evidence.close()
        assert os.fstat(external_fd).st_ino == external.stat().st_ino
    finally:
        os.close(external_fd)


@_POSIX_EVIDENCE
def test_close_is_idempotent_and_all_post_close_mutations_are_io_free(tmp_path: Path) -> None:
    evidence = soak.Evidence(tmp_path / "run")

    assert evidence.close()
    assert evidence.closed
    assert evidence.state is soak.RunState.FAIL
    assert evidence.terminal_summary_available
    summary = (evidence.directory / "summary.json").read_bytes()
    assert not evidence.close()

    operations = (
        lambda: evidence.write_manifest(_manifest()),
        lambda: evidence.write_prerequisites(_prerequisites()),
        lambda: evidence.write_exact_six_result(_exact_six_result()),
        evidence.begin_run,
        lambda: evidence.append("samples.jsonl", {}),
        lambda: evidence.write_log("log-test.txt", "INFO"),
        lambda: evidence.record_shutdown({}),
        evidence.seal,
        lambda: evidence.finish_fail("late failure"),
        evidence.finish_pass,
    )
    for operation in operations:
        with pytest.raises(soak.EvidenceUnavailableError, match="closed"):
            operation()
        assert (evidence.directory / "summary.json").read_bytes() == summary


@_POSIX_EVIDENCE
def test_context_manager_and_gc_settle_failure_and_release_descriptors(tmp_path: Path) -> None:
    context_path = tmp_path / "context"
    with soak.Evidence(context_path) as evidence:
        assert not evidence.closed
        context_fd = evidence._directory_fd
    assert evidence.closed
    assert evidence.terminal_summary_available
    with pytest.raises(OSError):
        os.fstat(context_fd)
    assert json.loads((context_path / "summary.json").read_text())["status"] == "FAIL"

    gc_path = tmp_path / "gc"
    unclosed = soak.Evidence(gc_path)
    gc_fd = unclosed._directory_fd
    del unclosed
    gc.collect()

    with pytest.raises(OSError):
        os.fstat(gc_fd)
    assert json.loads((gc_path / "summary.json").read_text())["status"] == "FAIL"


@_POSIX_EVIDENCE
def test_context_close_after_root_replacement_writes_only_pinned_original(tmp_path: Path) -> None:
    run = tmp_path / "run"
    original = tmp_path / "original"
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "marker"
    marker.write_bytes(b"unchanged")

    with soak.Evidence(run) as evidence:
        run.rename(original)
        run.symlink_to(external, target_is_directory=True)

    assert evidence.closed
    assert evidence.terminal_summary_available
    assert json.loads((original / "summary.json").read_text())["status"] == "FAIL"
    assert {path.name: path.read_bytes() for path in external.iterdir()} == {"marker": b"unchanged"}


def _assert_two_terminal_retries(
    evidence: soak.Evidence,
    retry: object,
) -> None:
    summary = (evidence.directory / "summary.json").read_bytes()
    for _attempt in range(2):
        with pytest.raises(RuntimeError, match="invalid evidence transition"):
            retry()
        assert (evidence.directory / "summary.json").read_bytes() == summary


@_POSIX_EVIDENCE
def test_huge_shutdown_is_normalized_terminal_and_exactly_two_retries_fail(tmp_path: Path) -> None:
    evidence = soak.Evidence(tmp_path)
    evidence.write_manifest(_manifest())
    _write_prerequisites(evidence)
    evidence.begin_run()
    invalid = _shutdown(_qualification_samples())
    invalid["elapsed_s"] = 10**1000

    with pytest.raises(ValueError, match="bounded evidence range"):
        evidence.record_shutdown(invalid)

    assert evidence.state == soak.RunState.FAIL
    _assert_two_terminal_retries(
        evidence,
        lambda: evidence.record_shutdown(_shutdown(_qualification_samples())),
    )


@_POSIX_EVIDENCE
def test_wrong_prerequisite_container_is_terminal_and_exactly_two_retries_fail(tmp_path: Path) -> None:
    evidence = soak.Evidence(tmp_path)
    evidence.write_manifest(_manifest())
    soak.atomic_json(tmp_path / "exact-six-result.json", _exact_six_result())
    invalid = _prerequisites()
    invalid["exact_six"] = []

    with pytest.raises(ValueError):
        evidence.write_prerequisites(invalid)

    assert evidence.state == soak.RunState.FAIL
    _assert_two_terminal_retries(evidence, lambda: evidence.write_prerequisites(_prerequisites()))


@pytest.mark.parametrize(
    ("stream", "payload"),
    [
        ("samples.jsonl", {"elapsed_s": 10**1000, "wall_time": "x", "roles": {}}),
        ("faults.jsonl", {"target": "engine"}),
        ("samples.jsonl", {"elapsed_s": object(), "wall_time": "x", "roles": {}}),
    ],
)
@_POSIX_EVIDENCE
def test_malformed_public_stream_mutation_is_terminal(
    tmp_path: Path,
    stream: str,
    payload: dict[str, object],
) -> None:
    evidence = soak.Evidence(tmp_path)
    evidence.write_manifest(_manifest())
    _write_prerequisites(evidence)
    evidence.begin_run()

    with pytest.raises(ValueError):
        evidence.append(stream, payload)

    assert evidence.state == soak.RunState.FAIL
    with pytest.raises(RuntimeError, match="invalid evidence transition"):
        evidence.append(stream, payload)


@pytest.mark.parametrize("command", [["true"], list(soak.EXACT_SIX_COMMAND)])
@_POSIX_EVIDENCE
def test_caller_asserted_exact_six_result_is_never_authority(tmp_path: Path, command: list[str]) -> None:
    invalid = soak.Evidence(tmp_path)
    invalid.write_manifest(_manifest())
    result = _exact_six_result()
    result["command"] = command
    with pytest.raises(RuntimeError, match="execution-produced runner authority"):
        invalid.write_exact_six_result(result)
    assert invalid.state == soak.RunState.FAIL
    assert not (tmp_path / "exact-six-result.json").exists()


@_POSIX_EVIDENCE
def test_exact_six_result_mutation_is_rejected(tmp_path: Path) -> None:

    evidence = soak.Evidence(tmp_path / "mutation")
    evidence.write_manifest(_manifest())
    _write_prerequisites(evidence)
    result_path = evidence.directory / "exact-six-result.json"
    result_path.write_text(result_path.read_text().replace('"status": "PASS"', '"status": "FAIL"'))
    evidence.begin_run()
    samples = _qualification_samples()
    for sample in samples:
        evidence.append("samples.jsonl", sample)
    for fault in _faults():
        evidence.append("faults.jsonl", fault)
    evidence.write_log("log-launcher.txt", "INFO │ healthy\n")
    _write_periodic_artifacts(evidence)
    evidence.record_shutdown(_shutdown(samples))
    with pytest.raises(ValueError, match="exact-six"):
        evidence.seal()


@_POSIX_EVIDENCE
def test_arbitrary_source_command_and_missing_role_fail_terminally(tmp_path: Path) -> None:
    arbitrary = soak.Evidence(tmp_path / "arbitrary")
    manifest = _manifest()
    manifest["source_command"] = ["true"]
    arbitrary.write_manifest(manifest)
    _write_prerequisites(arbitrary)
    arbitrary.begin_run()
    samples = _qualification_samples()
    for sample in samples:
        arbitrary.append("samples.jsonl", sample)
    for fault in _faults():
        arbitrary.append("faults.jsonl", fault)
    arbitrary.write_log("log-launcher.txt", "INFO │ healthy\n")
    _write_periodic_artifacts(arbitrary)
    arbitrary.record_shutdown(_shutdown(samples))
    with pytest.raises(ValueError, match="canonical current-interpreter launcher"):
        arbitrary.seal()
    assert arbitrary.state == soak.RunState.FAIL

    missing_role = soak.Evidence(tmp_path / "missing-role")
    _populate_complete(missing_role)
    rows = (missing_role.directory / "samples.jsonl").read_text().splitlines()
    first = json.loads(rows[0])
    del first["roles"]["bridge"]
    rows[0] = json.dumps(first)
    (missing_role.directory / "samples.jsonl").write_text("\n".join(rows) + "\n")
    with pytest.raises(ValueError) as caught:
        missing_role.seal()
    assert not isinstance(caught.value.__cause__, KeyError)
    assert missing_role.state == soak.RunState.FAIL
    summary = json.loads((missing_role.directory / "summary.json").read_text())
    assert summary["status"] == "FAIL"
    assert summary["finished_at"]
    with pytest.raises(RuntimeError, match="invalid evidence transition"):
        missing_role.seal()


def test_faults_are_exactly_correlated_to_sample_transitions_and_injection_contract() -> None:
    selected = soak.profile("short")
    samples = _qualification_samples()
    faults = _faults()
    assert soak._validate_faults(faults, selected, samples) == []

    bad_method = json.loads(json.dumps(faults))
    bad_method[0]["injection_method"] = "subprocess.kill"
    assert any("injection contract" in error for error in soak._validate_faults(bad_method, selected, samples))

    wrong_pre = json.loads(json.dumps(faults))
    wrong_pre[0]["pre_pid"] = wrong_pre[0]["recheck_pid"] = 999
    errors = soak._validate_faults(wrong_pre, selected, samples)
    assert any("immediately preceding sample" in error for error in errors)

    phantom = json.loads(json.dumps(samples))
    for sample in phantom:
        if float(sample["elapsed_s"]) >= 500:
            sample["roles"]["engine"].update({"epoch": 2, "pid": 121, "started_ns": 1210})
    errors = soak._validate_faults(faults, selected, phantom)
    assert any("phantom" in error or "one-to-one" in error for error in errors)

    launcher_restart = json.loads(json.dumps(samples))
    launcher_restart[-1]["roles"]["launcher"].update({"epoch": 1, "pid": 110, "started_ns": 1100})
    errors = soak._validate_faults(faults, selected, launcher_restart)
    assert "launcher or bridge restarted during fault qualification" in errors


@_POSIX_EVIDENCE
def test_fault_and_shutdown_identities_require_exact_positive_integers(tmp_path: Path) -> None:
    evidence = soak.Evidence(tmp_path / "fault")
    evidence.write_manifest(_manifest())
    _write_prerequisites(evidence)
    evidence.begin_run()
    samples = _qualification_samples()
    for sample in samples:
        evidence.append("samples.jsonl", sample)
    faults = _faults()
    faults[0]["pre_pid"] = True
    for fault in faults:
        evidence.append("faults.jsonl", fault)
    evidence.write_log("log-launcher.txt", "INFO │ healthy\n")
    _write_periodic_artifacts(evidence)
    evidence.record_shutdown(_shutdown(samples))
    with pytest.raises(ValueError, match="positive integer"):
        evidence.seal()

    invalid_shutdown = soak.Evidence(tmp_path / "shutdown")
    invalid_shutdown.write_manifest(_manifest())
    _write_prerequisites(invalid_shutdown)
    invalid_shutdown.begin_run()
    shutdown = _shutdown(samples)
    shutdown["observed_identities"][0]["pid"] = True
    with pytest.raises(ValueError, match="identity values"):
        invalid_shutdown.record_shutdown(shutdown)
    assert invalid_shutdown.state == soak.RunState.FAIL


@_POSIX_EVIDENCE
def test_finish_pass_validation_exception_is_terminal_and_normalized(tmp_path: Path) -> None:
    evidence = soak.Evidence(tmp_path)
    _populate_complete(evidence)
    evidence.state = soak.RunState.EVIDENCE_SEALED
    (tmp_path / "ledger.json").write_text("{}")
    (tmp_path / "samples.jsonl").unlink()
    with pytest.raises(ValueError):
        evidence.finish_pass()
    assert evidence.state == soak.RunState.FAIL
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["finished_at"]
    with pytest.raises(RuntimeError, match="invalid evidence transition"):
        evidence.finish_pass()


@_POSIX_EVIDENCE
def test_atomic_log_writer_redacts_and_external_secret_is_quarantined(tmp_path: Path) -> None:
    evidence = soak.Evidence(tmp_path)
    evidence.write_manifest(_manifest())
    _write_prerequisites(evidence)
    evidence.begin_run()
    evidence.write_log("log-launcher.txt", "Authorization: Bearer raw-secret\n")
    assert "raw-secret" not in (tmp_path / "log-launcher.txt").read_text()
    samples = _qualification_samples()
    for sample in samples:
        evidence.append("samples.jsonl", sample)
    for fault in _faults():
        evidence.append("faults.jsonl", fault)
    evidence.record_shutdown(_shutdown(samples))
    (tmp_path / "log-launcher.txt").write_text("Authorization: Bearer injected-secret\n")
    with pytest.raises(ValueError, match="secret detection"):
        evidence.seal()
    assert "injected-secret" not in (tmp_path / "log-launcher.txt").read_text()
    assert soak.secret_findings(tmp_path) == []
    quarantine = json.loads((tmp_path / "quarantine.json").read_text())
    assert quarantine["records"][0]["original_sha256"].startswith("sha256:")


@_POSIX_EVIDENCE
def test_evidence_forbids_environment_capture_and_failure_has_typed_metadata(tmp_path: Path) -> None:
    invalid = soak.Evidence(tmp_path / "invalid")
    with pytest.raises(ValueError, match="forbidden"):
        invalid.write_manifest({"environment": {"HOME": "/private"}})
    assert invalid.state == soak.RunState.FAIL

    evidence = soak.Evidence(tmp_path / "typed-failure")
    evidence.write_manifest(_manifest())
    evidence.finish_fail("blocked", phase="setup", error_type="GateError")
    summary = json.loads((evidence.directory / "summary.json").read_text())
    assert "environment" not in json.dumps(summary).casefold()


@pytest.mark.parametrize(
    "artifact,mutator,error_marker",
    [
        (
            "samples.jsonl",
            lambda value: {**value, "environment": {"HOME": "/private"}},
            "fields are not exact",
        ),
        (
            "manifest.json",
            lambda value: {**value, "thresholds": {"sample_interval_s": 999}},
            "thresholds differ",
        ),
        (
            "manifest.json",
            lambda value: {**value, "periodic_schedule": {"interval_s": 60}},
            "periodic schedule",
        ),
        (
            "log_capture.json",
            lambda value: {**value, "artifacts": ["../outside.txt"]},
            "log artifact list",
        ),
    ],
)
@_POSIX_EVIDENCE
def test_external_schema_or_path_tampering_cannot_seal(
    tmp_path: Path,
    artifact: str,
    mutator: object,
    error_marker: str,
) -> None:
    evidence = soak.Evidence(tmp_path)
    _populate_complete(evidence)
    path = tmp_path / artifact
    if artifact.endswith(".jsonl"):
        rows = path.read_text().splitlines()
        rows[0] = json.dumps(mutator(json.loads(rows[0])))
        path.write_text("\n".join(rows) + "\n")
    else:
        path.write_text(json.dumps(mutator(json.loads(path.read_text()))))
    with pytest.raises(ValueError, match=error_marker):
        evidence.seal()


@pytest.mark.parametrize(
    "overrides,error_marker",
    [
        ({"observer": {"identity": "", "version": "7.0", "locked": True}}, "observer identity"),
        (
            {"exact_six": {"command": [], "git_sha": "a" * 40, "exit_code": 0, "status": "PASS"}},
            "exact-six command",
        ),
    ],
)
@_POSIX_EVIDENCE
def test_prerequisites_require_nonempty_typed_identities(
    tmp_path: Path, overrides: dict[str, object], error_marker: str
) -> None:
    evidence = soak.Evidence(tmp_path)
    evidence.write_manifest(_manifest())
    soak.atomic_json(tmp_path / "exact-six-result.json", _exact_six_result())
    payload = _prerequisites()
    payload["exact_six"]["result_sha256"] = soak._sha256(tmp_path / "exact-six-result.json")
    payload.update(overrides)
    with pytest.raises(ValueError, match=error_marker):
        evidence.write_prerequisites(payload)


@pytest.mark.parametrize("phase", ["setup", "sampling", "injection", "recovery", "shutdown"])
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
@_POSIX_EVIDENCE
def test_lifecycle_interruption_is_atomic_and_idempotent(tmp_path: Path, phase: str, signum: int) -> None:
    evidence = soak.Evidence(tmp_path)
    cleanup_calls: list[str] = []
    lifecycle = soak.Lifecycle(evidence, lambda: cleanup_calls.append("cleanup"))
    lifecycle.set_phase(phase)
    with pytest.raises(soak.RunInterrupted):
        lifecycle.interrupt(signum)
    assert cleanup_calls == ["cleanup"]
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["status"] == "FAIL"
    assert summary["phase"] == phase
    assert not evidence.finish_fail("second finalization")


@_POSIX_EVIDENCE
def test_evidence_rejects_nonempty_run_directory(tmp_path: Path) -> None:
    (tmp_path / "stale.jsonl").write_text("stale")
    with pytest.raises(FileExistsError, match="must be empty"):
        soak.Evidence(tmp_path)


@_POSIX_EVIDENCE
def test_cli_delegates_manifest_and_execution_to_integrated_runner(monkeypatch, tmp_path: Path) -> None:
    from scripts import soak_mock_stack_runner as runner

    class FakeRunner:
        @staticmethod
        def require_platform() -> None:
            return None

        def run(self, evidence: soak.Evidence) -> None:
            evidence.write_manifest(
                {
                    "profile": "short",
                    "git_sha": "a" * 40,
                    "dirty": False,
                    "platform": "test-posix",
                    "python": sys.version,
                    "source_command": [sys.executable, "-m", "cryodaq.launcher", "--mock", "--tray"],
                    "thresholds": soak.effective_thresholds(soak.profile("short")),
                    "fatal_log_allowlist": [],
                    "capture_policy": "allowlisted metadata only; environment values forbidden",
                }
            )
            raise RuntimeError("deterministic runner stop")

    monkeypatch.setattr(runner, "_PosixSoakRunner", FakeRunner)
    run = tmp_path / "run"
    assert soak.main(["--profile", "short", "--evidence-dir", str(run)]) == 1
    manifest = json.loads((run / "manifest.json").read_text())
    summary = json.loads((run / "summary.json").read_text())
    assert manifest["schema"] == soak.SCHEMA
    assert manifest["thresholds"]["max_slope_pairs"] == soak.MAX_SLOPE_PAIRS
    assert manifest["thresholds"]["recovery_ceiling_s"] == 60
    assert manifest["thresholds"]["shutdown_ceiling_s"] == 20
    assert manifest["profile"] == "short"
    assert manifest["source_command"][-2:] == ["--mock", "--tray"]
    assert summary["status"] == "FAIL"
    assert summary["manifest_sha256"].startswith("sha256:")


@_POSIX_EVIDENCE
def test_module_entrypoint_preserves_exact_evidence_type(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    hook_dir = tmp_path / "hook"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(
        """
from scripts import soak_mock_stack_runner as runner

class FakeRunner:
    @staticmethod
    def require_platform():
        return None

    def run(self, evidence):
        from scripts import soak_mock_stack as soak
        if type(evidence) is not soak.Evidence:
            raise TypeError("evidence must be the exact Evidence type")
        raise RuntimeError("subprocess-entrypoint-sentinel")

runner._PosixSoakRunner = FakeRunner
""".lstrip(),
        encoding="utf-8",
    )
    evidence_dir = tmp_path / "entrypoint-evidence"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(hook_dir), str(repo_root / "src"), str(repo_root)))

    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "scripts.soak_mock_stack",
            "--profile",
            "short",
            "--evidence-dir",
            str(evidence_dir),
        ),
        cwd=repo_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 1, completed.stderr
    summary = json.loads((evidence_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["reason"] == "subprocess-entrypoint-sentinel"


@_POSIX_EVIDENCE
def test_module_entrypoint_rejects_preloaded_canonical_module(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    hook_dir = tmp_path / "preload-hook"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(
        """
import os
from pathlib import Path

from scripts import soak_mock_stack
from scripts import soak_mock_stack_runner as runner

class MustNotRun:
    @staticmethod
    def require_platform():
        Path(os.environ["CRYODAQ_PRELOAD_MARKER"]).write_text("require-platform")

    def run(self, evidence):
        Path(os.environ["CRYODAQ_PRELOAD_MARKER"]).write_text("run")

runner._PosixSoakRunner = MustNotRun
""".lstrip(),
        encoding="utf-8",
    )
    evidence_dir = tmp_path / "preloaded-evidence"
    marker = tmp_path / "runner-called"
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(hook_dir), str(repo_root / "src"), str(repo_root)))
    environment["CRYODAQ_PRELOAD_MARKER"] = str(marker)

    completed = subprocess.run(
        (
            sys.executable,
            "-m",
            "scripts.soak_mock_stack",
            "--profile",
            "short",
            "--evidence-dir",
            str(evidence_dir),
        ),
        cwd=repo_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode != 0
    assert "canonical soak module is already loaded" in completed.stderr
    assert not marker.exists()
    assert not evidence_dir.exists()


@_POSIX_EVIDENCE
def test_cli_has_no_caller_acknowledgement_bypass(tmp_path: Path) -> None:
    run = tmp_path / "acknowledged"
    with pytest.raises(SystemExit):
        soak.main(
            [
                "--profile",
                "short",
                "--evidence-dir",
                str(run),
                "--acknowledge-runtime-prerequisites",
            ]
        )
    assert not run.exists()


@_POSIX_EVIDENCE
def test_initial_summary_is_incomplete_fail(tmp_path: Path) -> None:
    evidence = soak.Evidence(tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["status"] == "FAIL"
    assert summary["reason"] == "incomplete"
    assert not evidence.terminal
