"""Report readings survive cold rotation.

Cold rotation (F17) deletes an aged daily SQLite file after copying its rows to
Parquet. Regenerating a report for a >age_days-old experiment must still see
those readings: the extractor has to union hot SQLite + cold Parquet, not scan
hot DBs directly. This pins the fix that routes ``_load_readings`` through
``ArchiveReader.query_rows``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.reporting.data import ReportDataExtractor
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


async def test_load_readings_reads_rotated_cold_day(tmp_path: Path) -> None:
    day = datetime(2026, 4, 14, 12, 0, tzinfo=UTC)
    writer = SQLiteWriter(tmp_path)
    writer._write_batch([_reading("T_STAGE", 4.3, "K", day)])
    await writer.stop()

    archive_dir = tmp_path / "archive"
    service = ColdRotationService(data_dir=tmp_path, archive_dir=archive_dir, age_days=30)
    # "now" is well beyond age_days after the seeded day → the day is eligible
    # and its hot SQLite file is deleted after rotation to Parquet.
    results = await service.run_once(now=datetime(2026, 6, 1, tzinfo=UTC))
    assert results, "old day must have rotated to Parquet"
    assert not (tmp_path / "data_2026-04-14.db").exists(), "rotation must delete the hot DB"

    extractor = ReportDataExtractor(tmp_path)
    readings = extractor._load_readings(
        day.replace(hour=0, minute=0), day.replace(hour=23, minute=59)
    )

    values = [r.value for r in readings]
    assert 4.3 in values, "rotated cold-day reading must still reach the report"
    channels = {r.channel for r in readings}
    assert "T_STAGE" in channels


async def test_load_operator_log_reads_rotated_cold_day(tmp_path: Path) -> None:
    """The operator journal in a report must survive cold rotation too.

    CR-3 archives operator_log to a companion Parquet before the daily SQLite
    file is deleted. Regenerating an old report must union hot SQLite + that
    cold Parquet, preserving the experiment_id / tags filter semantics.
    """
    day = datetime(2026, 4, 14, 12, 0, tzinfo=UTC)
    writer = SQLiteWriter(tmp_path)
    writer._write_batch([_reading("T_STAGE", 4.3, "K", day)])
    writer._write_operator_log_entry(
        timestamp=day,
        experiment_id="exp-42",
        author="operator",
        source="gui",
        message="cooldown started",
        tags=("cooldown",),
    )
    # An entry attributed to a different experiment must be filtered out.
    writer._write_operator_log_entry(
        timestamp=day,
        experiment_id="other-exp",
        author="operator",
        source="gui",
        message="unrelated experiment",
        tags=(),
    )
    # An unattributed (NULL experiment_id) entry must survive the filter.
    writer._write_operator_log_entry(
        timestamp=day,
        experiment_id=None,
        author="system",
        source="engine",
        message="global note",
        tags=(),
    )
    await writer.stop()

    archive_dir = tmp_path / "archive"
    service = ColdRotationService(data_dir=tmp_path, archive_dir=archive_dir, age_days=30)
    results = await service.run_once(now=datetime(2026, 6, 1, tzinfo=UTC))
    assert results, "old day must have rotated to Parquet"
    assert not (tmp_path / "data_2026-04-14.db").exists(), "rotation must delete the hot DB"

    extractor = ReportDataExtractor(tmp_path)
    records = extractor._load_operator_log(
        day.replace(hour=0, minute=0), day.replace(hour=23, minute=59), "exp-42"
    )

    messages = [r.message for r in records]
    assert "cooldown started" in messages, "rotated cold operator_log entry must reach the report"
    assert "global note" in messages, "NULL-experiment entry must pass the filter"
    assert "unrelated experiment" not in messages, "other-experiment entry must be filtered out"
    tagged = next(r for r in records if r.message == "cooldown started")
    assert tagged.tags == ("cooldown",), "tags must JSON-decode to a tuple"
    assert tagged.experiment_id == "exp-42"
