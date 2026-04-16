---
title: ToolRail
keywords: tool-rail, sidebar, left-rail, navigation, icon-only, vertical, chrome, primary-nav
applies_to: left vertical icon-only navigation strip
status: active
implements: src/cryodaq/gui/shell/tool_rail.py (Phase 0)
last_updated: 2026-04-17
references: rules/interaction-rules.md, rules/color-rules.md, tokens/icons.md
---

# ToolRail

Thin vertical icon-only navigation strip along the left edge of every screen. Primary application navigation — each icon opens one of the major panels.

**When to use:**
- Singleton in `MainWindow` — always visible at left edge
- Navigation between top-level application sections

**When NOT to use:**
- Sub-section navigation within a panel — use `TabGroup` instead
- Contextual actions within a tile — use inline buttons
- Shortcut palette — use a command palette (not yet in scope)
- Any navigation where labels would help — ToolRail is icon-only; if users need labels, use a regular sidebar

## Confirmed icons

Per Phase 0 audit, these icons open functional panels. **Canonical shortcut = mnemonic** per AD-002 (`tokens/keyboard-shortcuts.md`). The numeric `Ctrl+[N]` column is a transitional fallback — it remains active but is being phased out when rail slot ordering stabilizes.

| Slot | Icon | Panel | Canonical shortcut | Numeric fallback |
|---|---|---|---|---|
| 1 | `home` or `layout-dashboard` | Дашборд (overview) | *(no mnemonic yet — propose `Ctrl+H` for "home" in a future release)* | Ctrl+1 |
| 2 | `plus-circle` | Создать эксперимент | *(no mnemonic yet — Ctrl+E is taken by slot 3; candidate: `Ctrl+N` for "new experiment")* | Ctrl+2 |
| 3 | `flask-conical` | Карточка эксперимента | `Ctrl+E` | Ctrl+3 |
| 4 | `zap` | Keithley (источник мощности) | `Ctrl+K` | Ctrl+4 |
| 5 | `chart-line` | Аналитика / графики | `Ctrl+A` | Ctrl+5 |
| 6 | `activity` or `thermometer` | Теплопроводность | `Ctrl+C` | Ctrl+6 |
| 7 | `bell` | Алармы | `Ctrl+M` (М — «Модуль сигнализации») | Ctrl+7 |
| 8 | `file-text` | Журнал оператора | `Ctrl+L` | Ctrl+8 |
| 9 | `sliders` | Диагностика датчиков | `Ctrl+D` | Ctrl+9 |

Per Phase 0 product decision: «Создать эксперимент» (slot 2) and «Карточка эксперимента» (slot 3) may be merged into a single slot in Phase II — mnemonic for slot 2 will be settled at that point.

When both a canonical mnemonic and a numeric fallback exist, the tooltip shows the **canonical** shortcut: `«Дашборд (Ctrl+1)»` today, migrating to the mnemonic as slot mnemonics are finalized. Do not display both in one tooltip — pick the canonical one.

## Anatomy

```
┌──────┐
│      │ ◀── TOOL_RAIL_WIDTH (56)
│  □   │ ◀── slot 1 — 56x56 square
│      │
│  ▣   │ ◀── slot 2 — same size
│      │
│  □   │
│      │
│  □   │
│      │
│  □   │
│      │
│      │ ◀── growing space; icons top-anchored
│      │
│      │
│  □   │ ◀── optional bottom slot (settings, help)
│      │
└──────┘
  ◀── background: SURFACE_CARD
  ◀── border-right: 1px BORDER
  ◀── top and bottom of bar extend full viewport height
      EXCEPT: first HEADER_HEIGHT px is claimed by TopWatchBar → ToolRail
      starts at y = HEADER_HEIGHT (alternatively, bar starts at y=0 and
      TopWatchBar starts at x=TOOL_RAIL_WIDTH; implementations vary —
      ensure corner is square via coupled constants per RULE-SPACE-006)
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Rail frame** | Yes | Vertical strip, `TOOL_RAIL_WIDTH` (56) wide, full viewport height |
| **Icon slot** | Multiple | 56×56 square containing Lucide icon (24×24 inside) |
| **Active indicator** | Yes | 3px vertical bar on left edge of active slot, ACCENT color |
| **Divider** | Implicit | 1px right border separates rail from main content |
| **Optional bottom slots** | 0-2 | Secondary actions at rail bottom (settings, help) |

## Invariants

1. **Width = TOOL_RAIL_WIDTH (56).** Coupled to HEADER_HEIGHT per RULE-SPACE-006.
2. **Icon-only, tooltip mandatory** per RULE-INTER-008. Tooltip includes name + shortcut: «Дашборд (Ctrl+1)».
3. **Active slot uses ACCENT.** This is legitimate ACCENT use — selection affordance per RULE-COLOR-004.
4. **Inactive slots MUTED_FOREGROUND icons.** Active slot FOREGROUND icon + 3px ACCENT bar on left edge.
5. **Click selects.** Hover does not select — hover only changes icon color to FOREGROUND (RULE-COLOR-006).
6. **Keyboard navigation.** Down/Up Arrow to navigate; Enter selects. Or use the canonical mnemonic shortcuts (`Ctrl+L`, `Ctrl+E`, etc. per `tokens/keyboard-shortcuts.md`); numeric `Ctrl+[1-9]` remains as transitional fallback.
7. **No emoji icons.** (RULE-COPY-005) — Lucide SVG only.
8. **Icon color inherits from slot's text color.** Recolor via `load_colored_icon`. (RULE-COLOR-005)
9. **Icon size 24×24** centered in 56×56 slot — even padding all around (16px).
10. **No badges on icons** in default rail (alarm badge is separate widget in TopWatchBar area, not on rail slot).

## API

Reference implementation (`tool_rail.py` Phase 0):

```python
@dataclass
class ToolRailSlot:
    key: str                # stable id, e.g. "dashboard"
    icon_name: str          # Lucide name
    label: str              # "Дашборд"
    shortcut: str | None    # "Ctrl+1"
    handler: Callable[[], None] | None = None
    position: str = "top"   # "top" | "bottom"

class ToolRail(QWidget):
    """Left vertical icon-only navigation."""
    
    selection_changed = Signal(str)  # emits slot key
    
    SLOT_SIZE = 56  # matches TOOL_RAIL_WIDTH
    ICON_SIZE = 24
    
    def __init__(
        self,
        slots: list[ToolRailSlot],
        parent: QWidget | None = None,
        *,
        initial_key: str | None = None,
    ) -> None: ...
    
    def set_selected(self, key: str) -> None: ...
    def selected(self) -> str: ...
    def register_shortcut(self, shortcut: str, key: str) -> None: ...
```

## Slot widget reference

```python
class ToolRailSlotWidget(QWidget):
    """One icon slot in the rail."""
    
    clicked = Signal()
    
    def __init__(self, slot: ToolRailSlot, parent=None):
        super().__init__(parent)
        self._slot = slot
        self._selected = False
        
        self.setFixedSize(
            theme.TOOL_RAIL_WIDTH,  # 56 — slot is square matching rail width
            theme.TOOL_RAIL_WIDTH,
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # DESIGN: RULE-INTER-008 — tooltip mandatory for icon-only
        tooltip_text = slot.label
        if slot.shortcut:
            tooltip_text = f"{slot.label} ({slot.shortcut})"
        self.setToolTip(tooltip_text)
        
        # DESIGN: RULE-COLOR-005 — icon color inherits from text context
        self._icon_label = QLabel(self)
        self._icon_label.setFixedSize(theme.ICON_SIZE_MD, theme.ICON_SIZE_MD)  # proposed: theme.ICON_SIZE_MD — not yet in theme.py
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_icon(color=theme.MUTED_FOREGROUND)
        
        # Center icon in slot
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._icon_label)
    
    def _update_icon(self, color: str) -> None:
        pixmap = load_colored_icon(self._slot.icon_name, color=color).pixmap(
            theme.ICON_SIZE_MD, theme.ICON_SIZE_MD  # proposed: theme.ICON_SIZE_MD — not yet in theme.py
        )
        self._icon_label.setPixmap(pixmap)
    
    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._apply_style()
    
    def _apply_style(self) -> None:
        # DESIGN: RULE-COLOR-001
        if self._selected:
            # DESIGN: RULE-COLOR-004 — ACCENT for selection
            self._update_icon(color=theme.FOREGROUND)
            self.setStyleSheet(f"""
                ToolRailSlotWidget {{
                    background: {theme.MUTED};
                    border-left: 3px solid {theme.ACCENT};
                }}
            """)
        else:
            self._update_icon(color=theme.MUTED_FOREGROUND)
            self.setStyleSheet(f"""
                ToolRailSlotWidget {{
                    background: transparent;
                    border-left: 3px solid transparent;
                }}
                ToolRailSlotWidget:hover {{
                    background: {theme.MUTED};
                }}
            """)
    
    def enterEvent(self, event):
        if not self._selected:
            # DESIGN: RULE-COLOR-006 — hover goes via MUTED not ACCENT
            self._update_icon(color=theme.FOREGROUND)
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        if not self._selected:
            self._update_icon(color=theme.MUTED_FOREGROUND)
        super().leaveEvent(event)
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)
```

## Rail reference

```python
class ToolRail(QWidget):
    def __init__(self, slots, parent=None, *, initial_key=None):
        super().__init__(parent)
        self.setFixedWidth(theme.TOOL_RAIL_WIDTH)  # DESIGN: RULE-SPACE-006
        self.setObjectName("toolRail")
        self.setStyleSheet(f"""
            #toolRail {{
                background: {theme.SURFACE_CARD};
                border: none;
                border-right: 1px solid {theme.BORDER};
            }}
        """)
        
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self._widgets: dict[str, ToolRailSlotWidget] = {}
        
        top_slots = [s for s in slots if s.position == "top"]
        bottom_slots = [s for s in slots if s.position == "bottom"]
        
        for slot in top_slots:
            w = ToolRailSlotWidget(slot, self)
            w.clicked.connect(lambda key=slot.key: self._on_click(key))
            column.addWidget(w)
            self._widgets[slot.key] = w
        
        column.addStretch()
        
        for slot in bottom_slots:
            w = ToolRailSlotWidget(slot, self)
            w.clicked.connect(lambda key=slot.key: self._on_click(key))
            column.addWidget(w)
            self._widgets[slot.key] = w
        
        # Register shortcuts
        for slot in slots:
            if slot.shortcut:
                sc = QShortcut(QKeySequence(slot.shortcut), parent)
                sc.activated.connect(lambda key=slot.key: self._on_click(key))
        
        if initial_key:
            self.set_selected(initial_key)
    
    def _on_click(self, key: str) -> None:
        self.set_selected(key)
        self.selection_changed.emit(key)
    
    def set_selected(self, key: str) -> None:
        for slot_key, widget in self._widgets.items():
            widget.set_selected(slot_key == key)
```

## States

| Slot state | Icon color | Background | Left border |
|---|---|---|---|
| Default | MUTED_FOREGROUND | transparent | 3px transparent (reserved) |
| Hover | FOREGROUND | MUTED | 3px transparent |
| Selected | FOREGROUND | MUTED | 3px ACCENT |
| Keyboard focus | FOREGROUND | MUTED | 3px ACCENT (same as selected) OR subtle dotted outline around icon |
| Disabled | TEXT_DISABLED | transparent | 3px transparent — cursor ArrowCursor |

## Keyboard shortcut policy

Per `tokens/keyboard-shortcuts.md` (canonical registry, AD-002):

- **Canonical (mnemonic):** `Ctrl+L`, `Ctrl+E`, `Ctrl+A`, `Ctrl+K`, `Ctrl+M`, `Ctrl+C`, `Ctrl+D` (and others in the registry) route to their respective rail slots by panel identity, independent of slot position.
- **Transitional fallback:** `Ctrl+1` … `Ctrl+9` route to rail slots 1–9 by position. Being phased out — do not extend.
- `F11` — toggle fullscreen.
- `Ctrl+Shift+X` — emergency stop (hold-to-confirm).

ToolRail registers both the canonical mnemonic and the numeric-fallback shortcut at application level (not rail-local) so shortcuts work from anywhere. When mnemonics are finalized for all nine slots, the numeric registrations will be removed per deprecation policy.

## Common mistakes

1. **Text labels on rail.** Adding «Дашборд» text next to home icon. Breaks 56×56 slot geometry, turns rail into a wide sidebar. Keep icon-only + tooltip.

2. **Emoji icons.** 🏠 instead of Lucide `home`. RULE-COPY-005.

3. **Missing tooltip.** Icon-only button without tooltip. RULE-INTER-008.

4. **Active indicator on right instead of left.** Visual convention: indicator adjacent to main content (i.e., right of the icon, left of the main pane). Left-edge indicator is correct for LEFT rail.

5. **Hover color = ACCENT.** Violates RULE-COLOR-006. Hover is MUTED background + FOREGROUND icon.

6. **Slot height != slot width.** Slots are 56×56 squares; if height changes, corner-square invariant with TopWatchBar breaks.

7. **Forgetting to register shortcut at app level.** Ctrl+1 only works when rail has focus. Register as QShortcut on parent window so it works anywhere.

8. **Clicking icon opens panel + navigates away from current work.** If operator is filling form in a panel, clicking rail slot should either preserve form state (save draft) or confirm navigation. Don't silently discard operator work.

9. **Rail width not matching HEADER_HEIGHT.** Breaks corner square. Coupled constant per RULE-SPACE-006.

10. **Mixing text and icons in slots.** E.g., "📊 Dash" half-icon half-text. Commit to icon-only OR use a regular sidebar with text labels.

## Related components

- `cryodaq-primitives/top-watch-bar.md` — Horizontal counterpart (top chrome)
- `cryodaq-primitives/bottom-status-bar.md` — Bottom status strip
- `components/tab-group.md` — For sub-navigation within panels
- `tokens/icons.md` — Lucide icon bundle
- `tokens/keyboard-shortcuts.md` — Shortcut registry

## Changelog

- 2026-04-17: Initial version. Documents Phase 0 implementation. 9 slot definitions confirmed. Slot 2+3 merge pending product decision. Ctrl+[1-9] shortcuts + Ctrl+L alias for Operator Log.
- 2026-04-17 (v1.0.1): Aligned with canonical mnemonic shortcut registry per AD-002 (FR-011). Added canonical-shortcut column to the slot table (Ctrl+E / Ctrl+K / Ctrl+A / Ctrl+C / Ctrl+M / Ctrl+L / Ctrl+D). Demoted Ctrl+[1-9] to "numeric fallback" column. Clarified that slots 1 and 2 do not yet have approved mnemonics and still rely on the fallback. Keyboard-shortcut-policy section rewritten to match.
