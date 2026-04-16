---
title: Accessibility Rules
keywords: accessibility, a11y, wcag, keyboard, tab, contrast, motion, color-blind, readability, target, reduced-motion
applies_to: all widgets
enforcement: strict
priority: critical
last_updated: 2026-04-17
status: canonical
---

# Accessibility Rules

Rules aligning CryoDAQ with WCAG 2.1 AA where practical given the desktop-operator context. These rules override aesthetic preferences when they conflict.

CryoDAQ provides basic screen-reader support (per architect decision **AD-003**, screen reader is in scope for v1.0):

- Every interactive widget sets `accessibleName`
- Custom widgets set `accessibleDescription` matching tooltip text
- State changes fire `QAccessible.Event.ValueChanged` (throttled to avoid flooding — see `accessibility/keyboard-navigation.md`)
- Fault transitions announced immediately via `QAccessible` notification
- Live data updates throttled to ~1/min for SR users (routine updates), immediate for fault transitions

Full SR narration of chart data points is out of scope (data is complex numeric; operators read values directly).

Beyond SR support, these rules focus on: keyboard navigation, color-independent information, reduced-motion, readability, and click-target sizing — all of which benefit all operators, not just those with disabilities.

Enforce in code via `# DESIGN: RULE-A11Y-XXX` comment marker.

**Rule index:**
- RULE-A11Y-001 — Tab order matches visual order
- RULE-A11Y-002 — Status never conveyed by color alone
- RULE-A11Y-003 — Status color body-text contrast constraint
- RULE-A11Y-004 — Respect reduced motion preference
- RULE-A11Y-005 — Readable at arm's length on lab monitor
- RULE-A11Y-006 — Escape works from any focusable context
- RULE-A11Y-007 — Minimum click target 32px on desktop
- RULE-A11Y-008 — No critical information via motion alone

---

## RULE-A11Y-001: Tab order matches visual order

**TL;DR:** Pressing Tab moves keyboard focus in the same order operator reads the screen (top-to-bottom, left-to-right, respecting logical grouping).

**Statement:** Widget tab order MUST follow visual order. When operator presses Tab, focus moves to the next logical element as it appears on screen. Qt default tab order follows widget creation order — this may or may not match visual order depending on layout dynamics.

For any layout where creation order differs from visual order, explicitly set tab order via `QWidget.setTabOrder(first, second)` pattern.

**Rationale:** Keyboard navigation assumes Tab goes "forward" as visually perceived. If Tab jumps around unpredictably (skipping top-right for bottom-left, then back up), operator cannot navigate efficiently. They waste time pressing Tab repeatedly to find target element.

**Applies to:** forms, dashboard panels with multiple inputs, multi-section modal

**Example (good):**

```python
# DESIGN: RULE-A11Y-001
# Form: name, email, phone (visual order top to bottom)
# Tab order matches.
form_layout = QVBoxLayout(form)
form_layout.addWidget(self._name_field)   # 1st visually
form_layout.addWidget(self._email_field)  # 2nd visually
form_layout.addWidget(self._phone_field)  # 3rd visually

# Explicit tab chain if default widget-creation order doesn't match visual
QWidget.setTabOrder(self._name_field, self._email_field)
QWidget.setTabOrder(self._email_field, self._phone_field)
QWidget.setTabOrder(self._phone_field, self._submit_button)
```

**Example (bad):**

```python
# Created in one order, rearranged in layout → tab order doesn't match visual
self._submit_button = QPushButton("OK")     # created 1st
self._name_field = QLineEdit()              # created 2nd
self._email_field = QLineEdit()             # created 3rd

# But visually rendered in this order:
form_layout.addWidget(self._name_field)
form_layout.addWidget(self._email_field)
form_layout.addWidget(self._submit_button)

# No setTabOrder call → Tab jumps Submit → Name → Email (creation order)
# WRONG — visual order is Name → Email → Submit
```

**Exception:** Tab order may deliberately skip static/decorative widgets — those shouldn't receive focus anyway (`Qt.NoFocus` policy).

**Related rules:** RULE-INTER-001 (focus ring mandatory), RULE-INTER-002 (escape)

---

## RULE-A11Y-002: Status never conveyed by color alone

**TL;DR:** If status is communicated via color (STATUS_OK green, STATUS_FAULT red), it MUST also be communicated via icon, text label, or shape. Color alone fails for color-blind users and under poor monitor calibration.

**Statement:** Information that conveys status (OK, warning, fault, info, stale) MUST use at least two distinct visual channels:
- Color + icon (preferred — icon is redundant glyph)
- Color + text label ("НОРМА", "АВАРИЯ")
- Color + shape (circle = OK, triangle = warning, square = fault)
- Color + position (first column = OK, last = fault — if geometrically enforced)

Color-only is forbidden, even if color contrast passes AA.

**Rationale:** ~8% of male population has red-green color blindness. CryoDAQ lab has all-male engineering team by current demographic — likely 1-2 color-blind operators at any time. A STATUS_FAULT red indicator distinguishable only by color is invisible to them.

Secondary benefit: on poorly-calibrated or aging lab monitors, subtle color distinctions may fail even for color-normal operators.

**Applies to:** status indicators, badges, chart series categories, any categorical visualization

**Example (good):**

```python
# DESIGN: RULE-A11Y-002
# Status badge with icon + text + color
status_row = QHBoxLayout()
status_row.setSpacing(theme.SPACE_1)
status_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

icon = QLabel()
icon.setPixmap(
    load_colored_icon("check-circle", color=theme.STATUS_OK)
      .pixmap(theme.ICON_SIZE_SM, theme.ICON_SIZE_SM)
)
label = QLabel("НОРМА")
label.setStyleSheet(f"color: {theme.STATUS_OK};")

status_row.addWidget(icon)
status_row.addWidget(label)
# 3 channels: check-circle icon + "НОРМА" text + green color
```

```python
# Fault with triangle icon + text + red
fault_row.addWidget(
    icon_widget(load_colored_icon("alert-triangle", color=theme.STATUS_FAULT))
)
fault_row.addWidget(
    colored_label("АВАРИЯ", theme.STATUS_FAULT)
)
# Triangle + text + red → works even monochrome
```

**Example (bad):**

```python
# Color-only status indicator
status_dot = QLabel()
status_dot.setFixedSize(16, 16)
status_dot.setStyleSheet(f"background: {theme.STATUS_OK}; border-radius: 8px;")
# WRONG — green dot. To color-blind operator, looks same as gray or red dot.

# Green text alone
status_label = QLabel("Работает")
status_label.setStyleSheet(f"color: {theme.STATUS_OK};")
# WRONG — "works" info conveyed by green color. Without color, just text.
# Add icon to make it color-independent.
```

**Related rules:** RULE-COLOR-002 (status semantic), `tokens/icons.md`, RULE-A11Y-008 (motion alone)

---

## RULE-A11Y-003: Status color body-text contrast constraint

**TL;DR:** STATUS_FAULT (#c44545, 3.94:1), STATUS_INFO (#4a7ba8, 4.31:1), STATUS_STALE (#5a5d68, 2.94:1) fail WCAG AA body contrast. Do not use them as color for body-size text (<18pt / <14pt bold).

**Statement:** Measured contrast ratios vs BACKGROUND #0d0e12:

| Token | Ratio | AA body (≥4.5) | Use for body text? |
|---|---|---|---|
| STATUS_OK | 4.67:1 | ✓ | Yes |
| STATUS_WARNING | 6.24:1 | ✓ | Yes |
| STATUS_CAUTION | 5.67:1 | ✓ | Yes |
| STATUS_FAULT | 3.94:1 | ✗ | **No** — use FOREGROUND + icon |
| STATUS_INFO | 4.31:1 | ✗ | **No** — use FOREGROUND + icon |
| STATUS_STALE | 2.94:1 | ✗✗ | **No** — deliberately low |
| COLD_HIGHLIGHT | 5.46:1 | ✓ | Yes |

For contexts where STATUS_FAULT / STATUS_INFO / STATUS_STALE must convey status in body text, use this compound pattern:

- Text color: `theme.FOREGROUND` (readable)
- Icon prefix: colored in status token
- Optional: border-left in status color

**Rationale:** Readability is safety-critical. Operator who cannot read a fault message because contrast fails may miss the fault entirely. Body text MUST be readable; status color belongs on icons and borders that don't carry textual meaning.

**Applies to:** all text under 18pt (or 14pt bold) using status tokens as foreground color

**Example (good):**

```python
# DESIGN: RULE-A11Y-003
# Fault message: readable text + colored icon + colored border
row = QFrame()
row.setObjectName("faultRow")
row.setStyleSheet(f"""
    #faultRow {{
        border-left: 3px solid {theme.STATUS_FAULT};
        background: transparent;
        padding: {theme.SPACE_2}px;
    }}
""")
row_layout = QHBoxLayout(row)
row_layout.setSpacing(theme.SPACE_2)

icon = icon_widget(
    load_colored_icon("alert-triangle", color=theme.STATUS_FAULT)
)
text = QLabel("Т11 вышел за уставку, срабатывание блокировки")
text.setStyleSheet(f"color: {theme.FOREGROUND};")  # readable FG
# Icon + border convey fault-color. Text readable.

row_layout.addWidget(icon)
row_layout.addWidget(text)
```

**Example (bad):**

```python
# Fault message in STATUS_FAULT color — fails contrast
fault_label = QLabel("Т11 вышел за уставку, срабатывание блокировки")
fault_label.setStyleSheet(f"color: {theme.STATUS_FAULT};")  # WRONG — 3.94:1

# Long info body in STATUS_INFO
info_label = QLabel("Калибровка выполнена 23 дня назад. Планируйте перекалибровку.")
info_label.setStyleSheet(f"color: {theme.STATUS_INFO};")  # WRONG — 4.31:1
```

**Exception (narrow):** Large-size headings (18pt+ = FONT_SIZE_LG+) pass AA large at 3.0:1. Fault banner title "АВАРИЯ" at FONT_TITLE_SIZE (22px) with STATUS_FAULT color is acceptable — passes AA large. But body paragraph beneath should be FOREGROUND.

**Related rules:** RULE-COLOR-008 (ON_* pairs), `tokens/colors.md` contrast matrix, ANTI_PATTERNS.md status-color-for-small-text

---

## RULE-A11Y-004: Respect reduced motion preference

**TL;DR:** When system indicates reduced motion preference, skip all animations — jump straight to final state. Helper function `should_animate()` encapsulates the check.

**Statement:** Some operators experience motion sensitivity (vestibular disorders, migraines). OS-level reduced-motion preference (macOS: System Preferences → Accessibility → Display → Reduce Motion; Windows: Settings → Ease of Access → Display → Show animations) MUST be honored.

Pattern: centralize animation decision in `should_animate()` helper:

```python
def should_animate() -> bool:
    """Check OS reduced-motion preference + app override."""
    # Implementation varies per platform; simplified example
    return not _os_reduced_motion_preferred()
```

All QPropertyAnimation code MUST gate on this helper. If `False`, apply final state instantly.

**Rationale:** Motion sensitivity is invisible disability. Operator affected may not even realize animation triggers discomfort until they've been working 4 hours and developed migraine. Providing OS-respected opt-out costs very little implementation effort.

Additional benefit: low-end hardware (spec-old lab PCs) may drop animation frames — skipping animations yields smoother perceived performance on such systems.

**Applies to:** any `QPropertyAnimation`, `QGraphicsEffect` with animated properties, custom timer-driven animations

**Example (good):**

```python
# DESIGN: RULE-A11Y-004
from cryodaq.gui.a11y import should_animate

def open_modal(self):
    if should_animate():
        anim = QPropertyAnimation(self._card, b"opacity")
        anim.setDuration(300)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start()
    else:
        # Instant final state
        self._card.setGraphicsEffect(None)
        self._card.show()
```

**Example (bad):**

```python
# No reduced-motion check
def open_modal(self):
    anim = QPropertyAnimation(self._card, b"opacity")
    anim.setDuration(300)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.start()  # WRONG — ignores OS preference
```

**Related rules:** RULE-INTER-005 (async durations), RULE-INTER-006 (faults instant), `tokens/motion.md`

---

## RULE-A11Y-005: Readable at arm's length on lab monitor

**TL;DR:** Text MUST be readable at ~60cm from screen on lab PC (96 DPI, non-retina). This implies minimum 11px font size and minimum weight 400.

**Statement:** All operator-facing text MUST satisfy:
- Font size ≥ `theme.FONT_SIZE_XS = 11` (smallest font in scale)
- Font weight ≥ `theme.FONT_WEIGHT_REGULAR = 400` (see RULE-TYPO-006)
- Contrast ≥ WCAG AA (4.5:1 for body, 3.0:1 for large 18pt+)

Lab monitor assumptions:
- 1920×1080 or similar, non-retina
- 96 DPI (standard desktop)
- ~60cm typical viewing distance
- Possibly aging monitor with reduced contrast

Tiny text (<11px), light weights (<400), or color-only low-contrast pairings are forbidden.

**Rationale:** Lab PC is not a design studio 5K retina display 30cm away. Real viewing conditions reduce legibility compared to designer assumptions. Readability threshold must account for this.

Operator night-shift fatigue further compounds — text that's "readable with effort" in daylight becomes unreadable after 10 hours.

**Applies to:** all text widgets, global typography configuration

**Example (good):**

```python
# DESIGN: RULE-A11Y-005
# Smallest label — FONT_SIZE_XS = 11, weight MEDIUM = 500
axis_tick = QFont(theme.FONT_MONO, theme.FONT_SIZE_XS)
axis_tick.setWeight(theme.FONT_WEIGHT_MEDIUM)

# Body text — FONT_BODY_* preset
body_font = QFont(theme.FONT_BODY, theme.FONT_BODY_SIZE)
body_font.setWeight(theme.FONT_BODY_WEIGHT)
```

**Example (bad):**

```python
# Too small for lab conditions
tiny_label = QFont(theme.FONT_BODY, 9)  # WRONG — < 11px minimum
tiny_label.setWeight(300)                # WRONG — < 400 minimum
```

**Related rules:** RULE-TYPO-006 (minimum weight), RULE-TYPO-007 (off-scale sizes), RULE-A11Y-003 (contrast)

---

## RULE-A11Y-006: Escape works from any focusable context

**TL;DR:** From any focused widget inside an overlay/modal, Escape MUST dismiss the overlay — not just when top-level overlay widget has focus.

**Statement:** Event filter or key handler at overlay level MUST intercept Escape regardless of which inner widget currently has focus. Qt's default behavior often requires modal top-level to have focus for its keyPressEvent to receive Escape — this is insufficient for complex modals with internal focusable elements.

Implementation: install event filter on modal, or override `keyPressEvent` on ALL child focusable widgets (heavier — prefer event filter).

**Rationale:** Operator tabs through modal inputs, focused somewhere deep inside. Presses Escape to cancel. Without proper propagation, Escape does nothing — focus is on QLineEdit which consumes it. Operator feels trapped.

RULE-INTER-002 states "Escape dismisses overlays" — this rule specifies it must work from ANY focus location, not only when overlay root is focused.

**Applies to:** ModalCard, Dialog, Drawer, any overlay with internal focusable widgets

**Example (good):**

```python
# DESIGN: RULE-A11Y-006
class ModalCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # Install event filter on self — intercepts events for all children
        self.installEventFilter(self)
    
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.KeyPress:
            key_event = event  # type: QKeyEvent
            if key_event.key() == Qt.Key.Key_Escape:
                self.close()
                return True  # consumed
        return super().eventFilter(obj, event)
```

**Example (bad):**

```python
# Only root keyPressEvent handles Escape
class BrokenModal(QWidget):
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
# If focus is on internal QLineEdit, QLineEdit's own keyPressEvent
# may consume Escape before it reaches modal root → Escape does nothing
```

**Related rules:** RULE-INTER-002 (escape basic), RULE-INTER-001 (focus ring)

---

## RULE-A11Y-007: Minimum click target 32px on desktop

**TL;DR:** Interactive elements (buttons, clickable rows, icon-only buttons) have minimum 32×32 pixel hit region. `theme.ROW_HEIGHT = 36` satisfies this with margin.

**Statement:** Every clickable element MUST have hit-region at least 32×32 pixels. For most controls, `theme.ROW_HEIGHT = 36` provides 4px safety margin over minimum. Icon-only buttons MUST have widget size ≥ 32×32 even if icon inside is smaller (16 or 20px).

This is smaller than WCAG 2.5.5 recommendation (44×44) — desktop with precise mouse allows smaller than touch. But 32 is the floor.

**Rationale:** Mouse precision is ~1 pixel under normal conditions, but operators with tremor, fatigue, or low-cost mouse hardware may miss smaller targets. Emergency actions MUST NOT require precise targeting — 32+ minimum allows reliable clicking under stress.

Icon-only buttons are common pitfall: icon is 16px, designer sizes button to 16px matching icon visually — hit region becomes 16×16, well below threshold. Always pad icon to larger clickable widget.

**Applies to:** buttons, icon buttons, clickable list rows, tool rail icons, clickable badges/chips

**Example (good):**

```python
# DESIGN: RULE-A11Y-007
# Icon-only close button — 32×32 widget, 16px icon centered
close_button = QPushButton()
close_button.setFixedSize(32, 32)  # satisfies minimum
close_button.setIcon(load_colored_icon("x"))
close_button.setIconSize(QSize(theme.ICON_SIZE_MD, theme.ICON_SIZE_MD))  # 20px icon

# Tool rail icon — 48×48 (emergency-action safety)
tool_rail_button = QPushButton()
tool_rail_button.setFixedSize(48, 48)
tool_rail_button.setIcon(load_colored_icon("bell"))
tool_rail_button.setIconSize(QSize(theme.ICON_SIZE_MD, theme.ICON_SIZE_MD))

# Row button — ROW_HEIGHT = 36 by default
button = QPushButton("Применить")
button.setFixedHeight(theme.ROW_HEIGHT)  # 36 ≥ 32
```

**Example (bad):**

```python
# Icon-sized button — hit region too small
close_button = QPushButton()
close_button.setFixedSize(16, 16)  # WRONG — icon-sized, not clickable-sized
close_button.setIcon(load_colored_icon("x"))
close_button.setIconSize(QSize(16, 16))
# Hit region 16×16, operator will mis-click

# Below ROW_HEIGHT standard
compact_button.setFixedHeight(28)  # WRONG — below 32 floor
```

**Exception:** Small chips/badges that are DISPLAY ONLY (not clickable) may be smaller than 32. But if they're clickable, must hit threshold.

**Related rules:** RULE-SPACE-005 (adjacent clickable gap), RULE-SPACE-007 (row height), RULE-INTER-011 (cursor)

---

## RULE-A11Y-008: No critical information via motion alone

**TL;DR:** If information is critical (fault, alarm, state change), it MUST be visible in a static screenshot. Not just "flashes" or "pulses" — static appearance must also convey the information.

**Statement:** Critical information (faults, alarms, phase transitions, command acceptance) MUST be communicated through static visual state in addition to any motion. A user with motion disabled (RULE-A11Y-004) or a screenshot examiner must see the critical info from the static state.

Specifically forbidden:
- Fault indicated by blinking red (if motion off, no fault visible)
- Alarm indicated only by pulsing animation
- Confirmation only via fade-in (if motion off, no confirmation visible)

Allowed: motion enhances static state (pulse draws attention to already-visible fault indicator), but static state carries the information.

**Rationale:** This is the static-counterpart of RULE-A11Y-004 (reduced motion). Reduced-motion users must still see fault state. Static screenshot examiners (review logs, debugging) must see system state from snapshots.

Also: operator eye may be elsewhere when animation triggers — static indicator must still be there when eye returns.

**Applies to:** fault indicators, alarm visuals, state-change notifications

**Example (good):**

```python
# DESIGN: RULE-A11Y-008
def show_fault(self, fault_info):
    # Static state — persistent and self-evident
    self._fault_banner.setStyleSheet(
        f"background: {theme.STATUS_FAULT};"
        f"color: {theme.ON_DESTRUCTIVE};"
    )
    self._fault_banner.setText(f"АВАРИЯ: {fault_info.description}")
    self._fault_banner.setVisible(True)
    # ↑ Fault visible from screenshot, static, no motion needed
    
    # OPTIONAL motion enhancement (reduced-motion aware)
    if should_animate():
        self._pulse_attention(self._fault_banner)  # draws eye to already-visible fault
```

**Example (bad):**

```python
# Fault indicated only by blinking
def show_fault(self, fault_info):
    # Static state: banner invisible
    self._fault_banner.setStyleSheet("background: transparent;")
    
    # Motion only: blink between red and transparent
    self._fault_banner.setVisible(True)
    self._blink_timer.start(500)
    # If motion disabled, banner stays transparent → fault invisible
    # Screenshot at random moment may show banner or not → inconsistent
```

**Related rules:** RULE-A11Y-004 (reduced motion), RULE-INTER-006 (faults instant), RULE-A11Y-002 (not color alone)

---

## Changelog

- 2026-04-17: Initial version. 8 rules covering tab order, color-independent status, contrast constraints on status colors, reduced-motion respect, lab-conditions readability, universal Escape, 32px minimum click target, static-not-motion critical info.
- 2026-04-17 (v1.0.1): Replaced screen-reader scope-out language with positive AD-003 commitment. CryoDAQ provides basic SR support (accessibleName / accessibleDescription / throttled QAccessible events / immediate fault announcements); only full SR narration of chart data points remains out of scope.
