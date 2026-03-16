from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from cryodaq.core.experiment import ExperimentManager


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
    (root / "thermal_conductivity.yaml").write_text(
        yaml.dump(
            {
                "id": "thermal_conductivity",
                "name": "Thermal Conductivity",
                "sections": ["setup"],
                "report_enabled": True,
                "report_sections": ["title_page"],
            }
        ),
        encoding="utf-8",
    )
    (root / "cooldown_test.yaml").write_text(
        yaml.dump(
            {
                "id": "cooldown_test",
                "name": "Cooldown Test",
                "sections": ["setup"],
                "report_enabled": True,
                "report_sections": ["title_page"],
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def manager(tmp_path: Path, instruments_yaml: Path, templates_dir: Path) -> ExperimentManager:
    return ExperimentManager(tmp_path, instruments_yaml, templates_dir=templates_dir)


async def test_archive_discovers_experiments(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_a = manager.start_experiment(
        name="Run A",
        title="Run A",
        operator="Ivanov",
        template_id="thermal_conductivity",
        sample="Cu",
        start_time="2026-03-16T10:00:00+00:00",
    )
    manager.finalize_experiment(exp_a, end_time="2026-03-16T11:00:00+00:00")
    exp_b = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Run B",
        operator="Petrov",
        sample="Al",
        start_time="2026-03-15T10:00:00+00:00",
        end_time="2026-03-15T11:00:00+00:00",
    )

    entries = manager.list_archive_entries()

    ids = [entry.experiment_id for entry in entries]
    assert exp_a in ids
    assert exp_b.experiment_id in ids
    assert entries[0].start_time >= entries[-1].start_time


async def test_archive_filters_and_sorts(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_a = manager.start_experiment(
        name="Thermal",
        title="Thermal",
        operator="Ivanov",
        template_id="thermal_conductivity",
        sample="Cu",
        start_time="2026-03-16T10:00:00+00:00",
    )
    manager.finalize_experiment(exp_a, end_time="2026-03-16T11:00:00+00:00")
    exp_b = manager.create_retroactive_experiment(
        template_id="cooldown_test",
        title="Cooldown",
        operator="Petrov",
        sample="Al",
        start_time="2026-03-15T10:00:00+00:00",
        end_time="2026-03-15T11:00:00+00:00",
    )
    report_path = tmp_path / "experiments" / exp_b.experiment_id / "reports"
    report_path.mkdir(parents=True, exist_ok=True)
    (report_path / "report.docx").write_text("dummy", encoding="utf-8")

    entries = manager.list_archive_entries(template_id="cooldown_test", report_present=True)

    assert len(entries) == 1
    assert entries[0].experiment_id == exp_b.experiment_id

    operator_sorted = manager.list_archive_entries(sort_by="operator", descending=False)
    assert [entry.operator for entry in operator_sorted] == ["Ivanov", "Petrov"]


async def test_archive_missing_report_does_not_crash(manager: ExperimentManager) -> None:
    exp_id = manager.start_experiment(
        name="No Report",
        title="No Report",
        operator="Sidorov",
        template_id="thermal_conductivity",
        start_time="2026-03-16T10:00:00+00:00",
    )
    manager.finalize_experiment(exp_id, end_time="2026-03-16T11:00:00+00:00")

    entry = manager.list_archive_entries()[0]
    assert entry.report_present is False
    assert entry.docx_path is None
    assert entry.pdf_path is None


async def test_archive_normalizes_none_text_fields(manager: ExperimentManager) -> None:
    artifact_dir = manager.data_dir / "experiments" / "exp-bad"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "metadata.json").write_text(
        json.dumps(
            {
                "experiment": {
                    "experiment_id": None,
                    "title": None,
                    "template_id": None,
                    "operator": None,
                    "sample": None,
                    "status": None,
                    "start_time": "2026-03-16T10:00:00+00:00",
                    "end_time": None,
                    "notes": None,
                    "report_enabled": True,
                    "retroactive": False,
                },
                "template": {"id": None, "name": None},
            }
        ),
        encoding="utf-8",
    )

    entry = manager.list_archive_entries()[0]

    assert entry.experiment_id == ""
    assert entry.title == ""
    assert entry.template_id == ""
    assert entry.template_name == ""
    assert entry.operator == ""
    assert entry.sample == ""
    assert entry.status == ""
    assert entry.notes == ""
