"""Tests for cryodaq.core.atomic_write."""
from __future__ import annotations

import os

import pytest

from cryodaq.core.atomic_write import atomic_write_bytes, atomic_write_text


def test_atomic_write_creates_file(tmp_path):
    target = tmp_path / "state.json"
    atomic_write_text(target, '{"ok": true}')
    assert target.read_text(encoding="utf-8") == '{"ok": true}'


def test_atomic_write_overwrites_existing(tmp_path):
    target = tmp_path / "state.json"
    target.write_text("old", encoding="utf-8")
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_atomic_write_no_partial_on_replace_failure(tmp_path, monkeypatch):
    """If os.replace fails, target keeps its original content and no temp leaks."""
    target = tmp_path / "state.json"
    target.write_text("original", encoding="utf-8")

    def bad_replace(*args, **kwargs):
        raise OSError("simulated")

    monkeypatch.setattr(os, "replace", bad_replace)

    with pytest.raises(OSError):
        atomic_write_text(target, "new content")

    assert target.read_text(encoding="utf-8") == "original"
    leaked = list(tmp_path.glob(".state.json.*.tmp"))
    assert leaked == [], f"Temp files leaked: {leaked}"


def test_atomic_write_cyrillic(tmp_path):
    """Cyrillic content (Russian operator log) round-trips through utf-8."""
    target = tmp_path / "log.txt"
    atomic_write_text(target, "Эксперимент начат, оператор Иванов")
    assert target.read_text(encoding="utf-8") == "Эксперимент начат, оператор Иванов"


def test_atomic_write_bytes(tmp_path):
    target = tmp_path / "blob.bin"
    payload = b"\x00\x01\x02\xff"
    atomic_write_bytes(target, payload)
    assert target.read_bytes() == payload
