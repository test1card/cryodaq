from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from cryodaq.core.experiment import ExperimentManager, ExperimentStatus


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
def templates_dir(tmp_path: Path) -> Path:
    root = tmp_path / "experiment_templates"
    root.mkdir()
    (root / "thermal_conductivity.yaml").write_text(
        yaml.dump(
            {
                "id": "thermal_conductivity",
                "name": "Thermal Conductivity",
                "sections": ["setup", "sample", "operator_log"],
                "report_enabled": True,
                "custom_fields": [
                    {"id": "sample_id", "label": "Sample ID"},
                    {"id": "heater_geometry", "label": "Heater Geometry"},
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "debug_checkout.yaml").write_text(
        yaml.dump(
            {
                "id": "debug_checkout",
                "name": "Debug Checkout",
                "sections": ["setup", "checks"],
                "report_enabled": False,
                "custom_fields": [{"id": "issue_ticket", "label": "Issue Ticket"}],
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def manager(tmp_path: Path, instruments_yaml: Path, templates_dir: Path) -> ExperimentManager:
    return ExperimentManager(
        data_dir=tmp_path,
        instruments_config=instruments_yaml,
        templates_dir=templates_dir,
    )


def _open_db(data_dir: Path, day: str | None = None) -> sqlite3.Connection:
    current_day = day or datetime.now(timezone.utc).date().isoformat()
    conn = sqlite3.connect(str(data_dir / f"data_{current_day}.db"))
    conn.row_factory = sqlite3.Row
    return conn


async def test_templates_load_correctly(manager: ExperimentManager) -> None:
    templates = manager.get_templates()
    ids = {template.template_id for template in templates}

    assert {"thermal_conductivity", "debug_checkout", "custom"} <= ids
    thermal = manager.get_template("thermal_conductivity")
    assert thermal.report_enabled is True
    assert thermal.sections == ("setup", "sample", "operator_log")


async def test_start_experiment_creates_artifact_metadata(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment(
        name="Lambda run",
        title="Lambda run",
        operator="Ivanov",
        template_id="thermal_conductivity",
        sample="Cu-01",
        notes="Start note",
        custom_fields={"sample_id": "S-42"},
    )

    metadata_path = tmp_path / "experiments" / exp_id / "metadata.json"
    assert metadata_path.exists()

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["experiment"]["template_id"] == "thermal_conductivity"
    assert payload["experiment"]["custom_fields"]["sample_id"] == "S-42"
    assert payload["template"]["report_enabled"] is True
    assert payload["artifacts"]["metadata_path"].endswith("metadata.json")


async def test_finalize_persists_metadata_and_sqlite(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment(
        name="Cooldown",
        title="Cooldown",
        operator="Petrov",
        template_id="debug_checkout",
    )
    info = manager.finalize_experiment(
        exp_id,
        status=ExperimentStatus.ABORTED,
        notes="Aborted by operator",
        custom_fields={"issue_ticket": "BUG-17"},
    )

    assert info.status == ExperimentStatus.ABORTED
    assert info.notes == "Aborted by operator"
    assert info.custom_fields["issue_ticket"] == "BUG-17"

    conn = _open_db(tmp_path)
    row = conn.execute(
        "SELECT status, template_id, notes, custom_fields, report_enabled, artifact_dir "
        "FROM experiments WHERE experiment_id = ?",
        (exp_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["status"] == "ABORTED"
    assert row["template_id"] == "debug_checkout"
    assert row["notes"] == "Aborted by operator"
    assert json.loads(row["custom_fields"])["issue_ticket"] == "BUG-17"
    assert row["report_enabled"] == 0
    assert Path(row["artifact_dir"]).name == exp_id


async def test_report_disabled_template_is_stored(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment(
        name="Checkout",
        title="Checkout",
        operator="Sidorov",
        template_id="debug_checkout",
    )
    manager.finalize_experiment(exp_id)

    metadata_path = tmp_path / "experiments" / exp_id / "metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["experiment"]["report_enabled"] is False
    assert payload["template"]["report_enabled"] is False


async def test_retroactive_experiment_creates_completed_artifact(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    info = manager.create_retroactive_experiment(
        template_id="thermal_conductivity",
        title="Retro run",
        operator="Operator",
        start_time="2026-03-15T10:00:00+00:00",
        end_time="2026-03-15T12:00:00+00:00",
        notes="Tagged after acquisition",
        custom_fields={"sample_id": "retro-1"},
    )

    assert info.retroactive is True
    assert info.status == ExperimentStatus.COMPLETED

    conn = _open_db(tmp_path, "2026-03-15")
    row = conn.execute(
        "SELECT retroactive, end_time FROM experiments WHERE experiment_id = ?",
        (info.experiment_id,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row["retroactive"] == 1
    assert row["end_time"] == "2026-03-15T12:00:00+00:00"

    metadata_path = tmp_path / "experiments" / info.experiment_id / "metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["data_range"]["start_time"] == "2026-03-15T10:00:00+00:00"
    assert payload["data_range"]["end_time"] == "2026-03-15T12:00:00+00:00"


async def test_duplicate_start_rejected(manager: ExperimentManager) -> None:
    manager.start_experiment("First", "Operator", template_id="custom")
    with pytest.raises(RuntimeError):
        manager.start_experiment("Second", "Operator", template_id="custom")


async def test_stop_without_active_raises(manager: ExperimentManager) -> None:
    with pytest.raises(RuntimeError):
        manager.finalize_experiment()
