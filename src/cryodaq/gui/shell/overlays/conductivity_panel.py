"""ConductivityPanel — Phase II.5 thermal conductivity overlay.

Supersedes the v1 widget at ``src/cryodaq/gui/widgets/conductivity_panel.py``.
Aligned with the canonical design-system tokens. Preserves the three public
auto-sweep guard-state values and the flight-recorder CSV schema while adding
generation-bound command settlement, explicit outcome-unknown retention, and a
successful current-generation SafetyManager Stop reply before operator Stop or
completion is published.
Exposes ``get_auto_state()`` / ``is_auto_sweep_active()`` as public accessors
for the ExperimentOverlay finalize guard.

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
  ``"done"``. ``"stabilizing"`` is conservative: it also covers target
  settlement, Stop-confirmation, and outcome-unknown substates.
- ``is_auto_sweep_active() -> bool`` — finalize-guard predicate; ``True``
  does not imply that the auto timer is running or command outcome is known.

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
# F81 finding: a fixed freshness window silently rejects every sample of an
# otherwise healthy instrument whose configured poll_interval_s (registry allows
# up to 86_400 s) or successful read (up to 300 s) exceeds 10 seconds, leaving
# the sweep in "stabilizing" forever. The window is therefore derived from the
# observed acquisition cadence of the bound channels (median of recent
# inter-sample monotonic acquisition gaps), with this constant kept as the
# fail-closed floor: a dead feed still ages past any finite window.
_AUTO_SAMPLE_MAX_AGE_S = 10.0
_AUTO_SAMPLE_AGE_CADENCE_FACTOR = 3.0
_AUTO_CADENCE_SAMPLE_SLOTS = 9
_ACQUISITION_STARTED_AT = "acquisition_started_at"
# F81 finding C: a fixed 300-second predictor window with the default 30-point
# minimum silently never yields a valid prediction for a cadence slower than
# 10 seconds (300/30), so a healthy 30-second-cadence channel holds ~10 points
# and the sweep sits in "stabilizing" forever. The predictor window is derived
# from the observed cadence of the bound temperature feeds (window = cadence x
# min_points, floored at 300 s) so every bound channel can accumulate the
# minimum point count inside it. The minimum itself is not lowered: fewer
# points would weaken the exponential fit.
_PREDICTOR_BASE_WINDOW_S = 300.0
_PREDICTOR_MIN_POINTS = 30
_PREDICTOR_UPDATE_INTERVAL_S = 10.0

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
    return [(ch_id, mgr.get_display_name(ch_id)) for ch_id in mgr.get_all_visible() if ch_id.startswith("Т")]


def _pct_color(_pct: float) -> str:
    """Render settling progress without making a safety-health assertion."""

    return theme.ACCENT


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
    elif variant == "caution":
        bg, fg = theme.STATUS_CAUTION, theme.ON_PRIMARY
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

        # Public guard state. "stabilizing" is retained through settling,
        # command-pending, Stop-pending, and outcome-unknown substates until
        # current-authority Stop settlement permits idle/done publication.
        self._auto_state: str = "idle"
        self._auto_power_list: list[float] = []
        self._auto_step: int = 0
        self._auto_step_start: float = 0.0
        self._auto_results: list[dict] = []
        self._auto_workers: list[ZmqCommandWorker] = []
        self._auto_connection_generation = 0
        self._auto_operation_generation = 0
        self._auto_command_sequence = 0
        self._auto_settled_command_tokens: set[int] = set()
        self._auto_pending_token: int | None = None
        self._auto_pending_stop_intent: str | None = None
        # Activity and command outcome are independent truth axes.  A lost
        # reply must retain the last-known ACTIVE state so external finalize
        # guards cannot be cleared by GUI inference.
        self._auto_outcome_unknown = False
        self._auto_step_ack_wall_s: float | None = None
        self._auto_step_ack_monotonic_s: float | None = None
        self._auto_step_temperature_channels: tuple[str, ...] = ()
        self._auto_step_power_channel: str | None = None
        self._auto_step_temperature_values: dict[str, float] = {}
        self._auto_step_temperature_received_at: dict[str, float] = {}
        self._auto_step_power_value: float | None = None
        self._auto_step_power_received_at: float | None = None

        # F81 finding: per-channel observed acquisition cadence (monotonic gap
        # between successive samples of the same channel). The freshness window
        # is derived from the median of the most recent gaps so a configured
        # poll_interval_s or slow read above 10 seconds does not reject every
        # healthy sample, while the 10-second floor stays fail-closed.
        self._auto_cadence_gaps: dict[str, deque[float]] = {}
        self._auto_last_acquisition_s: dict[str, float] = {}

        # F81 finding C: the predictor is constructed after the step's channel
        # state and cadence dictionaries so its window can be derived from the
        # observed temperature cadence (see _make_auto_predictor). At this
        # point no cadence has been observed yet, so the base window applies.
        self._auto_predictor_window_s: float = _PREDICTOR_BASE_WINDOW_S
        self._predictor = self._make_auto_predictor()

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
        # v0.55.2 A3: top toolbar pulls power-source / channel-counter /
        # export-CSV out of the cramped chain card and into a horizontal
        # strip directly under the banner — matches cryodaq-primitives/
        # conductivity-panel.md "Anatomy".
        root.addWidget(self._build_toolbar())

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
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none; letter-spacing: 1px;")
        layout.addWidget(title)
        layout.addStretch()
        return header

    def _build_banner(self) -> QWidget:
        self._banner_label = QLabel("")
        self._banner_label.setFont(_label_font())
        self._banner_label.setObjectName("conductivityBanner")
        self._banner_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._banner_label.setContentsMargins(theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1)
        self._banner_label.setVisible(False)
        return self._banner_label

    def _build_toolbar(self) -> QWidget:
        """Top strip with power source, channel counter, and export.

        v0.55.2 A3: per cryodaq-primitives/conductivity-panel.md the
        spec mandates a top toolbar for these controls so the chain
        card on the left can devote its space to channel selection
        rather than fighting with controls at the bottom.
        """
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        src_cap = QLabel("Источник P:")
        src_cap.setFont(_label_font())
        src_cap.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(src_cap)

        self._power_combo = QComboBox()
        self._power_combo.addItems(list(_POWER_CHANNELS))
        self._power_combo.currentTextChanged.connect(self._on_power_changed)
        self._power_channel = self._power_combo.currentText()
        _style_input(self._power_combo)
        layout.addWidget(self._power_combo)

        layout.addStretch(1)

        # Channel counter — updates from _on_check / _refresh_chain_counter.
        self._chain_counter_label = QLabel("Выбрано: 0 датчиков")
        self._chain_counter_label.setFont(_label_font())
        self._chain_counter_label.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;"
        )
        layout.addWidget(self._chain_counter_label)

        layout.addStretch(1)

        self._export_btn = QPushButton("Экспорт CSV")
        # Phase III.D Item 18: CSV export is a secondary action — the
        # primary autosweep actions («Старт», «Стоп») own the ACCENT
        # slot; export should be neutral.
        _style_button(self._export_btn, "neutral")
        self._export_btn.clicked.connect(self._on_export)
        layout.addWidget(self._export_btn)

        return bar

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
        caption.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(caption)

        # v0.55.2 A3: 2-column grid keeps the channel list compact so the
        # left column stops monopolising vertical space. Scrollable in
        # case channel count grows past the card height.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        ch_container = QWidget()
        ch_container.setStyleSheet("background: transparent;")
        self._ch_layout = QGridLayout(ch_container)
        self._ch_layout.setContentsMargins(0, 0, 0, 0)
        self._ch_layout.setHorizontalSpacing(theme.SPACE_2)
        self._ch_layout.setVerticalSpacing(theme.SPACE_1)
        n_channels = len(self._all_channels)
        rows_per_col = (n_channels + 1) // 2  # left column gets the extra
        for idx, (ch_id, display_name) in enumerate(self._all_channels):
            row = idx % rows_per_col
            col = idx // rows_per_col
            cb = QCheckBox(display_name)
            cb.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent;")
            cb.stateChanged.connect(lambda state, cid=ch_id: self._on_check(cid, state))
            self._checkboxes[ch_id] = cb
            self._ch_layout.addWidget(cb, row, col)
        self._ch_layout.setRowStretch(rows_per_col, 1)
        scroll.setWidget(ch_container)
        layout.addWidget(scroll, stretch=1)

        # Reorder buttons stay in the chain card — they act on the
        # chain ordering itself, not on global controls.
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
        btn_row.addStretch(1)
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
        self._steady_banner_label.setContentsMargins(theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1)
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
        self._power_label.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
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
        self._empty_label = QLabel("Нет данных. Выберите датчики и запустите эксперимент.", self._plot)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
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
        self._power_preview.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
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
        _style_button(self._auto_stop_btn, "caution")
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
        label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
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
        self._refresh_chain_counter()

    def _refresh_chain_counter(self) -> None:
        """Update the toolbar's «Выбрано: N датчиков» readout."""
        if not hasattr(self, "_chain_counter_label"):
            return
        n = len(self._chain)
        self._chain_counter_label.setText(f"Выбрано: {n} датчиков")

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

    @staticmethod
    def _smu_channel_for(power_channel: str) -> str:
        parts = power_channel.split("/")
        return parts[1] if len(parts) >= 2 else "smua"

    def _smu_channel(self) -> str:
        return self._smu_channel_for(self._power_channel)

    @staticmethod
    def _reading_monotonic_metadata(reading: Reading, key: str) -> float | None:
        metadata = reading.metadata if isinstance(reading.metadata, dict) else {}
        value = metadata.get(key)
        if isinstance(value, bool):
            return None
        try:
            monotonic_value = float(value)
        except (TypeError, ValueError):
            return None
        return monotonic_value if math.isfinite(monotonic_value) else None

    def _observe_auto_cadence(self, channel: str, acquisition_started_monotonic: float | None) -> None:
        """Record the inter-sample acquisition gap for one channel.

        F81 finding: the freshness window must track the instrument's actual
        acquisition cadence, not a fixed 10-second constant, or a configured
        poll_interval_s above 10 seconds rejects every healthy sample. The gap
        is measured between successive samples of the same channel on the same
        monotonic clock (``acquisition_started_monotonic``).

        F81 finding C: when a slow cadence is observed after the sweep has
        already started (the predictor was built before the first samples of the
        step arrived), the predictor window must be grown to match, or the feed
        can never accumulate the 30-point minimum and the sweep sits in
        "stabilizing" forever.
        """
        if acquisition_started_monotonic is None:
            return
        previous = self._auto_last_acquisition_s.get(channel)
        self._auto_last_acquisition_s[channel] = acquisition_started_monotonic
        if previous is None:
            return
        gap = acquisition_started_monotonic - previous
        if gap <= 0:
            return
        self._auto_cadence_gaps.setdefault(channel, deque(maxlen=_AUTO_CADENCE_SAMPLE_SLOTS)).append(gap)
        if self._auto_state != "stabilizing":
            return
        required = self._required_predictor_window_s()
        if required > self._auto_predictor_window_s:
            self._auto_predictor_window_s = required
            self._predictor = SteadyStatePredictor(
                window_s=required,
                update_interval_s=_PREDICTOR_UPDATE_INTERVAL_S,
            )

    def _auto_feed_max_age_s(self, channel: str) -> float:
        """Fail-closed freshness window for ONE feed, from its own cadence.

        F81/P1 finding: the earlier helper computed a single window as the
        maximum median cadence across every bound feed and applied it to every
        temperature and power sample, so a slow temperature channel widened the
        power-feed failure bound and a stale power value could advance the
        heater. Each selected feed now carries its own cadence and its own
        bound. Uses the median of that feed's most recent inter-sample gaps so
        a single long gap (for example a one-off slow read within the permitted
        300-second timeout) cannot inflate the window, while the 10-second
        floor keeps the guard fail-closed: a genuinely dead feed still ages
        past any finite window. When no cadence has been observed yet, the
        floor applies unchanged.
        """
        gaps = self._auto_cadence_gaps.get(channel)
        if not gaps:
            return _AUTO_SAMPLE_MAX_AGE_S
        ordered = sorted(gaps)
        return max(_AUTO_SAMPLE_MAX_AGE_S, _AUTO_SAMPLE_AGE_CADENCE_FACTOR * ordered[len(ordered) // 2])

    def _reset_auto_temperature_evidence(self) -> None:
        self._auto_step_temperature_values.clear()
        self._auto_step_temperature_received_at.clear()
        self._predictor = self._make_auto_predictor()

    def _make_auto_predictor(self) -> SteadyStatePredictor:
        """Construct the predictor sized to the observed temperature cadence.

        F81 finding C: a fixed 300-second window with the 30-point minimum
        holds only ~10 points of a 30-second-cadence feed, so the predictor
        never yields a valid prediction and the sweep stays in "stabilizing"
        forever. Derive the window from the slowest bound temperature feed so
        every bound channel can accumulate the minimum point count inside it.
        The 30-point minimum is not lowered: fewer points would weaken the
        exponential fit. When no cadence has been observed yet, the base window
        applies unchanged. The derived window is stored on the panel so
        _observe_auto_cadence can grow it if a slow cadence arrives after the
        sweep has started.
        """
        window_s = self._required_predictor_window_s()
        self._auto_predictor_window_s = window_s
        return SteadyStatePredictor(
            window_s=window_s,
            update_interval_s=_PREDICTOR_UPDATE_INTERVAL_S,
        )

    def _required_predictor_window_s(self) -> float:
        """Predictor window the bound temperature feeds' cadence demands.

        F81 finding C: the slowest temperature feed bound to the auto step
        drives the predictor window, so a 30-second feed widens the window to
        900 seconds instead of silently never producing a valid prediction.
        When no cadence has been observed yet for any bound feed, the base
        window applies unchanged.
        """
        cadence = self._bound_temperature_cadence_s()
        if cadence is None:
            return _PREDICTOR_BASE_WINDOW_S
        # Rounded UP, and the rounding is load-bearing rather than cosmetic. The cadence
        # is a MEASURED median of observed gaps, so a nominal 30-second feed arrives as
        # 29.999999999999996 and the product lands one unit in the last place BELOW the
        # window that holds the required number of points -- 899.9999999999999 instead of
        # 900.0. A window a hair too short holds one point fewer than the count this
        # method exists to guarantee, which is the "silently never producing a valid
        # prediction" failure named above. Measured at master on Ubuntu 22.04.5: the
        # guard test failed 1 run in 12 for exactly this, so it also cost a CI round in
        # eight, on a queue that is already the constraint.
        return max(_PREDICTOR_BASE_WINDOW_S, float(math.ceil(cadence * _PREDICTOR_MIN_POINTS)))

    def _bound_temperature_cadence_s(self) -> float | None:
        """Median of medians of the step's temperature feeds' observed cadence.

        F81 finding C: the slowest temperature feed bound to the auto step
        drives the predictor window, so a 30-second feed widens the window to
        900 seconds instead of silently never producing a valid prediction.
        Only channels actually bound to the current step are considered, so an
        unrelated slow channel cannot inflate the predictor window.
        """
        medians: list[float] = []
        for channel in self._auto_step_temperature_channels:
            gaps = self._auto_cadence_gaps.get(channel)
            if not gaps:
                continue
            ordered = sorted(gaps)
            medians.append(ordered[len(ordered) // 2])
        return max(medians) if medians else None

    def _on_channels_changed(self) -> None:
        new_channels = _get_temperature_channels()
        active = self._auto_state == "stabilizing"
        bound_channels = self._auto_step_temperature_channels if active else ()
        if bound_channels:
            display_names = dict(self._all_channels)
            new_ids = {ch_id for ch_id, _ in new_channels}
            new_channels.extend(
                (ch_id, display_names.get(ch_id, ch_id)) for ch_id in bound_channels if ch_id not in new_ids
            )

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
            self._update_control_enablement()
            return

        checked = {ch_id for ch_id, cb in self._checkboxes.items() if cb.isChecked()}
        checked.update(bound_channels)
        self._all_channels = new_channels
        while self._ch_layout.count():
            item = self._ch_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self._checkboxes.clear()
        rows_per_col = max(1, (len(self._all_channels) + 1) // 2)
        for idx, (ch_id, display_name) in enumerate(self._all_channels):
            cb = QCheckBox(display_name)
            cb.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent;")
            cb.setChecked(ch_id in checked)
            cb.stateChanged.connect(lambda state, cid=ch_id: self._on_check(cid, state))
            self._checkboxes[ch_id] = cb
            self._ch_layout.addWidget(cb, idx % rows_per_col, idx // rows_per_col)
        self._ch_layout.setRowStretch(rows_per_col, 1)
        self._chain = list(bound_channels) if bound_channels else [ch for ch in self._chain if ch in new_ids]
        for ch_id in list(self._plot_items.keys()):
            if ch_id not in new_ids:
                self._plot.removeItem(self._plot_items.pop(ch_id))
        for ch_id in list(self._buffers.keys()):
            if ch_id not in new_ids:
                del self._buffers[ch_id]
        for ch_id in list(self._rate_buffers.keys()):
            if ch_id not in new_ids:
                del self._rate_buffers[ch_id]
        self._update_control_enablement()
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
        received_at = self._reading_monotonic_metadata(reading, "bridge_ingress_monotonic")
        acquisition_started_monotonic = self._reading_monotonic_metadata(reading, "acquisition_started_monotonic")
        self._observe_auto_cadence(ch_id or ch, acquisition_started_monotonic)
        # NaN-доктрина (A3): статус — дискриминатор годности; не годное
        # температурное показание не питает SteadyStatePredictor.
        auto_step_fresh = (
            self._auto_step_ack_monotonic_s is not None
            and acquisition_started_monotonic is not None
            and acquisition_started_monotonic >= self._auto_step_ack_monotonic_s
        )
        # F81-1: the engine-side publisher queue can stall before the bridge
        # ingress stamp, so a post-ack sample can wait upstream and arrive
        # with a fresh ingress stamp after publication resumes. Bound the
        # acquisition-to-ingress age with the same cadence-derived window
        # _auto_tick applies to bridge ingress, so a stale sample that merely
        # looks fresh cannot refill the predictor or advance the sweep.
        auto_step_current = (
            auto_step_fresh
            and received_at is not None
            and received_at - acquisition_started_monotonic <= self._auto_feed_max_age_s(ch_id or ch)
        )
        selected_auto_temperature = self._auto_state == "stabilizing" and ch_id in self._auto_step_temperature_channels
        if selected_auto_temperature and not reading.is_usable():
            self._reset_auto_temperature_evidence()
        if ch_id is not None and reading.unit == "K" and reading.is_usable():
            # Hide the empty-state overlay only when a real temperature
            # reading lands — a power-only reading has nothing to plot,
            # so the overlay must stay up until temps arrive. II.5
            # residual fix. setVisible(False) is idempotent so we skip
            # the isVisible() pre-check (which is offscreen-Qt flaky).
            self._empty_label.setVisible(False)
            self._temps[ch_id] = reading.value
            if ch_id in self._buffers:
                self._buffers[ch_id].append((ts, reading.value))
                self._rate_buffers[ch_id].append((ts, reading.value))
            if not selected_auto_temperature or auto_step_current:
                self._predictor.add_point(ch_id, ts, reading.value)
            if selected_auto_temperature and auto_step_current:
                self._auto_step_temperature_values[ch_id] = reading.value
                self._auto_step_temperature_received_at[ch_id] = received_at
        if ch == self._power_channel:
            self._power = reading.value
            self._power_received = True
        selected_auto_power = self._auto_state == "stabilizing" and ch == self._auto_step_power_channel
        if selected_auto_power:
            if auto_step_current and reading.is_usable():
                self._auto_step_power_value = reading.value
                self._auto_step_power_received_at = received_at
            elif not reading.is_usable():
                self._auto_step_power_value = None
                self._auto_step_power_received_at = None
                self._reset_auto_temperature_evidence()

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
        self._table.setItem(total_row, 1, _cell(f"{t_first:.4f}" if math.isfinite(t_first) else "—"))
        self._table.setItem(total_row, 2, _cell(f"{t_last:.4f}" if math.isfinite(t_last) else "—"))
        self._table.setItem(total_row, 3, _cell(f"{total_dt:.4f}" if math.isfinite(total_dt) else "—"))
        self._table.setItem(
            total_row,
            4,
            _cell(f"{total_r:.4g}" if math.isfinite(total_r) and total_r != 0 else "—"),
        )
        self._table.setItem(total_row, 5, _cell(f"{total_G:.4g}" if math.isfinite(total_G) else "—"))
        self._table.setItem(total_row, 6, _cell(""))
        self._table.setItem(total_row, 7, _cell(""))
        self._table.setItem(total_row, 8, _cell(""))
        self._table.setItem(total_row, 9, _cell(f"{total_r_pred:.4g}" if total_r_pred != 0 else "—"))
        self._table.setItem(total_row, 10, _cell(f"{total_G_pred:.4g}" if math.isfinite(total_G_pred) else "—"))

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
            self._set_steady_banner("ГОТОВО — стационар достигнут", theme.ACCENT)
        elif min_pct >= 95.0:
            remaining = max_tau * math.log(100.0 / max(100.0 - min_pct, 0.1)) / 60.0
            self._set_steady_banner(
                f"Стабилизация {min_pct:.0f}% — ещё ~{remaining:.0f} мин",
                theme.ACCENT,
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
                f"#steadyBanner {{ background: transparent; border: none; color: {theme.MUTED_FOREGROUND}; }}"
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
            color = theme.ACCENT
        else:
            self._stability_label.setText(f"Нестабильно (dT/dt = {max_rate:.3f} К/мин)")
            color = theme.STATUS_INFO
        self._stability_label.setStyleSheet(
            f"color: {color}; background: transparent; border: none; font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
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
    # Auto-sweep — three public guard states plus generation-bound settlement substates
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

    def _send_auto_cmd(
        self,
        cmd: dict,
        *,
        stop_intent: str | None = None,
        evidence_power_channel: str | None = None,
        evidence_temperature_channels: tuple[str, ...] | None = None,
    ) -> bool:
        """Dispatch one generation-bound command while live authority exists."""

        if not self._connected:
            if self._auto_state == "stabilizing":
                self._latch_auto_outcome_unknown("Нет живой связи с Engine; команда не отправлена.")
            return False

        self._auto_command_sequence += 1
        token = self._auto_command_sequence
        expected_connection_generation = self._auto_connection_generation
        expected_operation_generation = self._auto_operation_generation
        worker = ZmqCommandWorker(cmd, parent=self)

        def _completed(
            result: dict,
            command_token: int = token,
            command: dict = dict(cmd),
            connection_generation: int = expected_connection_generation,
            operation_generation: int = expected_operation_generation,
            completed_worker: ZmqCommandWorker = worker,
            command_stop_intent: str | None = stop_intent,
            command_power_channel: str | None = evidence_power_channel,
            command_temperature_channels: tuple[str, ...] | None = evidence_temperature_channels,
        ) -> None:
            self._on_auto_cmd_result(
                command_token,
                command,
                result,
                connection_generation,
                operation_generation,
                completed_worker,
                command_stop_intent,
                command_power_channel,
                command_temperature_channels,
            )

        worker.finished.connect(_completed)
        self._auto_workers.append(worker)
        self._auto_pending_token = token
        worker.start()
        return True

    def _on_auto_cmd_result(
        self,
        token: int,
        command: dict,
        result: dict,
        expected_connection_generation: int,
        expected_operation_generation: int,
        worker: ZmqCommandWorker | None = None,
        stop_intent: str | None = None,
        evidence_power_channel: str | None = None,
        evidence_temperature_channels: tuple[str, ...] | None = None,
    ) -> None:
        """Commit only the exact current operation's authoritative reply."""

        if token in self._auto_settled_command_tokens:
            logger.warning("Повторный ответ автоизмерения проигнорирован: token=%s", token)
            return
        self._auto_settled_command_tokens.add(token)
        if worker is not None:
            self._auto_workers = [candidate for candidate in self._auto_workers if candidate is not worker]
        pending_token = self._auto_pending_token
        if pending_token is not None and token != pending_token:
            logger.warning(
                "Ответ вытесненной авто-команды проигнорирован: %s, token=%s, current=%s",
                command.get("cmd", "?"),
                token,
                pending_token,
            )
            return
        if token == pending_token:
            self._auto_pending_token = None

        if (
            expected_connection_generation != self._auto_connection_generation
            or expected_operation_generation != self._auto_operation_generation
            or not self._connected
        ):
            logger.warning(
                "Запоздалый ответ автоизмерения проигнорирован: %s, token=%s",
                command.get("cmd", "?"),
                token,
            )
            return

        if not isinstance(result, dict) or result.get("ok") is not True:
            error = (
                str(result.get("error", "неизвестная ошибка"))
                if isinstance(result, dict)
                else "некорректный ответ Engine"
            )
            logger.warning("Авто-команда Keithley не подтверждена: %s", error)
            self._auto_pending_stop_intent = None
            self._latch_auto_outcome_unknown(f"Engine не подтвердил {command.get('cmd', 'команду')}: {error[:120]}")
            return

        if command.get("cmd") == "keithley_stop":
            if stop_intent == "complete":
                self._commit_auto_complete()
            else:
                self._commit_auto_stop()
            return

        if command.get("cmd") == "keithley_set_target":
            if evidence_power_channel is None or evidence_temperature_channels is None:
                self._latch_auto_outcome_unknown("В ответе команды нет идентичности измерительного шага.")
                return
            self._arm_auto_step_evidence(
                power_channel=evidence_power_channel,
                temperature_channels=evidence_temperature_channels,
            )
        self._update_control_enablement()

    def _latch_auto_outcome_unknown(self, reason: str) -> None:
        """Stop advancement and retain guard-active truth until current Stop succeeds."""

        if self._auto_state != "stabilizing":
            return
        self._auto_outcome_unknown = True
        self._auto_timer.stop()
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText("ИСХОД НЕИЗВЕСТЕН — последнее известное: АВТОИЗМЕРЕНИЕ АКТИВНО. " + reason)
        self._update_control_enablement()

    def _invalidate_auto_step_evidence(self) -> None:
        self._auto_step_ack_wall_s = None
        self._auto_step_ack_monotonic_s = None
        self._reset_auto_temperature_evidence()
        self._auto_step_power_value = None
        self._auto_step_power_received_at = None

    def _arm_auto_step_evidence(
        self,
        *,
        power_channel: str,
        temperature_channels: tuple[str, ...],
    ) -> None:
        """Start one evidence epoch after the target command is acknowledged."""

        self._auto_step_ack_wall_s = time.time()
        self._auto_step_ack_monotonic_s = time.monotonic()
        self._auto_step_start = self._auto_step_ack_monotonic_s
        self._auto_step_power_channel = power_channel
        self._auto_step_temperature_channels = temperature_channels
        self._reset_auto_temperature_evidence()
        self._auto_step_power_value = None
        self._auto_step_power_received_at = None

    @Slot()
    def _on_auto_start(self) -> None:
        # Button enablement is presentation only.  The handler owns the final
        # live-authority check so direct/queued invocation cannot bypass it.
        if (
            not self._connected
            or self._auto_state == "stabilizing"
            or self._auto_outcome_unknown
            or self._auto_pending_token is not None
        ):
            return
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
        self._auto_operation_generation += 1
        self._auto_outcome_unknown = False
        self._auto_pending_stop_intent = None
        self._invalidate_auto_step_evidence()

        self._auto_start_btn.setEnabled(False)
        self._auto_stop_btn.setEnabled(True)
        self._auto_progress.setVisible(True)
        self._auto_progress.setValue(0)
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText(f"Шаг 1/{len(powers)} — P = {powers[0]:.4g} Вт")
        self._update_control_enablement()

        self._auto_step_start = time.monotonic()
        self._auto_step_power_channel = self._power_channel
        self._auto_step_temperature_channels = tuple(self._chain)
        power_channel = self._auto_step_power_channel
        temperature_channels = self._auto_step_temperature_channels
        dispatched = self._send_auto_cmd(
            {
                "cmd": "keithley_set_target",
                "channel": self._smu_channel_for(power_channel),
                "p_target": powers[0],
            },
            evidence_power_channel=power_channel,
            evidence_temperature_channels=temperature_channels,
        )
        if not dispatched:
            self._latch_auto_outcome_unknown("Начальная команда мощности не отправлена.")
            return
        logger.info("Автоизмерение: старт, %d шагов, P=%s", len(powers), powers)
        self._auto_timer.start()
        self.auto_sweep_started.emit()

    @Slot()
    def _on_auto_stop(self) -> None:
        if self._auto_state != "stabilizing" or self._auto_pending_stop_intent is not None:
            return
        if not self._connected:
            self._latch_auto_outcome_unknown(
                "Останов нельзя отправить без живой связи; состояние источника требует сверки."
            )
            return
        self._auto_timer.stop()
        self._auto_pending_stop_intent = "operator"
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText("Останов запрошен — ожидается подтверждение отключения источника")
        self._update_control_enablement()
        if not self._send_auto_cmd(
            {
                "cmd": "keithley_stop",
                "channel": self._smu_channel_for(self._auto_step_power_channel or self._power_channel),
            },
            stop_intent="operator",
        ):
            self._auto_pending_stop_intent = None
            self._latch_auto_outcome_unknown("Команда останова не отправлена.")

    def _commit_auto_stop(self) -> None:
        """Apply operator stop only after SafetyManager confirms the command."""

        self._auto_state = "idle"
        self._auto_outcome_unknown = False
        self._auto_pending_stop_intent = None
        self._auto_timer.stop()
        self._auto_progress.setVisible(False)
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText("Остановлено оператором — отключение подтверждено")
        self._on_channels_changed()
        logger.info("Автоизмерение: остановлено оператором, отключение подтверждено")
        self.auto_sweep_aborted.emit("operator_stop")

    @Slot()
    def _auto_tick(self) -> None:
        if (
            self._auto_state != "stabilizing"
            or not self._connected
            or self._auto_outcome_unknown
            or self._auto_pending_token is not None
            or self._auto_pending_stop_intent is not None
        ):
            return
        now_monotonic = time.monotonic()
        elapsed = now_monotonic - self._auto_step_start
        step_total = len(self._auto_power_list)
        step_idx = self._auto_step
        P = self._auto_power_list[step_idx]
        temperature_channels = self._auto_step_temperature_channels

        settled_values: list[float] = []
        for ch in temperature_channels:
            pred = self._predictor.get_prediction(ch)
            if pred is not None and pred.valid:
                settled_values.append(pred.percent_settled)
            else:
                settled_values.append(0.0)
        min_settled = min(settled_values) if settled_values else 0.0
        threshold = self._settled_pct_spin.value()
        min_wait = self._min_wait_spin.value()
        temperature_ages_are_current = bool(temperature_channels) and all(
            ch in self._auto_step_temperature_values
            and ch in self._auto_step_temperature_received_at
            and now_monotonic - self._auto_step_temperature_received_at[ch] <= self._auto_feed_max_age_s(ch)
            for ch in temperature_channels
        )
        if not temperature_ages_are_current and self._auto_step_temperature_values:
            self._reset_auto_temperature_evidence()
            settled_values = [0.0 for _ in temperature_channels]
            min_settled = 0.0
        power_feed = self._auto_step_power_channel
        power_age_is_current = (
            power_feed is not None
            and self._auto_step_power_value is not None
            and self._auto_step_power_received_at is not None
            and now_monotonic - self._auto_step_power_received_at <= self._auto_feed_max_age_s(power_feed)
        )
        if not power_age_is_current:
            self._auto_step_power_value = None
            self._auto_step_power_received_at = None
            self._reset_auto_temperature_evidence()
            temperature_ages_are_current = False
            settled_values = [0.0 for _ in temperature_channels]
            min_settled = 0.0
        is_stable = (
            elapsed >= min_wait and min_settled >= threshold and temperature_ages_are_current and power_age_is_current
        )

        step_progress = min(min_settled / threshold, 1.0) if threshold > 0 else 1.0
        pct = int(((step_idx + step_progress) / step_total) * 100)
        self._auto_progress.setValue(min(pct, 99))

        settled_str = " / ".join(f"{s:.0f}%" for s in settled_values[:4])
        self._auto_status_label.setText(
            f"Шаг {step_idx + 1}/{step_total} — P = {P:.4g} Вт — {elapsed:.0f} с — стабил.: {settled_str}"
        )

        if is_stable:
            self._auto_record_point()
            self._auto_step += 1
            if self._auto_step >= step_total:
                self._auto_complete()
            else:
                next_p = self._auto_power_list[self._auto_step]
                power_channel = self._auto_step_power_channel
                temperature_channels = self._auto_step_temperature_channels
                self._invalidate_auto_step_evidence()
                if power_channel is None or not temperature_channels:
                    self._latch_auto_outcome_unknown("Идентичность следующего измерительного шага потеряна.")
                    return
                self._send_auto_cmd(
                    {
                        "cmd": "keithley_set_target",
                        "channel": self._smu_channel_for(power_channel),
                        "p_target": next_p,
                    },
                    evidence_power_channel=power_channel,
                    evidence_temperature_channels=temperature_channels,
                )
                logger.info(
                    "Автоизмерение: шаг %d/%d, P=%.4g Вт",
                    self._auto_step + 1,
                    step_total,
                    next_p,
                )

    def _auto_record_point(self) -> None:
        P = self._auto_step_power_value
        temperature_channels = self._auto_step_temperature_channels
        if len(temperature_channels) < 2 or P is None:
            return
        hot_ch = temperature_channels[0]
        cold_ch = temperature_channels[-1]
        T_hot = self._auto_step_temperature_values.get(hot_ch, float("nan"))
        T_cold = self._auto_step_temperature_values.get(cold_ch, float("nan"))
        dT = T_hot - T_cold
        R = dT / P if P != 0 and math.isfinite(dT) else float("nan")
        G = P / dT if dT != 0 and math.isfinite(dT) else float("nan")
        settled_values = []
        for ch in temperature_channels:
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
        if self._auto_state != "stabilizing" or self._auto_pending_stop_intent is not None:
            return
        self._auto_timer.stop()
        if not self._connected:
            self._latch_auto_outcome_unknown("Все точки записаны, но отключение источника не подтверждено.")
            return
        self._auto_pending_stop_intent = "complete"
        self._auto_progress.setValue(99)
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText("Все точки записаны — ожидается подтверждение отключения источника")
        self._update_control_enablement()
        if not self._send_auto_cmd(
            {
                "cmd": "keithley_stop",
                "channel": self._smu_channel_for(self._auto_step_power_channel or self._power_channel),
            },
            stop_intent="complete",
        ):
            self._auto_pending_stop_intent = None
            self._latch_auto_outcome_unknown("Команда завершающего останова не отправлена.")

    def _commit_auto_complete(self) -> None:
        """Publish completion only after authoritative source shutdown."""

        self._auto_state = "done"
        self._auto_outcome_unknown = False
        self._auto_pending_stop_intent = None
        self._auto_progress.setValue(100)
        self._on_channels_changed()
        n = len(self._auto_results)
        self._auto_status_label.setText(f"Завершено: {n} точек измерено; отключение источника подтверждено")
        logger.info("Автоизмерение: завершено, %d точек", n)
        if self._auto_results:
            summary_lines = ["Автоизмерение завершено:\n"]
            for i, pt in enumerate(self._auto_results, 1):
                summary_lines.append(f"{i}. P={pt['P']:.4g} Вт, dT={pt['dT']:.4f} К, R={pt['R']:.4g}, G={pt['G']:.4g}")
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
        # Stop owned timers so a closed/destroyed panel does not keep ticking
        # (_auto_tick / banner refresh firing on a deleted widget segfaults).
        for timer in (self._timer, self._auto_timer, self._banner_timer):
            try:
                timer.stop()
            except RuntimeError:
                pass
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
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт теплопроводности", "", "CSV файлы (*.csv)")
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
        connected = bool(connected)
        if connected == self._connected:
            return
        self._connected = connected
        self._auto_connection_generation += 1
        if not connected and self._auto_state == "stabilizing":
            self._auto_pending_token = None
            self._auto_pending_stop_intent = None
            self._latch_auto_outcome_unknown("Связь потеряна; результат выполнявшейся команды неизвестен.")
        self._update_control_enablement()
        if not connected:
            self.show_error("Нет связи с engine")
        else:
            self.clear_message()

    def _update_control_enablement(self) -> None:
        # Handler-level authority checks mirror these presentation gates.
        # Stop is the safe direction, but a GUI without a live Engine link has
        # no authority to claim it was delivered.
        active = self._auto_state == "stabilizing"
        start_ok = (
            self._connected and not active and not self._auto_outcome_unknown and self._auto_pending_token is None
        )
        stop_ok = self._connected and active and self._auto_pending_stop_intent is None
        self._auto_start_btn.setEnabled(start_ok)
        self._auto_stop_btn.setEnabled(stop_ok)
        self._power_combo.setEnabled(not active)
        for checkbox in self._checkboxes.values():
            checkbox.setEnabled(not active)

    def get_auto_state(self) -> str:
        """Return the conservative public auto-sweep guard state.

        Values are ``"idle"``, ``"stabilizing"``, and ``"done"``.
        ``"stabilizing"`` includes normal settling, target-command settlement,
        Stop confirmation, and outcome-unknown retention. External finalize
        guards must block for every ``"stabilizing"`` substate.
        """

        return self._auto_state

    def is_auto_sweep_active(self) -> bool:
        """True while finalization treats the sweep as active or possibly active.

        This does not prove that ``_auto_timer`` is running or that the latest
        command outcome is known.
        """
        return self._auto_state == "stabilizing"

    # ------------------------------------------------------------------
    # Banner
    # ------------------------------------------------------------------

    def show_info(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_INFO)

    def show_warning(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_CAUTION)

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
