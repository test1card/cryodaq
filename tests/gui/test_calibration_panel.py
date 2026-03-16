from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml
from PySide6.QtWidgets import QApplication, QCheckBox

from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.calibration_panel import CalibrationPanel


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
            }
        ]
    }
    path.write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")
    return path


def _checkbox(panel: CalibrationPanel, row: int) -> QCheckBox:
    wrapper = panel._targets_table.cellWidget(row, 0)
    assert wrapper is not None
    checkbox = wrapper.findChild(QCheckBox)
    assert checkbox is not None
    return checkbox


def test_calibration_panel_instantiates_and_loads_channels(tmp_path: Path) -> None:
    _app()
    panel = CalibrationPanel(instruments_config=_write_instruments(tmp_path / "instruments.yaml"))

    assert panel._reference_combo.count() == 3
    assert panel._targets_table.rowCount() == 3
    assert panel._targets_table.item(0, 1).text() == "LS218_1:Т1 Криостат верх"


def test_calibration_panel_uses_normalized_russian_labels(tmp_path: Path) -> None:
    _app()
    panel = CalibrationPanel(instruments_config=_write_instruments(tmp_path / "instruments.yaml"))

    assert panel._start_button.text() == "Начать сеанс"
    assert panel._capture_button.text() == "Записать точку"
    assert panel._stop_button.text() == "Завершить сеанс"
    assert panel._fit_button.text() == "Построить кривую"
    assert panel._export_button.text() == "Экспорт JSON/CSV"
    assert panel._apply_button.text() == "Применить в CryoDAQ"


def test_calibration_panel_handles_missing_or_malformed_config(tmp_path: Path) -> None:
    _app()
    missing = tmp_path / "missing.yaml"
    malformed = tmp_path / "broken.yaml"
    malformed.write_text("instruments: [", encoding="utf-8")

    missing_panel = CalibrationPanel(instruments_config=missing)
    malformed_panel = CalibrationPanel(instruments_config=malformed)

    for panel in (missing_panel, malformed_panel):
        assert panel._reference_combo.isEnabled() is False
        assert panel._reference_combo.count() == 1
        assert panel._targets_table.rowCount() == 0
        assert panel._start_button.isEnabled() is False
        assert panel._capture_button.isEnabled() is False
        assert panel._stop_button.isEnabled() is False
        assert panel._fit_button.isEnabled() is False
        assert panel._export_button.isEnabled() is False
        assert panel._apply_button.isEnabled() is False
        assert "LakeShore" in panel._capture_status.text()


def test_calibration_panel_accepts_list_shaped_channel_config(tmp_path: Path) -> None:
    _app()
    config = {
        "instruments": [
            {
                "type": "lakeshore_218s",
                "name": "LS218_1",
                "channels": [
                    "Т1 Криостат верх",
                    {"label": "Т2 Криостат низ"},
                    {},
                ],
            }
        ]
    }
    path = tmp_path / "instruments.yaml"
    path.write_text(yaml.dump(config, allow_unicode=True), encoding="utf-8")

    panel = CalibrationPanel(instruments_config=path)

    assert panel._reference_combo.count() == 3
    assert panel._targets_table.item(0, 1).text() == "LS218_1:Т1 Криостат верх"
    assert panel._targets_table.item(1, 1).text() == "LS218_1:Т2 Криостат низ"
    assert panel._targets_table.item(2, 1).text() == "LS218_1:CH3"


def test_calibration_panel_command_flow_and_fit_rendering(monkeypatch, tmp_path: Path) -> None:
    _app()
    sessions: dict[str, dict] = {}
    exports: list[dict] = []

    def _fake_send(payload: dict) -> dict:
        cmd = payload["cmd"]
        if cmd == "calibration_session_start":
            session_id = f"sess-{len(sessions) + 1}"
            session = {
                "session_id": session_id,
                "sensor_id": payload["sensor_id"],
                "reference_channel": payload["reference_channel"],
                "sensor_channel": payload["sensor_channel"],
                "raw_unit": "sensor_unit",
                "started_at": "2026-03-16T12:00:00+00:00",
                "finished_at": None,
                "reference_instrument_id": payload["reference_instrument_id"],
                "sensor_instrument_id": payload["sensor_instrument_id"],
                "experiment_id": "exp-001",
                "notes": payload.get("notes", ""),
                "metadata": {},
                "samples": [],
            }
            sessions[session_id] = session
            return {"ok": True, "session": session}
        if cmd == "calibration_session_capture":
            session = sessions[payload["session_id"]]
            session["samples"].append(
                {
                    "timestamp": "2026-03-16T12:01:00+00:00",
                    "reference_channel": session["reference_channel"],
                    "reference_temperature": 4.2 + len(session["samples"]),
                    "sensor_channel": session["sensor_channel"],
                    "sensor_raw_value": 80.0 - (3 * len(session["samples"])),
                    "reference_instrument_id": session["reference_instrument_id"],
                    "sensor_instrument_id": session["sensor_instrument_id"],
                    "experiment_id": session["experiment_id"],
                    "metadata": {},
                }
            )
            return {"ok": True, "session": session, "sample": session["samples"][-1]}
        if cmd == "calibration_session_finalize":
            session = sessions[payload["session_id"]]
            session["finished_at"] = "2026-03-16T12:10:00+00:00"
            return {"ok": True, "session": session}
        if cmd == "calibration_curve_fit":
            session = sessions[payload["session_id"]]
            curve = {
                "curve_id": "curve-001",
                "sensor_id": session["sensor_id"],
                "fit_timestamp": "2026-03-16T12:15:00+00:00",
                "raw_unit": "sensor_unit",
                "sensor_kind": "generic",
                "source_session_ids": [session["session_id"]],
                "zones": [
                    {
                        "raw_min": 68.0,
                        "raw_max": 80.0,
                        "order": 2,
                        "coefficients": [6.0, -1.5, 0.2],
                        "rmse_k": 0.012,
                        "max_abs_error_k": 0.031,
                        "point_count": len(session["samples"]),
                    }
                ],
                "metrics": {
                    "sample_count": len(session["samples"]),
                    "zone_count": 1,
                    "rmse_k": 0.012,
                    "max_abs_error_k": 0.031,
                },
                "metadata": {},
            }
            return {
                "ok": True,
                "curve": curve,
                "curve_path": str(tmp_path / "curve.json"),
                "table_path": str(tmp_path / "curve_table.csv"),
            }
        if cmd == "calibration_curve_export":
            exports.append(dict(payload))
            return {
                "ok": True,
                "json_path": payload["json_path"],
                "table_path": payload["table_path"],
            }
        raise AssertionError(f"Unexpected command: {payload}")

    monkeypatch.setattr("cryodaq.gui.widgets.calibration_panel.send_command", _fake_send)
    monkeypatch.setattr(
        "cryodaq.gui.widgets.calibration_panel.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (
            str(tmp_path / ("curve.json" if "JSON" in _args[1] else "curve.csv")),
            "",
        ),
    )

    panel = CalibrationPanel(instruments_config=_write_instruments(tmp_path / "instruments.yaml"))
    panel._reference_combo.setCurrentIndex(0)
    _checkbox(panel, 1).setChecked(True)
    panel._targets_table.selectRow(1)

    panel._on_start_sessions()
    for _ in range(3):
        panel._on_capture_points()
    panel._on_stop_sessions()
    panel._on_fit_curves()
    panel.on_reading(Reading.now(channel="Т1 Криостат верх", value=4.15, unit="K", instrument_id="LS218_1"))
    panel.on_reading(Reading.now(channel="Т2 Криостат низ", value=4.05, unit="K", instrument_id="LS218_1"))
    panel._on_export_curve()

    assert panel._targets_table.item(1, 4).text() == "завершен"
    assert panel._targets_table.item(1, 5).text() == "3"
    assert panel._targets_table.item(1, 6).text() == "готова"
    assert panel._points_label.text() == "3"
    assert panel._zones_label.text() == "1"
    assert panel._rmse_label.text() == "0.0120 K"
    assert "Т1 Криостат верх" in panel._live_reading_label.text()
    assert len(panel._fit_curve_item.getData()[0]) > 0
    assert len(exports) == 1
    assert exports[0]["sensor_id"] == "LS218_1:Т2 Криостат низ"


def test_calibration_panel_handles_invalid_backend_payload(monkeypatch, tmp_path: Path) -> None:
    _app()
    def _fake_send(payload: dict) -> dict:
        if payload["cmd"] == "calibration_session_start":
            return {"ok": True}
        raise AssertionError(payload)

    monkeypatch.setattr("cryodaq.gui.widgets.calibration_panel.send_command", _fake_send)

    panel = CalibrationPanel(instruments_config=_write_instruments(tmp_path / "instruments.yaml"))
    panel._reference_combo.setCurrentIndex(0)
    _checkbox(panel, 1).setChecked(True)

    panel._on_start_sessions()

    assert panel._status_banner.text() == "Backend вернул некорректные данные сеанса калибровки."
    assert panel._capture_button.isEnabled() is False


def test_calibration_panel_handles_sparse_multizone_fit_data(tmp_path: Path) -> None:
    _app()
    panel = CalibrationPanel(instruments_config=_write_instruments(tmp_path / "instruments.yaml"))
    panel._targets_table.selectRow(1)
    option = panel._selected_target_option()
    assert option is not None
    panel._sessions_by_target[option.key] = {
        "session_id": "sess-1",
        "reference_instrument_id": "LS218_1",
        "reference_channel": "Т1 Криостат верх",
        "sensor_instrument_id": "LS218_1",
        "sensor_channel": "Т2 Криостат низ",
        "started_at": "2026-03-16T12:00:00+00:00",
        "finished_at": "2026-03-16T12:10:00+00:00",
        "samples": [
            {"reference_temperature": 4.2, "sensor_raw_value": 80.0},
            {"reference_temperature": "bad", "sensor_raw_value": 79.5},
            {"reference_temperature": 4.0},
            "bad",
        ],
    }
    panel._curves_by_sensor[panel._selected_sensor_id() or ""] = {
        "zones": [
            {"raw_min": 75.0, "raw_max": 80.0, "coefficients": [6.0, -1.5]},
            {"raw_min": 70.0, "raw_max": 75.0, "coefficients": []},
            {"raw_min": "bad", "raw_max": 70.0, "coefficients": [1.0]},
        ],
        "metrics": {"zone_count": 3, "rmse_k": 0.02, "max_abs_error_k": 0.05},
    }

    panel._update_selection_dependent_widgets()

    raw_xs, raw_ys = panel._raw_scatter.getData()
    fit_xs, fit_ys = panel._fit_curve_item.getData()
    assert raw_xs == [80.0]
    assert raw_ys == [4.2]
    assert len(fit_xs) > 0
    assert len(fit_xs) == len(fit_ys)
    assert panel._zones_label.text() == "3"


def test_calibration_panel_export_disabled_without_curve(tmp_path: Path) -> None:
    _app()
    panel = CalibrationPanel(instruments_config=_write_instruments(tmp_path / "instruments.yaml"))

    assert panel._export_button.isEnabled() is False
    assert panel._apply_button.isEnabled() is False


def test_calibration_panel_uses_inline_warning_for_missing_active_sessions(tmp_path: Path) -> None:
    _app()
    panel = CalibrationPanel(instruments_config=_write_instruments(tmp_path / "instruments.yaml"))

    panel._on_capture_points()

    assert panel._status_banner.text() == "Нет активных сеансов для записи точки."


def test_calibration_panel_export_cancel_does_not_call_backend(monkeypatch, tmp_path: Path) -> None:
    _app()
    calls: list[dict] = []
    panel = CalibrationPanel(instruments_config=_write_instruments(tmp_path / "instruments.yaml"))
    panel._targets_table.selectRow(1)
    sensor_id = panel._selected_sensor_id()
    assert sensor_id is not None
    panel._curves_by_sensor[sensor_id] = {"zones": [], "metrics": {}}
    panel._curve_artifacts[sensor_id] = {"curve_path": str(tmp_path / "existing.json"), "table_path": ""}
    panel._update_selection_dependent_widgets()

    monkeypatch.setattr("cryodaq.gui.widgets.calibration_panel.send_command", lambda payload: calls.append(dict(payload)) or {"ok": True})
    monkeypatch.setattr(
        "cryodaq.gui.widgets.calibration_panel.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: ("", ""),
    )

    panel._on_export_curve()

    assert calls == []
