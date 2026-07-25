"""Regression test: directory mutation-token identity must ignore st_nlink.

For a directory, st_nlink is 2 + the subdirectory count -- a property of
the directory's CONTENTS, not of the directory's identity. A subdirectory
created mid-scan (e.g. cold rotation writing a new date directory) changes
st_nlink while st_dev/st_ino/mtime/ctime still prove it is the same
directory.

_operator_log_read_identity() is used to build the directory mutation
tokens consulted by _read_only_mutation_token(), mutation_token(), and
relative_mutation_token() (sqlite_writer.py ~1614-1659). Before this fix it
folded st_nlink in unconditionally, so a benign concurrent mkdir under a
retained directory would flip the token and trip a false-positive
"authority changed" abort. For a FILE, st_nlink remains legitimate identity
evidence (an unnoticed hardlink swap) and must still be honored -- this
mirrors the fix already applied to _control_handle_identity().
"""

from __future__ import annotations

from types import SimpleNamespace

from cryodaq.storage.sqlite_writer import _operator_log_read_identity


def _stat_like(*, st_mode: int, st_nlink: int) -> SimpleNamespace:
    return SimpleNamespace(
        st_dev=1,
        st_ino=2,
        st_mode=st_mode,
        st_nlink=st_nlink,
        st_size=4096,
        st_mtime_ns=1_000_000_000,
        st_ctime_ns=1_000_000_000,
    )


def test_directory_identity_survives_subdirectory_created_mid_scan() -> None:
    import stat as stat_module

    directory_mode = stat_module.S_IFDIR | 0o700
    before = _stat_like(st_mode=directory_mode, st_nlink=2)  # empty directory
    after = _stat_like(st_mode=directory_mode, st_nlink=3)  # one subdir appeared

    assert before.st_nlink != after.st_nlink, "test setup must actually change st_nlink"
    assert _operator_log_read_identity(before, directory=True) == _operator_log_read_identity(
        after, directory=True
    ), "directory identity must ignore st_nlink -- it reflects contents, not identity"


def test_file_identity_still_honors_st_nlink() -> None:
    """Sanity: the directory carve-out must not silently disable nlink
    evidence for files, where it is genuine identity evidence."""
    import stat as stat_module

    file_mode = stat_module.S_IFREG | 0o600
    single_link = _stat_like(st_mode=file_mode, st_nlink=1)
    hardlinked = _stat_like(st_mode=file_mode, st_nlink=2)

    assert _operator_log_read_identity(single_link, directory=False) != _operator_log_read_identity(
        hardlinked, directory=False
    ), "file identity must still change when st_nlink changes"
