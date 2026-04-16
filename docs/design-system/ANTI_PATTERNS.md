---
title: Anti-Patterns Catalog
keywords: anti-pattern, forbidden, regression, mistake, history, commit, lesson
applies_to: all widget code
enforcement: strict
priority: critical
last_updated: 2026-04-17
status: canonical
---

# Anti-Patterns Catalog

Catalog of patterns that MUST NOT appear in CryoDAQ GUI code. Each entry documents:
- What the pattern is
- Why it's forbidden
- Historical context (where we encountered it, if applicable)
- Correct alternative

This file is **grep-friendly by design**. Search for specific symptoms here when debugging visual issues.

## Navigation

- [Surfaces](#surfaces)
- [Radius](#radius)
- [Color](#color)
- [Typography](#typography)
- [Spacing](#spacing)
- [Motion](#motion)
- [Elevation](#elevation)
- [Icons](#icons)
- [Interaction](#interaction)
- [Data Display](#data-display)
- [Charts](#charts)
- [Layout](#layout)

---

## Surfaces

### case: modal-card-nested-surface

**Pattern:** ModalCard's `_content_host` had implicit painted background, creating visible "inner sharp rectangle" nested inside "outer rounded card."

**Historical occurrence:** Phase I.1 commit `d87c24b`. Fixed in `cf72942`.

**Why forbidden:** Violates RULE-SURF-001 (single visible surface per card). Operators interpret stacked rectangles as hierarchical containers — cognitive split.

**Visual symptom:** Two distinct dark shades visible inside one card. Inner rectangle usually has sharp corners contrasting with outer rounded card.

**Fix:** Child content hosts MUST have explicit transparent background:

```python
self._content_host.setStyleSheet(
    "#modalCardContentHost { background: transparent; border: none; }"
)
```

### case: card-inside-card-same-category

**Pattern:** `ModalCard` containing another `ModalCard`, or `PanelCard` containing `PanelCard`.

**Why forbidden:** Violates RULE-SURF-005. No semantic nesting of same-category containers. Creates "Russian doll" visual pattern.

**Fix:** Nest different semantic categories. Modal → Grid → Tile, not Modal → Modal. See `components/modal.md`.

### case: sharp-rectangle-inside-rounded-card

**Pattern:** Parent card has `border-radius: 8` (RADIUS_LG), child has `border-radius: 0`.

**Historical occurrence:** Phase I.1 initial implementation.

**Why forbidden:** Violates RULE-SURF-002. Mixing sharp and rounded corners = broken hierarchy perception.

**Fix:** Either remove child background (transparent) OR give child `RADIUS_MD` / `RADIUS_SM` (smaller than parent, but > 0).

### case: asymmetric-card-padding

**Pattern:** `setContentsMargins(SPACE_5, SPACE_3, SPACE_5, SPACE_5)` — top padding smaller than sides.

**Historical occurrence:** Phase I.1 commit `d87c24b` (attempting to reduce "empty space above breadcrumb"). Fixed in `cf72942`.

**Why forbidden:** Violates RULE-SURF-003. Makes card look cut-off or accidentally truncated.

**Fix:** Keep symmetric padding, restructure header row instead. Proper header layout:

```python
# Single row: breadcrumb + stretch + close button, all sharing vertical baseline
header_row = QHBoxLayout()
header_row.addWidget(breadcrumb, 1)  # expanding
header_row.addWidget(close_button, 0, Qt.AlignmentFlag.AlignVCenter)
```

### case: close-button-own-row

**Pattern:** Close (×) button placed in its own top row, above breadcrumb/title in a separate row.

**Historical occurrence:** Phase I.1 commit `e25bbd9`. Fixed in `cf72942`.

**Why forbidden:** Violates RULE-SURF-004. Operators expect close button and header on single baseline. Stacking wastes vertical space.

**Fix:** Single HBox with breadcrumb + stretch + close button on one baseline.

---

## Radius

### case: radius-12-or-16

**Pattern:** `border-radius: 12` or `border-radius: 16` (Tailwind-typical card radius).

**Why forbidden:** Radius values not in CryoDAQ scale. Scale is NONE=0, SM=4, MD=6, LG=8, FULL=9999. Adding ad-hoc values breaks consistency.

**Fix:** Use `RADIUS_LG` (8) for max. If genuinely need larger, discuss with Vladimir before creating new token.

**Related rules:** RULE-SURF-006 (radius hierarchy cascade).

### case: radius-none-on-interactive

**Pattern:** Button or input with `RADIUS_NONE` (0) in an otherwise rounded UI.

**Why forbidden:** Creates unexpected sharp controls among rounded siblings. Visual inconsistency.

**Fix:** Buttons/inputs use `RADIUS_SM` (4). RADIUS_NONE is for separators, plot axes, full-width banners only.

**Related rules:** RULE-SURF-006 (radius hierarchy cascade).

---

## Color

### case: violet-phase-stepper

**Pattern:** Phase stepper in dashboard uses violet/purple color for active phase.

**Historical occurrence:** Ongoing until Phase II.9 fix. `ACCENT #7c8cff` (periwinkle, leans violet) was applied to active phase indication.

**Why forbidden:** `ACCENT` is semantically locked to focus/selection affordance (RULE-COLOR-004). Active phase is a **status** concept (this phase is operational), which should use `STATUS_OK #4a8a5e` green.

**Fix:** Replace ACCENT with STATUS_OK for active phase border/fill in PhaseStepper widget. Reserve ACCENT strictly for keyboard focus ring, selected tab indicator, and similar interaction affordances.

### case: hardcoded-hex-literal

**Pattern:** `widget.setStyleSheet("background: #1a1a1a")` — raw hex in code.

**Why forbidden:** Violates RULE-GOV-001. Bypasses token system, creates drift. If theme changes, this widget doesn't update.

**Fix:** Use token: `f"background: {theme.CARD}"`.

### case: tailwind-material-shades

**Pattern:** Using Tailwind (`#22C55E`, `#EF4444`, `#0F172A`) or Material (`#4CAF50`, `#F44336`) color values.

**Why forbidden:** Wrong aesthetic. CryoDAQ palette is intentionally desaturated industrial — Tailwind/Material are saturated SaaS/app. Not substitutable.

**Fix:** Use CryoDAQ tokens. See `tokens/colors.md`.

**Related rules:** RULE-COLOR-010 (canonical token registry; non-sanctioned palettes forbidden).

### case: bright-primary-color

**Pattern:** `#FF0000`, `#00FF00`, `#0000FF` or near-primary saturated colors.

**Why forbidden:** Over-saturated on dark mode causes eye strain. Conflicts with desaturated aesthetic.

**Fix:** Use `STATUS_*` tokens (all desaturated) or appropriate `PLOT_LINE_PALETTE` entries.

**Related rules:** RULE-COLOR-010 (canonical token registry; saturated primaries are not sanctioned tokens).

### case: gradient-anything

**Pattern:** `background: linear-gradient(...)` anywhere.

**Why forbidden:** Not in CryoDAQ aesthetic. We use solid colors only.

**Fix:** Solid token. If trying to indicate progress, use a determinate percentage label, not gradient fill.

**Related rules:** None currently — advisory guidance.

---

## Typography

### case: latin-T-for-temperature-channel

**Pattern:** Channel label `"T1 Криостат верх"` using Latin T (U+0054).

**Why forbidden:** Violates RULE-COPY-001. Russian UI uses Cyrillic Т (U+0422). Latin T breaks Russian typographic consistency and may interact poorly with Cyrillic-optimized fonts.

**Fix:** Use Cyrillic Т throughout. Consistent across all 24 temperature channels.

### case: font-weight-below-400

**Pattern:** `FONT_WEIGHT_THIN` (100), `LIGHT` (300) used in operator-facing widgets.

**Why forbidden:** Violates RULE-TYPO-006. Ghostly on low-DPI lab monitors. Illegible at typical viewing distance.

**Fix:** Minimum `FONT_WEIGHT_REGULAR` (400) for all operator UI.

### case: programming-ligatures-in-numeric

**Pattern:** Fira Code default `liga: 1` active on data cells, causing `->`, `==`, `!=` to render as ligature glyphs.

**Why forbidden:** Violates RULE-TYPO-004. In numeric readout context, ligatures are rare but possible. When they occur, they confuse operators reading data.

**Fix:** Disable ligatures on numeric displays:

```python
font.setFeature("liga", 0)
```

### case: non-tabular-numbers-in-realtime-data

**Pattern:** Fira Sans body font used for live numeric values without `tnum` feature enabled.

**Why forbidden:** Violates RULE-TYPO-003. Digit widths differ, so when value changes from `4.21` to `4.30`, the `2` vs `3` have different widths, causing horizontal jitter.

**Fix:** Enable tabular numbers: `font.setFeature("tnum", 1)`. Or use `FONT_MONO_VALUE_*` preset which uses Fira Code (mono, tabular by default).

### case: cyrillic-uppercase-no-letter-spacing

**Pattern:** `"АВАР. ОТКЛ."` in default letter-spacing — glyphs cram together.

**Why forbidden:** Violates RULE-TYPO-005. Cyrillic uppercase has narrower default tracking than Latin; needs positive letter-spacing.

**Fix:** `font.setLetterSpacing(QFont.AbsoluteSpacing, 0.05)` for Cyrillic uppercase labels.

### case: off-scale-size-normalized

**Pattern:** Developer sees `FONT_MONO_VALUE_SIZE = 15` in theme.py and "normalizes" to `FONT_SIZE_BASE` (14) or `FONT_SIZE_LG` (16).

**Why forbidden:** Violates RULE-TYPO-007. The off-scale sizes (15, 32) solve specific legibility problems in specific widgets. Normalizing breaks that optimization.

**Fix:** Leave protected off-scale values intact. Respect them as intentional decisions.

---

## Spacing

### case: arbitrary-pixel-value

**Pattern:** `setContentsMargins(10, 14, 11, 9)` with no tokens.

**Why forbidden:** Violates RULE-GOV-001 and RULE-SPACE-*. Arbitrary values accumulate as drift.

**Fix:** Use `SPACE_*` scale tokens.

### case: inner-gap-larger-than-outer-margin

**Pattern:** `setContentsMargins(SPACE_3, SPACE_3, SPACE_3, SPACE_3)` + `setSpacing(SPACE_5)` — outer 12px, inner 24px.

**Why forbidden:** Violates RULE-SPACE-004 (hierarchy). Content inside feels more spread out than outer enclosure — looks disconnected.

**Fix:** Inner gap ≤ outer margin. Typical: outer `SPACE_5` (24), inner `SPACE_4` (16) or `SPACE_3` (12).

---

## Motion

### case: pulsing-status-indicator

**Pattern:** `QPropertyAnimation` on status dot's opacity, looping to "draw attention."

**Why forbidden:** Violates RULE-DATA-009 and motion philosophy. Pulsing distracts, creates visual noise, blends into background over long shifts as operator habituates.

**Fix:** Static status indicator. If important, use contrasting color and placement, not motion.

### case: count-up-animation-on-readings

**Pattern:** Sensor reading changes from 4.21 K to 4.30 K, animated via `QVariantAnimation` counting up.

**Why forbidden:** Obscures current value during animation. Operator sees misleading intermediate numbers.

**Fix:** Snap to new value instantly. Value update is atomic.

**Related rules:** None currently — advisory guidance.

### case: fade-in-fault

**Pattern:** Fault alarm appears via `QPropertyAnimation` fade-in over 300ms.

**Why forbidden:** Violates RULE-INTER-006. Critical state needs instant visibility.

**Fix:** Set `setVisible(True)` + background color change immediately.

### case: linear-easing

**Pattern:** `QEasingCurve.Linear` on any transition.

**Why forbidden:** Linear feels mechanical, not natural. All UI transitions should have acceleration/deceleration.

**Fix:** Use `QEasingCurve.InOutQuad` for symmetric, `OutQuad` for enter, `InQuad` for exit.

**Related rules:** None currently — advisory guidance.

---

## Elevation

### case: card-drop-shadow

**Pattern:** `QGraphicsDropShadowEffect` applied to dashboard tiles or sidebar cards.

**Why forbidden:** Violates zero-shadow policy. Dark-mode shadows are ineffective (barely visible) and expensive to render.

**Fix:** Rely on surface brightness delta. Tile has `SURFACE_CARD`, background has `BACKGROUND` — the contrast provides depth. No shadow needed.

**Exception:** modal cards MAY have the single permitted shadow (see `tokens/elevation.md`).

**Related rules:** RULE-SURF-010 (elevation via surface tokens only; zero-shadow policy).

### case: hover-lift

**Pattern:** Button or tile moves up on hover via transform or margin change.

**Why forbidden:** Material Design "paper lifts to finger" metaphor. Wrong for industrial UI. Operators expect static elements.

**Fix:** Hover state uses `MUTED` background, no transform.

**Related rules:** RULE-SURF-010 (elevation via surface tokens only).

### case: z-index-magic-number

**Pattern:** `widget.setZValue(42)` with no semantic comment.

**Why forbidden:** Unclear what layer 42 means. Future developers don't know whether new widgets should be above or below.

**Fix:** Use semantic Z constants (see `tokens/elevation.md` — `Z_MODAL`, `Z_TOAST`, etc.).

**Related rules:** None currently — advisory guidance.

---

## Icons

### case: emoji-as-icon

**Pattern:** Bell emoji 🔔 for notifications, ⚠️ for warnings, ✅ for success.

**Why forbidden:** Cultural/OS inconsistency, wrong aesthetic, accessibility issues. See `tokens/icons.md` for full rationale.

**Fix:** Use Lucide SVG icons (`bell.svg`, `alert-triangle.svg`, `check-circle.svg`).

**Related rules:** RULE-COPY-005 (no emoji in UI chrome).

### case: hardcoded-icon-color

**Pattern:** SVG with `stroke="#FF0000"` embedded — doesn't adapt to theme.

**Why forbidden:** Violates RULE-COLOR-005 (icon color inheritance).

**Fix:** Recolor SVG dynamically or use `currentColor` stroke value.

### case: icon-only-button-no-tooltip

**Pattern:** Button with only icon, no tooltip, no visible label.

**Why forbidden:** Violates RULE-INTER-008. Unlearnable — operator cannot discover what button does.

**Fix:** Add tooltip with description and optional shortcut hint:

```python
button.setToolTip("Закрыть (Esc)")
```

---

## Interaction

### case: hover-only-affordance

**Pattern:** Button becomes visible or reveals action only on hover.

**Why forbidden:** Violates discoverability principle. Operator under stress cannot hover to find options.

**Fix:** Affordance visible by default. Hover adds emphasis, not reveals function.

**Related rules:** RULE-INTER-012 (affordance visible by default, not hover-only).

### case: single-click-destructive-action

**Pattern:** "Удалить эксперимент" or "Аварийное отключение" executes on single click.

**Why forbidden:** Destructive actions need confirmation (RULE-INTER-004). One misclick = data loss or safety trigger.

**Fix:** Hold-to-confirm pattern (1 second press) OR modal confirmation dialog. See `patterns/destructive-actions.md`.

### case: keyboard-shortcut-hardcoded

**Pattern:** `QShortcut(QKeySequence("Ctrl+L"), self)` with raw string in widget code.

**Why forbidden:** Violates RULE-INTER-009. Bypasses central registry, risks collision.

**Fix:** Import from `cryodaq.gui.shortcuts`:

```python
from cryodaq.gui import shortcuts
QShortcut(shortcuts.SHORTCUT_OPEN_LOG, self)
```

### case: no-escape-dismiss

**Pattern:** Modal or popover without Escape key dismissal.

**Why forbidden:** Operator expects Escape to close overlay. Without it, they may feel trapped.

**Fix:** All overlays respond to Escape. See `rules/interaction-rules.md` RULE-INTER-002.

---

## Data Display

### case: color-only-status

**Pattern:** Green/red dot without icon or text indicating what's OK vs fault.

**Why forbidden:** Violates RULE-A11Y-002. Color-blind users cannot distinguish; all users benefit from redundant channels.

**Fix:** Color + icon + text triple:
```
[✓ icon] Норма  (green)
[⚠ icon] Внимание (amber)
[✗ icon] АВАРИЯ (red)
```

### case: status-color-for-small-text

**Pattern:** Body text in `STATUS_FAULT` red, `STATUS_INFO` blue, or `STATUS_STALE` gray.

**Why forbidden:** These colors fail WCAG AA body contrast (4.5:1 minimum) on `BACKGROUND #0d0e12`:
- `STATUS_FAULT #c44545`: 3.94:1
- `STATUS_INFO #4a7ba8`: 4.31:1
- `STATUS_STALE #5a5d68`: 2.94:1 (intentionally fails all levels)

Reading body-size text (≤14px) in these colors causes eye strain over long shifts.

Note: `STATUS_OK` (4.67:1), `STATUS_WARNING` (6.24:1), `STATUS_CAUTION` (5.67:1), and `COLD_HIGHLIGHT` (5.46:1) DO pass AA body and are acceptable for body text.

**Fix:** For inline status with a failing color, use `FOREGROUND` text color and prefix with a colored icon. See RULE-A11Y-003 and `tokens/colors.md` contrast matrix.

### case: pressure-linear-scale

**Pattern:** Pressure plot uses linear Y axis.

**Why forbidden:** Violates RULE-DATA-008. Pressure spans 10+ orders of magnitude; linear is uninterpretable.

**Fix:** `plot.setLogMode(x=False, y=True)`.

### case: raw-pressure-in-plot-data

**Pattern:** Plotting raw pressure values in linear space, expecting pyqtgraph log mode to handle display.

**Why forbidden:** Ambiguous — some code computes log10 manually, some relies on pyqtgraph's mode. Inconsistency.

**Fix:** Standard pattern: pass raw values, `setLogMode(y=True)`. Document clearly.

**Related rules:** None currently — advisory guidance.

---

## Charts

### case: chart-surface-elevation

**Pattern:** Chart wrapped in card with `SURFACE_ELEVATED` background.

**Why forbidden:** Charts are flat on viewport background (`PLOT_BG = BACKGROUND`). Elevating distinguishes them as modal-like.

**Fix:** Chart tile has CARD background for container, but chart itself uses PLOT_BG (same as BACKGROUND) so it blends into dashboard.

**Related rules:** RULE-SURF-010 (elevation via surface tokens only).

### case: status-colors-as-line-colors

**Pattern:** `STATUS_OK` or `STATUS_FAULT` used for data series line color in chart.

**Why forbidden:** Status colors carry semantic meaning. Using them for data series conflates "this series is OK" with "this series value is OK."

**Fix:** Use `PLOT_LINE_PALETTE` entries for data series.

**Related rules:** RULE-COLOR-002 (status color semantic lock).

### case: too-saturated-grid

**Pattern:** Grid lines at `PLOT_GRID_ALPHA > 0.5` dominate the plot.

**Why forbidden:** Grid is reference, not data. Should support reading, not demand attention.

**Fix:** Use default `PLOT_GRID_ALPHA = 0.35` or lower.

**Related rules:** None currently — advisory guidance.

---

## Layout

### case: decoupled-header-toolrail

**Pattern:** Changing `HEADER_HEIGHT` from 56 to 48 without updating `TOOL_RAIL_WIDTH`.

**Why forbidden:** Breaks corner square. HEADER_HEIGHT and TOOL_RAIL_WIDTH are coupled.

**Fix:** Change together.

**Related rules:** None currently — advisory guidance.

### case: horizontal-scroll

**Pattern:** Content wider than viewport, activating horizontal scrollbar.

**Why forbidden:** Strict anti-pattern. Content must fit or truncate, never scroll sideways.

**Fix:** Responsive tile sizing, truncation with tooltips, or reduce information density.

**Related rules:** None currently — advisory guidance.

### case: window-too-small-silently

**Pattern:** CryoDAQ renders broken layout at 1024×768 without warning.

**Why forbidden:** Operator doesn't know the UI is outside supported range. Reports "bug" which is "unsupported resolution."

**Fix:** Check viewport at startup; if < 1280×720, display warning dialog requesting larger window.

**Related rules:** None currently — advisory guidance.

---

## Format for adding new entries

When adding a new anti-pattern:

```markdown
### case: <short-kebab-name>

**Pattern:** <what the bad code looks like>

**Historical occurrence:** (optional) commit SHA, phase, or context

**Why forbidden:** Violates <RULE-ID>. <short explanation>

**Visual symptom:** (optional) what user sees

**Fix:** <correct alternative with code example if applicable>
```

One heading per case. Keep descriptions terse. Target: Claude/Codex can grep `case: modal-card` and find this file fast.

## Changelog

- 2026-04-17: Initial version. Seeded with Phase I.1 regressions and Phase 0 inventory findings.
