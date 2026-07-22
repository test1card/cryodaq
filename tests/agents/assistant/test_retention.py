"""Tests for audit log retention cleanup."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from cryodaq.agents.assistant.shared import retention as retention_module
from cryodaq.agents.assistant.shared.retention import cleanup_old_audits


def _make_audit_file(date_dir: Path, name: str = "audit.json") -> Path:
    date_dir.mkdir(parents=True, exist_ok=True)
    f = date_dir / name
    f.write_text(json.dumps({"audit_id": name}), encoding="utf-8")
    return f


def _remove_directory_link(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if os.name == "nt":
        os.rmdir(path)
    else:
        os.unlink(path)


async def test_cleanup_removes_old_audits(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    old_date = (datetime.now(UTC) - timedelta(days=100)).strftime("%Y-%m-%d")
    old_dir = audit_dir / old_date
    _make_audit_file(old_dir, "old_entry.json")
    _make_audit_file(old_dir, "old_entry2.json")

    deleted = await cleanup_old_audits(audit_dir, retention_days=90)

    assert deleted == 2
    assert not old_dir.exists()


async def test_cleanup_preserves_recent_audits(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    recent_date = datetime.now(UTC).strftime("%Y-%m-%d")
    recent_dir = audit_dir / recent_date
    f = _make_audit_file(recent_dir, "recent.json")

    deleted = await cleanup_old_audits(audit_dir, retention_days=90)

    assert deleted == 0
    assert f.exists()


async def test_cleanup_handles_invalid_dirnames_gracefully(tmp_path: Path) -> None:
    audit_dir = tmp_path / "audit"
    bad_dir = audit_dir / "not-a-date"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "file.json").write_text("{}", encoding="utf-8")

    deleted = await cleanup_old_audits(audit_dir, retention_days=90)

    assert deleted == 0
    assert (bad_dir / "file.json").exists()


async def test_cleanup_nonexistent_dir_returns_zero(tmp_path: Path) -> None:
    deleted = await cleanup_old_audits(tmp_path / "nonexistent", retention_days=90)
    assert deleted == 0


async def test_cleanup_never_follows_symlinked_date_directory(tmp_path: Path) -> None:
    """An expired-looking link cannot turn retention into arbitrary deletion."""
    audit_dir = tmp_path / "audit"
    outside = tmp_path / "outside"
    audit_dir.mkdir()
    decoy = _make_audit_file(outside, "must-survive.json")
    linked_date = audit_dir / "2000-01-01"
    try:
        os.symlink(outside, linked_date, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    deleted = await cleanup_old_audits(audit_dir, retention_days=90)

    assert deleted == 0
    assert decoy.exists()
    assert linked_date.is_symlink()


async def test_cleanup_rejects_windows_reparse_root(tmp_path: Path, monkeypatch) -> None:
    audit_dir = tmp_path / "audit"
    old_dir = audit_dir / "2000-01-01"
    _make_audit_file(old_dir)
    original_lstat = os.lstat

    def _lstat(path):
        observed = original_lstat(path)
        if Path(path) == audit_dir:
            return SimpleNamespace(
                st_file_attributes=0x00000400,
                st_mode=observed.st_mode,
            )
        return observed

    monkeypatch.setattr(retention_module.os, "lstat", _lstat)

    assert await cleanup_old_audits(audit_dir, retention_days=90) == 0
    assert (old_dir / "audit.json").exists()


async def test_windows_junction_and_swap_cannot_escape_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_dir = tmp_path / "audit"
    outside = tmp_path / "outside"
    date_dir = audit_dir / "2000-01-01"
    parked_date_dir = audit_dir / "parked-original"
    victim = _make_audit_file(date_dir, "must-survive.json")
    outside_file = _make_audit_file(outside, "must-survive.json")
    original_unlink = Path.unlink
    original_os_unlink = retention_module.os.unlink
    attempted = False
    swapped = False

    def _swap_parent_then_unlink(path: Path, *args, **kwargs) -> None:
        nonlocal attempted, swapped
        if path == victim and not swapped:
            attempted = True
            date_dir.rename(parked_date_dir)
            created = subprocess.run(
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(date_dir),
                    str(outside),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            assert created.returncode == 0, created.stderr or created.stdout
            swapped = True
        original_unlink(path, *args, **kwargs)

    def _swap_parent_then_unlink_at(path, *args, **kwargs) -> None:
        nonlocal attempted, swapped
        if path == victim.name and kwargs.get("dir_fd") is not None and not swapped:
            attempted = True
            date_dir.rename(parked_date_dir)
            os.symlink(outside, date_dir, target_is_directory=True)
            swapped = True
        original_os_unlink(path, *args, **kwargs)

    if os.name == "nt":
        monkeypatch.setattr(Path, "unlink", _swap_parent_then_unlink)
    else:
        monkeypatch.setattr(retention_module.os, "unlink", _swap_parent_then_unlink_at)
    try:
        deleted = await cleanup_old_audits(audit_dir, retention_days=90)
    finally:
        if swapped:
            await asyncio.to_thread(_remove_directory_link, date_dir)

    assert attempted is True
    assert deleted in {0, 1}
    assert outside_file.exists()
    assert outside_file.read_text(encoding="utf-8") == '{"audit_id": "must-survive.json"}'
