---
title: Keyboard Shortcut Registry
keywords: keyboard, shortcut, hotkey, modifier, escape, tab, focus, canonical, mnemonic
applies_to: global application shortcuts and panel-level shortcuts
enforcement: required
priority: high
status: canonical
last_updated: 2026-04-17
architect_decision: AD-002 (mnemonic shortcuts canonical)
---

# Keyboard Shortcut Registry

> **Canonical registry.** This file is the single source of truth for
> all CryoDAQ keyboard shortcuts per architect decision **AD-002**.
> Other documents (`accessibility/keyboard-navigation.md`,
> `cryodaq-primitives/tool-rail.md`, component docs) must align with
> this registry — if they disagree, the registry wins and the other
> document is stale.

All keyboard shortcuts in CryoDAQ MUST be registered here. This prevents collision (two features binding the same key) and enables operators to learn shortcuts systematically.

## Canonical scheme: mnemonic shortcuts

Per **AD-002**, the canonical global-navigation shortcuts are **mnemonic** (Ctrl + first letter of the Russian / English panel name — whichever is clearest for operators). Numeric shortcuts (Ctrl+1 … Ctrl+9) are **legacy / transitional** — kept alive while rail slot ordering is still being finalized, but they are NOT the canonical scheme and new code should not rely on them.

- **Canonical (learn these):** `Ctrl+L`, `Ctrl+E`, `Ctrl+A`, `Ctrl+K`, `Ctrl+M`, `Ctrl+R`, `Ctrl+C`, `Ctrl+D`, `Ctrl+Shift+X`.
- **Transitional fallback (do not extend):** `Ctrl+1` … `Ctrl+9` to rail slots.

Shortcut constants (`SHORTCUT_*`) are currently proposed Python names; most widgets still bind via `QKeySequence("Ctrl+L")` literals. Migration to a central `src/cryodaq/gui/shortcuts.py` registry is tracked but non-blocking — the *bindings* below are canonical today regardless of where the literals live.

## Shortcut grammar

**Single key (no modifier):** only for in-focus context (text input, navigation). Never global.
**Ctrl + key:** global operator action (open panel, save, etc.)
**Ctrl + Shift + key:** global operator emergency or destructive action (e.g., emergency stop)
**Alt + key:** reserved, not used (Alt opens menu bar in Qt on some platforms)
**F-keys:** reserved, use sparingly (F1 help, F5 refresh, F11 fullscreen)
**Escape:** close overlay / cancel action (never global mode change)

## Canonical global shortcuts (mnemonic scheme)

These are the canonical bindings per AD-002. Constant names are the proposed Python identifiers in the future `src/cryodaq/gui/shortcuts.py` registry.

| Constant | Binding | Action | Scope |
|---|---|---|---|
| `SHORTCUT_OPEN_LOG` | `Ctrl+L` | Open operator log overlay (**L**og / **Л**ог) | Global |
| `SHORTCUT_OPEN_EXPERIMENT` | `Ctrl+E` | Open experiment card (**E**xperiment / **Э**ксперимент) | Global |
| `SHORTCUT_OPEN_ANALYTICS` | `Ctrl+A` | Open analytics / charts overlay (**A**nalytics / **А**налитика) | Global |
| `SHORTCUT_OPEN_KEITHLEY` | `Ctrl+K` | Open Keithley panel (**K**eithley) | Global |
| `SHORTCUT_OPEN_ALARMS` | `Ctrl+M` | Open alarms overlay (М for "**М**одуль сигнализации") | Global |
| `SHORTCUT_OPEN_ARCHIVE` | `Ctrl+R` | Open archive/records (**R**ecords) | Global |
| `SHORTCUT_OPEN_CONDUCTIVITY` | `Ctrl+C` | Open conductivity panel (**C**onductivity) | Global |
| `SHORTCUT_OPEN_SENSOR_DIAG` | `Ctrl+D` | Open sensor diagnostics (**D**iagnostics) | Global |
| `SHORTCUT_EMERGENCY_STOP` | `Ctrl+Shift+X` | Emergency stop (hold-to-confirm) | Global, confirmation required |
| `SHORTCUT_TOGGLE_MODE` | `Ctrl+Shift+M` | Toggle experiment/debug mode | Global |
| `SHORTCUT_HELP` | `F1` | Open help / shortcut reference | Global |
| `SHORTCUT_REFRESH` | `F5` | Refresh current view / reconnect instruments | Global |
| `SHORTCUT_FULLSCREEN` | `F11` | Toggle fullscreen | Global |

## Transitional numeric navigation (Ctrl+[1-9]) — legacy

`Ctrl+1` through `Ctrl+9` currently map to the nine slots of the left `ToolRail`. Per AD-002 this scheme is **transitional**, not canonical:

- It remains active so operators who memorized slot positions are not disrupted mid-release cycle.
- It must not be extended — no `Ctrl+0`, no new numeric slot bindings.
- Canonical mnemonics above take precedence when both target the same panel (e.g., `Ctrl+L` AND `Ctrl+8` both open the operator log; `Ctrl+L` is canonical, `Ctrl+8` is the alias being phased out).
- Removal is planned when rail slot ordering stabilizes. Timeline tracked in `governance/deprecation-policy.md`.

Rationale: slot numbers tie a shortcut to rail *position*, which is layout state, not meaning. Rail reorderings silently break muscle memory. Mnemonics tie shortcut to *panel identity*, which is stable.

## Phase navigation (in experiment context)

When experiment is active:

| Constant | Binding | Action |
|---|---|---|
| `SHORTCUT_PHASE_NEXT` | `Ctrl+→` | Advance to next phase |
| `SHORTCUT_PHASE_PREV` | `Ctrl+←` | Return to previous phase (with confirmation) |

> **Note.** Earlier drafts of this file listed `Ctrl+1`…`Ctrl+6` as
> "jump to phase N." Per AD-002 that binding conflicts with the
> transitional rail-slot shortcuts and is removed from the canonical
> scheme. Phase jumps happen via the phase stepper widget or
> `Ctrl+→` / `Ctrl+←` sequential navigation. A dedicated mnemonic
> (e.g., `Ctrl+P` for phase picker) is a candidate for a future
> minor release.

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
- 2026-04-17 (v1.0.1): Marked canonical per architect decision AD-002 (FR-011). Clarified that mnemonic shortcuts (`Ctrl+L`, `Ctrl+E`, …) are the canonical scheme and that `Ctrl+[1-9]` numeric rail-slot navigation is transitional. Removed `Ctrl+1`…`Ctrl+6` phase-jump entries to eliminate collision with rail slot bindings. Changed status from `partially-proposed` to `canonical`.
