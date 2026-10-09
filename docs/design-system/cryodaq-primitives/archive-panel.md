---
title: ArchivePanel
keywords: archive, experiment, history, export, csv, hdf5, xlsx, report, regenerate, k6
applies_to: Experiment archive overlay (historical experiment list + report regeneration + bulk data export)
status: active
implements: src/cryodaq/gui/shell/overlays/archive_panel.py (Phase II.2); legacy src/cryodaq/gui/widgets/archive_panel.py retained (DEPRECATED) until Phase III.3
last_updated: 2026-04-19
references: rules/data-display-rules.md, rules/interaction-rules.md, rules/content-voice-rules.md, components/card.md, components/input-field.md, components/button.md
---

# ArchivePanel

Operator overlay for the experiment archive. Three primary scenarios: find a past experiment, regenerate a report, export raw SQLite data in bulk. Replaces the tab-era v1 widget and absorbs the global CSV / HDF5 / Excel export actions that used to live in the legacy File menu (K6 mandate — `MainWindowV2` has no menu bar).

> **Implementation status (2026-04-19).** The shipped overlay at
> `src/cryodaq/gui/shell/overlays/archive_panel.py` matches this spec:
> filter bar (template / operator / sample / date range / report
> presence / sort + refresh), 9-column list table with FONT_MONO
> timestamps, details pane with summary / metadata / notes / runs /
> artifacts / results + action buttons (folder / PDF / DOCX /
> regenerate), «Экспорт данных» card with CSV / HDF5 / Excel buttons
> backed by `QThread` workers that wrap the existing
> `cryodaq.storage.{csv_export,hdf5_export,xlsx_export}` classes
> (no exporter re-implementation). Emoji pictograms in the legacy
> artifact view replaced with ASCII bracketed tags `[ДАННЫЕ]` /
> `[ИЗМЕРЕНИЯ]` / `[УСТАВКИ]` per RULE-COPY-005. Host Integration
> Contract wired via `_tick_status` + `_ensure_overlay("archive")`
> replay. Legacy v1 widget at `src/cryodaq/gui/widgets/archive_panel.py`
> marked DEPRECATED; removal scheduled for Phase III.3.
>
> **Known limitations / follow-ups:**
> - Per-experiment data export (current export card is global, not
>   per-row). Future filter: start/end date range applied to CSVExporter.
> - Auto-refresh on engine-side experiment-finalize event — no such
>   broker event exists yet, so manual refresh + post-regenerate
>   refresh are the only paths. `on_reading` is a contract no-op.
> - Pagination cursor (currently limit-based refetch).

**When to use:**
- ToolRail slot «Архив» opens this overlay.
- Shift handover: operator wants to re-inspect a prior run.
- Bulk data extraction for external analysis.

**When NOT to use:**
- Live experiment control — that belongs in the ExperimentOverlay.
- Real-time data view — use the dashboard or the per-instrument overlays.
- Per-run export scoped to a specific experiment — not yet a feature; global SQLite export is.

## Absolute invariants (from CryoDAQ codebase rules)

1. **Exporter classes are authoritative.** The overlay's export card wraps the existing `CSVExporter` / `HDF5Exporter` / `XLSXExporter` classes verbatim. No re-implementation, no bypass. Schema and file format are defined by those classes.
2. **Export runs off the GUI thread.** Each export button spawns a `QThread` with an `_ExportWorker`. Operator-visible freeze is forbidden — bulk SQLite exports can take minutes.
3. **Open artifact actions use `QDesktopServices.openUrl`.** Cross-platform, preserves legacy v1 behavior.
4. **`experiment_generate_report` is the only server-side mutation.** All other buttons are local (file open) or read-only (refresh, select).
5. **Russian operator-facing text.** Labels, placeholders, banners — all Russian. Code / docstrings / commits — English.
6. **No emoji.** (RULE-COPY-005.) Artifact roles use ASCII bracketed tags.

## Anatomy

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  АРХИВ ЭКСПЕРИМЕНТОВ                                                          │  ◀── header
│  ( status banner — transient info/warning/error, auto-clear 4 s )             │
│                                                                               │
│  ┌─ Фильтры ──────────────────────────────────────────────────────────────┐ │  ◀── filter bar
│  │  Шаблон: [▼ все]    Оператор: [____]    Образец: [____]                 │ │
│  │  С: [2026-03-19]    По: [2026-04-19]                                    │ │
│  │  Отчёт: [▼все]      Сортировка: [▼сначала новые]       [Обновить]      │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  ┌─ Список (2 cols stretch) ──────┐  ┌─ Сведения (1 col) ──────────────────┐ │
│  │ Начало | Конец | Эксп. | ...    │  │ <title>                              │ │
│  │ ──────────────────────────      │  │ ID: ...                             │ │
│  │ 2026-04-18 09:12  Run 3  ...    │  │ Статус: completed                   │ │
│  │ 2026-04-17 08:05  Run 2  ...    │  │                                      │ │
│  │ ...                              │  │ Шаблон:  Cooldown v2                 │ │
│  │                                  │  │ Оператор: Владимир                   │ │
│  │                                  │  │ Образец:  sample-42                  │ │
│  │                                  │  │ Диапазон: 2026-04-18 09:12 →        │ │
│  │                                  │  │           2026-04-18 15:47          │ │
│  │                                  │  │ Папка:   /data/exp-3                │ │
│  │                                  │  │ Отчёт:   PDF: ... / DOCX: ...       │ │
│  │                                  │  │                                      │ │
│  │                                  │  │ Заметки: <read-only text>            │ │
│  │                                  │  │ Состав:  runs=N, artifacts=M, ...   │ │
│  │                                  │  │ Прогоны: <list>                      │ │
│  │                                  │  │ Артефакты: [ДАННЫЕ] | ...            │ │
│  │                                  │  │ Результаты: ...                      │ │
│  │                                  │  │                                      │ │
│  │                                  │  │ [Папка][PDF][DOCX]  [Перегенерировать] │ │
│  └──────────────────────────────────┘  └──────────────────────────────────────┘ │
│                                                                               │
│  ┌─ Экспорт данных ────────────────────────────────────────────────────────┐ │  ◀── K6 card
│  │  Экспортировать все данные из SQLite (полный временной ряд):              │ │
│  │  [CSV...] [HDF5...] [Excel...]                                             │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Panel root** | Yes | `archivePanel` frame, SURFACE_WINDOW background |
| **Header** | Yes | «АРХИВ ЭКСПЕРИМЕНТОВ» title, FONT_SIZE_XL semibold with letter-spacing (RULE-TYPO-005) |
| **Status banner** | Yes | Transient info/warning/error; auto-clear 4 s |
| **Filter bar card** | Yes | Template combo, operator / sample QLineEdit, start / end QDateEdit, report-presence combo («Все» / «Есть отчёт» / «Нет отчёта»), sort combo, refresh button (accent variant) |
| **List card** | Yes | `listCard` SURFACE_CARD + BORDER_SUBTLE + RADIUS_MD. QTableWidget, 9 columns: Начало, Конец, Эксперимент, Шаблон, Оператор, Образец, Статус, Отчёт, Данные. Row selection single; FONT_MONO on timestamp columns |
| **Empty state label** | Yes | «Эксперименты по текущему фильтру не найдены» MUTED_FOREGROUND centered when table empty |
| **Details card** | Yes | `detailsCard` SURFACE_CARD + BORDER_SUBTLE + RADIUS_MD. Title (summary) + metadata block + notes + stats + runs + artifacts + results + actions |
| **Metadata block** | Yes | Label-value rows: Шаблон / Оператор / Образец / Диапазон / Папка / Отчёт |
| **Notes view** | Yes | Read-only QPlainTextEdit, fixed 72 px height |
| **Runs / Artifacts / Results views** | Yes | Read-only QPlainTextEdit, fixed heights, FONT_BODY |
| **Action row** | Yes | «Папка» / «PDF» / «DOCX» (neutral variant), «Перегенерировать» (primary variant, right-aligned) |
| **Export card** | Yes | `exportCard` SURFACE_CARD + BORDER_SUBTLE + RADIUS_MD. Caption + «CSV...» / «HDF5...» / «Excel...» buttons (neutral variant). Disabled while any export in-flight |

## Invariants

1. **Refresh payload shape matches engine handler.** Keys: `cmd="experiment_archive_list"`, `template_id`, `operator`, `sample`, `start_date`, `end_date`, `sort_by`, `descending`, optional `report_present` ("true" / "false"). Extra keys ignored by the engine; missing keys default to no-filter.
2. **Sort options.** «Сначала новые» → `("start_time", True)`; «Сначала старые» → `("start_time", False)`; «Оператор А-Я» → `("operator", False)`; «Образец А-Я» → `("sample", False)`.
3. **Table sort matches the selected sort combo.** Engine already sorts; overlay renders in received order.
4. **Row selection is atomic.** `_update_details()` updates every metadata / notes / stats / runs / artifacts / results field in a single call before buttons are re-evaluated. No partial-update flicker.
5. **First row auto-selected after refresh.** Operator immediately sees details for the newest entry.
6. **Disconnected state** disables refresh / regenerate / export buttons; folder / PDF / DOCX open actions stay enabled (local filesystem).
7. **Bulk export is always global.** No per-experiment filter. Card caption explicitly says «полный временной ряд».
8. **Export in-flight disables all three export buttons.** One worker at a time — avoids disk contention on the SQLite files.
9. **Export runs on a `QThread`.** `_ExportWorker(QObject)` is `moveToThread`-ed. Failure emits `(kind, 0, error_text)`; success emits `(kind, count, "")`. Banner reflects outcome.
10. **Artifact role formatting uses ASCII bracketed tags.** `[ДАННЫЕ]`, `[ИЗМЕРЕНИЯ]`, `[УСТАВКИ]`. No emoji. (RULE-COPY-005.)
11. **Report / Data column uses «Да» / «—» text marker.** No check-mark glyph (RULE-COPY-005 — check is a status indicator glyph).
12. **Regenerate disabled when `report_enabled=False`.** Shell has no way to know, so overlay gates from the selected entry's field.
13. **Regenerate refreshes the list on result.** PDF / DOCX paths refresh after engine returns; operator gets immediate feedback.
14. **on_reading is a contract no-op.** Archive does not subscribe to broker events (no finalize event exists). Kept for Host Integration Contract symmetry.

## API

```python
# src/cryodaq/gui/shell/overlays/archive_panel.py

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from cryodaq.drivers.base import Reading


class ArchivePanel(QWidget):
    """Experiment archive overlay (Phase II.2)."""

    entry_selected = Signal(dict)               # selected archive entry
    regenerate_requested = Signal(str)          # experiment_id
    export_requested = Signal(str)              # "csv" | "hdf5" | "xlsx"

    # Public state pushers (called by MainWindowV2)
    def on_reading(self, reading: Reading) -> None: ...   # contract no-op
    def set_connected(self, connected: bool) -> None: ...

    # Banner
    def show_info(self, text: str) -> None: ...
    def show_warning(self, text: str) -> None: ...
    def show_error(self, text: str) -> None: ...
    def clear_message(self) -> None: ...
```

**Host integration contract (`MainWindowV2`):**

- `_tick_status()` mirrors derived `connected: bool` onto `set_connected()`.
- `_ensure_overlay("archive")` replays connection state on first construction.
- `on_reading()` is a contract no-op — no auto-refresh wiring.

## Layout rules

- Panel root padding: SPACE_4 horizontal, SPACE_3 vertical. Section spacing: SPACE_3.
- Filter bar card: SPACE_3 horizontal, SPACE_2 vertical internal; SPACE_2 spacing between rows and fields.
- Content split: `QHBoxLayout` with list card stretch=2, details card stretch=1.
- List card: SPACE_2 internal padding; minimal row spacing.
- Details card: SPACE_3 internal padding; SPACE_2 between sections.
- Export card: SPACE_3 horizontal, SPACE_2 vertical internal; SPACE_2 button spacing.

## States

| Panel state | Treatment |
|---|---|
| **Disconnected** | Refresh / regenerate / export disabled; folder / PDF / DOCX stay enabled for cached entries |
| **Connected, empty list** | «Эксперименты по текущему фильтру не найдены» empty-state label shown; details card shows «Эксперимент не выбран.» |
| **Loading** | Previous table content visible; refresh button re-enables on result |
| **Error (refresh failed)** | Status banner shows error text in STATUS_FAULT; table retains previous entries |
| **Normal** | Table populated; first row auto-selected; details panel driven by selection |
| **Regenerate in-flight** | Regenerate button disabled; banner «Генерация отчёта...» STATUS_INFO; refresh still allowed |
| **Export in-flight** | All three export buttons disabled; banner «Экспорт XYZ выполняется в фоне...» STATUS_INFO |
| **Export completed** | Banner «Экспорт XYZ завершён: N записей.» STATUS_INFO; export buttons re-enabled |
| **Export failed** | Banner «Экспорт XYZ: <error>» STATUS_FAULT; export buttons re-enabled |

## Common mistakes

1. **Blocking the GUI thread on export.** Exporter classes are synchronous and can iterate over GB-scale SQLite files. Must offload via `QThread` + `_ExportWorker`.
2. **Re-implementing exporter logic.** Use `CSVExporter` / `HDF5Exporter` / `XLSXExporter` verbatim — schema and file format contracts live there.
3. **Using emoji for role icons in artifact rows.** RULE-COPY-005. Use ASCII tags.
4. **Using ✓ for has-report / has-data markers.** Check glyphs are emoji per RULE-COPY-005. Use Да / —.
5. **Clearing the table on refresh failure.** Preserve prior content + show banner.
6. **Forgetting to gate regenerate on `report_enabled`.** Some templates disable the report pipeline; the overlay must not spawn a worker the engine will immediately refuse.
7. **Emitting `regenerate_requested` without an experiment_id.** Require the selected entry; fallback is a banner error, no signal.
8. **Running multiple exports in parallel.** SQLite file contention. Gate with `_export_in_flight`.
9. **Legacy token usage** (`TEXT_PRIMARY` / `TEXT_DISABLED` / etc.) or legacy helpers (`PanelHeader` / `StatusBanner` / `apply_*_style` / `setup_standard_table` / `add_form_rows`). All forbidden.
10. **Adding export actions as command payloads.** Bulk export runs locally in the GUI process against SQLite directly; no ZMQ round-trip.

## Related components

- `components/card.md` — filter / list / details / export cards all use card semantics.
- `components/input-field.md` — operator / sample / search inputs; date edits.
- `components/button.md` — refresh (accent), regenerate (primary), folder / PDF / DOCX / export (neutral).
- `cryodaq-primitives/experiment-card.md` — experiment overlay reuses the regenerate-report handler; archive complements it with historical view.
- `cryodaq-primitives/operator-log-panel.md` — operator journal as peer shift-handover surface.

## Changelog

- **2026-04-19 — Phase II.2 initial version.** Full rewrite from legacy v1 at `src/cryodaq/gui/widgets/archive_panel.py`. DS v1.0.1 tokens throughout; legacy helpers (`PanelHeader` / `StatusBanner` / `build_action_row` / `create_panel_root` / `setup_standard_table` / `add_form_rows` / `TEXT_DISABLED`) purged. Emoji in artifact roles replaced with ASCII bracketed tags. K6 bulk export migration: CSV / HDF5 / Excel card added with `QThread` workers wrapping existing exporter classes unchanged. Host Integration Contract wired via `MainWindowV2._tick_status` mirror + `_ensure_overlay("archive")` replay; `on_reading` is a contract no-op (no engine finalize event). Legacy widget marked DEPRECATED; removal scheduled for Phase III.3.
