"""ConductivityPanel — Phase II.5 thermal conductivity overlay.

Supersedes the v1 widget at ``src/cryodaq/gui/widgets/conductivity_panel.py``.
Aligned with the canonical design-system tokens. Preserves the three public
auto-sweep guard-state contract and the flight-recorder CSV schema while adding
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
- ``get_auto_state() -> str`` — returns ``"idle"`` / ``"reserving"`` /
  ``"stabilizing"`` / ``"done"``. ``"reserving"`` cannot dispatch a source
  target; ``"stabilizing"`` also covers target settlement, Stop confirmation,
  and outcome-unknown substates.
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
import uuid
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
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
from cryodaq.gui.zmq_client import (
    ZmqCommandWorker,
    capture_gui_worker_session_token,
    gui_worker_delivery_is_current,
    record_gui_worker_delivery_disposition,
    start_gui_worker_with_ownership,
)
from cryodaq.storage.channel_descriptors import (
    ChannelDescriptorProjection,
    ChannelDescriptorStorageError,
    project_channel_descriptor,
)
from cryodaq.storage.conductivity_run import (
    ConductivityRunFormatError,
    ConductivityRunWriter,
    build_conductivity_descriptor_parameters,
)

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


class _ConductivityPersistenceWorker(QThread):
    """Run one serialized autosweep filesystem operation off the GUI thread."""

    completed = Signal(object)
    _result_ready = Signal(int, object)

    def __init__(
        self,
        operation: Callable[[], Any],
        *,
        cleanup_on_interruption: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(None)
        self._operation = operation
        self._cleanup_on_interruption = cleanup_on_interruption
        self._session_epoch: int | None = None
        self._result_ready.connect(self._deliver_if_current, Qt.ConnectionType.QueuedConnection)

    def start(self, priority: QThread.Priority = QThread.Priority.InheritPriority) -> None:
        session_epoch = capture_gui_worker_session_token()
        self._session_epoch = session_epoch
        try:
            start_gui_worker_with_ownership(self, session_epoch, priority)
        except BaseException:
            self._session_epoch = None
            raise

    def run(self) -> None:
        try:
            value = self._operation()
        except BaseException as exc:
            result: dict[str, Any] = {
                "ok": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }
        else:
            result = {"ok": True, "value": value}
        if self.isInterruptionRequested() and self._cleanup_on_interruption is not None:
            try:
                self._cleanup_on_interruption()
            except BaseException:
                logger.exception("Failed to close interrupted autosweep persistence owner")
        session_epoch = self._session_epoch
        if session_epoch is not None:
            self._result_ready.emit(session_epoch, result)

    @Slot(int, object)
    def _deliver_if_current(self, session_epoch: int, result: object) -> None:
        try:
            if not self.isInterruptionRequested() and gui_worker_delivery_is_current(session_epoch):
                self.completed.emit(result)
        finally:
            record_gui_worker_delivery_disposition(self)


class ConductivityPanel(QWidget):
    """Thermal conductivity overlay (Phase II.5)."""

    _reading_signal = Signal(object, object)

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
        self._auto_run_writer: ConductivityRunWriter | None = None
        self._auto_run_path: Path | None = None
        self._auto_run_id: str | None = None
        self._auto_run_started_at: datetime | None = None
        self._auto_run_parameters: dict[str, Any] | None = None
        self._latest_channel_descriptors: dict[str, object] = {}
        self._latest_channel_descriptor_generations: dict[str, int] = {}
        self._auto_bound_power_channel: str | None = None
        self._auto_bound_temperature_channels: tuple[str, ...] = ()
        self._auto_bound_descriptors: dict[str, ChannelDescriptorProjection] = {}
        self._auto_descriptor_parameters: dict[str, Any] | None = None
        self._auto_stabilization_threshold_pct: float | None = None
        self._auto_minimum_wait_s: float | None = None
        self._auto_persistence_error: str | None = None
        self._auto_trailing_write_outcome: str | None = None
        self._auto_experiment_id: str | None = None
        self._auto_expected_experiment_id: str | None = None
        self._auto_experiment_binding_known = False
        # Engine attachment settlement and durable file binding are separate
        # authorities: only the latter permits terminal publication.
        self._auto_binding_resolution = "unrequested"
        self._auto_persistence_worker: _ConductivityPersistenceWorker | None = None
        self._auto_pending_point_result: dict[str, float] | None = None
        self._auto_deferred_terminal_status: str | None = None
        self._auto_run_creation_failed = False
        self._auto_run_creation_error: str | None = None
        self._auto_terminal_attachment_command: dict[str, Any] | None = None
        self._auto_terminal_publication_status: str | None = None
        self._auto_terminal_attachment_inflight = False
        self._auto_workers: list[ZmqCommandWorker] = []
        self._auto_connection_generation = 0
        self._auto_verified_off_connection_generation: int | None = None
        self._auto_operation_generation = 0
        self._auto_command_sequence = 0
        self._auto_settled_command_tokens: set[int] = set()
        self._auto_pending_token: int | None = None
        self._auto_pending_stop_intent: str | None = None
        # Once a point write fails, a later generic Stop retry must not
        # downgrade the terminal record from FAILED to ABORTED.
        self._auto_terminal_failure_required = False
        self._auto_power_target_dispatched = False
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
        # ONE CADENCE OF HEADROOM, and the arithmetic is why. The predictor prunes at
        # `now - window_s` and refuses below `min_points`. N points spaced by one cadence
        # SPAN (N-1) cadences, so a window of exactly `cadence * points` fits the required
        # points with a single cadence to spare -- and any delay longer than one cadence
        # between the oldest sample and the update tick drops that sample, leaves N-1
        # points, and the prediction goes invalid with tau, amplitude and settled all zero.
        # A feed that is one cycle late therefore never accumulates its count, which is the
        # "silently never producing a valid prediction" failure this method exists to
        # prevent, arriving through the window instead of through the point count. Measured
        # on a loaded hosted runner: exactly that shape, with the window assertion passing
        # and the prediction invalid.
        return max(
            _PREDICTOR_BASE_WINDOW_S,
            float(math.ceil(cadence * (_PREDICTOR_MIN_POINTS + 1))),
        )

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
        active = self._auto_state in {"reserving", "stabilizing"}
        bound_channels = self._auto_bound_temperature_channels if active else ()
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
        """Render a legacy/unqualified reading without granting run identity."""

        self._reading_signal.emit(reading, None)

    def on_descriptor_reading(self, reading: Reading, descriptor: object) -> None:
        """Accept one authoritative reading and its immutable source identity."""

        self._reading_signal.emit(reading, descriptor)

    def _resolve_channel_id(self, channel: str) -> str | None:
        if channel in self._checkboxes:
            return channel
        short = channel.split(" ")[0] if " " in channel else channel
        if short in self._checkboxes:
            return short
        return None

    @Slot(object, object)
    def _handle_reading(self, reading: Reading, descriptor: object | None = None) -> None:
        ch = reading.channel
        ch_id = self._resolve_channel_id(ch)
        descriptor_was_supplied = descriptor is not None
        if descriptor is not None:
            try:
                verified = project_channel_descriptor(descriptor)
            except ChannelDescriptorStorageError:
                logger.warning("Conductivity reading descriptor was rejected for %s", ch)
                descriptor = None
            else:
                if (
                    verified.channel_id != ch
                    or verified.instrument_id != reading.instrument_id
                    or verified.unit != reading.unit
                ):
                    logger.warning("Conductivity reading descriptor identity mismatch for %s", ch)
                    descriptor = None
                else:
                    descriptor = verified
                    if self._connected:
                        self._latest_channel_descriptors[ch] = verified
                        self._latest_channel_descriptor_generations[ch] = self._auto_connection_generation
        bound_descriptor = self._auto_bound_descriptors.get(ch_id or ch)
        descriptor_matches_bound = (
            bound_descriptor is not None
            and descriptor is not None
            and descriptor.canonical_json == bound_descriptor.canonical_json
        )
        if bound_descriptor is not None and descriptor_was_supplied and not descriptor_matches_bound:
            self._reset_auto_temperature_evidence()
            self._auto_step_power_value = None
            self._auto_step_power_received_at = None
            self._latch_auto_outcome_unknown(
                "Идентичность выбранного измерительного канала изменилась; переход мощности запрещён."
            )
            return
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
            and descriptor_matches_bound
        )
        selected_auto_temperature = self._auto_state == "stabilizing" and ch_id in self._auto_step_temperature_channels
        if selected_auto_temperature and descriptor_matches_bound and not reading.is_usable():
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
            elif descriptor_matches_bound and not reading.is_usable():
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

    def _dispatch_persistence(
        self,
        operation: Callable[[], Any],
        callback: Callable[[dict[str, Any]], None],
        *,
        cleanup_on_interruption: Callable[[], None] | None = None,
    ) -> bool:
        """Serialize one filesystem operation through the registered GUI worker session."""

        if self._auto_persistence_worker is not None:
            return False
        expected_generation = self._auto_operation_generation
        worker = _ConductivityPersistenceWorker(
            operation,
            cleanup_on_interruption=cleanup_on_interruption,
        )

        def _completed(
            result: object,
            *,
            completed_worker: _ConductivityPersistenceWorker = worker,
            operation_generation: int = expected_generation,
        ) -> None:
            if self._auto_persistence_worker is not completed_worker:
                return
            self._auto_persistence_worker = None
            if operation_generation != self._auto_operation_generation:
                return
            if not isinstance(result, dict):
                callback({"ok": False, "error": "invalid persistence worker result"})
                return
            callback(result)

        worker.completed.connect(_completed)
        self._auto_persistence_worker = worker
        try:
            worker.start()
        except (RuntimeError, OSError) as exc:
            self._auto_persistence_worker = None
            callback({"ok": False, "error": str(exc), "error_type": type(exc).__name__})
            return False
        return True

    def _snapshot_auto_selection(self) -> bool:
        """Freeze one descriptor-qualified channel set before asynchronous pre-arm work."""

        temperature_channels = tuple(self._chain)
        power_channel = self._power_channel
        power_descriptor = self._current_cached_descriptor(power_channel)
        temperature_descriptors = tuple(
            descriptor
            for channel in temperature_channels
            if (descriptor := self._current_cached_descriptor(channel)) is not None
        )
        if power_descriptor is None or len(temperature_descriptors) != len(temperature_channels):
            self.show_warning("Автоизмерение не запущено: нет подтверждённых дескрипторов выбранных каналов.")
            return False
        try:
            descriptor_parameters = build_conductivity_descriptor_parameters(
                power=power_descriptor,
                temperatures=temperature_descriptors,
            )
        except (ConductivityRunFormatError, TypeError, ValueError, ChannelDescriptorStorageError) as exc:
            logger.warning("Autosweep descriptor selection was rejected: %s", exc)
            self.show_warning("Автоизмерение не запущено: идентичность выбранных каналов не подтверждена.")
            return False
        self._auto_bound_power_channel = power_channel
        self._auto_bound_temperature_channels = temperature_channels
        self._auto_bound_descriptors = {
            descriptor.channel_id: descriptor for descriptor in (power_descriptor, *temperature_descriptors)
        }
        self._auto_descriptor_parameters = descriptor_parameters
        self._auto_stabilization_threshold_pct = float(self._settled_pct_spin.value())
        self._auto_minimum_wait_s = float(self._min_wait_spin.value())
        return True

    def _current_cached_descriptor(self, channel: str) -> ChannelDescriptorProjection | None:
        """Return descriptor authority only from the current transport incarnation."""

        if self._latest_channel_descriptor_generations.get(channel) != self._auto_connection_generation:
            return None
        candidate = self._latest_channel_descriptors.get(channel)
        if candidate is None:
            return None
        try:
            return project_channel_descriptor(candidate)
        except ChannelDescriptorStorageError:
            return None

    def _clear_auto_selection(self) -> None:
        self._auto_bound_power_channel = None
        self._auto_bound_temperature_channels = ()
        self._auto_bound_descriptors.clear()
        self._auto_descriptor_parameters = None
        self._auto_stabilization_threshold_pct = None
        self._auto_minimum_wait_s = None

    def _begin_auto_run_async(self, powers: list[float], data_dir: Path) -> bool:
        """Resolve experiment authority before creating a file or changing power."""

        started_at = datetime.now(UTC)
        run_id = f"conductivity-{started_at.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:12]}"
        path = data_dir / "conductivity_runs" / f"{run_id}.csv"
        descriptor_parameters = self._auto_descriptor_parameters
        threshold = self._auto_stabilization_threshold_pct
        minimum_wait = self._auto_minimum_wait_s
        if descriptor_parameters is None or threshold is None or minimum_wait is None:
            return False
        parameters = {
            "power_values_w": list(powers),
            "stabilization_threshold_pct": threshold,
            "minimum_wait_s": minimum_wait,
            **descriptor_parameters,
        }
        self._auto_run_writer = None
        self._auto_run_path = path
        self._auto_run_id = run_id
        self._auto_run_started_at = started_at
        self._auto_run_parameters = parameters
        self._auto_experiment_id = None
        self._auto_expected_experiment_id = None
        self._auto_experiment_binding_known = False
        self._auto_binding_resolution = "unrequested"
        self._auto_persistence_error = None
        self._auto_trailing_write_outcome = None
        self._auto_terminal_failure_required = False
        self._auto_run_creation_failed = False
        self._auto_run_creation_error = None
        command = self._attachment_command(
            status="RUNNING",
            terminal=None,
            finished_at=None,
            reservation_state="reserved",
        )
        return command is not None and self._send_auto_cmd(command)

    def _begin_auto_writer_creation(self) -> bool:
        """Create the engine-reserved artifact off-thread."""

        path = self._auto_run_path
        run_id = self._auto_run_id
        started_at = self._auto_run_started_at
        parameters = self._auto_run_parameters
        if path is None or run_id is None or started_at is None or parameters is None:
            return False
        return self._dispatch_persistence(
            lambda: ConductivityRunWriter(
                path,
                run_id=run_id,
                started_at=started_at,
                parameters=parameters,
            ),
            self._on_auto_run_created,
        )

    def _on_auto_run_created(self, result: dict[str, Any]) -> None:
        if result.get("ok") is not True or not isinstance(result.get("value"), ConductivityRunWriter):
            reason = str(result.get("error", "file writer was not created"))
            self._auto_run_creation_failed = True
            self._auto_run_creation_error = reason
            self._auto_status_label.setVisible(True)
            if self._auto_deferred_terminal_status is not None:
                self._settle_prearm_creation_failure_after_off(reason)
                return
            if self._auto_pending_stop_intent is not None or self._auto_outcome_unknown:
                self._auto_status_label.setText(
                    f"Файл данных не создан ({reason[:120]}); ожидается подтверждение отключения источника"
                )
                self._update_control_enablement()
                return
            if self._auto_experiment_id is not None:
                self._terminalize_reserved_prearm_failure(reason)
                return
            self._auto_state = "idle"
            self._auto_outcome_unknown = False
            self._auto_status_label.setText(f"Автоизмерение не запущено: файл данных не создан ({reason[:160]})")
            self._clear_auto_selection()
            self._update_control_enablement()
            return
        self._auto_run_writer = result["value"]
        self._persist_auto_binding_then_arm(self._auto_experiment_id)

    def _settle_prearm_creation_failure_after_off(self, reason: str) -> None:
        """Release a run that never acquired a file only after verified OFF."""

        if self._auto_experiment_id is not None:
            self._auto_pending_stop_intent = None
            self._auto_deferred_terminal_status = None
            self._terminalize_reserved_prearm_failure(reason)
            return

        self._release_prearm_creation_failure(reason)

    def _release_prearm_creation_failure(self, reason: str) -> None:
        """Return an unarmed failed creation to idle after metadata settlement."""

        self._auto_state = "idle"
        self._auto_outcome_unknown = False
        self._auto_pending_stop_intent = None
        self._auto_deferred_terminal_status = None
        self._auto_run_creation_error = None
        self._auto_timer.stop()
        self._auto_progress.setVisible(False)
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText(
            f"Автоизмерение не запущено: файл данных не создан; отключение подтверждено ({reason[:120]})"
        )
        self._clear_auto_selection()
        self._on_channels_changed()

    def _terminalize_reserved_prearm_failure(self, reason: str) -> None:
        """Replace a durable reservation when its file never became writable."""

        finished_at = datetime.now(UTC)
        self._auto_persistence_error = reason
        command = self._attachment_command(
            status="FAILED",
            terminal={"accepted_point_count": 0},
            finished_at=finished_at,
            reservation_state="failed_prearm",
        )
        if command is None:
            self._block_after_terminal_attachment_failure("резервирование потеряло идентичность")
            return
        self._auto_terminal_attachment_command = command
        self._auto_terminal_publication_status = "FAILED"
        if not self._dispatch_pending_terminal_attachment():
            self._block_after_terminal_attachment_failure("FAILED-привязка не отправлена")

    def _attachment_command(
        self,
        *,
        status: str,
        terminal: dict[str, Any] | None,
        finished_at: datetime | None,
        reservation_state: str | None = None,
    ) -> dict[str, Any] | None:
        path = self._auto_run_path
        run_id = self._auto_run_id
        started_at = self._auto_run_started_at
        parameters = self._auto_run_parameters
        if path is None or run_id is None or started_at is None or parameters is None:
            return None
        if status != "RUNNING" and self._auto_experiment_id is None:
            return None
        result_summary = {
            "artifact_format": "conductivity_run_v1",
            "point_count": 0 if terminal is None else terminal["accepted_point_count"],
            "recovery_required": terminal is None,
            "persistence_error": self._auto_persistence_error,
        }
        if reservation_state is not None:
            result_summary["reservation_state"] = reservation_state
        command: dict[str, Any] = {
            "cmd": "experiment_attach_run_record",
            "source_tab": "conductivity",
            "source_module": "conductivity_panel",
            "run_type": "autosweep",
            "status": status,
            "source_run_id": run_id,
            "started_at": started_at.isoformat(),
            "parameters": dict(parameters),
            "result_summary": result_summary,
            "artifact_paths": [] if self._auto_run_writer is None and status != "RUNNING" else [str(path)],
        }
        experiment_id = self._auto_experiment_id or self._auto_expected_experiment_id
        if experiment_id is not None:
            command["experiment_id"] = experiment_id
        if finished_at is not None:
            command["finished_at"] = finished_at.isoformat()
        return command

    def _persist_auto_binding_then_arm(self, experiment_id: str | None) -> None:
        writer = self._auto_run_writer
        if writer is None:
            self._latch_auto_outcome_unknown("Контекст файла потерян до фиксации привязки; мощность не изменена.")
            return
        self._auto_experiment_id = experiment_id
        if not self._dispatch_persistence(
            lambda: writer.append_binding(experiment_id),
            self._on_auto_binding_persisted,
            cleanup_on_interruption=writer.close,
        ):
            self._latch_auto_outcome_unknown("Привязка файла не поставлена в очередь; мощность не изменена.")

    def _persist_explicit_unbound_while_stopping(self) -> bool:
        """Record pre-arm absence before a pending Stop can terminalize the run."""

        stopping = self._auto_pending_stop_intent is not None or self._auto_deferred_terminal_status is not None
        if self._auto_experiment_binding_known or not stopping:
            return False
        if self._auto_binding_resolution == "attachment_pending":
            return True
        if self._auto_binding_resolution != "unrequested":
            self._block_after_terminal_persistence_failure(
                "привязка эксперимента не получила устойчивого подтверждения"
            )
            return True
        writer = self._auto_run_writer
        if writer is None:
            self._block_after_terminal_persistence_failure("контекст файла потерян до записи отсутствующей привязки")
            return True
        self._auto_experiment_id = None
        self._auto_binding_resolution = "unbound"
        if not self._dispatch_persistence(
            lambda: writer.append_binding(None),
            self._on_prearm_unbound_persisted,
            cleanup_on_interruption=writer.close,
        ):
            self._block_after_terminal_persistence_failure("отсутствующая привязка не поставлена в очередь")
        return True

    def _on_prearm_unbound_persisted(self, result: dict[str, Any]) -> None:
        if result.get("ok") is not True:
            self._block_after_terminal_persistence_failure(
                f"отсутствующая привязка не подтверждена ({str(result.get('error', 'ошибка'))[:120]})"
            )
            return
        self._auto_experiment_binding_known = True
        self._auto_binding_resolution = "durable"
        if not self._persistence_completion_is_stopped():
            self._latch_auto_outcome_unknown(
                "Останов потерял состояние после записи отсутствующей привязки; мощность не изменена."
            )

    def _on_auto_binding_persisted(self, result: dict[str, Any]) -> None:
        if result.get("ok") is not True:
            self._latch_auto_outcome_unknown(
                f"Привязка файла не подтверждена ({str(result.get('error', 'ошибка'))[:120]}); мощность не изменена."
            )
            return
        self._auto_experiment_binding_known = True
        self._auto_binding_resolution = "durable"
        if self._persistence_completion_is_stopped():
            return
        if self._auto_experiment_id is None:
            self._dispatch_first_auto_target()
            return
        command = self._attachment_command(
            status="RUNNING",
            terminal=None,
            finished_at=None,
            reservation_state="artifact_ready",
        )
        if command is None:
            self._latch_auto_outcome_unknown("Готовность файла потеряна; мощность не изменена.")
            return
        self._auto_binding_resolution = "artifact_attachment_pending"
        if not self._send_auto_cmd(command):
            self._latch_auto_outcome_unknown("Готовность файла не прикреплена; мощность не изменена.")

    def _dispatch_first_auto_target(self) -> None:
        if not self._auto_power_list:
            self._latch_auto_outcome_unknown("Список мощностей потерян до первого шага.")
            return
        power_channel = self._auto_bound_power_channel
        temperature_channels = self._auto_bound_temperature_channels
        if power_channel is None or len(temperature_channels) < 2:
            self._latch_auto_outcome_unknown("Идентичность выбранных каналов потеряна до первого шага.")
            return
        self._auto_step_power_channel = power_channel
        self._auto_step_temperature_channels = temperature_channels
        self._auto_power_target_dispatched = True
        if not self._send_auto_cmd(
            {
                "cmd": "keithley_set_target",
                "channel": self._smu_channel_for(power_channel),
                "p_target": self._auto_power_list[0],
            },
            evidence_power_channel=power_channel,
            evidence_temperature_channels=temperature_channels,
        ):
            self._auto_power_target_dispatched = False
            self._latch_auto_outcome_unknown("Начальная команда мощности не отправлена.")
            return
        self._auto_timer.start()
        self.auto_sweep_started.emit()

    def _persistence_completion_is_stopped(self) -> bool:
        """Prevent target advancement while Stop or outcome-unknown blocks it."""

        status = self._auto_deferred_terminal_status
        if status is not None:
            self._auto_deferred_terminal_status = None
            self._begin_terminalize_auto_run(status)
            return True
        return self._auto_outcome_unknown or self._auto_pending_stop_intent is not None

    def _begin_or_defer_terminal(self, status: str) -> None:
        """Serialize terminal fsync after any already-running persistence operation."""

        if self._auto_terminal_failure_required:
            status = "FAILED"
        if self._auto_persistence_worker is not None:
            self._auto_deferred_terminal_status = status
            return
        self._auto_deferred_terminal_status = None
        self._begin_terminalize_auto_run(status)

    def _begin_terminalize_auto_run(self, status: str) -> None:
        """After authoritative OFF, fsync terminal truth off-thread."""

        if self._auto_terminal_failure_required:
            status = "FAILED"
        if self._auto_run_writer is None and self._auto_binding_resolution in {
            "reservation_pending",
            "reserved",
        }:
            self._auto_deferred_terminal_status = status
            return
        if self._auto_run_writer is None and self._auto_run_creation_failed:
            self._settle_prearm_creation_failure_after_off(self._auto_run_creation_error or "файл данных не создан")
            return
        if not self._auto_experiment_binding_known:
            self._auto_deferred_terminal_status = status
            if self._persist_explicit_unbound_while_stopping():
                return
        writer = self._auto_run_writer
        if writer is None:
            self._block_after_terminal_persistence_failure("контекст файла автоизмерения потерян")
            return
        finished_at = datetime.now(UTC)
        if not self._dispatch_persistence(
            lambda: writer.append_terminal(
                status,
                finished_at=finished_at,
                error=self._auto_persistence_error,
                trailing_write_outcome=self._auto_trailing_write_outcome,
            ),
            lambda result: self._on_auto_terminal_persisted(status, finished_at, result),
            cleanup_on_interruption=writer.close,
        ):
            self._block_after_terminal_persistence_failure("терминальная запись не поставлена в очередь")

    def _on_auto_terminal_persisted(
        self,
        status: str,
        finished_at: datetime,
        result: dict[str, Any],
    ) -> None:
        terminal = result.get("value")
        if result.get("ok") is not True or not isinstance(terminal, dict):
            self._block_after_terminal_persistence_failure(str(result.get("error", "ошибка терминальной записи")))
            return
        attachment = self._attachment_command(status=status, terminal=terminal, finished_at=finished_at)
        if attachment is not None:
            self._auto_terminal_attachment_command = attachment
            self._auto_terminal_publication_status = status
            self._dispatch_pending_terminal_attachment()
            return
        self._publish_terminal_status(status)

    def _publish_terminal_status(self, status: str) -> None:
        if status == "COMPLETED":
            self._publish_auto_complete()
        elif status == "FAILED":
            if self._auto_run_creation_failed and not self._auto_power_target_dispatched:
                self._release_prearm_creation_failure(self._auto_run_creation_error or "файл данных не создан")
            else:
                self._publish_auto_failure()
        else:
            self._publish_auto_stop()

    def _block_after_terminal_persistence_failure(self, reason: str) -> None:
        """Fail closed after OFF when terminal authority could not be fsynced."""

        self._auto_state = "stabilizing"
        self._auto_outcome_unknown = True
        self._auto_pending_stop_intent = "persistence_failed"
        self._auto_timer.stop()
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText(
            f"Источник отключен, но итоговый файл не подтверждён. Автозапуск заблокирован: {reason[:160]}"
        )
        self._update_control_enablement()

    def _dispatch_pending_terminal_attachment(self) -> bool:
        """Keep the guard active while the exact terminal replacement is pending."""

        command = self._auto_terminal_attachment_command
        if command is None or self._auto_terminal_attachment_inflight:
            return False
        if (
            self._auto_power_target_dispatched
            and self._auto_verified_off_connection_generation != self._auto_connection_generation
        ):
            self._update_control_enablement()
            return False
        self._auto_terminal_attachment_inflight = True
        if self._send_auto_cmd(command):
            self._update_control_enablement()
            return True
        self._auto_terminal_attachment_inflight = False
        self._block_after_terminal_attachment_failure("команда прикрепления не отправлена")
        return False

    def _block_after_terminal_attachment_failure(self, reason: str) -> None:
        """Retain finalize guard after OFF/fsync until metadata replacement is acknowledged."""

        self._auto_state = "stabilizing"
        self._auto_outcome_unknown = True
        self._auto_pending_stop_intent = None
        self._auto_terminal_attachment_inflight = False
        self._auto_timer.stop()
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText(
            f"Источник отключен и файл сохранён, но прикрепление не подтверждено. Повторите Стоп: {reason[:140]}"
        )
        self._update_control_enablement()

    def _request_stop_after_point_persistence_failure(self, exc: BaseException) -> None:
        """Request authoritative OFF without accepting or retrying the point."""

        self._auto_persistence_error = f"{type(exc).__name__}: {exc}"
        self._auto_trailing_write_outcome = "indeterminate"
        self._auto_terminal_failure_required = True
        if self._auto_deferred_terminal_status is not None:
            self._auto_deferred_terminal_status = "FAILED"
        self._auto_timer.stop()
        self._auto_pending_stop_intent = "failure"
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText(
            "Ошибка сохранения точки — переход запрещён; ожидается подтверждение отключения источника"
        )
        self._update_control_enablement()
        if not self._send_auto_cmd(
            {
                "cmd": "keithley_stop",
                "channel": self._smu_channel_for(
                    self._auto_bound_power_channel or self._auto_step_power_channel or self._power_channel
                ),
            },
            stop_intent="failure",
        ):
            self._auto_pending_stop_intent = None
            self._latch_auto_outcome_unknown("Команда останова после ошибки сохранения не отправлена.")

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
            if self._auto_state in {"reserving", "stabilizing"}:
                self._auto_state = "stabilizing"
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
        if cmd.get("cmd") == "keithley_set_target":
            self._auto_verified_off_connection_generation = None
        if cmd.get("cmd") == "experiment_attach_run_record" and cmd.get("status") == "RUNNING":
            reservation_state = (cmd.get("result_summary") or {}).get("reservation_state")
            self._auto_binding_resolution = (
                "artifact_attachment_pending" if reservation_state == "artifact_ready" else "reservation_pending"
            )
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
        is_start_attachment = (
            command.get("cmd") == "experiment_attach_run_record" and command.get("status") == "RUNNING"
        )
        is_ready_attachment = (
            is_start_attachment and (command.get("result_summary") or {}).get("reservation_state") == "artifact_ready"
        )
        reconcile_prearm = (
            is_start_attachment and not is_ready_attachment and self._auto_binding_resolution == "reservation_pending"
        ) or (is_ready_attachment and self._auto_binding_resolution == "artifact_attachment_pending")
        pending_token = self._auto_pending_token
        if pending_token is not None and token != pending_token and not reconcile_prearm:
            logger.warning(
                "Ответ вытесненной авто-команды проигнорирован: %s, token=%s, current=%s",
                command.get("cmd", "?"),
                token,
                pending_token,
            )
            return
        if token == pending_token:
            self._auto_pending_token = None

        if expected_operation_generation != self._auto_operation_generation or (
            not reconcile_prearm
            and (expected_connection_generation != self._auto_connection_generation or not self._connected)
        ):
            logger.warning(
                "Запоздалый ответ автоизмерения проигнорирован: %s, token=%s",
                command.get("cmd", "?"),
                token,
            )
            return

        if command.get("cmd") == "experiment_attach_run_record":
            if not is_start_attachment:
                self._auto_terminal_attachment_inflight = False
                error = (
                    str(result.get("error", "неизвестная ошибка"))
                    if isinstance(result, dict)
                    else "некорректный ответ Engine"
                )
                record = result.get("run_record") if isinstance(result, dict) else None
                context = record.get("experiment_context") if isinstance(record, dict) else None
                if (
                    not isinstance(result, dict)
                    or result.get("ok") is not True
                    or result.get("attached") is not True
                    or not isinstance(record, dict)
                    or record.get("source_run_id") != self._auto_run_id
                    or record.get("status") != command.get("status")
                    or record.get("parameters") != command.get("parameters")
                    or record.get("result_summary") != command.get("result_summary")
                    or record.get("artifact_paths") != command.get("artifact_paths")
                    or not isinstance(context, dict)
                    or context.get("experiment_id") != self._auto_experiment_id
                ):
                    logger.warning("Терминальная замена автоизмерения не подтверждена: %s", error)
                    self._block_after_terminal_attachment_failure(error)
                    return
                status = self._auto_terminal_publication_status
                if status is None or status != command.get("status"):
                    self._block_after_terminal_attachment_failure("идентичность терминального состояния потеряна")
                    return
                if (
                    self._auto_power_target_dispatched
                    and self._auto_verified_off_connection_generation != self._auto_connection_generation
                ):
                    self._block_after_terminal_attachment_failure("подтверждение отключения источника устарело")
                    return
                self._auto_terminal_attachment_command = None
                self._auto_terminal_publication_status = None
                self._auto_outcome_unknown = False
                self._publish_terminal_status(status)
                return
            if not reconcile_prearm:
                logger.warning("Повторный ответ RUNNING-привязки проигнорирован после разрешения привязки.")
                return
            if not isinstance(result, dict) or result.get("ok") is not True:
                error = (
                    str(result.get("error", "неизвестная ошибка"))
                    if isinstance(result, dict)
                    else "некорректный ответ Engine"
                )
                self._auto_binding_resolution = "unrequested"
                if not is_ready_attachment and self._auto_run_writer is None:
                    self._auto_state = "stabilizing"
                    if self._auto_deferred_terminal_status is not None:
                        if not self._begin_auto_writer_creation():
                            self._auto_run_creation_failed = True
                            self._auto_run_creation_error = "file creation was not queued"
                            self._settle_prearm_creation_failure_after_off(self._auto_run_creation_error)
                        return
                    self._auto_run_creation_failed = True
                    self._auto_run_creation_error = error
                if self._persistence_completion_is_stopped():
                    return
                self._latch_auto_outcome_unknown(
                    f"RUNNING-привязка не подтверждена ({error[:120]}); мощность не изменена."
                )
                return
            if result.get("attached") is False:
                if not is_ready_attachment:
                    logger.warning(
                        "Активный эксперимент отсутствует; автоизмерение продолжено с автономным файлом данных."
                    )
                    self.show_warning(
                        "Активный эксперимент не найден. Автоизмерение продолжено с автономным файлом данных."
                    )
                    self._auto_state = "stabilizing"
                    self._auto_binding_resolution = "unbound"
                    if not self._begin_auto_writer_creation():
                        self._on_auto_run_created(
                            {
                                "ok": False,
                                "error": "file creation was not queued",
                                "error_type": "RuntimeError",
                            }
                        )
                    return
                self._auto_run_creation_failed = True
                self._auto_run_creation_error = "активный эксперимент отсутствует"
                self._auto_binding_resolution = "unrequested"
                if self._persistence_completion_is_stopped():
                    return
                self._release_prearm_creation_failure(self._auto_run_creation_error)
                return
            if not is_ready_attachment:
                self._auto_state = "stabilizing"
            record = result.get("run_record")
            context = record.get("experiment_context") if isinstance(record, dict) else None
            experiment_id = context.get("experiment_id") if isinstance(context, dict) else None
            if (
                not isinstance(record, dict)
                or record.get("source_run_id") != self._auto_run_id
                or record.get("status") != "RUNNING"
                or record.get("parameters") != command.get("parameters")
                or record.get("result_summary") != command.get("result_summary")
                or record.get("artifact_paths") != command.get("artifact_paths")
                or type(experiment_id) is not str
                or not experiment_id
                or (is_ready_attachment and experiment_id != self._auto_expected_experiment_id)
            ):
                self._latch_auto_outcome_unknown(
                    "RUNNING-привязка вернула несогласованную идентичность; мощность не изменена."
                )
                return
            self._auto_experiment_id = experiment_id
            if is_ready_attachment:
                self._auto_binding_resolution = "durable"
                if not self._persistence_completion_is_stopped():
                    self._dispatch_first_auto_target()
                return
            self._auto_expected_experiment_id = experiment_id
            self._auto_binding_resolution = "reserved"
            if not self._begin_auto_writer_creation():
                self._latch_auto_outcome_unknown(
                    "Создание зарезервированного файла не поставлено в очередь; мощность не изменена."
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
            self._auto_verified_off_connection_generation = expected_connection_generation
            if self._auto_run_creation_failed:
                self._settle_prearm_creation_failure_after_off(self._auto_run_creation_error or "файл данных не создан")
                return
            if stop_intent == "terminal_attachment":
                self._auto_outcome_unknown = False
                if not self._dispatch_pending_terminal_attachment():
                    self._block_after_terminal_attachment_failure("команда прикрепления не отправлена")
                return
            if stop_intent == "complete":
                self._commit_auto_complete()
            elif stop_intent == "failure":
                self._commit_auto_failure()
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

    def _refuse_auto_start(self, reason: str) -> None:
        """Say why an auto sweep did not start, and leave the operator able to retry.

        A silent early return is the worst refusal this program can make: the
        operator presses Start, nothing happens, and nothing is said.  Every exit
        from _on_auto_start before dispatch goes through here.
        """

        logger.warning("Автоизмерение не запущено: %s", reason)
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText(f"Автоизмерение не запущено: {reason}")

    @Slot()
    def _on_auto_start(self) -> None:
        # Button enablement is presentation only.  The handler owns the final
        # live-authority check so direct/queued invocation cannot bypass it.
        # Each of these is a REFUSAL and must be spoken, never silent.
        if not self._connected:
            self._refuse_auto_start("нет связи с прибором")
            return
        if self._auto_state in {"reserving", "stabilizing"}:
            self._refuse_auto_start(f"измерение уже идёт (состояние {self._auto_state})")
            return
        if self._auto_outcome_unknown:
            self._refuse_auto_start("предыдущий результат не подтверждён; требуется сверка")
            return
        if self._auto_pending_token is not None:
            self._refuse_auto_start("предыдущая команда ещё не подтверждена")
            return
        if len(self._chain) < 2:
            QMessageBox.warning(self, "Ошибка", "Выберите минимум 2 датчика в цепочке.")
            return
        powers = self._generate_power_list()
        if not powers:
            QMessageBox.warning(self, "Ошибка", "Список мощностей пуст.")
            return
        if not self._snapshot_auto_selection():
            self._refuse_auto_start("выбор каналов не зафиксирован")
            return
        from cryodaq.paths import get_data_dir

        try:
            data_dir = get_data_dir()
        except OSError as exc:
            self._on_auto_run_created(
                {
                    "ok": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
            )
            return
        self._auto_power_list = powers
        self._auto_step = 0
        self._auto_results = []
        self._auto_state = "reserving"
        self._auto_operation_generation += 1
        self._auto_outcome_unknown = False
        self._auto_pending_stop_intent = None
        self._auto_deferred_terminal_status = None
        self._auto_run_creation_failed = False
        self._auto_run_creation_error = None
        self._auto_terminal_attachment_command = None
        self._auto_terminal_publication_status = None
        self._auto_terminal_attachment_inflight = False
        self._auto_verified_off_connection_generation = None
        self._auto_terminal_failure_required = False
        self._auto_power_target_dispatched = False
        self._invalidate_auto_step_evidence()

        self._auto_start_btn.setEnabled(False)
        self._auto_stop_btn.setEnabled(True)
        self._auto_progress.setVisible(True)
        self._auto_progress.setValue(0)
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText(f"Шаг 1/{len(powers)} — P = {powers[0]:.4g} Вт")
        self._update_control_enablement()

        if not self._begin_auto_run_async(powers, data_dir):
            self._latch_auto_outcome_unknown("Создание файла не поставлено в очередь; мощность не изменена.")
            return
        logger.info("Автоизмерение: старт, %d шагов, P=%s", len(powers), powers)

    @Slot()
    def _on_auto_stop(self) -> None:
        if self._auto_state not in {"reserving", "stabilizing"}:
            return
        self._auto_state = "stabilizing"
        terminal_attachment_pending = self._auto_terminal_attachment_command is not None
        if (
            terminal_attachment_pending
            and self._auto_verified_off_connection_generation == self._auto_connection_generation
        ):
            if self._auto_terminal_attachment_inflight or self._auto_pending_token is not None:
                return
            self._dispatch_pending_terminal_attachment()
            return
        if self._auto_pending_stop_intent is not None:
            return
        if not self._connected:
            self._latch_auto_outcome_unknown(
                "Останов нельзя отправить без живой связи; состояние источника требует сверки."
            )
            return
        self._auto_timer.stop()
        if terminal_attachment_pending:
            stop_intent = "terminal_attachment"
        else:
            stop_intent = "failure" if self._auto_terminal_failure_required else "operator"
        self._auto_pending_stop_intent = stop_intent
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText("Останов запрошен — ожидается подтверждение отключения источника")
        self._update_control_enablement()
        if not self._send_auto_cmd(
            {
                "cmd": "keithley_stop",
                "channel": self._smu_channel_for(
                    self._auto_bound_power_channel or self._auto_step_power_channel or self._power_channel
                ),
            },
            stop_intent=stop_intent,
        ):
            self._auto_pending_stop_intent = None
            self._latch_auto_outcome_unknown("Команда останова не отправлена.")

    def _commit_auto_stop(self) -> None:
        """After authoritative OFF, begin terminal persistence."""

        self._begin_or_defer_terminal("ABORTED")

    def _publish_auto_stop(self) -> None:
        """Apply operator stop only after SafetyManager confirms the command."""

        self._auto_state = "idle"
        self._auto_outcome_unknown = False
        self._auto_pending_stop_intent = None
        self._auto_power_target_dispatched = False
        self._auto_timer.stop()
        self._auto_progress.setVisible(False)
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText("Остановлено оператором — отключение и запись подтверждены")
        self._clear_auto_selection()
        self._on_channels_changed()
        logger.info("Автоизмерение: остановлено оператором, отключение и запись подтверждены")
        self.auto_sweep_aborted.emit("operator_stop")

    def _commit_auto_failure(self) -> None:
        """After authoritative OFF, begin FAILED terminal persistence."""

        self._begin_or_defer_terminal("FAILED")

    def _publish_auto_failure(self) -> None:
        """Publish a durable FAILED run only after authoritative source OFF."""

        self._auto_state = "done"
        self._auto_outcome_unknown = False
        self._auto_pending_stop_intent = None
        self._auto_terminal_failure_required = False
        self._auto_power_target_dispatched = False
        self._auto_timer.stop()
        self._auto_progress.setVisible(False)
        self._auto_status_label.setVisible(True)
        self._auto_status_label.setText(
            "Автоизмерение остановлено: точка не принята; отключение и FAILED-запись подтверждены"
        )
        self._clear_auto_selection()
        self._on_channels_changed()
        logger.error("Автоизмерение завершено с ошибкой сохранения: %s", self._auto_persistence_error)
        self.auto_sweep_aborted.emit("persistence_failure")

    @Slot()
    def _auto_tick(self) -> None:
        if (
            self._auto_state != "stabilizing"
            or not self._connected
            or self._auto_persistence_worker is not None
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
        threshold = self._auto_stabilization_threshold_pct
        min_wait = self._auto_minimum_wait_s
        if threshold is None or min_wait is None:
            self._latch_auto_outcome_unknown("Параметры приёмки шага потеряны; переход мощности запрещён.")
            return
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

    def _auto_record_point(self) -> bool:
        P = self._auto_step_power_value
        temperature_channels = self._auto_step_temperature_channels
        if len(temperature_channels) < 2 or P is None:
            self._request_stop_after_point_persistence_failure(ValueError("step measurement identity is incomplete"))
            return False
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
        point = {
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "P_W": P,
            "T_hot_K": T_hot,
            "T_cold_K": T_cold,
            "T_avg_K": (T_hot + T_cold) / 2.0,
            "dT_K": dT,
            "R_KW": R,
            "G_WK": G,
            "settled_pct": min_settled,
        }
        writer = self._auto_run_writer
        if writer is None:
            self._request_stop_after_point_persistence_failure(RuntimeError("autosweep writer is missing"))
            return False
        self._auto_pending_point_result = {
            "P": P,
            "T_hot": T_hot,
            "T_cold": T_cold,
            "dT": dT,
            "R": R,
            "G": G,
            "settled_pct": min_settled,
        }
        if not self._dispatch_persistence(
            lambda: writer.append_point(point),
            self._on_auto_point_persisted,
            cleanup_on_interruption=writer.close,
        ):
            self._auto_pending_point_result = None
            self._request_stop_after_point_persistence_failure(RuntimeError("point write was not queued"))
            return False
        return True

    def _on_auto_point_persisted(self, result: dict[str, Any]) -> None:
        pending = self._auto_pending_point_result
        self._auto_pending_point_result = None
        if result.get("ok") is not True or pending is None:
            error = RuntimeError(str(result.get("error", "point write failed")))
            logger.error("Автоизмерение: точка не принята из-за ошибки сохранения: %s", error)
            self._request_stop_after_point_persistence_failure(error)
            return
        self._auto_results.append(pending)
        self._auto_step += 1
        logger.info(
            "Автоизмерение: точка P=%.4g, dT=%.4f, R=%.4g, G=%.4g, settled=%.0f%%",
            pending["P"],
            pending["dT"],
            pending["R"],
            pending["G"],
            pending["settled_pct"],
        )
        if self._persistence_completion_is_stopped():
            return
        if self._auto_step >= len(self._auto_power_list):
            self._auto_complete()
            return
        next_p = self._auto_power_list[self._auto_step]
        power_channel = self._auto_step_power_channel
        temperature_channels = self._auto_step_temperature_channels
        self._invalidate_auto_step_evidence()
        if power_channel is None or not temperature_channels:
            self._latch_auto_outcome_unknown("Идентичность следующего измерительного шага потеряна.")
            return
        if not self._send_auto_cmd(
            {
                "cmd": "keithley_set_target",
                "channel": self._smu_channel_for(power_channel),
                "p_target": next_p,
            },
            evidence_power_channel=power_channel,
            evidence_temperature_channels=temperature_channels,
        ):
            self._latch_auto_outcome_unknown("Команда следующей мощности не отправлена.")
            return
        logger.info(
            "Автоизмерение: шаг %d/%d, P=%.4g Вт",
            self._auto_step + 1,
            len(self._auto_power_list),
            next_p,
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
                "channel": self._smu_channel_for(
                    self._auto_bound_power_channel or self._auto_step_power_channel or self._power_channel
                ),
            },
            stop_intent="complete",
        ):
            self._auto_pending_stop_intent = None
            self._latch_auto_outcome_unknown("Команда завершающего останова не отправлена.")

    def _commit_auto_complete(self) -> None:
        """After authoritative OFF, begin COMPLETED terminal persistence."""

        self._begin_or_defer_terminal("COMPLETED")

    def _publish_auto_complete(self) -> None:
        """Publish completion only after authoritative source shutdown."""

        self._auto_state = "done"
        self._auto_outcome_unknown = False
        self._auto_pending_stop_intent = None
        self._auto_power_target_dispatched = False
        self._auto_progress.setValue(100)
        self._clear_auto_selection()
        self._on_channels_changed()
        n = len(self._auto_results)
        self._auto_status_label.setText(f"Завершено: {n} точек; отключение и запись подтверждены")
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
        persistence_worker = self._auto_persistence_worker
        writer = self._auto_run_writer
        if persistence_worker is not None:
            persistence_worker.requestInterruption()
        elif writer is not None:
            close_worker = _ConductivityPersistenceWorker(
                writer.close,
                cleanup_on_interruption=writer.close,
            )
            self._auto_persistence_worker = close_worker
            try:
                close_worker.start()
            except (RuntimeError, OSError):
                logger.exception("Autosweep writer close could not be scheduled during panel shutdown")
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
        if not connected:
            self._latest_channel_descriptors.clear()
            self._latest_channel_descriptor_generations.clear()
            self._auto_verified_off_connection_generation = None
        if not connected and self._auto_state in {"reserving", "stabilizing"}:
            self._auto_state = "stabilizing"
            self._auto_pending_token = None
            self._auto_pending_stop_intent = None
            self._auto_terminal_attachment_inflight = False
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
        active = self._auto_state in {"reserving", "stabilizing"}
        start_ok = (
            self._connected and not active and not self._auto_outcome_unknown and self._auto_pending_token is None
        )
        if self._auto_terminal_attachment_command is not None:
            stop_ok = (
                self._connected
                and active
                and not self._auto_terminal_attachment_inflight
                and self._auto_pending_token is None
            )
        else:
            stop_ok = self._connected and active and self._auto_pending_stop_intent is None
        self._auto_start_btn.setEnabled(start_ok)
        self._auto_stop_btn.setEnabled(stop_ok)
        self._power_combo.setEnabled(not active)
        self._settled_pct_spin.setEnabled(not active)
        self._min_wait_spin.setEnabled(not active)
        for checkbox in self._checkboxes.values():
            checkbox.setEnabled(not active)

    def get_auto_state(self) -> str:
        """Return the conservative public auto-sweep guard state.

        Values are ``"idle"``, ``"reserving"``, ``"stabilizing"``, and ``"done"``.
        ``"reserving"`` is not yet an active sweep: no file exists and no
        source target can be dispatched until the engine commits its RUNNING
        reservation.
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
