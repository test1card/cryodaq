---
title: Color Tokens
keywords: color, token, palette, surface, status, text, plot, stone, accent, hex
applies_to: all widgets
enforcement: strict
priority: critical
last_updated: 2026-04-17
status: canonical
---

# Color Tokens

Every color in CryoDAQ GUI MUST reference a token from this file. Raw hex literals in widget code are forbidden (see `rules/color-rules.md` RULE-COLOR-001). Source of constant values: `src/cryodaq/gui/theme.py`.

Total: **71 color tokens** organized into 9 namespaces (sum = 71):
- **Base** (6): BACKGROUND, FOREGROUND, CARD, MUTED, MUTED_FOREGROUND, BORDER
- **Surface hierarchy** (7): SURFACE_*
- **Status** (7): 6 STATUS_* + COLD_HIGHLIGHT — semantic locked
- **Text semantic** (12): 11 TEXT_* + CARD_FOREGROUND — widget-API wrappers
- **Interaction** (2): ACCENT, RING
- **Domain** (4): QUANTITY_* — physics quantity → color mapping
- **Plot** (9): PLOT_* — pyqtgraph-specific (see also `chart-tokens.md`)
- **Legacy** (13): STONE_* — qdarktheme compat aliases, soft-deprecated
- **Semantic aliases** (11): PRIMARY, SECONDARY, DESTRUCTIVE, SUCCESS_400, WARNING_400, DANGER_400, QDARKTHEME_ACCENT, ON_ACCENT, ON_PRIMARY, ON_SECONDARY, ON_DESTRUCTIVE

## Aesthetic direction

Palette is **desaturated industrial dark**. All colors pulled toward gray. No pure primaries, no neons, no saturated web colors. This is intentional — see `README.md` design philosophy.

Compare our palette to common alternatives:

| We use | NOT Tailwind default | NOT Material default |
|---|---|---|
| `STATUS_OK #4a8a5e` (forest green, 40% saturation) | ~~`green-500 #22C55E` (bright, 70% saturation)~~ | ~~`#4CAF50` (Material green)~~ |
| `STATUS_FAULT #c44545` (muted brick red) | ~~`red-500 #EF4444`~~ | ~~`#F44336` (Material red)~~ |
| `COLD_HIGHLIGHT #5b8db8` (dusty slate blue) | ~~`cyan-400 #22D3EE`~~ | ~~`#2196F3` (Material blue)~~ |
| `BACKGROUND #0d0e12` (near-black, blue-shifted) | ~~`slate-900 #0F172A`~~ | ~~`#121212` (Material dark)~~ |

Do not substitute Tailwind / Material shades without product-level decision.

## Base palette

| Token | Hex | RGB | Use | Anti-use |
|---|---|---|---|---|
| `BACKGROUND` | `#0d0e12` | `13, 14, 18` | Viewport base, main window fill, default plot background | Card surface (use `SURFACE_CARD`); text (use `FOREGROUND`) |
| `FOREGROUND` | `#e8eaf0` | `232, 234, 240` | Primary text, numeric readouts, plot tick labels | Decorative background, disabled state (use `TEXT_DISABLED`) |
| `CARD` | `#181a22` | `24, 26, 34` | Default card / tile surface; 1 shade above background | Viewport bg (use `BACKGROUND`); modal surface (use `SURFACE_ELEVATED`) |
| `MUTED` | `#1d2028` | `29, 32, 40` | Hover background on ghost buttons, disabled control fill | Default card surface (use `CARD`); border (use `BORDER`) |
| `MUTED_FOREGROUND` | `#8a8f9b` | `138, 143, 155` | Secondary text, captions, timestamps, raw value when no TEXT alias needed | Primary numeric readouts (use `FOREGROUND`); interactive text (use `FOREGROUND`) |
| `BORDER` | `#2d3038` | `45, 48, 56` | 1px card border, separator rules, axis lines in plots | Emphasized outline (use `ACCENT` or `STATUS_*`); text |

## Surface hierarchy

Four surface levels in a deliberate brightness ramp. Moving from deeper to higher creates perceived elevation without requiring shadows (shadows are ineffective on dark mode).

| Token | Resolves to | Hex | Elevation level | Use |
|---|---|---|---|---|
| `SURFACE_WINDOW` | `BACKGROUND` | `#0d0e12` | 0 (viewport) | Main window background |
| `SURFACE_BG` | `BACKGROUND` | `#0d0e12` | 0 (viewport) | Same as above, semantic alias |
| `SURFACE_SUNKEN` | `PRIMARY` | `#181a22` | 1 (recessed) | Inset regions, plot panels below dashboard |
| `SURFACE_PANEL` | `CARD` | `#181a22` | 2 (panel) | Dashboard tiles, sidebar, information panels |
| `SURFACE_CARD` | `CARD` | `#181a22` | 2 (panel) | Same as SURFACE_PANEL, semantic alias for card containers |
| `SURFACE_ELEVATED` | `SECONDARY` | `#22252f` | 3 (raised) | Modal cards, popovers, dropdown menus |
| `SURFACE_OVERLAY_RGBA` | literal | `rgba(13, 14, 18, 0.6)` | (overlay) | Modal backdrop dim |

**Critical observation:** `SURFACE_PANEL` and `SURFACE_CARD` and `PRIMARY` all resolve to the same `#181a22`. Also `SURFACE_SUNKEN` resolves to same `PRIMARY #181a22`. This means sunken and panel are visually identical. The distinction is **semantic for code clarity**, not visual.

For true depth hierarchy, only three distinct surface brightness levels exist:
1. `BACKGROUND #0d0e12` (deepest)
2. `CARD #181a22` (mid, used by PANEL/CARD/SUNKEN aliases)
3. `SECONDARY #22252f` (highest, used by ELEVATED alias)

Delta between levels is small (~6% relative luminance) — subtle by design. This is why `RULE-SURF-001` matters: nesting a PANEL inside an ELEVATED creates only a 1-step visual step, which operators may or may not read as hierarchy depending on display calibration.

See `rules/surface-rules.md` for surface composition constraints.

## Status palette

Semantic colors with locked meaning. Cross-use is a specification violation.

> **Hue-locked, lightness-unlocked for light substrates (ADR 001, 2026-04-19).**
> Dark packs ship the hex values in the table below verbatim. Light
> packs (`gost`, `xcode`, `braun`) ship a shifted-lightness variant of
> the same HUE to restore WCAG AA contrast (≥4.5:1) against a light
> `SURFACE_CARD`. Semantic identity («amber = WARNING, red = FAULT»)
> is preserved 1:1 across mode switches; only lightness adapts to
> substrate. See
> [`docs/design-system/adr/001-light-theme-status-unlock.md`](../adr/001-light-theme-status-unlock.md)
> for the rationale and the dark↔light hex correspondence table.

| Token | Hex | Meaning | Use | Anti-use |
|---|---|---|---|---|
| `STATUS_OK` | `#4a8a5e` | Normal operating, within spec, healthy | "Норма" badge, active phase border, safety READY, successful confirmation | Any non-healthy meaning, decorative |
| `STATUS_WARNING` | `#c4862e` | Attention, approaching limit | Amber "Внимание" label, rate-of-change warning, calibration stale | Fault state (use FAULT); generic notice (use INFO) |
| `STATUS_CAUTION` | `#c47a30` | Intermediate severity between warning and fault | Temperature climbing into danger zone, pressure drift accelerating | Default warning (use WARNING) |
| `STATUS_FAULT` | `#c44545` | Out of spec, interlock, fault_latched | Red alarm badge, "АВАР. ОТКЛ." text, safety fault | Any non-fault red, generic error display text |
| `STATUS_INFO` | `#4a7ba8` | Informational, neutral notice | Info badge, neutral notification | Status meaning (use OK for healthy); primary action (no primary action color) |
| `STATUS_STALE` | `#5a5d68` | No data, disconnected, unknown | Stale sensor badge, disconnected instrument indicator | Muted-but-active text (use `MUTED_FOREGROUND`) |
| `COLD_HIGHLIGHT` | `#5b8db8` | Cryogenic temperature emphasis | Cold channel highlighting, low-temp series in plots, Т5 Экран 77К badge | General informational use (use INFO) |

**Contrast matrix vs `BACKGROUND #0d0e12`** (measured, not estimated):

| Status token | Ratio | AA body (≥4.5) | AA large (≥3.0) | Use in body text? |
|---|---|---|---|---|
| `STATUS_OK #4a8a5e` | 4.67:1 | ✓ passes | ✓ | Yes — body text OK |
| `STATUS_WARNING #c4862e` | 6.24:1 | ✓ passes | ✓ | Yes — body text OK |
| `STATUS_CAUTION #c47a30` | 5.67:1 | ✓ passes | ✓ | Yes — body text OK |
| `STATUS_FAULT #c44545` | 3.94:1 | ✗ **fails** | ✓ | **No** — large text (18pt+) / icons / borders only |
| `STATUS_INFO #4a7ba8` | 4.31:1 | ✗ **fails** | ✓ | **No** — large text / icons / borders only |
| `STATUS_STALE #5a5d68` | 2.94:1 | ✗ fails | ✗ fails | **No** — deliberate low contrast (stale data must not demand attention) |
| `COLD_HIGHLIGHT #5b8db8` | 5.46:1 | ✓ passes | ✓ | Yes — body text OK |

**Critical rule:** `STATUS_FAULT`, `STATUS_INFO`, and `STATUS_STALE` CANNOT be used for body-size text on the default dark background. For inline fault/info status in body text, use `FOREGROUND` for text color with a `STATUS_FAULT` / `STATUS_INFO` colored icon prefix. See `rules/accessibility-rules.md` RULE-A11Y-003.

`STATUS_STALE` fails all WCAG levels intentionally — stale/disconnected state should be visibly muted, not demanding attention. Never use for actionable or readable content; only for the "stale" visual treatment itself.

## Text palette

Wrapper tokens with widget-API semantics. Prefer these over base palette in `setStyleSheet` text-role contexts.

| Token | Resolves to | Hex | Use |
|---|---|---|---|
| `TEXT_PRIMARY` | `FOREGROUND` | `#e8eaf0` | Primary text, numeric readouts, labels users must read |
| `TEXT_SECONDARY` | `MUTED_FOREGROUND` | `#8a8f9b` | Secondary text, captions, timestamps |
| `TEXT_MUTED` | `MUTED_FOREGROUND` | `#8a8f9b` | Same as SECONDARY, alias for muted semantic |
| `TEXT_DISABLED` | literal | `#555a66` | Disabled controls, unreachable items |
| `TEXT_INVERSE` | `ON_PRIMARY` | `#e8eaf0` | Reserved for light surfaces (we have none) |
| `TEXT_ACCENT` | `ACCENT` | `#7c8cff` | Link color, selected item text, focused label |
| `TEXT_OK` | `STATUS_OK` | `#4a8a5e` | Positive status inline (respect contrast constraint) |
| `TEXT_WARNING` | `STATUS_WARNING` | `#c4862e` | Warning status inline |
| `TEXT_CAUTION` | `STATUS_CAUTION` | `#c47a30` | Caution status inline |
| `TEXT_FAULT` | `STATUS_FAULT` | `#c44545` | Fault status inline (respect contrast constraint) |
| `TEXT_INFO` | `STATUS_INFO` | `#4a7ba8` | Info status inline |

`MUTED_FOREGROUND` passes AA body at 5.95:1 — safe for captions and secondary text.
`TEXT_DISABLED` at 2.79:1 fails all contrast levels — this is intentional (disabled controls should be visibly unavailable).

## Interaction palette

| Token | Hex (default_cool) | Semantic role | Use |
|---|---|---|---|
| `ACCENT` | `#7c8cff` | UI activation affordance | Primary buttons («Сохранить», «Экспорт CSV», «Применить»), active ToolRail slot indicator, active tab underline, progress-bar chunk for running tasks, focused-input border. Per-theme recalibrated Phase III.A — see `adr/002-accent-status-decoupling.md`. |
| `RING` | `#7c8cff` | Focus ring alias for ACCENT | Legacy — prefer `FOCUS_RING` (neutral) for new focus outlines to avoid accent bleed. |
| `SELECTION_BG` | per-theme | Selected-row background (neutral) | QTableWidget selected row highlight, selected list item background. Phase III.A neutral — decoupled from STATUS semantics so safety-green never signals "selected". |
| `FOCUS_RING` | per-theme | Focused-element outline (neutral) | `:focus` QSS border on inputs / buttons when accent bleed would collide with surrounding UI chrome. |
| `ON_ACCENT` | `#0d0e12` | Text color on ACCENT background | When ACCENT used as button/chip background. |
| `ON_PRIMARY` | `#e8eaf0` | Text on PRIMARY surfaces | Reserved for inversion scenarios. |
| `ON_SECONDARY` | `#e8eaf0` | Text on SECONDARY surfaces | Reserved for inversion scenarios. |
| `ON_DESTRUCTIVE` | `#e8eaf0` | Text on destructive button background | АВАР. ОТКЛ. button label. |

**STATUS_OK — DO NOT use for UI activation** (Phase III.A decoupling,
ADR 002):
- ✗ Primary button background → use `ACCENT`.
- ✗ Mode badge «Эксперимент» → use `SURFACE_ELEVATED` + `FOREGROUND` +
  `BORDER_SUBTLE` (low-emphasis identifier chip).
- ✗ Progress-bar chunk for user-triggered task → use `ACCENT`.
- ✗ Active tab / selected ToolRail slot → use `ACCENT`.
- ✗ Selected table row background → use `SELECTION_BG`.
- ✓ Safety-state labels (engine/connection/running/permitted) — keep.
- ✓ Channel-health indicators (ChannelStatus.OK, `_health_color`
  ≥80 threshold, stability-ok, steady-state-reached banners) — keep.
- ✓ CoverageBar dense segment, SeverityChip("OK") — keep.
- ✓ Current-phase pill border in phase stepper — keep (phase is a
  state indicator, not user activation).

See `rules/color-rules.md` RULE-COLOR-004 and
`adr/002-accent-status-decoupling.md`.

## Domain-semantic palette (physics quantities)

Maps physical measurements to status colors. Used in Keithley panel and related widgets.

| Token | Resolves to | Physical quantity | Rationale |
|---|---|---|---|
| `QUANTITY_CURRENT` | `STATUS_OK` = `#4a8a5e` | Current (I) | Current flow = operational health = OK green |
| `QUANTITY_POWER` | `#c44545` | Power (P) | Power dissipation = potential hazard = FAULT red |
| `QUANTITY_RESISTANCE` | `STATUS_WARNING` = `#c4862e` | Resistance (R) | Resistance varies during experiment = attention = WARNING amber |
| `QUANTITY_VOLTAGE` | `#5b8db8` | Voltage (V) | Voltage applied (cold side) = COLD_HIGHLIGHT blue |

This mapping is **a domain convention**, not arbitrary. Do not swap without consulting lab personnel.

## Plot palette (pyqtgraph-specific)

See `tokens/chart-tokens.md` for full list with usage context. Summary:

| Token | Resolves to | Use |
|---|---|---|
| `PLOT_BG` | `BACKGROUND` | Chart background |
| `PLOT_FG` | `MUTED_FOREGROUND` | Default foreground, legend text |
| `PLOT_GRID_COLOR` | `BORDER` | Grid lines |
| `PLOT_GRID_ALPHA` | `0.35` | Grid line opacity |
| `PLOT_LABEL_COLOR` | `MUTED_FOREGROUND` | Axis labels |
| `PLOT_TICK_COLOR` | `FOREGROUND` | Axis tick marks |
| `PLOT_REGION_WARN_ALPHA` | `0.12` | Warning region overlay alpha |
| `PLOT_REGION_FAULT_ALPHA` | `0.15` | Fault region overlay alpha |
| `PLOT_LINE_PALETTE` | array of 8 hex | Default multi-series line colors |

`PLOT_LINE_PALETTE`:
1. `#5b8db8` (cold blue, COLD_HIGHLIGHT)
2. `#9b7bb8` (dusty purple)
3. `#5fa090` (teal green)
4. `#a3b85b` (olive)
5. `#c4862e` (WARNING amber)
6. `#b88a5b` (ochre)
7. `#b87b9b` (dusty rose)
8. `#7c8cff` (ACCENT periwinkle)

All 8 colors share ~60% saturation ceiling — consistent with desaturated aesthetic. Palette supports up to 8 concurrent series; for 9+ series, wrap and differentiate via line dash style (see `rules/data-display-rules.md` RULE-DATA-007).

## Destructive action palette

| Token | Hex | Use |
|---|---|---|
| `DESTRUCTIVE` | `#c44545` | Destructive button background (e.g., АВАР. ОТКЛ.) — same hex as STATUS_FAULT |
| `ON_DESTRUCTIVE` | `#e8eaf0` | Text color on destructive button |
| `DANGER_400` | `STATUS_FAULT` = `#c44545` | Alias, used in safety-specific context |

`DESTRUCTIVE` has same visual appearance as `STATUS_FAULT` by design — destructive actions carry fault-level semantic weight. Button must include hold-to-confirm or modal confirmation pattern (see `patterns/destructive-actions.md`).

## Semantic aliases (component API layer)

| Token | Resolves to | Purpose |
|---|---|---|
| `PRIMARY` | `#181a22` (same as CARD) | Primary surface in component APIs that expect "primary/secondary/destructive" tri-state |
| `SECONDARY` | `#22252f` | Secondary surface — same as `SURFACE_ELEVATED` |
| `ACCENT` (also listed under Interaction) | `#7c8cff` | Interaction accent |
| `SUCCESS_400` | `STATUS_OK` | Success feedback, alias used in shadcn/ui-style code |
| `WARNING_400` | `STATUS_WARNING` | Warning alias |
| `DANGER_400` | `STATUS_FAULT` | Danger alias |
| `CARD_FOREGROUND` | `#e8eaf0` | Text on CARD surface |
| `QDARKTHEME_ACCENT` | `ACCENT` | Alias for qdarktheme integration |

## Legacy palette (qdarktheme compat)

`STONE_*` tokens are **legacy aliases** inherited from qdarktheme library. They remain as backward-compatibility. New code MUST use modern semantic names.

| Legacy | Resolves to | Preferred modern name |
|---|---|---|
| `STONE_0` | `BACKGROUND` | `BACKGROUND` |
| `STONE_50` | `BACKGROUND` | `BACKGROUND` |
| `STONE_100` | `CARD` | `CARD` or `SURFACE_CARD` |
| `STONE_150` | `CARD` | `CARD` or `SURFACE_CARD` |
| `STONE_200` | `SECONDARY` | `SECONDARY` or `SURFACE_ELEVATED` |
| `STONE_300` | `BORDER` | `BORDER` |
| `STONE_400` | literal `#3a3e48` | (none — qdarktheme-specific) |
| `STONE_500` | `TEXT_DISABLED` | `TEXT_DISABLED` |
| `STONE_600` | `MUTED_FOREGROUND` | `MUTED_FOREGROUND` or `TEXT_MUTED` |
| `STONE_700` | `MUTED_FOREGROUND` | same |
| `STONE_800` | literal `#c8ccd4` | (none — inverse-only) |
| `STONE_900` | `FOREGROUND` | `FOREGROUND` or `TEXT_PRIMARY` |
| `STONE_1000` | literal `#f7f8fb` | (none — inverse-only) |

**Governance:** `STONE_*` tokens are not deprecated (no warning emitted), but they are not documented as first-class tokens. New widget code should prefer modern semantic names. `STONE_400`, `STONE_800`, `STONE_1000` have no modern equivalent (inverse/light-theme shades) — do not use in new code.

See `governance/deprecation-policy.md` for formal policy.

## Forbidden colors

| Color family | Reason | Alternative |
|---|---|---|
| Purple/violet bright (`#8B5CF6`, `#A855F7`, `#6366F1`) | No semantic role; violates status grammar. Dashboard phase stepper violation — corrected in Phase II.9 | Use `ACCENT #7c8cff` ONLY for focus/selection, `STATUS_OK` for active phase |
| Pure red `#FF0000` | Over-saturated on dark, eye strain | `STATUS_FAULT #c44545` |
| Pure white `#FFFFFF` | Too harsh, fatigue over long shifts | `FOREGROUND #e8eaf0` |
| Pure black `#000000` | Not in palette | `BACKGROUND #0d0e12` |
| Saturated pink, magenta, fuchsia | Not in palette | No alternative — do not use |
| Tailwind/Material default shades | Wrong aesthetic — we are desaturated industrial, not SaaS | Use tokens from this file |
| Gradients (any) | Not used in CryoDAQ aesthetic | Solid color tokens only |

See `ANTI_PATTERNS.md` for historical regressions and their corrections.

## Rule references

- `RULE-COLOR-001` — No raw hex in widget code (`rules/color-rules.md`)
- `RULE-COLOR-002` — Status color semantic lock (`rules/color-rules.md`)
- `RULE-COLOR-003` — One primary accent per composition (`rules/color-rules.md`)
- `RULE-COLOR-004` — ACCENT reserved for focus/selection (`rules/color-rules.md`)
- `RULE-SURF-001` — Single visible surface per card (`rules/surface-rules.md`)
- `RULE-A11Y-003` — Status color text contrast constraint (`rules/accessibility-rules.md`)

## Related files

- `tokens/typography.md` — text color pairs with font tokens
- `tokens/chart-tokens.md` — pyqtgraph-specific plot tokens
- `rules/color-rules.md` — enforcement rules for color usage
- `accessibility/contrast-matrix.md` — measured WCAG ratios for all pairs
- `ANTI_PATTERNS.md` — historical color misuse

## Changelog

- 2026-04-17: Initial version from theme.py inventory at commit 53e258c (71 color tokens)
