---
title: KeithleyPanel
keywords: keithley, smu, power, current, voltage, resistance, tsp, dual-channel, smua, smub, source, measure
applies_to: Keithley 2604B source-measure unit control panel
status: partial
implements: legacy power source panel (ToolRail slot 4)
last_updated: 2026-04-17
---

# KeithleyPanel

Panel for controlling and monitoring the Keithley 2604B source-measure unit (SMU). Dual-channel (smua + smub), TSP-scripted hardware. One of the most complex CryoDAQ widgets because it combines live measurement displays with output control and destructive-level actions (enable/disable current output).

**When to use:**
- Dedicated Keithley panel opened via ToolRail slot 4
- Inside the experiment overlay when SMU operation is part of the experiment flow

**When NOT to use:**
- Generic form for SMU parameters — Keithley has specific TSP-based behavior that must be respected
- Historical replay of SMU data — use Analytics panel
- Non-Keithley instruments — this panel is Keithley-specific; other SMUs need their own specialized panel

## Absolute invariants (from CryoDAQ codebase rules)

These are fixed at codebase level and must not be changed by UI code:

1. **Keithley uses TSP (Lua), NOT SCPI.** Commands go via `print(...)` TSP invocations. UI emits TSP-appropriate command names; never raw SCPI.
2. **Dual-channel.** `smua` and `smub` are both active. NOT single-channel. Any UI showing only one channel is wrong.
3. **Safety disconnect calls emergency_off first.** Disconnecting Keithley triggers safety emergency_off before USB release. UI must not bypass this.
4. **SafetyManager is the only source on/off authority.** UI cannot directly command hardware to enable output; it requests via SafetyManager which validates preconditions.
5. **Persistence-first ordering.** SMU readings go through the scheduler which writes to SQLite BEFORE publishing to DataBroker. UI reads via DataBroker only.

## Anatomy

```
┌────────────────────────────────────────────────────────────────────────────┐
│                                                                            │
│  KEITHLEY 2604B                         ● Подключён   ● Канал А   ● Канал B│  ◀── connection + channel state
│                                                                            │
│  ┌──────────────────────────┐  ┌──────────────────────────┐                │
│  │  Канал А (smua)          │  │  Канал B (smub)          │                │  ◀── two channel blocks
│  │                          │  │                          │                │      side by side
│  │  Режим:  Ток             │  │  Режим:  Напряжение      │                │
│  │                          │  │                          │                │
│  │  Установка:  0.100 А     │  │  Установка:  12.000 В    │                │
│  │  Измерено:  0.099 А      │  │  Измерено:  11.998 В     │                │
│  │  Напряжение: 1.23 В      │  │  Ток: 0.050 А            │                │
│  │  Мощность: 0.122 Вт      │  │  Мощность: 0.600 Вт      │                │
│  │                          │  │                          │                │
│  │  [ Вкл выход ]           │  │  [ Вкл выход ]           │                │
│  │                          │  │                          │                │
│  └──────────────────────────┘  └──────────────────────────┘                │
│                                                                            │
│  [ АВАР. ОТКЛ. ]  (hold-confirm 1s)                     [ Отключить Keithley ] │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Panel frame** | Yes | Standard Card with panel title header |
| **Connection indicator** | Yes | smua + smub state indicators + overall connection status |
| **Channel block** (×2) | Yes | smua + smub — symmetric, both always shown |
| **Mode selector** | Per channel | Current / Voltage / disabled |
| **Setpoint input** | Per channel | Numeric input with unit (A or V) |
| **Live measurements** | Per channel | Multiple readouts (measured, other-quantity, power) |
| **Output toggle** | Per channel | Enable/disable output — destructive for enable |
| **Emergency stop** | Yes | АВАР. ОТКЛ. — hold-confirm button, kills both channels immediately |
| **Disconnect button** | Yes | Safely disconnects Keithley (triggers emergency_off first per invariant 3) |

## Invariants

1. **Both channels always visible even if disabled.** Layout symmetry = operator visual parity = fewer mistakes. (Domain rule)
2. **Output toggle is destructive-level for enable, safe for disable.** Enabling output requires confirmation (hold-confirm or dialog); disabling does not. Operator never accidentally turns OFF something that was active — that's safe — but accidentally turning ON mid-experiment can damage equipment.
3. **Setpoint changes require explicit «Применить» click.** Don't auto-apply on typing. Operator may be mid-edit, and partial values shouldn't stream to hardware.
4. **Slew rate limit enforced server-side.** UI does NOT interpolate setpoints. Engine-side slew limiter (part of safety hardening per audit V2) ramps the output; UI just sends final value.
5. **Values display in SI units with Russian symbols.** Current = «А», Voltage = «В», Power = «Вт», Resistance = «Ом». (RULE-COPY-006)
6. **Measured value differs from setpoint — this is NORMAL.** Display both; don't alarm on mismatch unless > tolerance (operator configures). Some mismatch is physics, not fault.
7. **Live values tabular mono.** (RULE-TYPO-003)
8. **Output ON status via redundant channels.** Color (STATUS_OK green indicator) + text («Выход: вкл»). Not color alone. (RULE-A11Y-002)
9. **Emergency stop is NEVER a regular button.** HoldConfirmButton pattern with 1s hold. Shortcut: Ctrl+Shift+X global. (RULE-INTER-004)
10. **No emoji.** (RULE-COPY-005)
11. **Labels «Канал А» / «Канал B».** Not «smua» / «smub» in operator-facing UI — those are internal identifiers. (RULE-COPY-002)

## API (proposed)

```python
# src/cryodaq/gui/widgets/keithley_panel.py

@dataclass
class SmuChannelState:
    key: str                     # "smua" or "smub"
    label: str                   # "Канал А" or "Канал B"
    output_enabled: bool
    mode: str                    # "current" | "voltage" | "disabled"
    setpoint: float              # A or V depending on mode
    measured_primary: float      # A if current mode, V if voltage mode
    measured_secondary: float    # the other quantity
    power_w: float
    last_updated_t: float
    faulted: bool


@dataclass
class KeithleyState:
    connected: bool
    smua: SmuChannelState
    smub: SmuChannelState


class KeithleyPanel(QWidget):
    """Keithley 2604B SMU control + monitoring panel."""
    
    # Per-channel signals
    setpoint_apply_requested = Signal(str, float)  # (channel_key, value)
    mode_change_requested = Signal(str, str)        # (channel_key, mode)
    output_toggle_requested = Signal(str, bool)     # (channel_key, enable)
    
    # Panel-level signals
    emergency_off_requested = Signal()              # kills both channels
    disconnect_requested = Signal()                  # safe disconnect
    
    def __init__(self, parent: QWidget | None = None) -> None: ...
    
    def set_state(self, state: KeithleyState) -> None: ...
```

## Channel block reference

```python
class SmuChannelBlock(QWidget):
    """One of the two channel blocks (smua or smub)."""
    
    setpoint_apply_requested = Signal(float)
    mode_change_requested = Signal(str)
    output_toggle_requested = Signal(bool)
    
    def __init__(self, channel_key: str, label: str, parent=None):
        super().__init__(parent)
        self._channel_key = channel_key
        
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        
        # Each channel block is a PanelCard (inner)
        self._card = PanelCard(surface="elevated")
        outer.addWidget(self._card)
        
        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        
        # DESIGN: RULE-COPY-002 label "Канал А" not "smua"
        self._title = QLabel(label)
        title_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        title_font.setWeight(theme.FONT_LABEL_WEIGHT)
        title_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
        )
        self._title.setFont(title_font)
        self._title.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        col.addWidget(self._title)
        
        # Mode selector
        col.addWidget(self._build_mode_row())
        
        # Setpoint input + Apply
        col.addWidget(self._build_setpoint_row())
        
        # Measured values
        col.addWidget(self._build_measured_grid())
        
        # Output toggle
        col.addWidget(self._build_output_row())
        
        self._card.set_content(content)
    
    def _build_mode_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)
        
        label = QLabel("Режим:")
        label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        label.setFixedWidth(80)
        layout.addWidget(label)
        
        # DESIGN: segmented tab pattern (components/tab-group.md variant 4)
        self._mode_tabs = TabGroup(
            [
                TabDef(label="Ток",         key="current"),
                TabDef(label="Напряжение",  key="voltage"),
                TabDef(label="Откл",        key="disabled"),
            ],
            compact=True,
        )
        self._mode_tabs.selection_changed.connect(self.mode_change_requested)
        layout.addWidget(self._mode_tabs, 1)
        return row
    
    def _build_setpoint_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)
        
        label = QLabel("Установка:")
        label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        label.setFixedWidth(80)
        layout.addWidget(label)
        
        # DESIGN: RULE-COPY-006 (unit inline), RULE-TYPO-003 (tnum)
        self._setpoint_input = InputField(
            label="",
            placeholder="0.000",
            unit="А",  # dynamically updated per mode
            validator=QDoubleValidator(0.0, 1.0, 3),  # 0-1 A range for smua
        )
        layout.addWidget(self._setpoint_input, 1)
        
        # DESIGN: RULE-COPY-007 imperative
        self._apply_btn = SecondaryButton("Применить")
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)
        
        return row
    
    def _build_measured_grid(self) -> QWidget:
        row = QWidget()
        layout = QGridLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(theme.SPACE_5)
        layout.setVerticalSpacing(theme.SPACE_1)
        
        # DESIGN: RULE-TYPO-003 tnum for all measured values
        measured_font = QFont(theme.FONT_MONO, theme.FONT_MONO_VALUE_SIZE)
        measured_font.setFeature("tnum", 1)
        measured_font.setFeature("liga", 0)
        
        self._measured_labels: dict[str, QLabel] = {}
        for i, (key, caption) in enumerate([
            ("primary",   "Измерено:"),
            ("secondary", "—"),        # placeholder; label text updates per mode
            ("power",     "Мощность:"),
        ]):
            cap_label = QLabel(caption)
            cap_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
            layout.addWidget(cap_label, i, 0)
            
            val_label = QLabel("—")
            val_label.setFont(measured_font)
            val_label.setStyleSheet(f"color: {theme.FOREGROUND};")
            layout.addWidget(val_label, i, 1)
            self._measured_labels[key] = val_label
        
        return row
    
    def _build_output_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)
        
        # DESIGN: RULE-A11Y-002 icon + text for output state
        self._output_indicator = InlineIndicator("Выход: откл", "stale")
        layout.addWidget(self._output_indicator)
        
        layout.addStretch()
        
        # DESIGN: RULE-INTER-004 — enable is destructive-level (needs confirmation)
        # We use SecondaryButton for toggle; confirmation happens at dialog level
        # on enable only; disable proceeds without confirmation
        self._output_toggle = SecondaryButton("Вкл выход")
        self._output_toggle.clicked.connect(self._on_output_toggle)
        layout.addWidget(self._output_toggle)
        
        return row
    
    def _on_output_toggle(self) -> None:
        # DESIGN: RULE-INTER-004 — confirmation on enable only
        if self._current_state.output_enabled:
            # Disable = safe direction, proceed
            self.output_toggle_requested.emit(False)
        else:
            # Enable = destructive direction, confirm
            dialog = Dialog(
                parent=self.window(),
                title=f"Включить выход канала {self._title.text()}?",
                body=(
                    f"Будет подан {self._current_state.setpoint:.3f} "
                    f"{'А' if self._current_state.mode == 'current' else 'В'} "
                    f"на оборудование. Убедитесь, что подключение корректно."
                ),
                primary_label="Включить",
                primary_role="destructive",
                cancel_label="Отмена",
                icon_status="warning",
                default_focus="cancel",
            )
            def on_result(result: str):
                if result == Dialog.ACCEPTED:
                    self.output_toggle_requested.emit(True)
            dialog.finished.connect(on_result)
            dialog.open()
    
    def _on_apply(self) -> None:
        try:
            value = float(self._setpoint_input.text().replace(",", "."))
            self.setpoint_apply_requested.emit(value)
        except ValueError:
            self._setpoint_input.set_error("Введите число")
    
    def set_state(self, state: SmuChannelState) -> None:
        # DESIGN: RULE-DATA-001 atomic
        self._current_state = state
        self._mode_tabs.set_selected(state.mode)
        
        # Setpoint — update unit label per mode
        unit = "А" if state.mode == "current" else "В" if state.mode == "voltage" else ""
        # (InputField API would need method to update unit; ref only)
        
        # Measured — labels + values per mode
        if state.mode == "current":
            self._measured_labels["primary"].setText(f"{state.measured_primary:.3f} А")
            # secondary caption and value become "Напряжение: 1.23 В"
        elif state.mode == "voltage":
            self._measured_labels["primary"].setText(f"{state.measured_primary:.3f} В")
        self._measured_labels["power"].setText(f"{state.power_w:.3f} Вт")
        
        # Output state
        if state.output_enabled:
            self._output_indicator.set("Выход: вкл", "ok")
            self._output_toggle.setText("Откл выход")
        else:
            self._output_indicator.set("Выход: откл", "stale")
            self._output_toggle.setText("Вкл выход")
        
        # Fault treatment
        if state.faulted:
            # Apply fault-chrome via PanelCard style override or an inline banner
            pass
```

## Main panel reference (orchestration)

```python
class KeithleyPanel(QWidget):
    setpoint_apply_requested = Signal(str, float)
    mode_change_requested = Signal(str, str)
    output_toggle_requested = Signal(str, bool)
    emergency_off_requested = Signal()
    disconnect_requested = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5
        )
        outer.setSpacing(theme.SPACE_4)
        
        # Header row
        outer.addWidget(self._build_header())
        
        # Two channel blocks side by side
        channels_row = QHBoxLayout()
        channels_row.setContentsMargins(0, 0, 0, 0)
        channels_row.setSpacing(theme.GRID_GAP)
        
        self._smua = SmuChannelBlock("smua", "Канал А")
        self._smub = SmuChannelBlock("smub", "Канал B")
        
        for ch in (self._smua, self._smub):
            ch.setpoint_apply_requested.connect(
                lambda v, c=ch: self.setpoint_apply_requested.emit(c._channel_key, v)
            )
            ch.mode_change_requested.connect(
                lambda m, c=ch: self.mode_change_requested.emit(c._channel_key, m)
            )
            ch.output_toggle_requested.connect(
                lambda enable, c=ch: self.output_toggle_requested.emit(c._channel_key, enable)
            )
        
        channels_row.addWidget(self._smua, 1)
        channels_row.addWidget(self._smub, 1)
        outer.addLayout(channels_row)
        
        # Panel-level actions
        outer.addWidget(self._build_actions_row())
    
    def _build_header(self) -> QWidget:
        # DESIGN: RULE-TYPO-008 UPPERCASE category label
        # DESIGN: RULE-COPY-002 — "Канал А / Канал B" per invariant 11 (never smua/smub in operator UI)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_3)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        title = QLabel("KEITHLEY 2604B")
        title_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        title_font.setWeight(theme.FONT_LABEL_WEIGHT)
        title_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
        )
        title.setFont(title_font)
        title.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        layout.addWidget(title)
        
        layout.addStretch()
        
        # DESIGN: RULE-A11Y-002 — indicator uses dot + label (redundant channels)
        self._connection_indicator = InlineIndicator("Подключён", "ok")
        layout.addWidget(self._connection_indicator)
        
        self._smua_indicator = InlineIndicator("Канал А", "stale")
        layout.addWidget(self._smua_indicator)
        
        self._smub_indicator = InlineIndicator("Канал B", "stale")
        layout.addWidget(self._smub_indicator)
        
        return row
    
    def _build_actions_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_3)
        
        # DESIGN: RULE-INTER-004 — АВАР. ОТКЛ. is hold-confirm
        # DESIGN: RULE-TYPO-005 Cyrillic uppercase letter-spacing
        emergency_btn = HoldConfirmButton("АВАР. ОТКЛ.")
        emergency_btn.triggered.connect(self.emergency_off_requested)
        emergency_btn.setToolTip("Аварийное отключение обоих каналов (Ctrl+Shift+X)")
        layout.addWidget(emergency_btn)
        
        layout.addStretch()
        
        # Disconnect — destructive-ish (triggers emergency_off per invariant 3),
        # but slower path than АВАР. ОТКЛ.
        disconnect_btn = GhostButton("Отключить Keithley")
        disconnect_btn.clicked.connect(self._confirm_disconnect)
        layout.addWidget(disconnect_btn)
        
        return row
    
    def _confirm_disconnect(self) -> None:
        dialog = Dialog(
            parent=self.window(),
            title="Отключить Keithley?",
            body=(
                "Перед отключением будут выключены оба выхода (emergency_off). "
                "Активный эксперимент будет прерван."
            ),
            primary_label="Отключить",
            primary_role="destructive",
            cancel_label="Отмена",
            icon_status="warning",
            default_focus="cancel",
        )
        def on_result(result: str):
            if result == Dialog.ACCEPTED:
                self.disconnect_requested.emit()
        dialog.finished.connect(on_result)
        dialog.open()
```

## Layout rules specific to this panel

- **Channels side-by-side at ≥ 1100px viewport; stacked below that.** Desktop-only at 1280+ typical — side-by-side is the standard.
- **Equal channel widths.** Symmetry matters for operator parity. No asymmetric «bigger smua / smaller smub».
- **Emergency stop left-anchored, Disconnect right-anchored.** Spatial separation reduces miscick risk.

## States

| Panel state | Treatment |
|---|---|
| **Disconnected** | All values «—»; mode tabs disabled; setpoint disabled; emergency stop disabled; disconnect → reconnect button |
| **Connected, both outputs off** | Values show last sampled (likely zero); output toggles visible |
| **Normal operation (one or both outputs on)** | Live updates ≤ 2Hz; output indicators STATUS_OK |
| **Faulted** | Faulted channel has STATUS_FAULT border on its block; emergency stop button emphasized; auto-emergency_off already invoked by engine |
| **During slew** | Setpoint shows target; measured shows current (in-progress) value; no user-visible "ramping" animation — just see measured converge |

## Common mistakes

1. **Auto-applying setpoint on typing.** Partial values (e.g., operator typing «0.1» meaning to type «0.15») get streamed to hardware. Require explicit Apply.

2. **Single-channel view.** Showing only smua with «Advanced» expanding smub. Both channels always visible. Dual-channel is the invariant.

3. **Using «smua» / «smub» as operator labels.** Those are TSP identifiers. Operator sees «Канал А» / «Канал B». RULE-COPY-002.

4. **Enable-output as single click.** Operator clicks «Вкл», output goes on. Too dangerous. Require confirmation (Dialog with explicit impact description).

5. **Animating measured values.** Violates RULE-DATA-009. Live values snap.

6. **No confirmation on disconnect.** Disconnect triggers emergency_off and interrupts experiment. Confirm via Dialog.

7. **Emergency stop as regular button.** Single click accidentally triggered. Use HoldConfirmButton. RULE-INTER-004.

8. **Mixing SCPI with TSP commands.** TSP-only. Never emit SCPI from UI.

9. **Proportional font on measured values.** Current/voltage readouts jitter as digits change. Use FONT_MONO_VALUE. RULE-TYPO-003.

10. **Ignoring slew rate in UI.** UI interpolating target values sent in frames. Don't. Engine slew-limits; UI sends final target.

11. **Measured value colored STATUS_FAULT at body size.** Fails contrast. Use FOREGROUND + separate fault indicator. RULE-A11Y-003.

## Related components

- `components/dialog.md` — Output enable / disconnect confirmations
- `components/tab-group.md` — Mode selector (segmented variant)
- `components/input-field.md` — Setpoint entry
- `components/button.md` — HoldConfirmButton for АВАР. ОТКЛ.
- `cryodaq-primitives/experiment-card.md` — Experiment overlay may embed a compact SMU status summary; full control in this panel

## Changelog

- 2026-04-17: Initial version. Documents dual-channel Keithley 2604B control panel. All absolute invariants from CLAUDE.md preserved (TSP-only, dual-channel, emergency-off on disconnect, SafetyManager authority). Enable-output protected by confirmation dialog; АВАР. ОТКЛ. uses hold-confirm. Channel blocks labeled «Канал А» / «Канал B» (not smua/smub) for operator UI.
