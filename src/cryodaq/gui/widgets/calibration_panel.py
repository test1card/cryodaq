from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyqtgraph as pg
import yaml
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui.widgets.common import (
    PanelHeader,
    StatusBanner,
    add_form_rows,
    build_action_row,
    create_panel_root,
    setup_standard_table,
)
from cryodaq.gui.zmq_client import send_command
from cryodaq.paths import get_config_dir


@dataclass(frozen=True, slots=True)
class CalibrationChannelOption:
    instrument_id: str
    channel_name: str
    display_name: str

    @property
    def key(self) -> str:
        return f"{self.instrument_id}:{self.channel_name}"


class CalibrationPanel(QWidget):
    _TARGET_COLUMNS = ["Исп.", "ID датчика", "Прибор", "Канал", "Состояние", "Точки", "Кривая"]

    def __init__(self, *, instruments_config: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._instruments_config = instruments_config or self._resolve_instruments_config()
        self._channel_options = self._load_lakeshore_channels()
        self._sessions_by_target: dict[str, dict[str, Any]] = {}
        self._curves_by_sensor: dict[str, dict[str, Any]] = {}
        self._curve_artifacts: dict[str, dict[str, str]] = {}
        self._latest_temperatures: dict[str, float] = {}

        self._build_ui()
        self._populate_reference_channels()
        self._populate_target_rows()
        self._update_selection_dependent_widgets()
        self._update_availability_state()
        if self._channel_options:
            self._set_status_message("Нет активного сеанса калибровки")

    def on_reading(self, reading: Reading) -> None:
        if reading.unit != "K":
            return
        channel_name = str(reading.channel)
        if channel_name:
            self._latest_temperatures[channel_name] = reading.value
            if self._selected_target_option() is not None:
                self._update_live_readings()

    def _build_ui(self) -> None:
        root = create_panel_root(self)
        root.addWidget(
            PanelHeader(
                "Калибровка датчиков",
                "Запись точек калибровки, построение кривой и экспорт артефактов.",
            )
        )

        controls_box = QGroupBox("Сеанс калибровки")
        controls_layout = QGridLayout(controls_box)

        self._reference_combo = QComboBox()
        self._reference_combo.currentIndexChanged.connect(self._on_reference_changed)

        self._experiment_checkbox = QCheckBox("Привязать к текущему эксперименту")
        self._experiment_checkbox.setChecked(True)

        self._notes_edit = QLineEdit()
        self._notes_edit.setPlaceholderText("Примечания к сеансу")

        self._capture_status = QLabel("Нет активного сеанса калибровки")
        self._capture_status.setWordWrap(True)

        self._start_button = QPushButton("Начать сеанс")
        self._start_button.clicked.connect(self._on_start_sessions)
        self._capture_button = QPushButton("Записать точку")
        self._capture_button.clicked.connect(self._on_capture_points)
        self._stop_button = QPushButton("Завершить сеанс")
        self._stop_button.clicked.connect(self._on_stop_sessions)
        self._fit_button = QPushButton("Построить кривую")
        self._fit_button.clicked.connect(self._on_fit_curves)

        controls_layout.addWidget(QLabel("Опорный канал:"), 0, 0)
        controls_layout.addWidget(self._reference_combo, 0, 1, 1, 2)
        controls_layout.addWidget(self._experiment_checkbox, 0, 3)
        controls_layout.addWidget(QLabel("Примечания:"), 1, 0)
        controls_layout.addWidget(self._notes_edit, 1, 1, 1, 3)
        controls_layout.addWidget(self._start_button, 2, 0)
        controls_layout.addWidget(self._capture_button, 2, 1)
        controls_layout.addWidget(self._stop_button, 2, 2)
        controls_layout.addWidget(self._fit_button, 2, 3)
        controls_layout.addWidget(self._capture_status, 3, 0, 1, 4)
        root.addWidget(controls_box)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        self._targets_table = QTableWidget(0, len(self._TARGET_COLUMNS))
        setup_standard_table(self._targets_table, self._TARGET_COLUMNS)
        self._targets_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._targets_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._targets_table.itemSelectionChanged.connect(self._on_target_selection_changed)
        left_layout.addWidget(self._targets_table)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        summary_box = QGroupBox("Сводка аппроксимации")
        summary_form = QFormLayout(summary_box)
        self._selected_sensor_label = QLabel("—")
        self._live_reading_label = QLabel("—")
        self._points_label = QLabel("—")
        self._zones_label = QLabel("—")
        self._rmse_label = QLabel("—")
        self._max_error_label = QLabel("—")
        self._curve_path_label = QLabel("—")
        self._curve_path_label.setWordWrap(True)
        add_form_rows(
            summary_form,
            [
                ("Датчик:", self._selected_sensor_label),
                ("Опорный / целевой:", self._live_reading_label),
                ("Точки:", self._points_label),
                ("Зоны:", self._zones_label),
                ("RMS:", self._rmse_label),
                ("Макс. отклонение:", self._max_error_label),
                ("Артефакт:", self._curve_path_label),
            ],
        )
        right_layout.addWidget(summary_box)

        self._plot = pg.PlotWidget()
        self._plot.setBackground("#111111")
        plot_item = self._plot.getPlotItem()
        plot_item.showGrid(x=True, y=True, alpha=0.25)
        plot_item.setLabel("left", "Температура", units="K")
        plot_item.setLabel("bottom", "Сырое значение датчика", units="sensor_unit")
        self._raw_scatter = self._plot.plot(
            [],
            [],
            pen=None,
            symbol="o",
            symbolSize=6,
            symbolBrush="#58a6ff",
            name="Исходные точки",
        )
        self._fit_curve_item = self._plot.plot([], [], pen=pg.mkPen(color="#f0883e", width=2))
        right_layout.addWidget(self._plot, 1)

        self._export_button = QPushButton("Экспорт JSON/CSV")
        self._export_button.clicked.connect(self._on_export_curve)
        self._apply_button = QPushButton("Применить в CryoDAQ")
        self._apply_button.setEnabled(False)
        self._apply_button.setToolTip("Путь применения в backend пока не реализован.")
        export_row = build_action_row(self._export_button, self._apply_button, add_stretch=True)
        right_layout.addLayout(export_row)

        self._status_banner = StatusBanner("Нет активного сеанса калибровки")
        right_layout.addWidget(self._status_banner)

        self._details_text = QTextEdit()
        self._details_text.setReadOnly(True)
        self._details_text.setMaximumHeight(140)
        right_layout.addWidget(self._details_text)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

    @staticmethod
    def _resolve_instruments_config() -> Path:
        config_dir = get_config_dir()
        local = config_dir / "instruments.local.yaml"
        return local if local.exists() else config_dir / "instruments.yaml"

    def _load_lakeshore_channels(self) -> list[CalibrationChannelOption]:
        if not self._instruments_config.exists():
            return []
        try:
            raw = yaml.safe_load(self._instruments_config.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return []
        if not isinstance(raw, dict):
            return []
        instruments = raw.get("instruments", [])
        if not isinstance(instruments, list):
            return []

        options: list[CalibrationChannelOption] = []
        for instrument in instruments:
            if not isinstance(instrument, dict):
                continue
            if str(instrument.get("type", "")).strip() != "lakeshore_218s":
                continue
            instrument_id = str(instrument.get("name", "")).strip()
            if not instrument_id:
                continue
            channels = instrument.get("channels", {}) or {}
            if isinstance(channels, dict):
                channel_iter = channels.items()
            elif isinstance(channels, list):
                channel_iter = enumerate(channels, start=1)
            else:
                continue
            for key, value in channel_iter:
                if isinstance(value, dict):
                    channel_name = str(
                        value.get("name")
                        or value.get("label")
                        or value.get("channel")
                        or value.get("id")
                        or ""
                    ).strip()
                else:
                    channel_name = str(value).strip()
                channel_name = channel_name or f"CH{key}"
                options.append(
                    CalibrationChannelOption(
                        instrument_id=instrument_id,
                        channel_name=channel_name,
                        display_name=f"{instrument_id} / {channel_name}",
                    )
                )
        return options

    def _populate_reference_channels(self) -> None:
        self._reference_combo.clear()
        if not self._channel_options:
            self._reference_combo.addItem("LakeShore channels not available")
            self._reference_combo.setEnabled(False)
            return
        self._reference_combo.setEnabled(True)
        for option in self._channel_options:
            self._reference_combo.addItem(option.display_name, option)

    def _populate_target_rows(self) -> None:
        self._targets_table.setRowCount(0)
        for row, option in enumerate(self._channel_options):
            self._targets_table.insertRow(row)

            checkbox = QCheckBox()
            wrapper = QWidget()
            wrapper_layout = QHBoxLayout(wrapper)
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            wrapper_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            wrapper_layout.addWidget(checkbox)
            self._targets_table.setCellWidget(row, 0, wrapper)

            sensor_item = QTableWidgetItem(option.key)
            state_item = QTableWidgetItem("ожидание")
            points_item = QTableWidgetItem("0")
            curve_item = QTableWidgetItem("—")
            instrument_item = QTableWidgetItem(option.instrument_id)
            channel_item = QTableWidgetItem(option.channel_name)

            sensor_item.setData(Qt.ItemDataRole.UserRole, option)
            self._targets_table.setItem(row, 1, sensor_item)
            self._targets_table.setItem(row, 2, instrument_item)
            self._targets_table.setItem(row, 3, channel_item)
            self._targets_table.setItem(row, 4, state_item)
            self._targets_table.setItem(row, 5, points_item)
            self._targets_table.setItem(row, 6, curve_item)
        self._targets_table.resizeColumnsToContents()
        if self._targets_table.rowCount() > 0:
            self._targets_table.selectRow(0)
        else:
            self._details_text.setPlainText("Нет доступных LakeShore-каналов для калибровки.")

    def _update_availability_state(self) -> None:
        has_channels = bool(self._channel_options)
        has_sessions = bool(self._sessions_by_target)
        has_curve = self._selected_curve_payload() is not None
        self._start_button.setEnabled(has_channels)
        self._capture_button.setEnabled(has_sessions)
        self._stop_button.setEnabled(has_sessions)
        self._fit_button.setEnabled(has_channels and (has_sessions or self._selected_row() >= 0))
        self._export_button.setEnabled(has_curve)
        self._apply_button.setEnabled(False)
        if not has_channels:
            self._set_status_message("Каналы LakeShore недоступны. Проверьте instruments.yaml.")

    def _row_option(self, row: int) -> CalibrationChannelOption | None:
        item = self._targets_table.item(row, 1)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _checked_target_rows(self) -> list[int]:
        rows: list[int] = []
        for row in range(self._targets_table.rowCount()):
            wrapper = self._targets_table.cellWidget(row, 0)
            if wrapper is None:
                continue
            checkbox = wrapper.findChild(QCheckBox)
            if checkbox and checkbox.isChecked():
                rows.append(row)
        return rows

    def _selected_row(self) -> int:
        return self._targets_table.currentRow()

    def _selected_target_option(self) -> CalibrationChannelOption | None:
        row = self._selected_row()
        if row < 0:
            return None
        return self._row_option(row)

    def _selected_sensor_id(self) -> str | None:
        row = self._selected_row()
        if row < 0:
            return None
        item = self._targets_table.item(row, 1)
        if item is None:
            return None
        return item.text().strip() or None

    def _selected_curve_payload(self) -> dict[str, Any] | None:
        sensor_id = self._selected_sensor_id()
        if sensor_id is None:
            return None
        return self._curves_by_sensor.get(sensor_id)

    def _selected_artifacts(self) -> dict[str, str]:
        sensor_id = self._selected_sensor_id()
        if sensor_id is None:
            return {}
        return self._curve_artifacts.get(sensor_id, {})

    def _set_status_message(self, text: str) -> None:
        self._capture_status.setText(text)
        self._status_banner.show_info(text)

    def _show_warning(self, text: str) -> None:
        self._capture_status.setText(text)
        self._status_banner.show_warning(text)

    def _show_error(self, text: str) -> None:
        self._capture_status.setText(text)
        self._status_banner.show_error(text)

    @staticmethod
    def _result_payload(result: dict[str, Any], key: str) -> dict[str, Any] | None:
        payload = result.get(key)
        if not isinstance(payload, dict):
            return None
        return dict(payload)

    @Slot()
    def _on_reference_changed(self) -> None:
        reference = self._reference_combo.currentData()
        if not isinstance(reference, CalibrationChannelOption):
            return
        for row in range(self._targets_table.rowCount()):
            option = self._row_option(row)
            state_item = self._targets_table.item(row, 4)
            if option is None or state_item is None:
                continue
            if option.key == reference.key:
                state_item.setText("опорный")
            elif option.key not in self._sessions_by_target:
                state_item.setText("ожидание")

    @Slot()
    def _on_start_sessions(self) -> None:
        if not self._channel_options:
            self._show_warning("Каналы LakeShore недоступны. Проверьте instruments.yaml.")
            return
        reference = self._reference_combo.currentData()
        if not isinstance(reference, CalibrationChannelOption):
            self._show_warning("Выберите опорный канал.")
            return
        rows = self._checked_target_rows()
        if not rows:
            self._show_warning("Выберите хотя бы один целевой канал.")
            return

        started = 0
        for row in rows:
            option = self._row_option(row)
            sensor_item = self._targets_table.item(row, 1)
            if option is None or sensor_item is None:
                continue
            if option.key == reference.key:
                continue
            sensor_id = sensor_item.text().strip()
            if not sensor_id:
                self._show_warning("ID датчика не должен быть пустым.")
                return
            result = send_command(
                {
                    "cmd": "calibration_session_start",
                    "sensor_id": sensor_id,
                    "reference_instrument_id": reference.instrument_id,
                    "sensor_instrument_id": option.instrument_id,
                    "reference_channel": reference.channel_name,
                    "sensor_channel": option.channel_name,
                    "notes": self._notes_edit.text().strip(),
                    "current_experiment": self._experiment_checkbox.isChecked(),
                }
            )
            if not result.get("ok"):
                self._show_error(str(result.get("error", "Не удалось начать сеанс.")))
                return
            session_payload = self._result_payload(result, "session")
            if session_payload is None:
                self._show_error("Backend вернул некорректные данные сеанса калибровки.")
                return
            self._sessions_by_target[option.key] = session_payload
            started += 1
            self._update_row_from_session(row, session_payload)
        self._set_status_message(f"Активных сеансов калибровки: {started}")
        self._update_selection_dependent_widgets()

    @Slot()
    def _on_capture_points(self) -> None:
        if not self._sessions_by_target:
            self._show_warning("Нет активных сеансов для записи точки.")
            return
        captured = 0
        for row in range(self._targets_table.rowCount()):
            option = self._row_option(row)
            if option is None or option.key not in self._sessions_by_target:
                continue
            session = self._sessions_by_target[option.key]
            result = send_command(
                {
                    "cmd": "calibration_session_capture",
                    "session_id": session["session_id"],
                }
            )
            if not result.get("ok"):
                self._show_error(str(result.get("error", "Не удалось записать точку.")))
                return
            updated = self._result_payload(result, "session")
            if updated is None:
                self._show_error("Backend вернул некорректные данные сеанса калибровки.")
                return
            self._sessions_by_target[option.key] = updated
            self._update_row_from_session(row, updated)
            captured += 1
        self._set_status_message(f"Записано точек для целевых каналов: {captured}")
        self._update_selection_dependent_widgets()

    @Slot()
    def _on_stop_sessions(self) -> None:
        if not self._sessions_by_target:
            self._show_warning("Нет активных сеансов для завершения.")
            return
        stopped = 0
        for row in range(self._targets_table.rowCount()):
            option = self._row_option(row)
            if option is None or option.key not in self._sessions_by_target:
                continue
            session = self._sessions_by_target[option.key]
            result = send_command(
                {
                    "cmd": "calibration_session_finalize",
                    "session_id": session["session_id"],
                }
            )
            if not result.get("ok"):
                self._show_error(str(result.get("error", "Не удалось завершить сеанс.")))
                return
            updated = self._result_payload(result, "session")
            if updated is None:
                self._show_error("Backend вернул некорректные данные сеанса калибровки.")
                return
            self._sessions_by_target[option.key] = updated
            self._update_row_from_session(row, updated)
            stopped += 1
        self._set_status_message(f"Завершено сеансов: {stopped}")
        self._update_selection_dependent_widgets()

    @Slot()
    def _on_fit_curves(self) -> None:
        if not self._channel_options:
            self._show_warning("Каналы LakeShore недоступны.")
            return
        rows = self._checked_target_rows() or ([self._selected_row()] if self._selected_row() >= 0 else [])
        fitted = 0
        for row in rows:
            option = self._row_option(row)
            sensor_item = self._targets_table.item(row, 1)
            if option is None or sensor_item is None:
                continue
            session = self._sessions_by_target.get(option.key)
            if session is None:
                continue
            result = send_command(
                {
                    "cmd": "calibration_curve_fit",
                    "session_id": session["session_id"],
                    "min_points_per_zone": 6,
                    "target_rmse_k": 0.05,
                }
            )
            if not result.get("ok"):
                self._show_error(str(result.get("error", "Не удалось построить кривую.")))
                return
            curve_payload = self._result_payload(result, "curve")
            if curve_payload is None:
                self._show_error("Backend вернул некорректные данные калибровочной кривой.")
                return
            sensor_id = sensor_item.text().strip()
            self._curves_by_sensor[sensor_id] = curve_payload
            self._curve_artifacts[sensor_id] = {
                "curve_path": str(result.get("curve_path", "")),
                "table_path": str(result.get("table_path", "")),
            }
            curve_item = self._targets_table.item(row, 6)
            if curve_item is not None:
                curve_item.setText("готова")
            fitted += 1
        self._set_status_message(f"Построено кривых: {fitted}")
        self._update_selection_dependent_widgets()

    @Slot()
    def _on_export_curve(self) -> None:
        curve = self._selected_curve_payload()
        sensor_id = self._selected_sensor_id()
        if curve is None or sensor_id is None:
            self._show_warning("Сначала выберите построенную калибровочную кривую.")
            return

        selected_artifacts = self._selected_artifacts()
        default_dir = Path(selected_artifacts.get("curve_path") or self._instruments_config.parent)
        default_parent = default_dir.parent if default_dir.suffix else default_dir
        json_path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт калибровки в JSON",
            str(default_parent / f"{sensor_id.replace(':', '_')}.json"),
            "JSON (*.json)",
        )
        if not json_path:
            return
        csv_path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт таблицы калибровки",
            str(default_parent / f"{sensor_id.replace(':', '_')}.csv"),
            "CSV (*.csv)",
        )
        if not csv_path:
            return

        result = send_command(
            {
                "cmd": "calibration_curve_export",
                "sensor_id": sensor_id,
                "json_path": json_path,
                "table_path": csv_path,
            }
        )
        if not result.get("ok"):
            self._show_error(str(result.get("error", "Не удалось выполнить экспорт.")))
            return
        self._curve_artifacts[sensor_id] = {
            "curve_path": str(result.get("json_path", "")),
            "table_path": str(result.get("table_path", "")),
        }
        self._set_status_message("Артефакты калибровки экспортированы.")
        self._update_selection_dependent_widgets()

    @Slot()
    def _on_target_selection_changed(self) -> None:
        self._update_selection_dependent_widgets()

    def _update_row_from_session(self, row: int, session: dict[str, Any]) -> None:
        state_item = self._targets_table.item(row, 4)
        points_item = self._targets_table.item(row, 5)
        if state_item is None or points_item is None:
            return
        samples_raw = session.get("samples", [])
        sample_count = len(samples_raw) if isinstance(samples_raw, list) else 0
        finished_at = session.get("finished_at")
        state_item.setText("завершен" if finished_at else "запись")
        points_item.setText(str(sample_count))

    def _update_selection_dependent_widgets(self) -> None:
        option = self._selected_target_option()
        curve = self._selected_curve_payload()
        session = self._sessions_by_target.get(option.key) if option is not None else None
        artifacts = self._selected_artifacts()

        self._selected_sensor_label.setText(self._selected_sensor_id() or "—")
        self._update_live_readings()

        if option is None:
            self._points_label.setText("0")
            self._details_text.setPlainText("Нет доступных каналов для калибровки.")
        elif session is None:
            self._points_label.setText("0")
            self._details_text.setPlainText("Нет данных сеанса калибровки для выбранного канала.")
        else:
            samples_raw = session.get("samples", [])
            samples = list(samples_raw) if isinstance(samples_raw, list) else []
            self._points_label.setText(str(len(samples)))
            self._details_text.setPlainText(self._format_session_details(session))

        if curve is None:
            self._zones_label.setText("—")
            self._rmse_label.setText("—")
            self._max_error_label.setText("—")
            self._curve_path_label.setText(artifacts.get("curve_path", "—") or "—")
            self._raw_scatter.setData([], [])
            self._fit_curve_item.setData([], [])
        else:
            metrics = curve.get("metrics", {})
            if not isinstance(metrics, dict):
                metrics = {}
            self._zones_label.setText(str(metrics.get("zone_count", len(curve.get("zones", [])))))
            self._rmse_label.setText(f"{float(metrics.get('rmse_k', 0.0)):.4f} K")
            self._max_error_label.setText(f"{float(metrics.get('max_abs_error_k', 0.0)):.4f} K")
            self._curve_path_label.setText(artifacts.get("curve_path", "—") or "—")
            self._render_curve_plot(session or {}, curve)

        self._update_availability_state()

    def _update_live_readings(self) -> None:
        reference = self._reference_combo.currentData()
        option = self._selected_target_option()
        if not isinstance(reference, CalibrationChannelOption) or option is None:
            self._live_reading_label.setText("—")
            return
        ref_value = self._latest_temperatures.get(reference.channel_name)
        target_value = self._latest_temperatures.get(option.channel_name)
        if ref_value is None and target_value is None:
            self._live_reading_label.setText("—")
            return
        ref_text = f"{reference.channel_name}: {ref_value:.4f} K" if ref_value is not None else f"{reference.channel_name}: —"
        target_text = f"{option.channel_name}: {target_value:.4f} K" if target_value is not None else f"{option.channel_name}: —"
        self._live_reading_label.setText(f"{ref_text} | {target_text}")

    def _render_curve_plot(self, session: dict[str, Any], curve: dict[str, Any]) -> None:
        samples_raw = session.get("samples", [])
        samples = list(samples_raw) if isinstance(samples_raw, list) else []
        xs: list[float] = []
        ys: list[float] = []
        for item in samples:
            if not isinstance(item, dict):
                continue
            try:
                raw_value = float(item["sensor_raw_value"])
                reference_temperature = float(item["reference_temperature"])
            except (KeyError, TypeError, ValueError):
                continue
            xs.append(raw_value)
            ys.append(reference_temperature)
        self._raw_scatter.setData(xs, ys)

        zones_raw = curve.get("zones", [])
        zones = list(zones_raw) if isinstance(zones_raw, list) else []
        if not zones:
            self._fit_curve_item.setData([], [])
            return
        plot_xs: list[float] = []
        plot_ys: list[float] = []
        for zone in zones:
            if not isinstance(zone, dict):
                continue
            try:
                raw_min = float(zone["raw_min"])
                raw_max = float(zone["raw_max"])
                coefficients = [float(value) for value in zone.get("coefficients", [])]
            except (KeyError, TypeError, ValueError):
                continue
            if raw_max <= raw_min or not coefficients:
                continue
            step_count = 80
            for idx in range(step_count):
                raw_value = raw_min + ((raw_max - raw_min) * idx / (step_count - 1))
                scaled = ((2.0 * (raw_value - raw_min)) / (raw_max - raw_min)) - 1.0
                temperature = 0.0
                for order, coeff in enumerate(coefficients):
                    if order == 0:
                        basis = 1.0
                    elif order == 1:
                        basis = scaled
                    else:
                        basis_prev = 1.0
                        basis_curr = scaled
                        for _ in range(2, order + 1):
                            basis_prev, basis_curr = basis_curr, (2 * scaled * basis_curr) - basis_prev
                        basis = basis_curr
                    temperature += coeff * basis
                plot_xs.append(raw_value)
                plot_ys.append(temperature)
        self._fit_curve_item.setData(plot_xs, plot_ys)

    @staticmethod
    def _format_session_details(session: dict[str, Any]) -> str:
        samples_raw = session.get("samples", [])
        samples = list(samples_raw) if isinstance(samples_raw, list) else []
        lines = [
            f"Сеанс: {session.get('session_id', '')}",
            f"Опора: {session.get('reference_instrument_id', '')} / {session.get('reference_channel', '')}",
            f"Цель: {session.get('sensor_instrument_id', '')} / {session.get('sensor_channel', '')}",
            f"Начат: {session.get('started_at', '')}",
            f"Завершен: {session.get('finished_at', '') or 'активен'}",
            f"Точек: {len(samples)}",
        ]
        if samples and isinstance(samples[-1], dict):
            last = samples[-1]
            try:
                lines.append(
                    "Последняя точка: "
                    f"Tоп={float(last.get('reference_temperature', 0.0)):.6g} K, "
                    f"raw={float(last.get('sensor_raw_value', 0.0)):.6g}"
                )
            except (TypeError, ValueError):
                lines.append("Последняя точка: некорректные данные")
        return "\n".join(lines)
