---
title: Primary View vs Modal Overlay — Panel Audit
date: 2026-04-17
author: CC (post-AnalyticsPanel rev 2 fix)
scope: every cryodaq-primitives spec + its shipped implementation
status: audit — findings only, no remediation
companion: docs/design-system/cryodaq-primitives/analytics-panel.md (revision 2)
---

# Primary view vs modal overlay — panel audit

After Codex caught the ModalCard architectural bug in B.8
AnalyticsPanel and it was corrected to `AnalyticsView` (primary view
QWidget, commit `860ecf3`), this audit walks every other
cryodaq-primitives spec and shipped widget to check whether the same
class of bug — a ToolRail-activated widget inheriting `ModalCard`
instead of being a QWidget page in the shell's main content stack —
exists elsewhere.

**Method.** For each spec, grep for `ModalCard` / `BentoGrid` /
`ToolRail` / `Ctrl+`; for the implementation file referenced by
`implements:`, read the class declaration and its base(s). For
ToolRail-activated widgets, the canonical pattern is
`class Foo(QWidget)` registered into `OverlayContainer` (a
`QStackedWidget`) via `register(name, widget)` in
`src/cryodaq/gui/shell/main_window_v2.py`.

**Severity legend.**
- `NO REGRESSION` — correct pattern today.
- `VISUAL REGRESSION` — wrong pattern producing a visible visual
  problem (backdrop, close button, cropped layout).
- `NAMING DRIFT` — correct functional pattern, mislocated or misnamed
  file/directory; no runtime impact.

---

## Summary table

| Spec | Shipped impl | Correct base today? | ToolRail target? | Severity |
|---|---|---|---|---|
| `analytics-panel.md` (rev 2) | `shell/views/analytics_view.py` (`AnalyticsView(QWidget)`) | **Yes** | Yes (`Ctrl+A`) | — (just fixed in commit `860ecf3`) |
| `keithley-panel.md` | `shell/overlays/keithley_panel.py` (`KeithleyPanel(QWidget)`) | **Yes (functionally)** | Yes (`Ctrl+K` / slot 4) | **NAMING DRIFT** — file lives in `overlays/` but class is a QWidget page. No visual bug. |
| `experiment-card.md` (dashboard variant) | `gui/dashboard/experiment_card.py` (`ExperimentCard(QFrame)`) | **Yes** | No (embedded dashboard tile) | — |
| *Experiment overlay variant (separate class)* | `shell/experiment_overlay.py` (`ExperimentOverlay(QWidget)`) | **Yes** | Yes (`Ctrl+E` / slot 3) | **NAMING DRIFT** — class named "Overlay" but is a QWidget page. No visual bug. |
| `quick-log-block.md` | legacy `widgets/operator_log_panel.py` — compact block inside dashboard | n/a | No (embedded) | — |
| `alarm-badge.md` | legacy inline bell indicator in TopWatchBar | n/a | No (indicator only; clicks → alarms slot) | — |
| `sensor-cell.md` | `dashboard/sensor_cell.py` | Yes | No (grid child) | — |
| `phase-stepper.md` | `dashboard/phase_stepper.py` | Yes | No (embedded) | — |
| `tool-rail.md` / `top-watch-bar.md` / `bottom-status-bar.md` | shell chrome widgets | Yes | No (chrome) | — |

No `VISUAL REGRESSION` severities found. Two `NAMING DRIFT` items.

---

## Detail per panel

### analytics-panel.md → `AnalyticsView` (fixed)

Commit `860ecf3` landed revision 2. `AnalyticsView(QWidget)` at
`src/cryodaq/gui/shell/views/analytics_view.py`. Registered in
`main_window_v2._OVERLAY_FACTORIES["analytics"]`; `OverlayContainer`
shows it as a stack page. No backdrop, no close button, no focus
trap. Spec status `active`, callout aligned.

Inclusion in this audit is historical — the bug that motivated the
audit.

### keithley-panel.md → `KeithleyPanel`

**Current base:** `class KeithleyPanel(QWidget)`. `SmuChannelState` /
`KeithleyState` dataclasses; private `_SmuChannelBlock(QFrame)` helper.

**Pattern:** correct. Registered as a page in `OverlayContainer` under
the `"source"` key (ToolRail slot 4, `Ctrl+K`). No `ModalCard`
inheritance; no backdrop.

**Drift:** file path is `src/cryodaq/gui/shell/overlays/keithley_panel.py`.
The directory name `overlays/` is misleading — by convention (after
analytics rev 2) `overlays/` should host ModalCard-based modals only,
and `views/` hosts QWidget primary views. Keithley v2 is a primary
view that happens to live under `overlays/`.

**Severity:** `NAMING DRIFT`. No runtime or visual impact.

**Remediation option (separate commit, not in scope here):** `git mv`
the file into `shell/views/keithley_panel.py`, update the
`main_window_v2` import, update the spec's `implements:` path, keep
the class name and API. Mechanical rename only.

### experiment-card.md — dashboard variant + experiment overlay

The spec covers two variants:
1. **Dashboard variant** — `ExperimentCard(QFrame)` at
   `src/cryodaq/gui/dashboard/experiment_card.py`. Embedded as a tile
   inside the dashboard, not a ToolRail target in isolation. Correct
   pattern. No drift.
2. **Overlay variant** — handled by a separate class,
   `ExperimentOverlay(QWidget)` at
   `src/cryodaq/gui/shell/experiment_overlay.py`. This IS the
   ToolRail target for slot 3 (`"experiment"`, `Ctrl+E`). Class
   correctly extends `QWidget`, registered in `OverlayContainer`.
   Docstring explicitly says "Registered as overlay page in
   OverlayContainer."

**Drift:** the class name `ExperimentOverlay` uses the word "overlay"
in the architectural-pattern sense from before the rev 2 terminology
clarification. By the new vocabulary, this is a primary view, not a
ModalCard overlay. The name could mislead future contributors into
thinking the class should inherit `ModalCard`.

**Severity:** `NAMING DRIFT`. No functional bug. No visual regression.

**Remediation option (separate commit):** rename
`ExperimentOverlay` → `ExperimentView`, move to `shell/views/`.
Wider-reaching than Keithley because tests + shell + top-bar wiring
all reference the class name. Tracked as a decision for the
architect, not a mechanical fix.

### quick-log-block.md

Compact operator-log block embedded inside the dashboard and
experiment-overlay pages. Not a ToolRail target. The ToolRail `"log"`
slot opens the legacy `OperatorLogPanel` instead, which is a full
panel (separate from this spec).

Spec `status: proposed`; no shipped widget under this exact API yet.
Legacy `widgets/operator_log_panel.py` inherits QFrame — no ModalCard
misuse.

### alarm-badge.md

Inline badge rendered inside `TopWatchBar`. Not a panel. Not a
ToolRail target. Click navigates to the `"alarms"` slot
(`AlarmPanel` from `widgets/alarm_panel.py`, legacy v1 QWidget).

Spec `status: partial`. No ModalCard misuse. No separate
alarms-panel spec exists today; when that spec lands, revisit it
specifically for the primary-view pattern.

### sensor-cell.md / phase-stepper.md

Dashboard-embedded widgets (tile / compact stepper). Not ToolRail
targets. Correct QFrame / QWidget bases. No drift.

### tool-rail.md / top-watch-bar.md / bottom-status-bar.md

Shell chrome primitives — always visible around the main content
stack. Not primary views themselves and not ModalCards. Correct
patterns.

---

## Ecosystem gap: no "primary view" primitive spec

`cryodaq-primitives/` today has specs for chrome (tool-rail,
top-watch-bar, bottom-status-bar), dashboard tiles (sensor-cell,
phase-stepper, experiment-card, quick-log-block), the alarm badge,
and two panels (keithley-panel, analytics-panel). There is no spec
that canonicalises the **primary view** pattern itself — the
architectural invariants (QWidget base, no dismiss chrome, no focus
trap, hosted in `OverlayContainer` stack, stays alive across
switches) are only documented inside `analytics-panel.md` revision 2.

**Finding:** extract a `components/primary-view.md` spec (or
`patterns/primary-view.md`) so future panels reference a single
architectural anchor instead of re-discovering it every time.

**Severity:** docs ecosystem gap, not a per-panel bug. Flagged for
the architect to decide whether to land the new spec.

---

## Overall verdict

The analytics-panel fix was the only panel-level `VISUAL REGRESSION`.
No other shipped panel inherits `ModalCard` today. Two NAMING DRIFT
items (Keithley v2 file location, ExperimentOverlay class name) are
mechanical cleanups that do not affect operator visuals. One docs
ecosystem gap (missing primary-view pattern spec) is a future
canonicalisation decision.

No remediation attempted in this audit per the Task 3 read-only
constraint. Recommend tracking:

1. `git mv shell/overlays/keithley_panel.py shell/views/keithley_panel.py`
   + import + spec `implements:` update. Low risk, one small commit.
2. Rename `ExperimentOverlay` → `ExperimentView` + move to
   `shell/views/`. Architect decision — class rename touches tests,
   shell, top-bar wiring. Medium-risk commit.
3. Land `components/primary-view.md` or `patterns/primary-view.md`
   canonicalising the QWidget / OverlayContainer pattern. Architect
   decision — docs-only, but sets vocabulary for future panels.
