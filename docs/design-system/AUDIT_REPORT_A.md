# Audit Report A — Foundation + Rules

## Summary
- Files audited: 24
- CRITICAL issues: 0
- HIGH issues: 3
- MEDIUM issues: 5
- LOW issues: 4

Implemented token values in the audited token docs are mostly aligned with `src/cryodaq/gui/theme.py`; I did not find a direct hex/number drift in the documented non-proposed token rows. The foundation layer is still not clean: one token document lies about what exists in `theme.py`, four `python` code blocks in rules are syntactically invalid, there is one direct rule contradiction on stale text rendering, and the root docs disagree with each other about grid structure and chart-token inventory.

## CRITICAL

No CRITICAL issues found under A1. The implemented token rows I checked in `tokens/colors.md`, `tokens/typography.md`, `tokens/spacing.md`, `tokens/radius.md`, `tokens/layout.md`, and the implemented portions of `tokens/chart-tokens.md` match the values currently defined in `src/cryodaq/gui/theme.py`.

## HIGH

### A1.1 — `tokens/motion.md` falsely claims motion tokens are absent from `theme.py`
**File:** `docs/design-system/tokens/motion.md:13-15`; `src/cryodaq/gui/theme.py:157-159`

**Issue:** `tokens/motion.md` says motion tokens are “NOT yet in `src/cryodaq/gui/theme.py`” and instructs widget code to use literal values until they are added. That is false: `theme.py` already defines `TRANSITION_FAST_MS = 150`, `TRANSITION_BASE_MS = 200`, and `TRANSITION_SLOW_MS = 300`.

**Recommendation:** Rewrite the motion token doc to acknowledge existing transition constants, distinguish current runtime tokens from proposed future expansion, and remove the instruction to use literals.

### A7.1 — `surface-rules.md` contains three `python` code blocks that are not valid Python
**File:** `docs/design-system/rules/surface-rules.md:448-460`, `docs/design-system/rules/surface-rules.md:464-470`, `docs/design-system/rules/surface-rules.md:475-484`

**Issue:** Three blocks under `RULE-SURF-008` are fenced as `python`, but they are actually ASCII tree diagrams. `ast.parse` fails on them with `SyntaxError` / `unexpected indent`.

**Recommendation:** Re-fence these blocks as `text` or rewrite them into syntactically valid Python pseudocode.

### A7.2 — `content-voice-rules.md` contains an invalid `python` example block
**File:** `docs/design-system/rules/content-voice-rules.md:246-258`

**Issue:** The “bad” example under `RULE-COPY-004` is fenced as `python`, but the block is not syntactically valid Python. Bare string literals with trailing comments are fine individually, but the final multiline concatenation is malformed as written and fails `ast.parse`.

**Recommendation:** Rewrite the example into valid Python string assignments or re-fence it as `text`.

## MEDIUM

### A6.1 — `RULE-DATA-005` contradicts `RULE-A11Y-003` on stale body text color
**File:** `docs/design-system/rules/data-display-rules.md:245-250`; `docs/design-system/rules/accessibility-rules.md:155-173`

**Issue:** `RULE-DATA-005` says stale sensor cells should render “value + unit in `STATUS_STALE`.” `RULE-A11Y-003` says `STATUS_STALE` fails WCAG for body text and must not be used for body-size text; instead use `FOREGROUND` text plus icon/border.

**Recommendation:** Choose one canonical stale treatment and update the other rule. Right now the rule system gives mutually exclusive instructions.

### A4.1 — 19 anti-pattern cases have no direct `RULE-*` anchor
**File:** `docs/design-system/ANTI_PATTERNS.md`

**Examples:**
- `radius-12-or-16` at line 106
- `tailwind-material-shades` at line 144
- `emoji-as-icon` at line 314
- `chart-surface-elevation` at line 435
- `window-too-small-silently` at line 479

**Issue:** These entries describe forbidden patterns but do not cite any concrete `RULE-*`. That weakens enforceability and breaks the stated “rule-system anchored” structure.

**Recommendation:** Add at least one explicit `Violates RULE-...` reference to each anti-pattern case, or downgrade `ANTI_PATTERNS.md` from enforcement language to informal guidance.

### A6.2 — Root docs disagree on BentoGrid column count
**File:** `docs/design-system/MANIFEST.md:44`, `docs/design-system/MANIFEST.md:158`, `docs/design-system/tokens/breakpoints.md:41`, `docs/design-system/tokens/breakpoints.md:96`

**Issue:** `MANIFEST.md` says `bento-grid.md` is an “8-column layout engine” and later states “BentoGrid stays 8 columns at all viewports.” `tokens/breakpoints.md` defines `DASHBOARD_GRID_COLUMNS = 12` and says dashboard uses a 12-column logical grid.

**Recommendation:** Normalize the design system to one grid definition. Right now the foundation docs encode two incompatible layout models.

### A9.1 — Chart-token inventory is internally inconsistent and omits runtime tokens
**File:** `docs/design-system/README.md:68`, `docs/design-system/tokens/chart-tokens.md:14`, `src/cryodaq/gui/theme.py:165-174`

**Issue:** `README.md` says `chart-tokens.md` covers 12 pyqtgraph-specific tokens. `chart-tokens.md` says total = 10 tokens. `theme.py` currently exposes 12 chart-related runtime tokens if counted honestly: `PLOT_BG`, `PLOT_FG`, `PLOT_GRID_COLOR`, `PLOT_GRID_ALPHA`, `PLOT_LABEL_COLOR`, `PLOT_TICK_COLOR`, `PLOT_LINE_WIDTH`, `PLOT_LINE_WIDTH_HIGHLIGHTED`, `PLOT_REGION_FAULT_ALPHA`, `PLOT_REGION_WARN_ALPHA`, `PLOT_LINE_PALETTE`, `PLOT_AXIS_WIDTH_PX`.

**Recommendation:** Recount and document the chart token surface consistently across `README.md`, `chart-tokens.md`, and `theme.py`.

### A8.1 — `tokens/elevation.md` contains an untraced hex value outside token or explicit bad-example context
**File:** `docs/design-system/tokens/elevation.md:24`

**Issue:** `#090a0d` appears as a derived shadow-result color. It is not a token in `theme.py`, not a documented exception, and not presented as a violation example. That breaks the “all hexes traced or explicitly bad” rule stated in `MANIFEST.md`.

**Recommendation:** Either rewrite this as prose without a raw hex, convert it into a token-backed explanation, or mark it explicitly as a derived explanatory value.

## LOW

### A5.1 — 17 audited docs fail the minimum front-matter contract
**File:** multiple

**Issue:** The audit contract required `title`, `status`, and `last_updated` in every audited markdown file, with `keywords` and `applies_to` additionally required for rules. These files violate that:
- Missing `status`: `README.md`, `ANTI_PATTERNS.md`, `tokens/colors.md`, `tokens/typography.md`, `tokens/spacing.md`, `tokens/radius.md`, `tokens/layout.md`, `tokens/chart-tokens.md`, `rules/color-rules.md`, `rules/surface-rules.md`, `rules/typography-rules.md`, `rules/spacing-rules.md`, `rules/interaction-rules.md`, `rules/data-display-rules.md`, `rules/accessibility-rules.md`, `rules/content-voice-rules.md`
- Missing front matter entirely: `MANIFEST.md`

**Recommendation:** Normalize front matter across the root docs, token docs, and rule docs so tooling can reason about status consistently.

### A9.2 — `MANIFEST.md` line-count statistic is stale
**File:** `docs/design-system/MANIFEST.md:95`

**Issue:** `MANIFEST.md` claims “66 files, ~20 459 lines.” Actual count in `docs/design-system/` is 66 markdown files and 20 507 lines.

**Recommendation:** Refresh the statistics block or mark it as approximate generated metadata.

### A5.2 — `README.md` file-structure index omits `rules/governance-rules.md`
**File:** `docs/design-system/README.md:75-83`

**Issue:** The README lists eight files under `rules/` and omits `governance-rules.md`, while `MANIFEST.md` correctly lists nine rule files.

**Recommendation:** Add `governance-rules.md` to the README’s file-structure tree or explain why it is intentionally excluded.

### OTHER.1 — `theme.py` still points to deleted design-system docs
**File:** `src/cryodaq/gui/theme.py:10-11`

**Issue:** The module docstring still references `docs/design-system/MASTER.md` and `docs/design-system/FINDINGS.md`, but those files are no longer in the deployed design system tree.

**Recommendation:** Update the docstring to point at `docs/design-system/README.md` and `docs/design-system/MANIFEST.md`.

## Conclusion

Foundation + rules are not broken at the value layer: the implemented token values documented in the audited token files are broadly in sync with `theme.py`, RULE IDs are unique and sequential, and cross-rule references resolve. The problems are structural honesty and enforceability. One token document misstates the runtime source of truth, four `python` code examples are unparsable, one core stale-data rule contradicts accessibility guidance, the anti-pattern catalog is only partially anchored in the rule system, and the root docs disagree about grid and chart foundations. This is fixable, but I would not call the foundation layer “fully internally consistent” until those issues are cleaned up.
