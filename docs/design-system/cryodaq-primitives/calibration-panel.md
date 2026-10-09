---
title: CalibrationPanel
keywords: calibration, krdg, srdg, calibration curves, cooldown calibration, three-mode, setup, acquisition, results, chebyshev fit
applies_to: Three-mode sensor calibration overlay (Setup → Acquisition → Results)
status: active
implements: src/cryodaq/gui/shell/overlays/calibration_panel.py (Phase II.7); legacy src/cryodaq/gui/widgets/calibration_panel.py retained (DEPRECATED) until Phase III.3
last_updated: 2026-04-19
references: rules/data-display-rules.md, rules/interaction-rules.md, components/card.md, components/input-field.md, components/button.md
---

# CalibrationPanel

K3-critical overlay for calibrating temperature sensors against a reference probe via a cooldown cycle. Three modes — Setup / Acquisition / Results — switch automatically based on `calibration_acquisition_status` polled every 3 s. Calibrations run 1-2 times per year but affect every subsequent measurement; the button wiring (import / export / runtime-apply) is as operationally important as the visual rebuild.

> **Implementation status (2026-04-19).** The shipped overlay at
> `src/cryodaq/gui/shell/overlays/calibration_panel.py` matches this
> spec: three-mode QStackedWidget preserved verbatim (Setup /
> Acquisition / Results), 3 s engine-poll mode auto-switch
> (`calibration_acquisition_status`) preserved, CoverageBar migrated
> from hardcoded hex (`#2ECC40` / `#FFDC00` / `#FF851B` / `#333333`)
> to DS tokens (STATUS_OK / STATUS_CAUTION / STATUS_WARNING /
> MUTED_FOREGROUND). All six import / export / runtime-apply buttons
> now dispatch real engine commands via `ZmqCommandWorker`:
> `calibration_curve_import` (with file dialog), `calibration_curve_export`
> (with file dialog + format-specific path parameter), 
> `calibration_runtime_set_global`,
> `calibration_runtime_set_channel_policy` (with `calibration_curve_lookup`
> bridge step to resolve `curve_id`). Acquisition widget's
> `_experiment_label` + `_elapsed_label` are now populated from poll
> result (v1 declared them but never wrote). DS v1.0.1 tokens
> exclusively — zero legacy tokens, zero emoji, zero hardcoded hex.
> Host Integration Contract wired: `_tick_status` mirror +
> `_ensure_overlay("calibration")` replay; readings routing preserved
> from v1 (shell dispatches unit=="K" to panel; panel filters for
> `_raw` / `sensor_unit` in acquisition mode).
>
> **Known limitations / follow-ups:**
> - Δ before/after label in Apply card — empty placeholder,
>   Phase III polish.
> - Scatter plot of calibration points against the fit — v1 never
>   had this; deferred.
> - Manual curve-to-channel assignment UI (engine command exists,
>   no GUI surface yet) — deferred.

**When to use:**
- ToolRail slot «Калибровка» opens this overlay.
- 1-2× per year: fresh calibration run after hardware changes.
- Ad-hoc: importing a vendor curve, applying runtime policy per channel.

**When NOT to use:**
- Real-time temperature monitoring — use the dashboard.
- Reviewing historical experiments — use ArchiveOverlay.
- SMU calibration — different domain entirely (Keithley self-cal).

## Absolute invariants (from CryoDAQ codebase rules)

1. **Auto-switch logic preserved verbatim.** Setup → Acquisition when engine reports `active: True`; Acquisition → Results when engine reports `active: False` after the widget was in acquisition mode. Any other transition keeps the current mode. Changing this breaks operator muscle memory.
2. **3 s poll cadence preserved.** Faster polls stress the engine REP handler; slower polls make the transition feel laggy. 3 s is the established number — do not tune here.
3. **Reference channel auto-excluded from targets** at engine-side `experiment_start`. Do not filter visually in the target checkboxes — v1 semantic preserved (all checkboxes default-on, reference is excluded at submit time via `get_selected_targets` comparison).
4. **`calibration_curve_export` is eager.** The engine writes all four formats (`.330`, `.340`, `.json`, `.csv`) in one call. Per-button UX uses the single format-specific path parameter (`curve_330_path`, `curve_340_path`, `json_path`, `table_path`) to control where that format lands; the other three go to engine defaults. Do not attempt to split into four command variants.
5. **Russian operator-facing text.** Labels, banners, dialogs — all Russian.
6. **No emoji** (RULE-COPY-005). **No hardcoded hex** outside `PLOT_LINE_PALETTE` indexing (CoverageBar uses STATUS_* tokens).

## Anatomy

```
┌─────────────────────────────────────────────────────────────────────┐
│  КАЛИБРОВКА ДАТЧИКОВ                                                 │
│  ( status banner — transient info/warning/error, auto-clear 4 s )    │
│  ┌─ QStackedWidget (one of three modes) ────────────────────────┐  │
│  │                                                                │  │
│  │  ─── SETUP ─────────────────────────────────────────────       │  │
│  │  ┌─ Параметры калибровки ───────────────────────────┐         │  │
│  │  │ Опорный канал: [▼ LS218_1:Т1]                    │         │  │
│  │  │ [LS218_1 group] [☑Т1] [☑Т2] [☑Т3]...             │         │  │
│  │  │ ...                                                │         │  │
│  │  │ Опорный канал автоматически исключается...        │         │  │
│  │  │ [Начать калибровочный прогон]                     │         │  │
│  │  └────────────────────────────────────────────────────┘         │  │
│  │  ┌─ Импорт внешней кривой ──────────────────────────┐         │  │
│  │  │ [Импорт .330] [Импорт .340] [Импорт JSON]         │         │  │
│  │  └────────────────────────────────────────────────────┘         │  │
│  │  ┌─ Существующие кривые ────────────────────────────┐         │  │
│  │  │ Датчик | Curve ID | Зон | RMSE | Источник         │         │  │
│  │  └────────────────────────────────────────────────────┘         │  │
│  │                                                                │  │
│  │  ─── ACQUISITION ───────────────────────────────────────       │  │
│  │  ┌─ Сбор данных — активен ──────────────────────────┐         │  │
│  │  │ Эксперимент: Calibration-2026-04-19               │         │  │
│  │  │ Время: HH:MM:SS                                    │         │  │
│  │  │ Точек записано: N                                  │         │  │
│  │  │ Диапазон T_ref: min — max K                        │         │  │
│  │  └────────────────────────────────────────────────────┘         │  │
│  │  ┌─ Покрытие по температуре ────────────────────────┐         │  │
│  │  │ [▓▓▓▒▒░░░__________________]                       │         │  │
│  │  │ dense   medium   sparse   empty                    │         │  │
│  │  └────────────────────────────────────────────────────┘         │  │
│  │  ┌─ Последние значения ─────────────────────────────┐         │  │
│  │  │ Т1_raw: 1234.5                                     │         │  │
│  │  │ Т2_raw: 2345.6                                     │         │  │
│  │  └────────────────────────────────────────────────────┘         │  │
│  │  Запись идёт автоматически. Дождитесь cooldown...             │  │
│  │                                                                │  │
│  │  ─── RESULTS ───────────────────────────────────────────       │  │
│  │  ┌─ Канал: [▼ Т1] ───────────────────────────────────┐         │  │
│  │  └────────────────────────────────────────────────────┘         │  │
│  │  ┌─ Метрики подгонки ───────────────────────────────┐         │  │
│  │  │ Raw пар / После downsample / Breakpoints /         │         │  │
│  │  │ Зон Chebyshev / RMSE / Max ошибка                  │         │  │
│  │  └────────────────────────────────────────────────────┘         │  │
│  │  ┌─ Экспорт кривой ─────────────────────────────────┐         │  │
│  │  │ [.330] [.340] [JSON] [CSV]                         │         │  │
│  │  └────────────────────────────────────────────────────┘         │  │
│  │  ┌─ Применить в CryoDAQ ────────────────────────────┐         │  │
│  │  │ ☐ SRDG + calibration curves (глобально)           │         │  │
│  │  │ Политика канала: [▼ Наследовать]                   │         │  │
│  │  │ [Применить]                                         │         │  │
│  │  └────────────────────────────────────────────────────┘         │  │
│  └────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Panel root** | Yes | `calibrationPanel` frame, SURFACE_WINDOW background |
| **Header** | Yes | «КАЛИБРОВКА ДАТЧИКОВ» title, FONT_SIZE_XL semibold with letter-spacing (RULE-TYPO-005) |
| **Status banner** | Yes | Transient info / warning / error; auto-clear 4 s |
| **QStackedWidget** | Yes | Three child widgets. Mode poll (3 s) via `ZmqCommandWorker` with in-flight guard, started/stopped by `set_connected`. |
| **Setup: Params card** | Yes | Reference channel combo (LakeShore channels grouped `<instrument>:<channel>`), target QCheckBox groups per instrument, start button (primary). |
| **Setup: Import card** | Yes | Three buttons (`Импорт .330` / `.340` / `JSON`) each wired via `QFileDialog.getOpenFileName` → `calibration_curve_import`. |
| **Setup: Curves card** | Yes | 5-column QTableWidget (Датчик / Curve ID / Зон / RMSE / Источник) populated from `calibration_curve_list` on connect + after any import success. |
| **Acquisition: Stats card** | Yes | Эксперимент / Время (HH:MM:SS) / Точек / Диапазон T_ref. Values from poll result. |
| **Acquisition: Coverage card** | Yes | `CoverageBar` widget paints one segment per bin using STATUS_* tokens. |
| **Acquisition: Live card** | Yes | Read-only QPlainTextEdit with last 5 `_raw` / `sensor_unit` readings, FONT_MONO tabular figures. |
| **Results: Channel selector** | Yes | ComboBox populated from last acquisition's `target_channels` (or `calibration_curve_list` on fresh launch). |
| **Results: Metrics card** | Yes | 6-row form: Raw пар / После downsample / Breakpoints / Зон Chebyshev / RMSE / Max ошибка. Updates on selector change via `calibration_curve_get`. |
| **Results: Export card** | Yes | Four buttons (`.330` / `.340` / `JSON` / `CSV`) each wired via `QFileDialog.getSaveFileName` → `calibration_curve_export` with format-specific path param. |
| **Results: Apply card** | Yes | Global checkbox + channel-policy combo (Наследовать / Включить / Выключить) + Применить button. Dispatches `calibration_runtime_set_global` (if checkbox toggled) then `calibration_curve_lookup` → `calibration_runtime_set_channel_policy` chain. |

## Invariants

1. **Auto-switch FSM** — exactly three modes, transitions driven solely by engine poll. No manual mode buttons (operator flow is linear).
2. **Mode poll runs only when connected.** `set_connected(True)` starts the 3 s timer; `set_connected(False)` stops it. Prevents ZmqCommandWorker spawns that will fail before MainWindowV2 confirms engine reachable.
3. **Curves list refresh triggers.** On first `set_connected(True)` after construction + after any successful `calibration_curve_import`. Not on every mode transition (wasteful).
4. **Import flow.** Click → `QFileDialog.getOpenFileName` with format-specific filter → `ZmqCommandWorker({"cmd": "calibration_curve_import", "path": ...})` → banner + refresh. Cancel (empty path) is a no-op; no worker spawned.
5. **Export flow.** Click → `QFileDialog.getSaveFileName` with format filter → `ZmqCommandWorker({"cmd": "calibration_curve_export", "sensor_id": ..., <format>_path: ...})` → banner. Engine writes all four formats per call; only the clicked format's path is operator-specified. No channel selected → error banner, no dialog.
6. **Apply flow.** If global checkbox toggled: `calibration_runtime_set_global` first; on success, dispatch `calibration_curve_lookup` to resolve `curve_id` → `calibration_runtime_set_channel_policy` with `{channel_key, policy, sensor_id, curve_id}`. If global unchecked: skip straight to the lookup → policy chain. No channel selected → error banner.
7. **CoverageBar token-coded.** Status strings (`dense` / `medium` / `sparse` / `empty`) map 1:1 to `STATUS_OK` / `STATUS_CAUTION` / `STATUS_WARNING` / `MUTED_FOREGROUND`. RULE-COLOR-010 compliance verified by pre-commit hex grep.
8. **Reference auto-exclusion.** `_SetupWidget.get_selected_targets()` excludes the reference channel at the Python level before the `experiment_start` dispatch; engine receives only true target channels in `custom_fields.target_channels`.
9. **Readings filter.** `on_reading()` in acquisition mode only routes channels ending with `_raw` OR `unit == "sensor_unit"`. Regular `K` readings are ignored even though the shell dispatcher sends them through.
10. **No emoji, no hardcoded hex.** Pre-commit gates enforce.

## API

```python
# src/cryodaq/gui/shell/overlays/calibration_panel.py

from PySide6.QtWidgets import QWidget

from cryodaq.drivers.base import Reading


class CalibrationPanel(QWidget):
    """Three-mode calibration overlay (Phase II.7)."""

    # Public state pushers
    def on_reading(self, reading: Reading) -> None: ...
    def set_connected(self, connected: bool) -> None: ...

    # Public state accessors (for host tests / future finalize guard)
    def get_current_mode(self) -> str: ...  # "setup" | "acquisition" | "results"
    def is_acquisition_active(self) -> bool: ...

    # Banner
    def show_info(self, text: str) -> None: ...
    def show_warning(self, text: str) -> None: ...
    def show_error(self, text: str) -> None: ...
    def clear_message(self) -> None: ...
```

**Host integration contract (`MainWindowV2`):**

- `_tick_status()` mirrors derived `connected: bool` onto `set_connected()`.
- `_ensure_overlay("calibration")` replays connection state on first construction.
- `_dispatch_reading()` forwards any `unit == "K"` reading to `on_reading()` (unchanged from v1 shell contract). The overlay internally filters for acquisition mode + `_raw` / `sensor_unit` suffix.

## Engine command surface

All commands fire via `ZmqCommandWorker`. The overlay never calls engine / analytics code directly.

| Command | Trigger | Payload keys | Response |
|---|---|---|---|
| `calibration_acquisition_status` | 3 s poll (when connected) | — | `{ok, active, point_count?, t_min?, t_max?, experiment_name?, elapsed_s?, coverage_bins?, target_channels?}` |
| `experiment_start` | Setup Старт click | `template_id="calibration"`, `name`, `title`, `operator`, `custom_fields.{reference_channel, target_channels}` | `{ok, experiment_id}` |
| `calibration_curve_list` | Connect + after import success | — | `{ok, curves, assignments}` |
| `calibration_curve_get` | Results channel-selector change | `sensor_id` | `{ok, curve}` |
| `calibration_curve_lookup` | Apply button (channel-policy bridge) | `channel_key` | `{ok, assignment: {curve_id, ...}}` |
| `calibration_curve_import` | Import button click (after file dialog) | `path` | `{ok, curve, artifacts, assignment}` |
| `calibration_curve_export` | Export button click (after file dialog) | `sensor_id`, `<format>_path` (one of `curve_330_path` / `curve_340_path` / `json_path` / `table_path`) | `{ok, json_path, table_path, curve_330_path, curve_340_path}` |
| `calibration_runtime_set_global` | Apply with checkbox toggled | `global_mode`: `"on"` / `"off"` | `{ok, runtime}` |
| `calibration_runtime_set_channel_policy` | Apply second step | `channel_key`, `policy`, `sensor_id`, `curve_id` | `{ok, ...}` |

## Layout rules

- Panel root padding: SPACE_4 horizontal, SPACE_3 vertical. Section spacing: SPACE_3.
- Each mode's root: zero outer padding, SPACE_3 spacing between cards — `QStackedWidget` content fills the panel.
- Card internal padding: SPACE_3. Form row spacing: SPACE_1 vertical, SPACE_3 horizontal.
- CoverageBar: fixed 24 px height. Legend label immediately below.

## States

| Panel state | Treatment |
|---|---|
| **Disconnected** | Setup Start / Import / Export / Apply buttons disabled; mode poll suspended; banner «Нет связи с engine» |
| **Connected, Setup** | All Setup controls enabled; curves table populated from `calibration_curve_list` |
| **Connected, Acquisition** | Stats + coverage auto-update via 3 s poll; live-reading feed (last 5); Setup / Results not visible |
| **Connected, Results** | Channel selector populated; metrics update on selection change; Export + Apply enabled |
| **Import success** | Banner «Кривая импортирована: <curve_id>»; curves table refreshed |
| **Import failure** | Banner error text from engine; no table mutation |
| **Export success** | Banner «Экспорт <format> → <path>» (dispatched before engine confirms; actual ok/error flows via a deferred banner check) |
| **Export failure** | Banner error text from engine |
| **Apply success** | Banner «Политика канала применена.» |
| **Apply failure** | Banner with engine error at the failing step (global or channel policy) |

## Common mistakes

1. **Wiring buttons at the widget level, not via engine commands.** The whole point of II.7 is that v1 created the buttons but never connected them. Every button must dispatch a `ZmqCommandWorker`.
2. **Reimplementing calibration math in GUI.** `CalibrationStore` + `CalibrationFitter` live in `analytics/`. The overlay is a thin engine-command dispatcher; no Python-level calibration logic.
3. **Polling in setup mode.** Mode poll runs continuously while connected — not only in acquisition. That's how Setup → Acquisition transitions at all. Gating poll on mode would break the flow.
4. **Filtering readings by `K` unit.** The overlay only wants `_raw` / `sensor_unit` readings in the live area; regular K readings are noise here. The shell dispatcher's `unit=="K"` gate is a superset; the overlay narrows internally.
5. **Hardcoded hex in CoverageBar.** Legacy v1 shipped `#2ECC40` / `#FFDC00` / `#FF851B` / `#333333`. II.7 migrated to `theme.STATUS_OK` / `STATUS_CAUTION` / `STATUS_WARNING` / `MUTED_FOREGROUND`. Pre-commit hex grep guards against regression.
6. **Ignoring no-channel error paths.** Export and Apply BOTH require a selected channel. Click with empty `_current_sensor_id` → error banner, no command dispatched.
7. **Forgetting the reference auto-exclusion.** Target checkboxes are default-all-on and visually include the reference. Exclusion happens at submit time in `get_selected_targets`. V1 operator muscle memory assumes this; UI-level filtering would confuse.

## Related components

- `cryodaq-primitives/archive-panel.md` — archive shows completed calibration experiments post-finalize.
- `cryodaq-primitives/conductivity-panel.md` — peer K3-critical overlay with auto-sweep FSM; calibration has auto-switch FSM (different pattern, same spirit).
- `components/card.md` — every section uses card semantics.
- `components/button.md` — primary (Старт / Применить) / neutral (Import / Export / close). No destructive variant here.

## Changelog

- **2026-04-19 — Phase II.7 initial version.** Full rewrite from legacy v1 at `src/cryodaq/gui/widgets/calibration_panel.py`. DS v1.0.1 tokens throughout; legacy helpers (`PanelHeader` / `StatusBanner` / `apply_button_style` / `apply_group_box_style` / `create_panel_root` / `setup_standard_table`) purged. CoverageBar hardcoded hex palette replaced with DS status tokens. Three-mode QStackedWidget + 3 s engine poll + auto-switch logic preserved verbatim. **K3 mandate completed:** all six import / export / runtime-apply buttons now dispatch real engine commands (`calibration_curve_import`, `calibration_curve_export`, `calibration_runtime_set_global`, `calibration_runtime_set_channel_policy` with `calibration_curve_lookup` bridge). Acquisition widget's `_experiment_label` / `_elapsed_label` populated from poll result (v1 declared them but never wrote). Public accessors `get_current_mode()` / `is_acquisition_active()` added for future finalize guards. Host Integration Contract wired: `_tick_status` mirror + `_ensure_overlay("calibration")` replay. Legacy widget marked DEPRECATED; removal scheduled for Phase III.3.
