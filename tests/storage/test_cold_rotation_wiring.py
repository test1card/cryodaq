"""Sweep-B wiring tests: ColdRotationService scheduling + ArchiveReader read-threading.

Rotation moves aged daily SQLite files into Parquet cold storage and DELETES the
SQLite. The CSV/XLSX date-range export paths must therefore read cold Parquet for
rotated days, or exports silently go blind over rotated history. These tests pin
that coupling end-to-end: rotate, then export across the rotation boundary and
assert the rotated rows are still visible (and sentinel rows still masked).
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from cryodaq.drivers.base import ChannelStatus, Reading  # noqa: E402
from cryodaq.storage.archive_reader import ArchiveReader  # noqa: E402
from cryodaq.storage.cold_rotation import (  # noqa: E402
    ColdRotationService,
    build_cold_rotation_service,
    normalize_schedule_time,
    seconds_until_next,
)
from cryodaq.storage.csv_export import CSVExporter  # noqa: E402
from cryodaq.storage.sentinel import SENTINEL  # noqa: E402
from cryodaq.storage.sqlite_writer import SQLiteWriter  # noqa: E402
from cryodaq.storage.xlsx_export import XLSXExporter  # noqa: E402

TODAY = datetime(2026, 4, 29, tzinfo=UTC)


def _write_day(data_dir: Path, day: datetime, readings: list[Reading]) -> None:
    """Persist readings for a given day via the real SQLiteWriter."""
    writer = SQLiteWriter(data_dir)
    writer._write_batch(readings)
    if writer._conn is not None:
        writer._conn.close()
    writer._conn = None


def _reading(channel: str, value: float, ts: datetime, status: ChannelStatus) -> Reading:
    return Reading(
        timestamp=ts,
        instrument_id="ls218s",
        channel=channel,
        value=value,
        unit="K",
        status=status,
    )


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------------------
# Part 1 + 3: scheduler config gate (fail-closed strict bool) + schedule timing
# ---------------------------------------------------------------------------


def test_build_service_enabled(tmp_path: Path) -> None:
    """enabled: true → a live service resolved against the configured archive_dir."""
    cfg = {
        "enabled": True,
        "archive_dir": "data/archive",
        "age_days": 30,
        "schedule_time": "03:00",
        "zstd_compression_level": 3,
    }
    svc = build_cold_rotation_service(cfg, data_dir=tmp_path / "data", project_root=tmp_path)
    assert isinstance(svc, ColdRotationService)
    assert svc._age_days == 30
    # archive_dir is resolved relative to project root → tmp_path/data/archive
    assert svc._archive_dir == tmp_path / "data" / "archive"


@pytest.mark.parametrize("flag", [False, None, "true", 1, "yes"])
def test_build_service_disabled_fail_closed(tmp_path: Path, flag: object) -> None:
    """Anything that is not a strict bool True → no service (fail-closed)."""
    cfg = {} if flag is None else {"enabled": flag}
    svc = build_cold_rotation_service(cfg, data_dir=tmp_path / "data", project_root=tmp_path)
    assert svc is None


def test_seconds_until_next_future_same_day() -> None:
    now = datetime(2026, 4, 29, 1, 0, tzinfo=UTC)
    # 03:00 is two hours ahead
    assert seconds_until_next("03:00", now) == pytest.approx(2 * 3600)


def test_seconds_until_next_rolls_to_tomorrow() -> None:
    now = datetime(2026, 4, 29, 5, 0, tzinfo=UTC)
    # 03:00 already passed → next occurrence is +22h
    assert seconds_until_next("03:00", now) == pytest.approx(22 * 3600)


# ---------------------------------------------------------------------------
# Part 4: age_days boundary — fresh files never rotate, old ones do
# ---------------------------------------------------------------------------


def test_age_days_boundary(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"

    old_day = TODAY - timedelta(days=40)
    fresh_day = TODAY - timedelta(days=5)
    _write_day(data_dir, old_day, [_reading("Т1", 77.0, old_day, ChannelStatus.OK)])
    _write_day(data_dir, fresh_day, [_reading("Т1", 78.0, fresh_day, ChannelStatus.OK)])

    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    results = asyncio.run(svc.run_once(now=TODAY))

    assert len(results) == 1
    assert results[0].db_path.name == f"data_{old_day.date().isoformat()}.db"
    # Fresh file untouched.
    assert (data_dir / f"data_{fresh_day.date().isoformat()}.db").exists()


# ---------------------------------------------------------------------------
# Part 4: CSV date-range export spanning a rotated day returns rotated rows
# ---------------------------------------------------------------------------


def test_csv_export_spans_rotated_day(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"

    old_day = TODAY - timedelta(days=40)
    recent_day = TODAY - timedelta(days=1)

    old_ts = old_day.replace(hour=12)
    recent_ts = recent_day.replace(hour=12)
    bad_ts = old_day.replace(hour=13)

    _write_day(
        data_dir,
        old_day,
        [
            _reading("Т1", 70.0, old_ts, ChannelStatus.OK),
            _reading("Т1", float("nan"), bad_ts, ChannelStatus.SENSOR_ERROR),
        ],
    )
    _write_day(data_dir, recent_day, [_reading("Т1", 85.0, recent_ts, ChannelStatus.OK)])

    # Rotate: old day → Parquet + SQLite deleted; recent day stays hot.
    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    asyncio.run(svc.run_once(now=TODAY))
    assert not (data_dir / f"data_{old_day.date().isoformat()}.db").exists()

    out = tmp_path / "spanning.csv"
    count = CSVExporter(data_dir, archive_dir=archive_dir).export(out, start=old_day, end=TODAY)
    rows = _read_csv(out)

    values = {r["channel"]: [] for r in rows}
    for r in rows:
        values.setdefault(r["channel"], []).append(r["value"])

    # 3 rows total: old good + old sentinel + recent good.
    assert count == 3, f"rotated + hot rows must all export, got {count}"
    t1_vals = values["Т1"]
    assert any(v == "" for v in t1_vals), "sentinel row must mask to blank"
    numeric = sorted(float(v) for v in t1_vals if v != "")
    assert numeric == pytest.approx([70.0, 85.0]), "both rotated + hot values must appear"


def test_csv_idempotent_rerun_same_export(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    old_day = TODAY - timedelta(days=40)
    _write_day(data_dir, old_day, [_reading("Т1", 70.0, old_day.replace(hour=12), ChannelStatus.OK)])

    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    first = asyncio.run(svc.run_once(now=TODAY))
    second = asyncio.run(svc.run_once(now=TODAY))
    assert len(first) == 1
    assert second == [], "re-running on an already-rotated day must be a no-op"

    out = tmp_path / "idem.csv"
    count = CSVExporter(data_dir, archive_dir=archive_dir).export(out, start=old_day, end=TODAY)
    assert count == 1, "row must remain visible after idempotent re-run"


def test_xlsx_export_spans_rotated_day(tmp_path: Path) -> None:
    pytest.importorskip("openpyxl")
    import openpyxl

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    old_day = TODAY - timedelta(days=40)
    recent_day = TODAY - timedelta(days=1)
    _write_day(data_dir, old_day, [_reading("Т1", 70.0, old_day.replace(hour=12), ChannelStatus.OK)])
    _write_day(data_dir, recent_day, [_reading("Т2", 85.0, recent_day.replace(hour=12), ChannelStatus.OK)])

    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    asyncio.run(svc.run_once(now=TODAY))

    out = tmp_path / "spanning.xlsx"
    XLSXExporter(data_dir, archive_dir=archive_dir).export(out, start=old_day, end=TODAY)

    ws = openpyxl.load_workbook(out)["Данные"]
    header = [c.value for c in ws[1]]
    assert "Т1" in header, "rotated-day channel missing from XLSX"
    assert "Т2" in header, "hot-day channel missing from XLSX"


def test_disabled_flag_hot_only(tmp_path: Path) -> None:
    """enabled:false → no service; hot exports keep working with no archive."""
    data_dir = tmp_path / "data"
    old_day = TODAY - timedelta(days=40)
    _write_day(data_dir, old_day, [_reading("Т1", 70.0, old_day.replace(hour=12), ChannelStatus.OK)])

    svc = build_cold_rotation_service({"enabled": False}, data_dir=data_dir, project_root=tmp_path)
    assert svc is None
    # SQLite still present (never rotated); export reads it hot-only.
    out = tmp_path / "hot.csv"
    count = CSVExporter(data_dir).export(out, start=old_day, end=TODAY)
    assert count == 1


# ---------------------------------------------------------------------------
# Sentinel doctrine: query_rows masks non-finite at the read boundary
# ---------------------------------------------------------------------------


def test_query_rows_masks_sentinel_from_parquet(tmp_path: Path) -> None:
    import math

    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    old_day = TODAY - timedelta(days=40)
    _write_day(
        data_dir,
        old_day,
        [
            _reading("Т1", 70.0, old_day.replace(hour=12), ChannelStatus.OK),
            _reading("Т1", float("nan"), old_day.replace(hour=13), ChannelStatus.SENSOR_ERROR),
        ],
    )
    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    asyncio.run(svc.run_once(now=TODAY))

    reader = ArchiveReader(data_dir, archive_dir)
    rows = reader.query_rows(old_day, TODAY, None, None)
    vals = [v for _ts, _inst, _ch, v, _u, _s in rows]
    assert SENTINEL not in vals, "raw sentinel leaked out of query_rows"
    assert sum(1 for v in vals if math.isnan(v)) == 1, "sentinel row must present as NaN"
    assert 70.0 in vals, "usable reading must survive"


# ---------------------------------------------------------------------------
# Backdated-write shadowing: a hot DB reappearing for an already-rotated day
# must NOT be silently hidden by the archive (operator-data criterion).
# ---------------------------------------------------------------------------


def test_query_rows_unions_backdated_hot_over_archived_day(tmp_path: Path) -> None:
    """Restored/backdated hot DB for a rotated day must surface, deduped.

    Rotation archives + deletes the hot .db. If an operator later restores or
    backdates a daily DB for that same day, query_rows unions both sources: the
    extra restored row surfaces, and an exact (ts, instrument, channel) duplicate
    collapses to one rather than doubling.
    """
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    old_day = TODAY - timedelta(days=40)
    dup_ts = old_day.replace(hour=12)
    new_ts = old_day.replace(hour=13)
    db_name = f"data_{old_day.date().isoformat()}.db"

    # Seed + rotate → archived, hot .db deleted.
    _write_day(data_dir, old_day, [_reading("Т1", 70.0, dup_ts, ChannelStatus.OK)])
    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    asyncio.run(svc.run_once(now=TODAY))
    assert not (data_dir / db_name).exists(), "rotation must delete the hot DB"

    # Backdated restore for the same day: archived row again + one restored-only row.
    _write_day(
        data_dir,
        old_day,
        [
            _reading("Т1", 70.0, dup_ts, ChannelStatus.OK),  # exact duplicate
            _reading("Т1", 71.5, new_ts, ChannelStatus.OK),  # restored-only
        ],
    )
    assert (data_dir / db_name).exists(), "backdated hot DB now overlaps the archive"

    reader = ArchiveReader(data_dir, archive_dir)
    rows = reader.query_rows(old_day, TODAY, None, None)
    vals = [v for _ts, _inst, _ch, v, _u, _s in rows]
    assert 71.5 in vals, "backdated restored row must not be shadowed by the archive"
    assert vals.count(70.0) == 1, "exact (ts, instrument, channel) duplicate must dedup to one"
    assert len(rows) == 2, f"expected union-deduped 2 rows, got {rows}"


# ---------------------------------------------------------------------------
# F1b: legacy .db.gz ingestion — a daily DB compressed by retention BEFORE the
# rotation guard existed (real lab disks have these) must still be decompressed,
# archived through the normal path, and the .gz deleted.
# ---------------------------------------------------------------------------


def test_cold_rotation_ingests_legacy_gz(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    archive_dir = tmp_path / "archive"
    old_day = TODAY - timedelta(days=41)

    _write_day(data_dir, old_day, [_reading("Т1", 77.0, old_day.replace(hour=12), ChannelStatus.OK)])
    db_path = data_dir / f"data_{old_day.date().isoformat()}.db"
    gz_path = data_dir / (db_path.name + ".gz")
    with db_path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    db_path.unlink()  # legacy state: only the .gz remains on disk

    svc = ColdRotationService(data_dir=data_dir, archive_dir=archive_dir, age_days=30)
    results = asyncio.run(svc.run_once(now=TODAY))

    assert len(results) == 1, "legacy .gz must rotate like a plain .db"
    assert not gz_path.exists(), ".gz must be deleted after archiving"
    assert not (data_dir / f"{db_path.name}.tmp").exists()  # no temp leaks

    idx = json.loads((archive_dir / "index.json").read_text(encoding="utf-8"))
    entry = idx["files"][0]
    assert entry["original_name"] == db_path.name, "index records the canonical .db name"
    assert "source_md5" in entry, "source_md5 (of decompressed db) must be recorded"

    reader = ArchiveReader(data_dir, archive_dir)
    rows = reader.query_rows(old_day, TODAY, None, None)
    vals = [v for _ts, _inst, _ch, v, _u, _s in rows]
    assert 77.0 in vals, "rotated legacy-gz rows must be queryable"


# ---------------------------------------------------------------------------
# Scheduler guard: a malformed schedule_time must fail safe at build time,
# never raise out of the scheduler's out-of-try seconds_until_next call.
# ---------------------------------------------------------------------------


def test_normalize_schedule_time_valid_passthrough() -> None:
    assert normalize_schedule_time("03:00") == "03:00"
    assert normalize_schedule_time("23:59") == "23:59"


@pytest.mark.parametrize("bad", ["oops", "25:00", "3am", "", "12:60"])
def test_normalize_schedule_time_malformed_falls_back(bad: str) -> None:
    """Malformed schedule → fall back to 03:00, never raise, and stay schedulable."""
    resolved = normalize_schedule_time(bad)
    assert resolved == "03:00"
    # The fallback must itself be a valid, schedulable time.
    seconds_until_next(resolved, datetime(2026, 4, 29, tzinfo=UTC))
