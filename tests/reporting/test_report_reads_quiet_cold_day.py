"""A day with no operator entries must survive cold rotation as *proven empty*.

PI-00. Rotation deletes the hot SQLite after copying rows to Parquet. For a day
whose ``operator_log`` held zero rows there is no sidecar to write — correctly,
there is nothing to put in it — so the only surviving trace that the journal was
*empty* rather than *lost* is the declaration rotation writes into ``index.json``:
a null path with an explicit zero row count.

The stand has produced exactly this shape three days running (2026-09-04 and
2026-09-05 archived zero operator entries against ~1.3M readings each), and
rotation has not yet fired against them. The sibling suite
``test_report_reads_cold_rotation`` covers only a day that *had* entries, so the
quiet day — the one the stand actually produces — reaches the report path with
no end-to-end coverage at all. That gap is what this module closes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.reporting.data import ReportDataExtractor
from cryodaq.storage.archive_reader import operator_log_declared_absent
from cryodaq.storage.cold_rotation import ColdRotationService
from cryodaq.storage.sqlite_writer import SQLiteWriter


def _reading(channel: str, value: float, unit: str, ts: datetime) -> Reading:
    return Reading(
        timestamp=ts,
        instrument_id="ls218s",
        channel=channel,
        value=value,
        unit=unit,
        status=ChannelStatus.OK,
    )


async def _rotate_quiet_day(tmp_path: Path, day: datetime) -> Path:
    """Archive a day carrying readings and no operator entries at all."""
    writer = SQLiteWriter(tmp_path)
    writer._write_batch([_reading("T_STAGE", 4.3, "K", day)])
    # Deliberately no _write_operator_log_entry call: this is the quiet day.
    await writer.stop()

    archive_dir = tmp_path / "archive"
    service = ColdRotationService(data_dir=tmp_path, archive_dir=archive_dir, age_days=30)
    results = await service.run_once(now=datetime(2026, 6, 1, tzinfo=UTC))
    assert results, "old day must have rotated to Parquet"
    assert not (tmp_path / f"data_{day:%Y-%m-%d}.db").exists(), "rotation must delete the hot DB"
    return archive_dir


async def test_quiet_day_emptiness_is_declared_and_outlives_the_hot_database(tmp_path: Path) -> None:
    """The proof that the journal was empty must survive deleting the SQLite."""
    day = datetime(2026, 4, 14, 12, 0, tzinfo=UTC)
    archive_dir = await _rotate_quiet_day(tmp_path, day)

    index = json.loads((archive_dir / "index.json").read_text(encoding="utf-8"))
    entry = next(e for e in index["files"] if e["original_name"] == "data_2026-04-14.db")

    # Absence must be STATED. An entry carrying no operator_log_* key at all is
    # indistinguishable from an index written before the field existed, and the
    # reader is required to reject that.
    assert operator_log_declared_absent(entry), (
        f"a quiet day must archive an explicit empty declaration, not an absent one — got {entry!r}"
    )
    assert entry["operator_log_path"] is None
    assert entry["operator_log_rows"] == 0

    # No sidecar is written, and none should be: there is nothing to put in it.
    assert not list(archive_dir.rglob("*.operator_log.parquet")), (
        "a day with zero entries must not leave an operator-log artifact"
    )


async def test_report_over_a_quiet_cold_day_builds_instead_of_refusing(tmp_path: Path) -> None:
    """A period containing a rotated quiet day must still produce a report."""
    day = datetime(2026, 4, 14, 12, 0, tzinfo=UTC)
    await _rotate_quiet_day(tmp_path, day)

    extractor = ReportDataExtractor(tmp_path)
    start = day.replace(hour=0, minute=0)
    end = day.replace(hour=23, minute=59)

    # The journal reads as empty — not as an error, and not as unavailable.
    records = extractor._load_operator_log(start, end, "exp-42")
    assert records == [], f"a quiet day must read back as an empty journal, got {records!r}"

    # And the measurements the day *did* carry still reach the report, so the
    # quiet journal does not take the readings down with it.
    readings = extractor._load_readings(start, end)
    assert 4.3 in [r.value for r in readings], "readings of a quiet day must still reach the report"
