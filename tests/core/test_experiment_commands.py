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
