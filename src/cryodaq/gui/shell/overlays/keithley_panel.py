"""KeithleyPanel — dual-channel Keithley 2604B operator overlay (Phase II.6).

Supersedes the dead B.7 mode-based shell overlay. Aligned with engine
power-control API (``p_target`` + ``v_comp`` + ``i_comp``) and Design
System v1.0.1 tokens.

Per channel (smua + smub, shown side-by-side as «Канал А» / «Канал B»,
Cyrillic А per RULE-COPY-002):
- P target / V compliance / I compliance QDoubleSpinBox, debounced 300ms
- Старт / Стоп / АВАР. ОТКЛ. buttons
- 4 live readouts (V / I / R / P) in Fira Mono with tabular figures
- 4 rolling pyqtgraph plots (V / I / R / P), 2×2 grid, 10m/1h/6h window
- State badge (ВЫКЛ / ВКЛ / АВАРИЯ) driven by backend state channel

Panel-level:
- «Старт A+B» / «Стоп A+B» / «АВАР. ОТКЛ. A+B»
- Time-window toolbar affecting both channels
- Connection indicator, safety gate label, transient status banner

Public API (MainWindowV2 push points):
- ``on_reading(reading)``  — route a single Reading into the overlay
- ``set_connected(ok)``    — mark Keithley connection state
- ``set_safety_ready(ok, reason="")`` — toggle safety gate

Out of scope (tracked as follow-ups):
- FU.4: K4 custom-command popup
- FU.5: HoldConfirm 1s hold for emergency button (shipped with QMessageBox.warning)
- Phase III.3: removal of legacy ``widgets/keithley_panel.py``
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from collections.abc import Callable

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.drivers.base import Reading
from cryodaq.gui import theme
from cryodaq.gui._plot_style import apply_plot_style
from cryodaq.gui.shell.overlays._base_panel import is_stale
from cryodaq.gui.state.time_window import TimeWindow, get_time_window_controller
from cryodaq.gui.state.time_window_selector import TimeWindowSelector
from cryodaq.gui.zmq_client import ZmqCommandWorker

logger = logging.getLogger(__name__)

_MEASUREMENTS: tuple[str, ...] = ("voltage", "current", "resistance", "power")
_MEASUREMENT_LABELS: dict[str, str] = {
    "voltage": "Напряжение",
    "current": "Ток",
    "resistance": "Сопротивление",
    "power": "Мощность",
}
_MEASUREMENT_UNITS: dict[str, str] = {
    "voltage": "В",
    "current": "А",
    "resistance": "Ом",
    "power": "Вт",
}

_BUFFER_MAXLEN = 3600
_DEBOUNCE_MS = 300
_REFRESH_MS = 500
_STALE_AFTER_S = 5.0
_BANNER_AUTO_CLEAR_MS = 4000

_STATE_LABELS: dict[str, str] = {
    "unknown": "НЕИЗВЕСТНО",
    "off": "ВЫКЛ",
    "on": "ВКЛ",
    "fault": "АВАРИЯ",
}


def _format_voltage(value: float) -> str:
    if not math.isfinite(value):
        return "— В"
    return f"{value:.3f} В"


def _format_current(value: float) -> str:
    if not math.isfinite(value):
        return "— А"
    return f"{value:.4g} А"


def _format_resistance(value: float) -> str:
    if not math.isfinite(value):
        return "— Ом"
    return f"{value:.2f} Ом"


def _format_power(value: float) -> str:
    if not math.isfinite(value):
        return "— Вт"
    return f"{value:.3f} Вт"


_FORMATTERS: dict[str, Callable[[float], str]] = {
    "voltage": _format_voltage,
    "current": _format_current,
    "resistance": _format_resistance,
    "power": _format_power,
}

# Dash placeholder per suffix — used by handle_reading when a
# derived quantity is meaningless (e.g. R at I≈0).
_DASH_BY_UNIT: dict[str, str] = {
    "voltage": "— В",
    "current": "— А",
    "resistance": "— Ом",
    "power": "— Вт",
}


def _mono_value_font() -> QFont:
    """Fira Mono value font with tabular figures enabled when supported."""

    font = QFont(theme.FONT_MONO)
    font.setPixelSize(theme.FONT_MONO_VALUE_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_MONO_VALUE_WEIGHT))
    try:
        font.setFeature(QFont.Tag("tnum"), 1)
    except (AttributeError, TypeError):
        # Qt < 6.7 has no setFeature; tabular figures fall back to default.
        pass
    return font


def _label_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_LABEL_SIZE)
    font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
    return font


def _title_font() -> QFont:
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_LG)
    font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
    return font


def _tick_font() -> QFont:
    # v0.55.2 ds-013: arithmetic on FONT_LABEL_SIZE (12-2=10) clamps via
    # max() back up to FONT_SIZE_XS (11) — the clamp was load-bearing,
    # so the smallest legible tick value really is XS. Use the token
    # directly per RULE-TYPO-007 (no arithmetic on font tokens).
    font = QFont(theme.FONT_BODY)
    font.setPixelSize(theme.FONT_SIZE_XS)
    return font


def _style_button(btn: QPushButton, variant: str) -> None:
    """Apply DS-v1.0.1 button QSS. No dependence on legacy helpers."""

    radius = theme.RADIUS_MD
    if variant == "primary":
        # Phase III.A: primary uses ACCENT (UI activation), not STATUS_OK.
        bg, fg = theme.ACCENT, theme.ON_ACCENT
        border_color = theme.BORDER_SUBTLE
    elif variant == "warning":
        bg, fg = theme.STATUS_WARNING, theme.ON_PRIMARY
        border_color = theme.BORDER_SUBTLE
    elif variant == "destructive":
        bg, fg = theme.STATUS_FAULT, theme.ON_DESTRUCTIVE
        border_color = theme.BORDER_SUBTLE
    elif variant == "accent":
        bg, fg = theme.ACCENT, theme.ON_ACCENT
        border_color = theme.BORDER_SUBTLE
    elif variant == "caution_outlined":
        # Phase III.D Item 10: combined «Старт A+B» is more
        # consequential than per-channel Старт (two heaters at once).
        # Render as outlined STATUS_CAUTION rather than filled ACCENT
        # so it never reads as an identical twin of the per-channel
        # primary button.
        bg = "transparent"
        fg = theme.STATUS_CAUTION
        border_color = theme.STATUS_CAUTION
    else:  # "neutral"
        bg, fg = theme.SURFACE_MUTED, theme.FOREGROUND
        border_color = theme.BORDER_SUBTLE
    btn.setStyleSheet(
        f"QPushButton {{"
        f" background-color: {bg};"
        f" color: {fg};"
        f" border: 1px solid {border_color};"
        f" border-radius: {radius}px;"
        f" padding: {theme.SPACE_1}px {theme.SPACE_3}px;"
        f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        f"}} "
        f"QPushButton:disabled {{"
        f" background-color: {theme.SURFACE_MUTED};"
        f" color: {theme.TEXT_DISABLED};"
        f" border: 1px solid {theme.BORDER_SUBTLE};"
        f"}}"
    )


class _SmuChannelBlock(QFrame):
    """One SMU channel: header + controls + readouts + plots grid."""

    channel_start_requested = Signal(str, float, float, float)
    channel_stop_requested = Signal(str)
    channel_emergency_requested = Signal(str)
    channel_target_updated = Signal(str, float)
    channel_limits_updated = Signal(str, float, float)
    command_started = Signal(str, int, str)
    command_finished = Signal(str, int, str, str, str)
    command_rejected = Signal(str, str, str)
    outcome_reconciled = Signal(str)

    def __init__(self, key: str, label: str, palette_index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._key = key
        self._label_text = label
        self._palette_index = palette_index
        # Connection/Safety readiness does not prove the physical output state.
        # Start remains fail-closed until an authoritative OFF event arrives.
        self._channel_state: str = "unknown"
        self._last_confirmed_state: str | None = None
        self._connected: bool = False
        self._safety_ready: bool = False
        self._read_only: bool = False
        self._connection_generation = 0
        self._source_observation_revision = 0
        self._safety_observation_revision = 0
        self._unknown_outcome_requires: tuple[int, int] | None = None
        self._normal_pending_token: int | None = None
        # IV.2 A.3: default to the longest per-block buffer so the
        # first tick before _apply_global_window lands renders the
        # full available history. Parent panel overwrites this the
        # moment the TimeWindow controller fires.
        self._window_s: float = float(_BUFFER_MAXLEN)
        self._workers: list[ZmqCommandWorker] = []
        self._command_sequence = 0
        self._settled_command_tokens: set[int] = set()
        self._buffers: dict[str, deque[tuple[float, float]]] = {m: deque(maxlen=_BUFFER_MAXLEN) for m in _MEASUREMENTS}
        self._value_labels: dict[str, QLabel] = {}
        self._plot_widgets: dict[str, pg.PlotWidget] = {}
        self._plots: dict[str, pg.PlotDataItem] = {}
        self._last_update_ts: float | None = None
        self._stale: bool = False

        self.setObjectName(f"smuBlock_{key}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._build_ui()
        self._wire_debounce_timers()
        self._apply_frame_style()
        self._apply_state_visuals()
        self._update_control_enablement()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_3, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        root.setSpacing(theme.SPACE_2)

        root.addWidget(self._build_header_row())
        root.addWidget(self._build_controls_card())
        root.addWidget(self._build_readouts_card())
        root.addWidget(self._build_plots_grid(), stretch=1)

    def _build_header_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        self._title_label = QLabel(self._label_text)
        self._title_label.setFont(_title_font())
        self._title_label.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(self._title_label)
        layout.addStretch()

        self._state_badge = QLabel(_STATE_LABELS["unknown"])
        badge_font = _label_font()
        badge_font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
        self._state_badge.setFont(badge_font)
        layout.addWidget(self._state_badge)

        return row

    def _build_controls_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName(f"smuControls_{self._key}")
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        card.setStyleSheet(
            f"#smuControls_{self._key} {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )

        # Two-row layout (IV.1 finding 4). Row 1 — numeric inputs,
        # Row 2 — actions. Previously every control sat on a single
        # horizontal row; spin arrows bled into the next label
        # ("V⬍редел") on narrower widths, and the inputs/actions mix
        # forced the operator to visually re-group "set parameters"
        # vs "run". Two rows separate the concerns explicitly and let
        # each row breathe.
        root = QVBoxLayout(card)
        root.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        root.setSpacing(theme.SPACE_2)

        inputs_row = QHBoxLayout()
        inputs_row.setContentsMargins(0, 0, 0, 0)
        # Generous spacing between input groups so the spin arrows at
        # the right edge of each spinbox never reach the next caption.
        inputs_row.setSpacing(theme.SPACE_4)

        self._p_spin = self._spinbox(0.0, 10.0, 0.5, 0.1, 3)
        inputs_row.addWidget(self._caption("P цель (Вт):"))
        inputs_row.addWidget(self._p_spin)

        self._v_spin = self._spinbox(0.0, 200.0, 40.0, 1.0, 2)
        inputs_row.addWidget(self._caption("V предел (В):"))
        inputs_row.addWidget(self._v_spin)

        self._i_spin = self._spinbox(0.0, 3.0, 1.0, 0.1, 3)
        inputs_row.addWidget(self._caption("I предел (А):"))
        inputs_row.addWidget(self._i_spin)

        inputs_row.addStretch()
        root.addLayout(inputs_row)
        self._controls_inputs_row = inputs_row

        actions_row = QHBoxLayout()
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.setSpacing(theme.SPACE_2)

        self._start_btn = QPushButton("Старт")
        _style_button(self._start_btn, "primary")
        self._start_btn.clicked.connect(self._on_start_clicked)
        actions_row.addWidget(self._start_btn)

        self._stop_btn = QPushButton("Стоп")
        _style_button(self._stop_btn, "warning")
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        actions_row.addWidget(self._stop_btn)

        self._emergency_btn = QPushButton("АВАР. ОТКЛ.")
        _style_button(self._emergency_btn, "destructive")
        self._emergency_btn.clicked.connect(self._on_emergency_clicked)
        actions_row.addWidget(self._emergency_btn)

        actions_row.addStretch()
        root.addLayout(actions_row)
        self._controls_actions_row = actions_row

        return card

    def _build_readouts_card(self) -> QWidget:
        self._readouts_card = QFrame()
        self._readouts_card.setObjectName(f"smuReadouts_{self._key}")
        self._readouts_card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._readouts_card_default_style = (
            f"#smuReadouts_{self._key} {{"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {theme.BORDER_SUBTLE};"
            f" border-radius: {theme.RADIUS_MD}px;"
            f"}}"
        )
        self._readouts_card.setStyleSheet(self._readouts_card_default_style)

        layout = QHBoxLayout(self._readouts_card)
        layout.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        layout.setSpacing(theme.SPACE_2)

        for key in _MEASUREMENTS:
            tile = self._build_readout_tile(key)
            layout.addWidget(tile, stretch=1)

        return self._readouts_card

    def _build_readout_tile(self, key: str) -> QWidget:
        tile = QWidget()
        tile_layout = QVBoxLayout(tile)
        tile_layout.setContentsMargins(theme.SPACE_2, theme.SPACE_1, theme.SPACE_2, theme.SPACE_1)
        tile_layout.setSpacing(theme.SPACE_1)

        title = QLabel(_MEASUREMENT_LABELS[key])
        title.setFont(_label_font())
        title.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile_layout.addWidget(title)

        value = QLabel(f"— {_MEASUREMENT_UNITS[key]}")
        value.setFont(_mono_value_font())
        value.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile_layout.addWidget(value)

        self._value_labels[key] = value
        return tile

    def _build_plots_grid(self) -> QWidget:
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(theme.SPACE_2)

        pen_color = theme.PLOT_LINE_PALETTE[self._palette_index % len(theme.PLOT_LINE_PALETTE)]
        pen = pg.mkPen(color=pen_color, width=theme.PLOT_LINE_WIDTH)
        tick_font = _tick_font()

        for idx, key in enumerate(_MEASUREMENTS):
            plot = pg.PlotWidget()
            apply_plot_style(plot)
            item = plot.getPlotItem()
            item.setLabel(
                "left",
                _MEASUREMENT_LABELS[key],
                units=_MEASUREMENT_UNITS[key],
            )
            # Keithley measurements (V / I / P / R) must stay in their
            # stated base units; autoSIPrefix would turn 0.5 V into
            # 500 mV silently, confusing the operator about setpoint
            # vs. measurement magnitude.
            item.getAxis("left").enableAutoSIPrefix(False)
            # Phase III.D Item 8: X axis was tick-only ("-35 -30 … 0") with
            # no units; operator could not tell seconds from minutes. The
            # domain is seconds before now — label explicitly.
            item.setLabel("bottom", "Время", units="с")
            item.getAxis("bottom").enableAutoSIPrefix(False)
            for axis_name in ("left", "bottom"):
                axis = item.getAxis(axis_name)
                if axis is not None:
                    axis.setStyle(tickFont=tick_font)
            plot_item = plot.plot([], [], pen=pen)
            self._plot_widgets[key] = plot
            self._plots[key] = plot_item
            row, col = divmod(idx, 2)
            grid.addWidget(plot, row, col)

        return grid_widget

    # ------------------------------------------------------------------
    # Styling helpers
    # ------------------------------------------------------------------

    def _apply_frame_style(self) -> None:
        if self._channel_state == "fault":
            border_color = theme.STATUS_FAULT
            border_width = 3
        elif self._channel_state == "unknown":
            border_color = theme.STATUS_CAUTION
            border_width = 2
        else:
            border_color = theme.BORDER_SUBTLE
            border_width = 1
        self.setStyleSheet(
            f"#smuBlock_{self._key} {{"
            f" background-color: {theme.SURFACE_PANEL};"
            f" border: {border_width}px solid {border_color};"
            f" border-radius: {theme.RADIUS_LG}px;"
            f"}}"
        )

    def _apply_state_visuals(self) -> None:
        text = _STATE_LABELS.get(self._channel_state, _STATE_LABELS["unknown"])
        if self._channel_state == "unknown" and self._last_confirmed_state:
            last = _STATE_LABELS.get(self._last_confirmed_state, _STATE_LABELS["unknown"])
            text = f"{text} · последнее: {last}"
        self._state_badge.setText(text)
        self._state_badge.setAccessibleName(text)
        self._state_badge.setAccessibleDescription(
            "Текущее состояние источника неизвестно; последнее подтверждённое "
            "состояние показано только как историческое свидетельство."
            if self._channel_state == "unknown" and self._last_confirmed_state
            else text
        )
        if self._channel_state == "on":
            # Source activity is not proof of health.  Safety green remains
            # reserved for independently proven healthy state.
            color = theme.ACCENT
        elif self._channel_state == "fault":
            color = theme.STATUS_FAULT
        elif self._channel_state == "unknown":
            color = theme.STATUS_CAUTION
        else:
            color = theme.MUTED_FOREGROUND
        self._state_badge.setStyleSheet(
            f"color: {color}; background: transparent; border: none; font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        )
        self._apply_frame_style()

    def _apply_readouts_style(self) -> None:
        if self._stale:
            self._readouts_card.setStyleSheet(
                f"#smuReadouts_{self._key} {{"
                f" background-color: {theme.SURFACE_CARD};"
                f" border: 1px solid {theme.STATUS_STALE};"
                f" border-radius: {theme.RADIUS_MD}px;"
                f"}}"
            )
        else:
            self._readouts_card.setStyleSheet(self._readouts_card_default_style)

    # ------------------------------------------------------------------
    # Debounce wiring
    # ------------------------------------------------------------------

    def _wire_debounce_timers(self) -> None:
        self._p_debounce = QTimer(self)
        self._p_debounce.setSingleShot(True)
        self._p_debounce.setInterval(_DEBOUNCE_MS)
        self._p_debounce.timeout.connect(self._send_p_target)

        self._limits_debounce = QTimer(self)
        self._limits_debounce.setSingleShot(True)
        self._limits_debounce.setInterval(_DEBOUNCE_MS)
        self._limits_debounce.timeout.connect(self._send_limits)

        self._p_spin.valueChanged.connect(self._on_p_spin_changed)
        self._v_spin.valueChanged.connect(self._on_limit_spin_changed)
        self._i_spin.valueChanged.connect(self._on_limit_spin_changed)

    # ------------------------------------------------------------------
    # Primitives
    # ------------------------------------------------------------------

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(_label_font())
        label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
        return label

    @staticmethod
    def _spinbox(minimum: float, maximum: float, value: float, step: float, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setFixedWidth(96)
        # Phase III.D Item 3: arrows were bleeding into the preceding
        # label ("V⬍редел (В)"). Anchor the up/down buttons to the
        # right edge of the input rectangle and reserve horizontal
        # padding inside so the numeric value never collides with them.
        spin.setStyleSheet(
            "QDoubleSpinBox { padding-right: 22px; padding-left: 4px; }"
            " QDoubleSpinBox::up-button {"
            " subcontrol-position: right top; width: 18px; }"
            " QDoubleSpinBox::down-button {"
            " subcontrol-position: right bottom; width: 18px; }"
        )
        return spin

    # ------------------------------------------------------------------
    # Click handlers
    # ------------------------------------------------------------------

    def _on_start_clicked(self) -> bool:
        p = float(self._p_spin.value())
        v = float(self._v_spin.value())
        i = float(self._i_spin.value())
        dispatched = self._dispatch_command(
            {
                "cmd": "keithley_start",
                "channel": self._key,
                "p_target": p,
                "v_comp": v,
                "i_comp": i,
            }
        )
        if dispatched:
            self.channel_start_requested.emit(self._key, p, v, i)
        return dispatched

    def _on_stop_clicked(self) -> bool:
        dispatched = self._dispatch_command({"cmd": "keithley_stop", "channel": self._key})
        if dispatched:
            self.channel_stop_requested.emit(self._key)
        return dispatched

    def _on_emergency_clicked(self) -> bool:
        reason = self.authorization_reason("keithley_emergency_off")
        if reason is not None:
            self.command_rejected.emit(self._key, "keithley_emergency_off", reason)
            return False
        answer = QMessageBox.warning(
            self,
            "Аварийное отключение",
            (
                f"Подтвердите аварийное отключение канала "
                f"{self._label_text}. Действие немедленно обрывает "
                f"подачу питания."
            ),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return False
        dispatched = self._dispatch_command({"cmd": "keithley_emergency_off", "channel": self._key})
        if dispatched:
            self.channel_emergency_requested.emit(self._key)
        return dispatched

    def _on_p_spin_changed(self, value: float) -> None:
        if self._read_only or self._channel_state != "on" or value <= 0:
            return
        self._p_debounce.start()

    def _on_limit_spin_changed(self, _value: float | None = None) -> None:
        if self._read_only or self._channel_state != "on":
            return
        self._limits_debounce.start()

    def _send_p_target(self) -> None:
        p = float(self._p_spin.value())
        if p <= 0:
            return
        dispatched = self._dispatch_command(
            {
                "cmd": "keithley_set_target",
                "channel": self._key,
                "p_target": p,
            }
        )
        if dispatched:
            self.channel_target_updated.emit(self._key, p)

    def _send_limits(self) -> None:
        v = float(self._v_spin.value())
        i = float(self._i_spin.value())
        if v <= 0 or i <= 0:
            return
        dispatched = self._dispatch_command(
            {
                "cmd": "keithley_set_limits",
                "channel": self._key,
                "v_comp": v,
                "i_comp": i,
            }
        )
        if dispatched:
            self.channel_limits_updated.emit(self._key, v, i)

    def _dispatch_command(self, cmd: dict) -> bool:
        """Dispatch without blocking while preserving visible command outcome."""

        command_name = str(cmd.get("cmd", "unknown"))
        reason = self.authorization_reason(command_name)
        if reason is not None:
            logger.warning(
                "Keithley command rejected on %s: %s (%s)",
                self._key,
                command_name,
                reason,
            )
            self.command_rejected.emit(self._key, command_name, reason)
            return False

        self._command_sequence += 1
        token = self._command_sequence
        expected_generation = self._connection_generation
        if command_name != "keithley_emergency_off":
            self._normal_pending_token = token
        worker = ZmqCommandWorker(cmd, parent=self)

        def _completed(
            result: dict,
            command_token: int = token,
            command: dict = dict(cmd),
            generation: int = expected_generation,
            completed_worker: ZmqCommandWorker = worker,
        ) -> None:
            self._on_command_result(command_token, command, result, generation, completed_worker)

        worker.finished.connect(_completed)
        self._workers.append(worker)
        self._update_control_enablement()
        self.command_started.emit(self._key, token, command_name)
        worker.start()
        return True

    def _on_command_result(
        self,
        token: int,
        command: dict,
        result: dict,
        expected_generation: int | None = None,
        worker: ZmqCommandWorker | None = None,
    ) -> None:
        if token in self._settled_command_tokens:
            logger.warning(
                "ignored duplicate Keithley reply on %s for token %s",
                self._key,
                token,
            )
            return
        self._settled_command_tokens.add(token)
        if worker is not None:
            self._workers = [candidate for candidate in self._workers if candidate is not worker]
        if token == self._normal_pending_token:
            self._normal_pending_token = None
        command_name = str(command.get("cmd", "unknown"))
        if expected_generation is not None and expected_generation != self._connection_generation:
            error = "ответ относится к предыдущему состоянию подключения"
            self._latch_unknown_outcome()
            logger.warning(
                "ignored stale Keithley reply on %s: %s",
                self._key,
                command_name,
            )
            self.command_finished.emit(self._key, token, command_name, "unknown", error)
            return

        error = str(result.get("error") or "") if isinstance(result, dict) else "некорректный ответ Engine"
        if isinstance(result, dict) and result.get("ok") is True:
            outcome = "ok"
        elif self._result_outcome_unknown(result):
            outcome = "unknown"
            self._latch_unknown_outcome()
        else:
            outcome = "failed"
        if outcome != "ok":
            logger.warning(
                "Keithley command %s on %s: %s",
                outcome,
                self._key,
                error,
            )
        self._update_control_enablement()
        self.command_finished.emit(
            self._key,
            token,
            command_name,
            outcome,
            error,
        )

    @staticmethod
    def _result_outcome_unknown(result: object) -> bool:
        if not isinstance(result, dict):
            return True
        if result.get("_handler_timeout") is True:
            return True
        error = str(result.get("error") or "").casefold()
        return any(
            marker in error
            for marker in (
                "timeout",
                "timed out",
                "тайм-аут",
                "не отвечает",
                "may still be running",
                "исход неизвестен",
            )
        )

    # ------------------------------------------------------------------
    # Public state pushers
    # ------------------------------------------------------------------

    def apply_state(self, state: str) -> None:
        normalized = state.strip().lower() if state else "unknown"
        if normalized not in _STATE_LABELS:
            normalized = "unknown"
        self._source_observation_revision += 1
        # A queued reading received after the host declared disconnect cannot
        # re-establish current truth. Keep it out of both current and confirmed
        # state until a live connection exists again.
        if self._connected:
            self._channel_state = normalized
            if normalized in {"off", "on", "fault"}:
                self._last_confirmed_state = normalized
        else:
            self._channel_state = "unknown"
        self._apply_state_visuals()
        self._update_control_enablement()
        self._maybe_reconcile_unknown_outcome()
        # When not "on", clear stale styling — channel isn't expected to
        # publish live measurements.
        if self._channel_state != "on" and self._stale:
            self._stale = False
            self._apply_readouts_style()
            self._strip_stale_suffix()

    def set_connected(self, connected: bool) -> None:
        if connected == self._connected:
            return
        self._connected = connected
        self._connection_generation += 1
        if not connected:
            self._p_debounce.stop()
            self._limits_debounce.stop()
            self._channel_state = "unknown"
            if self._normal_pending_token is not None:
                self._latch_unknown_outcome()
                self._normal_pending_token = None
            self._apply_state_visuals()
        self._update_control_enablement()

    def set_safety_ready(self, ready: bool) -> None:
        self._safety_observation_revision += 1
        self._safety_ready = bool(ready)
        self._update_control_enablement()
        self._maybe_reconcile_unknown_outcome()

    def set_read_only(self, read_only: bool) -> None:
        read_only = bool(read_only)
        if read_only != self._read_only:
            self._connection_generation += 1
            if read_only and self._normal_pending_token is not None:
                self._latch_unknown_outcome()
                self._normal_pending_token = None
        self._read_only = read_only
        self._update_control_enablement()

    def set_window(self, seconds: float) -> None:
        self._window_s = max(1.0, float(seconds))

    def _update_control_enablement(self) -> None:
        interactive_ok = (
            self._connected
            and self._safety_ready
            and not self._read_only
            and self._unknown_outcome_requires is None
            and self._normal_pending_token is None
        )
        self._p_spin.setEnabled(interactive_ok)
        self._v_spin.setEnabled(interactive_ok)
        self._i_spin.setEnabled(interactive_ok)
        # Only authoritative OFF permits Start. Unknown/fault remain fail-closed.
        start_enabled = interactive_ok and self._channel_state == "off"
        stop_enabled = interactive_ok and self._channel_state == "on"
        self._start_btn.setEnabled(start_enabled)
        self._stop_btn.setEnabled(stop_enabled)
        # Emergency stays reachable whenever we have a live link, even if
        # safety preconditions block normal control. It's the escape hatch.
        self._emergency_btn.setEnabled(self._connected and not self._read_only)

    def _latch_unknown_outcome(self) -> None:
        self._unknown_outcome_requires = (
            self._source_observation_revision + 1,
            self._safety_observation_revision + 1,
        )
        self._update_control_enablement()

    def _maybe_reconcile_unknown_outcome(self) -> None:
        required = self._unknown_outcome_requires
        if required is None or not self._connected:
            return
        source_required, safety_required = required
        if self._source_observation_revision < source_required or self._safety_observation_revision < safety_required:
            return
        self._unknown_outcome_requires = None
        self._update_control_enablement()
        self.outcome_reconciled.emit(self._key)

    def authorization_reason(self, command_name: str) -> str | None:
        if self._read_only:
            return "архивный повтор не имеет полномочий управления"
        if not self._connected:
            return "нет живой связи с Engine"
        if command_name == "keithley_emergency_off":
            return None
        if self._unknown_outcome_requires is not None:
            return "предыдущая команда имеет неизвестный исход; нужна свежая сверка state и Safety"
        if self._normal_pending_token is not None:
            return "для канала уже выполняется команда"
        if not self._safety_ready:
            return "нет свежего разрешения Safety"
        required_state = "off" if command_name == "keithley_start" else "on"
        if command_name not in {
            "keithley_start",
            "keithley_stop",
            "keithley_set_target",
            "keithley_set_limits",
        }:
            return "команда не входит в разрешённый набор панели"
        if self._channel_state != required_state:
            return (
                f"требуется подтверждённое состояние {_STATE_LABELS[required_state]}, "
                f"текущее состояние {_STATE_LABELS.get(self._channel_state, _STATE_LABELS['unknown'])}"
            )
        return None

    # ------------------------------------------------------------------
    # Readings + refresh
    # ------------------------------------------------------------------

    def handle_reading(self, suffix: str, reading: Reading) -> None:
        if suffix not in self._buffers:
            return
        ts = reading.timestamp.timestamp()
        self._buffers[suffix].append((ts, reading.value))
        self._last_update_ts = ts
        formatter = _FORMATTERS[suffix]
        # Phase III.D Item 1: resistance is meaningless at |I| ≈ 0
        # (engine sometimes carries the last-valid R forward; operator
        # sees a stale 2.32 Ω on a zero-current channel). Collapse it
        # to "—" at display time regardless of the engine's numeric
        # value. Power gets the same treatment — P = V·I is exactly
        # zero at zero current, but a stale cached value would mislead.
        if suffix in ("resistance", "power") and self._current_is_effectively_zero():
            self._value_labels[suffix].setText(_DASH_BY_UNIT[suffix])
        else:
            self._value_labels[suffix].setText(formatter(reading.value))
        if self._stale:
            self._stale = False
            self._apply_readouts_style()

    def _current_is_effectively_zero(self) -> bool:
        """Return True if the most recent current reading is <1 nA.

        1 nA is several decades below any realistic SMU operating
        current; anything under that is either zero or noise floor."""
        buf = self._buffers.get("current")
        if not buf:
            return False
        _ts, last_i = buf[-1]
        try:
            return abs(float(last_i)) < 1e-9
        except (TypeError, ValueError):
            return False

    def refresh(self, now: float) -> None:
        self._refresh_plots(now)
        self._refresh_stale(now)

    def _refresh_plots(self, now: float) -> None:
        x_min = now - self._window_s
        visible: list[tuple[str, list[float], list[float]]] = []
        earliest = now
        for key in _MEASUREMENTS:
            buffer = self._buffers[key]
            xs: list[float] = []
            ys: list[float] = []
            for ts, value in buffer:
                if ts < x_min:
                    continue
                xs.append(ts - now)
                ys.append(value)
            visible.append((key, xs, ys))
            if xs:
                earliest = min(earliest, now + xs[0])

        left = max(-self._window_s, earliest - now)
        for key, xs, ys in visible:
            self._plots[key].setData(xs, ys)
            plot_item = self._plot_widgets[key].getPlotItem()
            plot_item.setXRange(left, 0, padding=0)

    def _refresh_stale(self, now: float) -> None:
        should_be_stale = self._channel_state == "on" and is_stale(self._last_update_ts, _STALE_AFTER_S, now=now)
        if should_be_stale == self._stale:
            return
        self._stale = should_be_stale
        self._apply_readouts_style()
        if self._stale:
            self._apply_stale_suffix()
        else:
            self._strip_stale_suffix()

    def _apply_stale_suffix(self) -> None:
        for key, label in self._value_labels.items():
            text = label.text()
            if "(устар.)" in text:
                continue
            label.setText(f"{text} (устар.)")

    def _strip_stale_suffix(self) -> None:
        for label in self._value_labels.values():
            text = label.text().replace(" (устар.)", "").replace("(устар.)", "")
            label.setText(text)


class KeithleyPanel(QWidget):
    """Dual-channel Keithley operator overlay."""

    channel_start_requested = Signal(str, float, float, float)
    channel_stop_requested = Signal(str)
    channel_emergency_requested = Signal(str)
    channel_target_updated = Signal(str, float)
    channel_limits_updated = Signal(str, float, float)
    both_channels_start_requested = Signal()
    both_channels_stop_requested = Signal()
    both_channels_emergency_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connected: bool = False
        self._safety_ready: bool = False
        self._read_only: bool = False
        self._pending_commands: dict[tuple[str, int], str] = {}
        self._unresolved_outcomes: dict[str, str] = {}
        self._command_error_latched = False
        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.setInterval(_BANNER_AUTO_CLEAR_MS)
        self._banner_timer.timeout.connect(self.clear_message)

        self.setObjectName("keithleyPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"#keithleyPanel {{ background-color: {theme.BACKGROUND}; }}")

        self._smua_block = _SmuChannelBlock("smua", "Канал А", palette_index=0)
        self._smub_block = _SmuChannelBlock("smub", "Канал B", palette_index=1)
        self._blocks: dict[str, _SmuChannelBlock] = {
            "smua": self._smua_block,
            "smub": self._smub_block,
        }

        self._build_ui()
        self._wire_block_signals()
        # IV.2 A.3: Keithley panel uses the shared global time-window
        # controller instead of a private per-panel toolbar. Seed each
        # channel block with the current global window and subscribe
        # to future changes so operators don't re-set the window
        # separately per view.
        controller = get_time_window_controller()
        self._apply_global_window(controller.get_window())
        controller.window_changed.connect(self._apply_global_window)
        self.set_connected(False)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(_REFRESH_MS)
        self._refresh_timer.timeout.connect(self._on_refresh_tick)
        self._refresh_timer.start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        root.setSpacing(theme.SPACE_3)

        root.addWidget(self._build_header())
        root.addWidget(self._build_banner())
        root.addWidget(self._build_gate_label())
        root.addWidget(self._build_window_toolbar())

        channels = QHBoxLayout()
        channels.setContentsMargins(0, 0, 0, 0)
        channels.setSpacing(theme.SPACE_3)
        channels.addWidget(self._smua_block, stretch=1)
        channels.addWidget(self._smub_block, stretch=1)
        root.addLayout(channels, stretch=1)

        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        header = QWidget()
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        title = QLabel("KEITHLEY 2604B")
        title_font = _title_font()
        title_font.setPixelSize(theme.FONT_SIZE_XL)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {theme.FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(title)
        layout.addStretch()

        self._connection_label = QLabel("● Нет связи")
        conn_font = _label_font()
        conn_font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
        self._connection_label.setFont(conn_font)
        self._connection_label.setStyleSheet(f"color: {theme.STATUS_FAULT}; background: transparent; border: none;")
        layout.addWidget(self._connection_label)
        return header

    def _build_banner(self) -> QWidget:
        self._banner_label = QLabel("")
        self._banner_label.setFont(_label_font())
        self._banner_label.setVisible(False)
        self._banner_label.setObjectName("keithleyBanner")
        self._banner_label.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._banner_label.setContentsMargins(theme.SPACE_3, theme.SPACE_1, theme.SPACE_3, theme.SPACE_1)
        return self._banner_label

    def _build_gate_label(self) -> QWidget:
        self._gate_reason_label = QLabel("")
        self._gate_reason_label.setFont(_label_font())
        self._gate_reason_label.setVisible(False)
        self._gate_reason_label.setStyleSheet(
            f"color: {theme.STATUS_WARNING};"
            f" background: transparent; border: none;"
            f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
        )
        return self._gate_reason_label

    def _build_window_toolbar(self) -> QWidget:
        # IV.2 A.3: delegate to the shared TimeWindowSelector so the
        # global controller drives this panel's X range — same
        # selector used by dashboard and analytics. "10м" is NOT in
        # the global TimeWindow enum (it was a Keithley-local
        # expedient); drop it and use the canonical 1мин/1ч/6ч/24ч/Всё
        # via show_6h=True.
        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_1)

        caption = QLabel("Окно:")
        caption.setFont(_label_font())
        caption.setStyleSheet(f"color: {theme.MUTED_FOREGROUND}; background: transparent; border: none;")
        layout.addWidget(caption)

        self._time_selector = TimeWindowSelector(show_6h=True, parent=self)
        layout.addWidget(self._time_selector)
        layout.addStretch()
        return toolbar

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)

        layout.addStretch()

        self._start_both_btn = QPushButton("Старт A+B")
        # Phase III.D Item 10: outlined caution — distinct from
        # per-channel filled Старт buttons.
        _style_button(self._start_both_btn, "caution_outlined")
        self._start_both_btn.clicked.connect(self._on_start_both)
        layout.addWidget(self._start_both_btn)

        self._stop_both_btn = QPushButton("Стоп A+B")
        _style_button(self._stop_both_btn, "warning")
        self._stop_both_btn.clicked.connect(self._on_stop_both)
        layout.addWidget(self._stop_both_btn)

        self._emergency_both_btn = QPushButton("АВАР. ОТКЛ. A+B")
        _style_button(self._emergency_both_btn, "destructive")
        self._emergency_both_btn.clicked.connect(self._on_emergency_both)
        layout.addWidget(self._emergency_both_btn)
        return footer

    # ------------------------------------------------------------------
    # Signal relays from channel blocks
    # ------------------------------------------------------------------

    def _wire_block_signals(self) -> None:
        for block in self._blocks.values():
            block.channel_start_requested.connect(self.channel_start_requested)
            block.channel_stop_requested.connect(self.channel_stop_requested)
            block.channel_emergency_requested.connect(self.channel_emergency_requested)
            block.channel_target_updated.connect(self.channel_target_updated)
            block.channel_limits_updated.connect(self.channel_limits_updated)
            block.command_started.connect(self._on_block_command_started)
            block.command_finished.connect(self._on_block_command_finished)
            block.command_rejected.connect(self._on_block_command_rejected)
            block.outcome_reconciled.connect(self._on_block_outcome_reconciled)

    @staticmethod
    def _command_description(channel: str, command: str) -> str:
        channel_label = "канала А" if channel == "smua" else "канала B"
        action = {
            "keithley_start": "Запуск",
            "keithley_stop": "Остановка",
            "keithley_emergency_off": "Аварийное отключение",
            "keithley_set_target": "Изменение мощности",
            "keithley_set_limits": "Изменение пределов",
        }.get(command, "Команда")
        return f"{action} {channel_label}"

    def _on_block_command_started(self, channel: str, token: int, command: str) -> None:
        if not self._pending_commands and not self._unresolved_outcomes:
            # A deliberate retry/new action acknowledges the prior command error;
            # the new pending state remains visible until Engine answers.
            self._command_error_latched = False
        self._pending_commands[(channel, token)] = command
        description = self._command_description(channel, command)
        self._set_banner(
            f"{description}: команда отправлена, ожидается ответ Engine.",
            theme.STATUS_INFO,
            auto_clear=False,
        )
        self._update_both_buttons_enablement()

    def _on_block_command_finished(
        self,
        channel: str,
        token: int,
        command: str,
        outcome: str,
        error: str,
    ) -> None:
        self._pending_commands.pop((channel, token), None)
        description = self._command_description(channel, command)
        if outcome == "unknown":
            self._unresolved_outcomes[channel] = description
            self._command_error_latched = True
            cause = error.strip() or "Engine не подтвердил выполнение"
            self._set_banner(
                f"{description}: ИСХОД НЕИЗВЕСТЕН — {cause}. Не повторяйте команду "
                "вслепую; обычное управление заблокировано до свежей сверки "
                "состояния источника и Safety. Аварийное отключение остаётся доступно "
                "при живой связи.",
                theme.STATUS_CAUTION,
                auto_clear=False,
            )
            self._update_both_buttons_enablement()
            return
        if outcome != "ok":
            self._command_error_latched = True
            cause = error.strip() or "Engine отклонил команду"
            self.show_error(f"{description} отклонена: {cause}.")
            self._update_both_buttons_enablement()
            return
        if self._command_error_latched or self._unresolved_outcomes:
            self._update_both_buttons_enablement()
            return
        if self._pending_commands:
            self._set_banner(
                f"Engine подтвердил часть команд; ожидается ответ: {len(self._pending_commands)}.",
                theme.STATUS_INFO,
                auto_clear=False,
            )
            self._update_both_buttons_enablement()
            return
        self.show_info(f"{description}: Engine подтвердил выполнение.")
        self._update_both_buttons_enablement()

    def _on_block_command_rejected(self, channel: str, command: str, reason: str) -> None:
        description = self._command_description(channel, command)
        self._set_banner(
            f"{description} не отправлена: {reason}.",
            theme.STATUS_CAUTION,
            auto_clear=False,
        )
        self._update_both_buttons_enablement()

    def _on_block_outcome_reconciled(self, channel: str) -> None:
        self._unresolved_outcomes.pop(channel, None)
        if self._unresolved_outcomes:
            return
        self._command_error_latched = False
        self.show_info("Свежие состояния источника и Safety получены; неизвестный исход сверён.")
        self._update_both_buttons_enablement()

    # ------------------------------------------------------------------
    # A+B handlers
    # ------------------------------------------------------------------

    def _on_start_both(self) -> None:
        if any(block.authorization_reason("keithley_start") is not None for block in self._blocks.values()):
            self.show_warning(
                "Старт A+B не отправлен: оба канала должны иметь подтверждённое "
                "состояние ВЫКЛ, свежий Safety и не иметь команды в полёте."
            )
            return
        dispatched = [block._on_start_clicked() for block in self._blocks.values()]
        if all(dispatched):
            self.both_channels_start_requested.emit()

    def _on_stop_both(self) -> None:
        if any(block.authorization_reason("keithley_stop") is not None for block in self._blocks.values()):
            self.show_warning(
                "Стоп A+B не отправлен: оба канала должны иметь подтверждённое "
                "состояние ВКЛ, свежий Safety и не иметь команды в полёте."
            )
            return
        dispatched = [block._on_stop_clicked() for block in self._blocks.values()]
        if all(dispatched):
            self.both_channels_stop_requested.emit()

    def _on_emergency_both(self) -> None:
        if any(block.authorization_reason("keithley_emergency_off") is not None for block in self._blocks.values()):
            self.show_warning("Аварийное отключение A+B не отправлено: нет живой связи с Engine.")
            return
        answer = QMessageBox.warning(
            self,
            "Аварийное отключение A+B",
            (
                "Подтвердите аварийное отключение обоих каналов. "
                "Действие немедленно обрывает подачу питания на smua и smub."
            ),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Ok:
            return
        if any(block.authorization_reason("keithley_emergency_off") is not None for block in self._blocks.values()):
            self.show_warning("Связь изменилась во время подтверждения; команда A+B не отправлена.")
            return
        dispatched: list[bool] = []
        for block in self._blocks.values():
            # Sub-blocks dispatch the actual command; they skip their own
            # confirmation because the panel-level dialog already
            # confirmed both channels.
            sent = block._dispatch_command({"cmd": "keithley_emergency_off", "channel": block._key})
            dispatched.append(sent)
            if sent:
                block.channel_emergency_requested.emit(block._key)
        if all(dispatched):
            self.both_channels_emergency_requested.emit()

    # ------------------------------------------------------------------
    # Window toolbar
    # ------------------------------------------------------------------

    def _apply_global_window(self, window: TimeWindow) -> None:
        # IV.2 A.3: receive the global window and forward to every
        # channel block. TimeWindow.ALL maps to the full buffer
        # (_BUFFER_MAXLEN seconds — effectively the whole session).
        # The shared selector UI itself is already synced via the
        # controller's broadcast; we only need to push the seconds
        # into the per-block refresh math.
        if window is TimeWindow.ALL:
            seconds = float(_BUFFER_MAXLEN)
        else:
            seconds = window.seconds
        for block in self._blocks.values():
            block.set_window(seconds)

    # ------------------------------------------------------------------
    # Public state pushers
    # ------------------------------------------------------------------

    def on_reading(self, reading: Reading) -> None:
        channel = reading.channel
        if channel.startswith("analytics/keithley_channel_state/"):
            key = channel.rsplit("/", 1)[-1]
            block = self._blocks.get(key)
            if block is not None:
                state = str(reading.metadata.get("state", "unknown"))
                block.apply_state(state)
                self._update_both_buttons_enablement()
            return

        for key, block in self._blocks.items():
            if f"/{key}/" not in channel:
                continue
            for suffix in _MEASUREMENTS:
                if channel.endswith(f"/{suffix}"):
                    block.handle_reading(suffix, reading)
                    return

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        if connected:
            self._connection_label.setText("● Подключён")
            self._connection_label.setStyleSheet(
                f"color: {theme.STATUS_OK};"
                f" background: transparent; border: none;"
                f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
            )
        else:
            self._connection_label.setText("● Нет связи")
            self._connection_label.setStyleSheet(
                f"color: {theme.STATUS_FAULT};"
                f" background: transparent; border: none;"
                f" font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
            )
        for block in self._blocks.values():
            block.set_connected(connected)
        self._update_both_buttons_enablement()

    def set_safety_ready(self, ready: bool, reason: str = "") -> None:
        self._safety_ready = ready
        for block in self._blocks.values():
            block.set_safety_ready(ready)
        if self._read_only:
            self._gate_reason_label.setText("Архивный повтор: управление источником недоступно")
            self._gate_reason_label.setVisible(True)
        elif not ready:
            text = "Управление заблокировано"
            if reason:
                text = f"{text}: {reason}"
            self._gate_reason_label.setText(text)
            self._gate_reason_label.setVisible(True)
        else:
            self._gate_reason_label.setVisible(False)
            self._gate_reason_label.setText("")
        self._update_both_buttons_enablement()

    def set_read_only(self, read_only: bool) -> None:
        """Keep replay/source inspection available while removing command authority."""

        self._read_only = bool(read_only)
        for block in self._blocks.values():
            block.set_read_only(self._read_only)
        if self._read_only:
            self._gate_reason_label.setText("Архивный повтор: управление источником недоступно")
            self._gate_reason_label.setVisible(True)
        elif not self._safety_ready:
            self._gate_reason_label.setText("Управление заблокировано: нет авторитетных данных Safety")
            self._gate_reason_label.setVisible(True)
        self._update_both_buttons_enablement()

    def _update_both_buttons_enablement(self) -> None:
        self._start_both_btn.setEnabled(
            all(block.authorization_reason("keithley_start") is None for block in self._blocks.values())
        )
        self._stop_both_btn.setEnabled(
            all(block.authorization_reason("keithley_stop") is None for block in self._blocks.values())
        )
        self._emergency_both_btn.setEnabled(self._connected and not self._read_only)

    # ------------------------------------------------------------------
    # Status banner
    # ------------------------------------------------------------------

    def show_info(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_INFO)

    def show_warning(self, text: str) -> None:
        self._set_banner(text, theme.STATUS_CAUTION)

    def show_error(self, text: str) -> None:
        # Command failures remain visible until an explicit retry/new action or
        # clear; a four-second timeout would train operators to miss failures.
        self._set_banner(text, theme.STATUS_FAULT, auto_clear=False)

    def clear_message(self) -> None:
        self._banner_label.setVisible(False)
        self._banner_label.setText("")
        self._banner_timer.stop()

    def _set_banner(self, text: str, color: str, *, auto_clear: bool = True) -> None:
        self._banner_timer.stop()
        self._banner_label.setText(text)
        self._banner_label.setAccessibleName(text)
        self._banner_label.setStyleSheet(
            f"#keithleyBanner {{"
            f" color: {theme.FOREGROUND};"
            f" background-color: {theme.SURFACE_CARD};"
            f" border: 1px solid {color};"
            f" border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )
        self._banner_label.setVisible(True)
        if auto_clear:
            self._banner_timer.start()

    # ------------------------------------------------------------------
    # Refresh loop
    # ------------------------------------------------------------------

    def _on_refresh_tick(self) -> None:
        now = time.time()
        for block in self._blocks.values():
            block.refresh(now)
