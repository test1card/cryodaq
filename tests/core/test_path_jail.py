"""Tests for the calibration import/export path jail (ME-6)."""

from __future__ import annotations

import pytest

from cryodaq.core.path_jail import resolve_within


def test_resolve_within_rejects_traversal(tmp_path):
    base = tmp_path / "exports"
    base.mkdir()
    for bad in ["../../etc/x", "/tmp/z", "~/y"]:
        with pytest.raises(ValueError):
            resolve_within(base, bad)


def test_resolve_within_allows_in_base_name(tmp_path):
    base = tmp_path / "exports"
    base.mkdir()
    ok = resolve_within(base, "curve_T12.json")
    assert str(ok).startswith(str(base.resolve()))


def test_resolve_within_rejects_symlink_escape(tmp_path):
    """A symlink that lives inside base but points outside must be rejected."""
    base = tmp_path / "exports"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = base / "escape"
    link.symlink_to(outside)
    with pytest.raises(ValueError):
        resolve_within(base, "escape/secret.json")


def test_resolve_within_allows_nested_in_base(tmp_path):
    base = tmp_path / "exports"
    base.mkdir()
    ok = resolve_within(base, "sub/curve.340")
    assert str(ok).startswith(str(base.resolve()))
