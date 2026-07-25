"""Audit logger — persists every GemmaAgent LLM call for post-hoc review."""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import json
import logging
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400


@contextlib.contextmanager
def _owned_directory(path: Path):
    """Hold a no-delete-share directory handle while mutating its contents."""
    if os.name != "nt":
        fd = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            yield fd
        finally:
            os.close(fd)
        return
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(path),
        0x80000000,
        0x00000001 | 0x00000002,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.get_last_error()
        raise OSError(error, f"cannot own audit directory: {path}")
    try:
        yield handle
    finally:
        close_handle(handle)


def _reject_reparse_parent(path: Path) -> None:
    """Reject symlink/junction parents before creating audit evidence."""
    current = path
    while True:
        observed = os.lstat(current)
        if current.is_symlink() or bool(getattr(observed, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
            raise RuntimeError(f"audit path contains a reparse component: {current}")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _write_audit_record(path: Path, record: dict[str, Any]) -> None:
    """Create and atomically persist one strict-JSON audit record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_reparse_parent(path.parent)
    content = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _reject_reparse_parent(path.parent)
        with _owned_directory(path.parent) as directory_fd:
            if os.name == "posix":
                os.replace(
                    Path(temp_name).name,
                    path.name,
                    src_dir_fd=directory_fd,
                    dst_dir_fd=directory_fd,
                )
            else:
                os.replace(temp_name, path)
        _reject_reparse_parent(path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


class AuditLogger:
    """Writes one JSON file per LLM call under audit_dir/<YYYY-MM-DD>/.

    Schema per file matches docs/ORCHESTRATION.md, "Audit evidence".
    Retention housekeeping (deleting old files) is handled by HousekeepingService.
    """

    def __init__(
        self,
        audit_dir: Path,
        *,
        enabled: bool = True,
        retention_days: int = 90,
    ) -> None:
        self._audit_dir = Path(audit_dir)
        self._enabled = enabled
        self._retention_days = retention_days
        self._pending: dict[str, tuple[Path, dict[str, Any]]] = {}
        self._owned_tasks: set[asyncio.Task[Any]] = set()
        self._closed = False
        _legacy = Path("data/agents/gemma/audit")
        if _legacy.exists():
            logger.warning(
                "Legacy audit log path %s found. New path is %s. "
                "Manual migration required: mv data/agents/gemma/audit "
                "data/agents/assistant/audit — NEVER auto-deleted.",
                _legacy,
                self._audit_dir,
            )

    def make_audit_id(self) -> str:
        """Return a collision-resistant ID for one audit record."""
        return uuid.uuid4().hex

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _owned_to_thread(self, function, *args: Any) -> Any:
        if self._closed:
            raise RuntimeError("audit logger is closed")
        task = asyncio.create_task(asyncio.to_thread(function, *args), name="assistant_audit_io")
        self._owned_tasks.add(task)
        task.add_done_callback(self._owned_tasks.discard)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.shield(task)
            raise

    async def prepare(
        self,
        *,
        audit_id: str,
        trigger_event: dict[str, Any],
        context_assembled: str,
        prompt_template: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        response: str,
        tokens: dict[str, int],
        latency_s: float,
        errors: list[str],
    ) -> Path | None:
        """Durably persist an output intent before any external dispatch."""
        if not self._enabled:
            return None
        if self._closed:
            raise RuntimeError("audit logger is closed")

        now = datetime.now(UTC)
        path = self._audit_dir / now.strftime("%Y-%m-%d") / (f"{now.strftime('%Y%m%dT%H%M%S%f')}_{audit_id}.json")
        record: dict[str, Any] = {
            "audit_id": audit_id,
            "timestamp": now.isoformat(),
            "trigger_event": trigger_event,
            "context_assembled": context_assembled,
            "prompt_template": prompt_template,
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response": response,
            "tokens": tokens,
            "latency_s": round(latency_s, 3),
            "delivery_state": "intent_persisted",
            "outputs_dispatched": [],
            "output_outcomes": {},
            "errors": list(errors),
        }
        await self._owned_to_thread(_write_audit_record, path, record)
        self._pending[audit_id] = (path, record)
        return path

    async def complete(
        self,
        *,
        audit_id: str,
        outputs_dispatched: list[str],
        output_outcomes: dict[str, str],
        errors: list[str],
    ) -> Path | None:
        """Persist exact output settlement without fabricating delivery."""
        pending = self._pending.get(audit_id)
        if pending is None:
            return None
        path, record = pending
        record.update(
            {
                "delivery_state": "settled",
                "outputs_dispatched": list(outputs_dispatched),
                "output_outcomes": dict(output_outcomes),
                "errors": list(errors),
            }
        )
        await self._owned_to_thread(_write_audit_record, path, record)
        self._pending.pop(audit_id, None)
        return path

    async def log(
        self,
        *,
        audit_id: str,
        trigger_event: dict[str, Any],
        context_assembled: str,
        prompt_template: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        response: str,
        tokens: dict[str, int],
        latency_s: float,
        outputs_dispatched: list[str],
        errors: list[str],
        output_intent: list[str] | None = None,
    ) -> Path | None:
        """Persist an audit record. Returns the file path, or None if disabled or failed."""
        if not self._enabled:
            return None
        if self._closed:
            raise RuntimeError("audit logger is closed")

        now = datetime.now(UTC)
        date_dir = self._audit_dir / now.strftime("%Y-%m-%d")

        filename = f"{now.strftime('%Y%m%dT%H%M%S%f')}_{audit_id}.json"
        path = date_dir / filename

        record: dict[str, Any] = {
            "audit_id": audit_id,
            "timestamp": now.isoformat(),
            "trigger_event": trigger_event,
            "context_assembled": context_assembled,
            "prompt_template": prompt_template,
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response": response,
            "tokens": tokens,
            "latency_s": round(latency_s, 3),
            "output_intent": list(output_intent or []),
            "outputs_dispatched": outputs_dispatched,
            "errors": errors,
        }

        # JSON encoding, directory creation, fsync and replacement are all
        # filesystem work and must not stall the assistant event loop.
        await self._owned_to_thread(_write_audit_record, path, record)

        return path

    async def close(self) -> None:
        """Reject new writes and await every owned filesystem operation."""
        self._closed = True
        while self._owned_tasks:
            tasks = tuple(self._owned_tasks)
            await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
