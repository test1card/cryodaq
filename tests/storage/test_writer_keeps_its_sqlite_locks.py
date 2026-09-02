"""The writer must keep the SQLite locks that protect its own WAL.

Regression for the incident of 2026-09-02 22:45:45, in which every write began
failing with ``control database handle has invalid authority`` and the stand
persisted nothing for the next 40 minutes.

Mechanism: ``_ControlDatabaseAuthority.validate()`` runs before and after every
SQL statement, and proved path identity by opening a fresh descriptor on the
database and on each sidecar and then closing it. On Linux, closing ANY
descriptor a process holds on a file releases ALL of that process's fcntl locks
on that file — the lock is owned by the process, not by the descriptor. So each
validation destroyed SQLite's WAL dead-man-switch lock on ``-shm`` byte 128 and
its SHARED range lock on the main database. With those gone, the next process to
open the database read-write and close it cleanly believed itself the last
connection, checkpointed the WAL into the database and unlinked ``-wal`` and
``-shm``; the retained authority handles then correctly saw ``st_nlink == 0``
and refused every subsequent write.

These tests assert KERNEL state (``/proc/locks``) and READ-BACK durability, not
merely the absence of an exception, so they cannot pass by accident. Verified
red against the pre-fix tree: without the fix, ``test_writer_holds_wal_dead_man_switch``
reports no lock at all and ``test_external_rw_close_cannot_unlink_the_live_wal``
raises the exact production RuntimeError.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.sqlite_writer import SQLiteWriter

# The cross-process test below must import cryodaq from the SAME tree this
# run imported it from, not from whatever happens to be installed.
_SRC = str(Path(SQLiteWriter.__module__ and __import__("cryodaq").__file__).parent.parent)

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="POSIX close-drops-locks semantics; Windows locks are per-handle",
)


def _batch(count: int, base: float) -> list[Reading]:
    now = datetime.now(UTC)
    return [
        Reading(
            timestamp=now,
            instrument_id="T",
            channel=f"c{index}",
            value=base + index,
            unit="K",
            status=ChannelStatus.OK,
        )
        for index in range(count)
    ]


@dataclass(frozen=True)
class _LockRecord:
    """One parsed /proc/locks row, bound to the file it is actually against."""

    kind: str  # POSIX | FLOCK | OFDLCK
    mode: str  # ADVISORY | MANDATORY
    lock_type: str  # READ | WRITE
    pid: int
    major: int
    minor: int
    inode: int
    start: str
    end: str


def _locks_against(path: Path) -> list[_LockRecord]:
    """Every /proc/locks record whose (device, inode) is exactly this file.

    Matching on the inode alone would collide across filesystems, so the device
    from stat() is decomposed and compared too.
    """

    info = path.stat()
    want = (os.major(info.st_dev), os.minor(info.st_dev), info.st_ino)
    records: list[_LockRecord] = []
    for line in Path("/proc/locks").read_text().splitlines():
        fields = line.split()
        # e.g. "6: POSIX  ADVISORY  READ 7213 08:12:6061524 128 128"
        if len(fields) < 8:
            continue
        device = fields[5].split(":")
        if len(device) != 3:
            continue
        try:
            got = (int(device[0], 16), int(device[1], 16), int(device[2]))
        except ValueError:
            continue
        if got != want:
            continue
        records.append(
            _LockRecord(
                kind=fields[1],
                mode=fields[2],
                lock_type=fields[3],
                pid=int(fields[4]),
                major=got[0],
                minor=got[1],
                inode=got[2],
                start=fields[6],
                end=fields[7],
            )
        )
    return records


def _started_writer(tmp_path: Path) -> tuple[SQLiteWriter, Path]:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    writer = SQLiteWriter(data_dir)
    assert writer._write_batch(_batch(3, 100.0)) is True
    databases = sorted(data_dir.glob("data_????-??-??.db"))
    assert len(databases) == 1
    return writer, databases[0]


def test_writer_holds_wal_dead_man_switch(tmp_path: Path) -> None:
    """After a write, the kernel must show our WAL locks are still held.

    This is the direct assertion. Application code cannot fake it: the records
    come from /proc/locks, and they name the holding pid.
    """

    _writer, database = _started_writer(tmp_path)
    shm = Path(f"{database}-shm")
    assert shm.exists(), "WAL mode should have created the -shm sidecar"

    shm_locks = _locks_against(shm)
    dead_man_switch = [
        record
        for record in shm_locks
        if record.kind == "POSIX"
        and record.lock_type == "READ"
        and record.pid == os.getpid()
        and record.start == "128"
        and record.end == "128"
    ]
    assert dead_man_switch, (
        "SQLite's WAL dead-man-switch lock — POSIX READ, pid "
        f"{os.getpid()}, bytes 128..128 on {shm.name} — is not held. The "
        f"authority validation has released our locks. Records seen: {shm_locks}"
    )

    database_locks = [
        record for record in _locks_against(database) if record.kind == "POSIX" and record.pid == os.getpid()
    ]
    assert database_locks, "the SHARED range lock on the main database is not held by this process"
    assert any(record.lock_type == "READ" for record in database_locks), (
        f"expected a shared (READ) lock on the main database, got {database_locks}"
    )


def test_external_rw_close_cannot_unlink_the_live_wal(tmp_path: Path) -> None:
    """The exact 22:45:45 sequence must leave the writer working and durable."""

    writer, database = _started_writer(tmp_path)
    wal = Path(f"{database}-wal")
    shm = Path(f"{database}-shm")
    wal_inode = wal.stat().st_ino
    shm_inode = shm.stat().st_ino

    # An outside process opens the live database READ-WRITE, reads, closes
    # cleanly. This is what archive/report tooling used to do.
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sqlite3, sys;"
            " conn = sqlite3.connect(sys.argv[1], timeout=5);"
            " list(conn.execute('select count(*) from readings'));"
            " conn.close()",
            str(database),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr

    assert wal.exists() and wal.stat().st_ino == wal_inode, (
        "the external reader's close checkpointed and unlinked our live WAL"
    )
    assert shm.exists() and shm.stat().st_ino == shm_inode, "the external reader's close unlinked our live SHM"

    # The writer must still commit, and the rows must be durable — proven by an
    # independent read-only connection, not by the writer's own return value.
    assert writer._write_batch(_batch(3, 200.0)) is True
    readonly = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5)
    try:
        persisted = readonly.execute("select count(*) from readings where value >= 200").fetchone()[0]
    finally:
        readonly.close()
    assert persisted == 3


def test_read_only_reader_is_harmless_and_can_read(tmp_path: Path) -> None:
    """mode=ro is the shape archive reads must use, and it must still work."""

    writer, database = _started_writer(tmp_path)
    wal_inode = Path(f"{database}-wal").stat().st_ino

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sqlite3, sys;"
            " conn = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True, timeout=5);"
            " print(conn.execute('select count(*) from readings').fetchone()[0]);"
            " conn.close()",
            str(database),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "3"
    assert Path(f"{database}-wal").stat().st_ino == wal_inode
    assert writer._write_batch(_batch(1, 300.0)) is True


def test_symlink_swapped_over_the_database_is_refused_by_the_stat_probe(
    tmp_path: Path,
) -> None:
    """A symlink at the database name must be refused by the NEW code path.

    This has to be set up carefully. Simply unlinking the database and putting a
    symlink at its name leaves the RETAINED descriptor pointing at an inode with
    ``st_nlink == 0``, so ``validate_retained_handles()`` — which runs first —
    raises before ``_control_stat_identity_at()`` is ever reached. Such a test
    passes while proving nothing about the change under test.

    Renaming the real database aside keeps its link count at 1, so the retained
    handle stays valid and validation proceeds to the anchored stat probe, which
    is what must reject the symlink.

    This is a PRESERVATION test, not a defect reproduction. The pre-fix tree also
    refuses the symlink, but by a different route: its ``O_NOFOLLOW`` open fails
    with ``OSError``/``ELOOP``. The fixed tree refuses it because
    ``os.stat(..., follow_symlinks=False)`` reports ``S_IFLNK``, which fails the
    kind check. Both fail closed, which is the guarantee that had to survive the
    change, so either exception is accepted here.
    """

    writer, database = _started_writer(tmp_path)
    assert writer._write_batch(_batch(1, 400.0)) is True

    moved = database.parent / "moved_aside.db"
    os.rename(database, moved)
    assert moved.stat().st_nlink == 1
    database.symlink_to(moved.name)
    assert database.is_symlink()

    with pytest.raises((RuntimeError, OSError)):
        writer._write_batch(_batch(1, 500.0))


def test_a_different_regular_file_at_the_database_name_is_refused(
    tmp_path: Path,
) -> None:
    """Identity, not just kind: another regular file at the name must fail.

    Same rename trick, so the retained handle stays linked and the anchored stat
    probe is the check that has to notice the (device, inode) changed.
    """

    writer, database = _started_writer(tmp_path)
    moved = database.parent / "moved_aside.db"
    os.rename(database, moved)
    imposter = database
    imposter.write_bytes(b"")
    assert imposter.is_file() and not imposter.is_symlink()
    assert imposter.stat().st_ino != moved.stat().st_ino

    with pytest.raises(RuntimeError, match="authority"):
        writer._write_batch(_batch(1, 600.0))


def test_hard_linked_database_is_refused(tmp_path: Path) -> None:
    """A second name for the same inode must fail the single-owner rule."""

    writer, database = _started_writer(tmp_path)
    os.link(database, database.parent / "second_name.db")
    assert database.stat().st_nlink == 2

    with pytest.raises(RuntimeError, match="authority"):
        writer._write_batch(_batch(1, 700.0))


def test_archive_reader_declared_descriptor_hashes_cannot_disturb_the_writer(
    tmp_path: Path,
) -> None:
    """The glob-every-day path must read without replacing the live sidecars.

    ``declared_descriptor_hashes()`` globs every ``data_*.db`` — including the
    one the writer currently has open — and used to open each read-write. A
    clean close on such a connection is the reproduced unlink trigger.

    It has to run in a SEPARATE process to be a real test. In-process, SQLite
    shares one shm node per inode and its refcount prevents deletion regardless
    of lock state, so an in-process reader can never reproduce the fault and a
    test built that way would pass on the broken tree too.
    """

    writer, database = _started_writer(tmp_path)
    wal_inode = Path(f"{database}-wal").stat().st_ino
    shm_inode = Path(f"{database}-shm").stat().st_ino

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys;"
            " from pathlib import Path;"
            " from cryodaq.storage.archive_reader import ArchiveReader;"
            " reader = ArchiveReader(Path(sys.argv[1]), Path(sys.argv[2]));"
            " print(len(reader.declared_descriptor_hashes()))",
            str(database.parent),
            str(tmp_path / "archive"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(_SRC)},
    )
    assert completed.returncode == 0, completed.stderr

    assert Path(f"{database}-wal").stat().st_ino == wal_inode, "declared_descriptor_hashes() replaced the live WAL"
    assert Path(f"{database}-shm").stat().st_ino == shm_inode, "declared_descriptor_hashes() replaced the live SHM"

    assert writer._write_batch(_batch(1, 800.0)) is True
    readonly = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5)
    try:
        persisted = readonly.execute("select count(*) from readings where value >= 800").fetchone()[0]
    finally:
        readonly.close()
    assert persisted == 1
