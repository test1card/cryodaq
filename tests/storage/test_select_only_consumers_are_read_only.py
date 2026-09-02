"""SELECT-only consumers must hold no write authority on a database they read.

Follow-up to the incident of 2026-09-02 22:45:45. The root cause — the authority
probe releasing the writer's own fcntl locks — is fixed in ``b9eee506``, so a
read-write consumer is no longer destructive. This is the second half of the
invariant, and it is a boundary rule rather than a bug fix: code that only reads
receives no write authority, so a clean close can never checkpoint or unlink
sidecars belonging to the writer.

Each test proves the consumer still returns its expected rows through the
read-only URI, because a `mode=ro` conversion that quietly returned nothing
would be worse than the write authority it removed.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


def _make_readings_db(path: Path, *, rows: list[tuple[float, str, float, str, str]]) -> None:
    """A daily database shaped like the writer's, in WAL mode."""

    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE readings (timestamp REAL NOT NULL, channel TEXT NOT NULL, "
            "value REAL NOT NULL, unit TEXT NOT NULL, status TEXT NOT NULL, "
            "instrument_id TEXT NOT NULL DEFAULT 'T')"
        )
        conn.executemany(
            "INSERT INTO readings (timestamp, channel, value, unit, status) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _journal_mode(path: Path) -> str:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    finally:
        conn.close()


def _sidecars(path: Path) -> set[str]:
    return {p.name for p in path.parent.iterdir() if p.name.startswith(f"{path.name}-")}


# --------------------------------------------------------------------------
# 1. web/server.py :: _query_history
# --------------------------------------------------------------------------
def test_web_query_history_still_returns_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cryodaq.web import server

    now = datetime.now(UTC)
    day = tmp_path / f"data_{now.date().isoformat()}.db"
    recent = (now - timedelta(minutes=5)).timestamp()
    _make_readings_db(day, rows=[(recent, "T1", 295.5, "K", "ok"), (recent + 1, "T1", 295.6, "K", "ok")])
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)

    history = server._query_history(60)

    assert "T1" in history, f"expected channel T1 in {list(history)}"
    assert len(history["T1"]) == 2
    assert history["T1"][0]["v"] == pytest.approx(295.5)


# --------------------------------------------------------------------------
# 2. core/experiment.py :: _persisted_running_experiment_ids
# --------------------------------------------------------------------------
def test_persisted_running_experiment_ids_still_finds_running(tmp_path: Path) -> None:
    from cryodaq.core.experiment import ExperimentManager

    day = tmp_path / "data_2026-09-02.db"
    conn = sqlite3.connect(str(day))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE experiments (experiment_id TEXT, status TEXT)")
        conn.executemany(
            "INSERT INTO experiments VALUES (?, ?)",
            [("exp-running", "RUNNING"), ("exp-done", "COMPLETED")],
        )
        conn.commit()
    finally:
        conn.close()

    manager = ExperimentManager.__new__(ExperimentManager)
    manager._data_dir = tmp_path

    assert manager._persisted_running_experiment_ids() == {"exp-running"}


def test_persisted_running_experiment_ids_tolerates_a_vanished_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A read-only open of a database that vanished must skip, not create it.

    The glob must be made to yield a path that no longer exists at connect time,
    otherwise the loop body never runs and the test proves nothing — simply
    unlinking beforehand makes the glob return an empty list.
    """

    from cryodaq.core.experiment import ExperimentManager

    ghost = tmp_path / "data_2026-09-02.db"
    assert not ghost.exists()

    manager = ExperimentManager.__new__(ExperimentManager)
    manager._data_dir = tmp_path
    monkeypatch.setattr(type(tmp_path), "glob", lambda self, pattern: iter([ghost]))

    assert manager._persisted_running_experiment_ids() == set()
    assert not ghost.exists(), "a SELECT-only consumer must not CREATE a database; a read-write open does"


# --------------------------------------------------------------------------
# 3. analytics/calibration_fitter.py :: extract_pairs
# --------------------------------------------------------------------------
def test_calibration_extract_pairs_still_pairs_readings(tmp_path: Path) -> None:
    from cryodaq.analytics.calibration_fitter import CalibrationFitter

    base = datetime(2026, 9, 2, 12, 0, tzinfo=UTC).timestamp()
    day = tmp_path / "data_2026-09-02.db"
    _make_readings_db(
        day,
        rows=[
            (base, "Т1", 295.0, "K", "ok"),
            (base + 0.5, "Т1_raw", 1.234, "V", "ok"),
            (base + 10, "Т1", 296.0, "K", "ok"),
            (base + 10.5, "Т1_raw", 1.240, "V", "ok"),
        ],
    )

    result = CalibrationFitter.extract_pairs(tmp_path, base - 60, base + 60, "Т1", "Т1", raw_channel="Т1_raw")

    assert len(result.pairs) == 2, f"expected two aligned pairs, got {result.pairs}"
    assert not result.skipped_sources, result.skipped_sources


def test_calibration_reader_changes_no_journal_mode_and_adds_no_sidecar(tmp_path: Path) -> None:
    """The reader must leave the database exactly as it found it.

    It used to issue ``PRAGMA journal_mode=WAL`` on a database it does not own,
    which both mutates the file and creates sidecars on the active day.
    """

    from cryodaq.analytics.calibration_fitter import CalibrationFitter

    base = datetime(2026, 9, 2, 12, 0, tzinfo=UTC).timestamp()
    day = tmp_path / "data_2026-09-02.db"
    # Deliberately NOT in WAL: a rotated/idle database sits in delete mode, and
    # the reader must not upgrade it.
    conn = sqlite3.connect(str(day))
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute(
            "CREATE TABLE readings (timestamp REAL, channel TEXT, value REAL, "
            "unit TEXT, status TEXT, instrument_id TEXT DEFAULT 'T')"
        )
        conn.execute("INSERT INTO readings VALUES (?, 'Т1', 295.0, 'K', 'ok', 'T')", (base,))
        conn.commit()
    finally:
        conn.close()

    mode_before = _journal_mode(day)
    sidecars_before = _sidecars(day)
    assert mode_before == "delete"

    CalibrationFitter.extract_pairs(tmp_path, base - 60, base + 60, "Т1", "Т1", raw_channel="Т1_raw")

    assert _journal_mode(day) == mode_before, "the calibration reader changed the journal mode"
    assert _sidecars(day) == sidecars_before, (
        f"the calibration reader left sidecars behind: {_sidecars(day) - sidecars_before}"
    )


# --------------------------------------------------------------------------
# 4. storage/broker_replay.py :: ReplaySource._load_rows
# --------------------------------------------------------------------------
def test_broker_replay_load_rows_still_returns_rows(tmp_path: Path) -> None:
    from cryodaq.storage.broker_replay import ReplaySource

    base = datetime(2026, 9, 2, 12, 0, tzinfo=UTC).timestamp()
    day = tmp_path / "data_2026-09-02.db"
    _make_readings_db(
        day,
        rows=[(base, "T1", 295.0, "K", "ok"), (base + 1, "T2", 77.0, "K", "ok")],
    )

    source = ReplaySource.__new__(ReplaySource)
    rows = source._load_rows(day, start=None, end=None, channels=None)

    assert len(rows) == 2
    assert [row[1] for row in rows] == ["T1", "T2"]


def test_broker_replay_load_rows_leaves_no_sidecars(tmp_path: Path) -> None:
    from cryodaq.storage.broker_replay import ReplaySource

    base = datetime(2026, 9, 2, 12, 0, tzinfo=UTC).timestamp()
    day = tmp_path / "data_2026-09-02.db"
    _make_readings_db(day, rows=[(base, "T1", 295.0, "K", "ok")])
    # Close out WAL so the on-disk state is a bare database file.
    conn = sqlite3.connect(str(day))
    try:
        conn.execute("PRAGMA journal_mode=DELETE")
    finally:
        conn.close()
    sidecars_before = _sidecars(day)

    source = ReplaySource.__new__(ReplaySource)
    source._load_rows(day, start=None, end=None, channels=None)

    assert _sidecars(day) == sidecars_before
