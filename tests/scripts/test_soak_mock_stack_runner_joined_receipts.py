from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cryodaq.agents.assistant.periodic_delivery import PeriodicDeliveryReceipt
from cryodaq.periodic_config import load_periodic_png_config
from cryodaq.periodic_state import (
    PeriodicArtifact,
    allocate_pending,
    latest_completed_slot,
    load_periodic_state,
    mark_delivering,
    mark_ready,
    mark_rendering,
    mark_succeeded,
    periodic_local_destination_fingerprint,
    rotate_terminal_active,
    set_periodic_health,
)
from scripts import soak_mock_stack as soak
from scripts import soak_mock_stack_runner as runner

_POSIX_EVIDENCE = pytest.mark.skipif(os.name != "posix", reason="POSIX evidence filesystem authority")


def _config(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "notifications.yaml").write_text(
        "telegram:\n"
        "  bot_token: '123456:abcdefghijklmnopqrstuvwxyzABCDE'\n"
        "  chat_id: 1\n"
        "periodic_report:\n"
        "  enabled: true\n"
        "  report_interval_s: 60\n",
        encoding="utf-8",
    )
    loaded = load_periodic_png_config(config_dir)
    assert loaded.config is not None
    return loaded.config


def _joined_cut(tmp_path: Path, *, serial: int, slot_end: int, nonce: str | None = None):
    photo = b"\x89PNG\r\n\x1a\n" + (b"fixture" + bytes([serial])) * 20
    artifact_hash = f"sha256:{hashlib.sha256(photo).hexdigest()}"
    nonce = f"{serial:064x}" if nonce is None else nonce
    generation = f"{serial:032x}"
    owner = f"{serial + 100:032x}"
    config = _config(tmp_path)
    slot = latest_completed_slot(float(slot_end), config.interval_s)
    state = allocate_pending(
        load_periodic_state(tmp_path / f"data-{serial}"),
        slot,
        config,
        generation_id=generation,
        owner_token=owner,
        display_time="10.07.2026 04:05",
        now=float(slot_end + 1),
        destination_fingerprint=periodic_local_destination_fingerprint(nonce),
    )
    state = mark_rendering(state, slot_id=slot.slot_id, owner_token=owner, now=float(slot_end + 2))
    state = mark_ready(
        state,
        PeriodicArtifact(
            path=f"periodic/generations/{generation}/periodic.png",
            sha256=artifact_hash,
            size=len(photo),
            width=100,
            height=100,
            mime="image/png",
        ),
        "caption",
        slot_id=slot.slot_id,
        owner_token=owner,
        now=float(slot_end + 3),
    )
    state = mark_delivering(state, slot_id=slot.slot_id, owner_token=owner, now=float(slot_end + 4))
    delivery_state = state.payload

    receipt_id = f"g{serial}:s1"
    ack_core = {
        "artifact_sha256": artifact_hash,
        "assistant_generation": serial,
        "assistant_pid": 200 + serial,
        "nonce": nonce,
        "receipt_id": receipt_id,
        "schema": "cryodaq.soak.periodic-artifact",
        "sequence": 1,
        "type": "ack",
        "version": 1,
    }
    ack_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(ack_core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        ).hexdigest()
    )
    state = mark_succeeded(
        state,
        receipt=PeriodicDeliveryReceipt("soak_local", receipt_id, ack_hash),
        slot_id=slot.slot_id,
        owner_token=owner,
        now=float(slot_end + 5),
    )
    state = rotate_terminal_active(state, now=float(slot_end + 6))
    state = set_periodic_health(state, status="ready", code=None, text="", now=float(slot_end + 7))
    record = {
        "acknowledgement_sha256": ack_hash,
        "artifact_sha256": artifact_hash,
        "artifact_size": len(photo),
        "assistant_generation": serial,
        "assistant_pid": 200 + serial,
        "assistant_start_identity": f"start-{serial}",
        "caption_sha256": "sha256:" + "c" * 64,
        "caption_size": 7,
        "filename": f"periodic-g{serial}-s1-{artifact_hash[7:]}.png",
        "generation_id": generation,
        "nonce": nonce,
        "owner_token": owner,
        "receipt_id": receipt_id,
        "schema": "cryodaq.soak.periodic-artifact",
        "sequence": 1,
        "slot_id": slot.slot_id,
        "type": "artifact",
        "version": 1,
    }
    observation = runner._AssistantProcessObservation(
        runner._ProcessIdentity(200 + serial, f"start-{serial}"),
        100,
        "assistant",
        True,
    )
    joined = runner._validate_joined_receipt(
        ledger_record=record,
        delivery_state_payload=delivery_state,
        terminal_state_payload=state.payload,
        artifact_bytes=photo,
        assistant_observation=observation,
        expected_launcher_pid=100,
    )
    return joined, record, delivery_state, state.payload, photo, observation


def _pre_post_kwargs(tmp_path: Path) -> dict[str, object]:
    shared_nonce = "a" * 64
    _pre_joined, pre_record, pre_delivery, pre_terminal, pre_photo, pre_observation = _joined_cut(
        tmp_path, serial=1, slot_end=7_200, nonce=shared_nonce
    )
    _post_joined, post_record, post_delivery, post_terminal, post_photo, post_observation = _joined_cut(
        tmp_path, serial=2, slot_end=7_260, nonce=shared_nonce
    )
    return {
        "pre_ledger_record": pre_record,
        "pre_delivery_state_payload": pre_delivery,
        "pre_terminal_state_payload": pre_terminal,
        "pre_artifact_bytes": pre_photo,
        "pre_assistant_observation": pre_observation,
        "post_ledger_record": post_record,
        "post_delivery_state_payload": post_delivery,
        "post_terminal_state_payload": post_terminal,
        "post_artifact_bytes": post_photo,
        "post_assistant_observation": post_observation,
        "expected_launcher_pid": 100,
        "expected_interval_s": 60,
        "ledger_records": (pre_record, post_record),
    }


def _prepare_real_periodic_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[soak.Evidence, runner._PosixSoakRunner, tuple[dict[str, object], dict[str, object]]]:
    """Prepare the real registry-to-Evidence acceptance path without a long source run."""

    kwargs = _pre_post_kwargs(tmp_path)
    records = kwargs["ledger_records"]
    assert isinstance(records, tuple) and len(records) == 2
    typed_records = (records[0], records[1])
    assert all(type(record) is dict for record in typed_records)

    evidence = soak.Evidence(tmp_path / "evidence")
    evidence.state = soak.RunState.RUNNING
    photos = (kwargs["pre_artifact_bytes"], kwargs["post_artifact_bytes"])
    for record, photo in zip(typed_records, photos, strict=True):
        assert isinstance(photo, bytes)
        artifact = evidence.directory / str(record["filename"])
        artifact.write_bytes(photo)
        artifact.chmod(0o600)
    receipts = evidence.directory / "periodic-receipts.jsonl"
    receipts.write_text(
        "".join(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in typed_records),
        encoding="ascii",
    )
    receipts.chmod(0o600)

    result_kwargs = dict(kwargs)
    result_kwargs["report_interval_s"] = result_kwargs.pop("expected_interval_s")
    private_result = runner._OwnedRunResult(
        **result_kwargs,
        observations=(),
        survivors=(),
        graceful=True,
        shutdown_elapsed=0.1,
        collector=SimpleNamespace(observations=()),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(runner._PosixSoakRunner, "_run_owned", lambda self, candidate: private_result)
    monkeypatch.setattr(runner._PosixSoakRunner, "_finish_owned", lambda self, candidate, result: None)
    owner = runner._PosixSoakRunner()
    owner._used = True
    return evidence, owner, typed_records


def _accept_real_periodic_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[soak.Evidence, tuple[dict[str, object], dict[str, object]]]:
    evidence, owner, records = _prepare_real_periodic_acceptance(monkeypatch, tmp_path)
    try:
        runner._DELIVERY_EVIDENCE.run(owner, evidence)
        evidence._verify_periodic_delivery_seal()
    except BaseException:
        evidence.close()
        raise
    return evidence, records


@_POSIX_EVIDENCE
def test_real_registry_acceptance_captures_private_periodic_seal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence, records = _accept_real_periodic_evidence(monkeypatch, tmp_path)
    try:
        assert evidence.state is soak.RunState.RUNNING
        assert evidence._periodic_delivery_seal is not None
        assert tuple(item[0] for item in evidence._periodic_delivery_seal) == (
            "periodic-delivery-result.json",
            "periodic-receipts.jsonl",
            str(records[0]["filename"]),
            str(records[1]["filename"]),
        )
    finally:
        evidence.close()


@_POSIX_EVIDENCE
def test_private_periodic_seal_rejects_post_accept_in_place_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence, records = _accept_real_periodic_evidence(monkeypatch, tmp_path)
    try:
        artifact = evidence.directory / str(records[0]["filename"])
        artifact.write_bytes(artifact.read_bytes() + b"mutated")
        with pytest.raises(ValueError, match="authority-sealed"):
            evidence._verify_periodic_delivery_seal()
    finally:
        evidence.close()


@_POSIX_EVIDENCE
def test_private_periodic_seal_rejects_same_bytes_with_restored_mtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence, records = _accept_real_periodic_evidence(monkeypatch, tmp_path)
    try:
        artifact = evidence.directory / str(records[0]["filename"])
        original = artifact.read_bytes()
        identity = artifact.stat()
        time.sleep(0.01)
        artifact.write_bytes(bytes(byte ^ 0xFF for byte in original))
        artifact.write_bytes(original)
        os.utime(artifact, ns=(identity.st_atime_ns, identity.st_mtime_ns))
        assert artifact.read_bytes() == original
        assert artifact.stat().st_mtime_ns == identity.st_mtime_ns
        with pytest.raises(ValueError, match="authority-sealed"):
            evidence._verify_periodic_delivery_seal()
    finally:
        evidence.close()


@_POSIX_EVIDENCE
def test_private_periodic_seal_rejects_same_byte_inode_replacement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence, records = _accept_real_periodic_evidence(monkeypatch, tmp_path)
    try:
        artifact = evidence.directory / str(records[0]["filename"])
        replacement = evidence.directory / "replacement.tmp"
        replacement.write_bytes(artifact.read_bytes())
        replacement.chmod(0o600)
        os.replace(replacement, artifact)
        with pytest.raises(ValueError, match="authority-sealed"):
            evidence._verify_periodic_delivery_seal()
    finally:
        evidence.close()


@_POSIX_EVIDENCE
def test_real_acceptance_rejects_png_mutation_before_private_seal_capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence, owner, records = _prepare_real_periodic_acceptance(monkeypatch, tmp_path)
    target = evidence.directory / str(records[0]["filename"])
    original_atomic_json_at = soak._atomic_json_at

    def interposed_atomic_json_at(
        directory_fd: int,
        name: str,
        payload: dict[str, object],
        *,
        replace: bool = True,
    ) -> None:
        original_atomic_json_at(directory_fd, name, payload, replace=replace)
        if name == "periodic-delivery-result.json":
            target.write_bytes(b"not-a-png-after-initial-validation")

    monkeypatch.setattr(soak, "_atomic_json_at", interposed_atomic_json_at)
    try:
        with pytest.raises(ValueError, match="PNG"):
            runner._DELIVERY_EVIDENCE.run(owner, evidence)
        assert evidence.state is soak.RunState.FAIL
    finally:
        evidence.close()


@_POSIX_EVIDENCE
def test_private_periodic_seal_rejects_post_accept_hardlink(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    evidence, records = _accept_real_periodic_evidence(monkeypatch, tmp_path)
    linked = tmp_path / "linked-periodic.png"
    try:
        os.link(evidence.directory / str(records[0]["filename"]), linked)
        with pytest.raises(ValueError, match="authority-sealed"):
            evidence._verify_periodic_delivery_seal()
    finally:
        linked.unlink(missing_ok=True)
        evidence.close()


@_POSIX_EVIDENCE
def test_private_periodic_seal_rejects_coordinated_valid_rewrite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence, records = _accept_real_periodic_evidence(monkeypatch, tmp_path)
    try:
        rewritten_records = copy.deepcopy(list(records))
        result_path = evidence.directory / "periodic-delivery-result.json"
        rewritten_result = json.loads(result_path.read_text(encoding="utf-8"))
        for index, (label, record) in enumerate(
            zip(("pre_fault", "post_fault"), rewritten_records, strict=True),
            start=1,
        ):
            old_name = str(record["filename"])
            photo = b"\x89PNG\r\n\x1a\ncoordinated-rewrite" + bytes((index,))
            digest = "sha256:" + hashlib.sha256(photo).hexdigest()
            new_name = f"periodic-g{record['assistant_generation']}-s{record['sequence']}-{digest[7:]}.png"
            new_artifact = evidence.directory / new_name
            new_artifact.write_bytes(photo)
            new_artifact.chmod(0o600)
            (evidence.directory / old_name).unlink()
            record["artifact_sha256"] = digest
            record["artifact_size"] = len(photo)
            record["filename"] = new_name
            rewritten_result[label]["artifact_sha256"] = digest
            rewritten_result[label]["artifact_name"] = new_name
            rewritten_result[label]["ledger_record_sha256"] = (
                "sha256:"
                + hashlib.sha256(
                    json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
                ).hexdigest()
            )
        receipts = evidence.directory / "periodic-receipts.jsonl"
        receipts.write_text(
            "".join(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n" for record in rewritten_records),
            encoding="ascii",
        )
        result_path.write_text(
            json.dumps(rewritten_result, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with pytest.raises((OSError, ValueError)):
            evidence._verify_periodic_delivery_seal()
    finally:
        evidence.close()


@_POSIX_EVIDENCE
def test_real_periodic_acceptance_rejects_preexisting_hardlink(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    evidence, owner, records = _prepare_real_periodic_acceptance(monkeypatch, tmp_path)
    linked = tmp_path / "preaccepted-link.png"
    try:
        os.link(evidence.directory / str(records[0]["filename"]), linked)
        with pytest.raises(ValueError, match="identity is unsafe"):
            runner._DELIVERY_EVIDENCE.run(owner, evidence)
        assert evidence.state is soak.RunState.FAIL
        assert json.loads((evidence.directory / "summary.json").read_text(encoding="utf-8"))["status"] == "FAIL"
    finally:
        linked.unlink(missing_ok=True)
        evidence.close()


@_POSIX_EVIDENCE
def test_pass_summary_interposition_is_rechecked_and_leaves_durable_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence, records = _accept_real_periodic_evidence(monkeypatch, tmp_path)
    evidence._atomic_json("ledger.json", {})
    evidence.state = soak.RunState.EVIDENCE_SEALED
    fake_ledger = SimpleNamespace(
        payload=lambda: {},
        run=SimpleNamespace(manifest_sha256="sha256:" + "0" * 64),
    )
    monkeypatch.setattr(soak.Evidence, "_build_ledger", lambda self: (fake_ledger, []))
    original_atomic_json = soak.Evidence._atomic_json
    target = evidence.directory / str(records[0]["filename"])

    def interposed_atomic_json(self: soak.Evidence, name: str, payload: dict[str, object]) -> None:
        original_atomic_json(self, name, payload)
        if name == "summary.json" and payload.get("status") == "PASS":
            target.write_bytes(target.read_bytes() + b"interposed")

    monkeypatch.setattr(soak.Evidence, "_atomic_json", interposed_atomic_json)
    try:
        with pytest.raises(ValueError, match="authority-sealed"):
            evidence.finish_pass()
        summary = json.loads((evidence.directory / "summary.json").read_text(encoding="utf-8"))
        assert summary["status"] == "FAIL"
        assert summary["state"] == soak.RunState.FAIL.value
        assert evidence.state is soak.RunState.FAIL
    finally:
        evidence.close()


def test_join_requires_ack_file_process_state_destination_and_health_cut(tmp_path: Path) -> None:
    joined, record, delivery, terminal, photo, observation = _joined_cut(tmp_path, serial=1, slot_end=7_200)
    assert joined.receipt_id == "g1:s1"
    assert joined.assistant == runner._ProcessIdentity(201, "start-1")

    attacks: list[
        tuple[
            dict[str, object],
            dict[str, object],
            dict[str, object],
            bytes,
            runner._AssistantProcessObservation,
        ]
    ] = []
    wrong_ledger = copy.deepcopy(record)
    wrong_ledger["owner_token"] = "f" * 32
    attacks.append((wrong_ledger, delivery, terminal, photo, observation))
    wrong_terminal = copy.deepcopy(terminal)
    wrong_terminal["last_terminal"]["receipt"]["receipt_id"] = "g9:s9"  # type: ignore[index]
    attacks.append((record, delivery, wrong_terminal, photo, observation))
    attacks.append((record, delivery, terminal, photo + b"x", observation))
    wrong_process = runner._AssistantProcessObservation(runner._ProcessIdentity(201, "reused"), 100, "assistant", True)
    attacks.append((record, delivery, terminal, photo, wrong_process))
    unresolved = copy.deepcopy(terminal)
    unresolved["unresolved_delivery"] = {
        "slot_id": record["slot_id"],
    }
    attacks.append((record, delivery, unresolved, photo, observation))
    stale_health = copy.deepcopy(terminal)
    stale_health["health"]["updated_at"] = stale_health["last_terminal"]["finished_at"] - 1  # type: ignore[index]
    attacks.append((record, delivery, stale_health, photo, observation))
    degraded_health = copy.deepcopy(terminal)
    degraded_health["health"] = {
        "status": "degraded_projection",
        "error_code": "periodic_projection_incomplete",
        "error_text": "periodic projection evidence is incomplete",
        "updated_at": degraded_health["updated_at"],
    }
    attacks.append((record, delivery, degraded_health, photo, observation))
    reversed_cuts = copy.deepcopy(delivery)
    reversed_cuts["updated_at"] = terminal["last_terminal"]["finished_at"] + 1  # type: ignore[index]
    attacks.append((record, reversed_cuts, terminal, photo, observation))

    for candidate_record, candidate_delivery, candidate_terminal, candidate_photo, candidate_observation in attacks:
        with pytest.raises(runner._RunnerFoundationError):
            runner._validate_joined_receipt(
                ledger_record=candidate_record,
                delivery_state_payload=candidate_delivery,
                terminal_state_payload=candidate_terminal,
                artifact_bytes=candidate_photo,
                assistant_observation=candidate_observation,
                expected_launcher_pid=100,
            )


def test_pre_post_requires_exact_two_new_generation_owner_slot_and_process(tmp_path: Path) -> None:
    kwargs = _pre_post_kwargs(tmp_path)
    proof = runner._validate_pre_post_receipts(**kwargs)
    assert proof.pre_fault.receipt_id == "g1:s1"
    assert proof.post_fault.receipt_id == "g2:s1"

    with pytest.raises(runner._RunnerFoundationError, match="exactly two"):
        runner._validate_pre_post_receipts(**{**kwargs, "ledger_records": (kwargs["pre_ledger_record"],)})
    with pytest.raises(runner._RunnerFoundationError, match="duplicate"):
        runner._validate_pre_post_receipts(
            **{
                **kwargs,
                "ledger_records": (kwargs["pre_ledger_record"], kwargs["pre_ledger_record"]),
            }
        )
    with pytest.raises(runner._RunnerFoundationError):
        runner._validate_pre_post_receipts(
            **{
                **kwargs,
                "post_assistant_observation": kwargs["pre_assistant_observation"],
            }
        )


def test_pre_post_rejects_a_valid_but_changed_capability_nonce_and_destination(tmp_path: Path) -> None:
    kwargs = _pre_post_kwargs(tmp_path)
    _joined, record, delivery, terminal, photo, observation = _joined_cut(
        tmp_path,
        serial=2,
        slot_end=7_260,
        nonce="b" * 64,
    )
    with pytest.raises(runner._RunnerFoundationError, match="retained local capability"):
        runner._validate_pre_post_receipts(
            **{
                **kwargs,
                "post_ledger_record": record,
                "post_delivery_state_payload": delivery,
                "post_terminal_state_payload": terminal,
                "post_artifact_bytes": photo,
                "post_assistant_observation": observation,
                "ledger_records": (kwargs["pre_ledger_record"], record),
            }
        )


def test_pre_post_rejects_skipped_periodic_slot(tmp_path: Path) -> None:
    kwargs = _pre_post_kwargs(tmp_path)
    _joined, record, delivery, terminal, photo, observation = _joined_cut(
        tmp_path,
        serial=2,
        slot_end=7_320,
        nonce="a" * 64,
    )

    with pytest.raises(runner._RunnerFoundationError, match="adjacent slots"):
        runner._validate_pre_post_receipts(
            **{
                **kwargs,
                "post_ledger_record": record,
                "post_delivery_state_payload": delivery,
                "post_terminal_state_payload": terminal,
                "post_artifact_bytes": photo,
                "post_assistant_observation": observation,
                "ledger_records": (kwargs["pre_ledger_record"], record),
            }
        )


def test_fabricated_joined_carriers_cannot_enter_pre_post_gate(tmp_path: Path) -> None:
    kwargs = _pre_post_kwargs(tmp_path)
    valid = runner._validate_pre_post_receipts(**kwargs)
    fabricated = runner._JoinedReceiptEvidence(
        assistant=runner._ProcessIdentity(9_001, "fabricated"),
        assistant_generation=valid.pre_fault.assistant_generation,
        sequence=valid.pre_fault.sequence,
        slot_id="sha256:" + "f" * 64,
        generation_id="f" * 32,
        owner_token="e" * 32,
        artifact_sha256="sha256:" + "d" * 64,
        receipt_id=valid.pre_fault.receipt_id,
        acknowledgement_sha256=valid.pre_fault.acknowledgement_sha256,
        ledger_record_sha256=valid.pre_fault.ledger_record_sha256,
        destination_fingerprint="sha256:" + "c" * 64,
        state_updated_at=valid.pre_fault.state_updated_at,
        health_updated_at=valid.pre_fault.health_updated_at,
    )
    with pytest.raises(TypeError, match="unexpected keyword"):
        runner._validate_pre_post_receipts(  # type: ignore[call-arg]
            **kwargs,
            pre_fault=fabricated,
            post_fault=valid.post_fault,
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows activation refusal")
def test_joined_receipts_cannot_bypass_the_activation_platform_gate(tmp_path: Path) -> None:
    runner._validate_pre_post_receipts(**_pre_post_kwargs(tmp_path))
    with pytest.raises(runner._RunnerActivationDisabled):
        runner._PosixSoakRunner().run(None)


def test_forged_prepost_cannot_mint_delivery_pass(tmp_path: Path) -> None:
    valid = runner._validate_pre_post_receipts(**_pre_post_kwargs(tmp_path))
    forged = runner._PrePostReceiptEvidence(valid.pre_fault, valid.post_fault)
    assert forged.pre_fault == valid.pre_fault
    assert forged.post_fault == valid.post_fault
    assert not hasattr(runner, "_publish_periodic_delivery_result")
    assert not hasattr(runner, "_validate_and_publish_periodic_delivery_result")
    assert not hasattr(runner._DELIVERY_EVIDENCE, "validate_and_issue")
    assert not hasattr(runner._DELIVERY_EVIDENCE, "_register_from_runner")
    assert not hasattr(runner._DELIVERY_EVIDENCE, "_begin_runner")
    assert not hasattr(runner._DELIVERY_EVIDENCE, "_complete_runner")
    assert not hasattr(runner._DELIVERY_EVIDENCE, "_abandon_runner")


def test_caller_cannot_mint_without_triggering_owned_execution(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    persisted = tmp_path / "periodic-delivery-result.json"

    class EvidenceProbe:
        def _accept_periodic_delivery_result(self, authority: object) -> None:
            persisted.write_text('{"status":"PASS"}', encoding="utf-8")

    evidence = EvidenceProbe()
    forged_authority = object.__new__(runner._DeliveryEvidenceAuthority)
    owner = runner._PosixSoakRunner()
    owner._used = True
    for candidate_evidence in (evidence, object()):
        with pytest.raises(runner._RunnerFoundationError, match="unregistered"):
            runner._consume_periodic_delivery_authority(forged_authority, candidate_evidence)
    with pytest.raises(runner._RunnerFoundationError, match="unregistered"):
        runner._consume_periodic_delivery_authority(forged_authority, evidence)
    assert tuple(inspect.signature(runner._DELIVERY_EVIDENCE.run).parameters) == ("runner", "evidence")
    with pytest.raises(TypeError, match="unexpected keyword"):
        runner._DELIVERY_EVIDENCE.run(  # type: ignore[call-arg]
            owner,
            evidence,
            result=runner._validate_pre_post_receipts(**_pre_post_kwargs(tmp_path)),
        )
    executions: list[object] = []

    def execution_harness(self: object, candidate: object) -> runner._OwnedRunResult:
        executions.extend((self, candidate))
        raise RuntimeError("owned execution reached")

    monkeypatch.setattr(runner._PosixSoakRunner, "_run_owned", execution_harness)
    with pytest.raises(RuntimeError, match="owned execution reached"):
        runner._DELIVERY_EVIDENCE.run(owner, evidence)
    assert executions == [owner, evidence]
    assert not persisted.exists()


def test_integrated_owner_private_execution_harness_issues_one_exact_evidence_bound_terminal_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    accepted: list[dict[str, object]] = []

    class EvidenceProbe:
        def _accept_periodic_delivery_result(self, authority: object) -> None:
            accepted.append(runner._consume_periodic_delivery_authority(authority, self))

    evidence = EvidenceProbe()
    owner = runner._PosixSoakRunner()
    owner._used = True
    kwargs = _pre_post_kwargs(tmp_path)
    result_kwargs = dict(kwargs)
    result_kwargs["report_interval_s"] = result_kwargs.pop("expected_interval_s")
    executions: list[tuple[object, object]] = []
    finalizations: list[tuple[object, object, object]] = []

    class Collector:
        observations: tuple[object, ...] = ()

    private_result = runner._OwnedRunResult(
        **result_kwargs,
        observations=(),
        survivors=(),
        graceful=True,
        shutdown_elapsed=0.1,
        collector=Collector(),  # type: ignore[arg-type]
    )

    def execution_harness(self: object, candidate: object) -> runner._OwnedRunResult:
        executions.append((self, candidate))
        return private_result

    def finish_harness(self: object, candidate: object, result: object) -> None:
        finalizations.append((self, candidate, result))

    monkeypatch.setattr(runner._PosixSoakRunner, "_run_owned", execution_harness)
    monkeypatch.setattr(runner._PosixSoakRunner, "_finish_owned", finish_harness)
    runner._DELIVERY_EVIDENCE.run(owner, evidence)
    assert len(accepted) == 1
    assert executions == [(owner, evidence)]
    assert finalizations == [(owner, evidence, private_result)]
    assert accepted[0]["status"] == "PASS"
    assert accepted[0]["pre_fault"]["receipt_id"] == "g1:s1"  # type: ignore[index]
    assert accepted[0]["post_fault"]["receipt_id"] == "g2:s1"  # type: ignore[index]
