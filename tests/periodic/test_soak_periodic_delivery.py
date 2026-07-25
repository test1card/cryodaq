from __future__ import annotations

import asyncio
import glob
import hashlib
import json
import os
import socket
import struct
import threading
import zlib
from pathlib import Path

import pytest

from cryodaq.agents.assistant.periodic_delivery import (
    MAX_PERIODIC_ARTIFACT_BYTES,
    PeriodicDeliveryContext,
    PeriodicDeliveryOutcome,
)
from cryodaq.agents.assistant.soak_periodic_delivery import (
    SoakPeriodicDeliverySession,
    SoakPeriodicProtocolError,
    build_ack,
    decode_frame_body,
)
from scripts.soak_mock_stack_runner import (
    _ArtifactReceiptSink,
    _AssistantProcessObservation,
    _ProcessIdentity,
    _RunnerFoundationError,
)

_POSIX_ARTIFACT_CAPABILITY = pytest.mark.skipif(os.name != "posix", reason="artifact delivery capability is POSIX-only")


def _observation(pid: int, *, parent_pid: int = 42) -> _AssistantProcessObservation:
    return _AssistantProcessObservation(_ProcessIdentity(pid, f"start-{pid}"), parent_pid, "assistant", True)


def _accept(pid: int, photo: bytes, *, parent_pid: int = 42) -> dict[str, object]:
    return {
        "assistant_observation": _observation(pid, parent_pid=parent_pid),
        "expected_launcher_pid": parent_pid,
        "expected_assistant_generation": 1,
        "expected_slot_id": "sha256:" + "a" * 64,
        "expected_generation_id": "b" * 32,
        "expected_owner_token": "c" * 32,
        "expected_artifact_sha256": "sha256:" + hashlib.sha256(photo).hexdigest(),
    }


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)


def _png(size: int | None = None) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 100, 100, 8, 2, 0, 0, 0)
    fixed = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IEND", b"")
    payload_size = 4 if size is None else size - len(fixed) - 12
    assert payload_size >= 0
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", b"x" * payload_size) + _chunk(b"IEND", b"")


def _context(photo: bytes, caption: str = "Сводка") -> PeriodicDeliveryContext:
    caption_raw = caption.encode()
    return PeriodicDeliveryContext(
        "sha256:" + "a" * 64,
        "b" * 32,
        "c" * 32,
        "sha256:" + hashlib.sha256(photo).hexdigest(),
        len(photo),
        "sha256:" + hashlib.sha256(caption_raw).hexdigest(),
        len(caption_raw),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [None, MAX_PERIODIC_ARTIFACT_BYTES])
@_POSIX_ARTIFACT_CAPABILITY
async def test_minimum_and_maximum_artifact_round_trip_via_durable_sink(tmp_path: Path, size: int | None) -> None:
    os.chmod(tmp_path, 0o700)
    client, runner = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    session = SoakPeriodicDeliverySession(client, "d" * 64, 1, 1234)
    lease = session.lease()
    sink = _ArtifactReceiptSink(runner, nonce="d" * 64, evidence_dir=tmp_path)
    photo = _png(size)
    result_holder: list[object] = []

    thread = threading.Thread(
        target=lambda: result_holder.append(sink.accept_one(**_accept(1234, photo))),
        daemon=True,
    )
    thread.start()
    result = await lease.send_artifact(photo, "Сводка", _context(photo))
    thread.join(timeout=10)
    assert result.outcome is PeriodicDeliveryOutcome.ACCEPTED
    assert result.receipt is not None and result.receipt.receipt_id == "g1:s1"
    assert len(glob.glob(str(tmp_path / "periodic-g1-s1-*.png"))) == 1
    assert await asyncio.to_thread(os.path.isfile, tmp_path / "periodic-receipts.jsonl")
    ledger = json.loads(await asyncio.to_thread((tmp_path / "periodic-receipts.jsonl").read_text))
    assert ledger["receipt_id"] == "g1:s1"
    assert ledger["acknowledgement_sha256"] == result.receipt.acknowledgement_sha256
    await lease.close()
    await session.close()
    sink.close()


@pytest.mark.asyncio
@_POSIX_ARTIFACT_CAPABILITY
async def test_invalid_payload_is_not_sent_and_does_not_consume_sequence() -> None:
    client, runner = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    session = SoakPeriodicDeliverySession(client, "d" * 64, 1, 1234)
    lease = session.lease()
    photo = _png()
    invalid = await lease.send_artifact(photo + b"x", "Сводка", _context(photo))
    assert invalid.outcome is PeriodicDeliveryOutcome.NOT_SENT
    runner.setblocking(False)
    with pytest.raises(BlockingIOError):
        runner.recv(1)
    assert session._sequence == 0
    await session.close()
    runner.close()


def test_decoder_rejects_truncation_and_one_byte_oversize() -> None:
    from cryodaq.agents.assistant.soak_periodic_delivery import _frame, frame_body_limit

    photo = _png()
    framed = _frame(
        nonce="d" * 64,
        assistant_pid=123,
        assistant_generation=2,
        sequence=1,
        photo=photo,
        caption="Сводка",
        context=_context(photo),
    )
    (size,) = struct.unpack("!I", framed[:4])
    body = framed[4:]
    assert size == len(body)
    assert build_ack(decode_frame_body(body))
    with pytest.raises(SoakPeriodicProtocolError):
        decode_frame_body(body[:-1])
    with pytest.raises(SoakPeriodicProtocolError):
        decode_frame_body(b"x" * (frame_body_limit() + 1))


@_POSIX_ARTIFACT_CAPABILITY
def test_runner_rejects_wrong_pid_without_file_or_ack(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.soak_periodic_delivery import _frame

    os.chmod(tmp_path, 0o700)
    client, runner = socket.socketpair()
    photo = _png()
    client.sendall(
        _frame(
            nonce="d" * 64,
            assistant_pid=123,
            assistant_generation=1,
            sequence=1,
            photo=photo,
            caption="Сводка",
            context=_context(photo),
        )
    )
    sink = _ArtifactReceiptSink(runner, nonce="d" * 64, evidence_dir=tmp_path)
    with pytest.raises(_RunnerFoundationError, match="identity/generation/sequence"):
        sink.accept_one(**_accept(999, photo))
    assert not glob.glob(str(tmp_path / "periodic-*.png"))
    assert client.recv(1) == b""
    client.close()


@_POSIX_ARTIFACT_CAPABILITY
def test_runner_rejects_duplicate_generation_sequence_after_one_ack(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.soak_periodic_delivery import _frame

    os.chmod(tmp_path, 0o700)
    client, runner = socket.socketpair()
    photo = _png()
    frame = _frame(
        nonce="d" * 64,
        assistant_pid=123,
        assistant_generation=1,
        sequence=1,
        photo=photo,
        caption="Сводка",
        context=_context(photo),
    )
    sink = _ArtifactReceiptSink(runner, nonce="d" * 64, evidence_dir=tmp_path)
    client.sendall(frame)
    sink.accept_one(**_accept(123, photo))
    ack_size = struct.unpack("!I", client.recv(4))[0]
    assert len(client.recv(ack_size)) == ack_size
    client.sendall(frame)
    with pytest.raises(_RunnerFoundationError, match="identity/generation/sequence"):
        sink.accept_one(**_accept(123, photo))
    assert len(glob.glob(str(tmp_path / "periodic-*.png"))) == 1
    client.close()


@_POSIX_ARTIFACT_CAPABILITY
def test_runner_rejects_wrong_expected_authority(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.soak_periodic_delivery import _frame

    os.chmod(tmp_path, 0o700)
    client, runner = socket.socketpair()
    photo = _png()
    client.sendall(
        _frame(
            nonce="d" * 64,
            assistant_pid=123,
            assistant_generation=1,
            sequence=1,
            photo=photo,
            caption="Сводка",
            context=_context(photo),
        )
    )
    sink = _ArtifactReceiptSink(runner, nonce="d" * 64, evidence_dir=tmp_path)
    expected = _accept(123, photo)
    expected["expected_owner_token"] = "f" * 32
    with pytest.raises(_RunnerFoundationError, match="identity/generation/sequence"):
        sink.accept_one(**expected)
    assert not glob.glob(str(tmp_path / "periodic-*.png"))
    client.close()


@_POSIX_ARTIFACT_CAPABILITY
def test_runner_rejects_first_generation_jump(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.soak_periodic_delivery import _frame

    os.chmod(tmp_path, 0o700)
    client, runner = socket.socketpair()
    photo = _png()
    client.sendall(
        _frame(
            nonce="d" * 64,
            assistant_pid=123,
            assistant_generation=999,
            sequence=1,
            photo=photo,
            caption="Сводка",
            context=_context(photo),
        )
    )
    sink = _ArtifactReceiptSink(runner, nonce="d" * 64, evidence_dir=tmp_path)
    expected = _accept(123, photo)
    expected["expected_assistant_generation"] = 999
    with pytest.raises(_RunnerFoundationError, match="identity/generation/sequence"):
        sink.accept_one(**expected)
    assert not glob.glob(str(tmp_path / "periodic-*.png"))
    client.close()


@_POSIX_ARTIFACT_CAPABILITY
def test_runner_rejects_generation_jump_after_accepted_generation(tmp_path: Path) -> None:
    from cryodaq.agents.assistant.soak_periodic_delivery import _frame

    os.chmod(tmp_path, 0o700)
    client, runner = socket.socketpair()
    photo = _png()
    sink = _ArtifactReceiptSink(runner, nonce="d" * 64, evidence_dir=tmp_path)
    first = _frame(
        nonce="d" * 64,
        assistant_pid=123,
        assistant_generation=1,
        sequence=1,
        photo=photo,
        caption="Сводка",
        context=_context(photo),
    )
    client.sendall(first)
    sink.accept_one(**_accept(123, photo))
    ack_size = struct.unpack("!I", client.recv(4))[0]
    assert len(client.recv(ack_size)) == ack_size

    jumped = _frame(
        nonce="d" * 64,
        assistant_pid=999,
        assistant_generation=999,
        sequence=1,
        photo=photo,
        caption="Сводка",
        context=_context(photo),
    )
    client.sendall(jumped)
    expected = _accept(999, photo)
    expected["expected_assistant_generation"] = 999
    with pytest.raises(_RunnerFoundationError, match="identity/generation/sequence"):
        sink.accept_one(**expected)
    assert len(glob.glob(str(tmp_path / "periodic-*.png"))) == 1
    client.close()


@pytest.mark.parametrize("ledger_kind", ["fifo", "partial", "canonical_but_invalid"])
@_POSIX_ARTIFACT_CAPABILITY
def test_runner_rejects_unsafe_or_corrupt_existing_ledger(tmp_path: Path, ledger_kind: str) -> None:
    from cryodaq.agents.assistant.soak_periodic_delivery import _frame

    os.chmod(tmp_path, 0o700)
    ledger = tmp_path / "periodic-receipts.jsonl"
    if ledger_kind == "fifo":
        os.mkfifo(ledger, 0o600)
    else:
        ledger.write_bytes(b"{" if ledger_kind == "partial" else b"{}\n")
        os.chmod(ledger, 0o600)
    client, runner = socket.socketpair()
    photo = _png()
    client.sendall(
        _frame(
            nonce="d" * 64,
            assistant_pid=123,
            assistant_generation=1,
            sequence=1,
            photo=photo,
            caption="Сводка",
            context=_context(photo),
        )
    )
    sink = _ArtifactReceiptSink(runner, nonce="d" * 64, evidence_dir=tmp_path)
    with pytest.raises(_RunnerFoundationError, match="ledger"):
        sink.accept_one(**_accept(123, photo))
    assert client.recv(1) == b""
    client.close()


@_POSIX_ARTIFACT_CAPABILITY
def test_runner_zero_byte_stall_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import soak_mock_stack_runner as runner_module

    os.chmod(tmp_path, 0o700)
    client, runner = socket.socketpair()
    monkeypatch.setattr(runner_module, "_ARTIFACT_IO_TIMEOUT_S", 0.02)
    sink = _ArtifactReceiptSink(runner, nonce="d" * 64, evidence_dir=tmp_path)
    with pytest.raises(_RunnerFoundationError, match="deadline"):
        sink.accept_one(**_accept(123, _png()))
    assert client.recv(1) == b""
    client.close()


@_POSIX_ARTIFACT_CAPABILITY
def test_runner_ack_backpressure_is_bounded_after_durable_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryodaq.agents.assistant.soak_periodic_delivery import _frame
    from scripts import soak_mock_stack_runner as runner_module

    os.chmod(tmp_path, 0o700)
    client, runner = socket.socketpair()
    runner.setblocking(False)
    filler = b"x" * 64 * 1024
    while True:
        try:
            runner.send(filler)
        except BlockingIOError:
            break
    runner.setblocking(True)
    photo = _png()
    client.sendall(
        _frame(
            nonce="d" * 64,
            assistant_pid=123,
            assistant_generation=1,
            sequence=1,
            photo=photo,
            caption="Сводка",
            context=_context(photo),
        )
    )
    monkeypatch.setattr(runner_module, "_ARTIFACT_IO_TIMEOUT_S", 0.02)
    sink = _ArtifactReceiptSink(runner, nonce="d" * 64, evidence_dir=tmp_path)
    with pytest.raises(_RunnerFoundationError, match="ACK deadline"):
        sink.accept_one(**_accept(123, photo))
    assert len(glob.glob(str(tmp_path / "periodic-g1-s1-*.png"))) == 1
    assert os.path.isfile(tmp_path / "periodic-receipts.jsonl")
    client.close()


@_POSIX_ARTIFACT_CAPABILITY
def test_evidence_directory_replacement_between_lstat_and_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    os.chmod(tmp_path, 0o700)
    replacement = tmp_path.with_name(tmp_path.name + "-replacement")
    original_open = os.open
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(path) == tmp_path:
            swapped = True
            os.rename(tmp_path, replacement)
            os.mkdir(tmp_path, 0o700)
        return original_open(path, flags, *args, **kwargs)

    client, runner = socket.socketpair()
    monkeypatch.setattr(os, "open", swap_then_open)
    with pytest.raises(_RunnerFoundationError, match="identity changed"):
        _ArtifactReceiptSink(runner, nonce="d" * 64, evidence_dir=tmp_path)
    client.close()
    runner.close()


@pytest.mark.asyncio
@_POSIX_ARTIFACT_CAPABILITY
async def test_wrong_ack_is_unknown_and_terminal() -> None:
    client, runner = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    session = SoakPeriodicDeliverySession(client, "d" * 64, 1, 1234)
    lease = session.lease()
    photo = _png()

    def peer() -> None:
        size = struct.unpack("!I", runner.recv(4))[0]
        remaining = size
        while remaining:
            remaining -= len(runner.recv(remaining))
        runner.sendall(struct.pack("!I", 2) + b"{}")

    thread = threading.Thread(target=peer, daemon=True)
    thread.start()
    result = await lease.send_artifact(photo, "Сводка", _context(photo))
    assert result.outcome is PeriodicDeliveryOutcome.UNKNOWN
    assert session._terminal is True
    runner.close()


@pytest.mark.asyncio
@_POSIX_ARTIFACT_CAPABILITY
async def test_cancellation_after_frame_bytes_poison_session() -> None:
    client, runner = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    session = SoakPeriodicDeliverySession(client, "d" * 64, 1, 1234)
    lease = session.lease()
    photo = _png()
    task = asyncio.create_task(lease.send_artifact(photo, "Сводка", _context(photo)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session._terminal is True
    runner.close()


@pytest.mark.asyncio
@_POSIX_ARTIFACT_CAPABILITY
async def test_only_one_artifact_may_be_in_flight() -> None:
    client, runner = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    session = SoakPeriodicDeliverySession(client, "d" * 64, 1, 1234)
    lease = session.lease()
    photo = _png()
    first = asyncio.create_task(lease.send_artifact(photo, "Сводка", _context(photo)))
    await asyncio.sleep(0)
    second = await lease.send_artifact(photo, "Сводка", _context(photo))
    assert second.outcome is PeriodicDeliveryOutcome.NOT_SENT
    assert second.error_code == "soak_client_busy"
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    runner.close()


@pytest.mark.asyncio
@_POSIX_ARTIFACT_CAPABILITY
async def test_cancellation_before_first_byte_rolls_back_sequence_without_acceptance() -> None:
    client, runner = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    client.setblocking(False)
    filler = b"x" * 64 * 1024
    while True:
        try:
            client.send(filler)
        except BlockingIOError:
            break
    session = SoakPeriodicDeliverySession(client, "d" * 64, 1, 1234)
    lease = session.lease()
    photo = _png()
    task = asyncio.create_task(lease.send_artifact(photo, "Сводка", _context(photo)))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session._sequence == 0
    assert session._terminal is False
    await session.close()
    runner.close()
