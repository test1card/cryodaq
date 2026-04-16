---
title: TabGroup
keywords: tab, tabs, navigation, switch, view, group, segmented, selected
applies_to: tab-style navigation for sibling views
status: partial
implements: legacy QTabWidget usage in settings and instruments panels
last_updated: 2026-04-17
---

# TabGroup

Horizontal row of labeled tabs for switching between sibling views. One tab is selected; clicking a tab activates it and deactivates the previous selection.

**When to use:**
- Grouping sibling views of the same type (Settings → [Общие / Датчики / Соединения / О программе])
- Switching between parallel content panes where only one is relevant at a time
- Segmented control-like choices within a panel (plot time range: [15 мин / 1 час / 6 часов / 24 часа])

**When NOT to use:**
- Primary application navigation — CryoDAQ uses ToolRail (left vertical strip)
- Hierarchical navigation (parent → child) — use `Breadcrumb`
- Sequential flow (step 1 → step 2) — use a stepper widget or `PhaseStepper`
- Only 2 choices — use a toggle or two buttons instead; tabs are overkill
- Large content volume per tab where all need to be compared — use split view or drawer

## TabGroup vs ToolRail

| Property | TabGroup | ToolRail |
|---|---|---|
| Orientation | Horizontal | Vertical |
| Use level | Sub-section navigation | Top-level application navigation |
| Scope | Contained within a panel/card | Spans full viewport height |
| Count | 2-6 tabs typical | 6-10 sections typical |
| Typical location | Top of panel/modal/card | Left edge of viewport |

## Anatomy

```
 Tab row (height ROW_HEIGHT or slightly smaller)
┌─────────────┬──────────────┬─────────────────┬──────────────┐
│  Общие      │  Датчики     │  Соединения     │  О программе │
│             │   ▬▬▬▬▬▬     │                 │              │  ◀── active indicator
└─────────────┴──────────────┴─────────────────┴──────────────┘
                    ▲                                            ◀── separator line
                    │                                                1px BORDER full row
                    └── selected tab — FOREGROUND color, bottom accent bar
                        Other tabs: MUTED_FOREGROUND, no underline
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   Content panel for selected tab                            │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

The **active tab has a 2-3px accent bottom border** (bar under the label) — this is one of the few places ACCENT color appears in default state per RULE-COLOR-004 (selected = selection affordance, which is what ACCENT is for).

## Parts

| Part | Required | Description |
|---|---|---|
| **Tab row** | Yes | HBox of tab buttons |
| **Tab button** | Multiple | Clickable label, may contain icon + text |
| **Active indicator** | Yes | 2-3px bar under selected tab, ACCENT color |
| **Separator line** | Yes | 1px BORDER bottom border on tab row |
| **Content pane** | Yes | Host for selected tab's content |

## Invariants

1. **Exactly one tab selected at a time.** Multi-select tabs are not tabs — they're filter pills (use different component).
2. **Selection indicator is ACCENT.** This is the legitimate use of ACCENT in default state — selected tab IS a selection. (RULE-COLOR-004)
3. **Inactive tabs MUTED_FOREGROUND.** Active tab FOREGROUND. Color difference + bottom accent bar = two redundant channels. (RULE-A11Y-002)
4. **Tab row height = ROW_HEIGHT (36)** typically, may be smaller (32) in compact variants. (RULE-SPACE-007)
5. **Hover on inactive tab → FOREGROUND color**, no bar. Selected state remains distinct from hover.
6. **Keyboard navigation with Arrow keys.** Left/Right arrows navigate tabs when focus is on tab row. Tab key exits tab row to content. (RULE-INTER-001)
7. **Content pane transitions** may animate (optional) but don't delay interaction — tab click triggers content switch immediately.
8. **Label style:** sentence case, not UPPERCASE. Tabs are navigation nouns, not category labels. (RULE-COPY-003)
9. **Equal padding per tab.** Each tab has `SPACE_3` horizontal padding; widths are content-sized, not forced-equal unless specifically configured.
10. **No icon-only tabs** except in very compact variants with tooltip. Label is primary affordance. (RULE-INTER-008 if icon-only)

## API (proposed)

```python
# src/cryodaq/gui/widgets/tab_group.py  (proposed)

@dataclass
class TabDef:
    label: str
    key: str                     # stable identifier
    icon_name: str | None = None
    badge: int | str | None = None  # optional count/indicator

class TabGroup(QWidget):
    """Horizontal tabs + stacked content."""
    
    selection_changed = Signal(str)  # emits new selected key
    
    def __init__(
        self,
        tabs: list[TabDef],
        parent: QWidget | None = None,
        *,
        initial_key: str | None = None,
    ) -> None: ...
    
    def set_content(self, key: str, widget: QWidget) -> None:
        """Provide content for a tab key. Called once per tab typically."""
    
    def set_selected(self, key: str) -> None: ...
    def selected(self) -> str: ...
```

## Variants

### Variant 1: Standard horizontal tabs

Most common use.

```python
# DESIGN: RULE-COLOR-004 (selection via ACCENT is valid)
tabs = TabGroup(
    [
        TabDef(label="Общие", key="general"),
        TabDef(label="Датчики", key="sensors"),
        TabDef(label="Соединения", key="connections"),
        TabDef(label="О программе", key="about"),
    ],
    initial_key="general",
)

tabs.set_content("general", general_panel_widget)
tabs.set_content("sensors", sensors_panel_widget)
tabs.set_content("connections", connections_panel_widget)
tabs.set_content("about", about_panel_widget)

tabs.selection_changed.connect(self._on_tab_changed)
```

### Variant 2: Tabs with icons

Compact tabs with icon prefix. Tooltip optional.

```python
tabs = TabGroup([
    TabDef(label="Температуры", key="temps", icon_name="thermometer"),
    TabDef(label="Давления", key="pressures", icon_name="gauge"),
    TabDef(label="Мощность", key="power", icon_name="zap"),
])
```

### Variant 3: Tabs with count badges

Each tab shows a count next to label — useful for inbox-style views.

```python
tabs = TabGroup([
    TabDef(label="Активные", key="active", badge=3),
    TabDef(label="Завершённые", key="done"),
    TabDef(label="Архив", key="archive", badge=128),
])
```

### Variant 4: Segmented control (compact)

Small-scale tab-like selector for data ranges. Shorter height (28-32px), equal-width tabs, pill-shaped frame.

```python
# DESIGN: RULE-COLOR-004 (selection valid ACCENT use)
# Time range selector
range_tabs = TabGroup(
    [
        TabDef(label="15 мин", key="15m"),
        TabDef(label="1 час", key="1h"),
        TabDef(label="6 часов", key="6h"),
        TabDef(label="24 часа", key="24h"),
    ],
    compact=True,  # enables shorter height, pill frame around whole row
)
```

In segmented variant, the selection indicator is typically a filled background behind selected tab (small rounded rect), not a bottom bar.

## Reference stylesheet

```python
# DESIGN: RULE-COLOR-001, RULE-COLOR-004
tab_row_style = f"""
    QPushButton[role="tab"] {{
        background: transparent;
        border: none;
        border-bottom: 2px solid transparent;  /* invisible default bar */
        color: {theme.MUTED_FOREGROUND};
        padding: 0 {theme.SPACE_3}px;
        font-family: "{theme.FONT_BODY}";
        font-size: {theme.FONT_BODY_SIZE}px;
        font-weight: {theme.FONT_WEIGHT_MEDIUM};
    }}
    QPushButton[role="tab"]:hover {{
        color: {theme.FOREGROUND};
    }}
    QPushButton[role="tab"][selected="true"] {{
        color: {theme.FOREGROUND};
        border-bottom: 2px solid {theme.ACCENT};
    }}
    QPushButton[role="tab"]:focus {{
        /* Focus ring distinct from selection: use ACCENT color + dotted? */
        /* Simpler: use outline style on focus, preserve selection bar */
        background: {theme.MUTED};
    }}
    QWidget#tabGroupRow {{
        background: transparent;
        border-bottom: 1px solid {theme.BORDER};
    }}
"""
```

## Keyboard navigation

```python
# DESIGN: RULE-INTER-001, RULE-A11Y-001
def keyPressEvent(self, event: QKeyEvent) -> None:
    if event.key() == Qt.Key.Key_Left:
        self._select_prev()
        event.accept()
    elif event.key() == Qt.Key.Key_Right:
        self._select_next()
        event.accept()
    elif event.key() == Qt.Key.Key_Home:
        self._select_by_index(0)
        event.accept()
    elif event.key() == Qt.Key.Key_End:
        self._select_by_index(len(self._tabs) - 1)
        event.accept()
    else:
        super().keyPressEvent(event)

def _select_prev(self) -> None:
    idx = self._current_index()
    if idx > 0:
        self.set_selected(self._tabs[idx - 1].key)

def _select_next(self) -> None:
    idx = self._current_index()
    if idx < len(self._tabs) - 1:
        self.set_selected(self._tabs[idx + 1].key)
```

## States

| State | Visual treatment |
|---|---|
| **Tab inactive** | MUTED_FOREGROUND text, no bar |
| **Tab inactive hover** | FOREGROUND text, no bar |
| **Tab active** | FOREGROUND text, 2px ACCENT bar under |
| **Tab focus (keyboard)** | Background MUTED overlay (subtle), plus selection state if selected |
| **Tab disabled** | TEXT_DISABLED text, cursor ArrowCursor |

**Active + hover:** hover does not further change active tab — it's already the maximally-prominent state.

## Sizing

| Context | Height | Padding | Font |
|---|---|---|---|
| Default | ROW_HEIGHT (36) | SPACE_3 horiz | FONT_BODY (14) |
| Compact / segmented | 32 | SPACE_2 horiz | FONT_LABEL (12) |
| Large / hero | 44 | SPACE_4 horiz | FONT_TITLE (22) |

## Common mistakes

1. **Multiple tabs selected.** Tabs are single-select. Multi-select is filter pills (different widget).

2. **Active state using color alone.** Just changing text color to ACCENT with no bar indicator fails RULE-A11Y-002. Always include bar + color for two redundant channels.

3. **Using UPPERCASE on labels.** "ОБЩИЕ / ДАТЧИКИ / СОЕДИНЕНИЯ" is miscalibrated — these are navigation labels, sentence case per RULE-COPY-003.

4. **ACCENT used as default inactive color.** Violates RULE-COLOR-004 — ACCENT is for the selected state specifically.

5. **Tabs forced to equal width regardless of label length.** «О программе» is 5× wider than «Общие». Forced equal width creates awkward gaps. Let tabs size to content + equal padding, except segmented variant where equal width IS the aesthetic.

6. **No keyboard navigation.** Arrow keys don't move between tabs. Tab widget without Arrow-key support fails keyboard navigation expectations.

7. **Tab + content in different visual modes.** Tab row on SURFACE_CARD, content pane with no surface treatment. Creates inconsistent boundary. Tab row and content should share the same card context (tab row at top of card, content below, both within same surface).

8. **Content flash on tab change.** Rebuilding content on each click is visible flicker. Pre-build all tab content at construction; show/hide via `QStackedWidget` internally.

9. **Icon-only tabs without tooltip.** Fails RULE-INTER-008. If truly compact, every tab needs `setToolTip()`.

## Related components

- `cryodaq-primitives/tool-rail.md` — Primary vertical navigation, not tabs
- `components/breadcrumb.md` — For hierarchical navigation
- `cryodaq-primitives/phase-stepper.md` — For sequential progression, not parallel siblings
- `components/button.md` — Toggle button is a related but different paradigm

## Changelog

- 2026-04-17: Initial version. 4 variants (standard, with icons, with badges, segmented). `TabGroup` class proposed — current legacy uses QTabWidget directly; consolidation Phase II.
