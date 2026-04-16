---
title: Token Naming
keywords: tokens, naming, convention, primitive, semantic, component, layers, stone-legacy, prefix
applies_to: how design tokens are named and structured across the codebase
status: canonical
closes_forward_ref: RULE-GOV-001
references: tokens/*, rules/color-rules.md, rules/surface-rules.md
external_reference: UI UX Pro Max v2.5.0 design-system skill (three-layer architecture); W3C Design Tokens Community Group
last_updated: 2026-04-17
---

# Token Naming

Conventions for naming design tokens — the source-of-truth values that all visual decisions reference. **This document closes RULE-GOV-001.**

## Current state: flat token architecture

CryoDAQ ships v1.0.0 with a **flat token structure** — all tokens live as attributes of the `theme` module (`src/cryodaq/gui/theme.py`), named by category + role without intermediate layers:

```python
# theme.py — current structure
BACKGROUND = "#0d0e12"
FOREGROUND = "#e8eaf0"
STATUS_OK = "#4a8a5e"
STATUS_FAULT = "#c44545"
ACCENT = "#7c8cff"
SPACE_1 = 4
SPACE_2 = 8
# ... 126 tokens total
```

No primitive-vs-semantic distinction at the naming level. One layer. This is the reality; this document normalizes the naming conventions applied to it.

## Target state: three-layer architecture (future v2.0)

The UI UX Pro Max skill recommends a three-layer token system (primitive → semantic → component) for theme-switchability and component customization. CryoDAQ v2.0 (future, when light theme or accent-theming is added) will migrate to this structure:

```
┌─────────────────────────────────────────┐
│  Layer 3: Component Tokens              │  Per-component
│  BUTTON_BG, CARD_PADDING                │
├─────────────────────────────────────────┤
│  Layer 2: Semantic Tokens               │  Purpose aliases
│  COLOR_PRIMARY, SPACING_SECTION          │
├─────────────────────────────────────────┤
│  Layer 1: Primitive Tokens              │  Raw values
│  COLOR_BLUE_600, SPACE_4                │
└─────────────────────────────────────────┘
```

v1.0 is single-layer (primitive+semantic collapsed). Migration path documented in `governance/deprecation-policy.md`.

## Naming format

### Primitive colors (hex values)

Pattern: `<CATEGORY>` or `<CATEGORY>_<ROLE>`

```python
BACKGROUND       # shell root background
FOREGROUND       # primary text
CARD             # elevated surface for cards
SECONDARY        # secondary elevated surface
MUTED            # subdued surface
BORDER           # default border
ACCENT           # focus / selection
COLD_HIGHLIGHT   # cold-channel indicator
```

For status colors: `STATUS_<SEVERITY>`:

```python
STATUS_OK
STATUS_CAUTION
STATUS_WARNING
STATUS_FAULT
STATUS_INFO
STATUS_STALE
```

For semantic companion pairs: the "on-X" token for text that goes on a filled X:

```python
ON_DESTRUCTIVE   # text/icon color on DESTRUCTIVE/STATUS_FAULT filled background
DESTRUCTIVE      # same hex as STATUS_FAULT but distinct semantic (button role, not state)
DESTRUCTIVE_PRESSED  # pressed-state background for destructive button (future)
```

Per RULE-COLOR-007: DESTRUCTIVE and STATUS_FAULT share hex (`#c44545`) but are named separately to signal different intent. A refactor that changes STATUS_FAULT should not automatically change DESTRUCTIVE — they can diverge in future.

### Spacing scale (integers, px)

Pattern: `SPACE_<N>` where N is the step in the 4px scale:

```python
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32
SPACE_7 = 48
SPACE_8 = 64
SPACE_9 = 96
```

Scale is deliberate: not every multiple of 4 is tokenized. Adding a new size requires governance approval (see `governance/contribution.md`). Current 9 steps are sufficient for the current product.

### Radius scale

Pattern: `RADIUS_<SIZE>`:

```python
RADIUS_NONE = 0      # explicit zero for buttons inside toolbar contexts
RADIUS_SM = 4        # small (inputs, badges)
RADIUS_MD = 6        # medium (tiles)
RADIUS_LG = 8        # large (cards, panels)
RADIUS_FULL = 9999   # full (circular badges, pills)
```

### Typography

Font families: `FONT_<ROLE>`:

```python
FONT_BODY        # primary sans-serif for UI text (Fira Sans)
FONT_MONO        # tabular mono for numeric values (Fira Code)
FONT_DISPLAY     # large display sizes (same family as FONT_BODY, weight/size differ)
```

Font sizes: `FONT_<ROLE>_SIZE`:

```python
FONT_BODY_SIZE = 14
FONT_LABEL_SIZE = 12
FONT_TITLE_SIZE = 22
FONT_DISPLAY_SIZE = 32       # off-scale protected per RULE-TYPO-007
FONT_MONO_VALUE_SIZE = 15    # off-scale protected per RULE-TYPO-007
FONT_SIZE_XS = 11
```

Font weights: `FONT_WEIGHT_<NAME>`:

```python
FONT_WEIGHT_REGULAR = 400
FONT_WEIGHT_MEDIUM = 500
FONT_WEIGHT_SEMIBOLD = 600
FONT_WEIGHT_BOLD = 700
```

Per-role weight (composition):

```python
FONT_LABEL_WEIGHT = FONT_WEIGHT_MEDIUM
FONT_TITLE_WEIGHT = FONT_WEIGHT_SEMIBOLD
FONT_MONO_VALUE_WEIGHT = FONT_WEIGHT_MEDIUM
```

### Layout

Fixed layout constants: `<COMPONENT>_<DIMENSION>`:

```python
HEADER_HEIGHT = 56        # TopWatchBar
TOOL_RAIL_WIDTH = 56       # ToolRail (coupled with HEADER_HEIGHT per RULE-SPACE-006)
BOTTOM_BAR_HEIGHT = 28     # BottomStatusBar
ROW_HEIGHT = 36            # default button/input row height
GRID_GAP = 8               # BentoGrid inter-tile gap
```

### Icons and UI sizing

Pattern: `ICON_SIZE_<SIZE>`:

```python
ICON_SIZE_XS = 12
ICON_SIZE_SM = 16
ICON_SIZE_MD = 24
ICON_SIZE_LG = 32
```

## Category prefix registry

Current registered prefixes — every token belongs to one:

| Prefix | Domain | Count |
|---|---|---|
| (no prefix) | Root colors (BACKGROUND, FOREGROUND, ACCENT, CARD, BORDER, etc.) | 14 |
| `STATUS_` | Status semantic colors | 6 |
| `ON_` | Paired text-on-fill colors | 2 |
| `DESTRUCTIVE` | Button role (distinct from STATUS_FAULT) | 2 |
| `COLD_` | Cold channel indicator | 1 |
| `PLOT_` | Plot-specific colors + dimensions | ~8 |
| `SPACE_` | Spacing scale | 9 |
| `RADIUS_` | Radius scale | 5 |
| `FONT_` | Typography | 36 |
| `ICON_SIZE_` | Icon dimensions | 4 |
| `HEADER_`, `TOOL_RAIL_`, `BOTTOM_BAR_`, `ROW_`, `GRID_` | Layout constants | 5 |
| `OVERLAY_` | Overlay dimensions (OVERLAY_MAX_WIDTH) | ~2 |

New prefix proposals go through `governance/contribution.md` review.

## Legacy aliases (STONE_*)

During Phase 0 rename from the older "stone" palette to the current forest-green palette, the old names were kept as aliases for one version cycle:

```python
# Backward-compat aliases — DEPRECATED, will be removed in v2.0
STONE_50  = FOREGROUND       # alias for backward compat
STONE_900 = BACKGROUND        # alias
# ... etc
```

These are **deprecated** but not yet removed. See `governance/deprecation-policy.md` for removal schedule.

Rule: **no new code uses STONE_***. Existing call sites migrate to canonical names during the panel's next modification. Codex audit flags any new STONE_* reference.

## ALL_CAPS naming convention

Python module-level token constants use ALL_CAPS (standard Python convention for constants). Not camelCase, not snake_case with lowercase. Distinguishes tokens from regular variables in code review.

```python
# YES
BACKGROUND = "#0d0e12"
FONT_BODY_SIZE = 14

# NO
background = "#0d0e12"       # looks like mutable variable
fontBodySize = 14            # JavaScript-style; inconsistent
```

Exception: font family string literals are lowercase (they're actual font names):

```python
FONT_BODY = "Fira Sans"      # the VALUE is "Fira Sans", not "FIRA_SANS"
```

## Multi-word tokens

Use underscore `_` separator:

```python
# YES
COLD_HIGHLIGHT
FONT_MONO_VALUE_SIZE
OVERLAY_MAX_WIDTH

# NO
COLDHIGHLIGHT            # unreadable
COLD-HIGHLIGHT           # not valid Python identifier
coldHighlight            # camelCase conflicts with constants convention
```

## Reserved prefixes

Do NOT invent tokens with these prefixes without explicit governance:

- `THEME_*` — reserved for future theme-switching mechanism
- `DARK_*` / `LIGHT_*` — reserved for light-theme companion tokens (future v2.0)
- `DEFAULT_*` — ambiguous; use concrete role name
- `MAIN_*` / `PRIMARY_*` — ambiguous; use ACCENT or FOREGROUND as appropriate

## Token values: no arithmetic

Token VALUES are literals, not computed:

```python
# YES — literal
FONT_TITLE_SIZE = 22
SPACE_5 = 24

# NO — computation obscures the number
FONT_TITLE_SIZE = FONT_BODY_SIZE * 1.5 + 1
SPACE_5 = SPACE_4 * 1.5
```

Rationale: readers should see the token's actual value. Computed values hide the specific number chosen.

Exception: **font weight references** can reference the weight constants to enforce consistency:

```python
# OK — composition via named weight
FONT_LABEL_WEIGHT = FONT_WEIGHT_MEDIUM  # resolves to 500
```

## Alignment with W3C DTCG format

If CryoDAQ design tokens are ever exported to the W3C Design Tokens Community Group JSON format (for cross-tool interoperability), the mapping is:

```json
{
  "color": {
    "background": { "$value": "#0d0e12", "$type": "color" },
    "foreground": { "$value": "#e8eaf0", "$type": "color" },
    "status": {
      "ok": { "$value": "#4a8a5e", "$type": "color" },
      "fault": { "$value": "#c44545", "$type": "color" }
    }
  },
  "space": {
    "1": { "$value": "4px", "$type": "dimension" },
    "2": { "$value": "8px", "$type": "dimension" }
  }
}
```

Not currently exported; reserved for future integration with design tools (Figma tokens, etc.).

## Code reference pattern

Always reference tokens through the `theme` module:

```python
# YES
from cryodaq.gui import theme
widget.setStyleSheet(f"background: {theme.CARD};")

# NO — hardcoded
widget.setStyleSheet(f"background: #181a22;")
```

Per RULE-COLOR-010. Violation caught by `governance/testing-strategy.md` lint.

## Adding a new token

Minimum requirements for adding a new token (reviewed per `governance/contribution.md`):

1. **Justification:** why existing tokens don't suffice
2. **Name:** follows conventions above
3. **Value:** literal; if color, contrast-measured vs all relevant backgrounds
4. **Location:** added to `theme.py` in appropriate category section
5. **Documentation:** added to relevant `tokens/*.md` file (colors.md, spacing.md, etc.)
6. **Tests:** token-lint doesn't fail on its introduction
7. **Cross-check:** no existing token does the job (often a Codex-audit question)

## Closes: RULE-GOV-001

**RULE-GOV-001 — Token naming convention.** This document is the canonical source for token naming. Every new token follows the patterns here; every existing token is audited against them. Deviations require explicit governance exception per `governance/contribution.md`.

## Rules applied

- **RULE-COLOR-010** — tokens referenced through theme module, not hardcoded
- **RULE-GOV-001** — this document closes the ref
- UXPM `color-semantic` — semantic tokens not raw hex in components

## Common mistakes

1. **New token with new invented prefix.** `EXPERIMENT_BG = "#...".` Ad-hoc prefix without registration. Use registered prefix or propose new one.

2. **Hardcoded hex in call sites.** Bypasses token system. Contrast-matrix, deprecation, refactors all break. Always route through theme module.

3. **Computed token value.** `FONT_TITLE_SIZE = BASE * 1.5`. Hides value; makes contrast reviews harder; breaks W3C export.

4. **Reviving STONE_* for new code.** Legacy. Always use canonical names.

5. **Adding shade variant without namespace.** Like `BLUE_500, BLUE_600` alongside ACCENT. Choose one canonical; if a scale is needed, register a new prefix (e.g., `BLUE_*` primitive layer, governance-approved).

6. **Mixing naming conventions.** `STATUS_OK` and `statusWarning` in same module. Enforce ALL_CAPS consistently.

7. **Redundant prefixes.** `COLOR_STATUS_OK` when `STATUS_OK` is clearer. Don't stutter prefixes.

8. **Infix vs suffix confusion.** `LARGE_FONT_SIZE` vs `FONT_SIZE_LARGE`. Standardize: `<CATEGORY>_<ROLE>_<VARIANT>`. So `FONT_SIZE_LARGE` is correct, infix "SIZE" middle.

## Related governance

- `governance/deprecation-policy.md` — STONE_* legacy lifecycle
- `governance/contribution.md` — adding new tokens
- `governance/versioning.md` — token API breaking changes
- `governance/testing-strategy.md` — token lint (no raw hex)

## Changelog

- 2026-04-17: Initial version. Closes RULE-GOV-001. Documents current flat-architecture state + target three-layer architecture for future v2.0. Prefix registry. STONE_* legacy alias policy. W3C DTCG alignment (future).
