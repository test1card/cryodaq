---
title: Modal
keywords: modal, overlay, card, backdrop, escape, centered, focus-trap, dismissible
applies_to: full-viewport overlay with centered card and dimmed backdrop
status: active
implements: src/cryodaq/gui/shell/overlays/_design_system/modal_card.py
last_updated: 2026-04-17
references: rules/surface-rules.md, rules/interaction-rules.md, tokens/elevation.md
---

# Modal

Centered overlay card with dimmed backdrop. Blocks interaction with content beneath. Dismissible via close button or Escape.

> **Implementation status.** This spec defines the canonical target. The shipped code at `src/cryodaq/gui/shell/overlays/_design_system/modal_card.py` currently implements a low-level `ModalCard` container with backdrop click, close button, Escape-to-close, and a single `set_content()` insertion API. It does not implement the richer API shape used in this spec's examples (`set_header`, `set_footer`, `open()`), does not trap focus within the card, and does not restore focus to the previously focused control on close. `showEvent()` only focuses the wrapper widget itself. Code alignment is tracked as Phase II work. New development should follow this spec even where the shipped code diverges.

**When to use:**
- Drilling into detail from dashboard (drill-down pattern — breadcrumb back to parent)
- Multi-field workflows that don't fit as inline panel (create experiment, bulk action)
- Content that deserves operator's full attention without competing context
- Confirmations that need richer structure than a simple Dialog (e.g., confirm + show impact)

**When NOT to use:**
- Simple yes/no question — use `Dialog` (`components/dialog.md`) — simpler, faster
- Anchored to specific trigger element — use `Popover` (`components/popover.md`)
- Transient notification — use `Toast` (`components/toast.md`)
- Side panel that slides in without dimming — use `Drawer` (`components/drawer.md`)
- For full-screen views (no backdrop, no dismiss) — that's a page, not a modal

## Anatomy

```
┌───────────────────────────────────────────────────────────────┐
│  ◀── backdrop: SURFACE_OVERLAY_RGBA (rgba dim over viewport)  │
│                                                               │
│         ┌─────────────────────────────────────────┐           │
│         │ ◀── modal card: SURFACE_ELEVATED surface │           │
│         │     radius: RADIUS_LG, border 1px BORDER │           │
│         │                                          │           │
│         │  ┌──────────────────────────┬────┐       │           │
│         │  │ header_slot              │ ×  │       │           │
│         │  │ (breadcrumb or title)    │    │       │           │
│         │  └──────────────────────────┴────┘       │           │
│         │                                          │           │
│         │  ┌────────────────────────────────┐      │           │
│         │  │ content_host (transparent)     │      │           │
│         │  │                                │      │           │
│         │  │  BentoGrid or form or custom   │      │           │
│         │  │                                │      │           │
│         │  └────────────────────────────────┘      │           │
│         │                                          │           │
│         │  ┌────────────────────────────────┐      │           │
│         │  │ footer_slot (optional actions) │      │           │
│         │  └────────────────────────────────┘      │           │
│         └─────────────────────────────────────────┘           │
│                                                               │
└───────────────────────────────────────────────────────────────┘
  ◀── viewport margin: min SPACE_5 (24) on all sides
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Viewport overlay** | Yes | Fills entire parent; backdrop-dim layer |
| **Backdrop** | Yes | `SURFACE_OVERLAY_RGBA` semi-transparent dim; dismissible on click (optional per config) |
| **Modal card** | Yes | Centered `QFrame` with single painted surface — inherits Card anatomy |
| **Header row** | Yes | Single-row `QHBoxLayout` with header_slot (expanding) + close button (fixed 32×32, AlignVCenter) |
| **Content host** | Yes | Transparent wrapper for modal body |
| **Footer slot** | Optional | Actions row (e.g., Отмена / Применить) |

## Invariants

1. **One card surface.** Header row, content host, footer slot all transparent. (RULE-SURF-001, RULE-SURF-007)
2. **Single header baseline.** Breadcrumb/title and close button on one HBox row, AlignVCenter. NOT two stacked rows, NOT absolute-positioned close. (RULE-SURF-004)
3. **Symmetric card padding.** `SPACE_5` all sides. (RULE-SURF-003)
4. **Radius cascade.** Modal card `RADIUS_LG`; children use smaller. (RULE-SURF-006)
5. **Max width clamped.** Respect the proposed `OVERLAY_MAX_WIDTH` cap (~1400px) and leave minimum `SPACE_5` backdrop margin on all sides. (RULE-SURF-009)
6. **Modal shadow permitted.** The one exception to zero-shadow policy. (RULE-SURF-010)
7. **Escape dismisses.** `keyPressEvent` handles `Qt::Key_Escape` → close. (RULE-INTER-002)
8. **Focus trap while open.** Keyboard focus stays within modal until dismissed. Implementation: install event filter or use `setWindowModality`.
9. **Open animation asymmetric.** Exit faster than enter. (RULE-INTER-005)
10. **Not stackable with self.** No "modal over modal" — that's two drill-down levels done wrong. (RULE-SURF-005)

## API

Current reference implementation (`modal_card.py`):

```python
class ModalCard(QWidget):
    """Drill-down modal with breadcrumb header and content host."""
    
    closed = Signal()
    
    DEFAULT_MAX_WIDTH = 1400  # proposed OVERLAY_MAX_WIDTH; not yet a formal token
    DEFAULT_MAX_HEIGHT_VH = 0.9
    
    def __init__(
        self,
        parent: QWidget,
        *,
        max_width: int = DEFAULT_MAX_WIDTH,
        max_height_vh_pct: float = DEFAULT_MAX_HEIGHT_VH,
        backdrop_dismisses: bool = True,
    ) -> None: ...
    
    def set_header(self, widget: QWidget) -> None:
        """Install widget (typically DrillDownBreadcrumb or title) into header slot."""
    
    def set_content(self, widget: QWidget) -> None:
        """Install modal body content."""
    
    def set_footer(self, widget: QWidget | None) -> None:
        """Install footer actions row (optional)."""
    
    def open(self) -> None:
        """Show modal with enter animation."""
    
    def close(self) -> None:
        """Close with exit animation. Emits `closed` on finish."""
```

## Variants

### Variant 1: Drill-down modal

Dashboard → tile click → modal with detail. Header contains `DrillDownBreadcrumb`. Most common variant.

```python
# DESIGN: RULE-INTER-002 (Escape), RULE-SURF-009 (max width)
modal = ModalCard(parent=main_window)

breadcrumb = DrillDownBreadcrumb([
    DrillDownCrumb("Дашборд", handler=lambda: modal.close()),
    DrillDownCrumb("Датчики"),  # current — non-interactive
])
modal.set_header(breadcrumb)

sensor_grid = BentoGrid()
# ... populate
modal.set_content(sensor_grid)

modal.open()
```

### Variant 2: Form modal

Multi-field input. Header = title label (not breadcrumb). Footer = actions.

```python
# DESIGN: RULE-COPY-007 (imperative buttons)
modal = ModalCard(parent=main_window, max_width=720)  # narrower for form

title = QLabel("Создать эксперимент")
title_font = QFont(theme.FONT_BODY, theme.FONT_TITLE_SIZE)
title_font.setWeight(theme.FONT_TITLE_WEIGHT)
title.setFont(title_font)
modal.set_header(title)

form_widget = QWidget()
form_layout = QVBoxLayout(form_widget)
form_layout.addWidget(name_field)
form_layout.addWidget(template_select)
# ...
modal.set_content(form_widget)

actions = QWidget()
actions_layout = QHBoxLayout(actions)
actions_layout.setContentsMargins(0, 0, 0, 0)
actions_layout.setSpacing(theme.SPACE_2)
actions_layout.addStretch()
actions_layout.addWidget(cancel_button)   # «Отмена»
actions_layout.addWidget(create_button)   # «Создать»
modal.set_footer(actions)

modal.open()
```

### Variant 3: Confirmation modal (richer than Dialog)

Use when confirmation needs context beyond one-liner. For simple yes/no, use `Dialog` instead.

```python
modal = ModalCard(parent=main_window, max_width=560)

title = QLabel("Прервать эксперимент?")
title_font = QFont(theme.FONT_BODY, theme.FONT_TITLE_SIZE)
title_font.setWeight(theme.FONT_TITLE_WEIGHT)
title.setFont(title_font)
modal.set_header(title)

# Rich body: impact description + checkbox options
body = QWidget()
body_layout = QVBoxLayout(body)
body_layout.addWidget(QLabel(
    "Эксперимент 'calibration_run_042' выполняется 47 минут.\n"
    "Собранные данные будут сохранены в архив."
))
save_raw = QCheckBox("Также экспортировать сырые данные в CSV")
body_layout.addWidget(save_raw)
modal.set_content(body)

# Destructive action with ghost cancel
actions = ...  # GhostButton(«Отмена»), DestructiveButton(«Прервать»)
modal.set_footer(actions)

modal.open()
```

## States

| State | Visual treatment |
|---|---|
| **Opening** | Fade-in over 200-300ms with enter easing (RULE-INTER-005) |
| **Open** | Fully visible, backdrop dim, focus trapped inside |
| **Closing** | Fade-out over 150-200ms (60-70% of enter duration) |
| **Closed** | Hidden; removed from layout; `closed` signal emitted |

## Key implementation patterns

### Backdrop dim

```python
# DESIGN: RULE-COLOR-001
self.setStyleSheet(f"""
    QWidget#modalBackdrop {{
        background: {theme.SURFACE_OVERLAY_RGBA};  /* rgba(0,0,0,0.6) or similar */
    }}
""")
# Modal card is child of backdrop; backdrop fills parent via resize event
```

### Centering on resize

```python
def _reposition_card(self) -> None:
    if self.width() <= 0 or self.height() <= 0:
        return
    
    outer_margin = theme.SPACE_5
    available_width = max(0, self.width() - 2 * outer_margin)
    available_height = max(0, int(self.height() * self._max_height_vh_pct))
    
    card_width = min(self._max_width, available_width)
    card_height = min(available_height, self._card.sizeHint().height())
    
    x = (self.width() - card_width) // 2
    y = (self.height() - card_height) // 2
    self._card.setGeometry(QRect(x, y, card_width, card_height))

def resizeEvent(self, event):
    super().resizeEvent(event)
    self._reposition_card()
```

### Escape handling

```python
# DESIGN: RULE-INTER-002
def keyPressEvent(self, event: QKeyEvent) -> None:
    if event.key() == Qt.Key.Key_Escape:
        self.close()
        event.accept()
    else:
        super().keyPressEvent(event)
```

### Asymmetric animation

```python
# DESIGN: RULE-INTER-005
def open(self) -> None:
    self.show()
    if not self._should_animate():
        return
    anim = QPropertyAnimation(self, b"windowOpacity")
    anim.setDuration(300)  # DURATION_SLOW
    anim.setEasingCurve(QEasingCurve.Type.OutQuad)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.start()

def close(self) -> None:
    if not self._should_animate():
        self._finalize_close()
        return
    anim = QPropertyAnimation(self, b"windowOpacity")
    anim.setDuration(200)  # DURATION_BASE (67% of 300)
    anim.setEasingCurve(QEasingCurve.Type.InQuad)
    anim.setStartValue(1.0)
    anim.setEndValue(0.0)
    anim.finished.connect(self._finalize_close)
    anim.start()

def _finalize_close(self) -> None:
    self.hide()
    self.closed.emit()
```

### Shadow (the permitted exception)

```python
# DESIGN: RULE-SURF-010 exception
shadow = QGraphicsDropShadowEffect()
shadow.setBlurRadius(24)
shadow.setOffset(0, 8)
shadow.setColor(QColor(0, 0, 0, int(255 * 0.4)))
self._card.setGraphicsEffect(shadow)
```

## Common mistakes

1. **Close button in own row above content.** Two-band header wastes space and violates RULE-SURF-004. Close goes in single HBox with header content.

2. **Absolute positioning the close button.** `self._close_button.move(x, y)` creates fragility on resize. Use layout. (Historical Phase I.1 regression `d87c24b`, fixed `cf72942`.)

3. **Nesting a modal inside a modal.** Two drill-down levels means restructure — the second level should be its own stack or inline panel. (RULE-SURF-005)

4. **Backdrop click always dismisses.** For destructive-path modals (prevent data loss), backdrop click may not be safe. Use `backdrop_dismisses=False` and require explicit close/cancel.

5. **No focus trap.** Tab key escapes modal into background UI. Install event filter or use `setWindowModality(Qt.ApplicationModal)`.

6. **Symmetric open/close animations.** Equal-duration exit feels sluggish. Exit should be 60-70% of enter. (RULE-INTER-005)

7. **Fade-in on fault/alarm modal.** Fault modal should appear instantly, not animate in. RULE-INTER-006. (Rare case — fault-triggered modal is unusual; most faults use banners or toasts.)

8. **Modal without Escape handler.** Operator hits Escape, nothing happens. RULE-INTER-002.

9. **Clamping max_height before viewport.** Must clamp to both `DEFAULT_MAX_HEIGHT_VH * viewport_height` AND `max_height` token. Clamping only one lets modal overflow viewport on small screens.

## Related components

- `components/card.md` — Modal extends Card with overlay behavior
- `components/dialog.md` — Simpler yes/no alternative to confirmation modals
- `components/popover.md` — Smaller, anchored alternative for contextual content
- `components/breadcrumb.md` — Typical header content for drill-down modals

## Changelog

- 2026-04-17: Initial version documenting Phase I.1 implementation. 3 variants (drill-down, form, confirmation). All invariants derived from Phase I.1 regressions (commits `e25bbd9`, `d87c24b`, `cf72942`).
