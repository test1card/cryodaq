"""KeithleyPanel (v2) — dual-channel SMU control overlay.

Per `docs/design-system/cryodaq-primitives/keithley-panel.md` (B.7):

- Symmetric dual-channel layout: smua + smub shown side-by-side as
  «Канал А» / «Канал B» (Cyrillic А per RULE-COPY-002, invariant #11).
- Each channel: mode selector (Ток / Напряжение / Откл), setpoint
  input + «Применить», three live readouts (primary measured,
  secondary, power) in Fira Mono with tabular figures, output
  indicator + «Вкл / Выкл» toggle.
- Panel actions: АВАР. ОТКЛ. (Dialog confirmation; spec invariant #9
  calls for HoldConfirm hold — we ship Dialog today and track
  HoldConfirm as later work) + «Отключить Keithley» (Dialog confirm).
- Safety integration: controls disabled when the parent pushes
  `set_safety_ready(False)`; explanation label shows why.
- Connection integration: when `connected=False`, all controls
  disabled and status shows «Нет связи».

The widget is stateless beyond `set_state(KeithleyState)` / safety /
connection pushes from the parent. All user actions fire signals; the
parent shell routes them to the engine via ZMQ.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDoubleValidator, QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cryodaq.gui import theme


@dataclass
class SmuChannelState:
    """Live snapshot of one SMU channel."""

    key: str  # "smua" or "smub"
    label: str  # "Канал А" or "Канал B"
    output_enabled: bool
    mode: str  # "current" | "voltage" | "disabled"
    setpoint: float
    measured_primary: float  # A if current mode, V if voltage mode
    measured_secondary: float
    power_w: float
    faulted: bool = False


@dataclass
class KeithleyState:
    connected: bool
    smua: SmuChannelState
    smub: SmuChannelState


_MODE_ORDER = ("current", "voltage", "disabled")
_MODE_LABELS = {
    "current": "Ток",
    "voltage": "Напряжение",
    "disabled": "Откл",
}
_MODE_UNITS = {
    "current": "А",
    "voltage": "В",
    "disabled": "",
}
# Primary / secondary captions change meaning depending on mode.
_PRIMARY_CAPTIONS = {
    "current": "Измерено (ток):",
    "voltage": "Измерено (напр.):",
    "disabled": "Измерено:",
}
_SECONDARY_CAPTIONS = {
    "current": "Напряжение:",
    "voltage": "Ток:",
    "disabled": "—",
}
_PRIMARY_UNITS = {
    "current": "А",
    "voltage": "В",
    "disabled": "",
}
_SECONDARY_UNITS = {
    "current": "В",
    "voltage": "А",
    "disabled": "",
}


class _SmuChannelBlock(QFrame):
    """Single channel block (smua or smub). Composed inside KeithleyPanel."""

    setpoint_apply_requested = Signal(float)
    mode_change_requested = Signal(str)
    output_toggle_requested = Signal(bool)

    def __init__(
        self,
        channel_key: str,
        label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._channel_key = channel_key
        self._label_text = label
        self._current_mode = "disabled"
        self._output_on = False
        self._enabled = True
        self.setObjectName(f"smuBlock_{channel_key}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._build_ui()
        self._apply_chrome(faulted=False)

    def _build_ui(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(
            theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4
        )
        col.setSpacing(theme.SPACE_3)

        # Title
        title = QLabel(self._label_text, self)
        title_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        title_font.setWeight(QFont.Weight(theme.FONT_LABEL_WEIGHT))
        title.setFont(title_font)
        title.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        col.addWidget(title)

        # Mode row
        col.addWidget(self._build_mode_row())

        # Setpoint row
        col.addWidget(self._build_setpoint_row())

        # Measured readouts
        col.addWidget(self._build_measured_block())

        # Output toggle row
        col.addWidget(self._build_output_row())

    def _build_mode_row(self) -> QWidget:
        row = QWidget(self)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_2)

        caption = QLabel("Режим:", self)
        caption.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        caption.setFixedWidth(theme.SPACE_6 + theme.SPACE_5)
        lay.addWidget(caption)

        self._mode_group = QButtonGroup(self)
        self._mode_buttons: dict[str, QPushButton] = {}
        for mode in _MODE_ORDER:
            btn = QPushButton(_MODE_LABELS[mode], self)
            btn.setCheckable(True)
            btn.setObjectName(f"modeTab_{self._channel_key}_{mode}")
            btn.setStyleSheet(self._mode_tab_qss())
            btn.clicked.connect(
                lambda _checked=False, m=mode: self._on_mode_clicked(m)
            )
            self._mode_group.addButton(btn)
            self._mode_buttons[mode] = btn
            lay.addWidget(btn)
        lay.addStretch(1)
        return row

    def _build_setpoint_row(self) -> QWidget:
        row = QWidget(self)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_2)

        caption = QLabel("Установка:", self)
        caption.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        caption.setFixedWidth(theme.SPACE_6 + theme.SPACE_5)
        lay.addWidget(caption)

        self._setpoint_input = QLineEdit(self)
        self._setpoint_input.setPlaceholderText("0.000")
        self._setpoint_input.setObjectName(f"setpoint_{self._channel_key}")
        self._setpoint_input.setValidator(QDoubleValidator(0.0, 1000.0, 3))
        sp_font = QFont(theme.FONT_MONO, theme.FONT_LABEL_SIZE)
        self._setpoint_input.setFont(sp_font)
        self._setpoint_input.setStyleSheet(
            f"QLineEdit {{"
            f"background: {theme.SURFACE_CARD};"
            f"color: {theme.FOREGROUND};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_SM}px;"
            f"padding: {theme.SPACE_1}px {theme.SPACE_2}px;"
            f"}}"
        )
        lay.addWidget(self._setpoint_input, 1)

        self._setpoint_unit = QLabel("А", self)
        self._setpoint_unit.setStyleSheet(
            f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
        )
        self._setpoint_unit.setFixedWidth(24)
        lay.addWidget(self._setpoint_unit)

        self._apply_btn = QPushButton("Применить", self)
        self._apply_btn.setObjectName(f"apply_{self._channel_key}")
        self._apply_btn.setStyleSheet(self._ghost_button_qss())
        self._apply_btn.clicked.connect(self._on_apply_clicked)
        lay.addWidget(self._apply_btn)
        return row

    def _build_measured_block(self) -> QWidget:
        block = QFrame(self)
        block.setObjectName(f"measured_{self._channel_key}")
        block.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        block.setStyleSheet(
            f"#measured_{self._channel_key} {{"
            f"background: {theme.SURFACE_CARD};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_SM}px;"
            f"}}"
        )
        lay = QVBoxLayout(block)
        lay.setContentsMargins(
            theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2
        )
        lay.setSpacing(theme.SPACE_1)

        val_font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
        val_font.setWeight(QFont.Weight(theme.FONT_MONO_VALUE_WEIGHT))
        try:
            val_font.setFeature(QFont.Tag("tnum"), 1)
        except (AttributeError, TypeError, ValueError):
            pass

        def _line(caption_text: str) -> tuple[QLabel, QLabel]:
            line = QWidget(block)
            h = QHBoxLayout(line)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(theme.SPACE_3)
            cap = QLabel(caption_text, line)
            cap.setStyleSheet(
                f"color: {theme.MUTED_FOREGROUND}; background: transparent;"
            )
            h.addWidget(cap, 1)
            val = QLabel("—", line)
            val.setFont(val_font)
            val.setStyleSheet(
                f"color: {theme.FOREGROUND}; background: transparent;"
            )
            val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            h.addWidget(val, 0)
            lay.addWidget(line)
            return cap, val

        self._primary_caption, self._primary_value = _line("Измерено:")
        self._secondary_caption, self._secondary_value = _line("—")
        self._power_caption, self._power_value = _line("Мощность:")

        return block

    def _build_output_row(self) -> QWidget:
        row = QWidget(self)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_3)

        # RULE-A11Y-002: dot + text, not color alone.
        self._output_dot = QLabel("●", self)
        self._output_text = QLabel("Выход: откл", self)
        self._set_output_indicator(on=False)
        lay.addWidget(self._output_dot)
        lay.addWidget(self._output_text)
        lay.addStretch(1)

        self._output_toggle = QPushButton("Вкл выход", self)
        self._output_toggle.setObjectName(f"outputToggle_{self._channel_key}")
        self._output_toggle.setStyleSheet(self._ghost_button_qss())
        self._output_toggle.clicked.connect(self._on_output_toggle_clicked)
        lay.addWidget(self._output_toggle)
        return row

    # ------------------------------------------------------------------
    # External setters (called by KeithleyPanel)
    # ------------------------------------------------------------------

    def apply_state(self, state: SmuChannelState) -> None:
        self._current_mode = state.mode
        self._output_on = state.output_enabled

        # Mode buttons
        for mode, btn in self._mode_buttons.items():
            btn.setChecked(mode == state.mode)

        # Setpoint: only update text if user isn't mid-edit (not focused)
        if not self._setpoint_input.hasFocus():
            self._setpoint_input.setText(f"{state.setpoint:.3f}")
        self._setpoint_unit.setText(_MODE_UNITS.get(state.mode, ""))

        # Measured readouts
        self._primary_caption.setText(_PRIMARY_CAPTIONS[state.mode])
        self._secondary_caption.setText(_SECONDARY_CAPTIONS[state.mode])
        self._primary_value.setText(
            self._format_measured(state.measured_primary, _PRIMARY_UNITS[state.mode])
        )
        self._secondary_value.setText(
            self._format_measured(state.measured_secondary, _SECONDARY_UNITS[state.mode])
        )
        self._power_value.setText(self._format_measured(state.power_w, "Вт"))

        # Output indicator + toggle label
        self._set_output_indicator(on=state.output_enabled)
        self._output_toggle.setText("Выкл выход" if state.output_enabled else "Вкл выход")

        # Fault chrome
        self._apply_chrome(faulted=state.faulted)

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable all interactive controls (safety / connection gate)."""
        self._enabled = enabled
        for btn in self._mode_buttons.values():
            btn.setEnabled(enabled)
        self._setpoint_input.setEnabled(enabled)
        self._apply_btn.setEnabled(enabled)
        self._output_toggle.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _on_mode_clicked(self, mode: str) -> None:
        if mode == self._current_mode:
            return
        self.mode_change_requested.emit(mode)

    def _on_apply_clicked(self) -> None:
        raw = self._setpoint_input.text().strip().replace(",", ".")
        try:
            value = float(raw)
        except ValueError:
            return  # validator should have blocked non-numeric already
        self.setpoint_apply_requested.emit(value)

    def _on_output_toggle_clicked(self) -> None:
        target = not self._output_on
        if target:
            # RULE-INTER-004: enabling output is destructive-level — confirm.
            reply = QMessageBox.question(
                self.window() or self,
                "Включить выход?",
                (
                    f"Будет включён выход {self._label_text}. "
                    "Убедись, что установка и режим корректны."
                ),
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Ok:
                return
        # Disable path runs without confirmation (safe direction).
        self.output_toggle_requested.emit(target)

    def _apply_chrome(self, *, faulted: bool) -> None:
        base = (
            f"#smuBlock_{self._channel_key} {{"
            f"background: {theme.SURFACE_ELEVATED};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_LG}px;"
        )
        if faulted:
            base += f"border-left: 3px solid {theme.STATUS_FAULT};"
        base += "}"
        self.setStyleSheet(base)

    def _set_output_indicator(self, *, on: bool) -> None:
        color = theme.STATUS_OK if on else theme.STATUS_STALE
        self._output_dot.setStyleSheet(
            f"color: {color}; background: transparent; font-size: 14px;"
        )
        self._output_text.setText("Выход: вкл" if on else "Выход: откл")
        self._output_text.setStyleSheet(
            f"color: {color if on else theme.MUTED_FOREGROUND}; background: transparent;"
        )

    @staticmethod
    def _format_measured(value: float, unit: str) -> str:
        if unit == "":
            return "—"
        if abs(value) < 1e-3 and value != 0:
            return f"{value * 1000:.3f} м{unit}"
        return f"{value:.3f} {unit}"

    def _mode_tab_qss(self) -> str:
        return (
            "QPushButton {"
            f"background: transparent;"
            f"color: {theme.MUTED_FOREGROUND};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_SM}px;"
            f"padding: {theme.SPACE_1}px {theme.SPACE_3}px;"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_LABEL_SIZE}px;"
            "}"
            "QPushButton:checked {"
            f"background: {theme.ACCENT};"
            f"color: {theme.ON_PRIMARY};"
            f"border-color: {theme.ACCENT};"
            "}"
            "QPushButton:hover:!checked {"
            f"background: {theme.MUTED};"
            f"color: {theme.FOREGROUND};"
            "}"
        )

    @staticmethod
    def _ghost_button_qss() -> str:
        return (
            "QPushButton {"
            f"background: transparent;"
            f"color: {theme.FOREGROUND};"
            f"border: 1px solid {theme.BORDER};"
            f"border-radius: {theme.RADIUS_SM}px;"
            f"padding: {theme.SPACE_1}px {theme.SPACE_3}px;"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_LABEL_SIZE}px;"
            "}"
            "QPushButton:hover {"
            f"background: {theme.MUTED};"
            "}"
            "QPushButton:disabled {"
            f"color: {theme.MUTED_FOREGROUND};"
            f"border-color: {theme.BORDER_SUBTLE};"
            "}"
        )


class KeithleyPanel(QWidget):
    """Full dual-channel Keithley 2604B overlay panel (v2)."""

    # Per-channel user actions
    setpoint_apply_requested = Signal(str, float)  # (channel_key, value)
    mode_change_requested = Signal(str, str)  # (channel_key, mode)
    output_toggle_requested = Signal(str, bool)  # (channel_key, enable)

    # Panel-level
    emergency_off_requested = Signal()
    disconnect_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("keithleyPanel")
        self._connected = True
        self._safety_ready = True
        self._safety_reason = ""
        self._build_ui()
        self._refresh_gate()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(
            theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5
        )
        root.setSpacing(theme.SPACE_4)

        # Header
        header = QWidget(self)
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(theme.SPACE_4)

        title = QLabel("KEITHLEY 2604B", self)
        title_font = QFont(theme.FONT_BODY, theme.FONT_SIZE_LG)
        title_font.setWeight(QFont.Weight(theme.FONT_WEIGHT_SEMIBOLD))
        title.setFont(title_font)
        title.setStyleSheet(
            f"color: {theme.FOREGROUND}; background: transparent;"
        )
        hlay.addWidget(title)

        self._connection_label = QLabel("● Подключён", self)
        self._connection_label.setStyleSheet(
            f"color: {theme.STATUS_OK}; background: transparent;"
        )
        hlay.addStretch(1)
        hlay.addWidget(self._connection_label)
        root.addWidget(header)

        # Two channel blocks side-by-side
        channels_row = QWidget(self)
        chlay = QHBoxLayout(channels_row)
        chlay.setContentsMargins(0, 0, 0, 0)
        chlay.setSpacing(theme.SPACE_4)

        self._smua_block = _SmuChannelBlock("smua", "Канал А", self)
        self._smub_block = _SmuChannelBlock("smub", "Канал B", self)

        for block, key in ((self._smua_block, "smua"), (self._smub_block, "smub")):
            block.setpoint_apply_requested.connect(
                lambda v, k=key: self.setpoint_apply_requested.emit(k, v)
            )
            block.mode_change_requested.connect(
                lambda m, k=key: self.mode_change_requested.emit(k, m)
            )
            block.output_toggle_requested.connect(
                lambda on, k=key: self.output_toggle_requested.emit(k, on)
            )
            chlay.addWidget(block, 1)
        root.addWidget(channels_row, 1)

        # Safety / connection reason (shown when controls are gated)
        self._gate_reason_label = QLabel("", self)
        self._gate_reason_label.setObjectName("keithleyGateReason")
        self._gate_reason_label.setStyleSheet(
            f"color: {theme.STATUS_WARNING}; background: transparent;"
        )
        self._gate_reason_label.setVisible(False)
        root.addWidget(self._gate_reason_label)

        # Panel-level action row
        actions = QWidget(self)
        alay = QHBoxLayout(actions)
        alay.setContentsMargins(0, 0, 0, 0)
        alay.setSpacing(theme.SPACE_3)

        self._emergency_btn = QPushButton("АВАР. ОТКЛ.", self)
        self._emergency_btn.setObjectName("keithleyEmergencyBtn")
        self._emergency_btn.setStyleSheet(
            "QPushButton {"
            f"background: {theme.STATUS_FAULT};"
            f"color: {theme.ON_DESTRUCTIVE};"
            f"border: none;"
            f"border-radius: {theme.RADIUS_SM}px;"
            f"padding: {theme.SPACE_2}px {theme.SPACE_4}px;"
            f"font-family: '{theme.FONT_BODY}';"
            f"font-size: {theme.FONT_LABEL_SIZE}px;"
            f"font-weight: {theme.FONT_WEIGHT_SEMIBOLD};"
            "}"
            "QPushButton:hover {"
            # DESTRUCTIVE_PRESSED token is a proposed followup (see
            # MANIFEST #200 DESTRUCTIVE_PRESSED). Until it lands, use
            # the STATUS_FAULT base colour for the hover state.
            f"background: {theme.STATUS_FAULT};"
            "}"
        )
        self._emergency_btn.clicked.connect(self._on_emergency_clicked)
        alay.addWidget(self._emergency_btn)

        alay.addStretch(1)

        self._disconnect_btn = QPushButton("Отключить Keithley", self)
        self._disconnect_btn.setObjectName("keithleyDisconnectBtn")
        self._disconnect_btn.setStyleSheet(_SmuChannelBlock._ghost_button_qss())
        self._disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        alay.addWidget(self._disconnect_btn)

        root.addWidget(actions)

    # ------------------------------------------------------------------
    # Public API — parent pushes state
    # ------------------------------------------------------------------

    def set_state(self, state: KeithleyState) -> None:
        self._connected = state.connected
        if state.connected:
            self._connection_label.setText("● Подключён")
            self._connection_label.setStyleSheet(
                f"color: {theme.STATUS_OK}; background: transparent;"
            )
        else:
            self._connection_label.setText("● Нет связи")
            self._connection_label.setStyleSheet(
                f"color: {theme.STATUS_FAULT}; background: transparent;"
            )
        self._smua_block.apply_state(state.smua)
        self._smub_block.apply_state(state.smub)
        self._refresh_gate()

    def set_safety_ready(self, ready: bool, reason: str = "") -> None:
        """Gate controls on SafetyManager state.

        When `ready=False`, all interactive controls (mode, setpoint,
        output toggle) are disabled and `reason` is displayed so the
        operator knows why.
        """
        self._safety_ready = ready
        self._safety_reason = reason
        self._refresh_gate()

    # ------------------------------------------------------------------
    # Internal gating
    # ------------------------------------------------------------------

    def _refresh_gate(self) -> None:
        controls_enabled = self._connected and self._safety_ready
        self._smua_block.set_enabled(controls_enabled)
        self._smub_block.set_enabled(controls_enabled)

        # Reason label only for safety gate (not connection — connection
        # already has the «Нет связи» header indicator).
        if not self._safety_ready and self._connected:
            msg = self._safety_reason or "SafetyManager не в состоянии ready"
            self._gate_reason_label.setText(f"Управление заблокировано: {msg}")
            self._gate_reason_label.setVisible(True)
        else:
            self._gate_reason_label.setVisible(False)

        # Emergency stop remains available even when gated — it's the
        # escape hatch. Disconnect button also stays enabled so operator
        # can cleanly pull Keithley out if safety is latched.
        self._emergency_btn.setEnabled(True)
        self._disconnect_btn.setEnabled(self._connected)

    # ------------------------------------------------------------------
    # Destructive action handlers
    # ------------------------------------------------------------------

    def _on_emergency_clicked(self) -> None:
        # RULE-INTER-004: destructive, requires confirmation.
        # Spec invariant #9 calls for HoldConfirm 1s hold; we ship Dialog
        # confirmation today and track HoldConfirm as later work.
        reply = QMessageBox.warning(
            self.window() or self,
            "Аварийное отключение Keithley",
            (
                "Будут немедленно отключены оба канала smua и smub. "
                "Эксперимент может перейти в fault_latched. Продолжить?"
            ),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Ok:
            self.emergency_off_requested.emit()

    def _on_disconnect_clicked(self) -> None:
        reply = QMessageBox.question(
            self.window() or self,
            "Отключить Keithley?",
            (
                "Будут сначала отключены оба канала (emergency_off), "
                "затем освобождено USB-соединение. Продолжить?"
            ),
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Ok:
            self.disconnect_requested.emit()
