from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
import socket
import struct
import threading
import zlib
from pathlib import Path
from typing import Any

import pytest

from cryodaq.agents.assistant.periodic_delivery import (
    PeriodicDeliveryContext,
    PeriodicDeliveryReceipt,
)
from cryodaq.agents.assistant.periodic_png import PeriodicPngCoordinator
from cryodaq.agents.assistant.soak_periodic_delivery import SoakPeriodicDeliverySession
from cryodaq.periodic_state import (
    PeriodicArtifact,
    PeriodicStateDocument,
    PeriodicStatus,
    allocate_pending,
    latest_completed_slot,
    load_periodic_state,
    mark_ready,
    mark_rendering,
    mark_succeeded,
    periodic_local_destination_fingerprint,
    rotate_terminal_active,
    set_periodic_health,
    write_periodic_state,
)
from cryodaq.report_process import read_periodic_artifact_bytes
from scripts.soak_mock_stack_runner import (
    _ArtifactReceiptSink,
    _AssistantProcessObservation,
    _ProcessIdentity,
    _validate_joined_receipt,
)
from tests.agents.assistant.test_periodic_png_coordinator import (
    Alarm,
    Archive,
    Clock,
    Live,
    _config,
)
from tests.integration.test_periodic_png_crash_recovery import (
    CountingRunner,
    _inline,
)


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _photo() -> bytes:
    ihdr = struct.pack(">IIBBBBB", 100, 100, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", b"data") + _chunk(b"IEND", b"")


def _spawn_sender(endpoint: socket.socket, output: Any) -> None:
    async def send() -> None:
        photo = _photo()
        caption = "Сводка"
        session = SoakPeriodicDeliverySession(endpoint, "e" * 64, 1, os.getpid())
        lease = session.lease()
        context = PeriodicDeliveryContext(
            "sha256:" + "a" * 64,
            "b" * 32,
            "c" * 32,
            "sha256:" + hashlib.sha256(photo).hexdigest(),
            len(photo),
            "sha256:" + hashlib.sha256(caption.encode()).hexdigest(),
            len(caption.encode()),
        )
        result = await lease.send_artifact(photo, caption, context)
        output.put((result.outcome.value, result.receipt.receipt_id if result.receipt else None))
        await session.close()

    asyncio.run(send())


def _prepare_ready_local_delivery(data_dir: Path, nonce: str) -> tuple[dict[str, object], bytes, str]:
    photo = _photo()
    caption = "Summary"
    config = _config()
    slot = latest_completed_slot(121.0, config.interval_s)
    state = allocate_pending(
        load_periodic_state(data_dir),
        slot,
        config,
        generation_id="b" * 32,
        owner_token="c" * 32,
        display_time="01.01.1970 00:02",
        now=121.0,
        destination_fingerprint=periodic_local_destination_fingerprint(nonce),
    )
    write_periodic_state(data_dir, state)
    state = mark_rendering(state, slot_id=slot.slot_id, owner_token="c" * 32, now=122.0)
    write_periodic_state(
        data_dir,
        state,
        expected_slot_id=slot.slot_id,
        expected_owner_token="c" * 32,
        expected_status=PeriodicStatus.PENDING,
    )
    generation_dir = data_dir / "reporting" / "periodic" / "generations" / ("b" * 32)
    generation_dir.mkdir(parents=True)
    artifact_path = generation_dir / "periodic.png"
    artifact_path.write_bytes(photo)
    artifact = PeriodicArtifact(
        path=f"periodic/generations/{'b' * 32}/periodic.png",
        sha256="sha256:" + hashlib.sha256(photo).hexdigest(),
        size=len(photo),
        width=100,
        height=100,
        mime="image/png",
    )
    state = mark_ready(
        state,
        artifact,
        caption,
        slot_id=slot.slot_id,
        owner_token="c" * 32,
        now=123.0,
    )
    write_periodic_state(
        data_dir,
        state,
        expected_slot_id=slot.slot_id,
        expected_owner_token="c" * 32,
        expected_status=PeriodicStatus.RENDERING,
    )
    active = state.payload["active"]
    assert isinstance(active, dict)
    return dict(active), photo, caption


def _spawn_coordinator(
    endpoint: socket.socket,
    data_dir: Path,
    nonce: str,
    assistant_generation: int,
    output: Any,
    hold_after_delivery: bool,
) -> None:
    async def run() -> None:
        session = SoakPeriodicDeliverySession(endpoint, nonce, assistant_generation, os.getpid())
        lease = session.lease()

        class ObservedDelivery:
            def __init__(self) -> None:
                self.calls = 0

            async def send_artifact(
                self,
                photo: bytes,
                caption: str,
                context: PeriodicDeliveryContext,
            ) -> Any:
                self.calls += 1
                result = await lease.send_artifact(photo, caption, context)
                output.put(("delivery", result.outcome.value, result.receipt is not None))
                if hold_after_delivery:
                    await asyncio.Event().wait()
                return result

            async def close(self) -> None:
                await lease.close()

        delivery = ObservedDelivery()
        coordinator = PeriodicPngCoordinator(
            data_dir=data_dir,
            config=_config(),
            live_sources=Live(),
            alarm_query=Alarm(),
            archive_query=Archive(),
            runner=CountingRunner(data_dir),
            delivery=delivery,
            destination_fingerprint=periodic_local_destination_fingerprint(nonce),
            expected_delivery_kind="soak_local",
            artifact_reader=read_periodic_artifact_bytes,
            clock=Clock(124.0),
            generation_factory=lambda: "d" * 32,
            owner_factory=lambda: "f" * 32,
            run_blocking=_inline,
        )
        try:
            await coordinator.start()
            await coordinator.reconcile_once()
            state = load_periodic_state(data_dir).payload
            terminal = state["last_terminal"] or state["active"]
            output.put(
                (
                    "complete",
                    delivery.calls,
                    None if not isinstance(terminal, dict) else terminal["status"],
                    len(state["unresolved_delivery"]),
                )
            )
        finally:
            await coordinator.stop()
            await session.close()

    asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="AF_UNIX spawn proof is POSIX-only")
def test_real_spawn_process_delivers_one_durable_ack(tmp_path: Path) -> None:
    os.chmod(tmp_path, 0o700)
    parent, child = socket.socketpair()
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    process = context.Process(target=_spawn_sender, args=(child, output))
    process.start()
    child.close()
    sink = _ArtifactReceiptSink(parent, nonce="e" * 64, evidence_dir=tmp_path)
    observed: list[dict[str, object]] = []
    thread = threading.Thread(
        target=lambda: observed.append(
            sink.accept_one(
                assistant_observation=_AssistantProcessObservation(
                    _ProcessIdentity(process.pid, "spawn-observed-start"),
                    os.getpid(),
                    "assistant",
                    True,
                ),
                expected_launcher_pid=os.getpid(),
                expected_assistant_generation=1,
                expected_slot_id="sha256:" + "a" * 64,
                expected_generation_id="b" * 32,
                expected_owner_token="c" * 32,
                expected_artifact_sha256="sha256:" + hashlib.sha256(_photo()).hexdigest(),
            )
        ),
        daemon=True,
    )
    thread.start()
    process.join(timeout=15)
    thread.join(timeout=15)
    assert process.exitcode == 0
    assert output.get(timeout=2) == ("accepted", "g1:s1")
    assert observed[0]["assistant_pid"] == process.pid
    sink.close()


@pytest.mark.skipif(os.name != "posix", reason="AF_UNIX spawn and SIGKILL proof is POSIX-only")
def test_durable_receipt_before_ack_survives_unknown_sender_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nonce = "e" * 64
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(mode=0o700)
    os.chmod(evidence_dir, 0o700)
    data_dir = tmp_path / "data"
    active, photo, _caption = _prepare_ready_local_delivery(data_dir, nonce)
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    process = context.Process(
        target=_spawn_coordinator,
        args=(child, data_dir, nonce, 1, output, True),
    )
    process.start()
    child.close()
    observation = _AssistantProcessObservation(
        _ProcessIdentity(process.pid, "spawn-observed-start"),
        os.getpid(),
        "assistant",
        True,
    )
    delivery_cuts: list[dict[str, object]] = []

    def disconnect_after_durable_persist(
        sink: _ArtifactReceiptSink,
        _ack: bytes,
        *,
        deadline: float,
    ) -> None:
        assert deadline > 0
        ledger_path = evidence_dir / "periodic-receipts.jsonl"
        records = [json.loads(line) for line in ledger_path.read_text(encoding="ascii").splitlines()]
        assert len(records) == 1
        assert _ArtifactReceiptSink._valid_ledger_record(records[0])
        assert (evidence_dir / str(records[0]["filename"])).read_bytes() == photo
        state = load_periodic_state(data_dir).payload
        assert isinstance(state["active"], dict)
        assert state["active"]["status"] == "DELIVERING"
        delivery_cuts.append(dict(state))
        sink.close()
        raise ConnectionAbortedError("deterministic disconnect after durable receipt and before ACK")

    monkeypatch.setattr(_ArtifactReceiptSink, "_write_all", disconnect_after_durable_persist)
    sink = _ArtifactReceiptSink(parent, nonce=nonce, evidence_dir=evidence_dir)
    try:
        with pytest.raises(ConnectionAbortedError, match="after durable receipt and before ACK"):
            sink.accept_one(
                assistant_observation=observation,
                expected_launcher_pid=os.getpid(),
                expected_assistant_generation=1,
                expected_slot_id=str(active["slot_id"]),
                expected_generation_id=str(active["generation_id"]),
                expected_owner_token=str(active["owner_token"]),
                expected_artifact_sha256="sha256:" + hashlib.sha256(photo).hexdigest(),
            )
        assert output.get(timeout=10) == ("delivery", "unknown", False)
    finally:
        if process.is_alive():
            process.kill()
        process.join(timeout=15)
    assert process.exitcode is not None and process.exitcode < 0

    killed_state = load_periodic_state(data_dir).payload
    assert isinstance(killed_state["active"], dict)
    assert killed_state["active"]["status"] == "DELIVERING"
    assert len(delivery_cuts) == 1

    replacement_parent, replacement_child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    replacement_output = context.Queue()
    replacement = context.Process(
        target=_spawn_coordinator,
        args=(replacement_child, data_dir, nonce, 2, replacement_output, False),
    )
    replacement.start()
    replacement_child.close()
    try:
        replacement.join(timeout=15)
        assert replacement.exitcode == 0
        assert replacement_output.get(timeout=2) == ("complete", 0, "DELIVERY_UNKNOWN", 1)
        replacement_parent.settimeout(1.0)
        assert replacement_parent.recv(1) == b""
    finally:
        if replacement.is_alive():
            replacement.kill()
        replacement.join(timeout=15)
        replacement_parent.close()

    record = json.loads((evidence_dir / "periodic-receipts.jsonl").read_text(encoding="ascii"))
    receipt = PeriodicDeliveryReceipt(
        "soak_local",
        str(record["receipt_id"]),
        str(record["acknowledgement_sha256"]),
    )
    delivery_state = PeriodicStateDocument(delivery_cuts[0])
    succeeded = mark_succeeded(
        delivery_state,
        receipt=receipt,
        slot_id=str(record["slot_id"]),
        owner_token=str(record["owner_token"]),
        now=float(delivery_state.payload["updated_at"]) + 1,
    )
    terminal = rotate_terminal_active(succeeded, now=float(succeeded.payload["updated_at"]) + 1)
    terminal = set_periodic_health(
        terminal,
        status="ready",
        code=None,
        text="",
        now=float(terminal.payload["updated_at"]) + 1,
    )
    joined = _validate_joined_receipt(
        ledger_record=record,
        delivery_state_payload=delivery_cuts[0],
        terminal_state_payload=terminal.payload,
        artifact_bytes=(evidence_dir / str(record["filename"])).read_bytes(),
        assistant_observation=observation,
        expected_launcher_pid=os.getpid(),
    )
    assert joined.receipt_id == record["receipt_id"]
    assert joined.acknowledgement_sha256 == record["acknowledgement_sha256"]
