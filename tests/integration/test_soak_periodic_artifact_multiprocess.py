from __future__ import annotations

import asyncio
import hashlib
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
from cryodaq.agents.assistant.soak_periodic_delivery import SoakPeriodicDeliverySession
from scripts.soak_mock_stack_runner import (
    _ArtifactReceiptSink,
    _AssistantProcessObservation,
    _ProcessIdentity,
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
