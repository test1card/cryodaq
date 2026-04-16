---
title: Breadcrumb
keywords: breadcrumb, navigation, drill-down, back, trail, hierarchy, path
applies_to: hierarchical navigation trail indicating current location
status: active
implements: src/cryodaq/gui/shell/overlays/_design_system/drill_down_breadcrumb.py
last_updated: 2026-04-17
references: rules/typography-rules.md, rules/interaction-rules.md, tokens/colors.md
---

# Breadcrumb

Horizontal trail of navigation labels showing the operator's path from a parent context to the current view. Last crumb represents current location. Preceding crumbs are interactive and return to those ancestors.

**When to use:**
- Modal drill-down header: «← Дашборд / Датчики»
- Any navigation where operator went two or more levels deep from a root
- When operator needs to return to a specific ancestor, not just the immediate parent

**When NOT to use:**
- Single-level navigation — use a back button or close × alone
- Linear paginated flow (step 1 / step 2 / step 3) — use a stepper or phase-stepper instead
- Tab switching within same-level siblings — use `TabGroup`
- Site-wide global nav — CryoDAQ is desktop single-window, doesn't need a site breadcrumb

## Anatomy

```
 ← Дашборд  /  Датчики  /  Т11 Теплообменник
 ▲          ▲           ▲
 │          │           │
 │          │           └── current crumb (non-interactive, FOREGROUND color)
 │          │
 │          └── ancestor crumb (interactive, MUTED_FOREGROUND)
 │
 └── leading back arrow (subtle; indicates the path points back to somewhere)

 Separator: "/" in MUTED_FOREGROUND, SPACE_1 gap on each side
 Height: ~24-28px (smaller than ROW_HEIGHT since inline with header)
 Font: FONT_LABEL_SIZE or FONT_BODY_SIZE depending on header prominence
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Leading arrow** | Recommended | `←` glyph or `arrow-left` icon prefixing the first crumb, signals "back" intent |
| **Ancestor crumb** | Any number | Interactive label, clicking returns to that context |
| **Separator** | Between crumbs | `/` character in MUTED color, no interaction |
| **Current crumb** | Yes | Non-interactive label for current location |

## Invariants

1. **Last crumb non-interactive.** Current location is never a link. Clicking it would be a no-op — don't make it look interactive.
2. **All other crumbs interactive.** Clicking any ancestor closes the current overlay stack back to that level.
3. **Chronological left→right.** Root on left, deepest on right. Matches left-to-right reading.
4. **Truncation strategy.** If total width exceeds container, truncate middle crumbs to `...` — keep first and last visible.
5. **Focus ring on interactive crumbs.** Tab key navigates through crumbs. (RULE-INTER-001)
6. **Keyboard shortcut.** Backspace or Alt+Left navigates to immediate parent crumb. Escape closes the drill-down entirely. (RULE-INTER-002)
7. **Accent color on hover, not default.** Interactive crumbs are `MUTED_FOREGROUND` in default state, `FOREGROUND` on hover. Never ACCENT in default. (RULE-COLOR-004 — ACCENT reserved for focus/selection)
8. **Current crumb FOREGROUND + semibold.** Visual weight signals "you are here." Sentence case per RULE-COPY-003 (not uppercase).
9. **No hover state on current crumb.** It's not interactive.

## API

Reference implementation (`drill_down_breadcrumb.py`):

```python
@dataclass
class DrillDownCrumb:
    """Single crumb in a breadcrumb trail."""
    label: str
    handler: Callable[[], None] | None = None  # None = non-interactive (current)

class DrillDownBreadcrumb(QWidget):
    """Horizontal breadcrumb trail."""
    
    def __init__(
        self,
        crumbs: list[DrillDownCrumb],
        parent: QWidget | None = None,
    ) -> None: ...
    
    def set_crumbs(self, crumbs: list[DrillDownCrumb]) -> None:
        """Replace the trail. Last crumb should have handler=None."""
```

## Variants

### Variant 1: Drill-down modal header

Most common use — header of a drill-down modal.

```python
# DESIGN: RULE-INTER-002 (Escape dismisses overlay)
breadcrumb = DrillDownBreadcrumb([
    DrillDownCrumb("Дашборд", handler=lambda: modal.close()),
    DrillDownCrumb("Датчики", handler=lambda: modal.pop_to_sensors_view()),
    DrillDownCrumb("Т11 Теплообменник"),  # current — no handler
])
modal.set_header(breadcrumb)
```

### Variant 2: Compact inline breadcrumb

For tight headers where full breadcrumb is too heavy. Just back arrow + label.

```python
# Just "← Дашборд" as compact back affordance
back = QHBoxLayout()
back.setContentsMargins(0, 0, 0, 0)
back.setSpacing(theme.SPACE_1)
back.setAlignment(Qt.AlignmentFlag.AlignVCenter)

arrow = QLabel()
arrow.setPixmap(
    load_colored_icon("arrow-left", color=theme.MUTED_FOREGROUND)
      .pixmap(theme.ICON_SIZE_SM, theme.ICON_SIZE_SM)  # proposed: theme.ICON_SIZE_SM — not yet in theme.py
)
back.addWidget(arrow)

label_btn = GhostButton("Дашборд")
# strip most chrome — this is a lightweight link
label_btn.setStyleSheet(f"""
    QPushButton {{
        background: transparent;
        border: none;
        color: {theme.MUTED_FOREGROUND};
        padding: 0;
    }}
    QPushButton:hover {{ color: {theme.FOREGROUND}; }}
    QPushButton:focus {{
        border-bottom: 2px solid {theme.ACCENT};  /* keyboard affordance */
    }}
""")
label_btn.clicked.connect(self._on_back)
back.addWidget(label_btn)
```

Use this when screen real estate is tight and full trail doesn't fit.

### Variant 3: Truncated breadcrumb

When trail becomes too long, truncate middle.

```
← Дашборд  /  ...  /  Т11 Теплообменник
```

Implementation: collapse middle crumbs into `...` that opens a dropdown showing hidden crumbs.

```python
def _apply_truncation(self, available_width: int) -> None:
    if self._measure_full_width() <= available_width:
        return  # fits, no truncation
    
    # Keep first + last. Collapse middle into "..."
    first_crumb = self._crumbs[0]
    last_crumb = self._crumbs[-1]
    hidden = self._crumbs[1:-1]
    
    self._render_truncated(first_crumb, hidden, last_crumb)
```

## Reference stylesheet

```python
# DESIGN: RULE-COLOR-004 (ACCENT only for focus)
# DESIGN: RULE-INTER-001 (focus ring visible)
self.setStyleSheet(f"""
    QLabel[role="crumb-current"] {{
        color: {theme.FOREGROUND};
        font-weight: {theme.FONT_WEIGHT_SEMIBOLD};
    }}
    QLabel[role="crumb-separator"] {{
        color: {theme.MUTED_FOREGROUND};
    }}
    QPushButton[role="crumb-ancestor"] {{
        background: transparent;
        border: none;
        color: {theme.MUTED_FOREGROUND};
        padding: 0;
    }}
    QPushButton[role="crumb-ancestor"]:hover {{
        color: {theme.FOREGROUND};
        text-decoration: underline;
    }}
    QPushButton[role="crumb-ancestor"]:focus {{
        color: {theme.FOREGROUND};
        border-bottom: 2px solid {theme.ACCENT};  /* focus via bottom border */
    }}
""")
```

## Keyboard navigation

```python
def keyPressEvent(self, event: QKeyEvent) -> None:
    # DESIGN: RULE-INTER-002
    if event.key() == Qt.Key.Key_Escape:
        # Let parent handle — close entire overlay
        super().keyPressEvent(event)
        return
    
    if event.key() == Qt.Key.Key_Backspace or (
        event.key() == Qt.Key.Key_Left and event.modifiers() & Qt.KeyboardModifier.AltModifier
    ):
        # Navigate to immediate parent
        if len(self._crumbs) >= 2:
            parent_crumb = self._crumbs[-2]
            if parent_crumb.handler:
                parent_crumb.handler()
            event.accept()
            return
    
    super().keyPressEvent(event)
```

## States

| State | Visual treatment |
|---|---|
| **Current crumb** | FOREGROUND color, semibold, no hover response |
| **Ancestor crumb default** | MUTED_FOREGROUND color, regular weight |
| **Ancestor crumb hover** | FOREGROUND color + underline text-decoration |
| **Ancestor crumb focus** | FOREGROUND color + 2px ACCENT bottom border |
| **Ancestor crumb pressed** | Slightly darker than hover (briefly, during click) |
| **Separator `/`** | MUTED_FOREGROUND, never interactive |

## Layout spacing

```python
# DESIGN: RULE-SPACE-001
layout = QHBoxLayout(self)
layout.setContentsMargins(0, 0, 0, 0)
layout.setSpacing(theme.SPACE_1)  # 4px between crumb and separator
layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
```

The `SPACE_1` (4px) is tight because separator `/` visually occupies its own horizontal space; larger gap looks disconnected.

## Common mistakes

1. **Making current crumb look clickable.** Underline or hover response on the last crumb suggests interactivity. Operator clicks, nothing happens, confused. Keep current crumb visually distinct (FOREGROUND, semibold, no hover) from ancestors.

2. **ACCENT color on default state.** Violates RULE-COLOR-004. ACCENT is focus/selection only. Use MUTED for default, FOREGROUND for hover/current.

3. **No keyboard shortcut.** Operator has to mouse back. Backspace → parent is a common convention that costs nothing to implement.

4. **Icon-only back without label.** `←` alone doesn't tell operator WHERE back goes. Include destination label: `← Дашборд`.

5. **Full path in title bar.** Window title "CryoDAQ — Дашборд — Датчики — Т11" as breadcrumb substitute is unreadable and small. Use in-page breadcrumb widget.

6. **Uppercase Cyrillic in crumbs.** Crumbs are sentence case (per RULE-COPY-003) — "Дашборд", not "ДАШБОРД". UPPERCASE is for category labels (tile headers, destructive action buttons), not navigation.

7. **Letter-spacing on crumbs.** Crumbs are inline navigation text, not uppercase category labels. No letter-spacing.

8. **No truncation strategy.** At tight widths, long crumb trails overflow and clip. Implement middle-truncation or ellipsize individual long crumb labels.

9. **Hover color same as default.** No visual change on hover — operator doesn't know crumb is clickable. Always change color (or add underline) on hover.

## Related components

- `components/modal.md` — Typical breadcrumb host (drill-down modal header)
- `components/button.md` — Ancestor crumbs are essentially text-only buttons
- `cryodaq-primitives/phase-stepper.md` — Phase stepper is NOT a breadcrumb — breadcrumbs show path, stepper shows sequential progression

## Changelog

- 2026-04-17: Initial version documenting Phase I.1 `DrillDownBreadcrumb` implementation. 3 variants (full drill-down, compact inline, truncated). Keyboard navigation patterns and truncation strategy specified.
