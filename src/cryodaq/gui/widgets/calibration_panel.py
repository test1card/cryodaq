"""Calibration v2 panel — three-mode: Setup, Acquisition, Results.

Auto-switches based on calibration_acquisition_status:
- acquisition active → CalibrationAcquisitionWidget
- completed data exists → CalibrationResultsWidget
- otherwise → CalibrationSetupWidget
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QTimer, Slot
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme
from cryodaq.gui.widgets.common import (
    PanelHeader,
    StatusBanner,
    apply_button_style,
    apply_group_box_style,
    create_panel_root,
    setup_standard_table,
)

logger = logging.getLogger(__name__)

from cryodaq.paths import get_config_dir as _get_config_dir

_INSTRUMENTS_DEFAULT = _get_config_dir() / "instruments.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_instrument_prefix(channel_ref: str) -> str:
    """Strip 'instrument_id:' prefix from a channel reference.

    Calibration panel combobox stores channels as 'LS218_1:Т1 Криостат верх'
    to help operators identify which instrument owns each channel. Engine
    commands work on canonical Reading.channel values which never include
    an instrument prefix.
    """
    if ":" in channel_ref:
        return channel_ref.split(":", 1)[1]
    return channel_ref


def _load_lakeshore_channels(config_path: Path) -> list[dict[str, Any]]:
    """Load LakeShore channels grouped by instrument from instruments.yaml."""
    try:
        with config_path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        if not isinstance(raw, dict):
            return []
    except Exception:
        return []

    result: list[dict[str, Any]] = []
    for entry in raw.get("instruments", []):
        if entry.get("type") != "lakeshore_218s":
            continue
        name = entry.get("name", "LS218")
        channels_raw = entry.get("channels", {})
        channels: list[str] = []
        if isinstance(channels_raw, dict):
            for idx in sorted(channels_raw.keys(), key=int):
                channels.append(f"{name}:{channels_raw[idx]}")
        elif isinstance(channels_raw, (list, tuple)):
            for i, ch in enumerate(channels_raw, 1):
                if isinstance(ch, str):
                    channels.append(f"{name}:{ch}")
                elif isinstance(ch, dict) and "label" in ch:
                    channels.append(f"{name}:{ch['label']}")
                else:
                    channels.append(f"{name}:CH{i}")
        result.append({"instrument": name, "channels": channels})
    return result


# ---------------------------------------------------------------------------
# CoverageBar
# ---------------------------------------------------------------------------

class CoverageBar(QWidget):
    """Horizontal bar showing calibration point density across temperature range."""

    _COLORS = {
        "dense": QColor("#2ECC40"),
        "medium": QColor("#FFDC00"),
        "sparse": QColor("#FF851B"),
        "empty": QColor("#333333"),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(24)
        self._bins: list[dict[str, Any]] = []

    def set_coverage(self, bins: list[dict[str, Any]]) -> None:
        self._bins = bins
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: ANN001
        if not self._bins:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        n = len(self._bins)
        seg_w = max(1, w // n)
        for i, b in enumerate(self._bins):
            color = self._COLORS.get(b.get("status", "empty"), self._COLORS["empty"])
            painter.fillRect(i * seg_w, 0, seg_w, h, color)
        painter.end()


# ---------------------------------------------------------------------------
# CalibrationSetupWidget
# ---------------------------------------------------------------------------

class CalibrationSetupWidget(QWidget):
    """Setup mode: channel selection, import, existing curves."""

    def __init__(
        self,
        instruments_config: Path = _INSTRUMENTS_DEFAULT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._instruments_config = instruments_config
        self._instrument_groups = _load_lakeshore_channels(instruments_config)
        self._all_channels: list[str] = []
        self._target_checkboxes: dict[str, QCheckBox] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = create_panel_root(self)

        root.addWidget(PanelHeader(
            "Калибровка датчиков",
            "Автоматический сбор KRDG + SRDG во время калибровочного прогона.",
        ))

        # Reference channel
        ref_form = QFormLayout()
        self._reference_combo = QComboBox()
        for group in self._instrument_groups:
            for ch in group["channels"]:
                self._all_channels.append(ch)
                self._reference_combo.addItem(ch)
        if not self._all_channels:
            self._reference_combo.addItem("Нет LakeShore каналов")
            self._reference_combo.setEnabled(False)
        ref_form.addRow("Опорный канал:", self._reference_combo)
        root.addLayout(ref_form)

        # Target channels grouped by instrument
        for group in self._instrument_groups:
            box = QGroupBox(group["instrument"])
            apply_group_box_style(box)
            box_layout = QHBoxLayout(box)
            box_layout.setSpacing(8)
            for ch in group["channels"]:
                cb = QCheckBox(ch.split(":")[-1])
                cb.setChecked(True)
                self._target_checkboxes[ch] = cb
                box_layout.addWidget(cb)
            root.addWidget(box)

        # Note + start button
        note = QLabel("Опорный канал автоматически исключается из целевых.")
        note.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        root.addWidget(note)

        self._start_btn = QPushButton("Начать калибровочный прогон")
        apply_button_style(self._start_btn, "primary")
        self._start_btn.clicked.connect(self._on_start_calibration)
        if not self._all_channels:
            self._start_btn.setEnabled(False)
        root.addWidget(self._start_btn)

        self._status = StatusBanner()
        self._status.clear_message()
        root.addWidget(self._status)

        # Import
        import_box = QGroupBox("Импорт внешней кривой")
        apply_group_box_style(import_box)
        import_layout = QHBoxLayout(import_box)
        self._import_330_btn = QPushButton("Импорт .330")
        self._import_340_btn = QPushButton("Импорт .340")
        self._import_json_btn = QPushButton("Импорт JSON")
        for btn in (self._import_330_btn, self._import_340_btn, self._import_json_btn):
            apply_button_style(btn, "neutral")
            import_layout.addWidget(btn)
        root.addWidget(import_box)

        # Existing curves table
        curves_box = QGroupBox("Существующие кривые")
        apply_group_box_style(curves_box)
        curves_layout = QVBoxLayout(curves_box)
        self._curves_table = QTableWidget()
        setup_standard_table(self._curves_table, ["Датчик", "Curve ID", "Зон", "RMSE", "Источник"])
        curves_layout.addWidget(self._curves_table, stretch=1)
        h = self._curves_table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(curves_box, stretch=1)

    @Slot()
    def _on_start_calibration(self) -> None:
        ref = self._reference_combo.currentText()
        if not ref or ref == "Нет LakeShore каналов":
            self._status.show_warning("Выберите опорный канал.")
            return
        targets = self.get_selected_targets()
        if not targets:
            self._status.show_warning("Выберите хотя бы один целевой канал.")
            return

        from datetime import datetime

        name = f"Calibration-{datetime.now().strftime('%Y-%m-%d-%H-%M')}"
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._start_worker = ZmqCommandWorker({
            "cmd": "experiment_start",
            "template_id": "calibration",
            "name": name,
            "title": name,
            "operator": "",
            "custom_fields": {
                "reference_channel": _strip_instrument_prefix(ref),
                "target_channels": ", ".join(
                    _strip_instrument_prefix(t) for t in targets
                ),
            },
        })
        self._start_worker.finished.connect(self._on_start_result)
        self._start_btn.setEnabled(False)
        self._start_worker.start()

    @Slot(dict)
    def _on_start_result(self, result: dict) -> None:
        self._start_btn.setEnabled(True)
        if result.get("ok"):
            self._status.show_success("Калибровочный прогон начат. Переключение на режим сбора...")
        else:
            self._status.show_error(str(result.get("error", "Не удалось начать прогон.")))

    def get_selected_targets(self) -> list[str]:
        ref = self._reference_combo.currentText()
        return [
            ch for ch, cb in self._target_checkboxes.items()
            if cb.isChecked() and ch != ref
        ]


# ---------------------------------------------------------------------------
# CalibrationAcquisitionWidget
# ---------------------------------------------------------------------------

class CalibrationAcquisitionWidget(QWidget):
    """Acquisition mode: live stats + coverage bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = create_panel_root(self)

        root.addWidget(PanelHeader("Сбор данных — активен", "Запись KRDG + SRDG идёт автоматически."))

        # Stats
        stats_form = QFormLayout()
        self._experiment_label = QLabel("—")
        self._elapsed_label = QLabel("—")
        self._point_count_label = QLabel("0")
        self._temp_range_label = QLabel("— K")
        stats_form.addRow("Эксперимент:", self._experiment_label)
        stats_form.addRow("Время:", self._elapsed_label)
        stats_form.addRow("Точек записано:", self._point_count_label)
        stats_form.addRow("Диапазон T_ref:", self._temp_range_label)
        root.addLayout(stats_form)

        # Coverage bar
        coverage_box = QGroupBox("Покрытие по температуре")
        apply_group_box_style(coverage_box)
        cov_layout = QVBoxLayout(coverage_box)
        self._coverage_bar = CoverageBar()
        cov_layout.addWidget(self._coverage_bar)

        legend = QLabel(
            "▓ dense (>10 pts/K)  ▒ medium (3-10 pts/K)  "
            "░ sparse (<3 pts/K)  ▁ empty"
        )
        legend.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 9pt;")
        cov_layout.addWidget(legend)
        root.addWidget(coverage_box)

        # Live readings area
        self._live_label = QLabel("")
        self._live_label.setStyleSheet(f"color: {theme.TEXT_ACCENT};")
        self._live_label.setWordWrap(True)
        root.addWidget(self._live_label, stretch=1)

        note = QLabel("Запись идёт автоматически. Дождитесь полного cooldown, затем завершите эксперимент.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        root.addWidget(note)

    def update_stats(self, stats: dict[str, Any]) -> None:
        self._point_count_label.setText(f"{stats.get('point_count', 0):,}")
        t_min = stats.get("t_min")
        t_max = stats.get("t_max")
        if t_min is not None and t_max is not None:
            self._temp_range_label.setText(f"{t_min:.1f} — {t_max:.1f} K")

    def update_coverage(self, bins: list[dict[str, Any]]) -> None:
        self._coverage_bar.set_coverage(bins)


# ---------------------------------------------------------------------------
# CalibrationResultsWidget
# ---------------------------------------------------------------------------

class CalibrationResultsWidget(QWidget):
    """Results mode: fit metrics, scatter plot, export, runtime apply."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = create_panel_root(self)

        root.addWidget(PanelHeader("Результаты калибровки"))

        # Channel selector
        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Канал:"))
        self._channel_combo = QComboBox()
        selector_row.addWidget(self._channel_combo, stretch=1)
        root.addLayout(selector_row)

        # Metrics
        metrics_form = QFormLayout()
        self._raw_count_label = QLabel("—")
        self._downsampled_label = QLabel("—")
        self._breakpoints_label = QLabel("—")
        self._zones_label = QLabel("—")
        self._rmse_label = QLabel("—")
        self._max_error_label = QLabel("—")
        metrics_form.addRow("Raw пар:", self._raw_count_label)
        metrics_form.addRow("После downsample:", self._downsampled_label)
        metrics_form.addRow("Breakpoints:", self._breakpoints_label)
        metrics_form.addRow("Зон Chebyshev:", self._zones_label)
        metrics_form.addRow("RMSE:", self._rmse_label)
        metrics_form.addRow("Max ошибка:", self._max_error_label)
        root.addLayout(metrics_form)

        # Export buttons
        export_box = QGroupBox("Экспорт")
        apply_group_box_style(export_box)
        export_layout = QHBoxLayout(export_box)
        self._export_330_btn = QPushButton(".330")
        self._export_340_btn = QPushButton(".340")
        self._export_json_btn = QPushButton("JSON")
        self._export_csv_btn = QPushButton("CSV")
        for btn in (self._export_330_btn, self._export_340_btn, self._export_json_btn, self._export_csv_btn):
            apply_button_style(btn, "neutral")
            export_layout.addWidget(btn)
        root.addWidget(export_box)

        # Runtime apply
        apply_box = QGroupBox("Применить")
        apply_group_box_style(apply_box)
        apply_layout = QFormLayout(apply_box)
        self._global_checkbox = QCheckBox("SRDG + calibration curves")
        apply_layout.addRow("Глобально:", self._global_checkbox)
        self._policy_combo = QComboBox()
        self._policy_combo.addItem("Наследовать", "inherit")
        self._policy_combo.addItem("Включить", "on")
        self._policy_combo.addItem("Выключить", "off")
        apply_layout.addRow("Политика канала:", self._policy_combo)
        self._apply_btn = QPushButton("Применить в CryoDAQ")
        apply_button_style(self._apply_btn, "primary")
        apply_layout.addRow(self._apply_btn)

        # Before/after
        self._delta_label = QLabel("")
        self._delta_label.setStyleSheet(f"color: {theme.TEXT_ACCENT};")
        apply_layout.addRow("Δ:", self._delta_label)
        root.addWidget(apply_box)

        self._status = StatusBanner()
        root.addWidget(self._status)

        root.addStretch()  # Results form layout — stretch at bottom is appropriate

    def update_metrics(self, result: dict[str, Any]) -> None:
        self._raw_count_label.setText(f"{result.get('raw_count', 0):,}")
        self._downsampled_label.setText(str(result.get("downsampled_count", "—")))
        self._breakpoints_label.setText(str(result.get("breakpoint_count", "—")))
        m = result.get("metrics", {})
        self._zones_label.setText(str(m.get("zone_count", "—")))
        self._rmse_label.setText(f"{m.get('rmse_k', 0):.4f} K")
        self._max_error_label.setText(f"{m.get('max_abs_error_k', 0):.4f} K")


# ---------------------------------------------------------------------------
# CalibrationPanel — main container
# ---------------------------------------------------------------------------

class CalibrationPanel(QWidget):
    """Three-mode calibration panel with auto-switching."""

    def __init__(
        self,
        instruments_config: Path = _INSTRUMENTS_DEFAULT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._instruments_config = instruments_config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._setup_widget = CalibrationSetupWidget(instruments_config)
        self._acquisition_widget = CalibrationAcquisitionWidget()
        self._results_widget = CalibrationResultsWidget()

        self._stack = QStackedWidget()
        self._stack.addWidget(self._setup_widget)
        self._stack.addWidget(self._acquisition_widget)
        self._stack.addWidget(self._results_widget)
        layout.addWidget(self._stack, stretch=1)

        # Current mode
        self._current_mode = "setup"

        # Mode check timer (async)
        self._mode_worker = None
        self._mode_timer = QTimer(self)
        self._mode_timer.setInterval(3000)
        self._mode_timer.timeout.connect(self._check_mode)
        self._mode_timer.start()

    def on_reading(self, reading: Any) -> None:
        """Forward live readings to acquisition widget if active."""
        if self._current_mode == "acquisition" and hasattr(reading, "channel"):
            ch = reading.channel
            if ch.endswith("_raw") or reading.unit == "sensor_unit":
                live_text = self._acquisition_widget._live_label.text()
                line = f"{ch}: {reading.value:.4f}"
                lines = live_text.split("\n")[-4:] + [line]
                self._acquisition_widget._live_label.setText("\n".join(lines))

    @Slot()
    def _check_mode(self) -> None:
        if self._mode_worker is not None and not self._mode_worker.isFinished():
            return
        from cryodaq.gui.zmq_client import ZmqCommandWorker

        self._mode_worker = ZmqCommandWorker({"cmd": "calibration_acquisition_status"})
        self._mode_worker.finished.connect(self._on_mode_result)
        self._mode_worker.start()

    @Slot(dict)
    def _on_mode_result(self, result: dict) -> None:
        if result.get("ok") and result.get("active"):
            self._current_mode = "acquisition"
            self._stack.setCurrentWidget(self._acquisition_widget)
            self._acquisition_widget.update_stats(result)
        elif self._current_mode == "acquisition":
            # Just deactivated — switch to results
            self._current_mode = "results"
            self._stack.setCurrentWidget(self._results_widget)
        # Otherwise stay in current mode (setup or results)
