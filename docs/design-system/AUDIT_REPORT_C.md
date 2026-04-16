# Audit Report C — Patterns + Accessibility + Governance

## Summary
- Files audited: 20
- CRITICAL issues: 1
- HIGH issues: 5
- MEDIUM issues: 1
- LOW issues: 0

## CRITICAL

### C2.1 — Contrast matrix contains materially incorrect WCAG ratios and stale token inputs
**Files:**
- `docs/design-system/accessibility/contrast-matrix.md:28-55, 89-96`
- `src/cryodaq/gui/theme.py:35-61, 197-208`

**Issue:** The contrast matrix is not merely rounded differently; multiple published ratios are mathematically wrong when recomputed against the actual theme tokens in `theme.py`.

Verified examples:
- `STATUS_WARNING #c4862e` vs `BACKGROUND #0d0e12`
  - matrix: **6.93:1** (`contrast-matrix.md:35`)
  - actual: **6.24:1**
- `STATUS_OK #4a8a5e` filled pill with `ON_DESTRUCTIVE #e8eaf0`
  - matrix: **5.74:1** (`contrast-matrix.md:50`)
  - actual: **3.43:1**
- `STATUS_FAULT #c44545` filled pill with `ON_DESTRUCTIVE #e8eaf0`
  - matrix: **6.87:1** (`contrast-matrix.md:53`)
  - actual: **4.07:1**
- `BORDER #2d3038` vs `BACKGROUND #0d0e12`
  - matrix: **3.11:1** (`contrast-matrix.md:91`)
  - actual: **1.46:1**

The filled-pill table is especially compromised because it uses `ON_DESTRUCTIVE #f5f5f7` in the prose table (`contrast-matrix.md:50-55`), while `theme.py` defines `ON_DESTRUCTIVE = "#e8eaf0"` (`theme.py:45`).

This invalidates the design-system’s claimed accessibility math as a source of truth.

**Recommendation:** Recompute the full matrix from current `theme.py` values, update the table and downstream conclusions, and treat current accessibility conclusions derived from this file as untrusted until corrected.

## HIGH

### C3.1 — WCAG baseline claims 1.4.11 “Met” using a contrast ratio that is false
**File:** `docs/design-system/accessibility/wcag-baseline.md:58-64`

**Issue:** `wcag-baseline.md` marks **1.4.11 Non-text Contrast (AA)** as `Met`, with explicit evidence:
`BORDER #2d3038 vs BACKGROUND #0d0e12 = 3.1:1 ✓`.

That supporting number is wrong. Recalculation against current `theme.py` gives **1.46:1**, not 3.1:1. This means the criterion mapping is not just weakly justified; its cited basis is false.

Spot-checking other criterion numbers/levels (e.g. 1.3.4 AA, 2.1.4 A, 2.4.11 AA, 2.5.8 AA, 3.3.8 AA) did not reveal numbering/level mistakes. The problem is the compliance claim riding on bad measurements.

**Recommendation:** Downgrade the 1.4.11 commitment until the contrast matrix is corrected, then re-evaluate the criterion mapping against the repaired data.

### C1.1 / C6.1 — Multiple patterns compose around nonexistent or obsolete primitives/tokens
**Files:**
- `docs/design-system/patterns/page-scaffolds.md:70, 96, 99, 126, 150`
- `docs/design-system/patterns/cross-surface-consistency.md:86-88`
- `docs/design-system/patterns/responsive-behavior.md:61, 67-71, 77, 94, 131, 149, 176`
- `src/cryodaq/gui/shell/overlays/_design_system/bento_grid.py:9-18, 39-52`
- `src/cryodaq/gui/theme.py` (no `OVERLAY_*` tokens present)

**Issue:** The pattern layer still composes around artifacts that are not real in the shipped codebase:
- `PanelCard` is treated as a live scaffold primitive in `page-scaffolds.md` and `cross-surface-consistency.md`, but there is no `PanelCard` implementation in `src/cryodaq/gui/`.
- `responsive-behavior.md` depends on `OVERLAY_MAX_WIDTH`, but `theme.py` defines no `OVERLAY_*` tokens.
- `page-scaffolds.md` and `responsive-behavior.md` both codify an **8-column BentoGrid**, while the shipped Phase I.1 implementation is **12-column** and supports **auto-flow** (`bento_grid.py:15-17, 39-42`).

This makes the pattern layer non-composable against the current primitives layer.

**Recommendation:** Rewrite these patterns against the actual shipped primitives, or explicitly mark `PanelCard` / `OVERLAY_MAX_WIDTH` / 8-column BentoGrid as future-state proposals instead of current composition rules.

### C8.1 — Keyboard shortcut registry conflicts with keyboard-navigation and ToolRail docs
**Files:**
- `docs/design-system/accessibility/keyboard-navigation.md:48-66`
- `docs/design-system/tokens/keyboard-shortcuts.md:26-43, 48-53, 75-84`
- `docs/design-system/cryodaq-primitives/tool-rail.md:28-38`
- `docs/design-system/patterns/destructive-actions.md:176-182`

**Issue:** There are two incompatible “source of truth” registries for shortcuts:
- `keyboard-navigation.md` and `tool-rail.md` agree on global navigation shortcuts: `Ctrl+1..9`, `Ctrl+L`, `Ctrl+A`, `Ctrl+Shift+X`, `F5`, `F11`.
- `tokens/keyboard-shortcuts.md` defines a different proposed global scheme: `Ctrl+E`, `Ctrl+K`, `Ctrl+M`, `Ctrl+R`, `Ctrl+C`, `Ctrl+D`, and even reuses `Ctrl+1..6` for phase jumps.

This is a direct operator-facing inconsistency. An implementer cannot follow both documents at once.

**Recommendation:** Choose one registry as canonical. If the token registry is future-state only, mark it clearly as superseded-by / not yet adopted, and remove the conflicting bindings from operator-facing accessibility docs until migration actually happens.

### C5.1 — Token-naming registry does not match the prefixes and scale actually shipped in `theme.py`
**Files:**
- `docs/design-system/governance/token-naming.md:91-107, 182-200, 246`
- `src/cryodaq/gui/theme.py:31-61, 157-180, 190-274`

**Issue:** `token-naming.md` claims a canonical prefix registry and spacing scale, but it diverges from the live token inventory:
- It documents `SPACE_1..SPACE_9` (`token-naming.md:95-105`), while `theme.py` ships `SPACE_0..SPACE_6` only.
- It registers `OVERLAY_` as a current token family (`token-naming.md:199, 246`), but there are no `OVERLAY_*` tokens in `theme.py`.
- It omits live prefixes that do exist in `theme.py`, including at least `SURFACE_`, `TEXT_`, `TRANSITION_`, `QUANTITY_`, `QDARKTHEME_`, `SUCCESS_`, `WARNING_`, `DANGER_`, `ACCENT_`, `BORDER_`, `CARD_`, and `MUTED_`.

For a governance registry, that is not a cosmetic mismatch. It means the naming policy is not an accurate map of the system it claims to govern.

**Recommendation:** Rebuild the prefix registry from the actual `theme.py` export set, and clearly separate canonical families from deprecated aliases / compatibility families.

### C5.2 — Versioning document names release artifacts that do not exist in the deployed tree
**Files:**
- `docs/design-system/governance/versioning.md:23-29, 91-123, 205-209`
- filesystem check: `docs/design-system/VERSION` absent, `docs/design-system/CHANGELOG.md` absent

**Issue:** `versioning.md` says the current version is tracked in:
- `design-system/VERSION`
- `design-system/README.md`
- git tag `design-system-v1.0.0`

and later says release process includes updating `VERSION` and `CHANGELOG.md`.

In the deployed tree, `docs/design-system/VERSION` and `docs/design-system/CHANGELOG.md` do not exist. This leaves the governance release process partially fictional and untestable.

**Recommendation:** Either create the promised release artifacts or rewrite the versioning doc to match the actual repository structure and release mechanism.

## MEDIUM

### C9.1 / C5.3 — Motion docs disagree with the actual token state in `theme.py`
**Files:**
- `docs/design-system/tokens/motion.md:13-16, 38-47, 148-161`
- `docs/design-system/accessibility/reduced-motion.md:31-44, 79-88, 195`
- `src/cryodaq/gui/theme.py:157-159`

**Issue:** `tokens/motion.md` says motion tokens are **not yet** in `theme.py` and that code should use literals until they land. But `theme.py` already ships `TRANSITION_FAST_MS`, `TRANSITION_BASE_MS`, and `TRANSITION_SLOW_MS`.

At the same time, `reduced-motion.md` speaks as if a centralized `MotionPolicy` layer exists, while the token doc still frames the motion system as pre-token/proposed.

This is not as damaging as the contrast errors, but it means the motion/governance layer is not self-consistent about what the current source of truth actually is.

**Recommendation:** Decide whether motion is still “proposed” or already partially landed. Then align `tokens/motion.md`, `reduced-motion.md`, and `theme.py` around one truthful current-state story.

## LOW

None.

## Conclusion

The meta-layer is not structurally broken end-to-end, but it is not trustworthy enough to support compliance or implementation without correction. The most serious defect is the contrast layer: `contrast-matrix.md` contains materially wrong numbers, and `wcag-baseline.md` builds at least one AA claim directly on those bad calculations. The next tier of problems is governance/pattern drift: stale references to `PanelCard`, `OVERLAY_MAX_WIDTH`, 8-column BentoGrid, conflicting shortcut registries, and a token-naming registry that no longer describes the actual token surface in `theme.py`. The good news is that RULE-GOV forward refs are closed, the version number is internally consistent between `versioning.md` and `MANIFEST.md`, and the copy-voice lexicon covers the key CryoDAQ domain vocabulary. The bad news is that the accessibility and governance layers currently overstate their own integrity.
