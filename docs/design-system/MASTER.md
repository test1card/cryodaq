# CryoDAQ Design System Master Reference

> Design system colors, typography pairings, and UX guidelines adapted
> from UI UX Pro Max skill v2.5.0 by Next Level Builder, MIT licensed.
> https://github.com/nextlevelbuilder/ui-ux-pro-max-skill

**Status:** Active design system, applied in Block B.4.5
**Style:** Hybrid Real-Time Monitoring + Data-Dense Dashboard
**Theme:** Dark only

## Quick reference

For full rationale and findings see `FINDINGS.md` in this directory.

### Colors

| Token | Value | Role |
|-------|-------|------|
| `BACKGROUND` | `#0F172A` | Window background (deep slate) |
| `PRIMARY` | `#1E293B` | Primary surface |
| `SECONDARY` | `#334155` | Elevated surface |
| `CARD` | `#1B2336` | Card/panel background |
| `FOREGROUND` | `#F8FAFC` | Primary text |
| `MUTED_FOREGROUND` | `#94A3B8` | Secondary/muted text |
| `BORDER` | `#475569` | Borders and separators |
| `ACCENT` | `#22C55E` | Accent (green, matches STATUS_OK) |
| `DESTRUCTIVE` | `#EF4444` | Destructive actions |
| `STATUS_OK` | `#22C55E` | Normal operation |
| `STATUS_WARNING` | `#F59E0B` | Warning, attention required |
| `STATUS_CAUTION` | `#FB923C` | Attention without urgency |
| `STATUS_FAULT` | `#EF4444` | Serious fault |
| `STATUS_INFO` | `#38BDF8` | Informational / cold highlight |
| `STATUS_STALE` | `#64748B` | Stale data |
| `COLD_HIGHLIGHT` | `#38BDF8` | Cold temperature emphasis |

### Typography

- **Display / numeric / labels:** Fira Code (monospaced, programming
  ligatures, designed for data display)
- **Body / prose:** Fira Sans (humanist sans, Fira Code companion)
- **Type scale:** 11 / 12 / 14 / 16 / 20 / 28 / 40 px
- **Weights:** 400 (Regular) / 500 (Medium) / 600 (SemiBold) / 700 (Bold)

### Spacing rhythm

8px grid: 0 / 4 / 8 / 12 / 16 / 24 / 32 px

### Radius

| Token | Value | Use |
|-------|-------|-----|
| `RADIUS_SM` | 4px | Default (inputs, buttons, status pills) |
| `RADIUS_MD` | 6px | Cards, panels |
| `RADIUS_LG` | 8px | Modals, large containers |

### Motion

150-300ms transitions ease-out. No pulse, no glow, no parallax.

## Mandatory rules for new widgets

When implementing a new dashboard widget:

1. Use only tokens from `theme.py`. No hardcoded hex colors, no hardcoded
   pixel sizes outside what `theme.py` provides.
2. If a new token is needed, add it to `theme.py` AND update this MASTER.md
   AND update FINDINGS.md.
3. Russian operator-facing text only.
4. Cyrillic Т (U+0422) in temperature channel filtering.
5. Cleanup hooks via closeEvent AND destroyed signal for any subscription.
6. Status meaning conveyed by both color AND text label, never color alone.
7. Long labels: ElideRight + tooltip with full text.
8. No emojis as icons. Use SVG from `gui/resources/icons/`.

## Backwards compatibility

Old token names from Phase UI-1 v1 are aliased in `theme.py` to new
values. Migration path:

1. New code uses new token names (`BACKGROUND`, `CARD`, `FOREGROUND`)
2. Existing code continues to use old names (`SURFACE_CARD`, `TEXT_PRIMARY`)
3. As widgets are touched, migrate to new names
4. In B.7 cleanup, remove all aliases
