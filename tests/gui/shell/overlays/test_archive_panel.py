"""Tests for ArchivePanel (Phase II.2 overlay)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.archive_panel import (
    ArchivePanel,
    _format_artifacts,
    resolve_docx_path,
    resolve_folder_path,
    resolve_pdf_path,
)


def _wait_until(predicate, *, timeout_s: float = 3.0, tick_ms: int = 20) -> bool:
    """Spin QCoreApplication.processEvents() until predicate() or timeout."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():
            return True
        QCoreApplication.processEvents()
        time.sleep(tick_ms / 1000.0)
    QCoreApplication.processEvents()
    return predicate()


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def _entry(
    *,
    experiment_id: str = "exp-1",
    title: str = "Cooldown run",
    operator: str = "Владимир",
    sample: str = "sample-42",
    template_id: str = "cooldown",
    template_name: str = "Cooldown v2",
    status: str = "completed",
    start_time: str = "2026-04-18T09:12:00+00:00",
    end_time: str = "2026-04-18T15:47:00+00:00",
    notes: str = "",
    pdf_path: str = "",
    docx_path: str = "",
    artifact_dir: str = "",
    report_enabled: bool = True,
    run_record_count: int = 0,
    artifact_count: int = 0,
    result_table_count: int = 0,
    artifact_index: list[dict] | None = None,
) -> dict:
    return {
        "experiment_id": experiment_id,
        "title": title,
        "operator": operator,
        "sample": sample,
        "template_id": template_id,
        "template_name": template_name,
        "status": status,
        "start_time": start_time,
        "end_time": end_time,
        "notes": notes,
        "pdf_path": pdf_path,
        "docx_path": docx_path,
        "artifact_dir": artifact_dir,
        "report_enabled": report_enabled,
        "run_record_count": run_record_count,
        "artifact_count": artifact_count,
        "result_table_count": result_table_count,
        "artifact_index": artifact_index or [],
    }


# ----------------------------------------------------------------------
# Structure
# ----------------------------------------------------------------------


def test_panel_renders_core_surfaces(app):
    panel = ArchivePanel()
    assert panel.objectName() == "archivePanel"
    assert panel._table is not None
    assert panel._summary_label is not None
    assert panel._export_csv_btn is not None
    assert panel._export_hdf5_btn is not None
    assert panel._export_xlsx_btn is not None
    assert panel._export_parquet_btn is not None
    assert panel._refresh_btn is not None
    assert panel._regenerate_btn is not None


def test_panel_header_uses_cyrillic_uppercase(app):
    from PySide6.QtWidgets import QLabel

    panel = ArchivePanel()
    titles = [
        label.text() for label in panel.findChildren(QLabel) if label.text().startswith("АРХИВ")
    ]
    assert "АРХИВ ЭКСПЕРИМЕНТОВ" in titles


def test_table_has_nine_columns_with_cyrillic_headers(app):
    panel = ArchivePanel()
    assert panel._table.columnCount() == 9
    headers = [
        panel._table.horizontalHeaderItem(i).text() for i in range(panel._table.columnCount())
    ]
    assert "Начало" in headers
    assert "Отчёт" in headers
    assert "Данные" in headers


# ----------------------------------------------------------------------
# Filter payload
# ----------------------------------------------------------------------


def test_build_list_payload_includes_filter_fields(app):
    panel = ArchivePanel()
    panel._operator_edit.setText("Владимир")
    panel._sample_edit.setText("sample-42")
    panel._report_combo.setCurrentIndex(1)  # «Есть отчёт» → "true"
    payload = panel._build_list_payload()
    assert payload["cmd"] == "experiment_archive_list"
    assert payload["operator"] == "Владимир"
    assert payload["sample"] == "sample-42"
    assert payload["report_present"] == "true"
    assert "start_date" in payload
    assert "end_date" in payload
    assert payload["sort_by"] == "start_time"
    assert payload["descending"] is True


def test_sort_combo_changes_descending_flag(app):
    panel = ArchivePanel()
    panel._sort_combo.setCurrentIndex(1)  # Сначала старые → ascending
    payload = panel._build_list_payload()
    assert payload["sort_by"] == "start_time"
    assert payload["descending"] is False


def test_report_combo_all_omits_report_present_key(app):
    panel = ArchivePanel()
    panel._report_combo.setCurrentIndex(0)  # «Все»
    payload = panel._build_list_payload()
    assert "report_present" not in payload


def test_sort_combo_operator_alpha(app):
    panel = ArchivePanel()
    panel._sort_combo.setCurrentIndex(2)  # Оператор А-Я
    payload = panel._build_list_payload()
    assert payload["sort_by"] == "operator"
    assert payload["descending"] is False


# ----------------------------------------------------------------------
# Refresh
# ----------------------------------------------------------------------


def test_refresh_result_populates_table(app):
    panel = ArchivePanel()
    panel._on_refresh_result(
        {
            "ok": True,
            "entries": [
                _entry(experiment_id="e1", title="First"),
                _entry(experiment_id="e2", title="Second"),
            ],
        }
    )
    assert panel._table.rowCount() == 2
    assert panel._table.item(0, 2).text() == "First"
    assert panel._table.item(1, 2).text() == "Second"


def test_refresh_result_failure_preserves_entries(app):
    panel = ArchivePanel()
    panel._entries = [_entry(experiment_id="cached")]
    panel._populate_table()
    panel._on_refresh_result({"ok": False, "error": "boom"})
    assert any(e["experiment_id"] == "cached" for e in panel._entries)
    assert "boom" in panel._banner_label.text()


def test_empty_refresh_shows_empty_state_text(app):
    panel = ArchivePanel()
    panel._on_refresh_result({"ok": True, "entries": []})
    assert not panel._empty_state_label.isHidden()
    assert panel._empty_state_label.text() == "Эксперименты по текущему фильтру не найдены"


def test_first_row_selected_after_refresh(app):
    panel = ArchivePanel()
    panel._on_refresh_result(
        {
            "ok": True,
            "entries": [
                _entry(experiment_id="e1", title="First"),
                _entry(experiment_id="e2", title="Second"),
            ],
        }
    )
    selected = panel._selected_entry()
    assert selected is not None
    assert selected["experiment_id"] == "e1"


# ----------------------------------------------------------------------
# Details
# ----------------------------------------------------------------------


def test_selection_updates_details_atomically(app):
    panel = ArchivePanel()
    panel._on_refresh_result(
        {
            "ok": True,
            "entries": [
                _entry(
                    experiment_id="exp-xyz",
                    title="X",
                    operator="Иван",
                    template_name="Template X",
                )
            ],
        }
    )
    assert "exp-xyz" in panel._summary_label.text()
    assert "Template X" in panel._template_label.text()
    assert panel._operator_label.text() == "Иван"


def test_clear_details_when_no_selection(app):
    panel = ArchivePanel()
    panel._clear_details()
    assert panel._summary_label.text() == "Эксперимент не выбран."
    assert not panel._open_folder_btn.isEnabled()
    assert not panel._open_pdf_btn.isEnabled()


def test_format_artifacts_contains_no_emoji_and_uses_ascii_tags(app):
    entry = _entry(
        artifact_index=[
            {
                "role": "experiment_data",
                "summary": {"row_count": 10, "format": "sqlite", "channels": ["Т1"]},
                "path": "/tmp/x.db",
            },
            {"role": "measured_values", "summary": {"rows": 5}},
            {"role": "setpoint_values", "summary": {"rows": 2}},
        ]
    )
    text = _format_artifacts(entry)
    assert "[ДАННЫЕ]" in text
    assert "[ИЗМЕРЕНИЯ]" in text
    assert "[УСТАВКИ]" in text
    assert "📊" not in text
    assert "📋" not in text


def test_resolve_folder_path_returns_none_for_missing(tmp_path: Path, app):
    entry = _entry(artifact_dir=str(tmp_path / "nope"))
    assert resolve_folder_path(entry) is None
    # Existing dir resolves.
    entry_existing = _entry(artifact_dir=str(tmp_path))
    assert resolve_folder_path(entry_existing) == tmp_path


def test_resolve_pdf_path_prefers_primary_then_fallback(tmp_path: Path, app):
    primary = tmp_path / "report_primary.pdf"
    primary.write_bytes(b"%PDF-1.4")
    entry = _entry(pdf_path=str(primary))
    assert resolve_pdf_path(entry) == primary


def test_resolve_docx_path_falls_back_to_artifact_dir(tmp_path: Path, app):
    reports = tmp_path / "reports"
    reports.mkdir()
    docx = reports / "report_editable.docx"
    docx.write_bytes(b"PK")
    entry = _entry(artifact_dir=str(tmp_path), docx_path="")
    assert resolve_docx_path(entry) == docx


# ----------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------


def test_regenerate_requires_selection_and_emits_signal(app):
    panel = ArchivePanel()
    panel._on_refresh_result(
        {"ok": True, "entries": [_entry(experiment_id="exp-1", report_enabled=True)]}
    )
    seen: list[str] = []
    panel.regenerate_requested.connect(seen.append)
    panel.set_connected(True)
    panel._regenerate_btn.click()
    assert seen == ["exp-1"]
    assert not panel._regenerate_btn.isEnabled()


def test_regenerate_blocked_when_report_disabled(app):
    panel = ArchivePanel()
    panel._on_refresh_result(
        {"ok": True, "entries": [_entry(experiment_id="exp-1", report_enabled=False)]}
    )
    panel.set_connected(True)
    # Regenerate button is disabled at the details level.
    assert not panel._regenerate_btn.isEnabled()


def test_regenerate_result_failure_shows_error(app):
    panel = ArchivePanel()
    panel._on_refresh_result({"ok": True, "entries": [_entry(experiment_id="exp-1")]})
    panel.set_connected(True)
    panel._on_regenerate_result({"ok": False, "error": "LibreOffice missing"})
    assert "LibreOffice missing" in panel._banner_label.text()
    assert theme.STATUS_FAULT in panel._banner_label.styleSheet()


# ----------------------------------------------------------------------
# Export — K6 migration
# ----------------------------------------------------------------------


def test_export_csv_click_cancel_no_worker(app, monkeypatch):
    panel = ArchivePanel()
    panel.set_connected(True)
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    seen: list[str] = []
    panel.export_requested.connect(seen.append)
    panel._on_export_csv_clicked()
    # Signal emitted BEFORE dialog per current ordering; either way, no worker started.
    assert seen == ["csv"]
    assert not panel._export_in_flight
    assert panel._export_csv_btn.isEnabled()


def test_export_hdf5_click_cancel_no_worker(app, monkeypatch):
    panel = ArchivePanel()
    panel.set_connected(True)
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))
    panel._on_export_hdf5_clicked()
    assert not panel._export_in_flight


def test_export_xlsx_click_cancel_no_worker(app, monkeypatch):
    panel = ArchivePanel()
    panel.set_connected(True)
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    panel._on_export_xlsx_clicked()
    assert not panel._export_in_flight


def test_export_parquet_click_cancel_no_worker(app, monkeypatch):
    """IV.4 F1: cancelling the Parquet QFileDialog does not spawn a worker."""
    panel = ArchivePanel()
    panel.set_connected(True)
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    seen: list[str] = []
    panel.export_requested.connect(seen.append)
    panel._on_export_parquet_clicked()
    assert seen == ["parquet"]
    assert not panel._export_in_flight
    assert panel._export_parquet_btn.isEnabled()


def test_export_parquet_click_starts_worker(app, monkeypatch, tmp_path):
    """IV.4 F1: picking a path fires up the in-process worker and
    marks the export in flight. The worker itself runs synchronously
    in the monkeypatched runner, so we only observe state transitions."""
    panel = ArchivePanel()
    panel.set_connected(True)
    from PySide6.QtWidgets import QFileDialog

    output = tmp_path / "export.parquet"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(output), "Parquet файлы (*.parquet)")),
    )

    started: list[tuple[str, str]] = []

    def fake_start(self_panel, kind: str, runner, *, unit: str) -> None:
        started.append((kind, unit))

    monkeypatch.setattr(ArchivePanel, "_start_export_worker", fake_start)
    panel._on_export_parquet_clicked()
    assert started == [("parquet", "строк")]


def test_export_parquet_runner_calls_export_helper(app, monkeypatch, tmp_path):
    """The runner closure passed to _start_export_worker invokes the
    parquet_archive helper with the chosen output path and bulk
    [2000, now] range."""
    panel = ArchivePanel()
    panel.set_connected(True)
    from PySide6.QtWidgets import QFileDialog

    output = tmp_path / "export.parquet"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(output), "Parquet файлы (*.parquet)")),
    )

    captured: dict = {}

    def fake_export(*, experiment_id, start_time, end_time, sqlite_root, output_path):
        captured.update(
            experiment_id=experiment_id,
            start_time=start_time,
            end_time=end_time,
            output_path=output_path,
        )

        class _R:
            rows_written = 123

        return _R()

    import cryodaq.storage.parquet_archive as pa_mod

    monkeypatch.setattr(pa_mod, "export_experiment_readings_to_parquet", fake_export)

    captured_runner: list = []

    def capture_runner(self_panel, kind: str, runner, *, unit: str) -> None:
        captured_runner.append((kind, runner, unit))

    monkeypatch.setattr(ArchivePanel, "_start_export_worker", capture_runner)
    panel._on_export_parquet_clicked()
    assert captured_runner
    _, runner, _ = captured_runner[0]
    rows = runner()
    assert rows == 123
    assert captured["experiment_id"] == "bulk_export"
    assert captured["output_path"] == output
    assert captured["start_time"].year == 2000
    # end_time is "now" within a few seconds.
    from datetime import UTC, datetime

    assert (datetime.now(UTC) - captured["end_time"]).total_seconds() < 5.0


def test_export_in_flight_disables_all_export_buttons(app):
    panel = ArchivePanel()
    panel.set_connected(True)
    assert panel._export_csv_btn.isEnabled()
    panel._export_in_flight = True
    panel._update_control_enablement()
    assert not panel._export_csv_btn.isEnabled()
    assert not panel._export_hdf5_btn.isEnabled()
    assert not panel._export_xlsx_btn.isEnabled()
    assert not panel._export_parquet_btn.isEnabled()
    panel._export_in_flight = False
    panel._update_control_enablement()
    assert panel._export_csv_btn.isEnabled()
    assert panel._export_parquet_btn.isEnabled()


# ----------------------------------------------------------------------
# Connection gating
# ----------------------------------------------------------------------


def test_disconnected_disables_refresh_regenerate_export(app):
    panel = ArchivePanel()
    panel._on_refresh_result({"ok": True, "entries": [_entry(experiment_id="exp-1")]})
    panel.set_connected(False)
    assert not panel._refresh_btn.isEnabled()
    assert not panel._regenerate_btn.isEnabled()
    assert not panel._export_csv_btn.isEnabled()
    assert not panel._export_hdf5_btn.isEnabled()
    assert not panel._export_xlsx_btn.isEnabled()
    assert not panel._export_parquet_btn.isEnabled()


def test_reconnect_reenables_controls(app):
    panel = ArchivePanel()
    panel._on_refresh_result(
        {"ok": True, "entries": [_entry(experiment_id="exp-1", report_enabled=True)]}
    )
    panel.set_connected(False)
    panel.set_connected(True)
    assert panel._refresh_btn.isEnabled()
    assert panel._regenerate_btn.isEnabled()
    assert panel._export_csv_btn.isEnabled()


# ----------------------------------------------------------------------
# on_reading edge cases
# ----------------------------------------------------------------------


def test_on_reading_is_contract_no_op(app):
    from datetime import UTC, datetime

    panel = ArchivePanel()
    # Any channel — overlay does not subscribe to broker events for auto-refresh.
    panel.on_reading(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="x",
            channel="analytics/experiment_finalized",
            value=0.0,
            unit="",
            metadata={},
        )
    )
    # No crash, no state mutation.
    assert panel._entries == []


def test_on_reading_ignores_malformed_channels(app):
    from datetime import UTC, datetime

    panel = ArchivePanel()
    panel.on_reading(
        Reading(
            timestamp=datetime.now(UTC),
            instrument_id="x",
            channel="garbage",
            value=0.0,
            unit="",
            metadata={},
        )
    )


# ----------------------------------------------------------------------
# Cold-start / refresh deferral (II.2 post-review HIGH fix)
# ----------------------------------------------------------------------


def test_init_does_not_fire_refresh_worker(app, monkeypatch):
    """On construction the overlay must NOT spawn any ZmqCommandWorker.
    That fires before MainWindowV2 can replay connection state.
    """
    import cryodaq.gui.shell.overlays.archive_panel as module

    sentinel: list = []

    class _StubWorker:
        def __init__(self, *a, **kw) -> None:
            sentinel.append((a, kw))
            self.finished = MagicMock()

        def start(self) -> None:
            sentinel.append("started")

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    panel = ArchivePanel()
    assert sentinel == []  # No worker constructed, no start() call.
    assert panel._entries == []


def test_first_connect_triggers_refresh_when_empty(app, monkeypatch):
    import cryodaq.gui.shell.overlays.archive_panel as module

    started: list = []

    class _StubWorker:
        def __init__(self, *a, **kw) -> None:
            self._a = a
            self.finished = MagicMock()

        def start(self) -> None:
            started.append(self._a)

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    panel = ArchivePanel()
    panel.set_connected(True)
    assert len(started) == 1


# ----------------------------------------------------------------------
# Refresh in-flight gating (II.2 post-review fix #2 — MEDIUM)
# ----------------------------------------------------------------------


def test_refresh_archive_suppresses_duplicate_while_in_flight(app, monkeypatch):
    """Calling refresh_archive() twice before the first result returns
    must spawn exactly one worker. Second call is a no-op until the
    first result clears the in-flight flag.
    """
    import cryodaq.gui.shell.overlays.archive_panel as module

    started: list = []

    class _StubWorker:
        def __init__(self, *a, **kw) -> None:
            self.finished = MagicMock()

        def start(self) -> None:
            started.append(True)

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    panel = ArchivePanel()
    panel.set_connected(True)
    assert len(started) == 1  # cold-start deferred refresh
    assert panel._refresh_in_flight is True
    # Duplicate — should be a no-op.
    panel.refresh_archive()
    assert len(started) == 1
    # Simulate result — flag clears.
    panel._on_refresh_result({"ok": True, "entries": [_entry(experiment_id="e1")]})
    assert panel._refresh_in_flight is False
    # Now manual refresh spawns a new worker.
    panel.refresh_archive()
    assert len(started) == 2


def test_reconnect_flap_no_duplicate_refresh(app, monkeypatch):
    """A rapid disconnect → reconnect while the first refresh is still
    in flight must NOT enqueue a second worker. set_connected() guard
    checks _refresh_in_flight defensively.
    """
    import cryodaq.gui.shell.overlays.archive_panel as module

    started: list = []

    class _StubWorker:
        def __init__(self, *a, **kw) -> None:
            self.finished = MagicMock()

        def start(self) -> None:
            started.append(True)

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    panel = ArchivePanel()
    panel.set_connected(True)  # worker #1
    assert len(started) == 1
    assert panel._refresh_in_flight is True
    # Flap: disconnect then reconnect while result is still pending.
    panel.set_connected(False)
    panel.set_connected(True)
    # No duplicate — flag still set.
    assert len(started) == 1


def test_refresh_failure_clears_in_flight_flag(app, monkeypatch):
    """Failure result must clear the in-flight flag so the operator can
    retry. Flag-not-cleared would leave the overlay permanently locked
    out of future refreshes after one transient engine error.
    """
    import cryodaq.gui.shell.overlays.archive_panel as module

    started: list = []

    class _StubWorker:
        def __init__(self, *a, **kw) -> None:
            self.finished = MagicMock()

        def start(self) -> None:
            started.append(True)

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    panel = ArchivePanel()
    panel.set_connected(True)
    assert len(started) == 1
    assert panel._refresh_in_flight is True
    # Simulate engine failure.
    panel._on_refresh_result({"ok": False, "error": "engine timeout"})
    assert panel._refresh_in_flight is False
    # Retry works.
    panel.refresh_archive()
    assert len(started) == 2


def test_repeat_connect_does_not_refetch_when_entries_present(app, monkeypatch):
    import cryodaq.gui.shell.overlays.archive_panel as module

    started: list = []

    class _StubWorker:
        def __init__(self, *a, **kw) -> None:
            self._a = a
            self.finished = MagicMock()

        def start(self) -> None:
            started.append(self._a)

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    panel = ArchivePanel()
    panel._entries = [_entry(experiment_id="cached")]
    panel.set_connected(True)
    # Entries already present → no auto-refresh.
    assert started == []


# ----------------------------------------------------------------------
# Export happy-path / failure-path / thread retention (II.2 MEDIUM fix)
# ----------------------------------------------------------------------


class _StubCSVExporter:
    """Plain-Python stand-in for CSVExporter. Avoids PySide/QThread +
    MagicMock interaction that crashed in the initial attempt."""

    _next_result: int | Exception = 0
    calls: list[tuple] = []

    def __init__(self, data_dir=None, **kwargs) -> None:
        self.data_dir = data_dir

    def export(self, output_path, **kwargs) -> int:
        _StubCSVExporter.calls.append((output_path, kwargs))
        result = _StubCSVExporter._next_result
        if isinstance(result, Exception):
            raise result
        return int(result)


class _StubHDF5Exporter:
    _next_result: int | Exception = 0
    calls: list[tuple] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def export(self, db_file, out) -> int:
        _StubHDF5Exporter.calls.append((db_file, out))
        result = _StubHDF5Exporter._next_result
        if isinstance(result, Exception):
            raise result
        return int(result)


class _StubXLSXExporter:
    _next_result: int | Exception = 0
    calls: list[tuple] = []

    def __init__(self, data_dir) -> None:
        self.data_dir = data_dir

    def export(self, output_path) -> int:
        _StubXLSXExporter.calls.append((output_path,))
        result = _StubXLSXExporter._next_result
        if isinstance(result, Exception):
            raise result
        return int(result)


@pytest.fixture
def reset_stub_state():
    _StubCSVExporter.calls = []
    _StubCSVExporter._next_result = 0
    _StubHDF5Exporter.calls = []
    _StubHDF5Exporter._next_result = 0
    _StubXLSXExporter.calls = []
    _StubXLSXExporter._next_result = 0
    yield


def _patch_csv(monkeypatch, tmp_path):
    import cryodaq.paths as paths_module
    import cryodaq.storage.csv_export as csv_module

    monkeypatch.setattr(csv_module, "CSVExporter", _StubCSVExporter)
    monkeypatch.setattr(paths_module, "get_data_dir", lambda: tmp_path)


def _patch_hdf5(monkeypatch, tmp_path):
    import cryodaq.paths as paths_module
    import cryodaq.storage.hdf5_export as hdf5_module

    monkeypatch.setattr(hdf5_module, "HDF5Exporter", _StubHDF5Exporter)
    monkeypatch.setattr(paths_module, "get_data_dir", lambda: tmp_path)


def _patch_xlsx(monkeypatch, tmp_path):
    import cryodaq.paths as paths_module
    import cryodaq.storage.xlsx_export as xlsx_module

    monkeypatch.setattr(xlsx_module, "XLSXExporter", _StubXLSXExporter)
    monkeypatch.setattr(paths_module, "get_data_dir", lambda: tmp_path)


def test_csv_export_happy_path(app, monkeypatch, tmp_path, reset_stub_state):
    panel = ArchivePanel()
    panel.set_connected(True)
    output = tmp_path / "out.csv"

    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(output), "CSV (*.csv)")),
    )
    _StubCSVExporter._next_result = 12345
    _patch_csv(monkeypatch, tmp_path)

    panel._on_export_csv_clicked()
    assert _wait_until(lambda: not panel._export_in_flight)

    assert "12345" in panel._banner_label.text()
    assert "Экспорт CSV завершён" in panel._banner_label.text()
    assert len(_StubCSVExporter.calls) == 1
    assert _StubCSVExporter.calls[0][0] == output
    # Worker list pruned after QThread.finished.
    assert _wait_until(lambda: len(panel._export_workers) == 0)


def test_csv_export_failure(app, monkeypatch, tmp_path, reset_stub_state):
    panel = ArchivePanel()
    panel.set_connected(True)
    output = tmp_path / "out.csv"

    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(output), "CSV (*.csv)")),
    )
    _StubCSVExporter._next_result = OSError("disk full")
    _patch_csv(monkeypatch, tmp_path)

    panel._on_export_csv_clicked()
    assert _wait_until(lambda: not panel._export_in_flight)

    assert "disk full" in panel._banner_label.text()
    assert "Экспорт CSV" in panel._banner_label.text()
    assert theme.STATUS_FAULT in panel._banner_label.styleSheet()


def test_hdf5_export_happy_path(app, monkeypatch, tmp_path, reset_stub_state):
    panel = ArchivePanel()
    panel.set_connected(True)
    # One fake data_*.db so the hdf5 slot iterates once.
    db_file = tmp_path / "data_2026-04-19.db"
    db_file.write_bytes(b"")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *a, **k: str(out_dir)),
    )
    _StubHDF5Exporter._next_result = 777
    _patch_hdf5(monkeypatch, tmp_path)

    panel._on_export_hdf5_clicked()
    assert _wait_until(lambda: not panel._export_in_flight)

    assert "777" in panel._banner_label.text()
    assert "Экспорт HDF5 завершён" in panel._banner_label.text()
    assert len(_StubHDF5Exporter.calls) == 1


def test_xlsx_export_happy_path(app, monkeypatch, tmp_path, reset_stub_state):
    panel = ArchivePanel()
    panel.set_connected(True)
    output = tmp_path / "out.xlsx"

    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(output), "Excel (*.xlsx)")),
    )
    _StubXLSXExporter._next_result = 999
    _patch_xlsx(monkeypatch, tmp_path)

    panel._on_export_xlsx_clicked()
    assert _wait_until(lambda: not panel._export_in_flight)

    assert "999" in panel._banner_label.text()
    assert "Экспорт XLSX завершён" in panel._banner_label.text()
    assert len(_StubXLSXExporter.calls) == 1


def test_export_thread_retained_during_run_then_pruned(
    app, monkeypatch, tmp_path, reset_stub_state
):
    """While the export is running the QThread + worker must be retained
    (otherwise the Python wrapper can be GC'd mid-flight and crash the
    PySide signal path). On completion both lists are pruned.
    """
    panel = ArchivePanel()
    panel.set_connected(True)
    output = tmp_path / "out.csv"

    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(output), "CSV (*.csv)")),
    )

    class _SlowCSVExporter(_StubCSVExporter):
        def export(self, output_path, **kwargs) -> int:
            time.sleep(0.15)
            return 1

    import cryodaq.paths as paths_module
    import cryodaq.storage.csv_export as csv_module

    monkeypatch.setattr(csv_module, "CSVExporter", _SlowCSVExporter)
    monkeypatch.setattr(paths_module, "get_data_dir", lambda: tmp_path)

    panel._on_export_csv_clicked()
    assert len(panel._export_workers) == 1
    assert panel._export_in_flight is True

    assert _wait_until(lambda: not panel._export_in_flight, timeout_s=5.0)
    assert _wait_until(lambda: len(panel._export_workers) == 0)
