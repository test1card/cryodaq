"""Tests for audit log retention cleanup."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryodaq.agents.assistant.shared.retention import cleanup_old_audits


def _make_audit_file(date_dir: Path, name: str = "audit.json") -> Path:
    date_dir.mkdir(parents=True, exist_ok=True)
    f = date_dir / name
    f.write_text(json.dumps({"audit_id": name}), encoding="utf-8")
    return f


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
