---
title: QuickLogBlock
keywords: log, operator-log, journal, inline, dashboard, tile, entry, note
applies_to: inline log entry composition + recent-entries display
status: proposed
implements: legacy OperatorLogPanel exists; compact inline block pending
last_updated: 2026-04-17
references: rules/interaction-rules.md, rules/typography-rules.md, rules/content-voice-rules.md
---

# QuickLogBlock

Compact inline operator-log widget. Two halves:
1. **Input row** — operator types a note, presses Enter or clicks «Записать».
2. **Recent entries** — last N entries (3-5) displayed below, timestamped.

For full log navigation, the Journal panel (ToolRail slot) provides search/filter/export.

**When to use:**
- Dashboard BentoTile — operator can quickly log an observation without leaving overview
- Inside experiment overlay — log entries tied to current experiment context
- Any place where operator's own observations are valuable alongside auto-logged events

**When NOT to use:**
- Full log browsing — use Operator Log panel (`/Ctrl+L`)
- Auto-generated system events — those use `event_logger.py` directly, not this widget
- Commit messages / rich formatting — out of scope for operator quick-log

## Anatomy

```
┌──────────────────────────────────────────────────────────────────────┐
│  ◀── BentoTile frame (RADIUS_MD, CARD_PADDING, SURFACE_CARD)        │
│                                                                      │
│  ЖУРНАЛ ОПЕРАТОРА                                     [ 📓 Открыть ] │
│                                                                      │
│  ┌────────────────────────────────────────────────────┬───────────┐  │
│  │  Быстрая заметка...                                │ Записать  │  │  ◀── input + button
│  └────────────────────────────────────────────────────┴───────────┘  │
│                                                                      │
│  14:32:15  Давление упало до 1.23e-6, стабильно                     │  ◀── recent entries
│  14:28:02  Перешли в фазу захолаживания                              │     (newest first,
│  14:15:47  Запустили эксперимент calibration_run_042                 │      timestamp first)
│  14:11:30  Проверили подключение Keithley                            │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

📓 in header shows position only; actual widget uses Lucide icon per RULE-COPY-005.

## Parts

| Part | Required | Description |
|---|---|---|
| **Tile frame** | Yes | BentoTile base (since typically on dashboard as tile) |
| **Header row** | Yes | UPPERCASE category + «Открыть» link to full Journal |
| **Input field** | Yes | InputField (text variant) with placeholder |
| **Submit button** | Yes | SecondaryButton «Записать» or Enter key |
| **Recent entries list** | Yes | Read-only list: timestamp + entry text, newest first, max 3-5 rows |
| **Empty state** | When no entries | «Нет записей» |

## Invariants

1. **Inherits BentoTile invariants.** Single surface, CARD_PADDING, RADIUS_MD.
2. **Entry text sentence case.** Per RULE-COPY-003.
3. **Timestamps UTC-offset local time.** `14:32:15` — no seconds displayed if beyond 24h age, use relative («вчера», «2 дня назад»).
4. **Recent list max 3-5 entries.** More → Journal panel. Inline widget is not for browsing.
5. **Timestamps use FONT_MONO tnum.** (RULE-TYPO-003)
6. **Submit via Enter key** with focus in input. AND via button click. Both paths save.
7. **No destructive operations inline.** Cannot delete entries here; go to Journal panel for editing/deleting.
8. **Entry persistence on Enter.** Data writes atomically to engine via ZMQ. Failure shown as toast with retry.
9. **Empty input = no submit.** Whitespace-only rejected; show subtle tooltip on submit button «Заметка не может быть пустой».
10. **Max entry length**: 500 chars typical. Truncate preview with ellipsize; full text visible in Journal panel.

## Data model

```python
@dataclass
class LogEntry:
    t: datetime                 # timestamp (UTC-aware)
    text: str                   # operator-entered text
    source: str = "operator"    # "operator" | "system" | "alarm" — displayed entries filter by source
    experiment_id: str | None   # association with active experiment, if any
```

QuickLogBlock shows only `source="operator"` entries by default, or displays a filter.

## API (proposed)

```python
# src/cryodaq/gui/widgets/quick_log_block.py

class QuickLogBlock(BentoTile):
    """Dashboard / overlay inline operator log widget."""
    
    entry_submitted = Signal(str)     # emits text; consumer writes to engine
    open_journal_requested = Signal() # open full Journal panel
    
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        max_visible_entries: int = 4,
    ) -> None: ...
    
    def set_recent(self, entries: list[LogEntry]) -> None:
        """Update recent-entries list. Atomic."""
    
    def clear_input(self) -> None:
        """Clear input after successful submission."""
    
    def show_error(self, message: str) -> None:
        """Flash error on input row — e.g., 'Не удалось записать'."""
```

## Reference implementation

```python
class QuickLogBlock(BentoTile):
    entry_submitted = Signal(str)
    open_journal_requested = Signal()
    
    def __init__(self, parent=None, *, max_visible_entries=4):
        super().__init__(parent=parent, title="ЖУРНАЛ ОПЕРАТОРА")
        self._max_visible = max_visible_entries
        
        content = QWidget()
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        
        # Input row
        col.addWidget(self._build_input_row())
        
        # Recent entries list
        self._entries_container = QWidget()
        self._entries_layout = QVBoxLayout(self._entries_container)
        self._entries_layout.setContentsMargins(0, 0, 0, 0)
        self._entries_layout.setSpacing(theme.SPACE_1)
        col.addWidget(self._entries_container)
        
        col.addStretch()
        
        # Override default BentoTile header to include "Открыть" link
        self._build_custom_header()
        
        self.set_content(content)
        self._render_empty_state()
    
    def _build_custom_header(self) -> None:
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        
        # DESIGN: RULE-TYPO-008 UPPERCASE category
        title = QLabel("ЖУРНАЛ ОПЕРАТОРА")
        title_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
        title_font.setWeight(theme.FONT_LABEL_WEIGHT)
        title_font.setLetterSpacing(
            QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
        )
        title.setFont(title_font)
        title.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        row.addWidget(title, 1)
        
        open_btn = GhostButton("Открыть →")
        open_btn.clicked.connect(self.open_journal_requested)
        # DESIGN: RULE-SPACE-007 — compact button height (min 32 per components/button.md sizing table)
        open_btn.setFixedHeight(32)
        row.addWidget(open_btn, 0)
        
        self.set_title("")  # suppress default title; we installed custom header
        self._frame.layout().insertWidget(0, header)
    
    def _build_input_row(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)
        
        # DESIGN: RULE-INTER-001 focus ring, RULE-COPY-003 sentence-case placeholder
        self._input = QLineEdit()
        self._input.setFixedHeight(theme.ROW_HEIGHT)
        self._input.setPlaceholderText("Быстрая заметка...")
        self._input.returnPressed.connect(self._on_submit)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {theme.SURFACE_CARD};
                border: 1px solid {theme.BORDER};
                border-radius: {theme.RADIUS_SM}px;
                color: {theme.FOREGROUND};
                padding: 0 {theme.SPACE_2}px;
                font-family: "{theme.FONT_BODY}";
                font-size: {theme.FONT_BODY_SIZE}px;
            }}
            QLineEdit:focus {{
                border: 2px solid {theme.ACCENT};
            }}
        """)
        layout.addWidget(self._input, 1)
        
        # DESIGN: RULE-COPY-007 imperative «Записать»
        self._submit_btn = SecondaryButton("Записать")
        self._submit_btn.clicked.connect(self._on_submit)
        layout.addWidget(self._submit_btn, 0)
        
        return row
    
    def _on_submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            # DESIGN: RULE-COPY-004 specific error
            self._submit_btn.setToolTip("Заметка не может быть пустой")
            return
        self.entry_submitted.emit(text)
        # Consumer clears input on successful ZMQ roundtrip:
        # self.clear_input()
    
    def clear_input(self) -> None:
        self._input.clear()
        self._submit_btn.setToolTip("")
    
    def set_recent(self, entries: list[LogEntry]) -> None:
        # DESIGN: RULE-DATA-001 atomic
        # Clear existing rows
        while self._entries_layout.count():
            item = self._entries_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        
        if not entries:
            self._render_empty_state()
            return
        
        # Show newest first, max _max_visible
        visible = entries[:self._max_visible]
        for entry in visible:
            self._entries_layout.addWidget(self._build_entry_row(entry))
    
    def _build_entry_row(self, entry: LogEntry) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACE_2)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        
        # DESIGN: RULE-TYPO-003 tnum timestamp
        ts_text = self._format_timestamp(entry.t)
        ts_label = QLabel(ts_text)
        ts_font = QFont(theme.FONT_MONO, theme.FONT_LABEL_SIZE)
        ts_font.setFeature("tnum", 1)
        ts_font.setFeature("liga", 0)
        ts_label.setFont(ts_font)
        ts_label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        ts_label.setFixedWidth(80)  # stable column width
        layout.addWidget(ts_label)
        
        text_label = QLabel(entry.text)
        text_label.setStyleSheet(f"color: {theme.FOREGROUND};")
        text_label.setWordWrap(False)  # keep single-line for compact view
        # Ellipsize long entries — use Qt elision
        fm = text_label.fontMetrics()
        elided = fm.elidedText(entry.text, Qt.TextElideMode.ElideRight, 400)
        text_label.setText(elided)
        text_label.setToolTip(entry.text)  # full text in tooltip
        layout.addWidget(text_label, 1)
        
        return row
    
    def _format_timestamp(self, t: datetime) -> str:
        now = datetime.now(t.tzinfo)
        age = now - t
        if age.days == 0:
            return t.strftime("%H:%M:%S")
        elif age.days == 1:
            return "вчера"
        elif age.days < 7:
            return f"{age.days} дн"
        else:
            return t.strftime("%d.%m")
    
    def _render_empty_state(self) -> None:
        empty = QLabel("Нет записей")
        empty.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
        self._entries_layout.addWidget(empty)
    
    def show_error(self, message: str) -> None:
        # DESIGN: RULE-COPY-004 actionable
        self._input.setToolTip(message)
        # Optionally flash border red briefly
```

## Integration with engine

```
Operator types → Enter/Click «Записать»
         │
         ▼
QuickLogBlock.entry_submitted(text)
         │
         ▼
MainWindow handler → ZMQ REQ «operator_log.append»
         │
         ▼
Engine persists → SQLite + ZMQ PUB «operator_log.updated»
         │
         ▼
GUI ZMQ SUB updates QuickLogBlock.set_recent(recent_entries)
GUI clear_input() on ACK
```

Failure path:
```
ZMQ REQ timeout or error response
         │
         ▼
QuickLogBlock.show_error("Не удалось записать. Проверьте связь с engine.")
         │
         ▼
Input text preserved (don't lose user typing)
Toast notification also shown for visibility
```

## States

| State | Treatment |
|---|---|
| **Empty (no entries)** | Input available + «Нет записей» message |
| **Normal** | Input + N recent entries listed |
| **Submit pending** | Button disabled + small spinner; input disabled |
| **Submit succeeded** | Input cleared; list updates with new entry at top |
| **Submit failed** | Error tooltip on input; input preserves text; Toast notification |
| **Engine disconnected** | Input disabled with placeholder «Ожидание связи с engine» |

## Common mistakes

1. **Clearing input optimistically before engine ACK.** Network hiccup → operator loses typed text. Clear only after confirmed save.

2. **Showing >10 entries inline.** Inline widget becomes cramped. Limit to 3-5; full list in Journal panel.

3. **Submitting on any key (live typing).** Treats every keystroke as save. Use Enter or button click only.

4. **No empty-text validation.** Operator accidentally hits Enter with empty field; empty entry persisted. Reject whitespace-only.

5. **Timestamp as relative always.** «2 мин назад» gets confusing when reviewing log later. Use absolute time for today's entries, relative for older.

6. **Missing source distinction.** Mixing auto-system entries with operator entries in this widget. Keep operator-only here; Journal panel has source filter.

7. **Deleting entries from this widget.** Destructive action + compact UI = accidents. Delete only from Journal panel.

8. **Input loses focus on submission.** Operator types → Enter → submitted → field blurs. They want to type another entry. Keep focus on input after clear.

9. **Ellipsize entry mid-word with no tooltip.** Operator can't see full text of their own entry. Always provide full tooltip.

10. **No offline queue.** If engine is down, operator can't log. Queue entries locally; flush when reconnected. Simplest form: keep text in input; operator notified engine is offline; they decide whether to retry.

## Related components

- `components/bento-tile.md` — Parent base
- `components/input-field.md` — Input primitive (simplified single-line variant used here)
- `components/toast.md` — Submit failure notification
- `cryodaq-primitives/tool-rail.md` — «Открыть» link navigates to Journal panel (slot 8)

## Changelog

- 2026-04-17: Initial version. Compact inline operator-log widget for dashboard/overlay use. Two-part (input + recent list). Bounded entries for inline use; full browsing via Journal panel. Enter-to-submit + offline-friendly failure handling.
