"""Tests for CalibrationPanel (Phase II.7 overlay)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.shell.overlays.calibration_panel import (
    CalibrationPanel,
    CoverageBar,
    _strip_instrument_prefix,
)


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


class _FakeSignal:
    """Emitting fake signal: stores the slot and fires it synchronously on emit()."""

    def __init__(self) -> None:
        self._slot = None

    def connect(self, slot) -> None:
        self._slot = slot

    def emit(self, *args) -> None:
        if self._slot is not None:
            self._slot(*args)


class _StubWorker:
    """Plain-Python stub for ZmqCommandWorker — avoids Qt+MagicMock
    interaction across thread boundary (II.2 lesson).

    ``next_result`` maps cmd strings to the result dict to emit on start().
    When a cmd has an entry, finished.emit(result) fires synchronously so
    chained callbacks (e.g. lookup → set_channel_policy) run in the test.
    """

    dispatched: list[dict] = []
    instances: list[_StubWorker] = []
    next_result: dict[str, dict] = {}  # cmd → result dict

    def __init__(self, cmd, *, parent=None) -> None:
        self._cmd = dict(cmd)
        _StubWorker.dispatched.append(self._cmd)
        _StubWorker.instances.append(self)
        self.finished = _FakeSignal()

    def start(self) -> None:
        result = _StubWorker.next_result.get(self._cmd.get("cmd", ""))
        if result is not None:
            self.finished.emit(result)

    def isRunning(self) -> bool:
        return False


@pytest.fixture(autouse=True)
def _reset_stub(monkeypatch):
    import cryodaq.gui.shell.overlays.calibration_panel as module

    _StubWorker.dispatched = []
    _StubWorker.instances = []
    _StubWorker.next_result = {}
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
    # Default mode is setup: stack shows the setup widget.
    assert panel._stack.currentWidget() is panel._setup_widget
    # Section title rendered inside the setup widget.
    from PySide6.QtWidgets import QLabel

    texts = [lbl.text() for lbl in panel._setup_widget.findChildren(QLabel)]
    assert any("Параметры калибровки" in t for t in texts)
    # Start button present.
    assert panel._setup_widget._start_btn is not None
    assert "Начать" in panel._setup_widget._start_btn.text()


def test_panel_starts_in_setup_mode(app):
    panel = CalibrationPanel()
    assert panel.get_current_mode() == "setup"
    assert panel.is_acquisition_active() is False


def test_panel_header_cyrillic_uppercase(app):
    from PySide6.QtWidgets import QLabel

    panel = CalibrationPanel()
    titles = [label.text() for label in panel.findChildren(QLabel) if label.text().startswith("КАЛИБРОВКА")]
    assert "КАЛИБРОВКА ДАТЧИКОВ" in titles


# ----------------------------------------------------------------------
# Setup mode
# ----------------------------------------------------------------------


def test_setup_reference_combo_populated(app):
    panel = CalibrationPanel()
    combo = panel._setup_widget._reference_combo
    # Real instruments.yaml has LakeShore channels; combo must not be the
    # placeholder-only state.
    items = [combo.itemText(i) for i in range(combo.count())]
    non_placeholder = [t for t in items if t != "Нет LakeShore каналов"]
    assert len(non_placeholder) >= 1, f"Expected real channels, got: {items}"
    # First channel should be from the first instrument group (LS218_1).
    assert non_placeholder[0].startswith("LS218")


def test_setup_target_checkboxes_default_checked(app):
    panel = CalibrationPanel()
    # Must have checkbox keys (from real instruments.yaml).
    assert len(panel._setup_widget._target_checkboxes) >= 1, "No target checkboxes — instruments.yaml not loaded"
    for key, cb in panel._setup_widget._target_checkboxes.items():
        assert cb.isChecked() is True, f"Checkbox {key!r} not checked by default"


def test_setup_start_without_reference_warns(app):
    panel = CalibrationPanel()
    # Connect so the start button is enabled by engine-gate logic.
    panel.set_connected(True)
    # Force no-reference state by swapping combo content.
    panel._setup_widget._reference_combo.clear()
    panel._setup_widget._reference_combo.addItem("Нет LakeShore каналов")
    # Click the rendered button — catches broken button→slot wiring.
    panel._setup_widget._start_btn.click()
    assert "опорный" in panel._banner_label.text().lower()
    assert panel._banner_label.text() != ""


def test_setup_start_without_targets_warns(app):
    panel = CalibrationPanel()
    # Ensure a valid reference exists so only the target check fires.
    if not panel._setup_widget._all_channels:
        pytest.skip("no LakeShore channels in instruments.yaml")
    # Connect so the start button is enabled.
    panel.set_connected(True)
    panel._setup_widget._reference_combo.setCurrentIndex(0)
    # Uncheck every target.
    for cb in panel._setup_widget._target_checkboxes.values():
        cb.setChecked(False)
    panel._setup_widget._start_btn.click()
    text = panel._banner_label.text().lower()
    assert "целевой" in text, f"Expected target warning, got: {text!r}"


def test_setup_start_dispatches_experiment_start(app):
    panel = CalibrationPanel()
    # Real instruments.yaml is present — no skip needed.
    if not panel._setup_widget._all_channels:
        pytest.skip("no LakeShore channels in instruments.yaml")
    # Ensure at least one target checked (default state).
    ref = panel._setup_widget._reference_combo.currentText()
    assert ref != "Нет LakeShore каналов"
    # Enable the start button (requires connected state).
    panel.set_connected(True)
    panel._setup_widget._start_btn.click()
    start_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "experiment_start"]
    assert len(start_cmds) == 1
    cmd = start_cmds[0]
    assert cmd["template_id"] == "calibration"
    assert cmd["operator"] == ""
    cf = cmd["custom_fields"]
    assert "reference_channel" in cf
    assert "target_channels" in cf
    # reference_channel must be stripped (no instrument prefix).
    assert ":" not in cf["reference_channel"]
    # target_channels is a comma-joined string of stripped sensor IDs.
    assert ":" not in cf["target_channels"]


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


def test_coverage_bar_uses_data_palette_not_safety_tokens(app):
    assert CoverageBar._color_for("dense").name().lower() == theme.PLOT_LINE_PALETTE[0].lower()
    assert CoverageBar._color_for("medium").name().lower() == theme.PLOT_LINE_PALETTE[1].lower()
    assert CoverageBar._color_for("sparse").name().lower() == theme.PLOT_LINE_PALETTE[4].lower()
    assert CoverageBar._color_for("empty").name().lower() == theme.MUTED_FOREGROUND.lower()
    # Unknown status falls back to MUTED_FOREGROUND.
    assert CoverageBar._color_for("garbage").name().lower() == theme.MUTED_FOREGROUND.lower()
    density_colors = {CoverageBar._color_for(status).name().lower() for status in ("dense", "medium", "sparse")}
    safety_colors = {
        theme.STATUS_OK.lower(),
        theme.STATUS_CAUTION.lower(),
        theme.STATUS_FAULT.lower(),
    }
    assert density_colors.isdisjoint(safety_colors)
    assert len({CoverageBar._brush_style_for(status) for status in ("dense", "medium", "sparse")}) == 3


def test_coverage_bar_empty_bins_paints_nothing(app):
    # Call set_coverage([]) so the real setter + update() path runs.
    bar = CoverageBar()
    bar.resize(200, 24)
    bar.show()
    bar.set_coverage([])
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    # Empty bins: no segments painted (early-return in paintEvent).
    assert bar._bins == []


def test_coverage_bar_exposes_non_color_density_description(app):
    bar = CoverageBar()
    bar.set_coverage([{"status": "dense"}, {"status": "medium"}, {"status": "sparse"}, {"status": "empty"}])
    description = bar.accessibleDescription().lower()
    assert "плотно 1" in description
    assert "средне 1" in description
    assert "редко 1" in description
    assert "нет данных 1" in description


# ----------------------------------------------------------------------
# Results metrics
# ----------------------------------------------------------------------


def test_results_set_channels_populates_combo(app):
    panel = CalibrationPanel()
    panel._results_widget.set_channels(["Т1", "Т2", "Т3"])
    combo = panel._results_widget._channel_combo
    assert combo.count() == 3
    assert [combo.itemText(i) for i in range(combo.count())] == ["Т1", "Т2", "Т3"]
    assert panel._results_widget._current_sensor_id == "Т1"


def test_results_channel_change_dispatches_curve_get(app):
    panel = CalibrationPanel()
    _StubWorker.next_result = {"calibration_curve_get": {"ok": True, "curve": {}}}
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1", "Т2"])
    _StubWorker.dispatched = []
    panel._results_widget._channel_combo.setCurrentText("Т2")
    get_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "calibration_curve_get"]
    assert len(get_cmds) == 1
    assert get_cmds[0]["sensor_id"] == "Т2"


def test_metrics_requests_are_single_flight_and_channel_bound(app):
    panel = CalibrationPanel()
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1", "Т2"])
    first = next(
        worker for worker in reversed(_StubWorker.instances) if worker._cmd.get("cmd") == "calibration_curve_get"
    )
    panel._results_widget._channel_combo.setCurrentText("Т2")
    assert panel._results_widget._queued_metrics_sensor == "Т2"

    first.finished.emit({"ok": True, "curve": {"raw_count": 111}})
    assert panel._results_widget._raw_count_label.text() == "—"
    second = next(
        worker
        for worker in reversed(_StubWorker.instances)
        if worker is not first and worker._cmd.get("cmd") == "calibration_curve_get"
    )
    assert second._cmd["sensor_id"] == "Т2"
    second.finished.emit({"ok": True, "curve": {"raw_count": 222}})
    assert panel._results_widget._raw_count_label.text() == "222"
    assert "Т2" in panel._results_widget._metrics_status_label.text()


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
    import_path = tmp_path / "curve.340"
    import_path.write_text("# header\n4.0 75.0\n6.0 60.0\n10.0 40.0\n20.0 22.0\n")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(import_path), "LakeShore .340 (*.340)")),
    )
    _StubWorker.dispatched = []
    panel._setup_widget._import_340_btn.click()
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


def test_import_revalidates_connection_after_file_dialog(app, monkeypatch, tmp_path):
    panel = CalibrationPanel()
    panel.set_connected(True)
    import_path = tmp_path / "curve.340"
    import_path.write_text("# curve\n", encoding="utf-8")

    def _disconnect_during_dialog(*_args, **_kwargs):
        panel.set_connected(False)
        return str(import_path), "LakeShore .340 (*.340)"

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(_disconnect_during_dialog))
    _StubWorker.dispatched = []
    panel._setup_widget._on_import_clicked("LakeShore .340 (*.340)")
    assert not any(cmd.get("cmd") == "calibration_curve_import" for cmd in _StubWorker.dispatched)
    assert "не отправлен" in panel._banner_label.text().lower()


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------


def test_export_without_selection_shows_error(app, monkeypatch):
    panel = CalibrationPanel()
    panel.set_connected(True)
    # Channel combo empty → current_sensor_id unset.
    panel._results_widget._current_sensor_id = ""
    panel._results_widget._export_cof_btn.click()
    assert "канал" in panel._banner_label.text().lower()


def test_export_dispatches_correct_path_parameter(app, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    panel = CalibrationPanel()
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1"])
    out = tmp_path / "Т1.cof"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(out), "Chebyshev .cof (*.cof)")),
    )
    _StubWorker.dispatched = []
    panel._results_widget._export_cof_btn.click()
    export_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "calibration_curve_export"]
    assert len(export_cmds) == 1
    cmd = export_cmds[0]
    assert cmd["sensor_id"] == "Т1"
    assert cmd["curve_cof_path"] == str(out)
    # Other format paths not set.
    assert "json_path" not in cmd
    assert "table_path" not in cmd
    assert "curve_330_path" not in cmd
    assert "curve_340_path" not in cmd


def test_export_json_dispatches_json_path(app, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog

    panel = CalibrationPanel()
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т5"])
    out = tmp_path / "Т5.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "JSON (*.json)")))
    _StubWorker.dispatched = []
    panel._results_widget._export_json_btn.click()
    export_cmds = [c for c in _StubWorker.dispatched if c.get("cmd") == "calibration_curve_export"]
    assert len(export_cmds) == 1
    cmd = export_cmds[0]
    assert cmd["sensor_id"] == "Т5"
    assert cmd["json_path"] == str(out)
    # No other format path keys in this command.
    assert "curve_cof_path" not in cmd
    assert "curve_340_path" not in cmd
    assert "table_path" not in cmd


def test_export_revalidates_connection_after_file_dialog(app, monkeypatch, tmp_path):
    panel = CalibrationPanel()
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1"])
    out = tmp_path / "Т1.json"

    def _disconnect_during_dialog(*_args, **_kwargs):
        panel.set_connected(False)
        return str(out), "JSON (*.json)"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_disconnect_during_dialog))
    _StubWorker.dispatched = []
    panel._results_widget._on_export_clicked("json_path", "JSON (*.json)")
    assert not any(cmd.get("cmd") == "calibration_curve_export" for cmd in _StubWorker.dispatched)
    assert "не отправлен" in panel._banner_label.text().lower()


def test_export_late_success_after_disconnect_is_unknown(app, monkeypatch, tmp_path):
    panel = CalibrationPanel()
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1"])
    out = tmp_path / "Т1.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *_a, **_k: (str(out), "JSON (*.json)")))
    panel._results_widget._on_export_clicked("json_path", "JSON (*.json)")
    worker = panel._results_widget._export_worker
    assert worker is not None
    panel.set_connected(False)
    worker.finished.emit({"ok": True})
    assert "неизвестен" in panel._banner_label.text().lower()
    assert panel._banner_timer.isActive() is False


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
    """No global toggle: lookup fires first, then its finished signal
    (emitted synchronously by the emitting stub) chains set_channel_policy.
    Both commands must appear; set_global_mode must not.
    """
    panel = CalibrationPanel()
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1"])
    # Global unchecked — only channel policy path fires.
    panel._results_widget._global_checkbox.setChecked(False)
    panel._results_widget._policy_combo.setCurrentText("Включить")
    # Emitting stub: lookup returns ok so _after_lookup_for_policy fires.
    _StubWorker.next_result = {
        "calibration_curve_lookup": {"ok": True, "assignment": {"curve_id": "curve-abc"}},
    }
    _StubWorker.dispatched = []
    panel._results_widget._apply_btn.click()
    cmds = [c["cmd"] for c in _StubWorker.dispatched]
    assert "calibration_runtime_set_global" not in cmds
    assert "calibration_curve_lookup" in cmds
    assert "calibration_runtime_set_channel_policy" in cmds
    # Verify exact policy payload.
    policy_cmd = next(c for c in _StubWorker.dispatched if c["cmd"] == "calibration_runtime_set_channel_policy")
    assert policy_cmd["sensor_id"] == "Т1"
    assert policy_cmd["policy"] == "on"
    assert "channel_key" in policy_cmd
    assert "curve_id" in policy_cmd


def test_apply_global_plus_channel_dispatches_global_first(app):
    """Global toggle checked: set_global fires first (synchronously emits
    ok via stub), then lookup fires (also emits ok), then set_channel_policy.
    Full ordered payload sequence verified.
    """
    panel = CalibrationPanel()
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1"])
    panel._results_widget._global_checkbox.setChecked(True)
    panel._results_widget._policy_combo.setCurrentText("Включить")
    # Emitting stub: both global and lookup return ok so full chain runs.
    _StubWorker.next_result = {
        "calibration_runtime_set_global": {"ok": True},
        "calibration_curve_lookup": {"ok": True, "assignment": {"curve_id": "curve-xyz"}},
    }
    _StubWorker.dispatched = []
    panel._results_widget._apply_btn.click()
    cmds = [c["cmd"] for c in _StubWorker.dispatched]
    # Ordered: global → lookup → set_channel_policy.
    assert cmds[0] == "calibration_runtime_set_global"
    assert "calibration_curve_lookup" in cmds
    assert "calibration_runtime_set_channel_policy" in cmds
    # Global mode payload.
    global_cmd = _StubWorker.dispatched[0]
    assert global_cmd["global_mode"] == "on"
    # Policy payload.
    policy_cmd = next(c for c in _StubWorker.dispatched if c["cmd"] == "calibration_runtime_set_channel_policy")
    assert policy_cmd["sensor_id"] == "Т1"
    assert policy_cmd["policy"] == "on"
    assert policy_cmd["curve_id"] == "curve-xyz"


def test_apply_lookup_failure_never_dispatches_empty_curve_policy(app):
    panel = CalibrationPanel()
    _StubWorker.next_result = {
        "calibration_curve_get": {"ok": True, "curve": {}},
        "calibration_curve_lookup": {"ok": False, "error": "not assigned"},
    }
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1"])
    _StubWorker.dispatched = []
    panel._results_widget._apply_btn.click()
    assert any(cmd.get("cmd") == "calibration_curve_lookup" for cmd in _StubWorker.dispatched)
    assert not any(cmd.get("cmd") == "calibration_runtime_set_channel_policy" for cmd in _StubWorker.dispatched)
    assert panel._active_apply is None


def test_apply_timeout_reconciles_exact_runtime_state_without_retry(app):
    panel = CalibrationPanel()
    _StubWorker.next_result = {
        "calibration_curve_get": {"ok": True, "curve": {}},
        "calibration_curve_lookup": {"ok": True, "assignment": {"curve_id": "curve-1"}},
        "calibration_runtime_set_channel_policy": {
            "ok": False,
            "_handler_timeout": True,
            "error": "Engine timed out",
        },
        "calibration_runtime_status": {
            "ok": True,
            "runtime": {
                "global_mode": "off",
                "assignments": [
                    {
                        "channel_key": "Т1",
                        "sensor_id": "Т1",
                        "reading_mode_policy": "on",
                    }
                ],
            },
        },
    }
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1"])
    panel._results_widget._policy_combo.setCurrentText("Включить")
    _StubWorker.dispatched = []
    panel._results_widget._apply_btn.click()
    QApplication.processEvents()
    commands = [cmd["cmd"] for cmd in _StubWorker.dispatched]
    assert commands.count("calibration_runtime_set_channel_policy") == 1
    assert commands.count("calibration_runtime_status") == 1
    assert panel._unresolved_apply is None
    assert "подтверждено" in panel._banner_label.text().lower()


def test_disconnect_during_apply_prevents_late_chain_dispatch(app):
    panel = CalibrationPanel()
    _StubWorker.next_result = {"calibration_curve_get": {"ok": True, "curve": {}}}
    panel.set_connected(True)
    panel._results_widget.set_channels(["Т1"])
    _StubWorker.dispatched = []
    panel._results_widget._apply_btn.click()
    lookup = next(
        worker for worker in reversed(_StubWorker.instances) if worker._cmd.get("cmd") == "calibration_curve_lookup"
    )
    panel.set_connected(False)
    lookup.finished.emit({"ok": True, "assignment": {"curve_id": "curve-1"}})
    assert not any(cmd.get("cmd") == "calibration_runtime_set_channel_policy" for cmd in _StubWorker.dispatched)
    assert panel._unresolved_apply is not None
    assert "неизвестен" in panel._banner_label.text().lower()


# ----------------------------------------------------------------------
# Connection gating
# ----------------------------------------------------------------------


def test_disconnected_disables_setup_and_results_buttons(app):
    panel = CalibrationPanel()
    panel.set_connected(False)
    assert panel._setup_widget._start_btn.isEnabled() is False
    assert panel._setup_widget._import_340_btn.isEnabled() is False
    assert panel._results_widget._export_cof_btn.isEnabled() is False
    assert panel._results_widget._apply_btn.isEnabled() is False


def test_reconnect_reenables_controls(app):
    panel = CalibrationPanel()
    panel.set_connected(True)
    # Import buttons only enabled when channels loaded OR always?
    # _SetupWidget.set_engine_enabled(True) enables import unconditionally;
    # start gated by channel presence.
    assert panel._setup_widget._import_340_btn.isEnabled() is True
    assert panel._results_widget._export_cof_btn.isEnabled() is True


def test_direct_start_handler_refuses_disconnected_dispatch(app):
    panel = CalibrationPanel()
    panel._on_start_requested("LS218:Т1", ["LS218:Т2"])
    assert not any(cmd.get("cmd") == "experiment_start" for cmd in _StubWorker.dispatched)
    assert "не отправлен" in panel._banner_label.text().lower()


def test_start_timeout_blocks_repeat_until_exact_status(app):
    panel = CalibrationPanel()
    panel.set_connected(True)
    _StubWorker.next_result = {
        "experiment_start": {
            "ok": False,
            "_handler_timeout": True,
            "error": "Engine timed out",
        }
    }
    _StubWorker.dispatched = []
    panel._on_start_requested("LS218:Т1", ["LS218:Т2"])
    panel._on_start_requested("LS218:Т1", ["LS218:Т2"])
    starts = [cmd for cmd in _StubWorker.dispatched if cmd.get("cmd") == "experiment_start"]
    assert len(starts) == 1
    assert panel._unresolved_start_name
    assert "заблокирован" in panel._banner_label.text().lower()


def test_stale_mode_reply_from_old_connection_cannot_switch_view(app):
    panel = CalibrationPanel()
    panel.set_connected(True)
    old_worker = next(
        worker for worker in _StubWorker.instances if worker._cmd.get("cmd") == "calibration_acquisition_status"
    )
    panel.set_connected(False)
    panel.set_connected(True)
    old_worker.finished.emit({"ok": True, "active": True, "point_count": 10})
    assert panel.get_current_mode() == "setup"


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
