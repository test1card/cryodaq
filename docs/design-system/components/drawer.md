---
title: Drawer
keywords: drawer, side-panel, slide-in, detail, sidebar, overlay, right-panel
applies_to: side-sliding overlay panels
status: proposed
implements: not yet — currently embedded panels substitute
last_updated: 2026-04-17
---

# Drawer

Side panel that slides in from an edge (typically right). Overlays the page or pushes content aside. Dismissible via close button or Escape. Longer and narrower than Modal — optimized for list-of-detail or persistent secondary navigation.

**When to use:**
- Detail pane for a selected item (click on experiment row → drawer shows full metadata)
- Help panel or contextual documentation that stays open while operator works
- Side-by-side comparison (primary content + drawer with comparison data)
- Secondary settings or filter panels that don't warrant modal blocking

**When NOT to use:**
- Short question / answer — use `Dialog`
- Full-content detail with backdrop blocking — use `Modal` (drawer is optimized for persistent work-alongside)
- Small anchored menu — use `Popover`
- Transient notification — use `Toast`
- Primary dashboard content — that's the main content area, not a drawer

## Drawer vs Modal — when which

| Property | Drawer | Modal |
|---|---|---|
| Position | Edge-attached (typically right) | Centered |
| Shape | Tall narrow (320-480 wide, full height) | Any aspect ratio |
| Backdrop | Often absent; drawer may coexist with dashboard | Usually present |
| Dismiss | Close button / Escape / click-outside (configurable) | Close button / Escape / backdrop (optional) |
| Persistence | May stay open across operator actions | Usually one operation then close |

## Anatomy

```
Main content area                               Drawer (right-edge)
┌─────────────────────────────────┐┌───────────────────────────┐
│                                 ││ ◀── drawer card            │
│   Dashboard content              ││     bg: SURFACE_ELEVATED   │
│                                 ││     left border 1px BORDER │
│   (visible while drawer open)   ││     no radius on left edge │
│                                 ││     radius RADIUS_MD on    │
│                                 ││       top-right/bot-right  │
│                                 ││                            │
│                                 ││  ┌──────────────────┬──┐   │
│                                 ││  │ Title            │× │   │  ← header
│                                 ││  └──────────────────┴──┘   │
│                                 ││                            │
│                                 ││  ┌─────────────────────┐   │
│                                 ││  │                     │   │
│                                 ││  │  Content            │   │
│                                 ││  │  (scrollable)       │   │
│                                 ││  │                     │   │
│                                 ││  │                     │   │
│                                 ││  └─────────────────────┘   │
│                                 ││                            │
│                                 ││  ┌─────────────────────┐   │
│                                 ││  │   actions           │   │  ← footer (optional)
│                                 ││  └─────────────────────┘   │
└─────────────────────────────────┘└───────────────────────────┘
                                     ◀── width: 320-480 typical
                                     ◀── full viewport height
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Drawer card** | Yes | QFrame flush to viewport edge; radius only on inner corners |
| **Header row** | Yes | Title + close button, single HBox (RULE-SURF-004) |
| **Scrollable content** | Yes | `QScrollArea` wrapping content — drawer content often exceeds viewport height |
| **Footer actions** | Optional | Actions row at bottom |
| **Backdrop dim** | Optional | Per variant; default none |

## Invariants

1. **Edge-attached, not centered.** Left, top, right, or bottom edge. Typically right.
2. **Radius only on inner edges.** Right drawer: RADIUS_MD on top-left + bottom-left; 0 on top-right / bottom-right (flush to viewport). This is the one case where radius asymmetry is correct — the edge doesn't exist as a curve.
3. **Full viewport height** (for left/right drawers). Stretches top to bottom.
4. **Fixed width.** Drawer doesn't resize with viewport — it's a persistent-width panel (320, 400, 480 tokens).
5. **Single surface.** Same Card invariants. (RULE-SURF-001)
6. **Content scrollable.** Drawer content height likely exceeds viewport; internal QScrollArea.
7. **Asymmetric slide animation.** Enter slides in from edge; exit slides out. Exit 60-70% of enter duration. (RULE-INTER-005)
8. **Escape dismisses.** (RULE-INTER-002)
9. **Click-outside may not dismiss.** Drawer often coexists with interactive dashboard — clicking dashboard to interact should not close drawer. Configurable.
10. **Left border.** Right-attached drawer has `1px BORDER` on its left edge to separate from main content. Same for other attachment directions — the separator edge gets the border.

## API (proposed)

```python
# src/cryodaq/gui/widgets/drawer.py  (proposed)

class Drawer(QWidget):
    """Edge-attached sliding panel."""
    
    DIRECTION_RIGHT = "right"
    DIRECTION_LEFT = "left"
    # Top/bottom also theoretically supported, rarely useful
    
    WIDTH_SM = 320
    WIDTH_MD = 400
    WIDTH_LG = 480
    
    opened = Signal()
    closed = Signal()
    
    def __init__(
        self,
        parent: QWidget,
        *,
        direction: str = DIRECTION_RIGHT,
        width: int = WIDTH_MD,
        backdrop: bool = False,
        dismiss_on_outside_click: bool = False,
    ) -> None: ...
    
    def set_header(self, widget: QWidget) -> None: ...
    def set_content(self, widget: QWidget) -> None: ...
    def set_footer(self, widget: QWidget | None) -> None: ...
    
    def open(self) -> None: ...
    def close(self) -> None: ...
    def is_open(self) -> bool: ...
```

## Variants

### Variant 1: Detail drawer (right-attached)

Click on a list item in main content → drawer shows detail.

```python
# DESIGN: RULE-SURF-001, RULE-INTER-002, RULE-INTER-005
drawer = Drawer(
    parent=main_window,
    direction="right",
    width=Drawer.WIDTH_MD,  # 400
    backdrop=False,  # dashboard still visible, no dim
    dismiss_on_outside_click=False,  # operator may click dashboard to interact
)

# Header
header = QWidget()
header_layout = QHBoxLayout(header)
header_layout.setContentsMargins(0, 0, 0, 0)
header_layout.setSpacing(theme.SPACE_2)
header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

title = QLabel("Эксперимент calibration_run_042")
title_font = QFont(theme.FONT_BODY, theme.FONT_TITLE_SIZE)
title_font.setWeight(theme.FONT_TITLE_WEIGHT)
title.setFont(title_font)
header_layout.addWidget(title, 1)

close_btn = IconButton("x", tooltip="Закрыть (Esc)")
close_btn.clicked.connect(drawer.close)
header_layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignVCenter)

drawer.set_header(header)

# Content (scrollable)
scroll = QScrollArea()
scroll.setWidgetResizable(True)
scroll.setStyleSheet(f"QScrollArea {{ background: transparent; border: none; }}")

detail_widget = self._build_experiment_detail_widget()
scroll.setWidget(detail_widget)
drawer.set_content(scroll)

drawer.open()
```

### Variant 2: Navigation drawer (left-attached)

Secondary navigation, list of channels, templates.

```python
drawer = Drawer(
    parent=main_window,
    direction="left",
    width=Drawer.WIDTH_SM,  # 320
    backdrop=False,
)

# Typically navigation drawers are toggleable — open via toolbar button
```

### Variant 3: Modal-style drawer (with backdrop)

When drawer's work requires focus, add backdrop dim. Less common.

```python
drawer = Drawer(
    parent=main_window,
    direction="right",
    width=Drawer.WIDTH_LG,  # 480
    backdrop=True,  # darkens rest of UI
    dismiss_on_outside_click=True,  # treat like modal
)
# This is a drawer-shaped Modal. Consider whether actually a Modal is better.
```

## Slide animation

```python
# DESIGN: RULE-INTER-005 — exit shorter than enter
def open(self) -> None:
    self.show()
    if not self._should_animate():
        return
    
    start_x = self._offscreen_x()  # off-viewport initial position
    end_x = self._onscreen_x()
    self._card.setGeometry(start_x, 0, self._width, self.height())
    
    anim = QPropertyAnimation(self._card, b"geometry")
    anim.setDuration(300)  # DURATION_SLOW for enter
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.setStartValue(QRect(start_x, 0, self._width, self.height()))
    anim.setEndValue(QRect(end_x, 0, self._width, self.height()))
    anim.finished.connect(self.opened.emit)
    anim.start()

def close(self) -> None:
    if not self._should_animate():
        self._finalize_close()
        return
    
    start = self._card.geometry()
    end = QRect(self._offscreen_x(), 0, self._width, self.height())
    
    anim = QPropertyAnimation(self._card, b"geometry")
    anim.setDuration(200)  # DURATION_BASE ≈ 67% of 300
    anim.setEasingCurve(QEasingCurve.Type.InCubic)
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.finished.connect(self._finalize_close)
    anim.start()
```

## Coexistence with main content

```python
# When drawer is open WITHOUT backdrop, main content remains interactive.
# Pattern: drawer lives as overlay z-index above main but allows clicks to
# pass through to everything except its own card region.
#
# Qt: the backdrop QWidget can be transparent + no input capture.

# OR (alternative): main content may be pushed aside (main_area width reduced)
# when drawer opens. This requires drawer to be part of main layout,
# not an overlay. Trade-off: more responsive feel but layout refactor.
```

## States

| State | Visual treatment |
|---|---|
| **Closed** | Off-viewport, not in tab order |
| **Opening** | Sliding in, 300ms, ease-out |
| **Open** | Fully visible, focus on first focusable child |
| **Closing** | Sliding out, 200ms, ease-in |

## Common mistakes

1. **Drawer with radius on outer edge.** Right drawer with `RADIUS_MD` on top-right corner — looks like a disconnected card, not an edge-attached panel. Radius only on inner-facing edges.

2. **Missing left border on right drawer.** Without 1px border separator, drawer surface blends into main content surface. Add border on the attachment side.

3. **Drawer height not full viewport.** Right drawer with fixed `max_height` looks floating, not attached. Drawers stretch top-to-bottom (or left-to-right for top/bottom drawers).

4. **Click-outside dismisses when drawer is persistent.** For detail drawers that coexist with dashboard interaction, click on dashboard should NOT close drawer. Configure `dismiss_on_outside_click=False`.

5. **No scrollable content wrapper.** Drawer content exceeds viewport height, content clips. Always wrap content in QScrollArea.

6. **Using drawer for modal-style blocking work.** If operator must complete work before continuing, and work doesn't fit drawer aspect ratio — use Modal. Drawer shape optimized for list or detail pane, not forms.

7. **Backdrop always on.** If drawer is meant to coexist with work, backdrop blocks that. Make backdrop optional (default off for detail drawers).

8. **Keyboard trap when no backdrop.** Without backdrop, Tab key might escape drawer into dashboard. Either trap Tab within drawer, or accept that Tab leaves drawer (acceptable for non-blocking drawers).

## Related components

- `components/modal.md` — Centered blocking alternative
- `components/popover.md` — Smaller anchored alternative
- `components/dialog.md` — Simple Q&A alternative
- `cryodaq-primitives/tool-rail.md` — ToolRail might open drawers for channel lists, templates, etc.

## Changelog

- 2026-04-17: Initial version. 3 variants (detail, navigation, modal-style). `Drawer` class proposed — not yet implemented. CryoDAQ currently uses embedded panels; Phase III may introduce drawers if pattern emerges.
