---
title: Keyboard Navigation
keywords: keyboard, navigation, tab-order, shortcuts, hotkeys, focus-trap, accessibility, operator
applies_to: keyboard operability across the product
status: canonical
references: rules/accessibility-rules.md, rules/interaction-rules.md, tokens/keyboard-shortcuts.md, patterns/destructive-actions.md
external_reference: WCAG 2.2 sections 2.1.x, 2.4.x; Apple HIG Keyboard chapter; Material Design Accessibility
last_updated: 2026-04-17
---

# Keyboard Navigation

Rules for keyboard operability. CryoDAQ must be fully operable without a mouse — operator may need to run experiments wearing gloves, or during a mouse failure, or simply prefers keyboard. This is a WCAG 2.1.1 (Level A) requirement.

## Scope of keyboard commitment

Every interactive element reachable by mouse must also be reachable by keyboard, with the exception of:
- Chart pan/zoom in historical views (mouse-wheel and drag have keyboard alternatives: arrow keys pan, +/- zoom)
- Drag-to-reorder in BentoGrid (not a current feature; if added, must have keyboard alternative)

No gesture-only interactions, no hover-only-reveal features.

## Tab order rules

**Principle (RULE-A11Y-006):** Tab order matches visual reading order.

For CryoDAQ this means F-pattern order from `patterns/information-hierarchy.md`:

```
1. TopWatchBar (Tab enters here first on app open) — but chrome is not Tab-reachable
   once focus is established inside main content; only explicit shortcut returns to it
2. Main content area, top-left first
3. Main content area, across row (left → right)
4. Main content area, next row down
5. ToolRail (if focus moves left from main area)
6. BottomStatusBar (not focusable — status readout only)
```

Specifically:
- **Chrome (TopWatchBar, ToolRail, BottomStatusBar)** items are Tab-reachable when focus starts there (on app init) but not in the normal forward flow from main content. Operators use shortcuts to reach chrome, not Tab.
- **Main content area** is the primary Tab surface. Tab forward goes through all interactive elements in visual order.
- **Modal / Drawer overlays** trap focus (see "Focus trap" below). Tab wraps within the overlay.

## Keyboard shortcut registry

Registered globally at application level (QShortcut on the QMainWindow):

| Shortcut | Action |
|---|---|
| **Ctrl+1** | Open Dashboard (ToolRail slot 1) |
| **Ctrl+2** | Open «Создать эксперимент» (ToolRail slot 2) |
| **Ctrl+3** | Open «Карточка эксперимента» (ToolRail slot 3) |
| **Ctrl+4** | Open Keithley panel (ToolRail slot 4) |
| **Ctrl+5** | Open Analytics (ToolRail slot 5) |
| **Ctrl+6** | Open «Теплопроводность» (ToolRail slot 6) |
| **Ctrl+7** | Open Alarms (ToolRail slot 7) |
| **Ctrl+8** | Open Journal (ToolRail slot 8) |
| **Ctrl+L** | Open Journal (alias for Ctrl+8) |
| **Ctrl+9** | Open «Диагностика датчиков» (ToolRail slot 9) |
| **Ctrl+A** | Open Alarms panel (from AlarmBadge) |
| **Ctrl+Shift+X** | **Emergency stop (АВАР. ОТКЛ.)** |
| **F11** | Toggle fullscreen |
| **F5** | Refresh (reload current panel data from engine) |
| **Escape** | Dismiss overlay (Modal / Drawer / Popover) |
| **Ctrl+W** | Close current overlay |

Per Qt convention:
| Shortcut | Action |
|---|---|
| **Tab** | Focus next |
| **Shift+Tab** | Focus previous |
| **Enter / Space** | Activate focused button |
| **Arrow keys** | Navigate within widget (tabs, lists, steppers, chart) |

## Policy: no single-key shortcuts

Every CryoDAQ shortcut uses at least one modifier (Ctrl, Alt, Shift). Reason: operator may be typing into a QLineEdit (experiment name, log entry); single-key shortcut captured instead of the typed character is a trust-breaking bug.

Per WCAG 2.1.4 Character Key Shortcuts (Level A): shortcuts using only letter/number/punctuation keys must either be disable-able, remappable, or active only on focus. Modifier-requirement avoids the whole issue.

Exception: function keys (F5, F11) — these are not text input characters.

## The Ctrl+Shift+X exception

Emergency stop is the one exception to the "every shortcut has a visible affordance" principle. Reasoning:

- Emergency stop may be needed when operator panics — hunting for the АВАР. ОТКЛ. button in the Keithley panel (which might not even be the active panel) costs seconds
- The three-key combo is itself deliberate — cannot be triggered by accidental single-key press
- The Keithley panel's АВАР. ОТКЛ. hold-confirm button remains visible AND carries the same shortcut in its tooltip

So the shortcut is discoverable (tooltip), just not globally visually displayed as "press Ctrl+Shift+X here" on every panel.

## Focus trap in overlays

Modals, Drawers, and Popovers trap Tab focus within the overlay. When operator Tabs past the last focusable element, focus wraps to the first. Shift+Tab wraps the other way.

Required behavior:
- **On open:** focus moves to the overlay's primary focusable element (usually the first input or the close button) — NOT the destructive primary button (RULE-INTER-004 safe-default)
- **On Tab past end:** wraps to first
- **On Escape:** dismisses overlay (safe direction per RULE-INTER-002); focus returns to the element that opened the overlay
- **On outside click:** typically dismisses (same as Escape); for Dialogs with explicit `mandatory=True`, click-outside does NOT dismiss

Focus trap implementation uses Qt's `QWidget.setFocusPolicy(Qt.StrongFocus)` + overlay's own `keyPressEvent` handler cycling focus manually if needed.

## Destructive action keyboard behavior

Per `patterns/destructive-actions.md`:

- **Default focus in destructive Dialog = Cancel button.** Operator pressing Enter (muscle memory) dismisses safely.
- **Primary action requires explicit Tab navigation** to the destructive button before Enter, OR a mouse click.
- **HoldConfirmButton does NOT activate on Enter alone** — it requires continuous hold; keyboard holds space for 1 second works; Enter press for 1s also works (via Qt's key-repeat suppression during hold).

Alternative for keyboard users on hold-confirm: **Shift+Enter on a focused HoldConfirmButton** triggers immediately with same destructive dialog as mouse hold-complete. This makes hold-confirm fully keyboard-accessible without requiring held keypress.

## Per-widget keyboard behavior

### Buttons, toggles, checkboxes
- Enter OR Space activates
- Tab focuses

### Input fields
- Tab moves focus
- Enter submits parent form (or, if not in form, fires `returnPressed` signal)
- Esc clears focus (does NOT clear content; that's user's responsibility)

### TabGroup
- Arrow Left/Right cycles tabs
- Home/End jumps to first/last tab
- Tab moves focus OUT of tab bar into tab content

### PhaseStepper
- Not directly navigable by keyboard from within stepper — operator doesn't "pick" a phase; engine transitions. If Advance button present (overlay variant), it receives normal Tab focus and Enter activates.
- No Arrow navigation within stepper (avoid implying manual phase selection)

### BentoGrid / SensorCell
- Tab navigates through each cell in row-major order
- Enter on a cell opens its drill-down (if supported)
- Arrow keys are NOT used for cell navigation — Tab is; arrow keys reserved for within-cell behaviors (e.g., editing inline in rename mode)

### Chart / Plot
- Tab focuses the plot region as a single unit
- When focused: Left/Right arrow pan time window; +/- zoom; Home resets view
- No per-data-point keyboard access (numeric; not practical)

### Modal / Drawer
- Tab cycles within; Shift+Tab reverse-cycles
- Escape dismisses
- Close button (if present in header) is first Tab-reachable element

## Non-obvious: tab-order surprises to avoid

1. **Skipping decorative widgets:** Icon-only status dots (read-only) must NOT be Tab-focusable. Use `setFocusPolicy(Qt.NoFocus)`.
2. **Re-ordering by visual tricks:** Absolute positioning or transform that moves a widget visually but leaves it at original DOM position — Tab order breaks. Avoid.
3. **Hidden widgets in Tab order:** Widgets with `setVisible(False)` should be removed from tab order (Qt handles this automatically, but custom focus chains may miss it).
4. **Disabled buttons in Tab order:** Disabled widgets are still focusable by default in Qt. For purely disabled states (not planned to re-enable), `setFocusPolicy(Qt.NoFocus)` + tooltip explaining why.

## The "type while focus is elsewhere" problem

Operator types an experiment name — QLineEdit has focus. Presses Ctrl+1 expecting to go to Dashboard → Ctrl+1 fires (global shortcut) → panel changes → name text possibly lost.

Protection:
- **Warn on dirty-form panel switch.** If operator has unsaved text in an input and triggers a panel-change shortcut, show Dialog «Закрыть без сохранения?» (copy-voice.md).
- **Ctrl+1..9 routes through navigation handler** that checks dirty state, not directly bypassing.

## Screen-reader compatibility

Beyond Tab + Enter + Arrow operability, screen readers (NVDA on Windows most likely for Russian operators) need:
- `accessibleName` on every interactive widget (set via `setAccessibleName` or via visible QLabel buddy)
- `accessibleDescription` on widgets where label is ambiguous (e.g., icon-only button with tooltip text should also have accessibleDescription = tooltip)
- `QAccessible.Event.ValueChanged` fired on live data updates (but throttled — 2 Hz sensor updates would flood screen reader)

**Throttle SR announcements of live data:** announce once per minute for routine updates, immediately for fault transitions. Use `QAccessibleValueInterface` with explicit control rather than letting Qt auto-announce everything.

## Keyboard testing checklist

Before shipping any panel:

1. ☐ Tab from top of panel to bottom — order matches visual reading order
2. ☐ Every interactive element is reachable
3. ☐ Enter / Space activates every button
4. ☐ Escape dismisses overlays
5. ☐ Destructive dialogs default-focus Cancel
6. ☐ Focus ring visible on every focused state (RULE-A11Y-001)
7. ☐ Modal opens → focus moves to modal (not left behind in parent)
8. ☐ Modal closes → focus returns to opener
9. ☐ Global shortcuts work from any panel
10. ☐ Emergency stop Ctrl+Shift+X works from any context

## Rules applied

- **RULE-A11Y-001** — focus ring visibility
- **RULE-A11Y-005** — accessible names on custom widgets
- **RULE-A11Y-006** — tab order matches visual
- **RULE-INTER-002** — Escape dismisses overlays
- **RULE-INTER-004** — destructive default-focus Cancel
- **RULE-INTER-008** — tooltip mandatory for icon-only buttons (screen-reader context fallback)
- **WCAG 2.1.1** — keyboard accessible
- **WCAG 2.1.2** — no keyboard trap
- **WCAG 2.1.4** — character key shortcuts (modifier requirement)
- **WCAG 2.4.3** — focus order

## Common mistakes

1. **Single-key shortcut that fires during typing.** «T» for temperature panel — operator types experiment name «Test-042» and panel keeps switching. Use Ctrl+T instead.

2. **Tab order different from visual.** Absolute-positioned widget visually at top, DOM-order at bottom. Operator tabs through strange path. Keep DOM order matching visual.

3. **Focusable decorative widgets.** Status dots with `FocusPolicy.StrongFocus` Tab-reachable for no reason. `NoFocus` them.

4. **No focus trap in modals.** Tab escapes out of modal into background UI. Trap via Qt's focusPolicy + key event handler.

5. **Disabled button still focusable.** Operator Tabs to a disabled button and wonders why nothing happens on Enter. Remove from focus chain OR ensure tooltip explains disabled reason.

6. **Default focus on destructive primary.** Operator hits Enter → destructive action fires. Default-focus Cancel always.

7. **Shortcut without modifier.** Some single-key accelerators (A for alarm, C for Keithley). Collides with text input. Use Ctrl+modifiers always.

8. **Overlooking screen reader for live data.** Every 500ms update fires accessibility event → SR user hears continuous update noise. Throttle.

9. **Missing accessible name on icon-only button.** Screen reader announces "button" with no context. Set `accessibleName` + ensure tooltip present (dual channel).

10. **No way back to ToolRail from main area.** Operator in middle of panel needs slot 2; doesn't know Ctrl+2 or clicks with mouse. Document shortcut; make discoverable via tooltip on rail slots themselves.

## Related patterns

- `accessibility/focus-management.md` — focus ring visuals + restoration logic
- `accessibility/wcag-baseline.md` — 2.1.x and 2.4.x commitment
- `tokens/keyboard-shortcuts.md` — the shortcut registry token
- `patterns/destructive-actions.md` — Ctrl+Shift+X exception documented there

## Changelog

- 2026-04-17: Initial version. Tab order rules + F-pattern alignment. Shortcut registry table. No single-key policy. Ctrl+Shift+X exception rationale. Focus trap spec for overlays. Per-widget keyboard behavior. Screen-reader throttling guidance.
