from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from cryodaq.core.broker import DataBroker, RequiredPublication
from cryodaq.core.experiment import ExperimentManager
from cryodaq.engine import EngineCommandContext, _handle_gui_command, _run_operator_log_command
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


async def test_log_entry_command_uses_authoritative_owned_path_and_settles_publication(
    tmp_path: Path,
    experiment_manager: ExperimentManager,
) -> None:
    writer = SQLiteWriter(tmp_path)
    await writer.start_immediate()
    await writer.initialize_operator_log_idempotency()
    broker = DataBroker()
    queue = await broker.subscribe("operator_log_test", required_publisher=True)
    exp_id = experiment_manager.start_experiment("Cooldown", "Petrov")
    request_id = "a" * 32
    context = EngineCommandContext(
        safety_manager=None,
        event_logger=MagicMock(),
        sink_registry=SimpleNamespace(sinks=[]),
        interlock_engine=None,
        leak_rate_estimator=None,
        leak_cfg={},
        alarm_v2_state_mgr=None,
        alarm_ring=None,
        broker=broker,
        experiment_manager=experiment_manager,
        calibration_acquisition=MagicMock(),
        event_bus=MagicMock(),
        cooldown_alarm=None,
        vacuum_guard=None,
        alarm_dispatch_tasks=set(),
        calibration_store=None,
        writer=writer,
        drivers_by_name={},
        sensor_diag=None,
        vacuum_trend=None,
        alarm_v2_state_tracker=None,
        multiline_burst_auto_stop_meta={},
        multiline_burst_auto_stop_tasks={},
        mutation_capability_token="test-mutation-token-1",
    )

    async def settle_required_publication() -> RequiredPublication:
        publication = await queue.get()
        try:
            assert type(publication) is RequiredPublication
            publication.claim()
            publication.acknowledge()
            return publication
        finally:
            queue.task_done()

    command = {
        "cmd": "log_entry",
        "request_id": request_id,
        "experiment_id": exp_id,
        "message": "Reached stable pressure",
        "author": "petrov",
        "source": "gui",
        "tags": ["pressure"],
        "protocol_major": 1,
        "mutation_capability": "cryodaq_mutation_v1",
        "capability_token": "test-mutation-token-1",
    }
    publisher = asyncio.create_task(settle_required_publication())
    try:
        result = await _handle_gui_command(command, context=context)
        publication = await publisher
        replay = await _handle_gui_command(command, context=context)
        pending_outbox = await writer.pending_operator_log_publication_outbox()
    finally:
        if not publisher.done():
            publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)
        await writer.stop()

    assert result == replay
    assert result["ok"] is True
    assert result["committed"] is True
    assert result["commit_receipt"] == {
        "schema": "operator_log_commit_v1",
        "request_id": request_id,
        "entry_id": result["entry"]["id"],
        "experiment_id": exp_id,
        "committed": True,
    }
    assert result["entry"]["experiment_id"] == exp_id
    assert result["entry"]["source"] == "gui"
    assert publication.request_id == request_id
    assert len(publication.request_fingerprint) == 64
    assert publication.reading.channel == "analytics/operator_log_entry"
    assert publication.reading.metadata["request_id"] == request_id
    assert publication.reading.metadata["publication_schema"] == "operator_log_commit_v1"
    assert publication.reading.metadata["message"] == "Reached stable pressure"
    assert publication.reading.metadata["experiment_id"] == exp_id
    assert pending_outbox == ()
    assert queue.empty()


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
