# Audit Report B — Components + Primitives

## Summary
- Files audited: 23
- CRITICAL issues: 0
- HIGH issues: 5
- MEDIUM issues: 3
- LOW issues: 1

## CRITICAL

None.

## HIGH

### B3.1 — Invalid Python signature in Toast API example
**File:** `docs/design-system/components/toast.md:263-310`

**Issue:** The documented API example is not valid Python 3.12+. It uses placeholder ellipses directly in a function signature:
`def __init__(self, ..., duration_ms: int | None = None, ...):`
That does not parse under `ast.parse`, so the component spec fails the “copy/paste-able reference” bar required for implementation guidance.

**Recommendation:** Replace ellipsis placeholders inside the signature with concrete parameters or move omissions into comments outside the function signature.

### B4.1 / B6.1 — BentoGrid spec materially disagrees with the current implementation
**File:** `docs/design-system/components/bento-grid.md:40-59, 63-149, 213-217, 242`

**Issue:** The spec claims all of the following as facts of the current implementation:
- default width is **8 columns**
- explicit placement only, **no auto-flow**
- placement validation includes **overlap detection**
- changelog says Phase I.1 implementation shipped exactly that model

Current implementation says otherwise:
- `src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py:10-18` defaults to **12 columns**
- `src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py:39-42` supports **auto-flow** when `col` / `row` are omitted
- `src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py:44-52` validates bounds, but does **not** track overlaps

This is not editorial drift; it changes how an implementer would build layouts against the component contract.

**Recommendation:** Rewrite `bento-grid.md` to match the actual Phase I.1 implementation, or explicitly mark the 8-column / explicit-only model as a future proposal rather than “reference implementation”.

### B6.2 — Card spec presents a nonexistent `PanelCard` implementation as current reference code
**File:** `docs/design-system/components/card.md:6, 70-100, 188-280, 340`

**Issue:** The document mixes three incompatible claims:
- front-matter says the component is implemented via `modal_card.py` specialized variant
- the main API section defines a proposed `PanelCard`
- the “Reference implementation” section points to `src/cryodaq/gui/shell/overlays/_design_system/panel_card.py`

That file does not exist in the repo, and `rg -n "class PanelCard" src/cryodaq/gui -g '*.py'` returns no implementation. The changelog then says `PanelCard` “could be extracted as shared base”, which directly contradicts presenting it as a reference implementation.

**Recommendation:** Mark `PanelCard` unambiguously as proposed-only, or point the document at the real existing implementation (`modal_card.py`) until extraction actually exists.

### B6.3 — PhaseStepper points to the wrong implementation path
**File:** `docs/design-system/cryodaq-primitives/phase-stepper.md:1-7, 91-95`

**Issue:** The primitive claims `implements: src/cryodaq/gui/shell/overlays/_design_system/phase_aware_widget.py`, but the actual class is at `src/cryodaq/gui/dashboard/phase_aware_widget.py:37`. There is no `_design_system/phase_aware_widget.py` in the repo.

For a domain primitive spec, this is a high-severity traceability failure: the document sends an implementer to the wrong code.

**Recommendation:** Update `implements:` and API comments to the real file path, or mark the overlay extraction as future work if that was the intended destination.

### B6.4 — SensorCell points to the wrong implementation path and misstates the surrounding grid model
**File:** `docs/design-system/cryodaq-primitives/sensor-cell.md:1-7, 41, 263-267, 324-326`

**Issue:** The primitive claims `implements: src/cryodaq/gui/shell/overlays/_design_system/dynamic_sensor_grid.py`, but the real classes are:
- `src/cryodaq/gui/dashboard/sensor_cell.py:51` — `SensorCell`
- `src/cryodaq/gui/dashboard/dynamic_sensor_grid.py:24` — `DynamicSensorGrid`

The same document also describes the current grid as “responsive 8-column”, but the actual implementation computes a width-based dynamic column count from minimum cell width (`dynamic_sensor_grid.py:101-128`).

This is again implementation guidance drift, not wording noise.

**Recommendation:** Point the spec at the real dashboard implementation files and describe the actual width-driven layout logic instead of the invented “responsive 8-column” model.

## MEDIUM

### B8.1 — Dialog is interactive but has no explicit states matrix
**File:** `docs/design-system/components/dialog.md:89-295`

**Issue:** `Dialog` has anatomy, invariants, and API, but no `## States` / visual state matrix section at all. For an interactive overlay component this leaves hover/focus/default/disabled treatment implicit, especially for action buttons and destructive vs safe-default focus behavior.

**Recommendation:** Add an explicit states matrix covering default, focus trap active, destructive-confirm default-focus-on-cancel, disabled action, and dismiss animation states.

### B8.2 — SensorCell state matrix omits hover/focus interaction states
**File:** `docs/design-system/cryodaq-primitives/sensor-cell.md:66-78`

**Issue:** The primitive is explicitly interactive (`clicked`, `double_clicked`, diagnostic drill-down at `sensor-cell.md:97-113` and invariant 10 at `:64-65`), but the visual state matrix covers only data/domain states (`OK`, `Warning`, `Caution`, `Fault`, `Stale`, `Disconnected`, `Cold channel`). It does not specify hover, keyboard focus, or active/pressed feedback.

That leaves implementation freedom exactly where operator discoverability matters.

**Recommendation:** Extend the matrix with hover and focus states at minimum, and clarify whether click/press has any visual acknowledgment beyond domain color.

### B7.1 — Button spec includes a hardcoded destructive pressed-state hex in a normative example
**File:** `docs/design-system/components/button.md:202-227`

**Issue:** The destructive-button example uses `background: #a53838;` for `:pressed` in a normative code block. The note below acknowledges this is an exception that should become a token, but under the audit rule this is still a token-bypass in a good-example section, not a bad-example section.

**Recommendation:** Replace the literal with a named token before keeping this example as normative, or move the snippet into a documented temporary exception section with a stronger “do not copy” marker.

## LOW

### B1.1 / B5.1 — All audited component-spec files are missing `references:` in front matter
**File:** all 23 files in scope

**Issue:** Every audited component/primitive file has front-matter with `title`, `keywords`, `applies_to`, `status`, `implements`, and `last_updated`, but none include the requested `references:` key.

This does not break the spec layer directly, but it weakens traceability and makes upstream/downstream linkage less explicit.

**Recommendation:** Add a `references:` key consistently across the entire component-spec layer, even if initially populated with a short list of related rules, tokens, and implementation files.

## Conclusion

The component-spec layer is structurally usable, and the domain-fact layer is in better shape than the raw traceability layer: I did **not** find the high-cost B5 failures this audit was specifically watching for (wrong `Т11/Т12` metrology claim, Latin `T` in operator-facing examples, uppercase FSM states as normative UI text, or SCPI replacing Keithley TSP). The main problems are elsewhere: several specs point to nonexistent or wrong implementation files, `bento-grid.md` no longer describes the actual shipped grid primitive, and one code example (`toast.md`) is not syntactically valid Python. That means the layer is directionally sound but not yet trustworthy as an implementation source of truth without a cleanup pass on traceability and example accuracy.
