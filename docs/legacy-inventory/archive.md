# Legacy Archive Panel Feature Inventory

## File overview
- File: `src/cryodaq/gui/widgets/archive_panel.py`
- Total lines: 529
- Major sections:
  - Lines 1-36: imports
  - Lines 38-46: ArchivePanel init, columns definition
  - Lines 48-191: _build_ui (filters, table, details pane, action buttons)
  - Lines 192-235: refresh_archive (ZMQ query with filters)
  - Lines 236-248: _reload_template_choices
  - Lines 249-340: _populate_table, _selected_entry, _update_details
  - Lines 341-460: _clear_details, formatters (runs, artifacts, results), path resolvers
  - Lines 462-529: open folder/PDF/DOCX actions, regenerate report

## Layout structure

```
ArchivePanel: QVBoxLayout
  PanelHeader: "Архив экспериментов"
  
  Filters: QGridLayout (3 rows)
    Row 0: [Шаблон: QComboBox] [Оператор: QLineEdit] [Образец: QLineEdit]
    Row 1: [С: QDateEdit] [По: QDateEdit] [Отчёт: QComboBox (Все/Есть/Нет)]
    Row 2: [Сортировка: QComboBox (4 options)] [Обновить QPushButton]
  
  Body: QHBoxLayout
    Left (2/3): QTableWidget
      Columns: Начало | Конец | Эксперимент | Шаблон | Оператор | Образец | Статус | Отчёт | Данные
      Click row → details pane updates
    
    Right (1/3): QGroupBox "Сведения"
      Summary label
      Form: Шаблон / Оператор / Образец / Диапазон / Папка артефактов / Файлы отчёта
      Notes: QTextEdit (read-only, 120px)
      Runs: QGroupBox "Прогоны" → QTextEdit (read-only, 110px)
      Artifacts: QGroupBox "Артефакты" → QTextEdit (read-only, 130px)
      Results: QGroupBox "Результаты" → QTextEdit (read-only, 110px)
      Action row: [Открыть папку] [Открыть PDF] [Открыть DOCX] [Перегенерировать отчёты]
      StatusBanner
```

## ZMQ commands used

| Command | Payload | Trigger |
|---------|---------|---------|
| `experiment_archive_list` | `{cmd, template_id, operator, sample, start_date, end_date, sort_by, descending, report_present?}` | Обновить button + init |
| `experiment_generate_report` | `{cmd, experiment_id}` | Перегенерировать отчёты button |

## Filter capabilities
- Template: dropdown (populated from archive entries)
- Operator: free text search
- Sample: free text search
- Date range: QDateEdit start/end (default last 30 days)
- Report presence: Все / Есть отчёт / Нет отчёта
- Sort: Сначала новые / Сначала старые / Оператор А-Я / Образец А-Я

## Operator workflows

1. **Find past experiment** — set filters, click Обновить, browse table
2. **View experiment details** — click row, details pane shows metadata + notes + runs
3. **Open report** — click Открыть PDF or Открыть DOCX (opens with system viewer)
4. **Open artifact folder** — click Открыть папку (opens in file manager)
5. **Regenerate report** — click Перегенерировать, backend re-runs report pipeline

## Comparison: legacy vs new

| Feature | Legacy | New | Status |
|---------|--------|-----|--------|
| Experiment list table | Full filterable table | Not in dashboard | ✗ NOT COVERED |
| Multi-field filters | 6 filter criteria | Not available | ✗ NOT COVERED |
| Detail pane | Metadata + notes + runs + artifacts | Not available | ✗ NOT COVERED |
| Open PDF/DOCX | Desktop file open | Not available | ✗ NOT COVERED |
| Open artifact folder | Desktop folder open | Not available | ✗ NOT COVERED |
| Regenerate report | Backend re-run | Not available | ✗ NOT COVERED |

## Recommendations for Phase II overlay rebuild

**MUST preserve (K2 — archive of completed experiments):**
- Full experiment archive table with all columns
- Multi-field filter system (template, operator, sample, date range, report presence)
- Sort options (date, operator, sample)
- Detail pane with metadata, notes, runs, artifacts, results sections
- Open PDF / DOCX via system viewer (K6 partial)
- Open artifact folder
- Report regeneration capability

**COULD defer:**
- Template dropdown auto-population from archive entries
- Results section formatting (complex metadata rendering)

**SHOULD cut:**
- Hardcoded QGroupBox styling (use theme tokens)
- 5 separate QGroupBox sections in details (consolidate to simpler layout)
