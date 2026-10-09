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
| **STATUS_WARNING** | `#c4862e` | **6.24:1** | ✓ | ✓ | ✗ | Warning — AA OK |
| **STATUS_CAUTION** | `#c47a30` | **5.67:1** | ✓ | ✓ | ✗ | Caution — AA OK |
| **STATUS_FAULT** | `#c44545` | **3.94:1** | ✗ | ✓ | ✗ | **Body text FAILS AA.** Large text only OR chrome accent |
| **STATUS_INFO** | `#4a7ba8` | **4.31:1** | ✗ (close) | ✓ | ✗ | **Body text fails AA.** Use as chrome / filled pill only |
| **STATUS_STALE** | `#5a5d68` | **2.94:1** | ✗ | ✗ | ✗ | **Intentionally unreachable.** Reserved for dimmed/stale |
| **TEXT_DISABLED** | calculated from FG × 0.5 | **2.79:1** | ✗ | ✗ | ✗ | **Intentionally unreachable.** Disabled state |
| **DESTRUCTIVE** | `#c44545` | **3.94:1** | ✗ | ✓ | ✗ | Same as STATUS_FAULT — destructive button uses filled context not text |
| **DESTRUCTIVE_PRESSED** | `#a53838` | **2.96:1** | ✗ | ✗ | ✗ | Pressed-state background, not a text color |

## Filled-pill contexts

When STATUS_FAULT / STATUS_WARNING etc. is used as a **background** with ON_DESTRUCTIVE text overlay (e.g., filled AlarmBadge pill, mode badge, destructive button), the contrast math is different:

| Background | Foreground | Ratio | AA body (4.5:1) | AA large (3:1) | AAA body (7:1) |
|---|---|---|---|---|---|
| STATUS_OK `#4a8a5e` | ON_DESTRUCTIVE `#e8eaf0` | **3.43:1** | ✗ | ✓ | ✗ |
| STATUS_WARNING `#c4862e` | ON_DESTRUCTIVE `#e8eaf0` | **2.57:1** | ✗ | ✗ | ✗ |
| STATUS_CAUTION `#c47a30` | ON_DESTRUCTIVE `#e8eaf0` | **2.83:1** | ✗ | ✗ | ✗ |
| STATUS_FAULT `#c44545` | ON_DESTRUCTIVE `#e8eaf0` | **4.07:1** | ✗ | ✓ | ✗ |
| STATUS_INFO `#4a7ba8` | ON_DESTRUCTIVE `#e8eaf0` | **3.72:1** | ✗ | ✓ | ✗ |
| ACCENT `#7c8cff` | ON_DESTRUCTIVE `#e8eaf0` | **2.48:1** | ✗ | ✗ | ✗ |

**Implication:** All filled-pill contexts **fail AA body** with ON_DESTRUCTIVE (`#e8eaf0`). STATUS_OK, STATUS_FAULT, and STATUS_INFO pass AA large (≥3:1), so they remain usable for ≥14px semibold or ≥18px regular labels. STATUS_WARNING, STATUS_CAUTION, and ACCENT fail even AA large — label text on these backgrounds cannot rely on text contrast alone.

This is a documented AA gap in filled pills. Options to remediate (pick per use case):
1. Accept — rely on multi-channel redundancy (color + shape + icon + adjacent label) per RULE-A11Y-002; filled pills are informational, not the sole state signal
2. Invert the fill — use ON_ACCENT `#0d0e12` (dark text) on light-filled pills; this flips the math and recovers AA body contrast against STATUS_OK/WARNING/CAUTION/ACCENT backgrounds
3. Restrict ON_DESTRUCTIVE text to STATUS_FAULT/STATUS_INFO/STATUS_OK pills with ≥14px semibold (AA large applies, 3:1 threshold met); avoid ON_DESTRUCTIVE on STATUS_WARNING, STATUS_CAUTION, ACCENT pills

CryoDAQ v1.0.x ships option 1 — filled pills ride on multi-channel redundancy (shape + color + icon + adjacent FOREGROUND label), so the pill text itself is supplementary rather than the sole state signal. See `patterns/state-visualization.md`.

## Ratios vs SECONDARY surfaces

When content sits on a secondary surface (CARD `#181a22`, SECONDARY `#22252f`, MUTED `#1d2028`) instead of BACKGROUND, contrast ratios shift slightly because luminance of the background is higher:

| Token | vs CARD `#181a22` | vs SECONDARY `#22252f` | vs MUTED `#1d2028` |
|---|---|---|---|
| FOREGROUND | **14.43:1** | **12.71:1** | **13.54:1** |
| MUTED_FOREGROUND | **5.36:1** | **4.72:1** | **5.03:1** |
| ACCENT | **5.83:1** | **5.13:1** | **5.47:1** |
| STATUS_OK | **4.21:1** (fails AA body!) | **3.70:1** (fails AA body!) | **3.95:1** (fails AA body!) |
| STATUS_WARNING | **5.62:1** | **4.95:1** | **5.27:1** |
| STATUS_FAULT | **3.54:1** (fails AA body) | **3.12:1** (fails AA body) | **3.32:1** (fails AA body) |

**Critical callout:** STATUS_OK and STATUS_FAULT fail AA body on every secondary surface. MUTED_FOREGROUND on SECONDARY (4.72:1) passes AA body but sits close to the threshold. This means:

- STATUS_OK as text color is unreliable on any surface other than BACKGROUND (where it reaches 4.67:1)
- STATUS_FAULT as body text is unsafe on every surface; it passes only AA large (≥3:1) on BACKGROUND/CARD/MUTED and fails AA body everywhere
- Status colors should carry their signal via border + icon + filled pill, NOT body text color (echoes RULE-A11Y-003)
- MUTED_FOREGROUND remains safe as secondary text on any surface, but the SECONDARY pairing has the least headroom — prefer FOREGROUND for critical labels on SECONDARY-surfaced tiles

## Non-text contrast (UI boundaries)

WCAG 1.4.11 requires ≥ 3:1 for UI component boundaries (borders, form outlines, chart axes).

| Pair | Ratio | Passes 3:1 |
|---|---|---|
| BORDER `#2d3038` vs BACKGROUND `#0d0e12` | **1.46:1** | ✗ |
| BORDER vs CARD `#181a22` | **1.32:1** | ✗ |
| BORDER vs SECONDARY `#22252f` | **1.16:1** | ✗ |
| ACCENT (focus ring) vs BACKGROUND | **6.48:1** | ✓ (well above) |

**Implication:** BORDER fails the 3:1 non-text contrast threshold against every surface it is used on — it is a visual-grouping stroke, not a functional UI boundary. Card shape and surface-luminance difference (CARD vs BACKGROUND ≈ 1.1:1 luminance step) provide grouping even though the BORDER stroke itself is sub-threshold. For functional boundaries that must be perceivable — focus rings, active tabs, fault outlines, chart axes — always use ACCENT (6.48:1 vs BACKGROUND) or a STATUS_* token with a proven higher ratio. This gap is reflected in the 1.4.11 commitment in `accessibility/wcag-baseline.md`.

## Guidance tables

### For body text (13-14px normal weight)

Safe (AA passes):
- FOREGROUND on any background
- MUTED_FOREGROUND on any background (SECONDARY is the tightest at 4.72:1)
- ACCENT on any background
- STATUS_OK on BACKGROUND only (4.67:1 — fails on CARD/SECONDARY/MUTED)
- STATUS_WARNING on any background (SECONDARY is the tightest at 4.95:1)
- STATUS_CAUTION on BACKGROUND (5.67:1); CARD/MUTED/SECONDARY not measured separately but tracking within ~0.5 of STATUS_WARNING
- COLD_HIGHLIGHT on BACKGROUND (5.46:1)

Not safe as body text (use chrome/icon/border instead):
- STATUS_FAULT (fails AA body on every surface; use filled pill, border, or large text)
- STATUS_INFO (fails AA body on BACKGROUND; use filled pill)
- STATUS_STALE (intentional)
- TEXT_DISABLED (intentional)

### For large text (≥ 18px normal OR ≥ 14px semibold)

All AA-passing body colors above are safe; additionally, all tokens with ratio ≥ 3:1 qualify:
- STATUS_FAULT can be used as large text on BACKGROUND (3.94:1), CARD (3.54:1), MUTED (3.32:1), SECONDARY (3.12:1) — all pass AA large
- STATUS_INFO can be used as large text on BACKGROUND (4.31:1)
- DESTRUCTIVE matches STATUS_FAULT (same hex)

### For UI components (borders, axes, focus outlines)

Safe (3:1 passes against BACKGROUND):
- ACCENT (6.48:1), FOREGROUND, STATUS_OK (4.67:1), STATUS_WARNING (6.24:1), STATUS_CAUTION (5.67:1), STATUS_FAULT (3.94:1), STATUS_INFO (4.31:1), COLD_HIGHLIGHT (5.46:1)

Not safe as UI component borders:
- BORDER on any surface (1.46:1 vs BACKGROUND, 1.32:1 vs CARD, 1.16:1 vs SECONDARY) — treat BORDER as visual grouping only, not a functional separator. Functional boundaries (focus, active, fault) must use ACCENT or STATUS_* tokens with proven ≥ 3:1 against the adjacent surface.

## Applied patterns

This matrix underlies specific pattern decisions:

- `patterns/state-visualization.md` — why fault chrome uses border + icon + value FOREGROUND (not colored text)
- `components/bottom-status-bar.md` — why label text stays MUTED_FOREGROUND with dot carrying the color
- `components/alarm-badge.md` — why filled pills ship with multi-channel signaling rather than stressing contrast

## Rationale for accepted gaps

Some AA gaps are deliberate design trade-offs:

- **STATUS_STALE 2.94:1** — stale content is intentionally de-emphasized; operators see it as "information present but not fresh". Raising contrast would visually compete with fresh data.
- **TEXT_DISABLED 2.79:1** — disabled means unreachable; operator's eye should skip it. AA compliance on disabled text is not required per WCAG (explicitly excluded).
- **STATUS_OK 4.67:1 body on BACKGROUND** — passes AA but close to threshold; fails on CARD/SECONDARY/MUTED. Acceptable because STATUS_OK is used mostly as chrome/indicator, not body text.
- **STATUS_FAULT / DESTRUCTIVE 3.94:1 body on BACKGROUND** — fails AA body on every surface but passes AA large (≥3:1) on BACKGROUND/CARD/MUTED. Used as chrome, filled-pill background, or large semibold labels — never as body text.
- **Filled-pill text 2.48–4.07:1** — ON_DESTRUCTIVE (`#e8eaf0`) on STATUS_* and ACCENT pill backgrounds fails AA body; three combinations (STATUS_WARNING 2.57:1, STATUS_CAUTION 2.83:1, ACCENT 2.48:1) fail even AA large. Accepted because filled pills ride on multi-channel redundancy (shape + color + icon + adjacent FOREGROUND label) per RULE-A11Y-002 — the pill text is supplementary, not the sole state signal.
- **BORDER 1.46:1 non-text on BACKGROUND (and lower on CARD/SECONDARY)** — fails 1.4.11 (≥3:1) on every surface. Accepted as a visual-grouping stroke only; functional boundaries (focus, active, fault) use ACCENT or STATUS_* which do meet 3:1. This gap downgrades 1.4.11 to `Partial` in `accessibility/wcag-baseline.md`.

None of these gaps is "we didn't notice"; each is a documented trade-off between accessibility and visual design density. Multi-channel redundancy (shape + color + icon + text) ensures operators never depend on a single sub-threshold pair to resolve state.

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
contrast("#2d3038", "#0d0e12")  # BORDER vs BACKGROUND → 1.46 (fails 1.4.11)
contrast("#e8eaf0", "#c4862e")  # ON_DESTRUCTIVE on STATUS_WARNING → 2.57 (filled pill)
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
- 2026-04-17: v1.0.1 — Recomputed all ratios from theme.py. Fixed stale ON_DESTRUCTIVE input. Corrected BORDER non-text contrast.
