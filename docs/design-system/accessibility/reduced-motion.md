---
title: Reduced Motion
keywords: reduced-motion, prefers-reduced-motion, vestibular, animation-disable, motion-safe, fatigue
applies_to: animation and motion policy, OS preference respect, vestibular accommodation
status: canonical
references: rules/accessibility-rules.md, rules/interaction-rules.md, rules/data-display-rules.md, tokens/motion.md
external_reference: WCAG 2.2 section 2.3.3 Animation from Interactions; Apple HIG Reduced Motion; Material Design motion-reduce
last_updated: 2026-04-17
---

# Reduced Motion

Rules for motion respect. CryoDAQ already has a near-zero-animation baseline (RULE-INTER-006, RULE-DATA-009) driven by operator-trust and real-time-data correctness, not primarily by accessibility. But the few animations that exist (focus transitions, modal open/close, hold-confirm fill) must respect OS-level `prefers-reduced-motion` preference.

## Baseline: CryoDAQ animates less than most apps

Before talking about reducing motion, note: CryoDAQ's default motion budget is already low:

- **No tween on data values** (RULE-DATA-009) — numbers snap, don't count up
- **No fade on state transitions** (RULE-INTER-006) — fault appears instantly, no animation
- **No pulse on alerts** — alarm badge is static color, no pulsing
- **No parallax, no hero transitions, no kinetic scrolling** — product is industrial, not marketing
- **No carousel, no auto-advancing content**

This means the "reduce motion" need is narrower than in consumer apps. The user preference still matters; but the list of things to disable is short.

## What motion exists (and may need reduction)

Complete inventory of motion in CryoDAQ:

| Source | Type | Duration | Respects reduced-motion? |
|---|---|---|---|
| Modal / Drawer open/close | Fade opacity 0 ↔ 1 | 150ms | Yes — becomes instant under reduce |
| Button hover state | Color transition | 100ms | Yes — becomes instant |
| Button pressed state | Scale down 0.98 | 80ms | Yes — disabled under reduce |
| Focus ring appear | Border width 0 ↔ 2px | 100ms | Yes — becomes instant |
| Toast enter | Slide up 12px | 150ms | Yes — fade only, no slide |
| Toast exit | Slide down 12px + fade | 200ms | Yes — fade only, no slide |
| HoldConfirmButton fill | Width 0 ↔ 100% during 1s hold | **1000ms** | **Partial** — see below |
| Chart live data | New points appear (no animation) | 0ms | Already reduced |
| PhaseStepper state change | Color transition | 200ms | Yes — becomes instant |
| TabGroup indicator bar | Slide to selected tab | 150ms | Yes — snap instead |
| Popover open | Fade opacity 0 ↔ 1 | 120ms | Yes — becomes instant |

Outside reduced-motion pref: default durations already small (<250ms per UXPM `duration-timing` guidance "150-300ms for micro-interactions").

## The HoldConfirmButton special case

The 1-second progressive fill during hold is NOT decorative — it's a safety mechanism (operator needs visual feedback that the hold is progressing). Under reduced-motion, it cannot simply disappear.

Under `prefers-reduced-motion: reduce`:
- Fill still happens BUT with coarser increments (every 250ms jump instead of smooth progression)
- Textual progress announced to screen reader ("удерживайте 1 секунду... ещё 0.5с... готово")
- End-state still requires the 1s dwell (safety bar not lowered)

This balances accessibility accommodation with not compromising the safety gesture.

## Detecting the preference

Qt provides access to OS-level reduced-motion preference:

```python
# Windows: query SPI_GETCLIENTAREAANIMATION via user32
# macOS: query NSWorkspaceAccessibilityDisplayOptionsDidChangeNotification
# Linux: read org.gnome.desktop.interface animations-enabled or GTK3 setting

from PySide6.QtGui import QGuiApplication

def is_reduced_motion() -> bool:
    """OS-level preference for reduced motion."""
    # Qt 6.5+ exposes this via style hints; fallback to platform-specific check
    try:
        return QGuiApplication.styleHints().colorScheme() == ...  # not direct API
    except:
        pass
    # Platform-specific fallback — see full implementation in motion.py
    return False

class MotionPolicy:
    @staticmethod
    def current_duration(base_ms: int) -> int:
        """Returns 0 if reduced motion, else base_ms."""
        if is_reduced_motion():
            return 0
        return base_ms
```

Use `MotionPolicy.current_duration(150)` instead of hardcoded `150` anywhere a duration is applied.

## What "reduced" means exactly

Per WCAG 2.3.3 (AAA, but widely aspired-to for accessibility):

- **Parallax scrolling:** disabled
- **Vestibular-triggering animations** (rapid zoom, large translations, rotation): disabled
- **Auto-play video/animation:** disabled or pauseable
- **Essential motion:** reduced but not removed (e.g., progress indicator becomes discrete steps, not continuous)

**NOT required** to disable:
- Loading spinners (essential feedback)
- Focus indicators (essential; ours are instant anyway)
- Hover state color changes (not vestibular; instant transition is fine)

## CryoDAQ-specific reduced-motion behaviors

When `prefers-reduced-motion: reduce`:

1. **All transitions duration → 0ms** (instant state changes)
2. **Toast slide → pure fade** (no 12px translation; just opacity)
3. **Modal backdrop fade → instant opaque/transparent** (no 150ms opacity tween)
4. **Button pressed scale → disabled** (color change only, no scale 0.98)
5. **HoldConfirmButton progressive fill → discrete 4-step update** (at 0%, 25%, 50%, 75%, 100% — visible jumps, still 1s total)
6. **TabGroup indicator bar → snap to selected tab** (no slide)
7. **PhaseStepper transitions → no color fade** (already mostly instant; confirm)

**Not changed under reduced-motion:**
- Live data updates (already atomic per RULE-DATA-001)
- Focus ring appearance (already nearly instant at 100ms)
- Fault indication (already instant per RULE-INTER-006)

## Operator override

Operators may want to re-enable animations even if OS pref is reduce-motion (e.g., they find the hold-confirm smoother progress useful). Provide a Settings panel toggle:

```
Настройки → Интерфейс → Анимация:
  ○ Системная настройка (рекомендуется)
  ○ Всегда включена
  ○ Всегда отключена
```

Default: "Системная настройка". Override stored in user config (operator-local).

## Motion rules summary (full motion policy)

Beyond reduced-motion respect, the full motion rules for CryoDAQ:

1. **Max duration 250ms** for any UI transition. Exceeds → needs justification (hold-confirm 1s is justified).
2. **Ease-out for entering, ease-in for exiting** per UXPM `easing` rule.
3. **Transform + opacity only** — never animate width/height/top/left per UXPM `transform-performance` (avoid layout thrashing).
4. **Animations must be interruptible** — user click during animation cancels it. Per UXPM `interruptible`.
5. **No animation on live data** — RULE-DATA-009 (CryoDAQ-specific).
6. **Respect reduced-motion** — this document.

## Vestibular / photosensitive triggers to avoid

Even without reduced-motion pref, never use:

- **Flashing > 3 Hz** (RULE-INTER-006 already forbids; reiterate for vestibular scope)
- **Large-area parallax** (not used)
- **Rapid zoom in/out** (not used)
- **Infinite spinners with fast rotation** — loading spinners use gentle 1-2s rotation, not hectic speed
- **Auto-animation > 5s duration** without operator-initiated cause

## Testing reduced-motion

1. **OS preference enable:**
   - Windows: Settings → Ease of Access → Display → "Show animations in Windows: off"
   - macOS: System Preferences → Accessibility → Display → "Reduce motion"
   - Linux (GNOME): Settings → Accessibility → Seeing → "Reduce animation"
2. **Launch app; verify:**
   - Modal opens without fade
   - Toast appears without slide
   - Button pressed state no scale
   - HoldConfirmButton shows discrete progress steps
3. **Restore preference; verify motion resumes as expected**

Automated tests: mock `is_reduced_motion()` → True and verify widgets use 0ms durations via property-check.

## Rules applied

- **RULE-A11Y-007** — reduced-motion respect
- **RULE-INTER-006** — no flashing / instant state transitions (always, not just under reduce)
- **RULE-DATA-009** — no animation on live data (always)
- **WCAG 2.3.3** — animation from interactions (AAA, aspirational)
- **Apple HIG Reduced Motion API**
- **Material Design motion-reduce**

## Common mistakes

1. **Ignoring OS preference.** Animations run at full speed regardless. Violates vestibular accommodation; operator fatigue in long sessions. Detect and respect.

2. **Disabling motion entirely ignores essential feedback.** Under reduce, progress still needs visual indication — use discrete steps, not nothing.

3. **Animating hold-confirm fill to zero.** Safety feature eliminated. Keep the 1s dwell, reduce only the smoothness.

4. **Slide + fade on Toast enter under reduce.** Still translating 12px. Under reduce: fade only, no slide.

5. **Spinning loading indicator at high speed.** Nauseating for vestibular-sensitive users. Keep spin duration ≥ 1s per revolution.

6. **Auto-playing preview animations.** Dashboard "demo" that animates on app launch. Either user-triggered or disabled under reduce.

7. **Parallax scrolling on dashboard.** Never use in industrial app regardless of preference.

8. **Hard-coded durations bypass MotionPolicy.** `QPropertyAnimation` with `setDuration(250)` directly — doesn't check preference. Always route through MotionPolicy.

## Related patterns

- `accessibility/wcag-baseline.md` — 2.3.x criteria
- `tokens/motion.md` — canonical duration tokens
- `rules/interaction-rules.md` — RULE-INTER-006 instant state transitions
- `rules/data-display-rules.md` — RULE-DATA-009 no animation on live data
- `components/button.md` — HoldConfirmButton spec with reduced-motion fallback

## Changelog

- 2026-04-17: Initial version. Full motion inventory. HoldConfirmButton special case (discrete progress under reduce). MotionPolicy helper pattern. Operator override in Settings. Testing procedure per OS. Baseline acknowledged as already low-motion by product design.
