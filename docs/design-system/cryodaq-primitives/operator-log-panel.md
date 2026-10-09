---
title: OperatorLogPanel
keywords: operator, log, journal, shift handover, timeline, composer, filter chips, experiment, tags
applies_to: Operator journal / service log overlay (shift handover + event record)
status: active
implements: src/cryodaq/gui/shell/overlays/operator_log_panel.py (Phase II.3); legacy src/cryodaq/gui/widgets/operator_log_panel.py retained (DEPRECATED) until Phase III.3
last_updated: 2026-04-18
references: rules/data-display-rules.md, rules/interaction-rules.md, rules/copy-rules.md, components/card.md, components/input-field.md, components/button.md, components/badge.md
---

# OperatorLogPanel

Operator journal overlay. Full-featured surface for the shift-handover workflow: read the last 8 hours, skim what happened, file arrival or handover notes. Complements `QuickLogBlock` (dashboard peripheral quick-entry) with search, filtering, composer with tags + experiment binding, and a day-grouped timeline.

> **Implementation status (2026-04-18).** The shipped overlay at
> `src/cryodaq/gui/shell/overlays/operator_log_panel.py` matches this
> spec: composer card (author + tags + message + bind-experiment + save),
> filter bar (quick chips «Все» / «Текущий экспт.» / «Последние 8ч» /
> «За сутки» + text / author / tag search), day-grouped timeline, empty
> state, load-more pagination, DS v1.0.1 tokens throughout. Composer
> author persists via `QSettings("FIAN", "CryoDAQ")` key
> `last_log_author`. Tag normalization reuses
> `cryodaq.core.operator_log.normalize_operator_log_tags`. `MainWindowV2`
> wires `set_connected()` (from `_tick_status` data-flow inference),
> `set_current_experiment()` (from `_on_experiment_status_received`), and
> replays both on lazy overlay open.
>
> **Known limitations / follow-ups:**
> - CSV export of filtered timeline (deferred).
> - Per-entry edit/delete (journal is append-only by design).
> - Server-side pagination cursors (load-more increments client-side
>   `limit` instead; sufficient for operator scales).

**When to use:**
- ToolRail slot «Журнал» (Ctrl+L) — the full operator journal surface.
- Shift handover workflow: reading entries, searching by author/tag/day, writing handover notes.
- Investigation of past incidents by text search.

**When NOT to use:**
- Quick inline note during normal ops — use `QuickLogBlock` on the dashboard instead (one-line composer with minimal UI friction).
- Structured experiment sidecar metadata — use experiment overlay fields instead.
- Real-time sensor annotations — those flow through `analytics/*` broker channels, not the log.

## Absolute invariants (from CryoDAQ codebase rules)

1. **Journal is append-only.** No edit, no delete. The engine `log_entry` handler appends; there is no `log_update` or `log_delete`.
2. **Timestamps come from the server.** GUI never fabricates timestamps; the engine stamps each entry at `writer.append_operator_log()`.
3. **Persistence-first.** Entries persist to SQLite BEFORE publication on `analytics/operator_log_entry`. UI is a read-through surface.
4. **Russian operator-facing text.** Labels, placeholders, banners, captions — all Russian. Code / docstrings / commits — English.

## Anatomy

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ЖУРНАЛ ОПЕРАТОРА                                                             │  ◀── header
│                                                                               │
│  ( status banner — transient info/warning/error, auto-clear 4 s )             │
│                                                                               │
│  ┌─ Новая запись ─────────────────────────────────────────────────────────┐  │
│  │  Автор: [_____________]    Теги: [___________________________]          │  │  ◀── composer card
│  │  ┌──────────────────────────────────────────────────────────────────┐   │  │
│  │  │ Введите запись                                                   │   │  │
│  │  │                                                                  │   │  │
│  │  └──────────────────────────────────────────────────────────────────┘   │  │
│  │  ☑ Привязать к текущему эксперименту                   [ Сохранить ]  │  │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  ┌─ Фильтры ──────────────────────────────────────────────────────────────┐ │
│  │  [Все] [Текущий экспт.] [Последние 8ч] [За сутки]                       │ │  ◀── filter bar
│  │  Поиск: [______________]   Автор: [________]   Тег: [________]          │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  ┌─ История ─────────────────────────────────────────────────────────── ▲ │  │
│  │  ── 2026-04-18 ───────────────────────────────────────────────           │ │  ◀── timeline
│  │  15:42  Владимир                                                          │ │      grouped
│  │         Закрыл азотный клапан, начинаем прогрев.                          │ │      by day
│  │         [experiment: 2026-04-18-cooldown-3]                               │ │
│  │                                                                           │ │
│  │  14:05  system                                                            │ │
│  │         Аларм: Т11 выше порога                                           │ │  (gray,
│  │         [tag: alarm]                                                      │ │   system)
│  │  ── 2026-04-17 ───────────────────────────────────────────────           │ │
│  │  ...                                                                     ▼ │  │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  Загружено: 50 записей · отфильтровано: 23       [Загрузить ещё 50]           │  ◀── footer
└──────────────────────────────────────────────────────────────────────────────┘
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Panel root** | Yes | `operatorLogPanel` frame, SURFACE_WINDOW background |
| **Header** | Yes | «ЖУРНАЛ ОПЕРАТОРА» title in FONT_SIZE_XL semibold with letter-spacing (RULE-TYPO-005) |
| **Status banner** | Yes | Transient info / warning / error; auto-clears after 4 s |
| **Composer card** | Yes | `composerCard` SURFACE_CARD + BORDER_SUBTLE + RADIUS_MD; author / tags / message / bind-experiment / save |
| **Author field** | Yes | `QLineEdit`, persisted via `QSettings("FIAN", "CryoDAQ")` key `last_log_author` |
| **Tags field** | Yes | `QLineEdit` comma-separated; normalized via `normalize_operator_log_tags` |
| **Message edit** | Yes | `QPlainTextEdit` min height 80 px; grows with content |
| **Bind-experiment checkbox** | Yes | Auto-checked when `set_current_experiment(id)` is called with a non-null id; disabled when no active experiment |
| **Save button** | Yes | DS primary variant (STATUS_OK / ON_PRIMARY); disabled when disconnected |
| **Filter bar card** | Yes | `filterBarCard` SURFACE_CARD + BORDER_SUBTLE + RADIUS_MD |
| **Filter chips** | Yes | Mutually exclusive: «Все» / «Текущий экспт.» / «Последние 8ч» / «За сутки». Default «Последние 8ч». Active chip uses `accent` variant |
| **Search fields** | Yes | Text / author / tag `QLineEdit`s — debounced 250 ms; client-side filter on top of loaded entries |
| **Timeline card** | Yes | `timelineCard` scroll area, grouped by calendar day (local TZ) |
| **Day header row** | Yes | Muted-foreground centered «── 2026-04-18 ──» |
| **Entry row** | Yes | Time (FONT_MONO HH:MM tabular figures) + author + message body + chips (experiment / tags) |
| **System-entry styling** | Yes | `author == "system"` rendered with MUTED_FOREGROUND throughout (grayed) |
| **Empty state** | Yes | «Записей нет» centered MUTED_FOREGROUND |
| **Footer** | Yes | Loaded count + filtered count + «Загрузить ещё 50» button |

## Invariants

1. **Composer gate.** Disconnected → submit, message edit, tags edit, author edit all disabled; banner shows «Нет связи с engine» in STATUS_FAULT. Timeline stays readable (stale data is better than no data during operator shift handover).
2. **Save uses `log_entry` command** with payload keys: `cmd`, `message` (required non-empty), `author`, `source="gui"`, `tags` (list), `current_experiment` (bool).
3. **`log_entry` response preserves the stored entry.** Response shape `{"ok": True, "entry": {...}}` — overlay appends to local `_entries_all` optimistically, then reconciles via `refresh_entries()`.
4. **Tag normalization** matches `cryodaq.core.operator_log.normalize_operator_log_tags`: trim, drop empties, preserve order.
5. **Filter chips are mutually exclusive.** Active chip is `accent` variant; inactive chips are `neutral`. Default on overlay open: «Последние 8ч». Re-clicking the active chip does nothing (no toggle-off).
6. **«Текущий экспт.» is server-side.** Sends `current_experiment: true` in `log_get`. Other chips refetch without that flag and apply time cutoff client-side.
7. **Text / author / tag filters are client-side** over the currently loaded `_entries_all`, AND-combined with the active chip's time cutoff.
8. **Timeline sort is newest-first.** Client-side `_sort_entries()` descending on `timestamp` regardless of server sort — defensive.
9. **Day grouping uses local timezone.** Day header format: `YYYY-MM-DD` in operator's local TZ.
10. **System entries are visually muted.** `author == "system"` (case-insensitive) → MUTED_FOREGROUND for time, author label, and message body. Chips use the standard BORDER_SUBTLE border regardless of entry author (chip affordance is structural, not status-coded).
11. **Composer author persists.** On successful save, `QSettings` key `last_log_author` is updated; on next overlay open the field pre-fills.
12. **Load-more is incremental.** Each click adds 50 to `_limit` and re-fetches from server. No pagination cursor.
13. **Refresh failure preserves timeline.** If `log_get` errors, the status banner shows the error but `_entries_all` is NOT cleared — operator keeps context.
14. **`on_reading` triggers refresh only for `analytics/operator_log_entry`.** Other analytics channels are ignored (no crash, no re-fetch).
15. **No emoji** in any overlay string. (RULE-COPY-005.)

## API

```python
# src/cryodaq/gui/shell/overlays/operator_log_panel.py

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget

from cryodaq.drivers.base import Reading


class OperatorLogPanel(QWidget):
    """Full operator journal overlay (Phase II.3)."""

    # Signals (for tests + potential host wiring)
    entry_submitted = Signal(str, str, list, bool)
    # args: (message, author, tags: list[str], bind_to_experiment: bool)

    filter_changed = Signal(str)   # active chip key: "all" | "current" | "last_8h" | "last_24h"
    entries_loaded = Signal(int)   # total count loaded into _entries_all after refresh

    # Public state pushers (called by MainWindowV2)
    def on_reading(self, reading: Reading) -> None: ...
    def set_connected(self, connected: bool) -> None: ...
    def set_current_experiment(self, exp_id: str | None) -> None: ...

    # Banner
    def show_info(self, text: str) -> None: ...
    def show_warning(self, text: str) -> None: ...
    def show_error(self, text: str) -> None: ...
    def clear_message(self) -> None: ...
```

**Host integration contract (`MainWindowV2`):**

- `_tick_status()` mirrors derived `connected: bool` (`< 3s` data silence) onto `set_connected()`.
- `_on_experiment_status_received()` pushes the active experiment id via `set_current_experiment()`.
- `_ensure_overlay("log")` replays cached connection + experiment id on first construction, so the overlay opens with the right state instead of defaults.
- `_dispatch_reading()` already routes any `analytics/*` Reading to `on_reading()` generically — the overlay filters internally on channel name.

## Layout rules

- Panel root padding: SPACE_4 horizontal, SPACE_3 vertical. Section spacing: SPACE_3.
- Composer card internal padding: SPACE_3. Field row spacing: SPACE_2.
- Filter bar card internal padding: SPACE_3 horizontal, SPACE_2 vertical. Chip row spacing: SPACE_1.
- Timeline card internal padding: SPACE_2. Entry row spacing: SPACE_1.
- Entry row internal: SPACE_2 horizontal, SPACE_1 vertical. Time label fixed 52 px wide (FONT_MONO HH:MM alignment across rows).
- Message body indented by 56 px to align under the author column.
- Day header has SPACE_2 top padding, SPACE_1 bottom padding, letter-spacing 1 px.

## States

| Panel state | Treatment |
|---|---|
| **Connected, normal** | Composer enabled; timeline populated; footer shows loaded + filtered counts |
| **Disconnected** | Composer disabled; status banner «Нет связи с engine» STATUS_FAULT; timeline retains stale content |
| **Empty timeline (matching filter)** | «Записей нет» in MUTED_FOREGROUND centered in timeline card |
| **Loading (in-flight `log_get`)** | Timeline shows previous content; composer remains enabled; no blocking modal |
| **Error (`log_get` failed)** | Status banner shows error text; timeline retains previous content |
| **Submit success** | Message cleared; author retained; optimistic prepend of new entry; banner «Запись сохранена» |
| **Submit failure** | Message preserved; banner shows error text; submit re-enabled |
| **Filter chip change** | Triggers `refresh_entries()` with or without `current_experiment: true` flag depending on chip |

## Common mistakes

1. **Using TEXT_PRIMARY / TEXT_SECONDARY legacy tokens.** These are DS-v1.0.1-deprecated aliases. Use FOREGROUND / MUTED_FOREGROUND.
2. **Using `apply_panel_frame_style` / `apply_button_style` / `apply_status_label_style`** from `widgets/common.py`. Legacy pre-DS helpers. Inline QSS with `WA_StyledBackground + #objectName` pattern.
3. **Storing timestamps in GUI state.** GUI never fabricates timestamps; parse server ISO strings via `_parse_entry_timestamp()`.
4. **Blocking the GUI thread on refresh.** Use `ZmqCommandWorker` (QThread); wire its `finished` signal to a result handler. Never call `send_command()` directly from a slot.
5. **Clearing timeline on refresh failure.** Failure = preserve previous content + show banner. Operator still needs context.
6. **Sending empty-message log_entry.** Client-side guard: show warning banner, no signal emitted, no worker spawned.
7. **Filter chip toggle-off.** Re-clicking the active chip should stay on that chip (no implicit deactivation).
8. **System-entry color in STATUS_FAULT.** Auto-generated entries are not errors; use MUTED_FOREGROUND.
9. **Server-side day grouping.** Day boundaries are GUI-local; don't rely on engine pre-grouping.
10. **Hardcoded pixel values.** Use SPACE_* and RADIUS_* tokens; raw pixel literals violate RULE-SPACE-001 / RULE-RADIUS-001.

## Related components

- `components/card.md` — Composer / filter bar / timeline cards use card semantics.
- `components/input-field.md` — Author / tags / search / author-filter / tag-filter lines.
- `components/button.md` — Save (primary), Load-more (neutral), filter chips (accent when active, neutral when inactive).
- `components/badge.md` — Experiment / tag chips alignment target.
- `cryodaq-primitives/quick-log-block.md` — Dashboard peripheral composer; complementary surface.

## Changelog

- **2026-04-18 — Phase II.3 initial version.** Full rewrite from v1 widget at `src/cryodaq/gui/widgets/operator_log_panel.py`. Day-grouped timeline, filter chips (all / current / 8h / 24h), client-side text/author/tag search, composer with tags + experiment binding, DS v1.0.1 tokens, lazy host integration via `MainWindowV2._tick_status` / `_on_experiment_status_received` / `_ensure_overlay("log")` replay. Legacy widget marked DEPRECATED; removal scheduled for Phase III.3.
