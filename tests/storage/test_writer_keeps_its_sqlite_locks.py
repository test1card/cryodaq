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
from datetime import UTC, datetime
from pathlib import Path

import pytest

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.storage.sqlite_writer import SQLiteWriter

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


def _locks_on_inode(inode: int) -> list[tuple[str, ...]]:
    """Every POSIX/FLOCK record in /proc/locks against one inode."""

    records: list[tuple[str, ...]] = []
    for line in Path("/proc/locks").read_text().splitlines():
        fields = line.split()
        # e.g. "6: POSIX ADVISORY READ 7213 08:12:6061524 128 128"
        if len(fields) >= 8 and fields[5].split(":")[-1] == str(inode):
            records.append(tuple(fields))
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

    shm_locks = _locks_on_inode(shm.stat().st_ino)
    dead_man_switch = [record for record in shm_locks if record[6] == "128"]
    assert dead_man_switch, (
        "SQLite's WAL dead-man-switch lock on -shm byte 128 is gone — the "
        f"authority validation has released our locks. /proc/locks: {shm_locks}"
    )
    assert dead_man_switch[0][4] == str(os.getpid())

    assert _locks_on_inode(database.stat().st_ino), (
        "the SHARED range lock on the main database is gone"
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
    assert shm.exists() and shm.stat().st_ino == shm_inode, (
        "the external reader's close unlinked our live SHM"
    )

    # The writer must still commit, and the rows must be durable — proven by an
    # independent read-only connection, not by the writer's own return value.
    assert writer._write_batch(_batch(3, 200.0)) is True
    readonly = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=5)
    try:
        persisted = readonly.execute(
            "select count(*) from readings where value >= 200"
        ).fetchone()[0]
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


def test_symlink_over_the_database_is_still_refused(tmp_path: Path) -> None:
    """The identity guard must survive the fix, not be softened by it."""

    writer, database = _started_writer(tmp_path)
    # A normal write works first, so the refusal below is attributable to the
    # symlink and not to an already-broken writer.
    assert writer._write_batch(_batch(1, 400.0)) is True

    decoy = database.parent / "decoy.db"
    decoy.write_bytes(b"")
    database.unlink()
    database.symlink_to(decoy)

    with pytest.raises(RuntimeError, match="authority"):
        writer._write_batch(_batch(1, 500.0))
