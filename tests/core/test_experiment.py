from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from cryodaq.core.experiment import AppMode, ExperimentManager, ExperimentStatus
from cryodaq.drivers.base import ChannelStatus, Reading
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


async def test_app_mode_defaults_to_experiment_and_persists(
    tmp_path: Path,
    instruments_yaml: Path,
    templates_dir: Path,
) -> None:
    manager = ExperimentManager(
        data_dir=tmp_path,
        instruments_config=instruments_yaml,
        templates_dir=templates_dir,
    )

    assert manager.get_app_mode() is AppMode.EXPERIMENT
    manager.set_app_mode("debug")

    reloaded = ExperimentManager(
        data_dir=tmp_path,
        instruments_config=instruments_yaml,
        templates_dir=templates_dir,
    )
    assert reloaded.get_app_mode() is AppMode.DEBUG
    assert reloaded.active_experiment is None


async def test_debug_mode_blocks_experiment_creation(manager: ExperimentManager) -> None:
    manager.set_app_mode("debug")

    with pytest.raises(RuntimeError, match="experiment mode"):
        manager.create_experiment("Lambda run", "Ivanov", template_id="thermal_conductivity")


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


async def test_active_experiment_is_restored_from_persisted_state(
    tmp_path: Path,
    instruments_yaml: Path,
    templates_dir: Path,
) -> None:
    manager = ExperimentManager(
        data_dir=tmp_path,
        instruments_config=instruments_yaml,
        templates_dir=templates_dir,
    )
    exp_id = manager.start_experiment(
        name="Lambda run",
        title="Lambda run",
        operator="Ivanov",
        template_id="thermal_conductivity",
        notes="Initial note",
    )
    manager.update_experiment(exp_id, notes="Updated note", custom_fields={"sample_id": "S-42"})

    reloaded = ExperimentManager(
        data_dir=tmp_path,
        instruments_config=instruments_yaml,
        templates_dir=templates_dir,
    )

    assert reloaded.active_experiment is not None
    assert reloaded.active_experiment.experiment_id == exp_id
    assert reloaded.active_experiment.notes == "Updated note"
    assert reloaded.active_experiment.custom_fields["sample_id"] == "S-42"
    assert reloaded.get_app_mode() is AppMode.EXPERIMENT


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


async def test_update_preserves_existing_fields_after_save(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    exp_id = manager.start_experiment(
        name="Cooldown",
        title="Cooldown",
        operator="Petrov",
        template_id="thermal_conductivity",
        sample="Cu-01",
        description="Original description",
        notes="Original note",
        custom_fields={"sample_id": "S-1"},
    )

    updated = manager.update_experiment(
        exp_id,
        notes="Updated note",
        custom_fields={"heater_geometry": "spiral"},
    )

    assert updated.sample == "Cu-01"
    assert updated.description == "Original description"
    assert updated.notes == "Updated note"
    assert updated.custom_fields == {"sample_id": "S-1", "heater_geometry": "spiral"}

    payload = json.loads((tmp_path / "experiments" / exp_id / "metadata.json").read_text(encoding="utf-8"))
    assert payload["experiment"]["sample"] == "Cu-01"
    assert payload["experiment"]["description"] == "Original description"
    assert payload["experiment"]["notes"] == "Updated note"
    assert payload["experiment"]["custom_fields"]["sample_id"] == "S-1"
    assert payload["experiment"]["custom_fields"]["heater_geometry"] == "spiral"


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


async def test_switch_to_debug_with_active_experiment_is_rejected(manager: ExperimentManager) -> None:
    manager.start_experiment("First", "Operator", template_id="custom")

    with pytest.raises(RuntimeError, match="debug mode"):
        manager.set_app_mode("debug")


async def test_stop_without_active_raises(manager: ExperimentManager) -> None:
    with pytest.raises(RuntimeError):
        manager.finalize_experiment()


async def test_finalize_builds_archive_snapshot_with_tables_plots_and_run_artifacts(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    writer = SQLiteWriter(tmp_path)
    exp_id = manager.start_experiment(
        name="Thermal archive",
        title="Thermal archive",
        operator="Operator",
        template_id="thermal_conductivity",
        sample="Cu-archive",
        start_time="2026-03-16T12:00:00+00:00",
    )
    ts = datetime(2026, 3, 16, 12, 1, tzinfo=timezone.utc)
    writer._write_batch(
        [
            Reading(ts, "k1", "K1/smua/power", 1.5, "W", ChannelStatus.OK),
            Reading(ts, "k1", "P_MAIN/pressure", 2.2e-4, "mbar", ChannelStatus.OK),
            Reading(ts, "k1", "T_STAGE", 4.2, "K", ChannelStatus.OK),
        ]
    )
    sweep_csv = tmp_path / "autosweep_result.csv"
    sweep_csv.write_text(
        "T_avg_K,G_WK,R_KW\n4.2,0.12,8.33\n5.0,0.15,6.67\n",
        encoding="utf-8",
    )
    sweep_png = tmp_path / "autosweep_result.png"
    sweep_png.write_bytes(b"fake-png")
    manager.attach_run_record(
        experiment_id=exp_id,
        source_tab="autosweep",
        source_module="autosweep_panel",
        run_type="autosweep",
        status="COMPLETED",
        started_at="2026-03-16T12:00:00+00:00",
        finished_at="2026-03-16T12:02:00+00:00",
        source_run_id="autosweep-001",
        parameters={"power_start_w": 0.1, "power_end_w": 1.0},
        result_summary={"point_count": 2, "avg_temperature_k": 4.6},
        artifact_paths=[str(sweep_csv), str(sweep_png)],
    )

    manager.finalize_experiment(exp_id, end_time="2026-03-16T12:05:00+00:00")

    archive_root = tmp_path / "experiments" / exp_id / "archive"
    metadata = json.loads((tmp_path / "experiments" / exp_id / "metadata.json").read_text(encoding="utf-8"))
    assert (archive_root / "tables" / "measured_values.csv").exists()
    assert (archive_root / "tables" / "setpoint_values.csv").exists()
    assert (archive_root / "tables" / "run_results.csv").exists()
    assert (archive_root / "tables" / "conductivity_vs_temperature.csv").exists()
    assert (archive_root / "plots" / "temperature_overview.png").exists()
    assert (archive_root / "plots" / "thermal_power.png").exists()
    assert (archive_root / "plots" / "pressure.png").exists()
    assert (archive_root / "plots" / "conductivity_vs_temperature.png").exists()
    assert (archive_root / "summaries" / "summary_metadata.json").exists()
    assert (archive_root / "runs" / "autosweep" / "autosweep-001" / sweep_csv.name).exists()
    assert (archive_root / "runs" / "autosweep" / "autosweep-001" / sweep_png.name).exists()

    result_table_ids = {item["table_id"] for item in metadata["result_tables"]}
    assert {"measured_values", "setpoint_values", "run_results", "conductivity_vs_temperature"} <= result_table_ids
    assert metadata["summary_metadata"]["run_record_count"] == 1
    assert metadata["summary_metadata"]["artifact_count"] >= 8
    assert metadata["summary_metadata"]["conductivity_rows"] == 2
    assert any(item["role"] == "summary_metadata" for item in metadata["artifact_index"])
    assert any(item["category"] == "run_artifact" for item in metadata["artifact_index"])

    stored_record = metadata["run_records"][0]
    assert stored_record["experiment_context"]["sample"] == "Cu-archive"
    assert all(path.startswith(str(archive_root)) for path in stored_record["artifact_paths"])
