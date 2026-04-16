---
title: Motion Tokens
keywords: motion, animation, duration, easing, transition, reduced-motion
applies_to: all transitions and state changes
enforcement: recommended
priority: medium
status: partially-shipped
last_updated: 2026-04-17
---

# Motion Tokens

**Status: partially shipped.** Three duration tokens (`TRANSITION_FAST_MS`, `TRANSITION_BASE_MS`, `TRANSITION_SLOW_MS`) are live in `src/cryodaq/gui/theme.py` and are the canonical durations for the current UI. Easing tokens, a richer duration scale, and reduced-motion helpers are still proposed — see the sections below.

Widget code MUST reference the shipped tokens for duration (no literals for the three canonical values). Easing and additional durations remain inline literals with a `DESIGN:` comment until they are promoted.

## Current tokens (shipped in theme.py)

| Token | Value (ms) | Use |
|---|---|---|
| `TRANSITION_FAST_MS` | `150` | Hover, focus, toggle transitions; quick micro-interactions |
| `TRANSITION_BASE_MS` | `200` | Default for state transitions — modal/drawer open, dropdown, tab switch, toast enter |
| `TRANSITION_SLOW_MS` | `300` | Complex multi-element transitions; success-echo window; large overlay reveal |

```python
# Canonical usage — RULE-COLOR-010-style rule: reference theme, not literals
from cryodaq.gui import theme

animation = QPropertyAnimation(widget, b"opacity")
animation.setDuration(theme.TRANSITION_BASE_MS)
```

New code introducing a duration that matches one of these three values MUST use the token, not a `150` / `200` / `300` literal. Durations outside this set remain case-by-case until the expanded scale below lands.

## Core motion philosophy

**Motion in CryoDAQ indicates state change, never decoration.**

- Transition ≠ animation. Transitions communicate cause-and-effect ("this changed because of that").
- No count-up animation on sensor readings — values appear instantly to preserve read accuracy.
- No pulse, blink, or breathing animation on alarms or status indicators — visual noise that distracts.
- No parallax, scroll-triggered animation, or decorative motion — we are not a marketing site.

**What motion IS used for:**
- Overlay open/close (drawer, modal slide-in from backdrop)
- State transitions that are non-obvious (collapse/expand of sections)
- Success echo (brief visual confirmation of command acknowledged)
- Focus ring appearance on keyboard navigation

**What motion is NEVER used for:**
- Data updates
- Decoration, attention-grabbing
- "Delight"
- Hiding latency (use skeleton placeholder, not progress bar animation)

## Duration scale — proposed future expansion

The three shipped `TRANSITION_*_MS` tokens cover the common cases. A richer `DURATION_*` family is proposed to add the extremes (a shorter acknowledgement tier and a longer deliberate tier). Until the governance review approves and theme.py adds them, the non-shipped tiers below are **not** available as tokens.

| Token | Status | Value (ms) | Use |
|---|---|---|---|
| `DURATION_INSTANT` | Proposed | `75` | Barely-perceptible acknowledgment — pressed button state, tooltip appearance |
| `TRANSITION_FAST_MS` | **Shipped** | `150` | Quick micro-interactions — hover, focus, toggle |
| `TRANSITION_BASE_MS` | **Shipped** | `200` | Default state transitions — dropdown, tab switch, modal open |
| `TRANSITION_SLOW_MS` | **Shipped** | `300` | Overlay slide-in, modal backdrop fade, success echo |
| `DURATION_DELIBERATE` | Proposed | `400` | Multi-step transition, large overlay with content reveal |

**Maximum duration ceiling: 400ms.** Anything longer feels sluggish on desktop operator UI. If a transition genuinely needs >400ms, it should probably be decomposed into staged animations (each <400ms).

**No `DURATION_DELAYED`.** Intentional omission — delayed animation is rare and should be commented inline if needed.

**Proposed rename.** When the scale is expanded, a governance decision is required on whether to rename `TRANSITION_*_MS` → `DURATION_*` for naming consistency. Until then, keep the `TRANSITION_*_MS` names — no silent renames.

## Easing curves (proposed)

Qt supports `QEasingCurve` types. The proposed mapping:

| Token (proposed) | Qt curve | Use |
|---|---|---|
| `EASING_STANDARD` | `QEasingCurve.InOutQuad` | Default for symmetric transitions |
| `EASING_ENTER` | `QEasingCurve.OutQuad` | Entering an element (modal open) — decelerates into place |
| `EASING_EXIT` | `QEasingCurve.InQuad` | Exiting an element (modal close) — accelerates out |
| `EASING_SPRING` | `QEasingCurve.OutBack` (with overshoot 1.2) | Playful confirmation echo (rare; use sparingly) |

**No linear easing.** Linear feels mechanical, not natural. Always use one of the above curves.

## Asymmetric duration rule

**Exit animations should be shorter than enter animations** (60-70% of enter duration). Users spend longer perceiving something appear than perceiving it disappear — matched durations make exits feel sluggish.

```python
# DESIGN: RULE-INTER-005 (asymmetric open/close)
def open_modal(self):
    self._animate(duration=theme.TRANSITION_SLOW_MS, easing=EASING_ENTER)  # 300ms in

def close_modal(self):
    self._animate(duration=theme.TRANSITION_BASE_MS, easing=EASING_EXIT)   # 200ms out (~66%)
```

## Reduced motion

Respect system `prefers-reduced-motion` hint. Qt exposes this via `QStyleHints::showAnimations()` / OS-level accessibility setting.

```python
# DESIGN: RULE-A11Y-004 (reduced motion)
from PySide6.QtGui import QGuiApplication

def should_animate(self) -> bool:
    """Return False if user has requested reduced motion."""
    hints = QGuiApplication.styleHints()
    # Qt returns False for showAnimations() if reduced motion requested
    return hints.showAnimations()

def open_modal(self):
    if self.should_animate():
        self._animate(duration=theme.TRANSITION_SLOW_MS, easing=EASING_ENTER)
    else:
        # Instant appearance — no animation
        self._set_opacity(1.0)
        self._set_visible(True)
```

All non-essential animations MUST check this. Essential animations (none in CryoDAQ — we have no animations that carry semantic meaning requiring motion) would be exempted.

## Alarm / fault presentation

**Faults appear instantly, not animated.** A FAULT_LATCHED state appearing via fade-in obscures the critical moment. Use instant state change:

```python
# DESIGN: RULE-INTER-006 (fault instant)
def on_fault_detected(self, fault_info):
    # Instant red — no transition
    self._alarm_banner.setStyleSheet(f"background: {theme.STATUS_FAULT};")
    self._alarm_banner.setVisible(True)
    # Sound alert, not visual animation
    self._play_alarm_sound()
```

Exit of fault state (when cleared) MAY use DURATION_FAST fade — the urgency is past, transition communicates "fault acknowledged."

## Success echo pattern

When operator action succeeds (e.g., Keithley command accepted, phase advanced), brief visual confirmation:

```python
# DESIGN: RULE-INTER-007 (success echo)
def _success_echo(self, widget):
    """Brief green flash to confirm action registered."""
    original_style = widget.styleSheet()

    # Flash on
    widget.setStyleSheet(f"background: {theme.STATUS_OK};")

    # Revert after TRANSITION_SLOW_MS
    QTimer.singleShot(theme.TRANSITION_SLOW_MS, lambda: widget.setStyleSheet(original_style))
```

Echo is brief (300ms) and non-blocking — operator can immediately trigger next action.

## Forbidden motion patterns

- **Pulsing/blinking status** — creates visual noise, blends into background over time
- **Spinning loading indicators in data context** — hides missing data instead of showing it
- **Count-up number animation** — obscures the current value for the duration of count-up
- **Parallax scrolling** — wrong aesthetic for instrumentation
- **"Breathing" idle animation** — suggests alertness, we want stillness
- **Transition on sensor reading updates** — data should snap to new value instantly
- **Animated progress bars for known-duration operations** — use determinate progress (percentage updates), not animation

## Current widget implementations

Durations come from `theme.py`; easing curves are still inline until `EASING_*` tokens are promoted:

```python
from cryodaq.gui import theme
from PySide6.QtCore import QPropertyAnimation, QEasingCurve

animation = QPropertyAnimation(widget, b"opacity")
animation.setDuration(theme.TRANSITION_BASE_MS)
animation.setEasingCurve(QEasingCurve.Type.InOutQuad)  # DESIGN: replace with theme.EASING_STANDARD when promoted
```

When `EASING_*` tokens land, migration is a `find/replace` task across widget code. Audit for any remaining `150` / `200` / `300` literals used as animation durations and replace with the corresponding `TRANSITION_*_MS` token.

## Rule references

- `RULE-INTER-005` — Asymmetric open/close duration (`rules/interaction-rules.md`)
- `RULE-INTER-006` — Faults appear instantly (`rules/interaction-rules.md`)
- `RULE-INTER-007` — Success echo pattern (`rules/interaction-rules.md`)
- `RULE-A11Y-004` — Respect reduced motion preference (`rules/accessibility-rules.md`)
- `RULE-DATA-009` — No animation on data updates (`rules/data-display-rules.md`)

## Related files

- `rules/interaction-rules.md` — full interaction enforcement
- `rules/data-display-rules.md` — data update rules (no motion)
- `accessibility/reduced-motion.md` — accessibility compliance
- `ANTI_PATTERNS.md#motion` — forbidden motion patterns

## Changelog

- 2026-04-17: Initial proposal. Motion tokens NOT yet in `theme.py` — pending product decision to formalize.
- 2026-04-17 (v1.0.1): Acknowledged that `TRANSITION_FAST_MS` / `TRANSITION_BASE_MS` / `TRANSITION_SLOW_MS` are shipped in `theme.py` (FR-003). Removed the "NOT yet in theme.py" claim; replaced duration-literal examples with token references; moved the richer `DURATION_*` family to an explicitly "proposed future expansion" section. Easing tokens remain proposed.
