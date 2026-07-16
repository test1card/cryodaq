from __future__ import annotations

import os
from pathlib import Path

import pytest

import cryodaq.storage._windows_secure_read as secure_read
from cryodaq.storage._windows_secure_read import SecureRelativeReadError, read_secure_relative_bytes
from cryodaq.storage.channel_descriptors import (
    ChannelDescriptorStorageError,
    load_live_channel_descriptor_catalog,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows native-handle contract")


def _junction(target: Path, link: Path) -> None:
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


def test_reads_nested_file_from_retained_native_handles(tmp_path: Path) -> None:
    root = tmp_path / "config"
    nested = root / "lab"
    nested.mkdir(parents=True)
    (nested / "channels.yaml").write_bytes(b"schema_version: 1\n")

    assert read_secure_relative_bytes(root, "lab/channels.yaml") == b"schema_version: 1\n"


@pytest.mark.parametrize(
    "relative",
    ["", "../outside", "lab/../outside", "C:/outside", "/outside", "stream:secret", "name. "],
)
def test_rejects_non_relative_or_ambiguous_names(tmp_path: Path, relative: str) -> None:
    with pytest.raises(SecureRelativeReadError):
        read_secure_relative_bytes(tmp_path, relative)


def test_rejects_component_length_before_unicode_string_can_alias(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"must-not-be-selected")

    with pytest.raises(SecureRelativeReadError, match="NTFS limit"):
        read_secure_relative_bytes(tmp_path, "a" * 32_769)


def test_case_mismatch_cannot_select_differently_cased_authority(tmp_path: Path) -> None:
    (tmp_path / "Manifest.YAML").write_bytes(b"must-not-be-selected")

    with pytest.raises(SecureRelativeReadError):
        read_secure_relative_bytes(tmp_path, "manifest.yaml")


def test_rejects_non_fixed_drive_before_root_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secure_read, "_GetDriveTypeW", lambda _root: 4)

    with pytest.raises(SecureRelativeReadError, match="fixed local drive"):
        read_secure_relative_bytes(tmp_path, "manifest.yaml")


def test_wraps_native_value_error_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def invalid_native_value(_drive: str) -> int:
        raise ValueError("ctypes conversion failed")

    monkeypatch.setattr(secure_read, "_open_drive_root", invalid_native_value)

    with pytest.raises(SecureRelativeReadError, match="secure relative read failed"):
        read_secure_relative_bytes(tmp_path, "manifest.yaml")


def test_rejects_junction_inside_relative_traversal(tmp_path: Path) -> None:
    root = tmp_path / "config"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "channels.yaml").write_bytes(b"outside")
    _junction(outside, root / "redirect")

    with pytest.raises(SecureRelativeReadError, match="reparse point"):
        read_secure_relative_bytes(root, "redirect/channels.yaml")


def test_rejects_reparse_ancestor_in_root_path(tmp_path: Path) -> None:
    real = tmp_path / "real"
    nested = real / "nested"
    nested.mkdir(parents=True)
    (nested / "channels.yaml").write_bytes(b"outside")
    _junction(real, tmp_path / "root-link")

    with pytest.raises(SecureRelativeReadError, match="reparse point"):
        read_secure_relative_bytes(tmp_path / "root-link" / "nested", "channels.yaml")


def test_rejects_final_reparse_object(tmp_path: Path) -> None:
    root = tmp_path / "config"
    target = tmp_path / "target"
    root.mkdir()
    target.mkdir()
    _junction(target, root / "channels.yaml")

    with pytest.raises(SecureRelativeReadError, match="final file is a reparse point"):
        read_secure_relative_bytes(root, "channels.yaml")

    with pytest.raises(ChannelDescriptorStorageError, match="single-link regular file"):
        load_live_channel_descriptor_catalog(root / "channels.yaml")


def test_rejects_hard_linked_final_file(tmp_path: Path) -> None:
    original = tmp_path / "original.yaml"
    linked = tmp_path / "channels.yaml"
    original.write_bytes(b"shared")
    os.link(original, linked)

    with pytest.raises(SecureRelativeReadError, match="exactly one hard link"):
        read_secure_relative_bytes(tmp_path, "channels.yaml")


def test_reads_opened_file_not_same_metadata_replacement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "config"
    root.mkdir()
    selected = root / "channels.yaml"
    replacement = root / "replacement.yaml"
    selected.write_bytes(b"trusted1")
    replacement.write_bytes(b"hostile1")
    timestamp_ns = selected.stat().st_mtime_ns
    os.utime(replacement, ns=(timestamp_ns, timestamp_ns))
    original_read = secure_read._read_handle

    def replace_then_read(handle: int, max_bytes: int) -> bytes:
        os.replace(selected, root / "selected.old")
        os.replace(replacement, selected)
        os.utime(selected, ns=(timestamp_ns, timestamp_ns))
        return original_read(handle, max_bytes)

    monkeypatch.setattr(secure_read, "_read_handle", replace_then_read)

    assert read_secure_relative_bytes(root, "channels.yaml") == b"trusted1"
    assert selected.read_bytes() == b"hostile1"
    assert selected.stat().st_size == (root / "selected.old").stat().st_size
    assert selected.stat().st_mtime_ns == (root / "selected.old").stat().st_mtime_ns


def test_retained_ancestor_handle_defeats_directory_aba(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "config"
    held = root / "held"
    held.mkdir(parents=True)
    (held / "channels.yaml").write_bytes(b"trusted")
    original_open = secure_read._open_relative

    def swap_after_open(parent: int, name: str, *, directory: bool) -> int:
        handle = original_open(parent, name, directory=directory)
        if name == "held":
            os.replace(held, root / "held.old")
            held.mkdir()
            (held / "channels.yaml").write_bytes(b"hostile")
        return handle

    monkeypatch.setattr(secure_read, "_open_relative", swap_after_open)

    assert read_secure_relative_bytes(root, "held/channels.yaml") == b"trusted"
    assert (root / "held" / "channels.yaml").read_bytes() == b"hostile"


def test_enforces_read_bound(tmp_path: Path) -> None:
    (tmp_path / "channels.yaml").write_bytes(b"12345")

    with pytest.raises(SecureRelativeReadError, match="exceeds max_bytes"):
        read_secure_relative_bytes(tmp_path, "channels.yaml", max_bytes=4)
