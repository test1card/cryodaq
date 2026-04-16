---
title: Keyboard Shortcut Registry
keywords: keyboard, shortcut, hotkey, modifier, escape, tab, focus, proposed
applies_to: global application shortcuts and panel-level shortcuts
enforcement: recommended
priority: medium
status: partially-proposed
last_updated: 2026-04-17
---

# Keyboard Shortcut Registry

All keyboard shortcuts in CryoDAQ MUST be registered here. This prevents collision (two features binding same key) and enables operators to learn shortcuts systematically.

Shortcut constants are PROPOSED — currently shortcuts are hardcoded in widget code. This document specifies the target registry.

## Shortcut grammar

**Single key (no modifier):** only for in-focus context (text input, navigation). Never global.
**Ctrl + key:** global operator action (open panel, save, etc.)
**Ctrl + Shift + key:** global operator emergency or destructive action (e.g., emergency stop)
**Alt + key:** reserved, not used (Alt opens menu bar in Qt on some platforms)
**F-keys:** reserved, use sparingly (F1 help, F5 refresh, F11 fullscreen)
**Escape:** close overlay / cancel action (never global mode change)

## Global shortcuts (proposed constants)

| Constant (proposed) | Binding | Action | Scope |
|---|---|---|---|
| `SHORTCUT_OPEN_LOG` | `Ctrl+L` | Open operator log overlay | Global |
| `SHORTCUT_OPEN_EXPERIMENT` | `Ctrl+E` | Open experiment card | Global |
| `SHORTCUT_OPEN_ANALYTICS` | `Ctrl+A` | Open analytics / charts overlay | Global |
| `SHORTCUT_OPEN_KEITHLEY` | `Ctrl+K` | Open Keithley panel | Global |
| `SHORTCUT_OPEN_ALARMS` | `Ctrl+M` | Open alarms overlay (M for "Модуль сигнализации") | Global |
| `SHORTCUT_OPEN_ARCHIVE` | `Ctrl+R` | Open archive/records | Global |
| `SHORTCUT_OPEN_CONDUCTIVITY` | `Ctrl+C` | Open conductivity panel | Global |
| `SHORTCUT_OPEN_SENSOR_DIAG` | `Ctrl+D` | Open sensor diagnostics | Global |
| `SHORTCUT_EMERGENCY_STOP` | `Ctrl+Shift+X` | Emergency stop (hold-to-confirm) | Global, confirmation required |
| `SHORTCUT_TOGGLE_MODE` | `Ctrl+Shift+M` | Toggle experiment/debug mode | Global |
| `SHORTCUT_HELP` | `F1` | Open help / shortcut reference | Global |
| `SHORTCUT_REFRESH` | `F5` | Refresh current view / recon­nect instruments | Global |
| `SHORTCUT_FULLSCREEN` | `F11` | Toggle fullscreen | Global |

## Phase navigation (in experiment context)

When experiment is active:

| Constant (proposed) | Binding | Action |
|---|---|---|
| `SHORTCUT_PHASE_NEXT` | `Ctrl+→` | Advance to next phase |
| `SHORTCUT_PHASE_PREV` | `Ctrl+←` | Return to previous phase (with confirmation) |
| `SHORTCUT_PHASE_1..6` | `Ctrl+1` through `Ctrl+6` | Jump directly to phase N |

## Overlay dismissal

Universal dismissal shortcut:

| Constant (proposed) | Binding | Action |
|---|---|---|
| `SHORTCUT_ESCAPE` | `Escape` | Close current overlay / popover / dialog (innermost first) |

Escape works only on open overlays. No global function when nothing is open.

## Focus navigation

Standard Qt tab order applies:

- `Tab` — next focusable widget
- `Shift+Tab` — previous focusable widget
- `Enter` / `Space` — activate focused widget (default Qt behavior)
- `Arrow keys` — move within lists, grids, tab groups

No custom shortcuts override these.

## Operator log entry (context-sensitive)

When operator log input field is focused:

| Binding | Action |
|---|---|
| `Enter` | Submit log entry |
| `Shift+Enter` | Newline within log entry |
| `Ctrl+Enter` | Submit with "IMPORTANT" severity flag |
| `Escape` | Cancel entry (prompt to discard) |

## Registry implementation (proposed)

Central module `src/cryodaq/gui/shortcuts.py`:

```python
# DESIGN: proposed
from PySide6.QtGui import QKeySequence

# Global shortcuts
SHORTCUT_OPEN_LOG = QKeySequence("Ctrl+L")
SHORTCUT_OPEN_EXPERIMENT = QKeySequence("Ctrl+E")
SHORTCUT_OPEN_ANALYTICS = QKeySequence("Ctrl+A")
# ... etc.

# Registration helper
def register_global_shortcut(shortcut: QKeySequence, action_callback):
    """Register shortcut on QApplication level."""
    ...
```

Widgets import constants instead of hardcoding:

```python
# DESIGN: RULE-INTER-009 (shortcut from registry)
from cryodaq.gui import shortcuts

self.addAction(
    QAction(text="Открыть журнал",
            shortcut=shortcuts.SHORTCUT_OPEN_LOG,
            triggered=self._open_operator_log)
)
```

## Discoverability

Operators should be able to discover shortcuts:

1. **Tooltip on icon-only buttons** includes shortcut: `"Открыть журнал (Ctrl+L)"` (see RULE-INTER-008)
2. **Help overlay (F1)** lists all registered shortcuts organized by category
3. **Menu items** (if visible) display shortcut in right column (Qt default behavior with `QAction.setShortcut`)

## Rule references

- `RULE-INTER-008` — Icon button tooltip includes shortcut (`rules/interaction-rules.md`)
- `RULE-INTER-009` — Shortcut from registry, not hardcoded (`rules/interaction-rules.md`)
- `RULE-INTER-010` — No shortcut collision between global and context (`rules/interaction-rules.md`)

## Related files

- `components/dialog.md` — Escape dismisses dialogs
- `components/modal.md` — Escape closes modals
- `accessibility/keyboard-navigation.md` — Tab order and focus
- `cryodaq-primitives/top-watch-bar.md` — Global shortcut hints in tooltips

## Changelog

- 2026-04-17: Initial version. PROPOSED shortcuts. Current code has ad-hoc shortcuts — migration to registry pending.
