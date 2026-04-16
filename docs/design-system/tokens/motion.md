---
title: Motion Tokens
keywords: motion, animation, duration, easing, transition, reduced-motion, proposed
applies_to: all transitions and state changes
enforcement: recommended
priority: medium
status: proposed
last_updated: 2026-04-17
---

# Motion Tokens

**Status: PROPOSED.** These tokens are NOT yet in `src/cryodaq/gui/theme.py`. All motion timing in current widgets is hardcoded. This document specifies the proposed set to be added when motion system is formalized.

Until tokens land in theme.py, widget code SHOULD use the proposed values as literals (documented below) and update to tokens when they are added.

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

## Duration scale (proposed)

| Token (proposed) | Value (ms) | Use |
|---|---|---|
| `DURATION_INSTANT` | `75` | Barely-perceptible acknowledgment — pressed button state, tooltip appearance |
| `DURATION_FAST` | `150` | Quick micro-interactions — hover state, small popover |
| `DURATION_BASE` | `200` | Default for state transitions — dropdown open, tab switch |
| `DURATION_SLOW` | `300` | Overlay slide-in, modal backdrop fade |
| `DURATION_DELIBERATE` | `400` | Multi-step transition, large overlay with content reveal |

**Maximum duration ceiling: 400ms.** Anything longer feels sluggish on desktop operator UI. If a transition genuinely needs >400ms, it should probably be decomposed into staged animations (each <400ms).

**No `DURATION_DELAYED`.** Intentional omission — delayed animation is rare and should be commented inline if needed.

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
    self._animate(duration=DURATION_SLOW, easing=EASING_ENTER)  # 300ms in

def close_modal(self):
    self._animate(duration=DURATION_BASE, easing=EASING_EXIT)   # 200ms out (~66%)
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
        self._animate(duration=DURATION_SLOW, easing=EASING_ENTER)
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

    # Revert after DURATION_SLOW
    QTimer.singleShot(DURATION_SLOW, lambda: widget.setStyleSheet(original_style))
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

## Current widget implementations (pre-tokens)

Until tokens are added to `theme.py`, widgets hardcode values. Expected pattern:

```python
# Temporary pattern (pre-token)
FADE_DURATION_MS = 200  # DESIGN: replace with theme.DURATION_BASE when added

animation = QPropertyAnimation(widget, b"opacity")
animation.setDuration(FADE_DURATION_MS)
animation.setEasingCurve(QEasingCurve.Type.InOutQuad)  # DESIGN: replace with theme.EASING_STANDARD
```

When motion tokens land, migration is a `find/replace` task across widget code.

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
