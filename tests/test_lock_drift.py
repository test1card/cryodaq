"""Tests for scripts/check_lock_drift.py — the requirements-lock drift gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
LOCK = REPO_ROOT / "requirements-lock.txt"

_spec = importlib.util.spec_from_file_location(
    "check_lock_drift", REPO_ROOT / "scripts" / "check_lock_drift.py"
)
drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drift)


def test_current_lock_is_in_sync():
    """The regenerated lock pins every top-level pyproject dep."""
    assert drift.find_drift(PYPROJECT, LOCK) == []


def test_main_passes_on_current_lock():
    assert drift.main(["--pyproject", str(PYPROJECT), "--lock", str(LOCK)]) == 0


def test_synthetic_stale_lock_flags_missing(tmp_path):
    """A lock missing the frozen-build-critical pins must be flagged."""
    dropped = {"lancedb", "pypdf", "tzdata", "httpx"}
    kept = [
        line
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if not any(line.startswith(f"{name}==") for name in dropped)
    ]
    stale = tmp_path / "requirements-lock.txt"
    stale.write_text("\n".join(kept) + "\n", encoding="utf-8")

    missing = drift.find_drift(PYPROJECT, stale)
    assert dropped.issubset(set(missing))


def test_main_fails_on_synthetic_stale_lock(tmp_path):
    stale = tmp_path / "requirements-lock.txt"
    stale.write_text("numpy==2.4.4\n", encoding="utf-8")  # almost everything missing
    assert drift.main(["--pyproject", str(PYPROJECT), "--lock", str(stale)]) == 1


def test_name_normalization():
    """PEP 503: underscores/dots/case fold to the same canonical name."""
    assert drift._canon("PyPDF") == drift._canon("pypdf") == "pypdf"
    assert drift._canon("pytest_timeout") == "pytest-timeout"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
