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

from cryodaq.agents.assistant.periodic_delivery import PeriodicDeliveryContext
from cryodaq.agents.assistant.periodic_png import PeriodicPngCoordinator
from cryodaq.agents.assistant.soak_periodic_delivery import SoakPeriodicDeliverySession
from cryodaq.periodic_state import (
    PeriodicArtifact,
    PeriodicStatus,
    allocate_pending,
    latest_completed_slot,
    load_periodic_state,
    mark_ready,
    mark_rendering,
    periodic_local_destination_fingerprint,
    write_periodic_state,
)
from cryodaq.report_process import read_periodic_artifact_bytes
from scripts.soak_mock_stack_runner import (
    _ArtifactReceiptSink,
    _AssistantProcessObservation,
    _ProcessIdentity,
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


def _observe_receipt_fsyncs(
    sink: _ArtifactReceiptSink,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_at: int | None = None,
) -> list[str]:
    real_open = os.open
    real_fsync = os.fsync
    opened: dict[int, str] = {}
    events: list[str] = []

    def tracked_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        name = os.fsdecode(path)
        if name == "periodic-receipts.jsonl":
            opened[fd] = "ledger"
        elif name.startswith(".periodic-g") and name.endswith(".tmp"):
            opened[fd] = "artifact"
        return fd

    def tracked_fsync(fd: int) -> None:
        event = "directory" if fd == sink._dir_fd else opened.get(fd)
        if event is not None:
            events.append(event)
            if fail_at == len(events):
                raise OSError(f"injected {event} fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "fsync", tracked_fsync)
    return events


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


@pytest.mark.skipif(os.name != "posix", reason="AF_UNIX durability proof is POSIX-only")
@pytest.mark.parametrize(
    "failure_at,expected_events",
    [
        (1, ["artifact"]),
        (2, ["artifact", "directory"]),
        (3, ["artifact", "directory", "ledger"]),
        (4, ["artifact", "directory", "ledger", "directory"]),
    ],
)
def test_receipt_fsync_failure_prevents_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_at: int,
    expected_events: list[str],
) -> None:
    os.chmod(tmp_path, 0o700)
    parent, child = socket.socketpair()
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    process = context.Process(target=_spawn_sender, args=(child, output))
    process.start()
    child.close()
    sink = _ArtifactReceiptSink(parent, nonce="e" * 64, evidence_dir=tmp_path)
    events = _observe_receipt_fsyncs(sink, monkeypatch, fail_at=failure_at)
    ack_calls: list[bytes] = []

    def observe_ack(_sink: _ArtifactReceiptSink, ack: bytes, *, deadline: float) -> None:
        assert deadline > 0
        ack_calls.append(ack)

    monkeypatch.setattr(_ArtifactReceiptSink, "_write_all", observe_ack)
    with pytest.raises(OSError, match=rf"injected {expected_events[-1]} fsync failure"):
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
    process.join(timeout=15)
    if process.is_alive():
        process.kill()
        process.join(timeout=15)
    assert process.exitcode == 0
    assert output.get(timeout=2) == ("unknown", None)
    assert events == expected_events
    assert ack_calls == []


@pytest.mark.skipif(os.name != "posix", reason="AF_UNIX spawn and SIGKILL proof is POSIX-only")
@pytest.mark.parametrize("iteration", range(3))
def test_durable_receipt_before_ack_survives_unknown_sender_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    iteration: int,
) -> None:
    nonce = f"{iteration + 1:064x}"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir(mode=0o700)
    os.chmod(evidence_dir, 0o700)
    data_dir = tmp_path / "data"
    active, photo, caption = _prepare_ready_local_delivery(data_dir, nonce)
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
    durability_events: list[str]

    def disconnect_after_durable_persist(
        sink: _ArtifactReceiptSink,
        _ack: bytes,
        *,
        deadline: float,
    ) -> None:
        assert deadline > 0
        assert durability_events == ["artifact", "directory", "ledger", "directory"]
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
    durability_events = _observe_receipt_fsyncs(sink, monkeypatch)
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

    ledger_path = evidence_dir / "periodic-receipts.jsonl"
    records = [json.loads(line) for line in ledger_path.read_text(encoding="ascii").splitlines()]
    assert len(records) == 1
    record = records[0]
    persisted_photo = (evidence_dir / str(record["filename"])).read_bytes()
    delivery_active = delivery_cuts[0]["active"]
    recovered_state = load_periodic_state(data_dir).payload
    assert sum(value is not None for value in (recovered_state["active"], recovered_state["last_terminal"])) == 1
    unknown = recovered_state["last_terminal"] or recovered_state["active"]
    unresolved = recovered_state["unresolved_delivery"]

    assert _ArtifactReceiptSink._valid_ledger_record(record)
    assert isinstance(delivery_active, dict)
    artifact = delivery_active["artifact"]
    assert isinstance(artifact, dict)
    assert isinstance(unknown, dict)
    assert unknown["status"] == "DELIVERY_UNKNOWN"
    assert unknown["receipt"] is None
    assert len(unresolved) == 1
    unresolved_entry = unresolved[0]
    assert isinstance(unresolved_entry, dict)

    assert persisted_photo == photo
    assert record["artifact_sha256"] == "sha256:" + hashlib.sha256(persisted_photo).hexdigest()
    assert record["artifact_size"] == len(persisted_photo)
    caption_bytes = caption.encode("utf-8")
    assert record["caption_sha256"] == "sha256:" + hashlib.sha256(caption_bytes).hexdigest()
    assert record["caption_size"] == len(caption_bytes)
    destination_fingerprint = periodic_local_destination_fingerprint(str(record["nonce"]))
    assert (
        record["assistant_pid"],
        record["assistant_start_identity"],
        record["assistant_generation"],
        record["sequence"],
        record["receipt_id"],
        record["nonce"],
    ) == (observation.identity.pid, observation.identity.start_identity, 1, 1, "g1:s1", nonce)

    assert {
        "slot_id": record["slot_id"],
        "generation_id": record["generation_id"],
        "owner_token": record["owner_token"],
        "artifact_sha256": record["artifact_sha256"],
        "artifact_size": record["artifact_size"],
    } == {
        "slot_id": delivery_active["slot_id"],
        "generation_id": delivery_active["generation_id"],
        "owner_token": delivery_active["owner_token"],
        "artifact_sha256": artifact["sha256"],
        "artifact_size": artifact["size"],
    }
    assert {
        "slot_id": record["slot_id"],
        "generation_id": record["generation_id"],
        "artifact_sha256": record["artifact_sha256"],
        "destination_fingerprint": destination_fingerprint,
    } == {
        "slot_id": unresolved_entry["slot_id"],
        "generation_id": unresolved_entry["generation_id"],
        "artifact_sha256": unresolved_entry["artifact_sha256"],
        "destination_fingerprint": unresolved_entry["destination_fingerprint"],
    }
    assert delivery_active["destination_fingerprint"] == destination_fingerprint
