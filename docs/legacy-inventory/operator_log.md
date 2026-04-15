# Legacy Operator Log Panel Feature Inventory

## File overview
- File: `src/cryodaq/gui/widgets/operator_log_panel.py`
- Total lines: 171
- Major sections:
  - Lines 1-27: imports
  - Lines 29-78: __init__ + _build_ui (header, controls, message area, entries list)
  - Lines 81-84: on_reading (live update trigger)
  - Lines 86-119: refresh_entries (log_get ZMQ + list population)
  - Lines 121-153: _on_submit (log_entry ZMQ + author persistence)
  - Lines 155-171: _format_entry (timestamp + author + experiment_id + tags)

## Layout structure

```
OperatorLogPanel: QVBoxLayout
  PanelHeader: "Служебный журнал"
    subtitle: "Вторичный технический лог..."
  
  Controls row: HBox
    [Автор: QLineEdit (max 220px, persisted via QSettings)]
    [QCheckBox "Только текущий эксперимент"]
    [QPushButton "Обновить список"]
  
  Message area:
    QPlainTextEdit (120px height, placeholder "Введите операторскую запись")
  
  Action row: HBox
    [QPushButton "Сохранить запись"]
    [StatusBanner]
  
  Entries list: QListWidget (stretch=1)
    Each item: "[YYYY-MM-DD HH:MM:SS] author (experiment_id): message [tags]"
    System entries: grayed out (TEXT_DISABLED)
```

## Input fields / controls

| Control | Type | Label | Default | Validation | Persistence |
|---------|------|-------|---------|------------|-------------|
| Автор | QLineEdit | "Автор:" | QSettings "last_log_author" | None | QSettings save on submit |
| Только текущий эксперимент | QCheckBox | — | unchecked | — | — |
| Обновить список | QPushButton | — | — | — | — |
| Текст записи | QPlainTextEdit | — | empty | non-empty on submit | — |
| Сохранить запись | QPushButton | — | — | message non-empty | — |

## ZMQ commands used

| Command | Payload | Trigger |
|---------|---------|---------|
| `log_get` | `{cmd, limit: 50, current_experiment?: bool}` | Обновить + on_reading trigger + post-submit |
| `log_entry` | `{cmd, message: str, author: str, source: "gui", current_experiment?: bool}` | Сохранить запись click |

## Live data subscriptions

- `analytics/operator_log_entry` → triggers `refresh_entries()` (auto-refresh on new entries)

## Persistence

- QSettings key `"last_log_author"` — saved on successful submit, restored on init
- No other persistence — entries list reloaded from backend on each refresh

## Entry format

```
[2026-04-15 17:42:13] Vladimir (exp_2026_04_15_001): Заметка оператора [tag1, tag2]
```
- Timestamp: ISO → formatted `%Y-%m-%d %H:%M:%S`
- Author: from entry dict, falls back to source, then "system"
- Experiment ID: shown if present
- Tags: shown in brackets if present
- System entries: rendered with TEXT_DISABLED color (grayed out)

## Operator workflows

1. **Write a note** — type in message area, click Сохранить → saved to SQLite via engine
2. **Review recent entries** — scroll through QListWidget, last 50 entries
3. **Filter by experiment** — check "Только текущий эксперимент" → refresh → see only experiment-scoped entries
4. **Verify system events** — system-authored entries (grayed) show automatic events

## Comparison: legacy vs new

| Feature | Legacy Operator Log | New Surfaces | Status |
|---------|-------------------|--------------|--------|
| Quick note entry | QPlainTextEdit (120px) | QuickLogBlock composer (24px, single line) | ⚠ PARTIAL (dashboard = quick, this = detailed) |
| Entry list (50 entries) | Full QListWidget | QuickLogBlock (2 entries) | ⚠ PARTIAL |
| Filter by experiment | QCheckBox toggle | ExperimentOverlay ХРОНИКА column (auto-filtered) | ✓ COVERED |
| Author field | QLineEdit with QSettings | Not in dashboard (uses "dashboard" source) | ✗ NOT COVERED |
| Tags display | Shown in brackets | Not shown | ✗ NOT COVERED |
| Multi-line message | QPlainTextEdit | QLineEdit (single line) | ⚠ PARTIAL |
| System entries styling | Grayed out | Not distinguished | ✗ NOT COVERED |
| Live refresh | on analytics/operator_log_entry | QuickLogBlock 10s poll | ✓ COVERED |

## Recommendations for Phase II overlay rebuild

**MUST preserve (K1 — service log with chronology):**
- Full entry list with scrolling (50+ entries visible at once)
- Author field with QSettings persistence
- Filter by current experiment toggle
- Multi-line message input area (120px, not single-line)
- Formatted entries: timestamp + author + experiment_id + tags
- System vs operator entry visual distinction (grayed system entries)
- Live refresh on new entry arrival

**COULD defer:**
- Entry search by keyword (not in current panel, would be new feature)
- Entry editing/deletion (not supported currently)
- Export entries to file (not in current panel)

**SHOULD cut:**
- PanelHeader subtitle ("Вторичный технический лог...") — confusing, suggests it's secondary
- Fixed max 50 entries limit — could be configurable or paginated

This panel is simple but K1-critical (operators rely on it for shift
handover notes). The new dashboard QuickLogBlock covers only quick
note entry (2 entries visible). Full Operator Log overlay must provide
the complete reading + writing experience. Difference from ХРОНИКА
in ExperimentOverlay: ХРОНИКА is filtered by current experiment,
OperatorLog shows ALL entries across experiments.
