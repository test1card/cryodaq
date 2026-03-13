"""Tests for ExperimentManager — lifecycle, persistence, config snapshot."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from cryodaq.core.experiment import ExperimentManager, ExperimentStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def instruments_yaml(tmp_path: Path) -> Path:
    """Write a minimal instruments.yaml and return its path."""
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
    p = tmp_path / "instruments.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return p


@pytest.fixture()
def manager(tmp_path: Path, instruments_yaml: Path) -> ExperimentManager:
    return ExperimentManager(
        data_dir=tmp_path,
        instruments_config=instruments_yaml,
    )


# ---------------------------------------------------------------------------
# Helper: open today's DB
# ---------------------------------------------------------------------------

def _open_db(data_dir: Path) -> sqlite3.Connection:
    today = datetime.now(timezone.utc).date().isoformat()
    db_path = data_dir / f"data_{today}.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# 1. start_experiment returns an ID and sets active_experiment
# ---------------------------------------------------------------------------

async def test_start_experiment(manager: ExperimentManager) -> None:
    exp_id = manager.start_experiment("Тест охлаждения", "Иванов")

    assert isinstance(exp_id, str)
    assert len(exp_id) > 0
    assert manager.active_experiment is not None
    assert manager.active_experiment.experiment_id == exp_id
    assert manager.active_experiment.name == "Тест охлаждения"
    assert manager.active_experiment.operator == "Иванов"
    assert manager.active_experiment.status == ExperimentStatus.RUNNING


# ---------------------------------------------------------------------------
# 2. stop_experiment sets end_time and COMPLETED status in DB
# ---------------------------------------------------------------------------

async def test_stop_experiment(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment("Измерение", "Петров")
    manager.stop_experiment(exp_id)

    conn = _open_db(tmp_path)
    row = conn.execute(
        "SELECT status, end_time FROM experiments WHERE experiment_id = ?",
        (exp_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["status"] == ExperimentStatus.COMPLETED.value
    assert row["end_time"] is not None


# ---------------------------------------------------------------------------
# 3. After stop, active_experiment is None
# ---------------------------------------------------------------------------

async def test_stop_clears_active(manager: ExperimentManager) -> None:
    exp_id = manager.start_experiment("Тест", "Сидоров")
    assert manager.active_experiment is not None

    manager.stop_experiment(exp_id)

    assert manager.active_experiment is None


# ---------------------------------------------------------------------------
# 4. Starting a second experiment while one is active raises RuntimeError
# ---------------------------------------------------------------------------

async def test_duplicate_start_rejected(manager: ExperimentManager) -> None:
    manager.start_experiment("Первый", "Оператор1")

    with pytest.raises(RuntimeError):
        manager.start_experiment("Второй", "Оператор2")


# ---------------------------------------------------------------------------
# 5. Stopping with no active experiment raises RuntimeError
# ---------------------------------------------------------------------------

async def test_stop_without_active_raises(manager: ExperimentManager) -> None:
    with pytest.raises(RuntimeError):
        manager.stop_experiment()


# ---------------------------------------------------------------------------
# 6. instruments.yaml content is saved as config_snapshot in DB
# ---------------------------------------------------------------------------

async def test_config_snapshot_captured(
    manager: ExperimentManager,
    tmp_path: Path,
    instruments_yaml: Path,
) -> None:
    exp_id = manager.start_experiment("Снимок конфигурации", "Инженер")

    conn = _open_db(tmp_path)
    row = conn.execute(
        "SELECT config_snapshot FROM experiments WHERE experiment_id = ?",
        (exp_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    snapshot = json.loads(row["config_snapshot"])
    # The YAML had an "instruments" key
    assert "instruments" in snapshot
    assert snapshot["instruments"][0]["name"] == "ls218s_1"

    manager.stop_experiment(exp_id)


# ---------------------------------------------------------------------------
# 7. Row appears in the experiments table
# ---------------------------------------------------------------------------

async def test_experiment_persisted_in_sqlite(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    exp_id = manager.start_experiment("Персистентность", "Тестировщик")
    manager.stop_experiment(exp_id)

    conn = _open_db(tmp_path)
    rows = conn.execute(
        "SELECT * FROM experiments WHERE experiment_id = ?", (exp_id,)
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Персистентность"
    assert row["operator"] == "Тестировщик"
    assert row["start_time"] is not None


# ---------------------------------------------------------------------------
# 8. stop with status=ABORTED writes ABORTED in DB
# ---------------------------------------------------------------------------

async def test_abort_status(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment("Аварийный останов", "Оператор")
    manager.stop_experiment(exp_id, status=ExperimentStatus.ABORTED)

    conn = _open_db(tmp_path)
    row = conn.execute(
        "SELECT status FROM experiments WHERE experiment_id = ?", (exp_id,)
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["status"] == ExperimentStatus.ABORTED.value
