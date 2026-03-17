from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cryodaq.core.experiment import ExperimentManager
from cryodaq.engine import _run_experiment_command


@pytest.fixture()
def instruments_yaml(tmp_path: Path) -> Path:
    path = tmp_path / "instruments.yaml"
    path.write_text(
        yaml.dump({"instruments": [{"name": "k1", "type": "keithley_2604b", "resource": "MOCK"}]}),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def templates_dir(tmp_path: Path) -> Path:
    root = tmp_path / "experiment_templates"
    root.mkdir()
    (root / "cooldown_test.yaml").write_text(
        yaml.dump(
            {
                "id": "cooldown_test",
                "name": "Cooldown Test",
                "sections": ["setup", "cooldown_path"],
                "report_enabled": True,
                "custom_fields": [{"id": "target_temperature", "label": "Target Temperature"}],
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def manager(tmp_path: Path, instruments_yaml: Path, templates_dir: Path) -> ExperimentManager:
    return ExperimentManager(tmp_path, instruments_yaml, templates_dir=templates_dir)


async def test_experiment_templates_command_returns_templates(manager: ExperimentManager) -> None:
    result = await _run_experiment_command("experiment_templates", {}, manager)

    assert result["ok"] is True
    ids = {item["id"] for item in result["templates"]}
    assert {"cooldown_test", "custom"} <= ids


async def test_get_and_set_app_mode_commands(manager: ExperimentManager) -> None:
    current = await _run_experiment_command("get_app_mode", {}, manager)
    assert current == {"ok": True, "app_mode": "experiment"}

    updated = await _run_experiment_command("set_app_mode", {"app_mode": "debug"}, manager)
    assert updated["ok"] is True
    assert updated["app_mode"] == "debug"
    assert updated["active_experiment"] is None


async def test_experiment_start_and_finalize_commands(manager: ExperimentManager) -> None:
    start = await _run_experiment_command(
        "experiment_start",
        {
            "template_id": "cooldown_test",
            "title": "Cooldown 17",
            "operator": "Ivanov",
            "custom_fields": {"target_temperature": "4.2 K"},
        },
        manager,
    )
    assert start["ok"] is True
    assert start["active_experiment"]["template_id"] == "cooldown_test"

    finalize = await _run_experiment_command(
        "experiment_finalize",
        {
            "experiment_id": start["experiment_id"],
            "notes": "Completed cleanly",
            "status": "COMPLETED",
        },
        manager,
    )
    assert finalize["ok"] is True
    assert finalize["experiment"]["notes"] == "Completed cleanly"
    assert finalize["experiment"]["status"] == "COMPLETED"


async def test_experiment_lifecycle_commands(manager: ExperimentManager) -> None:
    create = await _run_experiment_command(
        "experiment_create",
        {
            "template_id": "cooldown_test",
            "title": "Cooldown 18",
            "operator": "Petrov",
            "sample": "Cu-02",
            "description": "Initial",
            "custom_fields": {"target_temperature": "3.8 K"},
        },
        manager,
    )
    assert create["ok"] is True
    experiment_id = create["experiment_id"]
    assert create["app_mode"] == "experiment"

    active = await _run_experiment_command("experiment_get_active", {}, manager)
    assert active["active_experiment"]["experiment_id"] == experiment_id

    updated = await _run_experiment_command(
        "experiment_update",
        {
            "experiment_id": experiment_id,
            "notes": "Stabilized",
        },
        manager,
    )
    assert updated["experiment"]["sample"] == "Cu-02"
    assert updated["experiment"]["description"] == "Initial"
    assert updated["experiment"]["notes"] == "Stabilized"

    with pytest.raises(RuntimeError, match="debug mode"):
        await _run_experiment_command("set_app_mode", {"app_mode": "debug"}, manager)

    finalized = await _run_experiment_command(
        "experiment_finalize",
        {"experiment_id": experiment_id, "status": "COMPLETED"},
        manager,
    )
    assert finalized["ok"] is True
    assert finalized["experiment"]["status"] == "COMPLETED"

    archive_list = await _run_experiment_command("experiment_list_archive", {}, manager)
    assert [entry["experiment_id"] for entry in archive_list["entries"]] == [experiment_id]

    archive_item = await _run_experiment_command(
        "experiment_get_archive_item",
        {"experiment_id": experiment_id},
        manager,
    )
    assert archive_item["entry"]["experiment_id"] == experiment_id


async def test_experiment_abort_command(manager: ExperimentManager) -> None:
    created = await _run_experiment_command(
        "experiment_create",
        {
            "template_id": "cooldown_test",
            "title": "Abort me",
            "operator": "Operator",
        },
        manager,
    )

    aborted = await _run_experiment_command(
        "experiment_abort",
        {"experiment_id": created["experiment_id"], "notes": "Manual abort"},
        manager,
    )
    assert aborted["ok"] is True
    assert aborted["experiment"]["status"] == "ABORTED"
    assert aborted["experiment"]["notes"] == "Manual abort"


async def test_experiment_attach_run_record_persists_metadata(manager: ExperimentManager) -> None:
    created = await _run_experiment_command(
        "experiment_create",
        {
            "template_id": "cooldown_test",
            "title": "Attach run",
            "operator": "Operator",
            "sample": "Cu-07",
        },
        manager,
    )
    attached = await _run_experiment_command(
        "experiment_attach_run_record",
        {
            "source_tab": "autosweep",
            "source_module": "autosweep_panel",
            "run_type": "autosweep",
            "status": "COMPLETED",
            "source_run_id": "sweep-001",
            "started_at": "2026-03-16T12:00:00+00:00",
            "finished_at": "2026-03-16T12:10:00+00:00",
            "parameters": {"power_start_w": 0.1, "power_end_w": 1.0},
            "result_summary": {"point_count": 4},
            "artifact_paths": ["C:/tmp/sweep.csv", "C:/tmp/sweep.png"],
        },
        manager,
    )

    assert attached["ok"] is True
    assert attached["attached"] is True
    record = attached["run_record"]
    assert record["source_tab"] == "autosweep"
    assert record["parameters"]["power_start_w"] == 0.1
    assert record["result_summary"]["point_count"] == 4
    assert record["experiment_context"]["sample"] == "Cu-07"
    assert record["started_at"] == "2026-03-16T12:00:00+00:00"
    assert record["finished_at"] == "2026-03-16T12:10:00+00:00"


async def test_experiment_attach_run_record_skips_in_debug_mode(manager: ExperimentManager) -> None:
    await _run_experiment_command("set_app_mode", {"app_mode": "debug"}, manager)

    attached = await _run_experiment_command(
        "experiment_attach_run_record",
        {
            "source_tab": "autosweep",
            "source_module": "autosweep_panel",
            "run_type": "autosweep",
            "status": "COMPLETED",
            "started_at": "2026-03-16T12:00:00+00:00",
        },
        manager,
    )

    assert attached == {"ok": True, "attached": False, "run_record": None}


async def test_experiment_create_retroactive_command(manager: ExperimentManager) -> None:
    result = await _run_experiment_command(
        "experiment_create_retroactive",
        {
            "template_id": "cooldown_test",
            "title": "Retro cooldown",
            "operator": "Petrov",
            "start_time": "2026-03-14T08:00:00+00:00",
            "end_time": "2026-03-14T10:00:00+00:00",
        },
        manager,
    )

    assert result["ok"] is True
    assert result["experiment"]["retroactive"] is True
    assert result["experiment"]["status"] == "COMPLETED"
