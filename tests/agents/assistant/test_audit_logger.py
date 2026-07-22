"""Deterministic persistence contracts for the assistant audit logger."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path

from cryodaq.agents.assistant.shared import audit as audit_module


def _record_args() -> dict:
    return {
        "audit_id": "abc123",
        "trigger_event": {"kind": "test"},
        "context_assembled": "context",
        "prompt_template": "template",
        "model": "local-model",
        "system_prompt": "system",
        "user_prompt": "user",
        "response": "response",
        "tokens": {"input": 1, "output": 2},
        "latency_s": 0.125,
        "outputs_dispatched": ["operator_log"],
        "errors": [],
    }


async def test_audit_log_offloads_atomic_file_io(tmp_path: Path, monkeypatch) -> None:
    """A slow disk worker must not occupy the assistant event-loop thread."""
    original = audit_module._write_audit_record
    entered = threading.Event()
    release = threading.Event()
    worker_ids: list[int] = []

    def _blocked_write(path: Path, record: dict) -> None:
        worker_ids.append(threading.get_ident())
        entered.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test did not release audit writer")
        original(path, record)

    monkeypatch.setattr(audit_module, "_write_audit_record", _blocked_write)
    logger = audit_module.AuditLogger(tmp_path / "audit")
    started = time.monotonic()
    task = asyncio.create_task(logger.log(**_record_args()))
    watchdog = threading.Timer(2.0, release.set)
    watchdog.start()
    try:
        assert await asyncio.to_thread(entered.wait, 1.0)
        assert time.monotonic() - started < 1.0
        assert len(worker_ids) == 1
        assert worker_ids[0] != threading.get_ident()
        release.set()
        path = await task
    finally:
        release.set()
        watchdog.cancel()

    assert path is not None and path.exists()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["audit_id"] == "abc123"
    assert payload["latency_s"] == 0.125
