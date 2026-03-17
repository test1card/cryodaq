from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cryodaq.gui.widgets.archive_panel import ArchivePanel


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_archive_panel_loads_entries_and_updates_details(monkeypatch, tmp_path: Path) -> None:
    _app()
    folder = tmp_path / "exp-001"
    reports = folder / "reports"
    reports.mkdir(parents=True)
    pdf_path = reports / "report_raw.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    docx_path = reports / "report_editable.docx"
    docx_path.write_text("dummy", encoding="utf-8")

    monkeypatch.setattr(
        "cryodaq.gui.widgets.archive_panel.send_command",
        lambda _payload: {
            "ok": True,
            "entries": [
                {
                    "experiment_id": "exp-001",
                    "title": "Cooldown",
                    "template_id": "cooldown_test",
                    "template_name": "Cooldown Test",
                    "operator": "Ivanov",
                    "sample": "Cu",
                    "status": "COMPLETED",
                    "start_time": "2026-03-16T10:00:00+00:00",
                    "end_time": "2026-03-16T11:00:00+00:00",
                    "artifact_dir": str(folder),
                    "metadata_path": str(folder / "metadata.json"),
                    "docx_path": str(docx_path),
                    "pdf_path": str(pdf_path),
                    "report_enabled": True,
                    "report_present": True,
                    "notes": "archive note",
                    "retroactive": False,
                    "run_record_count": 1,
                    "artifact_count": 3,
                    "result_table_count": 2,
                    "run_records": [
                        {
                            "run_type": "autosweep",
                            "source_tab": "autosweep",
                            "status": "COMPLETED",
                            "started_at": "2026-03-16T10:05:00+00:00",
                            "finished_at": "2026-03-16T10:10:00+00:00",
                            "artifact_paths": [str(folder / "archive" / "runs" / "autosweep.csv")],
                        }
                    ],
                    "artifact_index": [
                        {
                            "category": "plot",
                            "role": "temperature_overview",
                            "path": str(folder / "archive" / "plots" / "temperature_overview.png"),
                        }
                    ],
                    "result_tables": [
                        {
                            "table_id": "measured_values",
                            "row_count": 12,
                            "path": str(folder / "archive" / "tables" / "measured_values.csv"),
                        }
                    ],
                    "summary_metadata": {"measured_value_rows": 12},
                }
            ],
        },
    )

    panel = ArchivePanel()

    assert panel._table.rowCount() == 1
    panel._table.selectRow(0)
    panel._update_details()
    assert "Cooldown" in panel._summary_label.text()
    assert "report_raw.pdf" in panel._report_label.text()
    assert "report_editable.docx" in panel._report_label.text()
    assert panel._artifact_label.text().endswith("exp-001")
    assert panel._notes_view.toPlainText() == "archive note"
    assert "runs=1" in panel._archive_stats_label.text()
    assert "autosweep | autosweep | COMPLETED" in panel._runs_view.toPlainText()
    assert "plot | temperature_overview" in panel._artifacts_view.toPlainText()
    assert "measured_values | rows=12" in panel._results_view.toPlainText()
    assert panel._open_pdf_button.isEnabled() is True
    assert panel._open_docx_button.isEnabled() is True


def test_archive_panel_path_resolution_handles_new_and_legacy_report_names(tmp_path: Path) -> None:
    _app()
    folder = tmp_path / "exp-002"
    reports = folder / "reports"
    reports.mkdir(parents=True)
    (reports / "report_raw.pdf").write_bytes(b"%PDF-1.4")
    (reports / "report_editable.docx").write_text("dummy", encoding="utf-8")
    entry = {"artifact_dir": str(folder), "docx_path": "", "pdf_path": ""}

    assert ArchivePanel.resolve_folder_path(entry) == folder
    assert ArchivePanel.resolve_pdf_path(entry) == reports / "report_raw.pdf"
    assert ArchivePanel.resolve_docx_path(entry) == reports / "report_editable.docx"


def test_archive_panel_empty_state(monkeypatch) -> None:
    _app()
    monkeypatch.setattr(
        "cryodaq.gui.widgets.archive_panel.send_command",
        lambda _payload: {"ok": True, "entries": []},
    )

    panel = ArchivePanel()

    assert panel._table.rowCount() == 0
    assert panel._summary_label.text() == "Эксперименты по текущему фильтру не найдены."
    assert panel._notes_view.toPlainText() == "Выберите эксперимент, чтобы увидеть сведения и артефакты."
    assert panel._runs_view.toPlainText() == "Run records ещё нет."
    assert panel._artifacts_view.toPlainText() == "Артефактов ещё нет."
    assert panel._results_view.toPlainText() == "Result tables ещё нет."
    assert panel._open_folder_button.isEnabled() is False
    assert panel._open_pdf_button.isEnabled() is False
    assert panel._open_docx_button.isEnabled() is False
    assert panel._regenerate_button.isEnabled() is False
    assert panel._status_label.text() == "Эксперименты по текущему фильтру не найдены."


def test_archive_panel_regenerate_report_wiring(monkeypatch, tmp_path: Path) -> None:
    _app()
    folder = tmp_path / "exp-003"
    folder.mkdir()
    calls: list[dict] = []

    entry = {
        "experiment_id": "exp-003",
        "title": "Thermal",
        "template_id": "thermal_conductivity",
        "template_name": "Thermal Conductivity",
        "operator": "Petrov",
        "sample": "Si",
        "status": "COMPLETED",
        "start_time": "2026-03-16T10:00:00+00:00",
        "end_time": "2026-03-16T11:00:00+00:00",
        "artifact_dir": str(folder),
        "metadata_path": str(folder / "metadata.json"),
        "docx_path": "",
        "pdf_path": "",
        "report_enabled": True,
        "report_present": False,
        "notes": "",
        "retroactive": False,
    }

    def _fake_send(payload: dict) -> dict:
        calls.append(dict(payload))
        if payload["cmd"] == "experiment_generate_report":
            return {
                "ok": True,
                "report": {
                    "docx_path": str(folder / "reports" / "report_editable.docx"),
                    "pdf_path": str(folder / "reports" / "report_raw.pdf"),
                    "assets_dir": str(folder / "reports" / "assets"),
                    "sections": ["title_page", "operator_comments_section"],
                    "skipped": False,
                    "reason": "",
                },
            }
        return {"ok": True, "entries": [entry]}

    monkeypatch.setattr("cryodaq.gui.widgets.archive_panel.send_command", _fake_send)
    panel = ArchivePanel()
    panel._table.selectRow(0)

    panel._regenerate_selected_report()

    generate_calls = [payload for payload in calls if payload["cmd"] == "experiment_generate_report"]
    assert len(generate_calls) == 1
    assert generate_calls[0]["experiment_id"] == "exp-003"
    assert "PDF=" in panel._status_label.text()
    assert "DOCX=" in panel._status_label.text()


def test_archive_panel_regenerate_failure_uses_inline_error(monkeypatch, tmp_path: Path) -> None:
    _app()
    folder = tmp_path / "exp-006"
    folder.mkdir()
    warning_calls: list[str] = []
    entry = {
        "experiment_id": "exp-006",
        "title": "Thermal",
        "template_id": "thermal_conductivity",
        "template_name": "Thermal Conductivity",
        "operator": "Petrov",
        "sample": "Si",
        "status": "COMPLETED",
        "start_time": "2026-03-16T10:00:00+00:00",
        "end_time": "2026-03-16T11:00:00+00:00",
        "artifact_dir": str(folder),
        "metadata_path": str(folder / "metadata.json"),
        "docx_path": "",
        "pdf_path": "",
        "report_enabled": True,
        "report_present": False,
        "notes": "",
        "retroactive": False,
    }

    def _fake_send(payload: dict) -> dict:
        if payload["cmd"] == "experiment_generate_report":
            return {"ok": False, "error": "report engine offline"}
        return {"ok": True, "entries": [entry]}

    monkeypatch.setattr("cryodaq.gui.widgets.archive_panel.send_command", _fake_send)
    monkeypatch.setattr(
        "cryodaq.gui.widgets.archive_panel.QMessageBox.warning",
        lambda *_args: warning_calls.append("called"),
    )
    panel = ArchivePanel()
    panel._table.selectRow(0)

    panel._regenerate_selected_report()

    assert panel._status_label.text() == "report engine offline"
    assert warning_calls == []


def test_archive_panel_details_show_missing_report_text(monkeypatch, tmp_path: Path) -> None:
    _app()
    folder = tmp_path / "exp-004"
    folder.mkdir()
    monkeypatch.setattr(
        "cryodaq.gui.widgets.archive_panel.send_command",
        lambda _payload: {
            "ok": True,
            "entries": [
                {
                    "experiment_id": "exp-004",
                    "title": "No Report",
                    "template_id": "custom",
                    "template_name": "Custom",
                    "operator": "Sidorov",
                    "sample": "",
                    "status": "COMPLETED",
                    "start_time": "2026-03-16T10:00:00+00:00",
                    "end_time": "2026-03-16T11:00:00+00:00",
                    "artifact_dir": str(folder),
                    "metadata_path": str(folder / "metadata.json"),
                    "docx_path": "",
                    "pdf_path": "",
                    "report_enabled": True,
                    "report_present": False,
                    "notes": "",
                    "retroactive": False,
                }
            ],
        },
    )

    panel = ArchivePanel()
    panel._table.selectRow(0)
    panel._update_details()

    assert panel._report_label.text() == "Файлы отчёта отсутствуют"
    assert panel._open_pdf_button.isEnabled() is False
    assert panel._open_docx_button.isEnabled() is False


def test_archive_panel_report_disabled_template_updates_details(monkeypatch, tmp_path: Path) -> None:
    _app()
    folder = tmp_path / "exp-005"
    folder.mkdir()
    monkeypatch.setattr(
        "cryodaq.gui.widgets.archive_panel.send_command",
        lambda _payload: {
            "ok": True,
            "entries": [
                {
                    "experiment_id": "exp-005",
                    "title": "Debug",
                    "template_id": "debug_checkout",
                    "template_name": "Debug Checkout",
                    "operator": "Sidorov",
                    "sample": "",
                    "status": "COMPLETED",
                    "start_time": "2026-03-16T10:00:00+00:00",
                    "end_time": "2026-03-16T11:00:00+00:00",
                    "artifact_dir": str(folder),
                    "metadata_path": str(folder / "metadata.json"),
                    "docx_path": "",
                    "pdf_path": "",
                    "report_enabled": False,
                    "report_present": False,
                    "notes": "",
                    "retroactive": False,
                }
            ],
        },
    )

    panel = ArchivePanel()
    panel._table.selectRow(0)
    panel._update_details()

    assert panel._report_label.text() == "Отчёт не предусмотрен шаблоном"
    assert panel._regenerate_button.isEnabled() is False


def test_archive_panel_handles_malformed_entry_fields(monkeypatch) -> None:
    _app()
    monkeypatch.setattr(
        "cryodaq.gui.widgets.archive_panel.send_command",
        lambda _payload: {
            "ok": True,
            "entries": [
                {
                    "experiment_id": None,
                    "title": None,
                    "template_id": None,
                    "template_name": None,
                    "operator": None,
                    "sample": None,
                    "status": None,
                    "start_time": "bad-date",
                    "end_time": None,
                    "artifact_dir": "",
                    "metadata_path": "",
                    "docx_path": "",
                    "pdf_path": "",
                    "report_enabled": True,
                    "report_present": False,
                    "notes": None,
                    "retroactive": False,
                }
            ],
        },
    )

    panel = ArchivePanel()
    panel._table.selectRow(0)
    panel._update_details()

    assert "Идентификатор:" in panel._summary_label.text()
    assert panel._artifact_label.text() == "Папка артефактов не найдена"
    assert panel._report_label.text() == "Файлы отчёта отсутствуют"
    assert panel._notes_view.toPlainText() == "Заметки отсутствуют."
