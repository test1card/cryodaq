"""Deterministic persistence contracts for the assistant audit logger."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

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


async def test_atomic_audit_write_rejects_reparse_parent_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_root = tmp_path / "audit"
    outside = tmp_path / "outside"
    outside.mkdir()
    logger = audit_module.AuditLogger(audit_root)
    original_replace = audit_module.os.replace
    attempted = False
    swapped_parent: Path | None = None
    outside_target: Path | None = None

    def _swap_parent_at_commit(source, destination, *args, **kwargs) -> None:
        nonlocal attempted, swapped_parent, outside_target
        attempted = True
        source_path = Path(source)
        destination_path = Path(destination)
        if kwargs.get("dst_dir_fd") is not None:
            parent = next(path for path in audit_root.iterdir() if path.is_dir())
        else:
            parent = destination_path.parent
        parked = audit_root / "parked-date"
        outside_target = outside / destination_path.name
        outside_target.write_text("outside-sentinel", encoding="utf-8")
        parent.rename(parked)
        if os.name == "nt":
            created = subprocess.run(
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(parent),
                    str(outside),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert created.returncode == 0, created.stderr or created.stdout
        else:
            os.symlink(outside, parent, target_is_directory=True)
        swapped_parent = parent
        if kwargs.get("src_dir_fd") is None:
            outside_source = outside / source_path.name
            outside_source.write_text("attacker-controlled-temp", encoding="utf-8")
        original_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(audit_module.os, "replace", _swap_parent_at_commit)
    try:
        with pytest.raises((OSError, RuntimeError)):
            await logger.prepare(
                audit_id="abc123",
                trigger_event={"kind": "test"},
                context_assembled="context",
                prompt_template="template",
                model="local-model",
                system_prompt="system",
                user_prompt="user",
                response="response",
                tokens={"input": 1, "output": 2},
                latency_s=0.125,
                errors=[],
            )
    finally:
        await logger.close()
        if swapped_parent is not None:
            with contextlib.suppress(OSError):
                if os.name == "nt":
                    os.rmdir(swapped_parent)
                else:
                    os.unlink(swapped_parent)

    assert attempted is True
    assert outside_target is not None
    assert await asyncio.to_thread(outside_target.read_text, encoding="utf-8") == "outside-sentinel"
