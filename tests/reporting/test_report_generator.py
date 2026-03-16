from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from cryodaq.core.experiment import ExperimentManager
from cryodaq.drivers.base import ChannelStatus, Reading
from cryodaq.reporting.generator import ReportGenerator
from cryodaq.storage.sqlite_writer import SQLiteWriter


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
                "sections": ["setup", "sample"],
                "report_enabled": True,
                "report_sections": [
                    "title_page",
                    "thermal_section",
                    "pressure_section",
                    "operator_log_section",
                    "config_section",
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "cooldown_test.yaml").write_text(
        yaml.dump(
            {
                "id": "cooldown_test",
                "name": "Cooldown Test",
                "sections": ["setup", "cooldown_path"],
                "report_enabled": True,
                "report_sections": [
                    "title_page",
                    "cooldown_section",
                    "pressure_section",
                    "operator_log_section",
                    "alarms_section",
                    "config_section",
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
                "report_sections": ["title_page", "config_section"],
            }
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def manager(tmp_path: Path, instruments_yaml: Path, templates_dir: Path) -> ExperimentManager:
    return ExperimentManager(tmp_path, instruments_yaml, templates_dir=templates_dir)


def _reading(channel: str, value: float, unit: str, ts: datetime) -> Reading:
    return Reading(
        timestamp=ts,
        instrument_id="k1",
        channel=channel,
        value=value,
        unit=unit,
        status=ChannelStatus.OK,
    )


async def _seed_experiment_data(tmp_path: Path, experiment_id: str) -> None:
    writer = SQLiteWriter(tmp_path)
    ts = datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc)
    writer._write_batch(
        [
            _reading("K1/smua/power", 1.2, "W", ts),
            _reading("K1/smub/power", 0.8, "W", ts),
            _reading("P_MAIN/pressure", 2.1e-4, "mbar", ts),
            _reading("T_STAGE", 4.3, "K", ts),
            _reading("alarm/high_pressure", 1.0, "", ts),
        ]
    )
    await writer.append_operator_log(
        message="Report marker",
        author="ivanov",
        source="gui",
        experiment_id=experiment_id,
        timestamp=ts,
    )
    await writer.stop()


async def test_template_driven_section_selection_for_thermal(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment(
        name="Lambda",
        title="Lambda",
        operator="Ivanov",
        template_id="thermal_conductivity",
        start_time="2026-03-16T12:00:00+00:00",
    )
    manager.finalize_experiment(exp_id, end_time="2026-03-16T12:05:00+00:00")
    await _seed_experiment_data(tmp_path, exp_id)

    result = ReportGenerator(tmp_path).generate(exp_id)

    assert result.skipped is False
    assert result.docx_path.exists()
    assert result.pdf_path is None
    assert result.sections == (
        "title_page",
        "thermal_section",
        "pressure_section",
        "operator_log_section",
        "config_section",
    )
    assert (result.assets_dir / "thermal_power.png").exists()
    assert (result.assets_dir / "pressure.png").exists()


async def test_report_generation_for_cooldown_template(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment(
        name="Cooldown",
        title="Cooldown",
        operator="Petrov",
        template_id="cooldown_test",
        start_time="2026-03-16T12:00:00+00:00",
    )
    manager.finalize_experiment(exp_id, end_time="2026-03-16T12:05:00+00:00")
    await _seed_experiment_data(tmp_path, exp_id)

    result = ReportGenerator(tmp_path).generate(exp_id)

    assert "cooldown_section" in result.sections
    assert "alarms_section" in result.sections
    assert (result.assets_dir / "cooldown_temperature.png").exists()
    assert result.docx_path.name == "report.docx"


async def test_report_disabled_template_is_respected(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment(
        name="Checkout",
        title="Checkout",
        operator="Sidorov",
        template_id="debug_checkout",
        start_time="2026-03-16T12:00:00+00:00",
    )
    manager.finalize_experiment(exp_id, end_time="2026-03-16T12:05:00+00:00")

    result = ReportGenerator(tmp_path).generate(exp_id)

    assert result.skipped is True
    assert result.reason == "report disabled by template"
    assert result.docx_path.exists() is False


async def test_report_artifact_folder_contains_docx_and_assets(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment(
        name="Artifact Check",
        title="Artifact Check",
        operator="Operator",
        template_id="cooldown_test",
        start_time="2026-03-16T12:00:00+00:00",
    )
    manager.finalize_experiment(exp_id, end_time="2026-03-16T12:05:00+00:00")
    await _seed_experiment_data(tmp_path, exp_id)

    result = ReportGenerator(tmp_path).generate(exp_id)
    report_dir = tmp_path / "experiments" / exp_id / "reports"

    assert report_dir.exists()
    assert result.docx_path.parent == report_dir
    assert result.assets_dir.exists()


async def test_report_generation_graceful_without_pdf_tooling(
    manager: ExperimentManager,
    tmp_path: Path,
    monkeypatch,
) -> None:
    exp_id = manager.start_experiment(
        name="No PDF",
        title="No PDF",
        operator="Operator",
        template_id="cooldown_test",
        start_time="2026-03-16T12:00:00+00:00",
    )
    manager.finalize_experiment(exp_id, end_time="2026-03-16T12:05:00+00:00")
    await _seed_experiment_data(tmp_path, exp_id)

    monkeypatch.setattr("cryodaq.reporting.generator.shutil.which", lambda _name: None)
    result = ReportGenerator(tmp_path).generate(exp_id)

    assert result.docx_path.exists()
    assert result.pdf_path is None
