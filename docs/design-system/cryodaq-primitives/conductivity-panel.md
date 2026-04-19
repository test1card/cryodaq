---
title: ConductivityPanel
keywords: conductivity, thermal, R, G, steady-state, auto-sweep, keithley, power stepping, flight recorder
applies_to: Thermal conductivity overlay (R/G measurement + auto power-sweep + flight recorder)
status: active
implements: src/cryodaq/gui/shell/overlays/conductivity_panel.py (Phase II.5); legacy src/cryodaq/gui/widgets/conductivity_panel.py retained (DEPRECATED) until Phase III.3
last_updated: 2026-04-19
references: rules/data-display-rules.md, rules/interaction-rules.md, components/card.md, components/input-field.md, components/button.md, cryodaq-primitives/keithley-panel.md
---

# ConductivityPanel

Operator overlay for thermal-conductivity measurement by power stepping. Operator selects a chain of temperature sensors along the thermal path, configures a power sweep (start / step / count), starts auto-sweep; the overlay drives the Keithley via `keithley_set_target`, waits for each step to reach a settling threshold per `SteadyStatePredictor.percent_settled`, records R/G and advances to the next power, then calls `keithley_stop` on completion. A flight recorder writes every 1 Hz tick to a CSV for post-hoc analysis.

> **Implementation status (2026-04-19).** The shipped overlay at
> `src/cryodaq/gui/shell/overlays/conductivity_panel.py` matches this
> spec: 3-card layout (chain / live readout + R/G table + plot /
> auto-sweep), DS v1.0.1 tokens exclusively (zero legacy tokens,
> zero emoji, zero hardcoded hex — plot line colors from
> `PLOT_LINE_PALETTE` via `series_pen`), auto-sweep FSM preserved
> verbatim from v1 (idle → stabilizing → done with 1 Hz tick,
> SteadyStatePredictor driving settling detection, Keithley
> `keithley_set_target` / `keithley_stop` via `ZmqCommandWorker`).
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
│  ( status banner — transient info/warning/error, auto-clear 4 s )    │
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
| **Status banner** | Yes | Transient info/warning/error; auto-clear 4 s |
| **Chain card** | Yes | `chainCard` SURFACE_CARD + BORDER_SUBTLE + RADIUS_MD. Scrollable QCheckBox list of visible T channels, power source QComboBox, reorder ↑/↓ buttons, «Экспорт CSV» |
| **Live card** | Yes | `liveCard` SURFACE_CARD. Steady-state banner + stability/power indicator row + R/G table (11 cols) + pyqtgraph plot with `apply_plot_style()` |
| **R/G table** | Yes | 11 columns: Пара / T гор. / T хол. / dT / R / G / T∞ прогноз / τ (мин) / Готово % / R прогноз / G прогноз. ИТОГО row summarizes first-to-last endpoints. FONT_MONO cells with tabular figures. |
| **Plot** | Yes | pyqtgraph, DateAxisItem bottom axis, FONT_BODY for tick labels via `apply_plot_style`. Pens cycle through `PLOT_LINE_PALETTE` — channel-coded, not quantity-coded. X range = full buffer + 1/3 forecast zone, padded 2%. |
| **Empty state** | Yes | Label overlay: «Нет данных. Выберите датчики и запустите эксперимент.» MUTED_FOREGROUND, anchored over the plot, hidden as soon as the first reading arrives |
| **Auto-sweep card** | Yes | `autoSweepCard`. Power start/step/count spinboxes with preview label, settled% and min-wait spinboxes, Старт/Стоп buttons, progress bar + status label (hidden when idle) |
| **Flight recorder** | Yes (no UI) | 1 Hz CSV write to `get_data_dir()/conductivity_logs/conductivity_<ts>.csv` with 18-column schema, encoding `utf-8-sig`. Closes on `closeEvent`. |

## Invariants

1. **Auto-sweep FSM states are exactly three** — `"idle"` / `"stabilizing"` / `"done"`. Transitions: start → `"stabilizing"`, stop → `"idle"`, complete-N-steps → `"done"`. Do not introduce intermediate states — operator confusion.
2. **Auto-sweep Start requires chain ≥ 2.** If shorter, show `QMessageBox.warning` and remain in `"idle"`.
3. **Auto-sweep advance gate.** A step advances only when BOTH: (a) elapsed since step start ≥ `min_wait`, AND (b) `min(percent_settled across chain) ≥ settled%`. Either condition alone is insufficient — prevents false-positive advance during initial transient.
4. **Auto-sweep Stop always sends `keithley_stop`.** Even if no step was in flight. The safety invariant: `keithley_stop` is idempotent on the engine side; sending an extra one is cheaper than leaving power on by mistake.
5. **Flight recorder writes every `_refresh` tick (1 Hz), when chain ≥ 2.** Not gated on auto-sweep state — operators want the log regardless.
6. **`closeEvent` closes the flight log file.** Python's garbage collector is not a guarantee here; explicit close avoids data loss on overlay destruction.
7. **Plot line color is channel-coded, not quantity-coded.** Uses `series_pen(idx)` where `idx` is position in `_plot_items` insertion order. (RULE-COLOR-002.)
8. **Stability threshold is `0.01 К/мин`.** Constant `_STABILITY_THRESHOLD`. Changing it requires a physics discussion with the architect.
9. **`get_auto_state()` / `is_auto_sweep_active()` are the public contract** for external finalize guards. Do not reach into `_auto_state` from outside.
10. **Chain selection is position-sensitive.** First element = hot end, last element = cold end. Reorder buttons (↑/↓) act on the focused checkbox; if nothing is focused (offscreen test case), the call is a no-op.
11. **CSV exports are append-only.** Manual export via dialog produces a new file per invocation; flight recorder produces one file per overlay lifetime.
12. **No emoji, no hardcoded hex.** Pre-commit gates enforce both. Plot palette comes from `PLOT_LINE_PALETTE` indexing.

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
| **Chain < 2** | Table empty; steady-state banner empty; auto-sweep Start refuses with warning |
| **Chain ≥ 2, not connected** | Auto-sweep Start disabled; chain selection / export still enabled; status banner «Нет связи с engine» |
| **Normal connected, idle** | All controls enabled; 1 Hz refresh drives table + plot + flight log |
| **Stabilizing** | Start disabled, Stop enabled; progress bar + status label visible; auto-sweep FSM advances on stability criteria |
| **Stabilization reached (banner)** | «ГОТОВО — стационар достигнут» STATUS_OK |
| **95-99% settled** | «Стабилизация N% — ещё ~M мин» STATUS_WARNING |
| **<95% settled** | «Стабилизация N% — прогноз ~M мин» STATUS_INFO |
| **Auto-sweep complete** | `_auto_state == "done"`; Start re-enabled; progress 100%; completion dialog summarizes all recorded points |
| **Operator stop** | `_auto_state == "idle"`; `keithley_stop` sent; status «Остановлено оператором» |

## Common mistakes

1. **Refactoring the physics.** R = dT/P, G = P/dT, R_pred = (T∞_hot - T∞_cold) / P. Verbatim from v1 — don't "simplify" by changing numerator/denominator conventions.
2. **Using MagicMock for `ZmqCommandWorker` or `SteadyStatePredictor` in tests** — these get called across PySide signal boundaries; the interaction is fragile. Use plain-Python stub classes (pattern from II.2 fix).
3. **Writing flight log from outside `_refresh`.** Tick cadence is fixed; additional writes corrupt the 1 Hz sampling contract operators rely on.
4. **Sending `keithley_set_target` without starting the auto timer.** FSM invariant: stabilizing state implies `_auto_timer.isActive()`. Always start the timer on transition to `"stabilizing"`.
5. **Skipping `keithley_stop` on abort paths.** Stop + complete both must emit it. Leaving power on mid-experiment is a safety violation.
6. **Using `apply_group_box_style` / `apply_button_style` / `apply_status_label_style`** — forbidden. Inline QSS with DS v1.0.1 tokens only.
7. **Hardcoding hex colors.** All pen colors come from `PLOT_LINE_PALETTE[i]` via `series_pen(i)`. Surface / border / status colors come from DS tokens.
8. **Reaching into `_auto_state` directly from external code.** Use `get_auto_state()` / `is_auto_sweep_active()`.

## Related components

- `cryodaq-primitives/keithley-panel.md` — the Keithley overlay is the peer control surface. Auto-sweep's power commands go to the same engine handlers.
- `cryodaq-primitives/archive-panel.md` — post-experiment CSV / HDF5 / Excel exports are global (not per-experiment); conductivity flight recorder is a separate per-session CSV.
- `components/card.md` — chain / live / auto-sweep cards all use card semantics.
- `components/button.md` — Start (primary), Stop (warning), reorder/export (neutral).

## Changelog

- **2026-04-19 — Phase II.5 initial version.** Full rewrite from legacy v1 at `src/cryodaq/gui/widgets/conductivity_panel.py`. DS v1.0.1 tokens throughout; legacy helpers (`PanelHeader` / `StatusBanner` / `apply_button_style` / `apply_group_box_style` / `apply_status_label_style` / `build_action_row` / `create_panel_root`) purged. Hardcoded `_LINE_COLORS` palette replaced with `PLOT_LINE_PALETTE` via `series_pen`. Auto-sweep FSM preserved verbatim: `idle` / `stabilizing` / `done` states, 1 Hz `QTimer` tick, `SteadyStatePredictor`-driven settling detection, Keithley power stepping via `ZmqCommandWorker`. Flight recorder schema (18 columns, `utf-8-sig`) and path (`get_data_dir() / conductivity_logs / conductivity_<ts>.csv`) preserved. Public accessor `get_auto_state()` / `is_auto_sweep_active()` added for future ExperimentOverlay finalize guard (II.9). Host Integration Contract wired: `_tick_status` mirror + `_ensure_overlay("conductivity")` replay. Legacy widget marked DEPRECATED; removal scheduled for Phase III.3.
