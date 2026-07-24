---
title: ConductivityPanel
keywords: conductivity, thermal, R, G, steady-state, auto-sweep, keithley, power stepping, flight recorder
applies_to: Thermal conductivity overlay (R/G measurement + auto power-sweep + flight recorder)
status: active
implements: src/cryodaq/gui/shell/overlays/conductivity_panel.py; removed v1 widget is historical only
last_updated: 2026-07-20
references: rules/data-display-rules.md, rules/interaction-rules.md, components/card.md, components/input-field.md, components/button.md, cryodaq-primitives/keithley-panel.md
---

# ConductivityPanel

Operator overlay for thermal-conductivity measurement by power stepping. The
operator selects a temperature chain and power sweep; the overlay drives the
Keithley via `keithley_set_target`, waits for the settling threshold, records
R/G, and advances through the list. It finally requests `keithley_stop` and
publishes operator Stop (`idle`) or completed sweep (`done`) only after a
successful current-generation Engine/SafetyManager reply. Command dispatch
alone is never OFF evidence. A flight recorder writes every 1 Hz refresh tick
to CSV for post-hoc analysis.

> **Implementation status (2026-07-20).** The shipped overlay at
> `src/cryodaq/gui/shell/overlays/conductivity_panel.py` preserves the three
> public guard-state values (`idle`, `stabilizing`, `done`), settling physics,
> three-card information layout, and flight-recorder schema. Command settlement
> is no longer v1-verbatim: commands carry operation, connection, and command
> identity; duplicate, superseded, and stale replies cannot publish state; a
> failed, malformed, or disconnected outcome retains `stabilizing` plus an
> explicit outcome-unknown latch. Operator Stop and sweep completion remain
> guard-active until a successful current-generation `keithley_stop` reply
> permits publication of `idle` or `done`.
> Flight recorder schema preserved (18 columns, `utf-8-sig`,
> `logs/conductivity_<ts>.csv` under `get_data_dir() /
> conductivity_logs`). Public accessor `get_auto_state()` / 
> `is_auto_sweep_active()` replaces direct `_auto_state` attribute
> access for future ExperimentOverlay finalize guards (II.9
> follow-up — no v2 finalize path exists yet; legacy
> `main_window.py:_check_finalize_guard` uses the v1 widget).
> Host Integration Contract: `_tick_status` mirror +
> `_ensure_overlay("conductivity")` replay; readings routing
> (T-prefix + `/smu*/power`) unchanged from v1 shell contract.
>
> **Known limitations / follow-ups:**
> - Additional export formats (HDF5, Parquet) deferred.
> - Per-chain-pair independent power sweeps deferred.
> - Auto-sweep resume across restart: power list regenerates on
>   each Start — no persistence.
> - ExperimentOverlay v3 (II.9) should wire its finalize guard
>   through `ConductivityPanel.get_auto_state()` instead of
>   reaching into `_auto_state` directly (the v2 shell has no
>   finalize path today — this is forward-compat).

**When to use:**
- ToolRail slot «Теплопроводность» opens this overlay.
- Power-stepping thermal conductivity experiments (primary use case).
- Live R / G monitoring during manual operation (without auto-sweep).

**When NOT to use:**
- Simple temperature monitoring — use the dashboard.
- Non-sequential thermal paths — this overlay assumes a linear chain of sensors with power injected at one end.

## Absolute invariants (from CryoDAQ codebase rules)

1. **Auto-sweep drives Keithley via `SafetyManager`.** Commands go through `keithley_set_target` / `keithley_stop` (via `ZmqCommandWorker`); engine routes these through `SafetyManager.update_target` / `request_stop`. UI does not command hardware directly.
2. **Auto-sweep tick is 1 Hz.** Timer interval is fixed at 1000 ms. Faster ticking would over-sample `SteadyStatePredictor` (which updates every 10 s); slower would delay step advance past the operator's expected cadence.
3. **`SteadyStatePredictor` window is 300 s.** Do not mutate this from the overlay — it's a physics-tuned parameter for typical cryogenic time constants.
4. **Stability threshold (`dT/dt > 0.01 К/мин`)** is the "non-stationary" criterion for the indicator label. Independent of auto-sweep's `percent_settled` threshold.
5. **Flight recorder CSV is always written when chain ≥ 2.** Operators depend on it for post-hoc analysis; skipping rows loses irreplaceable experimental data.
6. **Russian operator-facing text.** Labels / banners / placeholders / dialogs — all Russian.
7. **No emoji** (RULE-COPY-005). **No hardcoded hex colors** outside `PLOT_LINE_PALETTE` indexing.

## Anatomy

```
┌─────────────────────────────────────────────────────────────────────┐
│  ТЕПЛОПРОВОДНОСТЬ                                                    │
│  ( status banner — transient info/caution/fault, auto-clear 4 s )   │
│                                                                       │
│  ┌──Chain card───────────┐ ┌──Live card─────────────────────────┐  │
│  │ Цепочка датчиков       │ │ Steady-state banner                │  │
│  │                        │ │                                     │  │
│  │ ☐ Т1 Криостат верх    │ │ Стабильность: ...   P = ... Вт     │  │
│  │ ☑ Т3 Рад. 1           │ │                                     │  │
│  │ ☑ Т4 Рад. 2           │ │ ┌─ R/G Table (11 cols) ──────────┐ │  │
│  │ ☑ Т5 Экран77          │ │ │ Пара | T гор. | T хол. | dT | R │ │  │
│  │ ...                    │ │ │ ...                             │ │  │
│  │                        │ │ │ ИТОГО                           │ │  │
│  │ Источник P: [▼smua]    │ │ └─────────────────────────────────┘ │  │
│  │ [↑] [↓] [Экспорт CSV]  │ │                                     │  │
│  │                        │ │ ┌─ Plot: temps vs time ─────────┐  │  │
│  │                        │ │ │                                │  │  │
│  │                        │ │ └────────────────────────────────┘  │  │
│  └────────────────────────┘ └─────────────────────────────────────┘  │
│                                                                       │
│  ┌──Auto-sweep card ───────────────────────────────────────────────┐ │
│  │ Автоизмерение                                                   │ │
│  │ Начальная P: [0.001 Вт]   Шаг P: [0.005 Вт]   Шагов: [10]     │ │
│  │ Список мощностей: 0.001, 0.006, ..., 0.046 (10 шагов)          │ │
│  │ Порог стабилизации: [95%]   Мин. ожидание: [30 с]              │ │
│  │ [Старт]  [Стоп]                                                 │ │
│  │ [progress ▓▓▓░░░░░░ 43%]                                         │ │
│  │ Шаг 4/10 — P = 0.016 Вт — 127 с — стабил.: 87%                │ │
│  └─────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Panel root** | Yes | `conductivityPanel` frame, SURFACE_WINDOW background |
| **Header** | Yes | «ТЕПЛОПРОВОДНОСТЬ» title, FONT_SIZE_XL semibold with letter-spacing (RULE-TYPO-005) |
| **Status banner** | Yes | Transient info/caution/fault; auto-clear 4 s. The compatibility method `show_warning()` renders canonical caution and does not create a separate warning rung. |
| **Chain card** | Yes | `chainCard` SURFACE_CARD + BORDER_SUBTLE + RADIUS_MD. Scrollable QCheckBox list of visible T channels, power source QComboBox, reorder ↑/↓ buttons, «Экспорт CSV» |
| **Live card** | Yes | `liveCard` SURFACE_CARD. Steady-state banner + stability/power indicator row + R/G table (11 cols) + pyqtgraph plot with `apply_plot_style()` |
| **R/G table** | Yes | 11 columns: Пара / T гор. / T хол. / dT / R / G / T∞ прогноз / τ (мин) / Готово % / R прогноз / G прогноз. ИТОГО row summarizes first-to-last endpoints. FONT_MONO cells with tabular figures. |
| **Plot** | Yes | pyqtgraph, DateAxisItem bottom axis, FONT_BODY for tick labels via `apply_plot_style`. Pens cycle through `PLOT_LINE_PALETTE` — channel-coded, not quantity-coded. X range = full buffer + 1/3 forecast zone, padded 2%. |
| **Empty state** | Yes | Label overlay: «Нет данных. Выберите датчики и запустите эксперимент.» MUTED_FOREGROUND, anchored over the plot, hidden as soon as the first reading arrives |
| **Auto-sweep card** | Yes | `autoSweepCard`. Power start/step/count spinboxes with preview label, settled% and min-wait spinboxes, Старт/Стоп buttons, progress bar + status label (hidden when idle) |
| **Flight recorder** | Yes (no UI) | 1 Hz CSV write to `get_data_dir()/conductivity_logs/conductivity_<ts>.csv` with 18-column schema, encoding `utf-8-sig`. Closes on `closeEvent`. |

## Invariants

1. **Public guard states are exactly three:** `"idle"`, `"stabilizing"`, and
   `"done"`. `"stabilizing"` is conservative and includes settling,
   command-pending, Stop-pending, and outcome-unknown substates.
2. **Start requires live Engine authority, chain ≥ 2, no active sweep, no
   outcome-unknown latch, and no pending command.**
3. **`auto_sweep_started` means dispatch began, not that the first target was
   acknowledged.** It is emitted after the worker is dispatched and the 1 Hz
   auto timer starts.
4. **Command settlement is generation-bound.** Only the current command token
   from the current connection and operation may settle state. Duplicate,
   superseded, stale-generation, and disconnected replies are ignored.
5. **The 1 Hz auto timer is execution cadence, not authority evidence.** It may
   run while a target reply is pending, but `_auto_tick()` must not advance. It
   is stopped for Stop-pending, completion-pending, outcome-unknown, and panel
   teardown. Therefore `stabilizing` does not imply an active timer.
6. **A step advances only when elapsed time and minimum settling percentage both
   pass, with no pending command, Stop intent, disconnect, or unknown outcome.**
7. **Stop dispatch is not OFF evidence.** Operator Stop and final completion
   retain `"stabilizing"` and block finalization until a successful current
   `keithley_stop` reply commits `"idle"` or `"done"` respectively.
8. **Disconnect or current command failure is fail-visible.** Retain
   `"stabilizing"`, stop automatic advancement, display «ИСХОД НЕИЗВЕСТЕН»,
   and require a new live Stop after reconnect. Reconnect or a late reply never
   clears uncertainty.
9. **`get_auto_state()` / `is_auto_sweep_active()` are conservative finalize
   guards.** `True` does not mean the timer is running or the last outcome is known.
10. **Flight recorder writes every `_refresh` tick when chain ≥ 2**, independent
    of auto-sweep settlement.
11. **`closeEvent` stops owned timers and closes the flight log but does not
    itself claim or publish OFF.**
12. **Plot line color is channel-coded, not quantity-coded.**
13. **The stability indicator threshold remains `0.01 К/мин`.**
14. **Chain order remains position-sensitive:** first is hot, last is cold.
15. **Manual and flight-recorder CSV outputs remain new-file/append-only evidence.**
16. **No emoji and no hardcoded hex colors.**

## API

```python
# src/cryodaq/gui/shell/overlays/conductivity_panel.py

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from cryodaq.drivers.base import Reading


class ConductivityPanel(QWidget):
    """Thermal conductivity overlay (Phase II.5)."""

    auto_sweep_started = Signal()
    auto_sweep_completed = Signal(int)   # number of points recorded
    auto_sweep_aborted = Signal(str)     # reason (e.g. "operator_stop")

    # Public state pushers (called by MainWindowV2)
    def on_reading(self, reading: Reading) -> None: ...
    def set_connected(self, connected: bool) -> None: ...

    # Public state accessors (for ExperimentOverlay finalize guards)
    def get_auto_state(self) -> str: ...          # "idle" | "stabilizing" | "done"
    def is_auto_sweep_active(self) -> bool: ...   # True iff "stabilizing"

    # Banner
    def show_info(self, text: str) -> None: ...
    def show_warning(self, text: str) -> None: ...
    def show_error(self, text: str) -> None: ...
    def clear_message(self) -> None: ...
```

**Host integration contract (`MainWindowV2`):**

- `_tick_status()` mirrors derived `connected: bool` onto `set_connected()`.
- `_ensure_overlay("conductivity")` replays connection state on first construction.
- `_dispatch_reading()` routes T-prefix readings AND `/smu*/power` readings to `on_reading()` via existing contract (unchanged from v1).
- `on_reading()` handles both T readings (updates `_temps` + rolling buffers + predictor) and power readings (updates `_power` if channel matches selected power source).

## Layout rules

- Panel root padding: SPACE_4 horizontal, SPACE_3 vertical. Section spacing: SPACE_3.
- Chain card: SPACE_3 internal padding; SPACE_2 between sections. `QScrollArea` for the checkbox list.
- Live card: SPACE_3 internal padding; SPACE_2 between subsections. Table max height 260 px to leave room for the plot.
- Auto-sweep card: SPACE_3 internal padding; `QGridLayout` for the parameter rows (SPACE_3 horizontal, SPACE_1 vertical).
- Pre-commit gates: forbidden-token grep, emoji scan, and hex-color scan must all be clean before commit (any hex outside `PLOT_LINE_PALETTE` is a RULE-COLOR-010 violation).

## States

| Panel state | Treatment |
|---|---|
| **No data** | Plot shows overlay label «Нет данных. Выберите датчики и запустите эксперимент.» |
| **Chain < 2** | Table empty; steady-state banner empty; auto-sweep Start refuses with an explicit caution message |
| **Chain ≥ 2, not connected** | Auto-sweep Start disabled; chain selection / export still enabled; status banner «Нет связи с engine» |
| **Normal connected, idle** | All controls enabled; 1 Hz refresh drives table + plot + flight log |
| **Target command pending** | Public state remains `stabilizing`; timer may run, but `_auto_tick()` cannot record or advance until the current reply settles |
| **Normal stabilizing** | Start disabled, Stop enabled; timer advances only when elapsed-time and settling gates both pass |
| **Operator Stop awaiting confirmation** | Remains `stabilizing`; timer stopped; both buttons disabled; status explicitly says confirmation is pending |
| **Completion Stop awaiting confirmation** | Remains `stabilizing`; timer stopped; progress held at 99%; completion is not published |
| **Outcome unknown while disconnected** | Remains `stabilizing`; timer and both controls disabled; «ИСХОД НЕИЗВЕСТЕН» remains visible |
| **Outcome unknown after reconnect** | Start remains disabled; Stop becomes available so the operator can request a new authoritative settlement |
| **Stabilization reached (banner)** | «ГОТОВО — стационар достигнут» ACCENT; task progress is not proof of health |
| **95-99% settled** | «Стабилизация N% — ещё ~M мин» ACCENT; settling progress is not a safety state |
| **<95% settled** | «Стабилизация N% — прогноз ~M мин» STATUS_INFO |
| **Confirmed auto-sweep complete** | `_auto_state == "done"` only after the current successful Stop reply; progress 100%; completion dialog summarizes all recorded points |
| **Confirmed operator stop** | `_auto_state == "idle"` only after the current successful Stop reply; status says shutdown was confirmed |

## Common mistakes

1. **Refactoring the physics.** R = dT/P, G = P/dT, R_pred = (T∞_hot - T∞_cold) / P. Verbatim from v1 — don't "simplify" by changing numerator/denominator conventions.
2. **Using MagicMock for `ZmqCommandWorker` or `SteadyStatePredictor` in tests** — these get called across PySide signal boundaries; the interaction is fragile. Use plain-Python stub classes (pattern from II.2 fix).
3. **Writing flight log from outside `_refresh`.** Tick cadence is fixed; additional writes corrupt the 1 Hz sampling contract operators rely on.
4. **Equating `"stabilizing"` with a running timer.** Stop-pending and
   outcome-unknown deliberately retain `"stabilizing"` while the timer is off.
5. **Treating `keithley_stop` dispatch as OFF evidence.** Keep the finalize
   guard active until a successful current-generation SafetyManager reply.
6. **Clearing outcome-unknown on reconnect or a late reply.** Reconnect only
   restores the ability to issue a new Stop; it does not settle prior authority.
7. **Using `apply_group_box_style` / `apply_button_style` /
   `apply_status_label_style`.** These helpers are forbidden; use canonical
   design-system tokens and components.
8. **Hardcoding hex colors.** All pen colors come from
   `PLOT_LINE_PALETTE[i]` via `series_pen(i)`; surfaces/status use tokens.
9. **Reaching into `_auto_state` directly from external code.** Use
   `get_auto_state()` / `is_auto_sweep_active()`.

## Related components

- `cryodaq-primitives/keithley-panel.md` — the Keithley overlay is the peer control surface. Auto-sweep's power commands go to the same engine handlers.
- `cryodaq-primitives/archive-panel.md` — post-experiment CSV / HDF5 / Excel exports are global (not per-experiment); conductivity flight recorder is a separate per-session CSV.
- `components/card.md` — chain / live / auto-sweep cards all use card semantics.
- `components/button.md` — Start (primary), Stop (caution), reorder/export (neutral).

## Changelog

- **2026-07-20 — fail-closed command settlement.** Retained the three public
  guard-state values while adding generation-bound replies, explicit
  outcome-unknown retention, Stop supersession of pending targets, and
  acknowledgment-gated operator Stop/completion.
- **2026-04-19 — Phase II.5 initial version.** Full rewrite from the former v1 conductivity widget. DS v1.0.1 tokens throughout; legacy helpers (`PanelHeader` / `StatusBanner` / `apply_button_style` / `apply_group_box_style` / `apply_status_label_style` / `build_action_row` / `create_panel_root`) purged. Hardcoded `_LINE_COLORS` palette replaced with `PLOT_LINE_PALETTE` via `series_pen`. Auto-sweep FSM preserved verbatim: `idle` / `stabilizing` / `done` states, 1 Hz `QTimer` tick, `SteadyStatePredictor`-driven settling detection, Keithley power stepping via `ZmqCommandWorker`. Flight recorder schema (18 columns, `utf-8-sig`) and path (`get_data_dir() / conductivity_logs / conductivity_<ts>.csv`) preserved. Public accessor `get_auto_state()` / `is_auto_sweep_active()` added for future ExperimentOverlay finalize guard (II.9). Host Integration Contract wired: `_tick_status` mirror + `_ensure_overlay("conductivity")` replay. The superseded widget was removed in the Montana cleanup.
