---
title: Focus Management
keywords: focus, focus-ring, focus-visible, focus-within, focus-trap, restoration, autofocus, accessibility
applies_to: focus indicator visuals + focus lifecycle across widgets and overlays
status: canonical
references: rules/accessibility-rules.md, rules/interaction-rules.md, tokens/colors.md, accessibility/keyboard-navigation.md
external_reference: WCAG 2.2 sections 2.4.7, 2.4.11; Apple HIG Keyboard/Focus; Material Design focus-visible
last_updated: 2026-04-17
---

# Focus Management

Rules for focus indication, focus trap behavior, and focus lifecycle (autofocus, restoration). Focus is the mechanism by which keyboard operators know "where am I"; poor focus management makes the product unusable without a mouse.

## Focus ring specification

**The canonical focus ring:** 2px solid ACCENT color, applied via border (not outline) for predictable Qt behavior.

```css
QWidget:focus {
    border: 2px solid ACCENT;  /* #7c8cff */
    border-radius: inherit;     /* match the widget's own radius */
}
```

Specifics:
- **Width:** 2px (UXPM v2.5.0 recommends 2-4px; we use 2 for density; 3px for the most critical destructive buttons to visually emphasize)
- **Color:** ACCENT (`#7c8cff`) — contrast 6.48:1 vs BACKGROUND, passes AA + non-text 3:1 per `contrast-matrix.md`
- **Offset:** none (adjacent to widget edge) — simpler rendering in Qt; deviation from web `outline-offset` convention
- **Style:** solid — no dashed/dotted; those read as states, not focus
- **Visibility:** only on `:focus-visible` equivalent (Qt's focus based on Tab, not click)

Rationale for 2px: visible without stealing pixels from content; distinguishable from BORDER's 1px; matches input `:focus` state already established in `components/input-field.md`.

## Focus-visible vs focus

Qt's native focus handling is less nuanced than web's focus-visible. We implement our equivalent:

- **Focus via keyboard (Tab, arrow):** show focus ring
- **Focus via mouse click:** no focus ring, but widget is still active

Implementation via Qt:
```python
# Track last interaction type
class FocusAwareWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._focus_via_keyboard = False
        self.installEventFilter(self)
    
    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            self._focus_via_keyboard = False
        elif event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
                self._focus_via_keyboard = True
        return super().eventFilter(obj, event)
    
    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self._focus_via_keyboard:
            self._show_focus_ring()
        else:
            self._hide_focus_ring()
```

Simpler: use Qt 6.7+ `:focus-visible` pseudo-state in QSS if available:
```css
QWidget:focus-visible {
    border: 2px solid #7c8cff;
}
```

## Focus restoration on overlay close

When a Modal / Drawer / Popover closes, focus returns to the element that opened it. Critical for keyboard users — without restoration, focus goes to document start, requiring re-navigation to continue work.

Implementation pattern:
```python
class Modal(QDialog):
    def __init__(self, parent, opener_widget=None, ...):
        super().__init__(parent)
        self._opener = opener_widget or QApplication.focusWidget()
    
    def closeEvent(self, event):
        super().closeEvent(event)
        if self._opener is not None:
            self._opener.setFocus()
```

Same pattern for Drawer, Popover, Dialog.

## Autofocus policy

**On overlay open: first focusable element receives focus.** Exceptions:

- **Destructive Dialog:** first focus = Cancel button (safe direction, RULE-INTER-004)
- **Non-destructive form Modal:** first focus = first input field (operator expects to type)
- **Alert Dialog (informational, no destruction):** first focus = OK button
- **Popover with options list:** first focus = first option
- **Modal with no inputs, no destruction:** first focus = close button

Don't autofocus elements that would cause unexpected changes (e.g., don't autofocus a «Запустить» button — operator opens and is immediately poised to accidentally Enter).

## Focus trap inside overlays

Focus trap prevents Tab from escaping a modal back into the underlying page. Required per WCAG 2.4.11 (Focus Not Obscured) in the spirit of "focus stays in the overlay so operator knows their location".

Implementation:
- Collect all focusable children of the overlay
- Override `keyPressEvent` for Tab / Shift+Tab at overlay level
- If Tab on last focusable → wrap to first
- If Shift+Tab on first → wrap to last

Edge cases:
- Overlay with zero focusable children: focus the overlay itself; Tab does nothing
- Overlay with one focusable child: Tab no-op (focus stays on it)
- Nested overlays (popover within modal): trap at innermost layer; outermost resumes on innermost close

## focus-within for composite widgets

When a compound widget (e.g., input field with embedded clear button) contains focusable sub-widgets, the OUTER widget should visually indicate "a child has focus" via focus-within.

Example: InputField shows border ACCENT not just on QLineEdit focus but on the combined input+unit+clear-button cluster:

```python
class InputField(QWidget):
    def focusInEvent(self, event):
        self._apply_focus_chrome()
    
    def focusOutEvent(self, event):
        # Only truly "out" if no child has focus
        QTimer.singleShot(0, self._check_true_focus_out)
    
    def _check_true_focus_out(self):
        focused = QApplication.focusWidget()
        if focused is None or not self.isAncestorOf(focused):
            self._remove_focus_chrome()
```

## Initial focus on app launch

On app launch, the initial focus goes to:
- **Dashboard primary tile** (usually ExperimentCard) if an experiment is active
- **Create Experiment button / tile** if no experiment is active
- **Shell root** only as fallback if no reasonable "first thing" exists

Operator on first launch can immediately press Enter or Tab without hunting for where they are.

## Focus during async operations

When an action is in progress (e.g., «Сохранить» clicked, waiting for engine roundtrip):

- Button enters loading state (per `components/button.md` — dimmed text + small spinner)
- Focus **stays on the button** (does NOT disappear or move to a spinner widget)
- Button `setEnabled(False)` would remove focus — instead use a "busy" state that keeps focus

On success: focus stays on button; operator can Tab away or re-click.
On failure: focus stays on button; error message appears adjacent (Toast); operator can re-try.

This mimics web `aria-busy="true"` pattern.

## Invisible focus issues

Common ways focus gets "lost":
1. Widget destroyed while focused → Qt fallback finds next, sometimes awkward
2. Widget hidden while focused → focus moves to parent or next sibling
3. Modal closes without restoration → focus goes to document root
4. Keyboard shortcut triggers panel switch → new panel's content gets focus, not the shortcut origin

For each, remediation:
1. Before destroying a focused widget, move focus explicitly to a sensible neighbor
2. Before hiding a focused widget, same
3. Implement restoration (see above)
4. Panel switch via shortcut: focus the panel's primary interactive element

## Focus ring on non-rectangular shapes

Some widgets have non-rectangular or complex shapes (e.g., a ToolRail slot with a 3px active indicator on its left edge). Focus ring should follow the widget's `boundingRect`, not compete with internal decorations:

```
Default ToolRail slot:
┌─────────────────┐
│       [Icon]    │
└─────────────────┘

Focused ToolRail slot (Tab):
╔═════════════════╗   ← 2px ACCENT border on full slot rect
║  [Icon]         ║
╚═════════════════╝

Selected ToolRail slot:
  [Icon]             ← 3px left-edge ACCENT bar
│───────────────────│ ← no outer border

Focused AND selected:
╔═════════════════╗
║[Icon]           ║   ← focus ring + left bar coexist
╚═════════════════╝
```

Selection chrome and focus chrome are independent; both can be active. Don't collapse them into one visual.

## Focus for custom-drawn widgets

Widgets that paint their own content (e.g., pyqtgraph PlotWidget, custom QFrame-based tiles):

- Reserve 2px on all sides for focus border in `paintEvent`
- When focused, paint a 2px ACCENT rectangle around the widget's `rect()`
- When not focused, leave that 2px blank (don't paint a disabled-looking border)

```python
def paintEvent(self, event):
    painter = QPainter(self)
    # ... paint contents ...
    if self.hasFocus():
        pen = QPen(QColor(theme.ACCENT))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
```

## Focus on lists and grids

Sensor grid, alarm list, archive list — many items, all focusable:

- Tab enters the list; focus on the first item
- Arrow keys move focus within the list (Up/Down for vertical, Left/Right for horizontal grid)
- Tab exits the list at the last item (or first, if Shift+Tab from first)
- Don't make every list item Tab-reachable individually; one Tab stop per list, arrows for within-list navigation

Qt's `QAbstractItemView` handles this natively; custom widgets (DynamicSensorGrid) need manual implementation.

## Rules applied

- **RULE-A11Y-001** — focus ring visibility (2px ACCENT)
- **RULE-A11Y-006** — tab order matches visual
- **RULE-INTER-001** — focus ring on all interactive elements
- **WCAG 2.4.7** — focus visible (AA)
- **WCAG 2.4.11** — focus not obscured (AA, WCAG 2.2)

## Common mistakes

1. **outline: 0 without replacement.** «Убрать ugly browser focus ring» без providing own. Kills keyboard accessibility. Always replace with custom ring, never delete.

2. **Focus ring only on some widgets.** Buttons have it, text links don't. Inconsistency confuses operator. Every interactive element has focus ring per RULE-A11Y-001.

3. **Same color for focus as selection.** ACCENT used for both; they conflict visually. Selection can use filled-bg + ACCENT left-bar; focus adds outer 2px border. Layer them.

4. **Focus lost on modal open.** Modal opens, nothing focused inside. Operator sees opaque overlay and no indication where to type. Always autofocus on open.

5. **No restoration on modal close.** Modal closes, focus jumps to document start. Operator has to Tab all the way back. Restore to opener.

6. **Focus trap without wrap.** Tab in modal hits end → focus escapes to background. Wrap to start.

7. **Autofocus destructive button.** Dialog opens and Enter deletes. Always default-focus Cancel.

8. **Disabled widget receives focus.** Tab stops on disabled widget; operator confused. Remove from focus chain OR indicate clearly why disabled.

9. **No focus ring on custom widgets.** Custom-painted tile has no visual focus indication. Paint explicit ring in paintEvent.

10. **Animated focus ring.** Focus ring fading in over 300ms. Delay obscures where focus actually is. Snap the ring.

## Related patterns

- `accessibility/keyboard-navigation.md` — Tab order, shortcuts, keyboard behaviors per widget
- `accessibility/wcag-baseline.md` — 2.4.7, 2.4.11 commitment
- `accessibility/reduced-motion.md` — focus indication stays snappy even under reduced motion
- `rules/accessibility-rules.md` — RULE-A11Y-001 canonical
- `tokens/colors.md` — ACCENT definition

## Changelog

- 2026-04-17: Initial version. 2px ACCENT focus ring spec. focus-visible equivalent in Qt. Restoration on overlay close. Autofocus policy by overlay type. Focus trap inside overlays. Coexistence of selection + focus chrome. Custom-widget paintEvent patterns.
