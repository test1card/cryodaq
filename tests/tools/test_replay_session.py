"""Tests for tools/replay_session.py SQLite replay."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cryodaq.drivers.base import ChannelStatus
from tools import replay_session


def _seed_db(path: Path, rows: list[tuple[float, str, str, float, str, str]]) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE readings ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "timestamp REAL NOT NULL, "
            "instrument_id TEXT NOT NULL, "
            "channel TEXT NOT NULL, "
            "value REAL NOT NULL, "
            "unit TEXT NOT NULL, "
            "status TEXT NOT NULL)"
        )
        conn.executemany(
            "INSERT INTO readings(timestamp, instrument_id, channel, value, unit, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def _sample_rows() -> list[tuple[float, str, str, float, str, str]]:
    base = 1_700_000_000.0
    return [
        (base + 0.0, "LakeShore_1", "T1", 290.0, "K", "ok"),
        (base + 0.5, "VSP63D_1", "VSP63D_1/pressure", 1e-3, "mbar", "ok"),
        (base + 1.0, "LakeShore_1", "T1", 150.0, "K", "ok"),
        (base + 2.0, "LakeShore_1", "T1", 50.0, "K", "ok"),
        (base + 3.5, "LakeShore_1", "T1", 4.2, "K", "ok"),
    ]


# ----------------------------------------------------------------------
# SQLite schema read
# ----------------------------------------------------------------------


def test_iter_rows_reads_schema_correctly(tmp_path):
    db = tmp_path / "session.db"
    _seed_db(db, _sample_rows())
    items = list(replay_session._iter_rows(db, channels=None, start_offset_s=0.0, duration_s=None))
    assert len(items) == 5
    first_offset, first_reading = items[0]
    assert first_offset == pytest.approx(0.0)
    assert first_reading.channel == "T1"
    assert first_reading.value == 290.0
    assert first_reading.unit == "K"
    assert first_reading.status is ChannelStatus.OK


def test_channels_filter_applied(tmp_path):
    db = tmp_path / "session.db"
    _seed_db(db, _sample_rows())
    items = list(
        replay_session._iter_rows(
            db,
            channels=frozenset({"T1"}),
            start_offset_s=0.0,
            duration_s=None,
        )
    )
    assert {r.channel for _, r in items} == {"T1"}
    assert len(items) == 4


def test_start_offset_skips_early_rows(tmp_path):
    db = tmp_path / "session.db"
    _seed_db(db, _sample_rows())
    items = list(replay_session._iter_rows(db, channels=None, start_offset_s=1.5, duration_s=None))
    # First two rows are at session offsets 0 and 0.5 — skipped.
    # Remaining: offsets 1.0, 2.0, 3.5 — all >= 1.5? Only 2.0 and 3.5.
    assert len(items) == 2
    assert items[0][1].value == 50.0
    assert items[1][1].value == 4.2


def test_duration_caps_window(tmp_path):
    db = tmp_path / "session.db"
    _seed_db(db, _sample_rows())
    # start_offset=1.0 → emit_base = row at t=base+1.0 (offset 0);
    # duration=1.1 → include offsets 0 and 1.0 but stop before 2.5.
    items = list(replay_session._iter_rows(db, channels=None, start_offset_s=1.0, duration_s=1.1))
    assert len(items) == 2
    assert items[0][0] == pytest.approx(0.0)
    assert items[1][0] == pytest.approx(1.0)


def test_invalid_status_falls_back_to_ok(tmp_path):
    db = tmp_path / "session.db"
    rows = [(1_700_000_000.0, "X", "T1", 1.0, "K", "garbage_status_value")]
    _seed_db(db, rows)
    items = list(replay_session._iter_rows(db, channels=None, start_offset_s=0.0, duration_s=None))
    assert len(items) == 1
    assert items[0][1].status is ChannelStatus.OK


# ----------------------------------------------------------------------
# CLI parsing
# ----------------------------------------------------------------------


def test_cli_requires_db():
    with pytest.raises(SystemExit):
        replay_session._parse_args([])


def test_cli_speed_default_and_override():
    args = replay_session._parse_args(["--db", "fake.db"])
    assert args.speed == 10.0
    args = replay_session._parse_args(["--db", "fake.db", "--speed", "100"])
    assert args.speed == 100.0


def test_cli_channels_split():
    parsed = replay_session._parse_channels("T1, T2, VSP63D_1/pressure")
    assert parsed == frozenset({"T1", "T2", "VSP63D_1/pressure"})
    assert replay_session._parse_channels(None) is None
    assert replay_session._parse_channels("") is None


def test_main_nonzero_on_missing_db(tmp_path):
    rc = replay_session.main(["--db", str(tmp_path / "nope.db")])
    assert rc == 1


def test_main_nonzero_on_bad_speed(tmp_path):
    db = tmp_path / "session.db"
    _seed_db(db, _sample_rows())
    rc = replay_session.main(["--db", str(db), "--speed", "0"])
    assert rc == 2


def test_main_dry_run_does_not_bind(tmp_path, capsys):
    db = tmp_path / "session.db"
    _seed_db(db, _sample_rows())
    rc = replay_session.main(["--db", str(db), "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    # Dry-run prints Reading reprs; first sample row's channel appears.
    assert "T1" in out
