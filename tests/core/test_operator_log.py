from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from cryodaq.core.broker import DataBroker
from cryodaq.core.experiment import ExperimentManager
from cryodaq.engine import _run_operator_log_command
from cryodaq.storage.sqlite_writer import SQLiteWriter


@pytest.fixture()
def instruments_yaml(tmp_path: Path) -> Path:
    cfg = {
        "instruments": [
            {
                "name": "ls218s_1",
                "type": "lakeshore_218s",
                "resource": "GPIB0::12::INSTR",
                "channels": ["CH1", "CH2"],
            }
        ]
    }
    path = tmp_path / "instruments.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return path


@pytest.fixture()
def experiment_manager(tmp_path: Path, instruments_yaml: Path) -> ExperimentManager:
    return ExperimentManager(data_dir=tmp_path, instruments_config=instruments_yaml)


async def test_operator_log_persists_in_sqlite(tmp_path: Path) -> None:
    writer = SQLiteWriter(tmp_path)
    entry = await writer.append_operator_log(
        message="Opened nitrogen valve",
        author="ivanov",
        source="gui",
        experiment_id="exp-001",
        tags=["ops", "nitrogen"],
        timestamp=datetime(2026, 3, 16, 12, 30, tzinfo=UTC),
    )

    db_path = tmp_path / "data_2026-03-16.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT experiment_id, author, source, message, tags FROM operator_log WHERE id = ?",
        (entry.id,),
    ).fetchone()
    conn.close()
    await writer.stop()

    assert row is not None
    assert row["experiment_id"] == "exp-001"
    assert row["author"] == "ivanov"
    assert row["source"] == "gui"
    assert row["message"] == "Opened nitrogen valve"
    assert row["tags"] == '["ops", "nitrogen"]'


async def test_log_entry_command_uses_active_experiment(
    tmp_path: Path,
    experiment_manager: ExperimentManager,
) -> None:
    writer = SQLiteWriter(tmp_path)
    broker = DataBroker()
    queue = await broker.subscribe("operator_log_test")
    exp_id = experiment_manager.start_experiment("Cooldown", "Petrov")

    result = await _run_operator_log_command(
        "log_entry",
        {
            "message": "Reached stable pressure",
            "author": "petrov",
            "source": "gui",
            "tags": ["pressure"],
        },
        writer,
        experiment_manager,
        broker,
    )

    reading = await queue.get()
    await writer.stop()

    assert result["ok"] is True
    assert result["entry"]["experiment_id"] == exp_id
    assert result["entry"]["source"] == "gui"
    assert reading.channel == "analytics/operator_log_entry"
    assert reading.metadata["message"] == "Reached stable pressure"
    assert reading.metadata["experiment_id"] == exp_id


async def test_log_get_filters_by_time_range(tmp_path: Path, experiment_manager: ExperimentManager) -> None:
    writer = SQLiteWriter(tmp_path)
    start_ts = datetime(2026, 3, 16, 8, 0, tzinfo=UTC)
    middle_ts = start_ts + timedelta(hours=1)
    end_ts = start_ts + timedelta(hours=2)

    await writer.append_operator_log(message="before", source="command", timestamp=start_ts)
    await writer.append_operator_log(message="inside", source="command", timestamp=middle_ts)
    await writer.append_operator_log(message="after", source="command", timestamp=end_ts)

    result = await _run_operator_log_command(
        "log_get",
        {
            "start_time": (middle_ts - timedelta(minutes=1)).isoformat(),
            "end_time": (middle_ts + timedelta(minutes=1)).isoformat(),
            "limit": 10,
        },
        writer,
        experiment_manager,
    )
    await writer.stop()

    assert result["ok"] is True
    assert [entry["message"] for entry in result["entries"]] == ["inside"]


async def test_log_get_current_experiment_returns_only_current_entries(
    tmp_path: Path,
    experiment_manager: ExperimentManager,
) -> None:
    writer = SQLiteWriter(tmp_path)
    active_id = experiment_manager.start_experiment("Run A", "Sidorov")
    await writer.append_operator_log(message="current", source="gui", experiment_id=active_id)
    await writer.append_operator_log(message="other", source="gui", experiment_id="exp-old")

    result = await _run_operator_log_command(
        "log_get",
        {"current_experiment": True},
        writer,
        experiment_manager,
    )
    await writer.stop()

    assert result["ok"] is True
    assert [entry["message"] for entry in result["entries"]] == ["current"]
