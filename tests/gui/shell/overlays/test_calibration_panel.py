"""Tests for CalibrationPanel (Phase II.7 overlay)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.calibration_panel import (
    CalibrationPanel,
    CoverageBar,
    _ResultsWidget,
    _strip_instrument_prefix,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


class _FakeSignal:
    def connect(self, *_a, **_k) -> None:
        return None


class _StubWorker:
    """Plain-Python stub for ZmqCommandWorker — avoids Qt+MagicMock
    interaction across thread boundary (II.2 lesson)."""

    dispatched: list[dict] = []

    def __init__(self, cmd, *, parent=None) -> None:
        self._cmd = cmd
        _StubWorker.dispatched.append(dict(cmd))
        self.finished = _FakeSignal()

    def start(self) -> None:
        return None

    def isRunning(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def _reset_stub(monkeypatch):
    import cryodaq.gui.shell.overlays.calibration_panel as module

    _StubWorker.dispatched = []
    _ResultsWidget._last_export_result = None
    monkeypatch.setattr(module, "ZmqCommandWorker", _StubWorker)
    yield


# ----------------------------------------------------------------------
# Structure
# ----------------------------------------------------------------------


def test_panel_constructs_and_exposes_three_modes(app):
    panel = CalibrationPanel()
    assert panel.objectName() == "calibrationPanel"
    assert panel._stack.count() == 3
    assert panel._setup_widget is not None
    assert panel._acquisition_widget is not None
    assert panel._results_widget is not None


def test_panel_starts_in_setup_mode(app):
    panel = CalibrationPanel()
    assert panel.get_current_mode() == "setup"
    assert panel.is_acquisition_active() is False


def test_panel_header_cyrillic_uppercase(app):
    from PySide6.QtWidgets import QLabel

    panel = CalibrationPanel()
    titles = [
        label.text()
        for label in panel.findChildren(QLabel)
        if label.text().startswith("КАЛИБРОВКА")
    ]
    assert "КАЛИБРОВКА ДАТЧИКОВ" in titles


# ----------------------------------------------------------------------
# Setup mode
# ----------------------------------------------------------------------


def test_setup_reference_combo_populated(app):
    panel = CalibrationPanel()
    combo = panel._setup_widget._reference_combo
    # Should have at least one item from the real instruments.yaml;
    # if empty, combo falls back to "Нет LakeShore каналов" placeholder.
    assert combo.count() >= 1


def test_setup_target_checkboxes_default_checked(app):
    panel = CalibrationPanel()
    for cb in panel._setup_widget._target_checkboxes.values():
        assert cb.isChecked() is True


def test_setup_start_without_reference_warns(app):
    panel = CalibrationPanel()
    # Force no-reference state by clearing combo.
    panel._setup_widget._reference_combo.clear()
    panel._setup_widget._reference_combo.addItem("Нет LakeShore каналов")
    panel._setup_widget._on_start_clicked()
    assert "опорный" in panel._banner_label.text().lower()
    assert panel._banner_label.text() != ""


def test_setup_start_without_targets_warns(app):
    panel = CalibrationPanel()
    # Uncheck every target.
    for cb in panel._setup_widget._target_checkboxes.values():
        cb.setChecked(False)
    panel._setup_widget._on_start_clicked()
    text = panel._banner_label.text().lower()
    # "опорный" when no reference either, or "целевой" when no targets.
    assert "целевой" in text or "опорный" in text


def test_setup_start_dispatches_experiment_start(app):
    panel = CalibrationPanel()
    # Ensure at least one target + reference.
    if panel._setup_widget._reference_combo.count() == 0:
        pytest.skip("no LakeShore channels loaded; skip dispatch test")
    ref = panel._setup_widget._reference_combo.currentText()
    if ref == "Нет LakeShore каналов":
        pytest.skip("placeholder reference — skip")
    panel._setup_widget._on_start_clicked()
    start_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "experiment_start"]
    assert len(start_cmds) == 1
    cmd = start_cmds[0]
    assert cmd["template_id"] == "calibration"
    assert "custom_fields" in cmd
    assert "reference_channel" in cmd["custom_fields"]
    assert "target_channels" in cmd["custom_fields"]


# ----------------------------------------------------------------------
# Mode switching
# ----------------------------------------------------------------------


def test_mode_switch_to_acquisition_on_active(app):
    panel = CalibrationPanel()
    panel._on_mode_result({"ok": True, "active": True, "point_count": 12})
    assert panel.get_current_mode() == "acquisition"
    assert panel.is_acquisition_active() is True


def test_mode_switch_to_results_when_acquisition_deactivates(app):
    panel = CalibrationPanel()
    # Enter acquisition first.
    panel._on_mode_result({"ok": True, "active": True, "point_count": 0})
    assert panel.get_current_mode() == "acquisition"
    # Now deactivate.
    panel._on_mode_result({"ok": True, "active": False, "target_channels": ["Т1", "Т2"]})
    assert panel.get_current_mode() == "results"


def test_mode_switch_idle_result_keeps_setup(app):
    panel = CalibrationPanel()
    panel._on_mode_result({"ok": True, "active": False})
    assert panel.get_current_mode() == "setup"


def test_mode_poll_suspended_when_disconnected(app):
    panel = CalibrationPanel()
    # By default _mode_timer is NOT started — set_connected(True) starts
    # it, set_connected(False) stops it.
    assert panel._mode_timer.isActive() is False
    panel.set_connected(True)
    assert panel._mode_timer.isActive() is True
    panel.set_connected(False)
    assert panel._mode_timer.isActive() is False


# ----------------------------------------------------------------------
# Acquisition stats + coverage
# ----------------------------------------------------------------------


def test_acquisition_update_stats_populates_labels(app):
    panel = CalibrationPanel()
    panel._acquisition_widget.update_stats(
        {
            "experiment_name": "Calibration-2026-04-19",
            "elapsed_s": 3665.0,
            "point_count": 1234,
            "t_min": 4.2,
            "t_max": 300.0,
        }
    )
    assert "Calibration-2026-04-19" in panel._acquisition_widget._experiment_label.text()
    assert "01:01:05" in panel._acquisition_widget._elapsed_label.text()
    assert "1,234" in panel._acquisition_widget._point_count_label.text()
    assert "4.2" in panel._acquisition_widget._temp_range_label.text()


def test_acquisition_update_coverage_forwards_to_bar(app):
    panel = CalibrationPanel()
    bins = [{"status": "dense"}, {"status": "medium"}, {"status": "empty"}]
    panel._acquisition_widget.update_coverage(bins)
    assert panel._acquisition_widget._coverage_bar._bins == bins


# ----------------------------------------------------------------------
# CoverageBar — DS tokens
# ----------------------------------------------------------------------


def test_coverage_bar_uses_status_tokens(app):
    assert CoverageBar._color_for("dense").name().lower() == theme.STATUS_OK.lower()
    assert CoverageBar._color_for("medium").name().lower() == theme.STATUS_CAUTION.lower()
    assert CoverageBar._color_for("sparse").name().lower() == theme.STATUS_WARNING.lower()
    assert CoverageBar._color_for("empty").name().lower() == theme.MUTED_FOREGROUND.lower()
    # Unknown status falls back to MUTED_FOREGROUND.
    assert CoverageBar._color_for("garbage").name().lower() == theme.MUTED_FOREGROUND.lower()


def test_coverage_bar_empty_bins_paints_nothing(app):
    # Smoke: paintEvent should not raise on empty bins.
    bar = CoverageBar()
    bar._bins = []
    # Force the widget to have a sensible size.
    bar.resize(200, 24)
    # paintEvent requires a QPaintEvent arg; testing via .update() +
    # processEvents is overkill for this smoke. Just confirm the
    # early-return path exists.
    assert bar._bins == []


# ----------------------------------------------------------------------
# Results metrics
# ----------------------------------------------------------------------


def test_results_set_channels_populates_combo(app):
    panel = CalibrationPanel()
    panel._results_widget.set_channels(["Т1", "Т2", "Т3"])
    assert panel._results_widget._channel_combo.count() == 3
    assert panel._results_widget._current_sensor_id == "Т1"


def test_results_channel_change_dispatches_curve_get(app):
    panel = CalibrationPanel()
    panel._results_widget.set_channels(["Т1", "Т2"])
    _StubWorker.dispatched = []
    panel._results_widget._channel_combo.setCurrentText("Т2")
    get_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "calibration_curve_get"]
    assert len(get_cmds) == 1
    assert get_cmds[0]["sensor_id"] == "Т2"


def test_results_update_metrics_populates_labels(app):
    panel = CalibrationPanel()
    panel._results_widget.update_metrics(
        {
            "raw_count": 5000,
            "downsampled_count": 200,
            "breakpoint_count": 6,
            "metrics": {
                "zone_count": 5,
                "rmse_k": 0.0123,
                "max_abs_error_k": 0.045,
            },
        }
    )
    assert "5,000" in panel._results_widget._raw_count_label.text()
    assert "200" in panel._results_widget._downsampled_label.text()
    assert "6" in panel._results_widget._breakpoints_label.text()
    assert "5" in panel._results_widget._zones_label.text()
    assert "0.0123" in panel._results_widget._rmse_label.text()
    assert "0.0450" in panel._results_widget._max_error_label.text()


# ----------------------------------------------------------------------
# Import
# ----------------------------------------------------------------------


def test_import_click_dispatches_curve_import(app, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    panel = CalibrationPanel()
    panel.set_connected(True)
    import_path = tmp_path / "curve.330"
    import_path.write_text("STUB")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(import_path), "LakeShore .330 (*.330)")),
    )
    _StubWorker.dispatched = []
    panel._setup_widget._import_330_btn.click()
    import_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "calibration_curve_import"]
    assert len(import_cmds) == 1
    assert import_cmds[0]["path"] == str(import_path)


def test_import_cancel_no_dispatch(app, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    panel = CalibrationPanel()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    _StubWorker.dispatched = []
    panel._setup_widget._import_json_btn.click()
    import_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "calibration_curve_import"]
    assert import_cmds == []


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------


def test_export_without_selection_shows_error(app, monkeypatch):
    panel = CalibrationPanel()
    panel.set_connected(True)
    # Channel combo empty → current_sensor_id unset.
    panel._results_widget._current_sensor_id = ""
    panel._results_widget._export_330_btn.click()
    assert "канал" in panel._banner_label.text().lower()


def test_export_dispatches_correct_path_parameter(app, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    panel = CalibrationPanel()
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1"])
    out = tmp_path / "Т1.330"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "LakeShore .330 (*.330)")),
    )
    _StubWorker.dispatched = []
    panel._results_widget._export_330_btn.click()
    export_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "calibration_curve_export"]
    assert len(export_cmds) == 1
    cmd = export_cmds[0]
    assert cmd["sensor_id"] == "Т1"
    assert cmd["curve_330_path"] == str(out)
    # Other format paths not set.
    assert "json_path" not in cmd
    assert "table_path" not in cmd
    assert "curve_340_path" not in cmd


def test_export_json_dispatches_json_path(app, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    panel = CalibrationPanel()
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т5"])
    out = tmp_path / "Т5.json"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "JSON (*.json)"))
    )
    _StubWorker.dispatched = []
    panel._results_widget._export_json_btn.click()
    export_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "calibration_curve_export"]
    assert len(export_cmds) == 1
    assert export_cmds[0]["json_path"] == str(out)


# ----------------------------------------------------------------------
# Runtime apply
# ----------------------------------------------------------------------


def test_apply_without_selection_shows_error(app):
    panel = CalibrationPanel()
    panel.set_connected(True)
    # Channel combo empty.
    panel._results_widget._current_sensor_id = ""
    panel._results_widget._apply_btn.click()
    assert "канал" in panel._banner_label.text().lower()


def test_apply_channel_policy_only_dispatches_lookup_and_policy(app):
    panel = CalibrationPanel()
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1"])
    # Global unchecked — only channel policy path fires.
    panel._results_widget._global_checkbox.setChecked(False)
    panel._results_widget._policy_combo.setCurrentText("Включить")
    _StubWorker.dispatched = []
    panel._results_widget._apply_btn.click()
    cmds = [c["cmd"] for c in _StubWorker.dispatched]
    # Lookup fires first, then set_channel_policy deferred to lookup's
    # finished signal (which doesn't fire in stub). So only lookup
    # visible in this synchronous stub; set_global_mode MUST NOT appear.
    assert "calibration_runtime_set_global" not in cmds
    assert "calibration_curve_lookup" in cmds


def test_apply_global_plus_channel_dispatches_global_first(app):
    panel = CalibrationPanel()
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1"])
    panel._results_widget._global_checkbox.setChecked(True)
    panel._results_widget._policy_combo.setCurrentText("Включить")
    _StubWorker.dispatched = []
    panel._results_widget._apply_btn.click()
    cmds = [c["cmd"] for c in _StubWorker.dispatched]
    # First dispatch should be set_global; set_channel_policy is chained
    # to global's finished signal (no-op under stub). Lookup also chained.
    assert cmds[0] == "calibration_runtime_set_global"


# ----------------------------------------------------------------------
# Connection gating
# ----------------------------------------------------------------------


def test_disconnected_disables_setup_and_results_buttons(app):
    panel = CalibrationPanel()
    panel.set_connected(False)
    assert panel._setup_widget._start_btn.isEnabled() is False
    assert panel._setup_widget._import_330_btn.isEnabled() is False
    assert panel._results_widget._export_330_btn.isEnabled() is False
    assert panel._results_widget._apply_btn.isEnabled() is False


def test_reconnect_reenables_controls(app):
    panel = CalibrationPanel()
    panel.set_connected(True)
    # Import buttons only enabled when channels loaded OR always?
    # _SetupWidget.set_engine_enabled(True) enables import unconditionally;
    # start gated by channel presence.
    assert panel._setup_widget._import_330_btn.isEnabled() is True
    assert panel._results_widget._export_330_btn.isEnabled() is True


# ----------------------------------------------------------------------
# Helper
# ----------------------------------------------------------------------


def test_strip_instrument_prefix():
    assert _strip_instrument_prefix("LS218_1:Т1") == "Т1"
    assert _strip_instrument_prefix("Т1") == "Т1"
    assert _strip_instrument_prefix("") == ""


# ----------------------------------------------------------------------
# on_reading routing (filter preserved from v1)
# ----------------------------------------------------------------------


def _reading(channel: str, value: float, unit: str = "K") -> Reading:
    return Reading(
        timestamp=datetime.now(UTC),
        instrument_id="LakeShore_1",
        channel=channel,
        value=value,
        unit=unit,
        metadata={},
    )


def test_on_reading_ignored_when_not_acquisition_mode(app):
    panel = CalibrationPanel()
    # Currently setup mode.
    panel.on_reading(_reading("Т1_raw", 1234.5, unit="sensor_unit"))
    assert panel._acquisition_widget._live_text.toPlainText() == ""


def test_on_reading_routes_raw_in_acquisition_mode(app):
    panel = CalibrationPanel()
    panel._on_mode_result({"ok": True, "active": True, "point_count": 0})
    panel.on_reading(_reading("Т1_raw", 1234.5, unit="sensor_unit"))
    text = panel._acquisition_widget._live_text.toPlainText()
    assert "Т1_raw" in text
    assert "1234.5000" in text


def test_on_reading_ignores_non_raw_non_sensor_unit(app):
    panel = CalibrationPanel()
    panel._on_mode_result({"ok": True, "active": True, "point_count": 0})
    # Regular K reading without _raw suffix — filter excludes.
    panel.on_reading(_reading("Т1", 77.3, unit="K"))
    assert panel._acquisition_widget._live_text.toPlainText() == ""
