---
title: ExperimentPanel (ExperimentOverlay)
keywords: experiment, phase stepper, timeline, finalize, abort, connection gating, K3 workflow
applies_to: Experiment management overlay (active experiment surface)
status: active
implements: src/cryodaq/gui/shell/experiment_overlay.py (B.8 + Phase II.9 harmonization)
last_updated: 2026-04-18
references: rules/color-rules.md, rules/copy-rules.md, cryodaq-primitives/experiment-card.md
---

# ExperimentOverlay

K3-critical surface. The operator's primary control point for in-progress experiments: rename, edit sample/description/notes, advance phase, finalize or abort. Ships at `src/cryodaq/gui/shell/experiment_overlay.py` (B.8 rebuild, harmonized in Phase II.9).

## Path choice (Phase II.9, 2026-04-18)

Stage 0 audit of `experiment_overlay.py`:

| Check                      | Result                  |
|----------------------------|-------------------------|
| Forbidden tokens           | **0 hits**              |
| Emoji (incl. ⬤ ✓ ⚠ ✘)      | **0 hits**              |
| Hardcoded hex              | **0 hits**              |
| Current DS tokens in use   | FOREGROUND, MUTED_FOREGROUND, BORDER, STATUS_OK, STATUS_FAULT, SPACE_1..5, RADIUS_MD/SM, FONT_BODY/MONO/DISPLAY |

**Decision: Path A — surgical harmonization.** The overlay was already DS v1.0.1-compliant at shipping (B.8). The single remaining gap was the missing Host Integration Contract: `set_connected(bool)` to disable action buttons on engine silence. Path A lands exactly that hook with a minimal diff; Path B would have been churn without deliverable improvement.

## Harmonization delta

- `_connected: bool = True` — new attribute, defaults True so nothing regresses on pre-first-tick usage.
- `set_connected(connected: bool) -> None` — new public method. Disables `_save_btn`, `_finalize_btn`, `_prev_btn`, `_next_btn` on `False`. Idempotent.
- `_apply_connection_gate()` — internal helper. Handles the button enabled-state logic.
- `_refresh_display()` — updated to respect `self._connected` when re-rendering the active experiment (so reconnect-after-set-experiment also picks up the gate).
- `MainWindowV2._tick_status` — added Phase II.9 mirror (same pattern as II.4 / II.8).
- `MainWindowV2._ensure_overlay("experiment")` — replay connection state on first open (same pattern as `keithley` / `log` / `archive` / `conductivity` / `calibration` / `instruments`).

**Functional behavior preserved verbatim.** No engine command signatures changed, no layout reordering, no callback interface changes, no new DS tokens introduced.

## Tokens (already in use, documented here)

- `BACKGROUND` — overlay root.
- `FOREGROUND` — name label, phase pill (current state).
- `MUTED_FOREGROUND` — passport line, phase status, timeline header, save-status text, nav arrow, past phase labels.
- `BORDER` — divider, phase pill borders (past / future).
- `STATUS_OK` — current phase pill border (green highlight).
- `STATUS_FAULT` — finalize button (destructive accent).
- Typography: `FONT_BODY` for labels, `FONT_DISPLAY` for the name, `FONT_MONO` for the passport line.
- Spacing: `SPACE_1 / SPACE_2 / SPACE_3 / SPACE_4 / SPACE_5`.
- Radii: `RADIUS_MD` (phase frame), `RADIUS_SM` (pills, buttons).

## Public API

```python
class ExperimentOverlay(QWidget):
    experiment_finalized = Signal()
    experiment_updated = Signal()
    closed = Signal()

    def set_experiment(self, experiment: dict | None, phase_history: list[dict] | None = None) -> None: ...
    def set_templates(self, templates: list[dict]) -> None: ...
    def on_reading(self, reading) -> None: ...

    # Phase II.9 Host Integration Contract
    def set_connected(self, connected: bool) -> None: ...
```

## Host Integration Contract

`MainWindowV2` must:

1. Build the overlay lazily via `_OVERLAY_FACTORIES["experiment"]`.
2. Mirror connection state from `_tick_status` into `set_connected(bool)`.
3. Replay connection state on first open via `_ensure_overlay("experiment")`.
4. Route `analytics/operator_log_entry` readings to `on_reading` for live timeline refresh.
5. Connect the overlay's `closed` / `experiment_finalized` signals to navigation hooks.

See `src/cryodaq/gui/shell/main_window_v2.py` for the canonical wiring (import at line 35, factory at line 131, wiring at `_tick_status` + `_ensure_overlay`).

## Rules cross-reference

- `rules/color-rules.md` RULE-COLOR-010 — no hardcoded hex (satisfied; zero hits in Stage 0).
- `rules/copy-rules.md` RULE-COPY-005 — no emoji (satisfied; zero hits in Stage 0).
- `rules/interaction-rules.md` RULE-INTERACT-001 — engine-command-dispatching buttons must be gated by connection state (satisfied via `set_connected`).

## Fail-OPEN

- Disconnected + active experiment → action buttons disable, but phase pills and timeline remain fully visible. Operator retains situational awareness even during engine silence.
- Reconnect → buttons re-enable on next `_tick_status`.

## Changelog

- **2026-04-18 (Phase II.9)** — harmonization landed: `set_connected` Host Integration Contract added; `MainWindowV2` wired. No DS token churn (audit showed zero forbidden hits).
- **Phase I.1 B.8 (prior)** — initial card-style rebuild replacing tab-based `ExperimentWorkspace`.
