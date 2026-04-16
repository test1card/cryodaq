---
title: Button
keywords: button, action, click, secondary, ghost, destructive, icon-only, hold-confirm, primary
applies_to: interactive button widgets
status: partial
implements: legacy widgets in src/cryodaq/gui/widgets/* (variants scattered; formalization pending)
last_updated: 2026-04-17
---

# Button

Interactive control that executes an action on click. The primary verb of CryoDAQ UI.

**When to use:**
- Operator-initiated actions (start, save, apply, advance, cancel)
- Triggers for confirmations, dialogs, navigation
- Icon-only controls for high-frequency actions in tight layouts

**When NOT to use:**
- For navigation where the result is "go somewhere" rather than "do something" — use `breadcrumb` or `tab-group`
- For toggle state without action — use a toggle switch or segmented control
- For menus — use `QMenu` with menu items, not a row of buttons
- For destructive actions without confirmation — NEVER. Destructive always goes via confirmation (RULE-INTER-004)

## CryoDAQ button hierarchy

CryoDAQ does NOT have a classic "primary button" (filled ACCENT CTA) because RULE-COLOR-004 reserves ACCENT for focus/selection only. Instead:

| Variant | Role | Visual |
|---|---|---|
| **Secondary** | Standard action, the default button type | Filled `SURFACE_ELEVATED`, 1px `BORDER` |
| **Ghost** | De-emphasized action (cancel, dismiss), toolbar controls | Transparent background, 1px `BORDER`, text-only on hover |
| **Destructive** | Irreversible / emergency action (АВАР. ОТКЛ., Удалить) | Filled `DESTRUCTIVE`, `ON_DESTRUCTIVE` text |
| **Icon-only** | Compact action in tight layout (close, expand, settings) | Square, transparent default, icon color from context |
| **Hold-confirm** | Destructive variant with 1-second press-and-hold safety | Fills progressively during hold (see RULE-INTER-004) |

There is **no filled-accent "primary" variant**. Attempting to add one reintroduces the ACCENT semantic violation.

## Anatomy

```
 Secondary button                Ghost button              Destructive button
┌────────────────────────┐     ┌──────────────────┐      ┌──────────────────┐
│  Начать эксперимент    │     │  Отмена          │      │   АВАР. ОТКЛ.    │
└────────────────────────┘     └──────────────────┘      └──────────────────┘
 bg: SURFACE_ELEVATED           bg: transparent           bg: DESTRUCTIVE
 border: 1px BORDER             border: 1px BORDER        border: none
 text: FOREGROUND               text: FOREGROUND          text: ON_DESTRUCTIVE
 padding: SPACE_3 horiz         padding: SPACE_3 horiz    padding: SPACE_3 horiz
 height: ROW_HEIGHT (36)        height: ROW_HEIGHT (36)   height: ROW_HEIGHT (36)

 Icon-only button
┌───┐
│ × │   size: ROW_HEIGHT × ROW_HEIGHT (36×36) or 32×32 in dense contexts
└───┘   background: transparent, hover MUTED
        icon: SPACE_1 from edges on all sides
```

## Parts

| Part | Required | Description |
|---|---|---|
| **Button body** | Yes | `QPushButton` with stylesheet defining surface, border, radius |
| **Label** | Text variants | Text content, `FONT_LABEL_*` or `FONT_BODY_*` preset |
| **Icon** | Icon-only and mixed variants | SVG from Lucide bundle, color inherited from button text color (RULE-COLOR-005) |
| **Icon + label spacing** | Mixed variants | `SPACE_1` (4px) between icon and text (RULE-SPACE-001) |

## Invariants

1. **Height = ROW_HEIGHT (36)** unless documented exception for emergency or hero action. (RULE-SPACE-007)
2. **Focus ring mandatory.** `:focus` applies 2px `ACCENT` border, replacing 1px `BORDER`. (RULE-INTER-001)
3. **Pressed state visible within 100ms.** `:pressed` darkens background. (RULE-INTER-003)
4. **Cursor `PointingHandCursor` on hover.** (RULE-INTER-011)
5. **Icon-only buttons have tooltip.** Description + shortcut hint when applicable. (RULE-INTER-008)
6. **Icon color inherits from button text color.** No hardcoded icon colors. (RULE-COLOR-005)
7. **Label is imperative verb.** "Начать", "Сохранить", "Применить" — not "Захолаживание" on a start-cooldown button. (RULE-COPY-007)
8. **Destructive action requires confirmation.** Single click does NOT execute destructive. (RULE-INTER-004)
9. **No raw hex.** All color values via `theme.*`. (RULE-COLOR-001)
10. **Uppercase Cyrillic has letter-spacing.** `АВАР. ОТКЛ.` uses `0.05em` tracking. (RULE-TYPO-005)

## API (proposed class hierarchy)

All variants extend `QPushButton` with stylesheet and helper methods.

```python
# src/cryodaq/gui/widgets/buttons.py  (proposed)

class SecondaryButton(QPushButton):
    """Standard action button — filled SURFACE_ELEVATED surface."""
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None: ...

class GhostButton(QPushButton):
    """De-emphasized action — transparent background, border only."""
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None: ...

class DestructiveButton(QPushButton):
    """Irreversible action — filled DESTRUCTIVE. Requires confirmation wrapper."""
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None: ...

class IconButton(QPushButton):
    """Icon-only button. Tooltip required (enforced in __init__)."""
    def __init__(
        self,
        icon_name: str,
        tooltip: str,  # required, not optional
        parent: QWidget | None = None,
        *,
        size: int = 36,
    ) -> None: ...

class HoldConfirmButton(QPushButton):
    """Destructive action with hold-to-confirm. Emits `triggered` after 1s hold."""
    triggered = Signal()
    CONFIRM_DURATION_MS = 1000
    
    def __init__(self, text: str, parent: QWidget | None = None) -> None: ...
```

## Variants

### Variant 1: Secondary (default)

Standard action button. Use for most buttons.

```python
# DESIGN: RULE-SPACE-007, RULE-INTER-001, RULE-INTER-011, RULE-COPY-007
button = QPushButton("Сохранить")  # imperative verb
button.setFixedHeight(theme.ROW_HEIGHT)
button.setCursor(Qt.CursorShape.PointingHandCursor)
button.setStyleSheet(f"""
    QPushButton {{
        background: {theme.SURFACE_ELEVATED};
        border: 1px solid {theme.BORDER};
        border-radius: {theme.RADIUS_SM}px;
        color: {theme.FOREGROUND};
        padding: 0 {theme.SPACE_3}px;
        font-family: "{theme.FONT_BODY}";
        font-size: {theme.FONT_LABEL_SIZE}px;
        font-weight: {theme.FONT_WEIGHT_MEDIUM};
    }}
    QPushButton:hover {{
        background: {theme.MUTED};
    }}
    QPushButton:pressed {{
        background: {theme.BORDER};
    }}
    QPushButton:focus {{
        border: 2px solid {theme.ACCENT};
    }}
    QPushButton:disabled {{
        color: {theme.TEXT_DISABLED};
        background: {theme.SURFACE_CARD};
    }}
""")
```

### Variant 2: Ghost

De-emphasized action, dismiss, cancel. Transparent background.

```python
# DESIGN: RULE-COLOR-006
cancel_button = QPushButton("Отмена")
cancel_button.setFixedHeight(theme.ROW_HEIGHT)
cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
cancel_button.setStyleSheet(f"""
    QPushButton {{
        background: transparent;
        border: 1px solid {theme.BORDER};
        border-radius: {theme.RADIUS_SM}px;
        color: {theme.FOREGROUND};
        padding: 0 {theme.SPACE_3}px;
    }}
    QPushButton:hover {{
        background: {theme.MUTED};  /* subtle, not ACCENT */
    }}
    QPushButton:pressed {{
        background: {theme.BORDER};
    }}
    QPushButton:focus {{
        border: 2px solid {theme.ACCENT};
    }}
""")
```

### Variant 3: Destructive

Irreversible action. MUST be wrapped in confirmation pattern (hold-to-confirm or modal dialog per RULE-INTER-004).

```python
# DESIGN: RULE-COLOR-007, RULE-TYPO-005, RULE-TYPO-008
emergency_font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
emergency_font.setWeight(theme.FONT_WEIGHT_SEMIBOLD)
emergency_font.setLetterSpacing(
    QFont.SpacingType.AbsoluteSpacing, 0.05 * theme.FONT_LABEL_SIZE
)

button = QPushButton("АВАР. ОТКЛ.")  # uppercase Cyrillic category label
button.setFont(emergency_font)
button.setFixedHeight(theme.ROW_HEIGHT)
button.setCursor(Qt.CursorShape.PointingHandCursor)
button.setStyleSheet(f"""
    QPushButton {{
        background: {theme.DESTRUCTIVE};
        border: none;
        border-radius: {theme.RADIUS_SM}px;
        color: {theme.ON_DESTRUCTIVE};
        padding: 0 {theme.SPACE_3}px;
    }}
    QPushButton:hover {{
        /* Subtle darkening via opacity layer — or darker STATUS_FAULT shade */
        background: {theme.STATUS_FAULT};  /* same hex, semantic ambiguity acceptable in :hover */
    }}
    QPushButton:pressed {{
        background: #a53838;  /* DESIGN: RULE-COLOR-001 exception:
                                     pressed-darker variant; should be promoted to theme token
                                     as DESTRUCTIVE_PRESSED */
    }}
    QPushButton:focus {{
        border: 2px solid {theme.ACCENT};
    }}
""")
# Do NOT connect .clicked directly to destructive action — use HoldConfirmButton
# or wrap in confirmation dialog (RULE-INTER-004)
```

> **Note:** The `#a53838` in `:pressed` is a documented exception: CryoDAQ theme does not yet have `DESTRUCTIVE_PRESSED`. This should be promoted to a theme token — tracked as governance follow-up.

### Variant 4: Icon-only

Compact control. Tooltip MANDATORY.

```python
# DESIGN: RULE-INTER-008
close_button = QPushButton()
close_button.setFixedSize(theme.ROW_HEIGHT, theme.ROW_HEIGHT)
close_button.setCursor(Qt.CursorShape.PointingHandCursor)
close_button.setIcon(
    load_colored_icon("x", color=theme.MUTED_FOREGROUND)  # DESIGN: RULE-COLOR-005
)
close_button.setIconSize(QSize(theme.ICON_SIZE_MD, theme.ICON_SIZE_MD))
close_button.setToolTip("Закрыть (Esc)")  # MANDATORY description + shortcut
close_button.setStyleSheet(f"""
    QPushButton {{
        background: transparent;
        border: none;
        border-radius: {theme.RADIUS_SM}px;
    }}
    QPushButton:hover {{
        background: {theme.MUTED};
    }}
    QPushButton:focus {{
        border: 2px solid {theme.ACCENT};
    }}
""")
```

### Variant 5: Icon + label

Mixed icon and text. Gap between: `SPACE_1` (4px).

```python
# DESIGN: RULE-SPACE-001, RULE-SPACE-008
button = QPushButton()
button.setFixedHeight(theme.ROW_HEIGHT)
button.setCursor(Qt.CursorShape.PointingHandCursor)

icon = load_colored_icon("play", color=theme.FOREGROUND)
button.setIcon(icon)
button.setIconSize(QSize(theme.ICON_SIZE_SM, theme.ICON_SIZE_SM))
button.setText("Начать")

button.setStyleSheet(f"""
    QPushButton {{
        background: {theme.SURFACE_ELEVATED};
        border: 1px solid {theme.BORDER};
        border-radius: {theme.RADIUS_SM}px;
        color: {theme.FOREGROUND};
        padding: 0 {theme.SPACE_3}px;
        /* Qt controls icon-to-text spacing via iconSize + padding; for fine
           control use HBoxLayout inside custom widget */
    }}
""")
```

### Variant 6: Hold-confirm

Destructive action with 1-second press-and-hold safety. See RULE-INTER-004.

```python
class HoldConfirmButton(QPushButton):
    """Press-and-hold to confirm destructive action.
    
    Emits `triggered` after 1000ms continuous hold.
    """
    triggered = Signal()
    CONFIRM_DURATION_MS = 1000
    
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(text, parent)
        self._progress = 0.0  # 0.0 to 1.0
        
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._emit_triggered)
        
        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._tick_progress)
        self._animation_timer.setInterval(16)  # ~60 fps
        
        self.setFixedHeight(theme.ROW_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Apply destructive styling (as per Variant 3)
    
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_hold()
    
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._cancel_hold()
    
    def _start_hold(self):
        self._progress = 0.0
        self._timer.start(self.CONFIRM_DURATION_MS)
        self._animation_timer.start()
    
    def _cancel_hold(self):
        self._timer.stop()
        self._animation_timer.stop()
        self._progress = 0.0
        self.update()
    
    def _tick_progress(self):
        if self._timer.isActive():
            remaining = self._timer.remainingTime()
            elapsed = self.CONFIRM_DURATION_MS - remaining
            self._progress = elapsed / self.CONFIRM_DURATION_MS
            self.update()
    
    def _emit_triggered(self):
        self._animation_timer.stop()
        self._progress = 1.0
        self.triggered.emit()
        self._progress = 0.0
        self.update()
    
    def paintEvent(self, event):
        super().paintEvent(event)
        if 0 < self._progress < 1:
            # Paint progress indicator — subtle overlay fill from left to right
            from PySide6.QtGui import QPainter, QColor
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            fill_width = int(self.width() * self._progress)
            overlay = QColor(theme.ON_DESTRUCTIVE)
            overlay.setAlpha(40)  # subtle
            painter.fillRect(0, 0, fill_width, self.height(), overlay)
            painter.end()
```

## States

| State | Visual treatment |
|---|---|
| **Default** | Per variant (secondary/ghost/destructive/icon-only) |
| **Hover** | `MUTED` background overlay (for filled) or subtle tint (for ghost). (RULE-COLOR-006) |
| **Pressed** | Darker than hover. `BORDER` color or specific `_PRESSED` token if defined |
| **Focus** | 2px `ACCENT` border replacing 1px `BORDER`. Always visible — never suppress via `outline: none` without replacement (RULE-INTER-001) |
| **Disabled** | Color → `TEXT_DISABLED`; background → `SURFACE_CARD`; cursor `ArrowCursor`. Opacity or separate disabled tokens both acceptable |
| **Loading / Pending** | Disable button + replace text with pending verb ("Запуск...") + optionally small spinner icon |
| **Success echo** (after accepted action) | 300ms `STATUS_OK` border flash, then revert. (RULE-INTER-007) |

## Sizing

| Context | Height | Width | Padding |
|---|---|---|---|
| Default | `ROW_HEIGHT` (36) | content-sized with min 80 | `SPACE_3` horizontal |
| Compact (dense toolbar) | 32 | content-sized with min 64 | `SPACE_2` horizontal |
| Hero / emergency | 48 | content-sized with min 120 | `SPACE_4` horizontal |
| Icon-only default | 36×36 | — | — |
| Icon-only compact | 32×32 | — | — |

Any other size requires documented reason.

## Common mistakes

1. **Using ACCENT as button background.** Primary-button pattern with ACCENT filled background violates RULE-COLOR-004. CryoDAQ has no filled-accent CTA. Use Secondary (filled SURFACE_ELEVATED) instead.

2. **Single-click destructive.** Connecting `emergency_button.clicked` directly to `emergency_stop()` without confirmation. RULE-INTER-004. Always wrap in HoldConfirmButton or modal confirmation.

3. **Missing tooltip on icon-only.** Icon buttons without `setToolTip()` leave operators guessing. RULE-INTER-008.

4. **Hardcoded icon color.** Icons must recolor to match button text color (via `load_colored_icon` helper or preprocessed SVG). RULE-COLOR-005.

5. **Descriptive label on action button.** "Захолаживание" on a start button is ambiguous (is this a state or an action?). Use "Начать захолаживание" imperative. RULE-COPY-007.

6. **Hover = ACCENT.** Hover background should be `MUTED`, never `ACCENT`. Conflating hover with focus destroys keyboard nav affordance. RULE-COLOR-006.

7. **Missing focus ring.** `outline: none` without replacement focus style. RULE-INTER-001.

8. **Ad-hoc height.** Button height 40 or 34 or 38 for no reason. Default is 36. Use documented exceptions for hero/compact. RULE-SPACE-007.

9. **Cyrillic uppercase without letter-spacing.** "АВАР. ОТКЛ." cramps without `0.05em` tracking. RULE-TYPO-005.

## Related components

- `components/dialog.md` — Dialog uses buttons in footer action row; patterns for confirm/cancel layout
- `components/modal.md` — Modal close button is typically an IconButton
- `cryodaq-primitives/phase-stepper.md` — Phase advance buttons combine success echo (RULE-INTER-007)
- `components/input-field.md` — Input + button pairs (form fields, search boxes)

## Changelog

- 2026-04-17: Initial version. 6 variants (Secondary, Ghost, Destructive, Icon-only, Icon+label, Hold-confirm). API proposed — `buttons.py` module does not yet exist; current legacy widgets use ad-hoc stylesheets. Phase II task will formalize hierarchy per this spec.
