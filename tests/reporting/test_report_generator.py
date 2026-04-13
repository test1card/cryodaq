from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from docx import Document

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
                    "thermal_section",
                    "pressure_section",
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
                    "cooldown_section",
                    "pressure_section",
                    "alarms_section",
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
                "report_sections": ["config_section"],
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
    ts = datetime(2026, 3, 16, 12, 0, tzinfo=UTC)
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


def _doc_text(path: Path) -> str:
    document = Document(path)
    parts = [p.text for p in document.paragraphs if p.text]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)
    return "\n".join(parts)


async def test_report_generation_uses_new_output_names_and_sections(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment(
        name="Lambda",
        title="Lambda",
        operator="Ivanov",
        template_id="thermal_conductivity",
        sample="Cu sample",
        notes="Card note",
        start_time="2026-03-16T12:00:00+00:00",
    )
    await _seed_experiment_data(tmp_path, exp_id)
    manager.attach_run_record(
        experiment_id=exp_id,
        source_tab="autosweep",
        source_module="autosweep_panel",
        run_type="autosweep",
        status="COMPLETED",
        started_at="2026-03-16T12:01:00+00:00",
        finished_at="2026-03-16T12:02:00+00:00",
        source_run_id="autosweep-1",
        parameters={"power_start_w": 0.1},
        result_summary={"point_count": 3},
        artifact_paths=[],
    )
    manager.finalize_experiment(exp_id, end_time="2026-03-16T12:05:00+00:00")

    result = ReportGenerator(tmp_path).generate(exp_id)

    assert result.skipped is False
    assert result.docx_path.name == "report_editable.docx"
    assert (tmp_path / "experiments" / exp_id / "reports" / "report_raw.docx").exists()
    assert "run_timeline_section" in result.sections
    assert "run_parameters_section" in result.sections
    assert "result_tables_section" in result.sections
    assert "conductivity_section" in result.sections
    assert "artifact_manifest_section" in result.sections
    assert "operator_comments_section" in result.sections
    assert "operator_interpretation_section" in result.sections
    assert "operator_photos_section" in result.sections

    text = _doc_text(result.docx_path)
    assert "Ivanov" in text
    assert "Cu sample" in text
    assert "Таймлайн прогонов" in text
    assert "Параметры запусков" in text
    assert "Итоговые результаты и таблицы" in text
    assert "Ключевые артефакты" in text
    assert "Комментарии оператора" in text
    assert "Интерпретация результатов" in text
    assert "Фотографии и внешние изображения" in text


async def test_report_generation_for_cooldown_template_uses_archive_tables(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment(
        name="Cooldown",
        title="Cooldown",
        operator="Petrov",
        template_id="cooldown_test",
        start_time="2026-03-16T12:00:00+00:00",
    )
    await _seed_experiment_data(tmp_path, exp_id)
    manager.finalize_experiment(exp_id, end_time="2026-03-16T12:05:00+00:00")

    result = ReportGenerator(tmp_path).generate(exp_id)

    assert (tmp_path / "experiments" / exp_id / "archive" / "tables" / "measured_values.csv").exists()
    text = _doc_text(result.docx_path)
    assert "Охлаждение" in text
    assert "Алармы" in text
    assert "Таблица измеренных величин" in text


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
    assert result.reason == "Формирование отчёта отключено шаблоном."
    assert result.docx_path.exists() is False


async def test_report_artifact_folder_contains_named_outputs(manager: ExperimentManager, tmp_path: Path) -> None:
    exp_id = manager.start_experiment(
        name="Artifact Check",
        title="Artifact Check",
        operator="Operator",
        template_id="cooldown_test",
        start_time="2026-03-16T12:00:00+00:00",
    )
    await _seed_experiment_data(tmp_path, exp_id)
    manager.finalize_experiment(exp_id, end_time="2026-03-16T12:05:00+00:00")

    result = ReportGenerator(tmp_path).generate(exp_id)
    report_dir = tmp_path / "experiments" / exp_id / "reports"

    assert report_dir.exists()
    assert result.docx_path == report_dir / "report_editable.docx"
    assert result.assets_dir.exists()
    assert (report_dir / "report_raw.docx").exists()


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
    await _seed_experiment_data(tmp_path, exp_id)
    manager.finalize_experiment(exp_id, end_time="2026-03-16T12:05:00+00:00")

    monkeypatch.setattr("cryodaq.reporting.generator.shutil.which", lambda _name: None)
    result = ReportGenerator(tmp_path).generate(exp_id)

    assert result.docx_path.exists()
    assert result.docx_path.name == "report_editable.docx"
    assert result.pdf_path is None


async def test_report_generation_can_use_archived_measured_values_without_live_db(
    manager: ExperimentManager,
    tmp_path: Path,
) -> None:
    exp_id = manager.start_experiment(
        name="Archive source",
        title="Archive source",
        operator="Operator",
        template_id="cooldown_test",
        start_time="2026-03-16T12:00:00+00:00",
    )
    writer = SQLiteWriter(tmp_path)
    ts = datetime(2026, 3, 16, 12, 1, tzinfo=UTC)
    writer._write_batch(
        [
            _reading("K1/smua/power", 1.2, "W", ts),
            _reading("P_MAIN/pressure", 2.1e-4, "mbar", ts),
            _reading("T_STAGE", 4.3, "K", ts),
        ]
    )
    if writer._conn is not None:
        writer._conn.close()
        writer._conn = None
    manager.finalize_experiment(exp_id, end_time="2026-03-16T12:05:00+00:00")

    db_path = tmp_path / "data_2026-03-16.db"
    if db_path.exists():
        db_path.unlink()

    result = ReportGenerator(tmp_path).generate(exp_id)

    assert result.docx_path.exists()
    assert (tmp_path / "experiments" / exp_id / "archive" / "tables" / "measured_values.csv").exists()


def test_service_log_empty_state_is_russian(tmp_path: Path) -> None:
    from cryodaq.reporting.data import ReportDataset
    from cryodaq.reporting.sections import render_operator_log_section

    document = Document()
    dataset = ReportDataset(metadata={"experiment": {}, "template": {}}, operator_log=[])

    render_operator_log_section(document, dataset, tmp_path)

    text = "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text)
    assert "Служебный лог" in text
    assert "Записи служебного лога за интервал эксперимента отсутствуют." in text
