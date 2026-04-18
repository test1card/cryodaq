---
title: KeithleyPanel
keywords: keithley, smu, power, current, voltage, resistance, tsp, dual-channel, smua, smub, source, measure, p-target
applies_to: Keithley 2604B source-measure unit control overlay
status: active
implements: src/cryodaq/gui/shell/overlays/keithley_panel.py (Phase II.6 rewrite); legacy src/cryodaq/gui/widgets/keithley_panel.py retained (DEPRECATED) until Phase III.3
last_updated: 2026-04-18
references: rules/data-display-rules.md, rules/interaction-rules.md, patterns/destructive-actions.md
---

# KeithleyPanel

Operator overlay for controlling and monitoring the Keithley 2604B source-measure unit (SMU). Dual-channel (`smua` + `smub`), TSP-scripted hardware. The most complex CryoDAQ instrument widget because it combines live V/I/R/P measurement displays, live power-control setpoints (debounced), and destructive-level actions (start / stop / emergency-off per channel).

> **Implementation status (2026-04-18).** The shipped overlay at
> `src/cryodaq/gui/shell/overlays/keithley_panel.py` (Phase II.6)
> matches this spec: symmetric dual-channel layout «Канал А» / «Канал B»
> (Cyrillic А per RULE-COPY-002), per-channel P target / V compliance /
> I compliance `QDoubleSpinBox` controls debounced to 300 ms, 4 live
> readouts (V / I / R / P) in Fira Mono with tabular figures
> (RULE-TYPO-003), a 2×2 rolling plot grid per channel (V / I / R / P
> over time, `apply_plot_style()` from `_plot_style.py`), state badge
> driven by `analytics/keithley_channel_state/{smua,smub}`, STATUS_FAULT
> 3px border on a faulted channel block, stale detection applied
> *only* while state == "on" (if off/fault we don't expect live
> measurements), safety gating via `set_safety_ready(ok, reason)` with
> dedicated reason label, connection header that flips to «Нет связи»
> and disables controls when disconnected, panel-level «Старт A+B»
> / «Стоп A+B» / «АВАР. ОТКЛ. A+B», time-window toolbar
> («10м» / «1ч» / «6ч») affecting both channels simultaneously,
> emergency-off guarded by `QMessageBox.warning` confirmation
> (RULE-INTER-004 destructive variant), emergency always reachable when
> connected even if safety blocks normal control.
>
> **Known limitations** (tracked as follow-ups, not blocking):
> - FU.4 — K4 custom-command popup (Keithley TSP/SCPI console) not shipped.
> - FU.5 — HoldConfirm 1s hold for emergency buttons ships as
>   `QMessageBox.warning` today. HoldConfirm primitive not yet built.
> - DS coverage gaps flagged during rewrite: window-toolbar active-state
>   toggle pattern, connection-indicator dot glyph, state badge —
>   inline QSS used where a DS primitive was not available. Reconcile
>   when those primitives are defined.
>
> The legacy v1 panel at `src/cryodaq/gui/widgets/keithley_panel.py`
> is marked DEPRECATED and stays alive for the transitional
> `main_window.py` path only; removal is tracked under Phase III.3
> legacy cleanup. `MainWindowV2` imports the overlay from
> `shell/overlays/keithley_panel.py` exclusively.

**When to use:**
- Dedicated Keithley overlay opened via ToolRail (slot «Источник», Ctrl+K).
- Inside the experiment overlay when SMU operation is part of experiment flow (embed the overlay itself, not a compact summary).

**When NOT to use:**
- Generic form for SMU parameters — Keithley has TSP-specific behavior that must be respected.
- Historical replay of SMU data — use `AnalyticsView`.
- Non-Keithley instruments — other SMUs need their own specialized panel.

## Absolute invariants (from CryoDAQ codebase rules)

Fixed at codebase level; UI code must not violate:

1. **Keithley uses TSP (Lua), NOT SCPI.** Commands go via `print(...)` TSP invocations. UI emits TSP-appropriate command names (`keithley_start`, `keithley_stop`, `keithley_emergency_off`, `keithley_set_target`, `keithley_set_limits`); never raw SCPI.
2. **Engine API is power-control only.** Accepted payload keys: `p_target` (W), `v_comp` (V compliance), `i_comp` (A compliance). There is no `mode=current/voltage` in the engine. GUI must not invent mode semantics disconnected from the driver. Previous B.7 design violated this and was never wired.
3. **Dual-channel.** `smua` and `smub` are both active. Any UI showing only one channel is wrong.
4. **Safety disconnect calls `emergency_off` first.** Disconnecting Keithley triggers safety emergency_off before USB release. UI must not bypass this.
5. **`SafetyManager` is the only source on/off authority.** UI cannot directly command hardware to enable output; it sends `keithley_start` which the engine routes via `SafetyManager.request_run(...)` with preconditions validated.
6. **Persistence-first ordering.** SMU readings go through the scheduler which writes to SQLite BEFORE publishing to DataBroker. UI reads via DataBroker only.

## Anatomy

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  KEITHLEY 2604B                                        ● Подключён            │  ◀── header: title + connection
│                                                                               │
│  ( status banner — transient info/warning/error, auto-clear 4s )              │
│  ( gate reason label — shown when set_safety_ready(False, reason) )           │
│                                                                               │
│  Окно:  [10м]  [1ч]  [6ч]                                                     │  ◀── time-window toolbar
│                                                                               │
│  ┌──────────────────────────┐     ┌──────────────────────────┐                │
│  │  Канал А            [ВКЛ]│     │  Канал B           [ВЫКЛ]│                │  ◀── state badge
│  │                          │     │                          │                │
│  │  P цель  V пред.  I пред.│     │  P цель  V пред.  I пред.│                │
│  │  [0.500] [40.00] [1.000] │     │  [0.500] [40.00] [1.000] │                │  ◀── controls card
│  │  [Старт][Стоп][АВАР.ОТКЛ]│     │  [Старт][Стоп][АВАР.ОТКЛ]│                │
│  │                          │     │                          │                │
│  │  Напряжение   Ток        │     │  Напряжение   Ток        │                │
│  │   12.345 В    0.345 А    │     │   0.000 В    0.000 А     │                │  ◀── readouts card
│  │  Сопрот.      Мощность   │     │  Сопрот.      Мощность   │                │
│  │   35.78 Ом    4.256 Вт   │     │   — Ом        0.000 Вт   │                │
│  │                          │     │                          │                │
│  │  ┌────────┐  ┌────────┐  │     │  ┌────────┐  ┌────────┐  │                │
│  │  │   V    │  │   I    │  │     │  │   V    │  │   I    │  │                │
│  │  ├────────┤  ├────────┤  │     │  ├────────┤  ├────────┤  │  ◀── 2×2 plots
│  │  │   R    │  │   P    │  │     │  │   R    │  │   P    │  │                │
│  │  └────────┘  └────────┘  │     │  └────────┘  └────────┘  │                │
│  └──────────────────────────┘     └──────────────────────────┘                │
│                                                                               │
│                          [Старт A+B] [Стоп A+B] [АВАР. ОТКЛ. A+B]             │  ◀── footer: panel-level
└──────────────────────────────────────────────────────────────────────────────┘
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Panel root** | Yes | `keithleyPanel` frame with background SURFACE_WINDOW |
| **Header row** | Yes | Title «KEITHLEY 2604B» + connection indicator (● Подключён / ● Нет связи) |
| **Status banner** | Yes | Transient messages (info / warning / error); auto-clears after 4 s |
| **Gate reason label** | Yes | Shown when `set_safety_ready(False, reason)` — «Управление заблокировано: {reason}» in STATUS_WARNING |
| **Window toolbar** | Yes | «10м» / «1ч» / «6ч» time-window buttons (active variant highlighted) |
| **Channel block** (×2) | Yes | smua + smub — symmetric, always visible |
| **Channel header** | Per channel | Channel label «Канал А» / «Канал B» + state badge (ВЫКЛ / ВКЛ / АВАРИЯ) |
| **Controls card** | Per channel | P target + V compliance + I compliance `QDoubleSpinBox` + Старт / Стоп / АВАР. ОТКЛ. |
| **Readouts card** | Per channel | 4 live value labels (V / I / R / P) in Fira Mono with tabular figures |
| **Plots grid** | Per channel | 2×2 `pg.PlotWidget` (V / I / R / P), rolling window per panel-level toolbar selection |
| **Panel-level footer** | Yes | «Старт A+B» / «Стоп A+B» / «АВАР. ОТКЛ. A+B» (single confirmation dialog for A+B emergency) |

## Invariants

1. **Both channels always visible.** Layout symmetry = operator visual parity = fewer mistakes. No collapsing smub, even when disconnected.
2. **Engine command surface is power-control only.** Controls map 1:1 to engine payload: P target → `p_target` (W), V predel → `v_comp` (V), I predel → `i_comp` (A). No `mode=current/voltage`.
3. **Spin changes are debounced 300 ms and gated on state == "on".** Spinning P / V / I while the channel is "on" restarts a single-shot `QTimer(300ms)`; on timeout the final value is sent (P → `keithley_set_target`, V/I → `keithley_set_limits`). In state "off" or "fault" spins emit no commands — the channel isn't receiving power, so live limit updates are meaningless.
4. **Start is the only path to source ON.** `Старт` click sends `keithley_start` which the engine routes through `SafetyManager.request_run(p, v, i)`. If preconditions fail, engine returns an error — UI does not bypass. The GUI never directly commands hardware.
5. **Slew rate limit enforced server-side.** UI does NOT interpolate setpoints. Engine-side slew limiter ramps the output; UI sends the final target value.
6. **Values display in SI units with Russian symbols.** V = «В», I = «А», R = «Ом», P = «Вт». (RULE-COPY-006.)
7. **Live values use FONT_MONO with tabular figures.** `tnum` OpenType feature enabled when the Qt version supports it (graceful fallback). (RULE-TYPO-003.)
8. **State badge uses redundant channels.** Text label (ВЫКЛ / ВКЛ / АВАРИЯ) + color (MUTED_FOREGROUND / STATUS_OK / STATUS_FAULT). Not color alone. (RULE-A11Y-002.)
9. **Emergency stop guarded by destructive-variant confirmation.** `QMessageBox.warning` with Ok / Cancel (RULE-INTER-004). FU.5 tracks a future HoldConfirm 1 s hold upgrade. A+B emergency uses a single confirmation covering both channels, not two separate dialogs.
10. **Emergency button stays enabled whenever connected.** Escape hatch — disabled only on full disconnect. Safety gating blocks Start/Stop/spins, not emergency.
11. **No emoji.** (RULE-COPY-005.)
12. **Labels «Канал А» / «Канал B», not «smua» / «smub» in operator-facing UI.** Those identifiers are internal. Cyrillic А (U+0410), Latin B. (RULE-COPY-002.)
13. **Stale detection only when state == "on".** If channel is off or fault, a stalled reading isn't a symptom — the channel isn't supposed to stream. Stale chrome (STATUS_STALE border + «устар.» suffix) applies only to an "on" channel whose last reading is older than 5 s.
14. **Fault state draws a 3 px STATUS_FAULT border on the channel block.** Visual coherence with other fault-bearing surfaces.
15. **Plot line color is channel-coded, not quantity-coded.** smua → `PLOT_LINE_PALETTE[0]`, smub → `PLOT_LINE_PALETTE[1]`. All 4 plots of one channel share the same pen. Quantity distinction comes from the plot's Y-axis label + unit, not pen color. (RULE-COLOR-002 reserves STATUS_* for semantic state.)

## API

```python
# src/cryodaq/gui/shell/overlays/keithley_panel.py

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Signal

from cryodaq.drivers.base import Reading


class KeithleyPanel(QWidget):
    """Dual-channel Keithley 2604B operator overlay."""

    # Per-channel signals (for shell wiring and tests)
    channel_start_requested = Signal(str, float, float, float)
    # args: (channel_key: "smua" | "smub", p_target: W, v_comp: V, i_comp: A)

    channel_stop_requested = Signal(str)               # channel_key
    channel_emergency_requested = Signal(str)          # channel_key
    channel_target_updated = Signal(str, float)        # (channel_key, p_target) — debounced
    channel_limits_updated = Signal(str, float, float) # (channel_key, v_comp, i_comp) — debounced

    # Panel-level signals
    both_channels_start_requested = Signal()
    both_channels_stop_requested = Signal()
    both_channels_emergency_requested = Signal()

    # Public state pushers (called by MainWindowV2 / shell)
    def on_reading(self, reading: Reading) -> None: ...
    def set_connected(self, connected: bool) -> None: ...
    def set_safety_ready(self, ready: bool, reason: str = "") -> None: ...

    # Transient banner
    def show_info(self, text: str) -> None: ...
    def show_warning(self, text: str) -> None: ...
    def show_error(self, text: str) -> None: ...
    def clear_message(self) -> None: ...
```

**Signal semantics.** Per-channel signals are relays from the internal `_SmuChannelBlock` widgets — the panel exposes them so tests and shell code can observe every user intent without running a real ZMQ bridge. Production code path: each click handler also spawns a `ZmqCommandWorker` with the appropriate payload (`keithley_start`, `keithley_stop`, `keithley_emergency_off`, `keithley_set_target`, `keithley_set_limits`). Worker result is logged asynchronously; the UI thread does not block.

**Reading routing.** `on_reading(Reading)` inspects `reading.channel`:
- `analytics/keithley_channel_state/smua|smub` → `metadata["state"]` drives the channel's state badge and enable/disable logic.
- `<instrument>/smua|smub/{voltage|current|resistance|power}` → updates the matching readout label and appends `(timestamp, value)` to a per-measurement `deque(maxlen=3600)` for plot rendering.

A 500 ms `QTimer` drives plot refresh + stale detection (not per-reading — reading frequency from the driver is too high for per-event plot updates). Stale check: if state == "on" and `now - last_update_ts > 5 s`, apply STATUS_STALE border + «устар.» suffix.

## Layout rules specific to this panel

- **Channels side-by-side at ≥ 1100 px viewport; stacked below that.** Desktop-only at 1280+ typical — side-by-side is the standard.
- **Equal channel widths.** Symmetry matters for operator parity. No asymmetric «bigger smua / smaller smub».
- **Footer right-anchored.** Panel-level «Старт A+B» / «Стоп A+B» / «АВАР. ОТКЛ. A+B» all right-aligned with equal spacing.
- **Window toolbar left-anchored.** Caption «Окно:» + three toggle buttons + stretch.
- **SPACE_3 padding** inside channel block, **SPACE_2** between controls/readouts/plots, **SPACE_4** around panel root.

## States

| Panel state | Treatment |
|---|---|
| **Disconnected** | All readouts «— В/А/Ом/Вт»; spins + start/stop disabled; emergency disabled (no link); «Нет связи» in STATUS_FAULT |
| **Connected, both off** | Controls enabled, readouts show last sampled (likely zero), state badges «ВЫКЛ» in MUTED_FOREGROUND |
| **Channel "on"** | State badge «ВКЛ» STATUS_OK; start disabled, stop/emergency enabled; spins debounced-live against engine |
| **Channel "fault"** | State badge «АВАРИЯ» STATUS_FAULT; 3 px STATUS_FAULT border on channel block; start/stop/spins disabled on the faulted channel; emergency still enabled; sibling channel unaffected |
| **Safety gated** | Start/Stop/spins disabled across both channels; emergency stays enabled; gate label «Управление заблокировано: {reason}» visible in STATUS_WARNING |
| **Stale reading (state="on")** | Readouts keep FOREGROUND text color (RULE-DATA-005 — never dim values); readouts card gets STATUS_STALE 1 px border; each readout suffix becomes «12.345 В (устар.)» |
| **Transient banner** | Thin colored border (STATUS_INFO / STATUS_WARNING / STATUS_FAULT); auto-clear 4 s |

## Common mistakes

1. **Inventing mode semantics.** The engine does not have a `mode` field. `p_target + v_comp + i_comp` is the complete control surface. B.7 (`920aa97`) invented Ток/Напряжение/Откл and was never wired. Do not reintroduce.
2. **Sending debounce commands in state "off" or "fault".** Channel isn't receiving power; live limit updates are noise. Gate the debounce at both the spin event and timer timeout.
3. **Showing stale chrome in state "off".** Channel isn't supposed to stream; stalled reading isn't a symptom. Stale only applies when state == "on".
4. **Collapsing smub into an "advanced" disclosure.** Dual-channel is an invariant. Both always visible.
5. **Using «smua» / «smub» as operator labels.** Those are TSP identifiers. Operator sees «Канал А» / «Канал B». RULE-COPY-002. Cyrillic А (U+0410), not Latin A.
6. **Enable-output as single click without confirmation.** All emergency variants require a warning-variant dialog. RULE-INTER-004.
7. **Animating measured values.** Violates RULE-DATA-009. Live values snap.
8. **No confirmation on A+B emergency.** Must confirm with a single dialog covering both channels — not two separate confirms, not zero.
9. **Proportional font on readout values.** Current/voltage readouts jitter as digits change. Use `FONT_MONO` + `FONT_MONO_VALUE_SIZE` + tabular figures. RULE-TYPO-003.
10. **Ignoring slew rate in UI.** UI interpolating target values sent in frames. Don't. Engine slew-limits; UI sends final target.
11. **Coloring plot lines by quantity.** RULE-COLOR-002 reserves STATUS_* semantics and discourages per-quantity pen colors. Use `PLOT_LINE_PALETTE[channel_index]` — channel-coded, not quantity-coded.
12. **Measured value colored STATUS_FAULT at body size.** Fails contrast. Use FOREGROUND + separate fault indicator. RULE-A11Y-003.
13. **Blocking the GUI thread on a command.** `ZmqCommandWorker` is a `QThread`. Click handlers must spawn a worker and wire its `finished` signal; never call `send_command()` directly from a UI slot.

## Related components

- `components/dialog.md` — Emergency confirmation (warning variant per RULE-INTER-004).
- `components/button.md` — Primary / Warning / Destructive button variants. Window-toolbar toggle variant is a DS coverage gap flagged in the II.6 rewrite.
- `components/badge.md` — State badge (ВЫКЛ / ВКЛ / АВАРИЯ) alignment target.
- `components/card.md` — Controls / readouts cards use card semantics (SURFACE_CARD background + BORDER_SUBTLE 1 px + RADIUS_MD).
- `components/chart-tile.md` — Future alignment target for the V/I/R/P plots if Phase I.2 ChartTile primitive ships.
- `cryodaq-primitives/analytics-panel.md` — Analytics surface consumes historical SMU data; live control lives only here.

## Changelog

- **2026-04-18 — Phase II.6 rewrite.** Full rebuild of `shell/overlays/keithley_panel.py` aligned with engine power-control API. Replaces dead B.7 (`920aa97`) mode-based overlay. Removes all `mode=current/voltage` content from this spec. Replaces legacy v1 surface (`widgets/keithley_panel.py` now DEPRECATED) behind `MainWindowV2` Ctrl+K. Follow-ups FU.4 (K4 custom-command popup) and FU.5 (HoldConfirm 1 s for emergency) explicitly deferred.
- **2026-04-17 — Initial version.** Documented mode-based Keithley 2604B control panel (B.7 design). Superseded by 2026-04-18 rewrite; entry preserved for historical trace.
