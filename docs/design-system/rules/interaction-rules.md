---
title: Interaction Rules
keywords: interaction, focus, hover, cursor, click, press, feedback, shortcut, escape, tooltip, confirmation, affordance
applies_to: all interactive widgets
enforcement: strict
priority: critical
last_updated: 2026-04-17
status: canonical
---

# Interaction Rules

Enforcement rules for how widgets respond to user input. Focus, hover, click, keyboard navigation, destructive actions. Violations cost operators time and create stress.

Enforce in code via `# DESIGN: RULE-INTER-XXX` comment marker.

**Rule index:**
- RULE-INTER-001 — Focus ring mandatory on interactive widgets
- RULE-INTER-002 — Escape dismisses overlays (innermost first)
- RULE-INTER-003 — Press feedback within 100ms
- RULE-INTER-004 — Destructive actions require confirmation
- RULE-INTER-005 — Exit animation shorter than enter animation
- RULE-INTER-006 — Faults appear instantly, no fade-in
- RULE-INTER-007 — Success echo after accepted action
- RULE-INTER-008 — Icon-only button requires tooltip
- RULE-INTER-009 — Keyboard shortcut from central registry
- RULE-INTER-010 — No shortcut collision between global and context
- RULE-INTER-011 — Pointer cursor on clickable elements
- RULE-INTER-012 — Affordance visible by default, not hover-only

---

## RULE-INTER-001: Focus ring mandatory on interactive widgets

**TL;DR:** Every keyboard-focusable widget MUST show visible 2px `theme.ACCENT` focus ring when focused. `outline: none` without replacement is forbidden.

**Statement:** All interactive widgets (buttons, inputs, list items, tabs, clickable cards) MUST render a visible focus outline when they receive keyboard focus. Satisfies WCAG 2.4.7 (Focus Visible) and is fundamental for keyboard navigation.

**Rationale:** Keyboard users depend on focus ring to know "where am I?" on the page. Without visible focus, keyboard navigation is blind. Operators using Tab + shortcuts cannot function if focus is invisible.

**Applies to:** buttons, inputs, list items, tabs, any QWidget with `Qt.StrongFocus` or `Qt.TabFocus`

**Example (good):**

```python
# DESIGN: RULE-INTER-001
button.setStyleSheet(f"""
    QPushButton {{
        background: {theme.SURFACE_CARD};
        border: 1px solid {theme.BORDER};
        border-radius: {theme.RADIUS_SM}px;
        color: {theme.FOREGROUND};
        padding: 0 {theme.SPACE_3}px;
    }}
    QPushButton:hover {{ background: {theme.MUTED}; }}
    QPushButton:focus {{
        border: 2px solid {theme.ACCENT};
        outline: none;
    }}
    QPushButton:pressed {{ background: {theme.BORDER}; }}
""")
```

**Example (bad):**

```python
# No :focus state defined — keyboard users blind
button.setStyleSheet(f"QPushButton {{ background: {theme.SURFACE_CARD}; }}")

# Suppressed outline without replacement — WCAG violation
button.setStyleSheet("QPushButton:focus { outline: none; }")
```

**Exception:** Widgets with `Qt.NoFocus` policy (pure display) don't need focus ring. Verify via `widget.focusPolicy()`.

**Related rules:** RULE-COLOR-004 (ACCENT semantic), RULE-INTER-011 (cursor), RULE-A11Y-001 (tab order)

---

## RULE-INTER-002: Escape dismisses overlays (innermost first)

**TL;DR:** Escape MUST close the topmost overlay. Modal → Popover → Tooltip — Escape pops one at a time, not all at once.

**Statement:** Every overlay widget (modal, popover, dialog, drawer) MUST respond to `Qt.Key_Escape` by closing itself. When overlays stack, Escape closes the innermost (topmost Z) first.

**Rationale:** Escape is the universal "get me out" key. Silent Escape creates trap feeling. Catastrophic Escape (closes everything) loses context.

**Applies to:** ModalCard, Popover, Dialog, Drawer

**Example (good):**

```python
# DESIGN: RULE-INTER-002
class ModalCard(QWidget):
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            event.accept()
        else:
            super().keyPressEvent(event)
```

**Example (bad):**

```python
# Overlay ignores Escape — user feels trapped
class BrokenModal(QWidget):
    def keyPressEvent(self, event):
        super().keyPressEvent(event)

# Escape closes ALL stacked overlays — loses context
def keyPressEvent(self, event):
    if event.key() == Qt.Key.Key_Escape:
        for overlay in self._overlays:
            overlay.close()  # WRONG — close innermost only
```

**Related rules:** RULE-SURF-005 (no nested modals), `tokens/keyboard-shortcuts.md`

---

## RULE-INTER-003: Press feedback within 100ms

**TL;DR:** User clicks → visual state change within 100ms. Even if async action pending, immediate visual acknowledgement prevents re-click.

**Statement:** When operator clicks an interactive element, widget MUST show pressed/active visual state within 100ms of mousedown. Applies even when triggered action is asynchronous — visual feedback is independent of command completion.

**Rationale:** Operator clicks, nothing happens visibly, assumes miss, clicks again. Second click triggers duplicate command. For destructive or toggle actions, this is bug-territory. Immediate visual echo prevents double-click errors.

**Applies to:** all interactive controls

**Example (good):**

```python
# DESIGN: RULE-INTER-003
# Qt :pressed state — immediate
button.setStyleSheet(f"""
    QPushButton {{ background: {theme.SURFACE_CARD}; }}
    QPushButton:pressed {{ background: {theme.BORDER}; }}
""")

# Async action with pending state
def _on_start_clicked(self):
    self.start_button.setEnabled(False)
    self.start_button.setText("Запуск...")
    self._engine.send_command("start_experiment", callback=self._on_started)

def _on_started(self, success: bool):
    self.start_button.setEnabled(True)
    self.start_button.setText("Начать эксперимент")
    if success:
        self._success_echo(self.start_button)
```

**Example (bad):**

```python
# No pressed state, no loading — silent 2s while async fires
def _on_start_clicked(self):
    self._engine.send_command("start_experiment")  # user re-clicks meanwhile
```

**Related rules:** RULE-INTER-007 (success echo), RULE-INTER-012 (affordance visible)

---

## RULE-INTER-004: Destructive actions require confirmation

**TL;DR:** Emergency stop, delete, irreversible actions CANNOT execute on single click. Use hold-to-confirm (1s) or modal dialog.

**Statement:** Destructive actions — emergency stop (АВАР. ОТКЛ.), delete experiment, clear archive, overwrite configuration — MUST use one of:

- **Pattern A: Hold-to-confirm** (recommended for emergency) — press + hold 1s with progress indicator; release before 1s cancels
- **Pattern B: Modal dialog** (recommended for non-urgent destructive) — click opens confirmation; default focus on Cancel, destructive button in DESTRUCTIVE color; Escape cancels
- **Pattern C: Double-click** (not recommended — acceptable only for reversible)

**Rationale:** Single click is too easy. Operator in stress may click wrong button by reflex. Confirmation gives 1-2 seconds to catch error. Emergency stop peculiar: must be easy (it IS the emergency) but not accidental. Hold-to-confirm: 1s is deliberate but fast.

**Applies to:** АВАР. ОТКЛ., delete actions, configuration overwrites, irreversible state changes

**Example (good — hold-to-confirm):**

```python
# DESIGN: RULE-INTER-004
class HoldConfirmButton(QPushButton):
    CONFIRM_DURATION_MS = 1000
    triggered = Signal()
    
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.triggered.emit)
    
    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._timer.start(self.CONFIRM_DURATION_MS)
        self._animate_progress()
    
    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self._timer.stop()
        self._reset_progress()
```

**Example (good — modal confirmation):**

```python
# DESIGN: RULE-INTER-004
def _on_delete_clicked(self):
    dialog = QMessageBox(self)
    dialog.setWindowTitle("Удалить эксперимент?")
    dialog.setText(f"Удалить '{self._name}'? Действие необратимо.")
    cancel = dialog.addButton("Отмена", QMessageBox.RejectRole)
    delete = dialog.addButton("Удалить", QMessageBox.DestructiveRole)
    delete.setStyleSheet(
        f"background: {theme.DESTRUCTIVE}; color: {theme.ON_DESTRUCTIVE};"
    )
    dialog.setDefaultButton(cancel)  # safe default
    dialog.exec()
    if dialog.clickedButton() == delete:
        self._execute_delete()
```

**Example (bad):**

```python
# Emergency stop on single click — no confirmation
emergency_button.clicked.connect(self._execute_emergency_stop)  # WRONG

# Delete on single click — data loss risk
delete_button.clicked.connect(self._delete_experiment)  # WRONG
```

**Related rules:** RULE-COLOR-007 (DESTRUCTIVE token), `patterns/destructive-actions.md`

---

## RULE-INTER-005: Exit animation shorter than enter

**TL;DR:** Exit duration = 60-70% of enter duration. Enter `DURATION_SLOW` (300ms), exit `DURATION_BASE` (200ms). Equal durations make exits feel sluggish.

**Statement:** Paired animations (appearing, then disappearing) use asymmetric durations. Enter: 200-300ms. Exit: 60-70% of enter — typically 150-200ms.

**Rationale:** Users perceive duration asymmetrically. Appearance = "take your time to notice." Disappearance = "don't slow me down." Equal durations make exits drag. 60-70% ratio feels natural. Aligns with Material Design motion research.

**Applies to:** modal open/close, drawer slide, panel reveal, dropdown show/hide

**Example (good):**

```python
# DESIGN: RULE-INTER-005
def open_modal(self):
    if self.should_animate():
        anim = QPropertyAnimation(self._card, b"opacity")
        anim.setDuration(300)  # DURATION_SLOW
        anim.setEasingCurve(QEasingCurve.OutQuad)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()

def close_modal(self):
    if self.should_animate():
        anim = QPropertyAnimation(self._card, b"opacity")
        anim.setDuration(200)  # DURATION_BASE = 67% of 300
        anim.setEasingCurve(QEasingCurve.InQuad)
        anim.finished.connect(self.hide)
        anim.start()
```

**Example (bad):**

```python
# Equal durations — exit drags
open_anim.setDuration(300)
close_anim.setDuration(300)  # WRONG — 100% ratio

# Exit LONGER than enter — inverted
open_anim.setDuration(200)
close_anim.setDuration(400)  # WRONG
```

**Related rules:** `tokens/motion.md`, RULE-A11Y-004 (reduced motion)

---

## RULE-INTER-006: Faults appear instantly, no fade-in

**TL;DR:** FAULT state, emergency indicators, critical alarms — NO animation. Instant state change. Fade-in obscures the critical moment.

**Statement:** When system enters FAULT state or critical alarm triggers, visual indicators (red banner, fault badge) MUST appear via instant state change — no opacity fade, no slide-in, no scale animation. Exception to normal enter-animation patterns.

**Rationale:** Fault state is the most important information. Animating its appearance means 150-300ms window where operator sees "something changing but not yet red." That window is exactly when operator needs the info most. Aesthetic sacrifice (harsh snap) is worth it for safety.

**Applies to:** fault banners, emergency indicators, critical alarm visuals

**Example (good):**

```python
# DESIGN: RULE-INTER-006
def on_fault_detected(self, fault_info):
    # Instant — no animation
    self._fault_banner.setStyleSheet(
        f"background: {theme.STATUS_FAULT}; color: {theme.ON_DESTRUCTIVE};"
    )
    self._fault_banner.setText(f"АВАРИЯ: {fault_info.description}")
    self._fault_banner.setVisible(True)
```

**Example (bad):**

```python
# Fade-in on fault — obscures critical moment
def on_fault_detected(self, fault_info):
    anim = QPropertyAnimation(self._fault_banner, b"opacity")
    anim.setDuration(300)  # WRONG — delays critical info
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    self._fault_banner.setVisible(True)
    anim.start()
```

**Exception:** Exit of fault state (when cleared/acknowledged) MAY fade at `DURATION_FAST` (150ms). Urgency past; fade communicates "acknowledged."

**Related rules:** RULE-INTER-005 (async open/close), `tokens/motion.md`

---

## RULE-INTER-007: Success echo after accepted action

**TL;DR:** Action succeeds → brief `STATUS_OK` flash for ~300ms on triggering element. Operator sees proof it worked.

**Statement:** After user-initiated action completes successfully, triggering element (or nearby indicator) briefly changes to `STATUS_OK` color for `DURATION_SLOW` (300ms), then reverts. Transient acknowledgement, not persistent success state.

**Rationale:** Without echo, operator sees no evidence click registered. Might re-click, causing duplicate command. Echo closes feedback loop: click → press state → pending → echo → done.

**Applies to:** action buttons (submit, save, start, apply), successful async operations

**Example (good):**

```python
# DESIGN: RULE-INTER-007
def _success_echo(self, widget):
    original = widget.styleSheet()
    widget.setStyleSheet(
        original + f"QPushButton {{ border: 2px solid {theme.STATUS_OK}; }}"
    )
    QTimer.singleShot(300, lambda: widget.setStyleSheet(original))

def _on_advance_phase_accepted(self):
    self._success_echo(self._advance_button)
    self._update_phase_display()
```

**Example (bad):**

```python
# No feedback on success
def _on_advance_phase_accepted(self):
    self._update_phase_display()  # operator might not notice change

# Echo too long — blocks next action
def _success_echo(self, widget):
    widget.setStyleSheet(f"border: 2px solid {theme.STATUS_OK};")
    QTimer.singleShot(2000, lambda: widget.setStyleSheet(original))  # WRONG — 2s
```

**Related rules:** RULE-INTER-003 (press feedback), RULE-COLOR-002 (STATUS_OK semantic)

---

## RULE-INTER-008: Icon-only button requires tooltip

**TL;DR:** Button without visible text MUST have `setToolTip()` with description. Include keyboard shortcut in parentheses if applicable.

**Statement:** Icon-only buttons (close ×, play ▶, settings ⚙) are ambiguous without hover reveal. Every such button MUST call `setToolTip()` with:

1. Short description (Russian, sentence case)
2. Keyboard shortcut in parentheses if applicable

**Rationale:** Icons rely on cultural recognition — mostly reliable but not universal. Operator encountering unfamiliar icon has no way to learn without tooltip hover. Also enables future screen-reader `accessibleName`.

**Applies to:** any `QPushButton` without text, icon-only `QToolButton`, custom click widgets

**Example (good):**

```python
# DESIGN: RULE-INTER-008
close_button = QPushButton()
close_button.setIcon(load_colored_icon("x", color=theme.MUTED_FOREGROUND))
close_button.setIconSize(QSize(theme.ICON_SIZE_MD, theme.ICON_SIZE_MD))  # proposed: theme.ICON_SIZE_MD — not yet in theme.py
close_button.setFixedSize(32, 32)
close_button.setToolTip("Закрыть (Esc)")  # MANDATORY

# ToolRail with shortcut hint
log_button = QPushButton()
log_button.setIcon(load_colored_icon("file-text"))
log_button.setFixedSize(48, 48)
log_button.setToolTip("Журнал оператора (Ctrl+L)")
```

**Example (bad):**

```python
# No tooltip — icon meaning unlearnable
close_button = QPushButton()
close_button.setIcon(QIcon(":/icons/x.svg"))
# Missing setToolTip
```

**Related rules:** RULE-INTER-009 (shortcut registry), `tokens/keyboard-shortcuts.md`

---

## RULE-INTER-009: Keyboard shortcut from central registry

**TL;DR:** Import shortcuts from `cryodaq.gui.shortcuts`. Don't hardcode `QKeySequence("Ctrl+L")` in widget code.

**Statement:** Keyboard shortcuts in widget code MUST reference constants from central registry (proposed: `src/cryodaq/gui/shortcuts.py`). Hardcoded `QKeySequence` strings forbidden — they risk collision.

**Rationale:** Without registry, two features might bind same key unknowingly. Registry forces collision resolution at declaration.

**Applies to:** any widget adding `QAction` with shortcut, any `QShortcut` creation

**Example (good):**

```python
# DESIGN: RULE-INTER-009
from cryodaq.gui import shortcuts

open_log_action = QAction("Открыть журнал", self)
open_log_action.setShortcut(shortcuts.SHORTCUT_OPEN_LOG)
open_log_action.triggered.connect(self._open_operator_log)
self.addAction(open_log_action)
```

**Example (bad):**

```python
# Hardcoded shortcut — bypasses registry
action = QAction("Открыть журнал", self)
action.setShortcut(QKeySequence("Ctrl+L"))  # WRONG
```

**Migration:** Until registry module exists, document hardcoded shortcuts in inline comment: `# TODO: migrate to shortcuts.SHORTCUT_X when registry lands`.

**Related rules:** RULE-INTER-010 (no collisions), `tokens/keyboard-shortcuts.md`

---

## RULE-INTER-010: No shortcut collision between global and context

**TL;DR:** Global shortcut (Ctrl+L = open log) CANNOT be redefined by a context-specific widget to mean something else.

**Statement:** Globally-registered shortcuts (QApplication-level `Qt.ApplicationShortcut`) have priority. Widget MUST NOT define local shortcut duplicating a global one with different action.

Valid: context widget invokes same global action (refers to registry, no redefinition).
Invalid: context widget binds same key to different action.

**Rationale:** Shortcut meanings must be stable. Ctrl+L in dashboard vs modal doing different things creates cognitive chaos. Either both invoke same action, or context uses different shortcut.

**Applies to:** any widget-level shortcut registration

**Example (good):**

```python
# DESIGN: RULE-INTER-010
# Global: Ctrl+L = open log
app_action = QAction("Открыть журнал", app)
app_action.setShortcut(shortcuts.SHORTCUT_OPEN_LOG)
app_action.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)

# Modal with text input — does NOT register different Ctrl+L
# Global handles it — no conflict
```

**Example (bad):**

```python
# Global Ctrl+L = open log
app_action.setShortcut(QKeySequence("Ctrl+L"))

# Modal rebinds Ctrl+L to clear input — COLLISION
clear_action = QAction("Очистить", self)
clear_action.setShortcut(QKeySequence("Ctrl+L"))  # WRONG
self.addAction(clear_action)
```

**Related rules:** RULE-INTER-009 (registry), `tokens/keyboard-shortcuts.md`

---

## RULE-INTER-011: Pointer cursor on clickable elements

**TL;DR:** Interactive widgets show `Qt.PointingHandCursor` on hover. Indicates clickability.

**Statement:** Any widget responding to mouse click MUST set cursor to `Qt.CursorShape.PointingHandCursor`. Applies to buttons, clickable list rows, clickable tiles, links. Non-clickable widgets (labels, static displays) use default arrow.

**Rationale:** Cursor change is standard discoverability cue for "click here." Without it, operators may not realize a tile is clickable.

**Applies to:** any clickable QWidget

**Example (good):**

```python
# DESIGN: RULE-INTER-011
button = QPushButton("Применить")
button.setCursor(Qt.CursorShape.PointingHandCursor)

class ClickableTile(QFrame):
    clicked = Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
```

**Example (bad):**

```python
# Clickable tile with default cursor — no affordance
class ClickableTile(QFrame):
    clicked = Signal()
    def mousePressEvent(self, event):
        self.clicked.emit()
    # Missing setCursor
```

**Exception:** Disabled widgets use default arrow or `ForbiddenCursor` — clickability suppressed.

**Related rules:** RULE-INTER-012 (affordance visible), RULE-INTER-001 (focus ring)

---

## RULE-INTER-012: Affordance visible by default, not hover-only

**TL;DR:** Interactive elements visible and identifiable WITHOUT hovering. Hover enhances; it does not reveal.

**Statement:** Widgets MUST present their interactive nature at rest:
- Buttons: visible border/background
- Clickable rows: subtle indication (icon, color, cursor on pass-over)
- Links: distinguishable from body text (color/underline)

Hover states are ENHANCEMENTS, not first-time reveals.

Forbidden:
- "Secret" clickable areas revealed only on hover
- Plain text becoming a button on hover
- Table rows showing actions only on hover

**Rationale:** Under stress, operator cannot explore every pixel hoping for hover reveal. Discoverability requires static visibility. Common Material Design failure mode: "keep clean until hover" — cleaner-looking, less discoverable.

**Applies to:** all interactive widgets

**Example (good):**

```python
# DESIGN: RULE-INTER-012
# Button visible at rest
button.setStyleSheet(f"""
    QPushButton {{
        background: {theme.SURFACE_CARD};
        border: 1px solid {theme.BORDER};
        border-radius: {theme.RADIUS_SM}px;
        padding: 0 {theme.SPACE_3}px;
    }}
    QPushButton:hover {{ background: {theme.MUTED}; }}
""")

# List row with visible action icon
row_layout = QHBoxLayout()
row_layout.addWidget(row_label)
row_layout.addWidget(delete_icon_button)  # visible always
```

**Example (bad):**

```python
# "Secret" hover-reveal action
class SecretiveRow(QFrame):
    def __init__(self):
        super().__init__()
        self._delete_button = QPushButton("×")
        self._delete_button.setVisible(False)  # WRONG — hidden by default
    
    def enterEvent(self, event):
        self._delete_button.setVisible(True)
    
    def leaveEvent(self, event):
        self._delete_button.setVisible(False)

# Plain text becomes clickable on hover
label.setStyleSheet(f"color: {theme.MUTED_FOREGROUND};")
def enterEvent(self, event):
    self.setStyleSheet(f"color: {theme.ACCENT}; text-decoration: underline;")
    self.setCursor(Qt.PointingHandCursor)
# WRONG — no indication it's clickable until hovered
```

**Exception:** Menu items inside an already-open menu panel may use hover-to-highlight — the menu itself is the visible affordance; items within are expected to be interactive.

**Related rules:** RULE-INTER-011 (cursor), RULE-INTER-001 (focus ring)

---

## Changelog

- 2026-04-17: Initial version. 12 rules covering focus, escape, press feedback, destructive confirmation, async/instant animation exceptions, success echo, tooltip discovery, shortcut registry/collision, cursor affordance, hover-enhances-not-reveals.
