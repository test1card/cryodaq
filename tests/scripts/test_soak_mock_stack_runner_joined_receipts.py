from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

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
    set_periodic_health,
)
from scripts import soak_mock_stack_runner as runner


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
    photo = (b"png" + bytes([serial])) * 20
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
    state = set_periodic_health(state, status="ready", code=None, text="", now=float(slot_end + 6))
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
        state_payload=state.payload,
        artifact_bytes=photo,
        assistant_observation=observation,
        expected_launcher_pid=100,
    )
    return joined, record, state.payload, photo, observation


def _pre_post_kwargs(tmp_path: Path) -> dict[str, object]:
    shared_nonce = "a" * 64
    _pre_joined, pre_record, pre_state, pre_photo, pre_observation = _joined_cut(
        tmp_path, serial=1, slot_end=7_200, nonce=shared_nonce
    )
    _post_joined, post_record, post_state, post_photo, post_observation = _joined_cut(
        tmp_path, serial=2, slot_end=7_260, nonce=shared_nonce
    )
    return {
        "pre_ledger_record": pre_record,
        "pre_state_payload": pre_state,
        "pre_artifact_bytes": pre_photo,
        "pre_assistant_observation": pre_observation,
        "post_ledger_record": post_record,
        "post_state_payload": post_state,
        "post_artifact_bytes": post_photo,
        "post_assistant_observation": post_observation,
        "expected_launcher_pid": 100,
        "ledger_records": (pre_record, post_record),
    }


def test_join_requires_ack_file_process_state_destination_and_health_cut(tmp_path: Path) -> None:
    joined, record, state, photo, observation = _joined_cut(tmp_path, serial=1, slot_end=7_200)
    assert joined.receipt_id == "g1:s1"
    assert joined.assistant == runner._ProcessIdentity(201, "start-1")

    attacks: list[tuple[dict[str, object], dict[str, object], bytes, runner._AssistantProcessObservation]] = []
    wrong_ledger = copy.deepcopy(record)
    wrong_ledger["owner_token"] = "f" * 32
    attacks.append((wrong_ledger, state, photo, observation))
    wrong_state = copy.deepcopy(state)
    wrong_state["active"]["receipt"]["receipt_id"] = "g9:s9"  # type: ignore[index]
    attacks.append((record, wrong_state, photo, observation))
    attacks.append((record, state, photo + b"x", observation))
    wrong_process = runner._AssistantProcessObservation(runner._ProcessIdentity(201, "reused"), 100, "assistant", True)
    attacks.append((record, state, photo, wrong_process))
    unresolved = copy.deepcopy(state)
    unresolved["unresolved_delivery"] = {
        "slot_id": record["slot_id"],
    }
    attacks.append((record, unresolved, photo, observation))
    stale_health = copy.deepcopy(state)
    stale_health["health"]["updated_at"] = stale_health["active"]["finished_at"] - 1  # type: ignore[index]
    attacks.append((record, stale_health, photo, observation))
    degraded_health = copy.deepcopy(state)
    degraded_health["health"] = {
        "status": "degraded_projection",
        "error_code": "periodic_projection_incomplete",
        "error_text": "periodic projection evidence is incomplete",
        "updated_at": degraded_health["updated_at"],
    }
    attacks.append((record, degraded_health, photo, observation))

    for candidate_record, candidate_state, candidate_photo, candidate_observation in attacks:
        with pytest.raises(runner._RunnerFoundationError):
            runner._validate_joined_receipt(
                ledger_record=candidate_record,
                state_payload=candidate_state,
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
    _joined, record, state, photo, observation = _joined_cut(
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
                "post_state_payload": state,
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


def test_constructed_delivery_bundle_and_fake_evidence_cannot_persist_pass(tmp_path: Path) -> None:
    proof = runner._validate_pre_post_receipts(**_pre_post_kwargs(tmp_path))
    persisted = tmp_path / "periodic-delivery-result.json"

    class EvidenceProbe:
        def _accept_periodic_delivery_result(self, authority: object) -> None:
            persisted.write_text('{"status":"PASS"}', encoding="utf-8")

    evidence = EvidenceProbe()
    forged_authority = object.__new__(runner._DeliveryEvidenceAuthority)
    forged_run_authority = object.__new__(runner._IntegratedRunAuthority)
    owner = runner._PosixSoakRunner()
    owner._used = True
    for candidate_evidence in (evidence, object()):
        with pytest.raises(runner._RunnerFoundationError, match="unregistered"):
            runner._consume_periodic_delivery_authority(forged_authority, candidate_evidence)
    with pytest.raises(runner._RunnerFoundationError, match="unregistered"):
        runner._consume_periodic_delivery_authority(forged_authority, evidence)
    with pytest.raises(runner._RunnerFoundationError, match="unregistered"):
        runner._DELIVERY_EVIDENCE._register_from_runner(
            forged_run_authority,
            owner,
            evidence,
            proof,
        )
    assert not persisted.exists()


def test_integrated_owner_issues_one_exact_evidence_bound_terminal_result(tmp_path: Path) -> None:
    proof = runner._validate_pre_post_receipts(**_pre_post_kwargs(tmp_path))
    accepted: list[dict[str, object]] = []

    class EvidenceProbe:
        def _accept_periodic_delivery_result(self, authority: object) -> None:
            accepted.append(runner._consume_periodic_delivery_authority(authority, self))

    evidence = EvidenceProbe()
    owner = runner._PosixSoakRunner()
    owner._used = True
    authority = runner._DELIVERY_EVIDENCE._begin_runner(owner, evidence)
    runner._DELIVERY_EVIDENCE._register_from_runner(authority, owner, evidence, proof)
    assert len(accepted) == 1
    assert accepted[0]["status"] == "PASS"
    assert accepted[0]["pre_fault"]["receipt_id"] == "g1:s1"  # type: ignore[index]
    assert accepted[0]["post_fault"]["receipt_id"] == "g2:s1"  # type: ignore[index]
    with pytest.raises(runner._RunnerFoundationError, match="spent"):
        runner._DELIVERY_EVIDENCE._register_from_runner(authority, owner, evidence, proof)
