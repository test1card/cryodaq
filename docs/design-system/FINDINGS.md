# Design System Findings

> Extraction analysis from UI UX Pro Max skill v2.5.0 databases.

## Source analysis

### Style selection

Analyzed 67 UI styles in the skill database. Two styles matched
CryoDAQ's ambient information radiator requirements:

1. **Real-Time Monitoring Dashboard** — live data philosophy, status
   tiers, always-on mindset. Lacks concrete spacing/radius tokens.
2. **Data-Dense Dashboard** — compact density, 8px grid, sharp radius,
   monospace data. Lacks real-time status awareness.

**Decision:** Hybrid of both. Live data philosophy from Real-Time
Monitoring, spatial discipline and concrete tokens from Data-Dense
Dashboard.

### Palette selection

Analyzed 161 color palettes. Only one true dark monitoring palette:
**Smart Home/IoT Dashboard** — deep slate base, green accent,
16 semantic tokens including muted foreground for secondary text.

Extended with 5 CryoDAQ-specific status tiers (OK/Warning/Caution/
Fault/Stale) and 1 cold-temperature highlight.

### Typography selection

Analyzed 73 typography pairings. **Dashboard Data** pairing selected:
Fira Code (display/numeric) + Fira Sans (body/prose).

Rationale: Fira Code provides consistent digit widths critical for
sensor value display. Fira Sans is its humanist companion, sharing
x-height and weight design. Both are SIL OFL licensed.

### Anti-patterns rejected

From the skill's 99 UX guidelines, explicitly rejected for CryoDAQ:

- Pulse/glow/blink animations (distracting for ambient monitoring)
- Parallax effects
- Hero readout patterns (all channels are equal)
- Skeleton loading screens (not applicable to real-time data)
- Tooltip-only status indication (accessibility requirement: text labels)

### Anti-patterns adopted

- Status conveyed by color AND text label, never color alone
- 30-second stale threshold for data freshness
- ElideRight + tooltip for long labels
- 8px grid for spacing consistency
- Sharp radius (4px) for technical aesthetic

## Tone-down revision (B.4.5.1)

After initial B.4.5 adoption commit `550119e`, visual review with 14
sensor cells rendering simultaneously revealed the literal Smart
Home/IoT Dashboard palette was too saturated for laboratory monitoring
context. The Tailwind-flavored status colors (`#22C55E` green,
`#EF4444` red, `#F59E0B` amber) are designed for digital marketing
accent use, not for always-on monitoring with many simultaneous
indicators.

### Lesson learned

Design adoption decisions cannot be made by reading CSV descriptions
alone. The palette looked correct in isolation (2-3 elements) but
caused visual fatigue when applied to a 14+ sensor cell grid with
borders, labels, and additional status accents in TopWatchBar. Future
design adoption work must include a micro-prototype with target widget
density before commit.

### What changed in B.4.5.1

- Status tier colors desaturated 30-40% — saturation reduced, hue
  preserved (still distinguishable for color-blind operators)
- Background warmed: `#0F172A` cool slate -> `#0d0e12` warm near-black
- Card elevation increased: was ~7% lightness diff, now ~15%
- Border subtler: `#475569` -> `#2d3038` (less harsh against new BG)
- Accent returned to original B.1 v1 indigo `#7c8cff` — classic
  scientific instrument convention (LabVIEW, MATLAB, Cadence)
- Plot line palette desaturated to match status tier philosophy
- All token names preserved — only values changed

### What did NOT change

- Architecture (alias system) preserved
- Fira Code + Fira Sans typography preserved
- Spacing 8px grid preserved
- 4px sharp radius preserved
- Documentation structure preserved
- License attribution still valid — we use skill **philosophy**
  (16-token semantic model, status tier system, anti-pattern rules,
  spacing discipline, typography pairing) but adjust **specific hex
  values** for our domain
