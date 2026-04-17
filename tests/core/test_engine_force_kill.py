"""Tests for engine --force kill lock file handling."""

from __future__ import annotations

import inspect


def test_force_kill_reads_pid_via_os_open():
    """_force_kill_existing must use os.open, not read_text (Windows msvcrt compat)."""
    from cryodaq.engine import _force_kill_existing

    source = inspect.getsource(_force_kill_existing)
    assert "os.open" in source or "os.read" in source, (
        "_force_kill_existing must read PID via os.open/os.read (not read_text)"
    )
    assert "read_text" not in source, (
        "_force_kill_existing must NOT use read_text (PermissionError on Windows with msvcrt lock)"
    )
