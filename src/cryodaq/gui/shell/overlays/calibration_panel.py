"""CalibrationPanel — Phase II.7 three-mode calibration overlay.

Supersedes ``src/cryodaq/gui/widgets/calibration_panel.py``. Preserves
the QStackedWidget three-mode architecture (Setup → Acquisition →
Results) and the 3-second engine-poll mode auto-switch. Wires
previously-dead import / export / runtime-apply buttons to real
ZMQ commands.

Public API (host push points):
- ``on_reading(reading)`` — routes ``_raw`` / ``sensor_unit`` readings
  to the Acquisition widget's live-text area (v1 contract preserved).
- ``set_connected(bool)`` — gates engine-dependent controls; mode poll
  pauses while disconnected.
- ``get_current_mode() -> str`` — public accessor: ``"setup"`` /
  ``"acquisition"`` / ``"results"`` for tests and future host hooks.
- ``is_acquisition_active() -> bool`` — convenience.

Out of scope (follow-ups):
- Δ before/after computation in Results → Apply card — placeholder
  today, Phase III polish.
- Scatter plot of calibration points against the fit — v1 never had
  this either; deferred.
- Assignment workflow (associate curve with channel manually in a
  list view) — engine command exists but no UI yet; deferred.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui.zmq_client import ZmqCommandWorker
from cryodaq.paths import get_config_dir as _get_config_dir

logger = logging.getLogger(__name__)

_INSTRUMENTS_DEFAULT = _get_config_dir() / "instruments.yaml"
_BANNER_AUTO_CLEAR_MS = 4000
_MODE_POLL_INTERVAL_MS = 3000
_COVERAGE_BAR_HEIGHT = 24


# ---------------------------------------------------------------------------
# Helpers (copied from v1 — legacy dies together in Phase III.3)
# ---------------------------------------------------------------------------


def _strip_instrument_prefix(channel_ref: str) -> str:
    """Strip ``instrument_id:`` prefix from a channel reference string."""
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
# Font / styling helpers
# ---------------------------------------------------------------------------


def _label_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
    return font


def _body_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_BODY_SIZE)
    return font


def _title_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_XL)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _section_title_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_LG)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _mono_value_font() -> QFont:
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return font


def _style_button(btn: QPushButton, variant: str) -> None:
    if variant == "primary":
        # Phase III.A: primary uses ACCENT (UI activation), not STATUS_OK.
        bg, fg = theme.ACCENT, theme.ON_ACCENT
    elif variant == "warning":
        bg, fg = theme.STATUS_WARNING, theme.ON_PRIMARY
    elif variant == "accent":
        bg, fg = theme.ACCENT, theme.ON_ACCENT
    else:  # "neutral"
        bg, fg = theme.SURFACE_MUTED, theme.FOREGROUND
    btn.setStyleSheet(
        f"QPushButton {{"
        f" background-color: {bg};"
        f" color: {fg};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {theme.RADIUS_MD}px;"
        f" padding: {theme.SPACE_1}px {theme.SPACE_3}px;"
        f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        f"}}"
        f" QPushButton:disabled {{"
        f" background-color: {theme.SURFACE_MUTED};"
        f" color: {theme.MUTED_FOREGROUND};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f"}}"
    )


def _style_input(widget: QComboBox | QCheckBox | QPlainTextEdit) -> None:
    widget.setStyleSheet(
        f"QComboBox, QPlainTextEdit {{"
        f" background-color: {theme.SURFACE_SUNKEN};"
        f" color: {theme.FOREGROUND};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {theme.RADIUS_SM}px;"
        f" padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
        f"}}"
        f" QComboBox:disabled, QPlainTextEdit:disabled {{"
        f" color: {theme.MUTED_FOREGROUND};"
        f"}} "
        f"QCheckBox {{"
        f" color: {theme.FOREGROUND};"
        f" background: transparent;"
        f"}}"
    )


def _card_qss(object_name: str) -> str:
    return (
        f"#{object_name} {{"
        f" background-color: {theme.SURFACE_CARD};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {theme.RADIUS_MD}px;"
        f"}}"
    )


# ---------------------------------------------------------------------------
# CoverageBar — DS tokens (not hardcoded hex) per RULE-COLOR-010
# ---------------------------------------------------------------------------


class CoverageBar(QWidget):
    """Horizontal density bar: paints one segment per bin, colored by
    coverage status. Status colors come from DS tokens, not the legacy
    hex set, per RULE-COLOR-010.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(_COVERAGE_BAR_HEIGHT)
        self._bins: list[dict[str, Any]] = []

    def set_coverage(self, bins: list[dict[str, Any]]) -> None:
        self._bins = bins
        self.update()

    @staticmethod
    def _color_for(status: str) -> QColor:
        if status == "dense":
            return QColor(theme.STATUS_OK)
        if status == "medium":
            return QColor(theme.STATUS_CAUTION)
        if status == "sparse":
            return QColor(theme.STATUS_WARNING)
        return QColor(theme.MUTED_FOREGROUND)

    def paintEvent(self, event: object) -> None:  # noqa: ANN001 — Qt override
        if not self._bins:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        n = len(self._bins)
        seg_w = max(1, w // n)
        for i, b in enumerate(self._bins):
            painter.fillRect(i * seg_w, 0, seg_w, h, self._color_for(str(b.get("status", "empty"))))
        painter.end()


# ---------------------------------------------------------------------------
# Setup widget
# ---------------------------------------------------------------------------


class _SetupWidget(QWidget):
    """Setup mode: reference + targets selection, import, existing curves."""

    start_requested = Signal(str, list)  # reference_channel, target_channels
    import_result = Signal(dict)
    curves_refreshed = Signal(list)

    def __init__(
        self,
        instruments_config: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._instruments_config = instruments_config
        self._instrument_groups = _load_lakeshore_channels(instruments_config)
        self._all_channels: list[str] = []
        self._target_checkboxes: dict[str, QCheckBox] = {}
        self._workers: list[ZmqCommandWorker] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_params_card())
        root.addWidget(self._build_import_card())
        root.addWidget(self._build_curves_card(), stretch=1)

    def _build_params_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("calibParamsCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("calibParamsCard"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Параметры калибровки")
        title.setFont(_section_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        ref_row = QHBoxLayout()
        ref_row.setContentsMargins(0, 0, 0, 0)
        ref_row.setSpacing(theme.SPACE_2)
        ref_cap = QLabel("Опорный канал:")
        ref_cap.setFont(_label_font())
        ref_cap.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        ref_row.addWidget(ref_cap)

        self._reference_combo = QComboBox()
        for group in self._instrument_groups:
            for ch in group["channels"]:
                self._all_channels.append(ch)
                self._reference_combo.addItem(ch)
        if not self._all_channels:
            self._reference_combo.addItem("Нет LakeShore каналов")
            self._reference_combo.setEnabled(False)
        _style_input(self._reference_combo)
        ref_row.addWidget(self._reference_combo, stretch=1)
        layout.addLayout(ref_row)

        # Target groups
        for group in self._instrument_groups:
            gb = QGroupBox(group["instrument"])
            gb.setStyleSheet(
                f"QGroupBox {{"
                f" color: {theme.MUTED_FOREGROUND};"
                f" border: 1px solid {theme.BORDER_SUBTLE};"
                f" border-radius: {theme.RADIUS_SM}px;"
                f" margin-top: {theme.SPACE_3}px;"
                f" padding: {theme.SPACE_2}px;"
                f"}} "
                f"QGroupBox::title {{"
                f" subcontrol-origin: margin;"
                f" left: {theme.SPACE_2}px;"
                f" padding: 0 {theme.SPACE_1}px;"
                f"}}"
            )
            gb_layout = QHBoxLayout(gb)
            gb_layout.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2, theme.SPACE_2)
            gb_layout.setSpacing(theme.SPACE_2)
            for ch in group["channels"]:
                cb = QCheckBox(ch.split(":")[-1])
                cb.setChecked(True)
                cb.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent;")
                self._target_checkboxes[ch] = cb
                gb_layout.addWidget(cb)
            layout.addWidget(gb)

        note = QLabel("Опорный канал автоматически исключается из целевых.")
        note.setFont(_label_font())
        note.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(note)

        self._start_btn = QPushButton("Начать калибровочный прогон")
        _style_button(self._start_btn, "primary")
        self._start_btn.clicked.connect(self._on_start_clicked)
        if not self._all_channels:
            self._start_btn.setEnabled(False)
        layout.addWidget(self._start_btn)

        return card

    def _build_import_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("calibImportCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("calibImportCard"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Импорт внешней кривой")
        title.setFont(_section_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(theme.SPACE_2)
        self._import_340_btn = QPushButton("Импорт .340")
        self._import_json_btn = QPushButton("Импорт JSON")
        for btn, file_filter in (
            (self._import_340_btn, "LakeShore .340 (*.340)"),
            (self._import_json_btn, "JSON (*.json)"),
        ):
            _style_button(btn, "neutral")
            btn.clicked.connect(lambda _checked=False, f=file_filter: self._on_import_clicked(f))
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return card

    def _build_curves_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("calibCurvesCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("calibCurvesCard"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Существующие кривые")
        title.setFont(_section_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        self._curves_table = QTableWidget(0, 5)
        self._curves_table.setHorizontalHeaderLabels(
            ["Датчик", "Curve ID", "Зон", "RMSE", "Источник"]
        )
        self._curves_table.verticalHeader().setVisible(False)
        self._curves_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._curves_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._curves_table.setFont(_body_font())
        self._curves_table.setStyleSheet(
            f"QTableWidget {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" color: {theme.FOREGROUND};"
            f" gridline-color: {theme.BORDER_SUBTLE};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f"}} "
            f"QHeaderView::section {{"
            f" background-color: {theme.SURFACE_MUTED};"
            f" color: {theme.MUTED_FOREGROUND};"
            f" border: 0px;"
            f" border-bottom: 1px solid {theme.BORDER_SUBTLE};"
            f" padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
            f"}}"
        )
        layout.addWidget(self._curves_table, stretch=1)
        return card

    # -----------------------------------------------------------------
    # Button handlers
    # -----------------------------------------------------------------

    def _on_start_clicked(self) -> None:
        ref = self._reference_combo.currentText()
        if not ref or ref == "Нет LakeShore каналов":
            self.start_requested.emit("", [])
            return
        targets = self.get_selected_targets()
        self.start_requested.emit(ref, targets)

    def _on_import_clicked(self, file_filter: str) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Импорт калибровочной кривой", "", file_filter
        )
        if not path_str:
            return
        worker = ZmqCommandWorker(
            {"cmd": "calibration_curve_import", "path": path_str}, parent=self
        )
        worker.finished.connect(self._on_import_result)
        self._workers.append(worker)
        worker.start()

    def _on_import_result(self, result: dict) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        self.import_result.emit(result)

    def get_selected_targets(self) -> list[str]:
        ref = self._reference_combo.currentText()
        return [ch for ch, cb in self._target_checkboxes.items() if cb.isChecked() and ch != ref]

    def refresh_curves(self) -> None:
        """Dispatch calibration_curve_list; populate table on result."""
        worker = ZmqCommandWorker({"cmd": "calibration_curve_list"}, parent=self)
        worker.finished.connect(self._on_curves_list_result)
        self._workers.append(worker)
        worker.start()

    def _on_curves_list_result(self, result: dict) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        if not result.get("ok"):
            self.curves_refreshed.emit([])
            return
        curves = list(result.get("curves", []))
        self._populate_curves_table(curves)
        self.curves_refreshed.emit(curves)

    def _populate_curves_table(self, curves: list[dict]) -> None:
        mono = _mono_value_font()

        def _cell(text: str, *, mono_font: bool = False) -> QTableWidgetItem:
            item = QTableWidgetItem(text)
            if mono_font:
                item.setFont(mono)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return item

        self._curves_table.setRowCount(len(curves))
        for row, curve in enumerate(curves):
            self._curves_table.setItem(row, 0, _cell(str(curve.get("sensor_id", ""))))
            self._curves_table.setItem(
                row, 1, _cell(str(curve.get("curve_id", "")), mono_font=True)
            )
            metrics = curve.get("metrics", {}) or {}
            self._curves_table.setItem(
                row, 2, _cell(str(metrics.get("zone_count", "—")), mono_font=True)
            )
            rmse = metrics.get("rmse_k")
            rmse_text = f"{rmse:.4f}" if isinstance(rmse, (int, float)) else "—"
            self._curves_table.setItem(row, 3, _cell(rmse_text, mono_font=True))
            self._curves_table.setItem(row, 4, _cell(str(curve.get("source", ""))))

    def set_engine_enabled(self, enabled: bool) -> None:
        """Gate engine-dependent controls on connection state."""
        self._start_btn.setEnabled(enabled and bool(self._all_channels))
        self._import_340_btn.setEnabled(enabled)
        self._import_json_btn.setEnabled(enabled)


# ---------------------------------------------------------------------------
# Acquisition widget
# ---------------------------------------------------------------------------


class _AcquisitionWidget(QWidget):
    """Acquisition mode: live stats + coverage bar + last readings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_stats_card())
        root.addWidget(self._build_coverage_card())
        root.addWidget(self._build_live_card(), stretch=1)

        note = QLabel(
            "Запись идёт автоматически. Дождитесь полного cooldown, затем завершите эксперимент."
        )
        note.setFont(_label_font())
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        root.addWidget(note)

    def _build_stats_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("calibStatsCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("calibStatsCard"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Сбор данных — активен")
        title.setFont(_section_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(theme.SPACE_3)
        form.setVerticalSpacing(theme.SPACE_1)
        self._experiment_label = self._make_value_label("—")
        self._elapsed_label = self._make_value_label("—")
        self._point_count_label = self._make_value_label("0", mono=True)
        self._temp_range_label = self._make_value_label("— K", mono=True)
        form.addRow(self._make_caption_label("Эксперимент:"), self._experiment_label)
        form.addRow(self._make_caption_label("Время:"), self._elapsed_label)
        form.addRow(self._make_caption_label("Точек записано:"), self._point_count_label)
        form.addRow(self._make_caption_label("Диапазон T_ref:"), self._temp_range_label)
        layout.addLayout(form)
        return card

    def _build_coverage_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("calibCoverageCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("calibCoverageCard"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Покрытие по температуре")
        title.setFont(_section_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        self._coverage_bar = CoverageBar()
        layout.addWidget(self._coverage_bar)

        legend = QLabel("dense (>10 pts/K)   medium (3-10 pts/K)   sparse (<3 pts/K)   empty")
        legend.setFont(_label_font())
        legend.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(legend)
        return card

    def _build_live_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("calibLiveCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("calibLiveCard"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Последние значения")
        title.setFont(_section_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        self._live_text = QPlainTextEdit()
        self._live_text.setReadOnly(True)
        self._live_text.setFont(_mono_value_font())
        self._live_text.setMaximumBlockCount(5)
        self._live_text.setFixedHeight(96)
        _style_input(self._live_text)
        layout.addWidget(self._live_text)
        return card

    @staticmethod
    def _make_caption_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(_label_font())
        lbl.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        return lbl

    @staticmethod
    def _make_value_label(text: str, *, mono: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(_mono_value_font() if mono else _body_font())
        lbl.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        return lbl

    def update_stats(self, stats: dict[str, Any]) -> None:
        exp_name = stats.get("experiment_name") or stats.get("experiment_id")
        if exp_name:
            self._experiment_label.setText(str(exp_name))
        elapsed = stats.get("elapsed_s")
        if isinstance(elapsed, (int, float)) and elapsed >= 0:
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            self._elapsed_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        pc = stats.get("point_count", 0)
        self._point_count_label.setText(f"{pc:,}")
        t_min = stats.get("t_min")
        t_max = stats.get("t_max")
        if t_min is not None and t_max is not None:
            self._temp_range_label.setText(f"{t_min:.1f} — {t_max:.1f} K")

    def update_coverage(self, bins: list[dict[str, Any]]) -> None:
        self._coverage_bar.set_coverage(bins)

    def append_live_reading(self, channel: str, value: float) -> None:
        self._live_text.appendPlainText(f"{channel}: {value:.4f}")


# ---------------------------------------------------------------------------
# Results widget
# ---------------------------------------------------------------------------


class _ResultsWidget(QWidget):
    """Results mode: metrics, export, runtime apply."""

    metrics_requested = Signal(str)  # sensor_id
    export_requested = Signal(str, str, str)  # sensor_id, format_key, path
    runtime_apply_requested = Signal(dict)  # {global_mode?, policy?, channel_key, sensor_id}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._workers: list[ZmqCommandWorker] = []
        self._current_sensor_id: str = ""
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_channel_card())
        root.addWidget(self._build_metrics_card())
        root.addWidget(self._build_export_card())
        root.addWidget(self._build_apply_card())
        root.addStretch()

    def _build_channel_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("calibChannelCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("calibChannelCard"))
        layout = QHBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        layout.setSpacing(theme.SPACE_2)

        cap = QLabel("Канал:")
        cap.setFont(_label_font())
        cap.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(cap)

        self._channel_combo = QComboBox()
        _style_input(self._channel_combo)
        self._channel_combo.currentTextChanged.connect(self._on_channel_changed)
        layout.addWidget(self._channel_combo, stretch=1)
        return card

    def _build_metrics_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("calibMetricsCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("calibMetricsCard"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Метрики подгонки")
        title.setFont(_section_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(theme.SPACE_3)
        form.setVerticalSpacing(theme.SPACE_1)
        self._raw_count_label = _AcquisitionWidget._make_value_label("—", mono=True)
        self._downsampled_label = _AcquisitionWidget._make_value_label("—", mono=True)
        self._breakpoints_label = _AcquisitionWidget._make_value_label("—", mono=True)
        self._zones_label = _AcquisitionWidget._make_value_label("—", mono=True)
        self._rmse_label = _AcquisitionWidget._make_value_label("—", mono=True)
        self._max_error_label = _AcquisitionWidget._make_value_label("—", mono=True)
        form.addRow(_AcquisitionWidget._make_caption_label("Raw пар:"), self._raw_count_label)
        form.addRow(
            _AcquisitionWidget._make_caption_label("После downsample:"),
            self._downsampled_label,
        )
        form.addRow(
            _AcquisitionWidget._make_caption_label("Breakpoints:"),
            self._breakpoints_label,
        )
        form.addRow(
            _AcquisitionWidget._make_caption_label("Зон Chebyshev:"),
            self._zones_label,
        )
        form.addRow(_AcquisitionWidget._make_caption_label("RMSE:"), self._rmse_label)
        form.addRow(
            _AcquisitionWidget._make_caption_label("Max ошибка:"),
            self._max_error_label,
        )
        layout.addLayout(form)
        return card

    def _build_export_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("calibExportCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("calibExportCard"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Экспорт кривой")
        title.setFont(_section_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(theme.SPACE_2)
        self._export_cof_btn = QPushButton(".cof")
        self._export_340_btn = QPushButton(".340")
        self._export_json_btn = QPushButton("JSON")
        self._export_csv_btn = QPushButton("CSV")
        for btn, format_key, file_filter in (
            (self._export_cof_btn, "curve_cof_path", "Chebyshev .cof (*.cof)"),
            (self._export_340_btn, "curve_340_path", "LakeShore .340 (*.340)"),
            (self._export_json_btn, "json_path", "JSON (*.json)"),
            (self._export_csv_btn, "table_path", "CSV (*.csv)"),
        ):
            _style_button(btn, "neutral")
            btn.clicked.connect(
                lambda _checked=False, fk=format_key, ff=file_filter: self._on_export_clicked(
                    fk, ff
                )
            )
            btn_row.addWidget(btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return card

    def _build_apply_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("calibApplyCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(_card_qss("calibApplyCard"))
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("Применить в CryoDAQ")
        title.setFont(_section_title_font())
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)

        self._global_checkbox = QCheckBox("SRDG + calibration curves (глобально)")
        self._global_checkbox.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent;")
        layout.addWidget(self._global_checkbox)

        policy_row = QHBoxLayout()
        policy_row.setContentsMargins(0, 0, 0, 0)
        policy_row.setSpacing(theme.SPACE_2)
        policy_cap = QLabel("Политика канала:")
        policy_cap.setFont(_label_font())
        policy_cap.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        policy_row.addWidget(policy_cap)

        self._policy_combo = QComboBox()
        self._policy_combo.addItem("Наследовать", "inherit")
        self._policy_combo.addItem("Включить", "on")
        self._policy_combo.addItem("Выключить", "off")
        _style_input(self._policy_combo)
        policy_row.addWidget(self._policy_combo, stretch=1)
        layout.addLayout(policy_row)

        self._apply_btn = QPushButton("Применить")
        _style_button(self._apply_btn, "primary")
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        layout.addWidget(self._apply_btn)

        # Δ before/after placeholder — Phase III polish.
        self._delta_label = QLabel("")
        self._delta_label.setFont(_label_font())
        self._delta_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        self._delta_label.setVisible(False)
        layout.addWidget(self._delta_label)
        return card

    # -----------------------------------------------------------------
    # Handlers
    # -----------------------------------------------------------------

    def _on_channel_changed(self, channel: str) -> None:
        channel = channel.strip()
        if not channel:
            return
        sensor_id = _strip_instrument_prefix(channel)
        self._current_sensor_id = sensor_id
        self.metrics_requested.emit(sensor_id)
        worker = ZmqCommandWorker(
            {"cmd": "calibration_curve_get", "sensor_id": sensor_id}, parent=self
        )
        worker.finished.connect(self._on_metrics_result)
        self._workers.append(worker)
        worker.start()

    def _on_metrics_result(self, result: dict) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        if not result.get("ok"):
            return
        curve = result.get("curve") or {}
        self.update_metrics(curve)

    def update_metrics(self, curve: dict[str, Any]) -> None:
        self._raw_count_label.setText(f"{int(curve.get('raw_count', 0)):,}")
        ds = curve.get("downsampled_count")
        self._downsampled_label.setText(str(ds) if ds is not None else "—")
        bp = curve.get("breakpoint_count")
        self._breakpoints_label.setText(str(bp) if bp is not None else "—")
        metrics = curve.get("metrics", {}) or {}
        zc = metrics.get("zone_count")
        self._zones_label.setText(str(zc) if zc is not None else "—")
        rmse = metrics.get("rmse_k")
        self._rmse_label.setText(f"{rmse:.4f} K" if isinstance(rmse, (int, float)) else "—")
        maxe = metrics.get("max_abs_error_k")
        self._max_error_label.setText(f"{maxe:.4f} K" if isinstance(maxe, (int, float)) else "—")

    def _on_export_clicked(self, format_key: str, file_filter: str) -> None:
        if not self._current_sensor_id:
            self.export_requested.emit("", format_key, "")
            return
        path_str, _ = QFileDialog.getSaveFileName(
            self, "Экспорт калибровочной кривой", "", file_filter
        )
        if not path_str:
            return
        self.export_requested.emit(self._current_sensor_id, format_key, path_str)
        worker = ZmqCommandWorker(
            {
                "cmd": "calibration_curve_export",
                "sensor_id": self._current_sensor_id,
                format_key: path_str,
            },
            parent=self,
        )
        worker.finished.connect(self._on_export_result_internal)
        self._workers.append(worker)
        worker.start()

    _last_export_result: dict | None = None

    def _on_export_result_internal(self, result: dict) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        _ResultsWidget._last_export_result = result

    def _on_apply_clicked(self) -> None:
        if not self._current_sensor_id:
            self.runtime_apply_requested.emit({"error": "no_channel"})
            return
        channel_text = self._channel_combo.currentText()
        channel_key = _strip_instrument_prefix(channel_text)
        payload = {
            "sensor_id": self._current_sensor_id,
            "channel_key": channel_key,
            "global_toggle": self._global_checkbox.isChecked(),
            "policy": self._policy_combo.currentData() or "inherit",
        }
        self.runtime_apply_requested.emit(payload)

    def set_channels(self, channels: list[str]) -> None:
        self._channel_combo.blockSignals(True)
        self._channel_combo.clear()
        for ch in channels:
            self._channel_combo.addItem(ch)
        self._channel_combo.blockSignals(False)
        if channels:
            self._on_channel_changed(self._channel_combo.currentText())

    def set_engine_enabled(self, enabled: bool) -> None:
        """Gate engine-dependent controls on connection state.
        Export buttons stay clickable (they need a file dialog first);
        the worker gate prevents the command from firing without
        connection via the shell's auto-pause path."""
        self._export_cof_btn.setEnabled(enabled)
        self._export_340_btn.setEnabled(enabled)
        self._export_json_btn.setEnabled(enabled)
        self._export_csv_btn.setEnabled(enabled)
        self._apply_btn.setEnabled(enabled)


# ---------------------------------------------------------------------------
# Main overlay container
# ---------------------------------------------------------------------------


class CalibrationPanel(QWidget):
    """Three-mode calibration overlay (Phase II.7)."""

    def __init__(
        self,
        instruments_config: Path = _INSTRUMENTS_DEFAULT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._instruments_config = instruments_config
        self._connected: bool = False
        self._current_mode: str = "setup"
        self._mode_worker: ZmqCommandWorker | None = None
        self._apply_workers: list[ZmqCommandWorker] = []

        self.setObjectName("calibrationPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#calibrationPanel {{ background-color: {theme.BACKGROUND}; }}")

        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.setInterval(_BANNER_AUTO_CLEAR_MS)
        self._banner_timer.timeout.connect(self.clear_message)

        self._build_ui()

        # Default state is disconnected — gate engine-dependent controls
        # from the start so a cold-open overlay doesn't show
        # false-positive enabled buttons before MainWindowV2 replays
        # the real connection state.
        self._setup_widget.set_engine_enabled(False)
        self._results_widget.set_engine_enabled(False)

        self._mode_timer = QTimer(self)
        self._mode_timer.setInterval(_MODE_POLL_INTERVAL_MS)
        self._mode_timer.timeout.connect(self._check_mode)
        # Poll only when connected — shell drives start/stop via set_connected.

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_header())
        root.addWidget(self._build_banner())

        self._setup_widget = _SetupWidget(self._instruments_config)
        self._acquisition_widget = _AcquisitionWidget()
        self._results_widget = _ResultsWidget()

        self._setup_widget.start_requested.connect(self._on_start_requested)
        self._setup_widget.import_result.connect(self._on_import_result)
        self._setup_widget.curves_refreshed.connect(self._on_curves_refreshed)
        self._results_widget.export_requested.connect(self._on_export_requested)
        self._results_widget.runtime_apply_requested.connect(self._on_runtime_apply_requested)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._setup_widget)
        self._stack.addWidget(self._acquisition_widget)
        self._stack.addWidget(self._results_widget)
        root.addWidget(self._stack, stretch=1)

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("КАЛИБРОВКА ДАТЧИКОВ")
        title.setFont(_title_font())
        title.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
            f" letter-spacing: 1px;"
        )
        layout.addWidget(title)
        layout.addStretch()
        return header

    def _build_banner(self) -> QWidget:
        self._banner_label = QLabel("")
        self._banner_label.setFont(_label_font())
        self._banner_label.setObjectName("calibrationBanner")
        self._banner_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._banner_label.setContentsMargins(
            theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1
        )
        self._banner_label.setVisible(False)
        return self._banner_label

    # ------------------------------------------------------------------
    # Mode poll
    # ------------------------------------------------------------------

    @Slot()
    def _check_mode(self) -> None:
        if self._mode_worker is not None and self._mode_worker.isRunning():
            return
        if not self._connected:
            return
        worker = ZmqCommandWorker({"cmd": "calibration_acquisition_status"}, parent=self)
        worker.finished.connect(self._on_mode_result)
        self._mode_worker = worker
        worker.start()

    @Slot(dict)
    def _on_mode_result(self, result: dict) -> None:
        self._mode_worker = None
        if not result.get("ok"):
            return
        if result.get("active"):
            self._switch_mode("acquisition")
            self._acquisition_widget.update_stats(result)
            bins = result.get("coverage_bins") or []
            if bins:
                self._acquisition_widget.update_coverage(bins)
        elif self._current_mode == "acquisition":
            # Just deactivated — transition to results.
            target_channels = result.get("target_channels") or []
            self._results_widget.set_channels(list(target_channels))
            self._switch_mode("results")
        # Else stay in current mode.

    def _switch_mode(self, mode: str) -> None:
        if mode == self._current_mode:
            return
        self._current_mode = mode
        if mode == "setup":
            self._stack.setCurrentWidget(self._setup_widget)
        elif mode == "acquisition":
            self._stack.setCurrentWidget(self._acquisition_widget)
        elif mode == "results":
            self._stack.setCurrentWidget(self._results_widget)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_start_requested(self, reference: str, targets: list) -> None:
        if not reference:
            self.show_warning("Выберите опорный канал.")
            return
        if not targets:
            self.show_warning("Выберите хотя бы один целевой канал.")
            return
        from datetime import datetime

        name = f"Calibration-{datetime.now().strftime('%Y-%m-%d-%H-%M')}"
        worker = ZmqCommandWorker(
            {
                "cmd": "experiment_start",
                "template_id": "calibration",
                "name": name,
                "title": name,
                "operator": "",
                "custom_fields": {
                    "reference_channel": _strip_instrument_prefix(reference),
                    "target_channels": ", ".join(_strip_instrument_prefix(t) for t in targets),
                },
            },
            parent=self,
        )
        worker.finished.connect(self._on_start_result)
        self._apply_workers.append(worker)
        worker.start()
        self.show_info("Запускаем калибровочный прогон...")

    def _on_start_result(self, result: dict) -> None:
        self._apply_workers = [w for w in self._apply_workers if w.isRunning()]
        if result.get("ok"):
            self.show_info("Калибровочный прогон начат.")
        else:
            self.show_error(str(result.get("error", "Не удалось начать прогон.")))

    def _on_import_result(self, result: dict) -> None:
        if not result.get("ok"):
            self.show_error(str(result.get("error", "Не удалось импортировать кривую.")))
            return
        curve = result.get("curve", {}) or {}
        cid = curve.get("curve_id") or curve.get("sensor_id", "?")
        self.show_info(f"Кривая импортирована: {cid}")
        # Reload existing-curves table.
        self._setup_widget.refresh_curves()

    def _on_curves_refreshed(self, _curves: list) -> None:
        pass  # hook reserved; table already populated by _SetupWidget

    def _on_export_requested(self, sensor_id: str, format_key: str, path: str) -> None:
        if not sensor_id:
            self.show_error("Выберите канал перед экспортом.")
            return
        # The worker inside _ResultsWidget fires the engine command; we
        # only surface the outcome via banner.
        # Poll the widget's last-result slot after a short delay.
        QTimer.singleShot(100, self._surface_export_banner)
        # Compose placeholder info — engine is eager and writes all formats.
        self.show_info(f"Экспорт {format_key} → {path}")

    def _surface_export_banner(self) -> None:
        result = _ResultsWidget._last_export_result
        if result is None:
            return
        _ResultsWidget._last_export_result = None
        if not result.get("ok"):
            self.show_error(str(result.get("error", "Не удалось экспортировать кривую.")))

    def _on_runtime_apply_requested(self, payload: dict) -> None:
        if payload.get("error") == "no_channel":
            self.show_error("Выберите канал перед применением.")
            return
        channel_key = payload.get("channel_key", "")
        sensor_id = payload.get("sensor_id", "")
        policy = payload.get("policy") or "inherit"
        global_toggle = bool(payload.get("global_toggle"))

        self.show_info("Применяем настройки...")

        # Step 1: global mode (if toggled). Step 2: channel policy.
        # Both run in sequence; first result gates the second via chained
        # finished signals to avoid interleaved banner updates.
        if global_toggle:
            worker = ZmqCommandWorker(
                {
                    "cmd": "calibration_runtime_set_global",
                    "global_mode": "on" if global_toggle else "off",
                },
                parent=self,
            )
            worker.finished.connect(
                lambda result: self._after_global_set(result, sensor_id, channel_key, policy)
            )
            self._apply_workers.append(worker)
            worker.start()
        else:
            self._dispatch_channel_policy(sensor_id, channel_key, policy)

    def _after_global_set(
        self, result: dict, sensor_id: str, channel_key: str, policy: str
    ) -> None:
        self._apply_workers = [w for w in self._apply_workers if w.isRunning()]
        if not result.get("ok"):
            self.show_error(str(result.get("error", "Не удалось установить глобальный режим.")))
            return
        self._dispatch_channel_policy(sensor_id, channel_key, policy)

    def _dispatch_channel_policy(self, sensor_id: str, channel_key: str, policy: str) -> None:
        # Look up curve_id for this channel so set_channel_policy has the
        # linkage; runs asynchronously, then fires the policy command.
        lookup_worker = ZmqCommandWorker(
            {"cmd": "calibration_curve_lookup", "channel_key": channel_key},
            parent=self,
        )
        lookup_worker.finished.connect(
            lambda result: self._after_lookup_for_policy(result, sensor_id, channel_key, policy)
        )
        self._apply_workers.append(lookup_worker)
        lookup_worker.start()

    def _after_lookup_for_policy(
        self, result: dict, sensor_id: str, channel_key: str, policy: str
    ) -> None:
        self._apply_workers = [w for w in self._apply_workers if w.isRunning()]
        curve_id = ""
        if result.get("ok"):
            assignment = result.get("assignment") or {}
            curve_id = str(assignment.get("curve_id", ""))
        worker = ZmqCommandWorker(
            {
                "cmd": "calibration_runtime_set_channel_policy",
                "channel_key": channel_key,
                "policy": policy,
                "sensor_id": sensor_id,
                "curve_id": curve_id,
            },
            parent=self,
        )
        worker.finished.connect(self._on_apply_channel_policy_result)
        self._apply_workers.append(worker)
        worker.start()

    def _on_apply_channel_policy_result(self, result: dict) -> None:
        self._apply_workers = [w for w in self._apply_workers if w.isRunning()]
        if result.get("ok"):
            self.show_info("Политика канала применена.")
        else:
            self.show_error(str(result.get("error", "Не удалось применить политику канала.")))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        """Route live readings to the acquisition widget when in
        acquisition mode. Filter matches v1: `_raw` channel suffix OR
        `sensor_unit` unit — these are the raw-ADC readings that
        SRDG/KRDG calibration bookkeeping cares about.
        """
        if self._current_mode != "acquisition":
            return
        ch = reading.channel
        if not ch:
            return
        if ch.endswith("_raw") or reading.unit == "sensor_unit":
            try:
                value = float(reading.value)
            except (TypeError, ValueError):
                return
            self._acquisition_widget.append_live_reading(ch, value)

    def set_connected(self, connected: bool) -> None:
        if connected == self._connected:
            return
        self._connected = connected
        self._setup_widget.set_engine_enabled(connected)
        self._results_widget.set_engine_enabled(connected)
        if connected:
            self.clear_message()
            self._mode_timer.start()
            # Load curves list immediately on first connect.
            self._setup_widget.refresh_curves()
        else:
            self._mode_timer.stop()
            self.show_error("Нет связи с engine")

    def get_current_mode(self) -> str:
        return self._current_mode

    def is_acquisition_active(self) -> bool:
        return self._current_mode == "acquisition"

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------

    def show_info(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_INFO)

    def show_warning(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_WARNING)

    def show_error(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_FAULT)

    def clear_message(self) -> None:
        self._banner_label.setText("")
        self._banner_label.setVisible(False)
        self._banner_timer.stop()

    def _set_banner(self, text: str, color: str) -> None:
        self._banner_label.setText(text)
        self._banner_label.setStyleSheet(
            f"#calibrationBanner {{"
            f" color: {theme.FOREGROUND};"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {color};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )
        self._banner_label.setVisible(True)
        self._banner_timer.start()
