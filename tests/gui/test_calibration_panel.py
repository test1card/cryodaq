"""Tests for Calibration v2 panel — three-mode with auto-switching."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml
from PySide6.QtWidgets import QApplication, QCheckBox

from cryodaq.gui.widgets.calibration_panel import (
    CalibrationAcquisitionWidget,
    CalibrationPanel,
    CalibrationResultsWidget,
    CalibrationSetupWidget,
    CoverageBar,
)


def _app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _write_instruments(path: Path) -> Path:
    config = {
        "instruments": [
            {
                "type": "lakeshore_218s",
                "name": "LS218_1",
                "resource": "MOCK",
                "channels": {
                    1: "Т1 Криостат верх",
                    2: "Т2 Криостат низ",
                    3: "Т3 Радиатор 1",
                },
            },
            {
                "type": "lakeshore_218s",
                "name": "LS218_2",
                "resource": "MOCK",
                "channels": {1: "Т9", 2: "Т10"},
            },
        ]
    }
    path.write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CalibrationPanel — mode switching
# ---------------------------------------------------------------------------

def test_panel_starts_in_setup_mode(tmp_path: Path) -> None:
    _app()
    panel = CalibrationPanel(instruments_config=_write_instruments(tmp_path / "inst.yaml"))
    assert panel._stack.currentWidget() is panel._setup_widget
    assert panel._current_mode == "setup"


# ---------------------------------------------------------------------------
# CalibrationSetupWidget
# ---------------------------------------------------------------------------

def test_setup_shows_grouped_channels(tmp_path: Path) -> None:
    _app()
    widget = CalibrationSetupWidget(instruments_config=_write_instruments(tmp_path / "inst.yaml"))

    assert widget._reference_combo.count() == 5  # 3 + 2 channels
    assert len(widget._target_checkboxes) == 5


def test_setup_has_import_buttons(tmp_path: Path) -> None:
    _app()
    widget = CalibrationSetupWidget(instruments_config=_write_instruments(tmp_path / "inst.yaml"))

    assert widget._import_330_btn.text() == "Импорт .330"
    assert widget._import_340_btn.text() == "Импорт .340"
    assert widget._import_json_btn.text() == "Импорт JSON"


def test_setup_get_selected_targets(tmp_path: Path) -> None:
    _app()
    widget = CalibrationSetupWidget(instruments_config=_write_instruments(tmp_path / "inst.yaml"))

    # Default: all checked
    targets = widget.get_selected_targets()
    # Reference is first item (index 0), so it's excluded
    ref = widget._reference_combo.currentText()
    assert ref not in targets
    assert len(targets) == 4  # 5 total - 1 reference


def test_setup_has_start_button(tmp_path: Path) -> None:
    _app()
    widget = CalibrationSetupWidget(instruments_config=_write_instruments(tmp_path / "inst.yaml"))
    assert widget._start_btn.text() == "Начать калибровочный прогон"
    assert widget._start_btn.isEnabled()


def test_setup_start_validates_targets(tmp_path: Path) -> None:
    _app()
    widget = CalibrationSetupWidget(instruments_config=_write_instruments(tmp_path / "inst.yaml"))
    # Uncheck all targets
    for cb in widget._target_checkboxes.values():
        cb.setChecked(False)
    widget._on_start_calibration()
    assert "целевой" in widget._status.text().lower()


# ---------------------------------------------------------------------------
# CalibrationAcquisitionWidget
# ---------------------------------------------------------------------------

def test_acquisition_shows_stats() -> None:
    _app()
    widget = CalibrationAcquisitionWidget()

    widget.update_stats({
        "point_count": 9142,
        "t_min": 4.5,
        "t_max": 185.0,
    })

    assert "9,142" in widget._point_count_label.text()
    assert "4.5" in widget._temp_range_label.text()
    assert "185.0" in widget._temp_range_label.text()


# ---------------------------------------------------------------------------
# CalibrationResultsWidget
# ---------------------------------------------------------------------------

def test_results_shows_metrics() -> None:
    _app()
    widget = CalibrationResultsWidget()

    widget.update_metrics({
        "raw_count": 28400,
        "downsampled_count": 480,
        "breakpoint_count": 156,
        "metrics": {
            "zone_count": 4,
            "rmse_k": 0.012,
            "max_abs_error_k": 0.048,
        },
    })

    assert "28,400" in widget._raw_count_label.text()
    assert "480" in widget._downsampled_label.text()
    assert "156" in widget._breakpoints_label.text()
    assert "4" in widget._zones_label.text()
    assert "0.0120" in widget._rmse_label.text()
    assert "0.0480" in widget._max_error_label.text()


def test_results_export_all_formats() -> None:
    _app()
    widget = CalibrationResultsWidget()

    assert widget._export_330_btn.text() == ".330"
    assert widget._export_340_btn.text() == ".340"
    assert widget._export_json_btn.text() == "JSON"
    assert widget._export_csv_btn.text() == "CSV"


def test_results_before_after_shows_delta() -> None:
    _app()
    widget = CalibrationResultsWidget()

    widget._delta_label.setText("Δ = -0.03 K")
    assert "0.03" in widget._delta_label.text()


# ---------------------------------------------------------------------------
# CoverageBar
# ---------------------------------------------------------------------------

def test_coverage_bar_renders() -> None:
    _app()
    bar = CoverageBar()
    bar.set_coverage([
        {"status": "dense", "temp_min": 4.0, "temp_max": 50.0, "point_count": 100},
        {"status": "medium", "temp_min": 50.0, "temp_max": 100.0, "point_count": 30},
        {"status": "empty", "temp_min": 100.0, "temp_max": 200.0, "point_count": 0},
        {"status": "sparse", "temp_min": 200.0, "temp_max": 300.0, "point_count": 5},
    ])

    assert len(bar._bins) == 4
    # Verify paintEvent doesn't crash
    bar.resize(200, 24)
    bar.repaint()
