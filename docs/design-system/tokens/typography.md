---
title: Typography Tokens
keywords: typography, font, size, weight, height, fira, sans, code, mono, cyrillic, tabular, ligatures
applies_to: all widgets with text
enforcement: strict
priority: critical
last_updated: 2026-04-17
status: canonical
---

# Typography Tokens

Typography in CryoDAQ uses **two font families**: Fira Sans (body) and Fira Code (display + mono). Both fully support Cyrillic + Latin + Greek scripts. This is verified against Google Fonts metadata.

Typography has **two tiers** of tokens:
- **Tier 1 — Primitives**: family name, size scale, weight scale (reusable building blocks)
- **Tier 2 — Semantic presets**: complete size + weight + line-height triples for specific text roles

Widgets MUST use Tier 2 presets where one matches the use case. Raw Tier 1 usage is allowed only for exceptional cases (e.g., inline computed font setup for a plot axis). See `rules/typography-rules.md` RULE-TYPO-001.

Total: **36 typography tokens** (4 family tokens + 7 size primitives + 4 weight primitives + 7 style presets × 3 attributes = 36).

## Font families

| Token | Value | Use | Cyrillic? | Weights available |
|---|---|---|---|---|
| `FONT_BODY` | `Fira Sans` | All body text, labels, paragraphs, form inputs | ✅ Full Cyrillic + Cyrillic-ext + Greek | 100-900 regular+italic |
| `FONT_UI` | alias → `FONT_BODY` | Button text, menu items, UI chrome | ✅ (same as FONT_BODY) | same |
| `FONT_DISPLAY` | `Fira Code` | Display-size numeric headers, TopWatchBar readouts | ✅ Full Cyrillic + Cyrillic-ext + Greek | 300-700 |
| `FONT_MONO` | `Fira Code` | Data cells, code snippets, log entries, timestamps | ✅ Full Cyrillic + Cyrillic-ext + Greek | 300-700 |

**Design decision: Fira Code for BOTH display and mono.** Unusual choice — typically display uses sans-serif. Rationale:
- Industrial aesthetic benefits from mechanical, precise glyph shapes
- Unified digit appearance across TopWatchBar headings and data tables
- Fira Code at 32px+ reads as "tech display," not as code
- Reduces font loading footprint (one family for both)

**Font file loading strategy:** Fira Sans and Fira Code are NOT installed on macOS dev machines by default. Qt falls back to Helvetica on Mac, which breaks aesthetic. MUST bundle `.ttf` files with application and register via `QFontDatabase.addApplicationFont()`.

See `rules/typography-rules.md` RULE-TYPO-002 for font loading enforcement.

### OpenType feature configuration

Both Fira Sans and Fira Code require explicit OpenType features:

| Feature | Fira Sans | Fira Code | Reason |
|---|---|---|---|
| `tnum` (tabular numbers) | **Must enable** for any numeric display | Enabled by default (monospace) | Prevents digit width jitter when value changes (`4.21 K` → `4.30 K`) |
| `liga` (programming ligatures) | Not applicable | **Must disable** in UI context (`->` should stay as 2 characters, not become arrow glyph) | Numeric readouts rarely contain ligature triggers, but `->` in experimental comments could render wrong |
| `ss02` (slashed zero) | Optional, recommended | Optional, recommended | Distinguishes 0 from O in data-dense contexts |

Code pattern for font setup in widgets:

```python
# DESIGN: RULE-TYPO-003
font = QFont(theme.FONT_BODY, theme.FONT_SIZE_BASE)
font.setWeight(theme.FONT_WEIGHT_REGULAR)
# Enable tabular numbers for numeric display
font.setFeature("tnum", 1)
# Disable programming ligatures (only applies to Fira Code; harmless on Fira Sans)
font.setFeature("liga", 0)
widget.setFont(font)
```

## Size scale (Tier 1 primitives)

| Token | Value (px) | Use |
|---|---|---|
| `FONT_SIZE_XS` | `11` | Captions, helper text, timestamp chips, axis labels |
| `FONT_SIZE_SM` | `12` | Secondary labels, form helper text, badge labels |
| `FONT_SIZE_BASE` | `14` | Body text default, most UI labels |
| `FONT_SIZE_LG` | `16` | Emphasized body text, section subheadings |
| `FONT_SIZE_XL` | `20` | Page subtitle, tile heading |
| `FONT_SIZE_2XL` | `28` | Page title, modal heading |
| `FONT_SIZE_3XL` | `40` | Hero numeric readout (rare, TopWatchBar max) |

**Scale ratio:** approximately 1.2× (minor third musical ratio) between adjacent steps. Deliberate — keeps type hierarchy tight without creating dramatic jumps. Consistent with industrial/data-dense aesthetic.

**Special-case off-scale sizes:**
- `FONT_DISPLAY_SIZE = 32` — used only in `FONT_DISPLAY_*` preset. Between 2XL (28) and 3XL (40). Optimized for TopWatchBar temperature readouts which need to be larger than page titles but smaller than hero.
- `FONT_MONO_VALUE_SIZE = 15` — used only in `FONT_MONO_VALUE_*` preset. Between SM (12) and BASE (14)... wait, between BASE (14) and LG (16). Optimized for numeric data cells in SensorCell widget — 4-digit temperature value (`4.21`) at 15px Fira Code Medium reads clearly without dominating the cell.

These off-scale sizes are **intentional and protected**. Do not "normalize" them to scale values. They solve specific legibility problems.

## Weight scale (Tier 1 primitives)

| Token | Value | Use |
|---|---|---|
| `FONT_WEIGHT_REGULAR` | `400` | Body text default |
| `FONT_WEIGHT_MEDIUM` | `500` | Labels, buttons, emphasized body |
| `FONT_WEIGHT_SEMIBOLD` | `600` | Headings, titles, primary actions |
| `FONT_WEIGHT_BOLD` | `700` | Display only (TopWatchBar values, critical numeric) |

**Minimum weight constraint:** No text below `FONT_WEIGHT_REGULAR` (400) in operator UI. Weights 100-300 render as "ghostly" on low-DPI lab monitors and fail readability. Lab PC is NOT retina; optimizing for 1440×900 LCD baseline.

## Line-height reference

Tier 2 presets bundle line-height. For Tier 1 exceptional use:

| Font size | Recommended line-height | Ratio |
|---|---|---|
| `FONT_SIZE_XS` (11) | 16 | 1.45 |
| `FONT_SIZE_SM` (12) | 16 | 1.33 |
| `FONT_SIZE_BASE` (14) | 20 | 1.43 |
| `FONT_SIZE_LG` (16) | 24 | 1.50 |
| `FONT_SIZE_XL` (20) | 24 | 1.20 (tight heading) |
| `FONT_SIZE_2XL` (28) | 32 | 1.14 (tight heading) |
| `FONT_SIZE_3XL` (40) | 44 | 1.10 (display) |

**Body text:** ratio 1.4-1.5 for multi-line readability.
**Headings:** ratio 1.1-1.25 for compact density.
**Display numerics:** ratio 1.1 (near-monoline).

## Semantic presets (Tier 2)

Seven complete text style presets. These are the **preferred API** for widget typography.

### `FONT_DISPLAY_*` — Display numeric

For TopWatchBar temperature/pressure headers, dashboard hero readouts.

| Attribute | Token | Value |
|---|---|---|
| Family | `FONT_DISPLAY` | `Fira Code` |
| Size | `FONT_DISPLAY_SIZE` | `32` |
| Weight | `FONT_DISPLAY_WEIGHT` | `600` (SEMIBOLD) |
| Line-height | `FONT_DISPLAY_HEIGHT` | `40` |

**Use for:** Temperature and pressure values in TopWatchBar («3.90 K», «1.23e-06 мбар»). Hero readout in experiment status.
**Don't use for:** Body text, section titles, buttons.

### `FONT_TITLE_*` — Page / modal title

For modal card headings, overlay titles, page titles.

| Attribute | Token | Value |
|---|---|---|
| Family | `FONT_BODY` (Fira Sans) | implicit |
| Size | `FONT_TITLE_SIZE` | `22` |
| Weight | `FONT_TITLE_WEIGHT` | `600` (SEMIBOLD) |
| Line-height | `FONT_TITLE_HEIGHT` | `28` |

**Use for:** Modal card title, overlay breadcrumb overlay-name text.
**Don't use for:** Dashboard headings (use HEADING), tile headings (use LABEL or BODY).

### `FONT_HEADING_*` — Section heading

For section dividers within overlays, grouped subheadings.

| Attribute | Token | Value |
|---|---|---|
| Family | `FONT_BODY` | implicit |
| Size | `FONT_HEADING_SIZE` | `18` |
| Weight | `FONT_HEADING_WEIGHT` | `600` |
| Line-height | `FONT_HEADING_HEIGHT` | `24` |

**Use for:** «КАРТОЧКА» / «ХРОНИКА» section headers inside ExperimentOverlay, archive panel section dividers.
**Don't use for:** Tile titles (use LABEL in uppercase).

### `FONT_LABEL_*` — Label / caption

For form labels, tile titles, status labels.

| Attribute | Token | Value |
|---|---|---|
| Family | `FONT_BODY` | implicit |
| Size | `FONT_LABEL_SIZE` | `12` (FONT_SIZE_SM) |
| Weight | `FONT_LABEL_WEIGHT` | `500` (MEDIUM) |
| Line-height | `FONT_LABEL_HEIGHT` | `16` |

**Use for:** Form field labels, sensor channel labels («Т1 Криостат верх»), status badges, tile titles (often uppercase — see RULE-TYPO-008).
**Don't use for:** Body prose, buttons (use BODY).

### `FONT_BODY_*` — Body text

For paragraph text, button labels, menu items, tooltip body.

| Attribute | Token | Value |
|---|---|---|
| Family | `FONT_BODY` | `Fira Sans` |
| Size | `FONT_BODY_SIZE` | `14` (FONT_SIZE_BASE) |
| Weight | `FONT_BODY_WEIGHT` | `400` (REGULAR) |
| Line-height | `FONT_BODY_HEIGHT` | `20` |

**Use for:** Alert banner body, tooltip text, operator log entries, button labels, menu items.

### `FONT_MONO_VALUE_*` — Numeric data cell

For sensor readout cells in SensorGrid, Keithley value displays, pressure cells.

| Attribute | Token | Value |
|---|---|---|
| Family | `FONT_MONO` | `Fira Code` |
| Size | `FONT_MONO_VALUE_SIZE` | `15` *(off-scale, intentional)* |
| Weight | `FONT_MONO_VALUE_WEIGHT` | `500` (MEDIUM) |
| Line-height | `FONT_MONO_VALUE_HEIGHT` | `20` |

**Use for:** SensorCell value (`4.21 K`), Keithley current/voltage/power values, conductivity result table cells.
**Don't use for:** Display headings (use DISPLAY), timestamps (use MONO_SMALL).

### `FONT_MONO_SMALL_*` — Small monospace

For timestamps, log timestamps, chart axis ticks.

| Attribute | Token | Value |
|---|---|---|
| Family | `FONT_MONO` | `Fira Code` |
| Size | `FONT_MONO_SMALL_SIZE` | `12` (FONT_SIZE_SM) |
| Weight | `FONT_MONO_SMALL_WEIGHT` | `500` |
| Line-height | `FONT_MONO_SMALL_HEIGHT` | `16` |

**Use for:** Timestamps in operator log (`23:08`), chart tick labels (`01:15`), elapsed time displays (`10ч 12мин`), log entry timestamps.

## Preset selection guide

Use this decision tree when picking a preset:

```
Is it a number/value displayed prominently (≥28px)?
  → FONT_DISPLAY_* (TopWatchBar readouts)

Is it a number in a data cell (multi-digit, 12-16px range)?
  → FONT_MONO_VALUE_*

Is it a timestamp or small monospace tech text?
  → FONT_MONO_SMALL_*

Is it a modal/overlay title?
  → FONT_TITLE_*

Is it a section heading within a card/overlay?
  → FONT_HEADING_*

Is it a label / caption / tile title?
  → FONT_LABEL_*

Is it body prose, button label, or general UI text?
  → FONT_BODY_*
```

## Cyrillic-specific considerations

Fira Sans and Fira Code both have complete Cyrillic + Cyrillic-Ext coverage.

**Russian UI rules:**

1. **Temperature channel identifiers use Cyrillic Т (U+0422)**, never Latin T (U+0054). Enforce in user-facing strings. See `rules/content-voice-rules.md` RULE-COPY-001.
2. **UPPERCASE Cyrillic labels** (e.g., «ЭКСПЕРИМЕНТ», «АВАР. ОТКЛ.») require `letter-spacing: 0.05em` because Cyrillic uppercase has narrower default tracking than Latin. Without this, letters cram together.
3. **Russian text is ~15% more vertically dense** than English at same size — Cyrillic glyphs often have tall diacriticals. Increase line-height by 2-3px for multi-line Russian content.

Code pattern:

```python
# DESIGN: RULE-TYPO-005 (Cyrillic uppercase spacing)
uppercase_label = QLabel("АВАР. ОТКЛ.")
font = QFont(theme.FONT_BODY, theme.FONT_LABEL_SIZE)
font.setWeight(theme.FONT_WEIGHT_SEMIBOLD)
font.setLetterSpacing(QFont.AbsoluteSpacing, 0.05)
uppercase_label.setFont(font)
```

## Fallback chain

Qt fallback when Fira Sans / Fira Code not available:

```python
# Recommended fallback chain in stylesheet
FONT_FAMILY_BODY_CSS = "'Fira Sans', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
FONT_FAMILY_MONO_CSS = "'Fira Code', 'Consolas', 'Courier New', monospace"
```

Fallback preserves Cyrillic on all platforms:
- **Windows**: Segoe UI (Cyrillic ✅)
- **macOS**: Helvetica Neue (Cyrillic ✅)
- **Linux**: DejaVu Sans or Liberation Sans (Cyrillic ✅)

Do NOT rely on fallback long-term — bundle the actual Fira fonts with application. Fallback is only for transient edge cases.

## Anti-patterns in typography

See `ANTI_PATTERNS.md` for full catalog. Key entries:

- **Mixed Latin T and Cyrillic Т in same view** — broken encoding, confuses operators
- **Weight below 400 in operator UI** — unreadable on lab displays
- **Size below 11px** — unreadable at arm's length on lab monitor
- **Programming ligatures enabled in data readouts** — `==` becomes one glyph
- **Non-tabular numbers in real-time data** — digits shift horizontally when value changes
- **Ignoring OpenType features** — even correct font family + size can look wrong without `tnum`, `liga`, `ss02` tuning

## Rule references

- `RULE-TYPO-001` — Prefer Tier 2 preset over Tier 1 primitives (`rules/typography-rules.md`)
- `RULE-TYPO-002` — Bundle Fira fonts, register via QFontDatabase (`rules/typography-rules.md`)
- `RULE-TYPO-003` — Enable `tnum` on all numeric text (`rules/typography-rules.md`)
- `RULE-TYPO-004` — Disable `liga` in UI context (`rules/typography-rules.md`)
- `RULE-TYPO-005` — Cyrillic uppercase letter-spacing (`rules/typography-rules.md`)
- `RULE-TYPO-006` — Minimum weight 400 in operator UI (`rules/typography-rules.md`)
- `RULE-TYPO-007` — Off-scale sizes (15, 32) are protected (`rules/typography-rules.md`)
- `RULE-COPY-001` — Cyrillic Т for temperature channels (`rules/content-voice-rules.md`)

## Related files

- `tokens/colors.md` — text color tokens pair with typography
- `rules/typography-rules.md` — enforcement rules
- `rules/content-voice-rules.md` — Russian text conventions
- `patterns/numeric-formatting.md` — how to format temperature/pressure/time
- `accessibility/wcag-baseline.md` — typography contrast requirements

## Changelog

- 2026-04-17: Initial version from theme.py inventory at commit 53e258c (36 typography tokens, 7 semantic presets)
