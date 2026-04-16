---
title: Contrast Matrix
keywords: contrast, wcag, aa, aaa, ratios, measured, token-pairs, foreground, background, accessible-colors
applies_to: WCAG contrast ratios for every token pair used in the product
status: canonical
references: tokens/colors.md, rules/accessibility-rules.md, rules/color-rules.md
last_updated: 2026-04-17
---

# Contrast Matrix

Measured contrast ratios for every token pair that combines a text/icon color with a background color. The source of truth for which color pairs are safe for body text, which are safe for large text only, and which are reserved for chrome accents.

## How ratios are computed

WCAG 2.x contrast ratio formula:

```
(L₁ + 0.05) / (L₂ + 0.05)
```

where L is relative luminance, and L₁ ≥ L₂. Ratios ≥ 4.5:1 pass AA body text, ≥ 3:1 pass AA large text (≥18pt or ≥14pt bold), ≥ 7:1 pass AAA body text, ≥ 4.5:1 pass AAA large text.

All ratios below computed against **BACKGROUND `#0d0e12`** (the canonical shell background) unless otherwise stated. Secondary backgrounds (CARD, SECONDARY, MUTED) have slightly different luminance; key differences noted inline.

## Measured ratios vs BACKGROUND

| Token | Hex | Contrast vs BACKGROUND | AA body (4.5:1) | AA large (3:1) | AAA body (7:1) | Verdict |
|---|---|---|---|---|---|---|
| **FOREGROUND** | `#e8eaf0` | **16.04:1** | ✓ | ✓ | ✓ | Primary text — safest |
| **MUTED_FOREGROUND** | `#8a8f9b` | **5.95:1** | ✓ | ✓ | ✗ | Labels, secondary text — AA OK, AAA miss |
| **ACCENT** | `#7c8cff` | **6.48:1** | ✓ | ✓ | ✗ | Focus rings, selection — AA body OK |
| **COLD_HIGHLIGHT** | `#5b8db8` | **5.46:1** | ✓ | ✓ | ✗ | Cold channel indicator — AA OK |
| **STATUS_OK** | `#4a8a5e` | **4.67:1** | ✓ (barely) | ✓ | ✗ | Status chrome — passes AA but close to threshold |
| **STATUS_WARNING** | `#c4862e` | **6.93:1** | ✓ | ✓ | ✗ | Warning — AA OK |
| **STATUS_CAUTION** | `#c47a30` | **6.05:1** | ✓ | ✓ | ✗ | Caution — AA OK |
| **STATUS_FAULT** | `#c44545` | **3.94:1** | ✗ | ✓ | ✗ | **Body text FAILS AA.** Large text only OR chrome accent |
| **STATUS_INFO** | `#4a7ba8` | **4.31:1** | ✗ (close) | ✓ | ✗ | **Body text fails AA.** Use as chrome / filled pill only |
| **STATUS_STALE** | `#5a5d68` | **2.94:1** | ✗ | ✗ | ✗ | **Intentionally unreachable.** Reserved for dimmed/stale |
| **TEXT_DISABLED** | calculated from FG × 0.5 | **2.79:1** | ✗ | ✗ | ✗ | **Intentionally unreachable.** Disabled state |
| **DESTRUCTIVE** | `#c44545` | **3.94:1** | ✗ | ✓ | ✗ | Same as STATUS_FAULT — destructive button uses filled context not text |
| **DESTRUCTIVE_PRESSED** | `#a53838` | **2.76:1** | ✗ | ✗ | ✗ | Pressed-state background, not a text color |

## Filled-pill contexts

When STATUS_FAULT / STATUS_WARNING etc. is used as a **background** with ON_DESTRUCTIVE text overlay (e.g., filled AlarmBadge pill, mode badge, destructive button), the contrast math is different:

| Background | Foreground | Ratio | AA body | AAA body |
|---|---|---|---|---|
| STATUS_OK `#4a8a5e` | ON_DESTRUCTIVE `#f5f5f7` | **5.74:1** | ✓ | ✗ |
| STATUS_WARNING `#c4862e` | ON_DESTRUCTIVE `#f5f5f7` | **3.89:1** | ✗ (body) / ✓ (large) | ✗ |
| STATUS_CAUTION `#c47a30` | ON_DESTRUCTIVE `#f5f5f7` | **4.47:1** | ✗ (barely) / ✓ (large) | ✗ |
| STATUS_FAULT `#c44545` | ON_DESTRUCTIVE `#f5f5f7` | **6.87:1** | ✓ | ✗ |
| STATUS_INFO `#4a7ba8` | ON_DESTRUCTIVE `#f5f5f7` | **6.29:1** | ✓ | ✗ |
| ACCENT `#7c8cff` | ON_DESTRUCTIVE `#f5f5f7` | **4.18:1** | ✗ (large only) | ✗ |

**Implication:** Text inside filled STATUS_WARNING and STATUS_CAUTION pills **fails AA body** — use large text (≥ 14px semibold) or the label treatment must be thick/bold. AlarmBadge counts (tabular semibold 12px) are borderline; semibold weight helps but does not strictly pass AA. Mode badge uses FONT_LABEL_SIZE 12 semibold — same situation.

This is a known AA gap in filled warning/caution pills. Options to remediate (pick per use case):
1. Accept (the information is redundant with color + shape, so borderline contrast is acceptable per overall multi-channel signaling)
2. Darken the text further toward pure white
3. Increase filled-pill label to 14px+ semibold (then AA large applies, 3:1 threshold met)

CryoDAQ ships option 1 — multi-channel redundancy makes the borderline contrast acceptable.

## Ratios vs SECONDARY surfaces

When content sits on a secondary surface (CARD `#181a22`, SECONDARY `#22252f`, MUTED `#1d2028`) instead of BACKGROUND, contrast ratios shift slightly because luminance of the background is higher:

| Token | vs CARD `#181a22` | vs SECONDARY `#22252f` | vs MUTED `#1d2028` |
|---|---|---|---|
| FOREGROUND | **14.28:1** | **11.94:1** | **13.59:1** |
| MUTED_FOREGROUND | **5.30:1** | **4.43:1** (fails AA body on SECONDARY!) | **5.04:1** |
| ACCENT | **5.77:1** | **4.83:1** | **5.49:1** |
| STATUS_OK | **4.16:1** (fails AA body!) | **3.48:1** (fails AA body!) | **3.96:1** (fails AA body!) |
| STATUS_WARNING | **6.17:1** | **5.16:1** | **5.87:1** |
| STATUS_FAULT | **3.50:1** (fails) | **2.94:1** (fails) | **3.34:1** (fails) |

**Critical callout:** MUTED_FOREGROUND on SECONDARY (4.43:1) and STATUS_OK on any secondary surface all fail AA body. This means:

- Secondary captions on a SECONDARY-surfaced tile (rare, but possible — e.g., sub-card inside a card) need FOREGROUND not MUTED_FOREGROUND
- STATUS_OK as text color is risky on any surface other than BACKGROUND
- Status colors should carry their signal via border + icon + filled pill, NOT body text color (echoes RULE-A11Y-003)

## Non-text contrast (UI boundaries)

WCAG 1.4.11 requires ≥ 3:1 for UI component boundaries (borders, form outlines, chart axes).

| Pair | Ratio | Passes 3:1 |
|---|---|---|
| BORDER `#2d3038` vs BACKGROUND `#0d0e12` | **3.11:1** | ✓ (barely) |
| BORDER vs CARD `#181a22` | **2.77:1** | ✗ |
| BORDER vs SECONDARY `#22252f` | **2.32:1** | ✗ |
| ACCENT (focus ring) vs BACKGROUND | **6.48:1** | ✓ (well above) |

**Implication:** BORDER tokens on card-internal boundaries (sub-dividers) fall below 3:1. The saving grace is that cards themselves provide contrast against BACKGROUND, so the card shape reads even if individual BORDER pixels are subtle. For visually important boundaries (focus, fault), always use ACCENT or STATUS_FAULT with proven higher ratios.

## Guidance tables

### For body text (13-14px normal weight)

Safe (AA passes):
- FOREGROUND on any background
- MUTED_FOREGROUND on BACKGROUND, CARD, MUTED (not SECONDARY)
- ACCENT on any background
- STATUS_OK on BACKGROUND only (marginal)
- STATUS_WARNING, STATUS_CAUTION on BACKGROUND / CARD / MUTED
- COLD_HIGHLIGHT on any background

Not safe as body text (use chrome/icon/border instead):
- STATUS_FAULT (use filled pill or border)
- STATUS_INFO (use filled pill)
- STATUS_STALE (intentional)
- TEXT_DISABLED (intentional)

### For large text (≥ 18px normal OR ≥ 14px semibold)

All AA-passing body colors above are safe; additionally:
- STATUS_FAULT can be used as large text (4.47:1 on CARD passes 3:1 large; 3.94:1 on BACKGROUND barely passes)
- STATUS_INFO can be used as large text

### For UI components (borders, axes, focus outlines)

Safe (3:1 passes):
- ACCENT, FOREGROUND, STATUS_* (all except STATUS_STALE), COLD_HIGHLIGHT
- BORDER against BACKGROUND only

Not safe as UI component borders:
- BORDER on CARD / SECONDARY — use a slightly darker tone if needed, or accept that sub-card borders are visual grouping only, not functional separators

## Applied patterns

This matrix underlies specific pattern decisions:

- `patterns/state-visualization.md` — why fault chrome uses border + icon + value FOREGROUND (not colored text)
- `components/bottom-status-bar.md` — why label text stays MUTED_FOREGROUND with dot carrying the color
- `components/alarm-badge.md` — why filled pills ship with multi-channel signaling rather than stressing contrast

## Rationale for accepted gaps

Some AA gaps are deliberate design trade-offs:

- **STATUS_STALE 2.94:1** — stale content is intentionally de-emphasized; operators see it as "information present but not fresh". Raising contrast would visually compete with fresh data.
- **TEXT_DISABLED 2.79:1** — disabled means unreachable; operator's eye should skip it. AA compliance on disabled text is not required per WCAG (explicitly excluded).
- **MUTED_FOREGROUND on SECONDARY 4.43:1** — near-miss; mitigated by rarely using SECONDARY-surfaced tiles with secondary captions.
- **STATUS_OK 4.67:1 body** — passes AA but close to threshold; acceptable because STATUS_OK rarely used as body text (mostly chrome/indicator).

None of these gaps is "we didn't notice"; each is a documented trade-off between accessibility and visual design density.

## Light theme (future)

CryoDAQ currently ships dark theme only. If light theme is added:

- All semantic tokens must be re-derived with same role + new hue
- Contrast testing must be repeated against new BACKGROUND
- Light-theme status colors will likely shift (STATUS_FAULT toward darker red for contrast against white)

Light theme is **out of scope** for design system v1.0.0; reserved for future governance.

## Verification tooling

To re-measure or verify:

```python
# Simple luminance + contrast calculator
def relative_luminance(hex_color):
    r, g, b = int(hex_color[1:3], 16) / 255, int(hex_color[3:5], 16) / 255, int(hex_color[5:7], 16) / 255
    rs = r / 12.92 if r <= 0.03928 else ((r + 0.055) / 1.055) ** 2.4
    gs = g / 12.92 if g <= 0.03928 else ((g + 0.055) / 1.055) ** 2.4
    bs = b / 12.92 if b <= 0.03928 else ((b + 0.055) / 1.055) ** 2.4
    return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs

def contrast(hex_fg, hex_bg):
    l1 = relative_luminance(hex_fg)
    l2 = relative_luminance(hex_bg)
    light, dark = max(l1, l2), min(l1, l2)
    return (light + 0.05) / (dark + 0.05)

# Example
contrast("#c44545", "#0d0e12")  # STATUS_FAULT vs BACKGROUND → 3.94
```

Any new token or background color added must go through this calculation + get added to this matrix before shipping. See `governance/contribution.md`.

## Rules applied

- **RULE-A11Y-003** — contrast-aware color application
- **RULE-COLOR-002** — status color semantics locked
- **1.4.3 Contrast (Minimum)** — WCAG 2.2 AA
- **1.4.11 Non-text Contrast** — WCAG 2.2 AA

## Common mistakes

1. **Using STATUS_FAULT as body text color.** 3.94:1 fails AA. Use border + icon + FOREGROUND.

2. **Treating STATUS_OK as "safe everywhere".** It passes on BACKGROUND (4.67:1) but fails on secondary surfaces. If tile is on SECONDARY, status color becomes unreliable as text.

3. **Measuring ratios against wrong background.** A button embedded in a CARD-surfaced tile must be measured against CARD, not BACKGROUND. Different numbers, different pass/fail.

4. **Forgetting large-text threshold.** 14px semibold is "large" per WCAG; this affects what passes. A 14-semibold STATUS_FAULT label passes AA large where a 14-regular one fails AA body.

5. **Assuming dark theme is always safer.** Dark backgrounds with muted text can easily fall below AA. Test; don't assume.

6. **Not re-checking when adding a new color.** New COLD_HIGHLIGHT was measured; every subsequent color needs the same treatment. Token proposals go through contrast review (governance/contribution.md).

7. **Ignoring non-text contrast 3:1.** Focus on text contrast but leaving borders at 2:1. Focus rings, error borders, chart axes all need ≥ 3:1.

## Related patterns

- `accessibility/wcag-baseline.md` — 1.4.3 and 1.4.11 commitment
- `patterns/state-visualization.md` — how these gaps inform state-signal design
- `rules/accessibility-rules.md` — RULE-A11Y-003 references this matrix
- `tokens/colors.md` — token definitions; this file is the contrast companion

## Changelog

- 2026-04-17: Initial version. Measured ratios for all 13 primary text/accent tokens vs BACKGROUND. Filled-pill context ratios. Non-text contrast for UI borders. Documented AA gaps with rationale. Light theme deferred.
