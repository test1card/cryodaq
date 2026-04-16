---
title: Popover
keywords: popover, tooltip, anchor, floating, contextual, hover, dismiss, arrow
applies_to: small contextual overlays anchored to a trigger element
status: proposed
implements: not yet — currently ad-hoc QToolTip and inline panels substitute
last_updated: 2026-04-17
---

# Popover

Small contextual overlay anchored to a specific trigger element. Unlike Modal, popover does NOT dim the rest of the UI and is typically dismissed on click-outside.

**When to use:**
- Contextual actions anchored to a specific widget (overflow menu on a row, channel settings on a SensorCell)
- Rich tooltip with formatted content, links, or small actions (exceeds what `QToolTip` plain text supports)
- Compact preview/details triggered from hover or click (sensor channel hover shows calibration info)
- Settings or filter pickers that don't warrant a modal

**When NOT to use:**
- Plain text hint — use `QToolTip` (smaller, standard)
- Dismissible notification — use `Toast` (auto-dismiss, corner-positioned)
- Destructive confirmation — use `Dialog` or `Modal` with backdrop (popover is too easy to dismiss accidentally)
- Deep forms or multi-step workflows — use `Modal`
- Complex content exceeding ~400×500px — use `Modal`

## Anatomy

```
Trigger element (e.g., button)
      │
      ▼
┌─────┬─────────────────────────┐
│  ▲  │                         │  ◀── arrow pointing at trigger (optional)
│  ◀──┼── popover card          │
│     │  bg: SURFACE_ELEVATED    │
│     │  border: 1px BORDER      │
│     │  radius: RADIUS_MD       │
│     │  padding: CARD_PADDING   │
│     │  shadow: subtle (see     │
│     │          elevation.md)   │
│     │                          │
│     │  Content                 │
│     │                          │
└─────┴─────────────────────────┘
      ◀── max width ~320px typically
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Popover card** | Yes | QFrame with surface, border, radius |
| **Arrow / pointer** | Optional | Small triangle indicating anchor direction |
| **Content** | Yes | Popover payload — text, buttons, form, list |
| **Dismiss regions** | Yes | Click-outside or trigger element click again dismisses |

## Invariants

1. **Anchored, not centered.** Position relative to trigger element — above/below/left/right based on viewport available space.
2. **Surface is SURFACE_ELEVATED.** Same elevation tone as modal. One visual level above the page.
3. **Small max size.** Width ≤ 400px, height ≤ 500px typically. If content needs more, it belongs in modal.
4. **Escape dismisses.** Same Escape behavior as Modal — innermost overlay first. (RULE-INTER-002)
5. **Click-outside dismisses** by default. Exception: if the popover contains a form being filled, click-outside may be configured to NOT dismiss (prevent data loss).
6. **Z-index between dashboard and modal.** Popovers can stack on top of dashboard but are dominated by modals.
7. **Single compact surface.** Same Card invariants apply — single painted frame, transparent children. (RULE-SURF-001)
8. **Symmetric padding `CARD_PADDING` (12px).** Tighter than modal's SPACE_5 since popover is smaller.
9. **Shadow permitted?** Elevation is signaled via position (floating over parent); additional subtle shadow may be appropriate. See `tokens/elevation.md` for current policy.

## API (proposed)

```python
# src/cryodaq/gui/widgets/popover.py  (proposed)

class Popover(QWidget):
    """Anchored floating panel."""
    
    dismissed = Signal()
    
    def __init__(
        self,
        parent: QWidget,
        anchor: QWidget,
        *,
        placement: str = "auto",  # "top" | "bottom" | "left" | "right" | "auto"
        max_width: int = 320,
        max_height: int = 500,
        dismiss_on_outside_click: bool = True,
        show_arrow: bool = True,
    ) -> None: ...
    
    def set_content(self, widget: QWidget) -> None: ...
    
    def show(self) -> None:
        """Show popover positioned relative to anchor."""
    
    def close(self) -> None:
        """Close popover. Emits `dismissed`."""
```

## Variants

### Variant 1: Overflow menu

Contextual menu anchored to a kebab icon button.

```python
popover = Popover(
    parent=self,
    anchor=self._kebab_button,
    placement="bottom",
    max_width=220,
)

menu_content = QWidget()
menu_layout = QVBoxLayout(menu_content)
menu_layout.setContentsMargins(0, 0, 0, 0)
menu_layout.setSpacing(0)

for label, handler in menu_items:
    btn = GhostButton(label)
    btn.setFixedHeight(theme.ROW_HEIGHT)
    btn.setStyleSheet("text-align: left; padding-left: " + f"{theme.SPACE_3}px;")
    btn.clicked.connect(handler)
    btn.clicked.connect(popover.close)
    menu_layout.addWidget(btn)

popover.set_content(menu_content)
popover.show()
```

### Variant 2: Rich tooltip (details on hover/click)

Hover on a SensorCell → popover shows calibration info, last update, history sparkline.

```python
popover = Popover(
    parent=self,
    anchor=self._sensor_cell,
    placement="auto",
    max_width=360,
    dismiss_on_outside_click=True,
)

details = QWidget()
layout = QVBoxLayout(details)

title = QLabel("Т11 Теплообменник 1")
title_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
title_font.setWeight(theme.FONT_WEIGHT_SEMIBOLD)
title.setFont(title_font)
layout.addWidget(title)

calib_row = QLabel(f"Калибровка: {self._calibration_date}")
calib_row.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
layout.addWidget(calib_row)

# Small sparkline of last 60 seconds
sparkline = pg.PlotWidget()
sparkline.setFixedHeight(60)
# ... configure
layout.addWidget(sparkline)

popover.set_content(details)
popover.show()
```

### Variant 3: Filter picker

Button opens popover with filter checkboxes. User toggles then closes.

```python
popover = Popover(
    parent=self,
    anchor=self._filter_button,
    placement="bottom",
    max_width=280,
    dismiss_on_outside_click=False,  # user may click outside while choosing, don't dismiss
)

filters = QWidget()
filters_layout = QVBoxLayout(filters)

for filter_name in available_filters:
    cb = QCheckBox(filter_name)
    cb.setChecked(filter_name in active_filters)
    cb.stateChanged.connect(lambda s, name=filter_name: self._toggle_filter(name, s))
    filters_layout.addWidget(cb)

apply_btn = SecondaryButton("Применить")
apply_btn.clicked.connect(popover.close)
filters_layout.addWidget(apply_btn)

popover.set_content(filters)
popover.show()
```

## Placement algorithm

Auto placement logic:

```
1. Measure anchor bounds (in viewport coordinates)
2. Compute available space above / below / left / right of anchor
3. Prefer below (most natural reading direction)
4. If below doesn't fit (content height > space below), try above
5. If neither vertical fits, try right then left
6. Final fallback: clip content height to fit below
```

Explicit placement overrides auto when specified.

## States

| State | Visual treatment |
|---|---|
| **Hidden** | Not in layout |
| **Opening** | Fade+slide in from anchor direction, ~150ms |
| **Open** | Fully visible, positioned per placement |
| **Closing** | Fade out, ~100ms (faster exit per RULE-INTER-005) |

Much faster animations than Modal (150ms enter / 100ms exit vs modal's 300/200) — popovers are lighter touch.

## Common mistakes

1. **Using popover for destructive confirmation.** Popover is too easy to dismiss accidentally (click-outside). Use Modal or Dialog with explicit "Отмена"/"Удалить" buttons.

2. **Content too large.** Popover with scrollable form inside. At that size, content deserves a Modal with proper max_width (~720px) and padding. 320px popover struggling to hold a form is a structural smell.

3. **No dismiss on Escape.** Operator hits Escape, popover stays. RULE-INTER-002.

4. **Placement ignores viewport edges.** Popover clips off right edge because anchor is near right border and placement is "right". Use auto or check bounds.

5. **Popover stacked over modal.** Modal + popover anchored to modal content is OK (popover inherits modal's Z-stack). Popover over modal without relation to it is wrong — close modal first.

6. **Inherits anchor widget's text color.** Popover is its own surface; content colors should be set fresh, not inherited via stylesheet.

7. **Animation too slow.** Modal timing (300ms) applied to popover feels sluggish. Popovers should feel immediate.

## Related components

- `components/modal.md` — When content is substantial or operator attention needed
- `components/dialog.md` — For yes/no confirmations (not popover)
- `components/toast.md` — For transient notifications
- `cryodaq-primitives/sensor-cell.md` — Common popover anchor (sensor cell hover/click details)

## Changelog

- 2026-04-17: Initial version. `Popover` class proposed — not yet implemented. Current CryoDAQ uses ad-hoc QToolTip + inline panels; formalization tracked as Phase II/III follow-up.
