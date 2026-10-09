"""Whole-run companion chart, read from the run's own databases.

The hourly report's chart is a short window: the projection feeding it keeps
only what fits that window, so it cannot show the shape of a cooldown that has
been running for a day. This builder answers that from the archive instead.
"""

import json
import sqlite3
import time
from pathlib import Path

import pytest

from cryodaq.reporting.run_overview import (
    RunOverviewError,
    build_run_overview_png,
    resolve_run_window,
)


def _make_db(path: Path, *, start: float, count: int, channels=("Т1", "Т2")) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE readings (timestamp REAL, instrument_id TEXT, channel TEXT, "
        "value REAL, unit TEXT, status TEXT)"
    )
    rows = []
    for index in range(count):
        for channel in channels:
            rows.append((start + index, "ls218", channel, 300.0 - index * 0.1, "K", "ok"))
    connection.executemany("INSERT INTO readings VALUES (?,?,?,?,?,?)", rows)
    connection.commit()
    connection.close()


def _make_run(tmp_path: Path, *, started_at: float, db_names: list[str]) -> None:
    (tmp_path / "experiment_state.json").write_text(
        json.dumps({"active_experiment_id": "abc123"}), encoding="utf-8"
    )
    experiment_dir = tmp_path / "experiments" / "abc123"
    experiment_dir.mkdir(parents=True)
    (experiment_dir / "metadata.json").write_text(
        json.dumps(
            {
                "experiment": {"title": "Карбид кремния", "start_time": None},
                "data_range": {
                    "start_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started_at)),
                    "daily_db_files": db_names,
                },
            }
        ),
        encoding="utf-8",
    )


def test_resolves_the_run_from_the_experiment_record(tmp_path: Path) -> None:
    started = time.time() - 3600
    _make_db(tmp_path / "data_day1.db", start=started, count=60)
    _make_run(tmp_path, started_at=started, db_names=["data_day1.db"])

    window = resolve_run_window(tmp_path)
    assert window.title == "Карбид кремния"
    assert abs(window.started_at - started) < 60
    assert [p.name for p in window.databases] == ["data_day1.db"]


def test_run_spanning_midnight_uses_every_daily_file(tmp_path: Path) -> None:
    started = time.time() - 7200
    _make_db(tmp_path / "data_2026-08-30.db", start=started, count=30)
    _make_db(tmp_path / "data_2026-08-31.db", start=started + 3600, count=30)
    _make_run(tmp_path, started_at=started, db_names=["data_2026-08-30.db", "data_2026-08-31.db"])

    window = resolve_run_window(tmp_path)
    assert [p.name for p in window.databases] == ["data_2026-08-30.db", "data_2026-08-31.db"]


def test_daily_file_missing_from_the_record_is_still_charted(tmp_path: Path) -> None:
    # A rollover the experiment record has not caught up with must not
    # silently truncate the chart at midnight.
    started = time.time() - 7200
    _make_db(tmp_path / "data_2026-08-30.db", start=started, count=30)
    _make_db(tmp_path / "data_2026-08-31.db", start=started + 3600, count=30)
    _make_run(tmp_path, started_at=started, db_names=["data_2026-08-30.db"])

    window = resolve_run_window(tmp_path)
    assert [p.name for p in window.databases] == ["data_2026-08-30.db", "data_2026-08-31.db"]


def test_no_active_experiment_is_reported_not_charted(tmp_path: Path) -> None:
    (tmp_path / "experiment_state.json").write_text(
        json.dumps({"active_experiment_id": None}), encoding="utf-8"
    )
    with pytest.raises(RunOverviewError):
        resolve_run_window(tmp_path)


def test_renders_the_whole_run(tmp_path: Path) -> None:
    started = time.time() - 3600
    _make_db(tmp_path / "data_day1.db", start=started, count=600)
    _make_run(tmp_path, started_at=started, db_names=["data_day1.db"])

    png, caption = build_run_overview_png(tmp_path)
    assert png.startswith(b"\x89PNG")
    assert "Весь прогон" in caption
    assert "Карбид кремния" in caption


def test_sentinel_rows_are_never_charted(tmp_path: Path) -> None:
    # A non-ok reading carries the instrument sentinel (-8.888e+88), which is
    # finite and would rescale the temperature axis to 1e88.
    started = time.time() - 600
    path = tmp_path / "data_day1.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE readings (timestamp REAL, instrument_id TEXT, channel TEXT, "
        "value REAL, unit TEXT, status TEXT)"
    )
    connection.executemany(
        "INSERT INTO readings VALUES (?,?,?,?,?,?)",
        [(started + i, "ls218", "Т1", 300.0, "K", "ok") for i in range(30)]
        + [(started + i, "ls218", "Т4", -8.888e88, "K", "fault") for i in range(30)],
    )
    connection.commit()
    connection.close()
    _make_run(tmp_path, started_at=started, db_names=["data_day1.db"])

    png, _caption = build_run_overview_png(tmp_path)
    assert png.startswith(b"\x89PNG")


def test_a_run_with_no_data_is_reported_not_charted(tmp_path: Path) -> None:
    started = time.time() - 600
    _make_db(tmp_path / "data_day1.db", start=started, count=0)
    _make_run(tmp_path, started_at=started, db_names=["data_day1.db"])

    with pytest.raises(RunOverviewError):
        build_run_overview_png(tmp_path)
