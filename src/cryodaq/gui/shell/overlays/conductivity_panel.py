"""ConductivityPanel — Phase II.5 thermal conductivity overlay.

Supersedes the v1 widget at ``src/cryodaq/gui/widgets/conductivity_panel.py``.
Aligned with Design System v1.0.1 tokens. Preserves the auto-sweep
state machine verbatim (operationally critical — drives real
power-stepping experiments), preserves the flight recorder CSV schema
(operators rely on it for post-hoc analysis), exposes
``get_auto_state()`` / ``is_auto_sweep_active()`` as public accessors
for the ExperimentOverlay finalize guard (II.9 follow-up wiring).

Layout (top to bottom):
    Header (ТЕПЛОПРОВОДНОСТЬ)
    Status banner (transient info/warning/error, auto-clear 4 s)
    Main split: Chain card | Live card (banner + indicators + R/G table + plot)
    Auto-sweep card (P parameters + Start/Stop + progress + status)

Public API (host push points):
- ``on_reading(reading)`` — handles T-prefixed K readings AND
  ``/smu*/power`` readings per existing shell routing contract.
- ``set_connected(bool)`` — gates auto-sweep Start + shows banner.
  Chain selection / CSV export stay enabled (local work).
- ``get_auto_state() -> str`` — returns ``"idle"`` / ``"stabilizing"`` /
  ``"done"`` for external finalize guards. Mirrors legacy
  ``_auto_state`` accessor but via a stable public API.
- ``is_auto_sweep_active() -> bool`` — convenience (state == "stabilizing").

Out of scope (follow-ups):
- Additional export formats (HDF5, Parquet).
- Per-chain-pair independent power sweeps.
- Auto-sweep resume after restart (power list regenerated on each Start).
"""

from __future__ import annotations

import csv
import logging
import math
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cryodaq.analytics.steady_state import SteadyStatePredictor
from cryodaq.core.channel_manager import get_channel_manager
from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style, series_pen
from cryodaq.gui.zmq_client import ZmqCommandWorker

logger = logging.getLogger(__name__)

_BUFFER_MAXLEN = 3600
_RATE_BUFFER_MAXLEN = 120
_STABILITY_THRESHOLD = 0.01  # К/мин
_BANNER_AUTO_CLEAR_MS = 4000
_REFRESH_INTERVAL_MS = 1000
_AUTO_TIMER_INTERVAL_MS = 1000

_COL_HEADERS: tuple[str, ...] = (
    "Пара",
    "T гор. (К)",
    "T хол. (К)",
    "dT (К)",
    "R (К/Вт)",
    "G (Вт/К)",
    "T∞ прогноз",
    "τ (мин)",
    "Готово %",
    "R прогноз",
    "G прогноз",
)

_POWER_CHANNELS: tuple[str, ...] = (
    "Keithley_1/smua/power",
    "Keithley_1/smub/power",
)


def _get_temperature_channels() -> list[tuple[str, str]]:
    """List visible T-prefixed channels as (id, display_name) tuples."""
    mgr = get_channel_manager()
    return [
        (ch_id, mgr.get_display_name(ch_id))
        for ch_id in mgr.get_all_visible()
        if ch_id.startswith("Т")
    ]


def _pct_color(pct: float) -> str:
    if pct >= 99.0:
        return theme.STATUS_OK
    if pct >= 90.0:
        return theme.STATUS_CAUTION
    return theme.STATUS_FAULT


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


def _mono_value_font() -> QFont:
    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_MONO_VALUE_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_MONO_VALUE_WEIGHT))
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        pass
    return font


def _mono_cell_font() -> QFont:
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


def _style_input(widget: QDoubleSpinBox | QSpinBox | QComboBox) -> None:
    widget.setStyleSheet(
        f"QDoubleSpinBox, QSpinBox, QComboBox {{"
        f" background-color: {theme.SURFACE_SUNKEN};"
        f" color: {theme.FOREGROUND};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f" border-radius: {theme.RADIUS_SM}px;"
        f" padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
        f"}}"
        f" QDoubleSpinBox:disabled, QSpinBox:disabled, QComboBox:disabled {{"
        f" color: {theme.MUTED_FOREGROUND};"
        f"}}"
    )


class ConductivityPanel(QWidget):
    """Thermal conductivity overlay (Phase II.5)."""

    _reading_signal = Signal(object)

    auto_sweep_started = Signal()
    auto_sweep_completed = Signal(int)
    auto_sweep_aborted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._connected: bool = False
        self._temps: dict[str, float] = {}
        self._power: float = 0.0
        # IV.2 A.1: distinguish "never received a reading" from "received P=0".
        # Without this flag the refresh tick renders "P = 0 Вт" from the moment
        # the panel opens, which is indistinguishable from a genuine zero-power
        # steady state. The flag is flipped the first time any power reading
        # lands via on_reading.
        self._power_received: bool = False
        self._power_channel: str = _POWER_CHANNELS[0]
        self._buffers: dict[str, deque[tuple[float, float]]] = {}
        self._rate_buffers: dict[str, deque[tuple[float, float]]] = {}
        self._chain: list[str] = []
        self._checkboxes: dict[str, QCheckBox] = {}
        self._plot_items: dict[str, pg.PlotDataItem] = {}

        self._predictor = SteadyStatePredictor(window_s=300.0, update_interval_s=10.0)

        # Auto-sweep FSM state (preserved verbatim from v1)
        self._auto_state: str = "idle"
        self._auto_power_list: list[float] = []
        self._auto_step: int = 0
        self._auto_step_start: float = 0.0
        self._auto_results: list[dict] = []
        self._auto_workers: list[ZmqCommandWorker] = []

        self._all_channels = _get_temperature_channels()
        get_channel_manager().on_change(self._on_channels_changed)

        # Flight recorder
        self._flight_log = None
        self._flight_log_writer = None

        self.setObjectName("conductivityPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#conductivityPanel {{ background-color: {theme.BACKGROUND}; }}")

        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.setInterval(_BANNER_AUTO_CLEAR_MS)
        self._banner_timer.timeout.connect(self.clear_message)

        self._build_ui()
        self._reading_signal.connect(self._handle_reading)
        self._update_control_enablement()

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(_AUTO_TIMER_INTERVAL_MS)
        self._auto_timer.timeout.connect(self._auto_tick)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_header())
        root.addWidget(self._build_banner())

        main_split = QHBoxLayout()
        main_split.setContentsMargins(0, 0, 0, 0)
        main_split.setSpacing(theme.SPACE_3)
        main_split.addWidget(self._build_chain_card(), stretch=1)
        main_split.addWidget(self._build_live_card(), stretch=3)
        root.addLayout(main_split, stretch=1)

        root.addWidget(self._build_auto_card())

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)
        title = QLabel("ТЕПЛОПРОВОДНОСТЬ")
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
        self._banner_label.setObjectName("conductivityBanner")
        self._banner_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._banner_label.setContentsMargins(
            theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1
        )
        self._banner_label.setVisible(False)
        return self._banner_label

    def _build_chain_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("chainCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#chainCard {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        caption = QLabel("Цепочка датчиков")
        caption.setFont(_label_font())
        caption.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(caption)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        ch_container = QWidget()
        ch_container.setStyleSheet("background: transparent;")
        self._ch_layout = QVBoxLayout(ch_container)
        self._ch_layout.setContentsMargins(0, 0, 0, 0)
        self._ch_layout.setSpacing(theme.SPACE_1)
        for ch_id, display_name in self._all_channels:
            cb = QCheckBox(display_name)
            cb.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent;")
            cb.stateChanged.connect(lambda state, cid=ch_id: self._on_check(cid, state))
            self._checkboxes[ch_id] = cb
            self._ch_layout.addWidget(cb)
        self._ch_layout.addStretch()
        scroll.setWidget(ch_container)
        layout.addWidget(scroll, stretch=1)

        # Power source selector
        src_cap = QLabel("Источник P:")
        src_cap.setFont(_label_font())
        src_cap.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(src_cap)

        self._power_combo = QComboBox()
        self._power_combo.addItems(list(_POWER_CHANNELS))
        self._power_combo.currentTextChanged.connect(self._on_power_changed)
        self._power_channel = self._power_combo.currentText()
        _style_input(self._power_combo)
        layout.addWidget(self._power_combo)

        # Reorder + export
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(theme.SPACE_1)
        self._up_btn = QPushButton("↑")
        _style_button(self._up_btn, "neutral")
        self._up_btn.clicked.connect(self._on_move_up)
        self._up_btn.setToolTip("Переместить сфокусированный датчик вверх по цепочке.")
        btn_row.addWidget(self._up_btn)
        self._down_btn = QPushButton("↓")
        _style_button(self._down_btn, "neutral")
        self._down_btn.clicked.connect(self._on_move_down)
        self._down_btn.setToolTip("Переместить сфокусированный датчик вниз по цепочке.")
        btn_row.addWidget(self._down_btn)
        self._export_btn = QPushButton("Экспорт CSV")
        # Phase III.D Item 18: CSV export is a secondary action — the
        # primary autosweep actions («Старт», «Стоп») own the ACCENT
        # slot; export should be neutral.
        _style_button(self._export_btn, "neutral")
        self._export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self._export_btn)
        layout.addLayout(btn_row)

        return card

    def _build_live_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("liveCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#liveCard {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        # Steady-state banner (separate from the transient status banner)
        self._steady_banner_label = QLabel("")
        self._steady_banner_label.setFont(_label_font())
        self._steady_banner_label.setObjectName("steadyBanner")
        self._steady_banner_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._steady_banner_label.setContentsMargins(
            theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1
        )
        self._steady_banner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_steady_banner("", None)
        layout.addWidget(self._steady_banner_label)

        # IV.3 Finding 1: before a sensor pair is selected, the stability
        # row previously read "Стабильность: выберите датчики · P = 0 Вт"
        # — awkward imperative mixed with a zero-valued readout. Swap
        # the row via a QStackedWidget: page 0 renders only a muted
        # «Прогноз» header (the instructional body below the table
        # already carries the "выберите пары датчиков..." guidance from
        # IV.1.5), page 1 renders the full stability + power pair.
        self._indicator_stack = QStackedWidget()

        prognosis_page = QWidget()
        prognosis_layout = QHBoxLayout(prognosis_page)
        prognosis_layout.setContentsMargins(0, 0, 0, 0)
        prognosis_layout.setSpacing(0)
        self._prognosis_header = QLabel("Прогноз")
        self._prognosis_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prognosis_header.setFont(_label_font())
        self._prognosis_header.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND};"
            f" background: transparent; border: none;"
            f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        )
        prognosis_layout.addWidget(self._prognosis_header)

        indicator_page = QWidget()
        indicator_row = QHBoxLayout(indicator_page)
        indicator_row.setContentsMargins(0, 0, 0, 0)
        indicator_row.setSpacing(theme.SPACE_3)

        self._stability_label = QLabel("Стабильность: —")
        self._stability_label.setFont(_label_font())
        self._stability_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND};"
            f" background: transparent; border: none;"
            f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        )
        indicator_row.addWidget(self._stability_label)

        self._power_label = QLabel("P = ожидание данных")
        self._power_label.setFont(_mono_value_font())
        self._power_label.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent; border: none;"
        )
        indicator_row.addWidget(self._power_label)
        indicator_row.addStretch()

        self._indicator_stack.addWidget(prognosis_page)  # index 0
        self._indicator_stack.addWidget(indicator_page)  # index 1
        self._indicator_stack.setCurrentIndex(0)
        # Fix the row height to the indicator page's sizeHint so the
        # layout does not jump when the stack swaps — the Прогноз
        # header is taller than a single-line indicator by default.
        self._indicator_stack.setFixedHeight(indicator_page.sizeHint().height())
        layout.addWidget(self._indicator_stack)

        # R/G table
        self._table = QTableWidget(0, len(_COL_HEADERS))
        self._table.setHorizontalHeaderLabels(list(_COL_HEADERS))
        self._table.setAlternatingRowColors(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setMaximumHeight(260)
        self._table.setFont(_body_font())
        self._table.setStyleSheet(
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

        # IV.1 finding 5: prediction table reads as "broken / loading"
        # when no sensor pairs are selected — the header row shows but
        # the body is empty. Swap in an explicit placeholder via
        # QStackedWidget so the empty state is unambiguous.
        self._prediction_placeholder = QLabel(
            "Здесь появится прогноз теплопроводности.\n\n"
            "Выберите пары датчиков и источник мощности,\n"
            "затем запустите автоизмерение."
        )
        self._prediction_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._prediction_placeholder.setWordWrap(True)
        placeholder_font = _label_font()
        placeholder_font.setItalic(True)
        self._prediction_placeholder.setFont(placeholder_font)
        self._prediction_placeholder.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND};"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f" padding: {theme.SPACE_4}px;"
        )
        self._prediction_placeholder.setMinimumHeight(120)

        self._prediction_stack = QStackedWidget()
        self._prediction_stack.addWidget(self._prediction_placeholder)
        self._prediction_stack.addWidget(self._table)
        self._prediction_stack.setCurrentWidget(self._prediction_placeholder)
        layout.addWidget(self._prediction_stack)

        # Plot
        self._plot = pg.PlotWidget(axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        apply_plot_style(self._plot)
        pi = self._plot.getPlotItem()
        pi.setLabel("left", "Температура", units="К")
        pi.getAxis("left").enableAutoSIPrefix(False)
        pi.setLabel("bottom", "Время")
        pi.enableAutoRange(axis="y", enable=True)
        layout.addWidget(self._plot, stretch=1)

        # Empty state overlay (anchored over the plot widget)
        self._empty_label = QLabel(
            "Нет данных. Выберите датчики и запустите эксперимент.", self._plot
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        self._empty_label.setGeometry(0, 0, 400, 80)
        return card

    def _build_auto_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("autoSweepCard")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#autoSweepCard {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        layout.setSpacing(theme.SPACE_2)

        caption = QLabel("Автоизмерение")
        caption.setFont(_label_font())
        caption.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND};"
            f" background: transparent; border: none;"
            f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        )
        layout.addWidget(caption)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.SPACE_3)
        grid.setVerticalSpacing(theme.SPACE_1)

        grid.addWidget(self._caption("Начальная P:"), 0, 0)
        self._power_start_spin = QDoubleSpinBox()
        self._power_start_spin.setRange(0.0001, 10.0)
        self._power_start_spin.setValue(0.001)
        self._power_start_spin.setDecimals(4)
        self._power_start_spin.setSuffix(" Вт")
        self._power_start_spin.setSingleStep(0.001)
        _style_input(self._power_start_spin)
        grid.addWidget(self._power_start_spin, 0, 1)

        grid.addWidget(self._caption("Шаг P:"), 0, 2)
        self._power_step_spin = QDoubleSpinBox()
        self._power_step_spin.setRange(0.0001, 10.0)
        self._power_step_spin.setValue(0.005)
        self._power_step_spin.setDecimals(4)
        self._power_step_spin.setSuffix(" Вт")
        self._power_step_spin.setSingleStep(0.001)
        _style_input(self._power_step_spin)
        grid.addWidget(self._power_step_spin, 0, 3)

        grid.addWidget(self._caption("Шагов:"), 0, 4)
        self._power_count_spin = QSpinBox()
        self._power_count_spin.setRange(2, 100)
        self._power_count_spin.setValue(10)
        _style_input(self._power_count_spin)
        grid.addWidget(self._power_count_spin, 0, 5)

        self._power_preview = QLabel("")
        self._power_preview.setFont(_label_font())
        self._power_preview.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        self._power_preview.setWordWrap(True)
        grid.addWidget(self._power_preview, 1, 0, 1, 6)

        self._power_start_spin.valueChanged.connect(self._update_power_preview)
        self._power_step_spin.valueChanged.connect(self._update_power_preview)
        self._power_count_spin.valueChanged.connect(self._update_power_preview)

        grid.addWidget(self._caption("Порог стабилизации:"), 2, 0)
        self._settled_pct_spin = QDoubleSpinBox()
        self._settled_pct_spin.setRange(80.0, 99.9)
        self._settled_pct_spin.setValue(95.0)
        self._settled_pct_spin.setDecimals(1)
        self._settled_pct_spin.setSuffix(" %")
        self._settled_pct_spin.setToolTip(
            "Процент стабилизации по экстраполяции SteadyState.\n"
            "95% = температура в пределах 5% от предсказанного стационара."
        )
        _style_input(self._settled_pct_spin)
        grid.addWidget(self._settled_pct_spin, 2, 1)

        grid.addWidget(self._caption("Мин. ожидание:"), 2, 2)
        self._min_wait_spin = QDoubleSpinBox()
        self._min_wait_spin.setRange(10, 600)
        self._min_wait_spin.setValue(30)
        self._min_wait_spin.setSuffix(" с")
        self._min_wait_spin.setToolTip("Минимальное время перед проверкой стабилизации.")
        _style_input(self._min_wait_spin)
        grid.addWidget(self._min_wait_spin, 2, 3)

        layout.addLayout(grid)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(theme.SPACE_2)
        self._auto_start_btn = QPushButton("Старт")
        _style_button(self._auto_start_btn, "primary")
        self._auto_start_btn.clicked.connect(self._on_auto_start)
        action_row.addWidget(self._auto_start_btn)
        self._auto_stop_btn = QPushButton("Стоп")
        _style_button(self._auto_stop_btn, "warning")
        self._auto_stop_btn.setEnabled(False)
        self._auto_stop_btn.clicked.connect(self._on_auto_stop)
        action_row.addWidget(self._auto_stop_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

        self._auto_progress = QProgressBar()
        self._auto_progress.setRange(0, 100)
        self._auto_progress.setValue(0)
        self._auto_progress.setVisible(False)
        self._auto_progress.setStyleSheet(
            f"QProgressBar {{"
            f" background-color: {theme.SURFACE_SUNKEN};"
            f" color: {theme.FOREGROUND};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f" text-align: center;"
            f"}} "
            f"QProgressBar::chunk {{"
            # Phase III.A: progress chunk uses ACCENT (task progress is
            # UI activation, not safety status).
            f" background-color: {theme.ACCENT};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )
        layout.addWidget(self._auto_progress)

        self._auto_status_label = QLabel("")
        self._auto_status_label.setFont(_label_font())
        self._auto_status_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        self._auto_status_label.setVisible(False)
        layout.addWidget(self._auto_status_label)

        self._update_power_preview()
        return card

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(_label_font())
        label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        return label

    # ------------------------------------------------------------------
    # Channel selection
    # ------------------------------------------------------------------

    def _on_check(self, ch_name: str, state: int) -> None:
        if state == Qt.CheckState.Checked.value:
            if ch_name not in self._chain:
                self._chain.append(ch_name)
                if ch_name not in self._buffers:
                    self._buffers[ch_name] = deque(maxlen=_BUFFER_MAXLEN)
                    self._rate_buffers[ch_name] = deque(maxlen=_RATE_BUFFER_MAXLEN)
                idx = len(self._plot_items)
                pen = series_pen(idx)
                display = get_channel_manager().get_display_name(ch_name)
                item = self._plot.plot([], [], pen=pen, name=display)
                self._plot_items[ch_name] = item
        else:
            if ch_name in self._chain:
                self._chain.remove(ch_name)
            if ch_name in self._plot_items:
                self._plot.removeItem(self._plot_items.pop(ch_name))
        # Flip the prediction stack immediately on each selection change
        # instead of waiting for the next 1 s refresh tick. The
        # placeholder ↔ table swap is pure UI state, so driving it
        # synchronously from the interaction path is safe and gives
        # the operator immediate feedback.
        self._sync_prediction_stack()

    def _sync_prediction_stack(self) -> None:
        """Set the prediction stack to placeholder or table per chain length.

        IV.3 Finding 1: also swap the indicator row's stack — before a
        pair is selected the stability/power readout is meaningless, so
        render only a muted «Прогноз» header instead of the imperative
        phrase + zeroed readout pair.
        """
        if len(self._chain) < 2:
            self._prediction_stack.setCurrentWidget(self._prediction_placeholder)
            self._indicator_stack.setCurrentIndex(0)
        else:
            self._prediction_stack.setCurrentWidget(self._table)
            self._indicator_stack.setCurrentIndex(1)

    def _on_move_up(self) -> None:
        for i, ch in enumerate(self._chain):
            if i > 0 and self._checkboxes.get(ch, QCheckBox()).hasFocus():
                self._chain[i - 1], self._chain[i] = self._chain[i], self._chain[i - 1]
                break

    def _on_move_down(self) -> None:
        for i, ch in enumerate(self._chain):
            if i < len(self._chain) - 1 and self._checkboxes.get(ch, QCheckBox()).hasFocus():
                self._chain[i], self._chain[i + 1] = self._chain[i + 1], self._chain[i]
                break

    def _on_power_changed(self, text: str) -> None:
        # Reset the waiting-state flag so switching the power source
        # doesn't leave the stale last-channel value on screen. The
        # operator must see "P = ожидание данных" until a reading on
        # the NEW channel actually lands.
        if text != self._power_channel:
            self._power = 0.0
            self._power_received = False
        self._power_channel = text
        self._update_power_label()

    def _smu_channel(self) -> str:
        parts = self._power_channel.split("/")
        return parts[1] if len(parts) >= 2 else "smua"

    def _on_channels_changed(self) -> None:
        new_channels = _get_temperature_channels()
        new_ids = {ch_id for ch_id, _ in new_channels}
        old_ids = set(self._checkboxes.keys())
        name_map = dict(new_channels)
        if new_ids == old_ids:
            for ch_id, cb in self._checkboxes.items():
                new_name = name_map.get(ch_id, ch_id)
                if cb.text() != new_name:
                    cb.setText(new_name)
            for ch_id, item in self._plot_items.items():
                new_name = name_map.get(ch_id, ch_id)
                if item.opts.get("name") != new_name:
                    item.opts["name"] = new_name
            self._all_channels = new_channels
            return

        checked = {ch_id for ch_id, cb in self._checkboxes.items() if cb.isChecked()}
        self._all_channels = new_channels
        while self._ch_layout.count():
            item = self._ch_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._checkboxes.clear()
        for ch_id, display_name in self._all_channels:
            cb = QCheckBox(display_name)
            cb.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent;")
            cb.setChecked(ch_id in checked)
            cb.stateChanged.connect(lambda state, cid=ch_id: self._on_check(cid, state))
            self._checkboxes[ch_id] = cb
            self._ch_layout.addWidget(cb)
        self._ch_layout.addStretch()
        self._chain = [ch for ch in self._chain if ch in new_ids]
        for ch_id in list(self._plot_items.keys()):
            if ch_id not in new_ids:
                self._plot.removeItem(self._plot_items.pop(ch_id))
        for ch_id in list(self._buffers.keys()):
            if ch_id not in new_ids:
                del self._buffers[ch_id]
        for ch_id in list(self._rate_buffers.keys()):
            if ch_id not in new_ids:
                del self._rate_buffers[ch_id]
        logger.info("ConductivityPanel: rebuilt (%d channels)", len(new_channels))

    # ------------------------------------------------------------------
    # Readings
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        self._reading_signal.emit(reading)

    def _resolve_channel_id(self, channel: str) -> str | None:
        if channel in self._checkboxes:
            return channel
        short = channel.split(" ")[0] if " " in channel else channel
        if short in self._checkboxes:
            return short
        return None

    @Slot(object)
    def _handle_reading(self, reading: Reading) -> None:
        ch = reading.channel
        ch_id = self._resolve_channel_id(ch)
        ts = reading.timestamp.timestamp()
        if ch_id is not None and reading.unit == "K":
            # Hide the empty-state overlay only when a real temperature
            # reading lands — a power-only reading has nothing to plot,
            # so the overlay must stay up until temps arrive. Codex II.5
            # residual fix. setVisible(False) is idempotent so we skip
            # the isVisible() pre-check (which is offscreen-Qt flaky).
            self._empty_label.setVisible(False)
            self._temps[ch_id] = reading.value
            if ch_id in self._buffers:
                self._buffers[ch_id].append((ts, reading.value))
                self._rate_buffers[ch_id].append((ts, reading.value))
            self._predictor.add_point(ch_id, ts, reading.value)
        if ch == self._power_channel:
            self._power = reading.value
            self._power_received = True

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    @Slot()
    def _refresh(self) -> None:
        now = time.time()
        self._predictor.update(now)
        all_preds = self._predictor.get_all_predictions()
        self._update_table(all_preds)
        self._update_stability()
        self._update_banner(all_preds)
        self._update_plot()
        self._update_power_label()
        self._write_flight_log(now, all_preds)

    def _update_power_label(self) -> None:
        """Render the live power readout with an explicit waiting state.

        IV.2 A.1: until a power reading has actually arrived, the label
        reads "P = ожидание данных" instead of "P = 0 Вт" — otherwise
        an idle-at-zero setpoint looks identical to a dropped feed.
        """
        if not self._power_received:
            self._power_label.setText("P = ожидание данных")
            return
        self._power_label.setText(f"P = {self._power:.6g} Вт")

    def _update_table(self, preds: dict) -> None:
        # IV.1 finding 5: stack state is kept in sync via both the
        # interactive path (_on_check → _sync_prediction_stack) and
        # the refresh tick (this method). Keeping the call here too
        # guards against any future mutation of _chain that bypasses
        # _on_check.
        self._sync_prediction_stack()
        if len(self._chain) < 2:
            self._table.setRowCount(0)
            return
        pairs = list(zip(self._chain[:-1], self._chain[1:], strict=False))
        self._table.setRowCount(len(pairs) + 1)
        total_r = 0.0
        total_r_pred = 0.0
        P = self._power

        mono_font = _mono_cell_font()

        def _cell(text: str) -> QTableWidgetItem:
            item = QTableWidgetItem(text)
            item.setFont(mono_font)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            return item

        for row, (hot_ch, cold_ch) in enumerate(pairs):
            t_hot = self._temps.get(hot_ch, float("nan"))
            t_cold = self._temps.get(cold_ch, float("nan"))
            dt = t_hot - t_cold
            R = dt / P if P != 0 and math.isfinite(dt) else float("nan")
            G = P / dt if dt != 0 and P != 0 else float("nan")
            if math.isfinite(R):
                total_r += R

            p_hot = preds.get(hot_ch)
            p_cold = preds.get(cold_ch)
            t_inf_str = ""
            tau_str = ""
            pct_str = ""
            r_pred_str = "—"
            g_pred_str = "—"
            pct_val = 0.0

            if self._is_good_pred(p_hot) and self._is_good_pred(p_cold):
                t_inf_hot = p_hot.t_predicted
                t_inf_cold = p_cold.t_predicted
                dt_inf = t_inf_hot - t_inf_cold
                t_inf_str = f"{t_inf_hot:.3f} / {t_inf_cold:.3f}"
                tau_avg = (p_hot.tau_s + p_cold.tau_s) / 2
                tau_str = f"{tau_avg / 60:.1f}"
                pct_val = min(p_hot.percent_settled, p_cold.percent_settled)
                pct_str = f"{pct_val:.0f}%"
                if P != 0 and abs(dt_inf) > 1e-10:
                    r_pred = dt_inf / P
                    g_pred = P / dt_inf
                    r_pred_str = f"{r_pred:.4g}"
                    g_pred_str = f"{g_pred:.4g}"
                    if math.isfinite(r_pred):
                        total_r_pred += r_pred

            hot_display = get_channel_manager().get_display_name(hot_ch)
            cold_display = get_channel_manager().get_display_name(cold_ch)
            self._table.setItem(row, 0, _cell(f"{hot_display} → {cold_display}"))
            self._table.setItem(row, 1, _cell(f"{t_hot:.4f}"))
            self._table.setItem(row, 2, _cell(f"{t_cold:.4f}"))
            self._table.setItem(row, 3, _cell(f"{dt:.4f}" if math.isfinite(dt) else "—"))
            self._table.setItem(row, 4, _cell(f"{R:.4g}" if math.isfinite(R) else "—"))
            self._table.setItem(row, 5, _cell(f"{G:.4g}" if math.isfinite(G) else "—"))
            self._table.setItem(row, 6, _cell(t_inf_str))
            self._table.setItem(row, 7, _cell(tau_str))
            pct_item = _cell(pct_str)
            if pct_str:
                pct_item.setForeground(QColor(_pct_color(pct_val)))
            self._table.setItem(row, 8, pct_item)
            self._table.setItem(row, 9, _cell(r_pred_str))
            self._table.setItem(row, 10, _cell(g_pred_str))

        total_row = len(pairs)
        t_first = self._temps.get(self._chain[0], float("nan"))
        t_last = self._temps.get(self._chain[-1], float("nan"))
        total_dt = t_first - t_last
        total_G = P / total_dt if total_dt != 0 and P != 0 else float("nan")
        total_G_pred = P / (total_r_pred * P) if total_r_pred != 0 and P != 0 else float("nan")

        self._table.setItem(total_row, 0, _cell("ИТОГО"))
        self._table.setItem(
            total_row, 1, _cell(f"{t_first:.4f}" if math.isfinite(t_first) else "—")
        )
        self._table.setItem(total_row, 2, _cell(f"{t_last:.4f}" if math.isfinite(t_last) else "—"))
        self._table.setItem(
            total_row, 3, _cell(f"{total_dt:.4f}" if math.isfinite(total_dt) else "—")
        )
        self._table.setItem(
            total_row,
            4,
            _cell(f"{total_r:.4g}" if math.isfinite(total_r) and total_r != 0 else "—"),
        )
        self._table.setItem(
            total_row, 5, _cell(f"{total_G:.4g}" if math.isfinite(total_G) else "—")
        )
        self._table.setItem(total_row, 6, _cell(""))
        self._table.setItem(total_row, 7, _cell(""))
        self._table.setItem(total_row, 8, _cell(""))
        self._table.setItem(
            total_row, 9, _cell(f"{total_r_pred:.4g}" if total_r_pred != 0 else "—")
        )
        self._table.setItem(
            total_row, 10, _cell(f"{total_G_pred:.4g}" if math.isfinite(total_G_pred) else "—")
        )

        bold_font = _mono_cell_font()
        bold_font.setBold(True)
        for col in range(len(_COL_HEADERS)):
            item = self._table.item(total_row, col)
            if item:
                item.setFont(bold_font)

    def _update_banner(self, preds: dict) -> None:
        if len(self._chain) < 2:
            self._set_steady_banner("", None)
            return
        valid_preds = [preds.get(ch) for ch in self._chain if preds.get(ch) and preds[ch].valid]
        if not valid_preds:
            self._set_steady_banner("Прогноз: сбор данных...", theme.STATUS_INFO)
            return
        min_pct = min(p.percent_settled for p in valid_preds)
        max_tau = max(p.tau_s for p in valid_preds) if valid_preds else 0
        if min_pct >= 99.0:
            self._set_steady_banner("ГОТОВО — стационар достигнут", theme.STATUS_OK)
        elif min_pct >= 95.0:
            remaining = max_tau * math.log(100.0 / max(100.0 - min_pct, 0.1)) / 60.0
            self._set_steady_banner(
                f"Стабилизация {min_pct:.0f}% — ещё ~{remaining:.0f} мин",
                theme.STATUS_WARNING,
            )
        else:
            remaining = max_tau * math.log(100.0 / max(100.0 - min_pct, 0.1)) / 60.0
            self._set_steady_banner(
                f"Стабилизация {min_pct:.0f}% — прогноз ~{remaining:.0f} мин",
                theme.STATUS_INFO,
            )

    def _set_steady_banner(self, text: str, color: str | None) -> None:
        self._steady_banner_label.setText(text)
        if not text or color is None:
            self._steady_banner_label.setStyleSheet(
                f"#steadyBanner {{ background: transparent; border: none;"
                f" color: {theme.MUTED_FOREGROUND}; }}"
            )
            return
        self._steady_banner_label.setStyleSheet(
            f"#steadyBanner {{"
            f" color: {theme.FOREGROUND};"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {color};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )

    @staticmethod
    def _is_good_pred(p) -> bool:
        return (
            p is not None
            and p.valid
            and p.confidence > 0.5
            and p.t_predicted > 0
            and abs(p.t_predicted - p.t_current) < 50.0
        )

    def _update_stability(self) -> None:
        # IV.2 A.1: the empty-state text is operator-facing and must
        # explain the required setup step, not just show an em-dash.
        # "Стабильность: —" on its own reads as "stable at an unknown
        # value" — the new copy makes the action explicit.
        if not self._chain:
            self._stability_label.setText("Стабильность: выберите датчики")
            self._stability_label.setStyleSheet(
                f"color: {theme.MUTED_FOREGROUND};"
                f" background: transparent; border: none;"
                f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
            )
            return
        stable = True
        max_rate = 0.0
        for ch in self._chain:
            buf = self._rate_buffers.get(ch)
            if not buf or len(buf) < 10:
                self._stability_label.setText("Стабильность: сбор данных...")
                self._stability_label.setStyleSheet(
                    f"color: {theme.MUTED_FOREGROUND};"
                    f" background: transparent; border: none;"
                    f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
                )
                return
            t0, v0 = buf[0]
            t1, v1 = buf[-1]
            dt_s = t1 - t0
            if dt_s > 0:
                rate = abs(v1 - v0) / (dt_s / 60.0)
                max_rate = max(max_rate, rate)
                if rate > _STABILITY_THRESHOLD:
                    stable = False
        if stable:
            self._stability_label.setText(f"Стабильно (dT/dt = {max_rate:.4f} К/мин)")
            color = theme.STATUS_OK
        else:
            self._stability_label.setText(f"Нестабильно (dT/dt = {max_rate:.3f} К/мин)")
            color = theme.STATUS_WARNING
        self._stability_label.setStyleSheet(
            f"color: {color};"
            f" background: transparent; border: none;"
            f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        )

    def _update_plot(self) -> None:
        now = time.time()
        t_start = now
        for ch in self._chain:
            buf = self._buffers.get(ch)
            if buf and len(buf) > 0:
                t_start = min(t_start, buf[0][0])
        for ch, item in self._plot_items.items():
            buf = self._buffers.get(ch)
            if not buf:
                item.setData([], [])
                continue
            xs = [t for t, _ in buf]
            ys = [v for _, v in buf]
            item.setData(xs, ys)
        if self._plot_items and t_start < now:
            forecast_s = (now - t_start) / 3.0
            self._plot.getPlotItem().setXRange(t_start, now + forecast_s, padding=0.02)

    # ------------------------------------------------------------------
    # Auto-sweep (preserved verbatim from v1 semantics)
    # ------------------------------------------------------------------

    def _generate_power_list(self) -> list[float]:
        start = self._power_start_spin.value()
        step = self._power_step_spin.value()
        count = self._power_count_spin.value()
        return [round(start + i * step, 6) for i in range(count)]

    def _update_power_preview(self) -> None:
        powers = self._generate_power_list()
        if len(powers) <= 6:
            text = ", ".join(f"{p:.4g}" for p in powers)
        else:
            first3 = ", ".join(f"{p:.4g}" for p in powers[:3])
            text = f"{first3}, ... , {powers[-1]:.4g}  ({len(powers)} шагов)"
        self._power_preview.setText("Список мощностей: " + text)

    def _send_auto_cmd(self, cmd: dict) -> None:
        worker = ZmqCommandWorker(cmd, parent=self)
        worker.finished.connect(self._on_auto_cmd_result)
        self._auto_workers.append(worker)
        worker.start()

    @Slot(dict)
    def _on_auto_cmd_result(self, result: dict) -> None:
        self._auto_workers = [w for w in self._auto_workers if w.isRunning()]
        if not result.get("ok"):
            logger.warning("Авто-команда Keithley: %s", result.get("error", "?"))

    @Slot()
    def _on_auto_start(self) -> None:
        if len(self._chain) < 2:
            QMessageBox.warning(self, "Ошибка", "Выберите минимум 2 датчика в цепочке.")
            return
        powers = self._generate_power_list()
        if not powers:
            QMessageBox.warning(self, "Ошибка", "Список мощностей пуст.")
            return

        self._auto_power_list = powers
        self._auto_step = 0
        self._auto_results = []
        self._auto_state = "stabilizing"

        self._auto_start_btn.setEnabled(False)
        self._auto_stop_btn.setEnabled(True)
        self._auto_progress.setVisible(True)
        self._auto_progress.setValue(0)
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText(f"Шаг 1/{len(powers)} — P = {powers[0]:.4g} Вт")

        self._auto_step_start = time.monotonic()
        self._send_auto_cmd(
            {
                "cmd": "keithley_set_target",
                "channel": self._smu_channel(),
                "p_target": powers[0],
            }
        )
        logger.info("Автоизмерение: старт, %d шагов, P=%s", len(powers), powers)
        self._auto_timer.start()
        self.auto_sweep_started.emit()

    @Slot()
    def _on_auto_stop(self) -> None:
        self._auto_state = "idle"
        self._auto_timer.stop()
        self._send_auto_cmd({"cmd": "keithley_stop", "channel": self._smu_channel()})
        self._auto_start_btn.setEnabled(self._connected)
        self._auto_stop_btn.setEnabled(False)
        self._auto_progress.setVisible(False)
        self._auto_status_label.setText("Остановлено оператором")
        logger.info("Автоизмерение: остановлено оператором")
        self.auto_sweep_aborted.emit("operator_stop")

    @Slot()
    def _auto_tick(self) -> None:
        if self._auto_state != "stabilizing":
            return
        elapsed = time.monotonic() - self._auto_step_start
        step_total = len(self._auto_power_list)
        step_idx = self._auto_step
        P = self._auto_power_list[step_idx]

        settled_values: list[float] = []
        for ch in self._chain:
            pred = self._predictor.get_prediction(ch)
            if pred is not None and pred.valid:
                settled_values.append(pred.percent_settled)
            else:
                settled_values.append(0.0)
        min_settled = min(settled_values) if settled_values else 0.0
        threshold = self._settled_pct_spin.value()
        min_wait = self._min_wait_spin.value()
        is_stable = elapsed >= min_wait and min_settled >= threshold

        step_progress = min(min_settled / threshold, 1.0) if threshold > 0 else 1.0
        pct = int(((step_idx + step_progress) / step_total) * 100)
        self._auto_progress.setValue(min(pct, 99))

        settled_str = " / ".join(f"{s:.0f}%" for s in settled_values[:4])
        self._auto_status_label.setText(
            f"Шаг {step_idx + 1}/{step_total} — "
            f"P = {P:.4g} Вт — {elapsed:.0f} с — "
            f"стабил.: {settled_str}"
        )

        if is_stable:
            self._auto_record_point()
            self._auto_step += 1
            if self._auto_step >= step_total:
                self._auto_complete()
            else:
                next_p = self._auto_power_list[self._auto_step]
                self._auto_step_start = time.monotonic()
                self._send_auto_cmd(
                    {
                        "cmd": "keithley_set_target",
                        "channel": self._smu_channel(),
                        "p_target": next_p,
                    }
                )
                logger.info(
                    "Автоизмерение: шаг %d/%d, P=%.4g Вт",
                    self._auto_step + 1,
                    step_total,
                    next_p,
                )

    def _auto_record_point(self) -> None:
        P = self._auto_power_list[self._auto_step]
        if len(self._chain) < 2:
            return
        hot_ch = self._chain[0]
        cold_ch = self._chain[-1]
        T_hot = self._temps.get(hot_ch, float("nan"))
        T_cold = self._temps.get(cold_ch, float("nan"))
        dT = T_hot - T_cold
        R = dT / P if P != 0 and math.isfinite(dT) else float("nan")
        G = P / dT if dT != 0 and math.isfinite(dT) else float("nan")
        settled_values = []
        for ch in self._chain:
            pred = self._predictor.get_prediction(ch)
            if pred and pred.valid:
                settled_values.append(pred.percent_settled)
        min_settled = min(settled_values) if settled_values else 0.0
        self._auto_results.append(
            {
                "P": P,
                "T_hot": T_hot,
                "T_cold": T_cold,
                "dT": dT,
                "R": R,
                "G": G,
                "settled_pct": min_settled,
            }
        )
        logger.info(
            "Автоизмерение: точка P=%.4g, dT=%.4f, R=%.4g, G=%.4g, settled=%.0f%%",
            P,
            dT,
            R,
            G,
            min_settled,
        )

    def _auto_complete(self) -> None:
        self._auto_state = "done"
        self._auto_timer.stop()
        self._send_auto_cmd({"cmd": "keithley_stop", "channel": self._smu_channel()})
        self._auto_start_btn.setEnabled(self._connected)
        self._auto_stop_btn.setEnabled(False)
        self._auto_progress.setValue(100)
        n = len(self._auto_results)
        self._auto_status_label.setText(f"Завершено: {n} точек измерено")
        logger.info("Автоизмерение: завершено, %d точек", n)
        if self._auto_results:
            summary_lines = ["Автоизмерение завершено:\n"]
            for i, pt in enumerate(self._auto_results, 1):
                summary_lines.append(
                    f"{i}. P={pt['P']:.4g} Вт, dT={pt['dT']:.4f} К, "
                    f"R={pt['R']:.4g}, G={pt['G']:.4g}"
                )
            QMessageBox.information(self, "Автоизмерение", "\n".join(summary_lines))
        self.auto_sweep_completed.emit(n)

    # ------------------------------------------------------------------
    # Flight recorder
    # ------------------------------------------------------------------

    def _write_flight_log(self, now: float, preds: dict) -> None:
        if len(self._chain) < 2:
            return
        if self._flight_log is None:
            from cryodaq.paths import get_data_dir

            log_dir = get_data_dir() / "conductivity_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts_str = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            log_path = log_dir / f"conductivity_{ts_str}.csv"
            self._flight_log = log_path.open("w", newline="", encoding="utf-8-sig")
            self._flight_log_writer = csv.writer(self._flight_log)
            self._flight_log_writer.writerow(
                [
                    "timestamp_utc",
                    "elapsed_s",
                    "T_hot",
                    "T_cold",
                    "dT",
                    "P",
                    "R_measured",
                    "G_measured",
                    "R_predicted",
                    "G_predicted",
                    "percent_settled_hot",
                    "percent_settled_cold",
                    "tau_hot_s",
                    "tau_cold_s",
                    "T_inf_hot",
                    "T_inf_cold",
                    "auto_sweep_step",
                    "auto_sweep_power",
                ]
            )
        hot_ch = self._chain[0]
        cold_ch = self._chain[-1]
        T_hot = self._temps.get(hot_ch, float("nan"))
        T_cold = self._temps.get(cold_ch, float("nan"))
        dT = T_hot - T_cold
        P = self._power
        R = dT / P if P != 0 and math.isfinite(dT) else float("nan")
        G = P / dT if dT != 0 and math.isfinite(dT) else float("nan")

        p_hot = preds.get(hot_ch)
        p_cold = preds.get(cold_ch)
        R_pred = G_pred = float("nan")
        pct_hot = pct_cold = 0.0
        tau_hot = tau_cold = T_inf_hot = T_inf_cold = float("nan")
        if p_hot and p_hot.valid:
            pct_hot = p_hot.percent_settled
            tau_hot = p_hot.tau_s
            T_inf_hot = p_hot.t_predicted
        if p_cold and p_cold.valid:
            pct_cold = p_cold.percent_settled
            tau_cold = p_cold.tau_s
            T_inf_cold = p_cold.t_predicted
        if self._is_good_pred(p_hot) and self._is_good_pred(p_cold):
            dt_pred = T_inf_hot - T_inf_cold
            if P != 0 and math.isfinite(dt_pred) and dt_pred != 0:
                R_pred = dt_pred / P
                G_pred = P / dt_pred

        step = self._auto_step if self._auto_state == "stabilizing" else -1
        step_P = (
            self._auto_power_list[self._auto_step]
            if self._auto_state == "stabilizing" and self._auto_step < len(self._auto_power_list)
            else 0
        )
        elapsed = now - self._buffers[hot_ch][0][0] if self._buffers.get(hot_ch) else 0

        self._flight_log_writer.writerow(
            [
                datetime.now(UTC).isoformat(),
                f"{elapsed:.1f}",
                f"{T_hot:.6f}",
                f"{T_cold:.6f}",
                f"{dT:.6f}",
                f"{P:.6g}",
                f"{R:.6g}",
                f"{G:.6g}",
                f"{R_pred:.6g}",
                f"{G_pred:.6g}",
                f"{pct_hot:.1f}",
                f"{pct_cold:.1f}",
                f"{tau_hot:.1f}",
                f"{tau_cold:.1f}",
                f"{T_inf_hot:.6f}",
                f"{T_inf_cold:.6f}",
                step,
                f"{step_P:.6g}",
            ]
        )
        self._flight_log.flush()

    def closeEvent(self, event) -> None:
        if self._flight_log:
            self._flight_log.close()
            self._flight_log = None
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Manual CSV export
    # ------------------------------------------------------------------

    @Slot()
    def _on_export(self) -> None:
        if len(self._chain) < 2:
            self.show_warning("Выберите минимум 2 датчика в цепочке.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт теплопроводности", "", "CSV файлы (*.csv)"
        )
        if not path:
            return
        out = Path(path)
        now = datetime.now(UTC)
        P = self._power
        preds = self._predictor.get_all_predictions()

        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "timestamp",
                    "P_W",
                    *[f"T_{ch}_K" for ch in self._chain],
                    "pair",
                    "dT_K",
                    "R_KW",
                    "G_WK",
                    "T_inf_hot",
                    "T_inf_cold",
                    "R_pred",
                    "G_pred",
                    "settled_%",
                ]
            )
            for hot_ch, cold_ch in zip(self._chain[:-1], self._chain[1:], strict=False):
                t_hot = self._temps.get(hot_ch, float("nan"))
                t_cold = self._temps.get(cold_ch, float("nan"))
                dt = t_hot - t_cold
                R = dt / P if P != 0 else float("nan")
                G = P / dt if dt != 0 else float("nan")
                t_values = [self._temps.get(ch, float("nan")) for ch in self._chain]
                p_hot = preds.get(hot_ch)
                p_cold = preds.get(cold_ch)
                t_inf_hot = p_hot.t_predicted if p_hot and p_hot.valid else float("nan")
                t_inf_cold = p_cold.t_predicted if p_cold and p_cold.valid else float("nan")
                dt_inf = t_inf_hot - t_inf_cold
                r_pred = dt_inf / P if P != 0 and math.isfinite(dt_inf) else float("nan")
                g_pred = P / dt_inf if dt_inf != 0 and P != 0 else float("nan")
                settled = min(
                    p_hot.percent_settled if p_hot and p_hot.valid else 0,
                    p_cold.percent_settled if p_cold and p_cold.valid else 0,
                )
                w.writerow(
                    [
                        now.isoformat(),
                        P,
                        *t_values,
                        f"{hot_ch} → {cold_ch}",
                        dt,
                        R,
                        G,
                        t_inf_hot,
                        t_inf_cold,
                        r_pred,
                        g_pred,
                        settled,
                    ]
                )
        self.show_info(f"Экспортировано: {out}")

    # ------------------------------------------------------------------
    # Public state pushers / accessors
    # ------------------------------------------------------------------

    def set_connected(self, connected: bool) -> None:
        if connected == self._connected:
            return
        self._connected = connected
        self._update_control_enablement()
        if not connected:
            self.show_error("Нет связи с engine")
        else:
            self.clear_message()

    def _update_control_enablement(self) -> None:
        # Auto-sweep Start gated on connection. Stop stays enabled while
        # stabilizing so operator can always abort. Chain selection +
        # CSV export stay enabled regardless (local work).
        start_ok = self._connected and self._auto_state != "stabilizing"
        self._auto_start_btn.setEnabled(start_ok)
        self._auto_stop_btn.setEnabled(self._auto_state == "stabilizing")

    def get_auto_state(self) -> str:
        """Public accessor for the auto-sweep FSM state.

        Returns one of ``"idle"``, ``"stabilizing"``, ``"done"``.

        Intended for external finalize guards (e.g. ExperimentOverlay v3,
        II.9 follow-up) that must block experiment finalization while
        the auto-sweep is actively stabilizing — closing the panel or
        ending the experiment mid-sweep would leave Keithley powered.
        """

        return self._auto_state

    def is_auto_sweep_active(self) -> bool:
        """True iff the auto-sweep FSM is actively stabilizing."""
        return self._auto_state == "stabilizing"

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
            f"#conductivityBanner {{"
            f" color: {theme.FOREGROUND};"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {color};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )
        self._banner_label.setVisible(True)
        self._banner_timer.start()
