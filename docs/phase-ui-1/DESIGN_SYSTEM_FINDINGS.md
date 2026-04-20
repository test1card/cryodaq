# CryoDAQ Design System — Findings & Decisions

**Status:** Reference document for Phase UI-1 v2 Block B.4.5+ work
**Source:** UI UX Pro Max skill v2.5.0 (MIT licensed, Next Level Builder)
**Skill repo:** https://github.com/nextlevelbuilder/ui-ux-pro-max-skill
**Date prepared:** 2026-04-15
**Adopted depth:** Medium — colors + fonts + spacing + radius + status tier; layouts unchanged

This document captures all design system decisions for CryoDAQ extracted
from the UI UX Pro Max skill databases. It is the authoritative source for
B.4.5 design adoption work and all subsequent block specs (B.5+).

---

## Why this document exists

UI UX Pro Max ships as a Python reasoning engine over CSV databases. We do
not install it as a runtime dependency in CryoDAQ. Instead we extracted
design tokens, typography pairings, and anti-pattern rules manually from
the skill ZIP, and we apply them statically to `theme.py`. Once applied
we no longer need the skill at runtime — but we DO need to remember why
we picked each token, so future blocks can stay consistent.

If anyone wonders "why is the background `#0F172A` and not `#1E1E1E`" — the
answer is in this document.

---

## License attribution

The skill is MIT licensed. We use color values, typography pairings, and
guideline rules extracted from its CSV databases. We do not redistribute
the skill itself, only derived design decisions applied to our own code.

Required attribution lives in:
- `docs/design-system/MASTER.md` header (created in B.4.5 Task 2)
- `CHANGELOG.md` unreleased entry under "Adopted from"
- `THIRD_PARTY_LICENSES.md` if/when that file exists

Attribution text:

> Design system colors, typography pairings, and UX guidelines adapted
> from UI UX Pro Max skill v2.5.0 by Next Level Builder, MIT licensed.
> https://github.com/nextlevelbuilder/ui-ux-pro-max-skill

---

## Style direction: hybrid Real-Time Monitoring + Data-Dense Dashboard

CryoDAQ is a real-time scientific instrument operator interface for
week-long cryogenic experiments. The closest matches in the UI UX Pro Max
style database are two BI/Analytics Dashboard styles, both of which apply.

We adopt a **hybrid** taking philosophy from one and discipline from the
other.

### From "Real-Time Monitoring" we take

- **Live data philosophy** — every value visible is current, status
  indicators reflect real state, no historical data masquerading as live
- **Color semantics for status tiers** — critical red, warning amber/orange,
  normal green, stale gray. Always meaningful, never decorative.
- **Status awareness baked into every widget** — sensor cells, top bar
  context, future phase widget all show status not just value
- **"Connection status shown"** rule — if engine is disconnected, every
  affected widget must indicate it (already done in v2 shell)

### From "Data-Dense Dashboard" we take

- **Spatial discipline** — compact spacing, max data per screen, minimal
  padding, no decorative whitespace
- **Concrete spacing tokens** — `--grid-gap: 8px, --card-padding: 12px,
  --header-height: 56px, --row-height: 36px`
- **Sharp geometry** — `--border-radius: 4px` (not 8/12/16). Technical,
  not consumer-friendly rounded.
- **Chart color discipline** — semantic colors for success/warning/alert
  consistent across all data viz

### What we explicitly REJECT from these styles

- ❌ **Pulse/blink animations on alarms** — Real-Time Monitoring suggests
  "alert pulse/glow, status indicator blink". CryoDAQ is an ambient
  information radiator for week-long unattended runs. Blinking is
  distracting and operator-hostile. Critical alarms can use color tier
  + audio (future), but no constant motion.
- ❌ **Alert sounds** for routine state changes. Sounds reserved for true
  emergencies (interlock trip), not for warnings.
- ❌ **"Hero metrics" treatment** — we already canceled T11/T12 hero
  readouts because reference channels change per experiment. The
  TopWatchBar T_min/T_max from cold channels (B.4) is the substitute.
- ❌ **Loading skeletons** for sensor cells — they refresh at 1Hz, no
  visible loading states needed. Skeletons are for slow async data.

### Other styles considered and rejected

| Style | Why rejected |
|-------|--------------|
| Minimalism & Swiss Style | Too general, no data-density token discipline |
| Bento Box Grid | Marketing-y, our sensor grid is already structurally similar |
| Cybersecurity Platform | Theatrical "hacker movie" aesthetic, not scientific |
| Biotech / Life Sciences | Light theme only, dark theme required |
| HUD / Sci-Fi FUI | Too immersive, not professional instrument |
| Glassmorphism | Wastes pixels on transparency, low contrast risk |
| Modern Dark (Cinema Mobile) | Mobile-optimized, not desktop dashboard |

---

## Color palette: Smart Home/IoT Dashboard (extended)

This was the **only true dark monitoring palette** in the 161-palette
database. Direct fit for CryoDAQ context. We adopt the full 16-token
semantic set and extend it with 5 status tiers and 1 cold-temperature
highlight specific to our use case.

### Base palette (from skill database verbatim)

| Token | Value | Role |
|-------|-------|------|
| `Primary` | `#1E293B` | Slate dark — primary chrome surfaces, button backgrounds |
| `On Primary` | `#FFFFFF` | Text on primary |
| `Secondary` | `#334155` | Slate — secondary surfaces, hover states |
| `On Secondary` | `#FFFFFF` | Text on secondary |
| `Accent` | `#22C55E` | Status green — "all systems normal" highlights |
| `On Accent` | `#0F172A` | Text on accent |
| `Background` | `#0F172A` | Deep slate — main canvas |
| `Foreground` | `#F8FAFC` | Almost-white — primary text |
| `Card` | `#1B2336` | Elevated surface — cards, panels |
| `Card Foreground` | `#F8FAFC` | Text on card |
| `Muted` | `#272F42` | Subdued surface — disabled, placeholder |
| `Muted Foreground` | `#94A3B8` | Dim text — labels, captions |
| `Border` | `#475569` | Default borders, separators |
| `Destructive` | `#EF4444` | Alarm red — danger actions |
| `On Destructive` | `#FFFFFF` | Text on destructive |
| `Ring` | `#1E293B` | Focus ring |

### CryoDAQ extensions (status tiers + cold highlight)

These are not in the original skill palette but we add them because
CryoDAQ has cryogenic-specific semantics that the generic dashboard
palette doesn't cover. Color values chosen to match Data-Dense
Dashboard chart color recommendations (green/amber/red).

| Token | Value | Role | Russian label |
|-------|-------|------|---------------|
| `Status OK` | `#22C55E` | Channel within normal range | Норма |
| `Status Warning` | `#F59E0B` | Channel approaching threshold | Внимание |
| `Status Caution` | `#FB923C` | Channel near limit | Предупреждение |
| `Status Fault` | `#EF4444` | Channel out of bounds / hardware error | Авария |
| `Status Stale` | `#64748B` | No recent data (>30s) | Устарело |
| `Cold Highlight` | `#38BDF8` | T_min/T_max in TopWatchBar emphasis | (no label) |

### Mapping from CryoDAQ ChannelStatus enum to Status tier

| `ChannelStatus` enum member | Status tier token | Russian label |
|---|---|---|
| `OK` | `Status OK` | Норма |
| `OVERRANGE` | `Status Fault` | Перегрузка |
| `UNDERRANGE` | `Status Fault` | Недоступно |
| `SENSOR_ERROR` | `Status Fault` | Ошибка датчика |
| `TIMEOUT` | `Status Stale` | Устарело |
| (no data in buffer) | `Status Stale` | Нет данных |

Note: `Warning` and `Caution` tiers are not currently emitted by any
backend — they exist as design tokens for future alarm v2 phase-gated
rules. Sensor cells will only show OK / Fault / Stale tiers in
practice today.

---

## Typography: "Dashboard Data" pairing

Selected from 73 font pairings in the skill typography database.

| Role | Font | Source |
|------|------|--------|
| Heading / numeric / labels | **Fira Code** | Google Fonts |
| Body / prose / menus | **Fira Sans** | Google Fonts |

**Mood per skill:** "dashboard, data, analytics, code, technical, precise"
**Best for per skill:** "Dashboards, analytics, data visualization, admin panels"
**Notes per skill:** "Fira family cohesion. Code for data, Sans for labels."

### Why Fira (and not other monos)

- **Fira Code** has programming ligatures and was designed by Mozilla for
  data display. Consistent character widths — sensor values align across
  cells without hand-tuning.
- **Fira Sans** is the humanist sans companion to Fira Code, designed by
  the same team. Same letterforms, different weight discipline. Perfect
  for labels next to mono numerics.
- **Both are open source** (SIL Open Font License), bundlable in our
  `gui/resources/fonts/` folder same way Inter and JetBrains Mono are
  currently bundled.
- **"Dashboard Data" is the only pairing in all 73 entries** specifically
  named for dashboard analytics use case.

### Replacement of current fonts

| Current usage | Replace with |
|---------------|--------------|
| Inter Regular/Medium/SemiBold | **Fira Sans** Regular/Medium/SemiBold |
| JetBrains Mono Regular/Medium/SemiBold | **Fira Code** Regular/Medium/SemiBold |

Files to bundle:
- `Fira Sans Regular.ttf`
- `Fira Sans Medium.ttf`
- `Fira Sans SemiBold.ttf`
- `Fira Code Regular.ttf`
- `Fira Code Medium.ttf`
- `Fira Code SemiBold.ttf`

Old files (Inter*.ttf, JetBrainsMono*.ttf) stay in `resources/fonts/`
during transition for safety. Removed in B.7 cleanup.

### Type scale

Adopted from Data-Dense Dashboard variables, adjusted for desktop:

| Token | Value | Use case |
|-------|-------|----------|
| `font_size_xs` | 11px | Captions, status hints, tooltips |
| `font_size_sm` | 12px | Default labels, table cells |
| `font_size_base` | 14px | Body text, menu items |
| `font_size_lg` | 16px | Section headings, dialog titles |
| `font_size_xl` | 20px | Page titles, prominent values |
| `font_size_2xl` | 28px | Hero values (TopWatchBar context numbers) |
| `font_size_3xl` | 40px | Phase widget large display (B.5 future) |

Weight tokens:

| Token | Value | Use case |
|-------|-------|----------|
| `font_weight_regular` | 400 | Body text |
| `font_weight_medium` | 500 | Labels, secondary emphasis |
| `font_weight_semibold` | 600 | Values, primary emphasis |
| `font_weight_bold` | 700 | Hero values, alerts |

---

## Spacing rhythm

Adopted from Data-Dense Dashboard `Design System Variables` with minor
adjustments for desktop density.

| Token | Value | Use case |
|-------|-------|----------|
| `space_0` | 0px | Reset |
| `space_1` | 4px | Tight gaps within compact components |
| `space_2` | 8px | Default grid gap, small padding |
| `space_3` | 12px | Card padding, default content padding |
| `space_4` | 16px | Section gaps, dialog padding |
| `space_5` | 24px | Major section separation |
| `space_6` | 32px | Page-level padding |

| Layout token | Value | Use case |
|--------------|-------|----------|
| `header_height` | 56px | TopWatchBar height |
| `tool_rail_width` | 56px | Left ToolRail width |
| `bottom_bar_height` | 28px | BottomStatusBar height |
| `row_height` | 36px | Table rows, list items |
| `card_padding` | 12px | Sensor cell internal padding |
| `grid_gap` | 8px | Sensor grid cell-to-cell gap |

---

## Border radius

Sharp, technical aesthetic. Skill recommends `--border-radius: 0px` for
Minimalism & Swiss but that's too austere for sensor cells. Compromise:
4px small, 6px medium, no large rounding.

| Token | Value | Use case |
|-------|-------|----------|
| `radius_none` | 0px | Tables, separators |
| `radius_sm` | 4px | Buttons, cells, default elements |
| `radius_md` | 6px | Cards, panels, dialogs |
| `radius_lg` | 8px | Modal overlays (rare) |
| `radius_full` | 9999px | Pills, status dots |

---

## Effects & motion

### Allowed

- **Hover transitions:** 150-300ms ease-out (per skill recommendation)
- **Focus rings:** 2px solid `Ring` color, immediate (no transition)
- **Color changes on status update:** instant (no transition — operator
  needs immediate awareness of state change)
- **Tooltip fade-in:** 200ms after 500ms hover delay
- **Loading spinners:** for async ops only (calibration, archive load)

### Forbidden

- **Pulse / blink** on any element (anti-pattern for ambient screens)
- **Glow** effects (text-shadow, box-shadow blur halos)
- **Backdrop blur** (low contrast risk, performance hit on Qt)
- **Parallax scrolling** (anti-pattern per skill ux-guidelines High severity)
- **Scroll-jacking** (no implicit scrolling animations)
- **Marquee text** for long labels (use ellipsis + tooltip instead)
- **Bouncing or spring physics** on UI elements
- **Animation duration > 400ms** for interactive feedback

### prefers-reduced-motion

If the OS reports reduced motion preference, all transitions become
instant (0ms). Qt does not have a built-in equivalent of CSS
`prefers-reduced-motion`, so we expose a settings toggle:
`Параметры → Доступность → Отключить анимации`. Default off, toggleable.

This is a **future** task, not B.4.5 scope. Backlog item.

---

## UX anti-patterns we actively avoid

Extracted from the 99-entry `ux-guidelines.csv` filtered to
HIGH/CRITICAL severity AND categories applicable to desktop Qt apps.

### Accessibility (HIGH)

- **Color Contrast:** body text against background must be ≥ 4.5:1 (WCAG AA).
  All Foreground-on-Background combinations in our palette verified:
  - `#F8FAFC` on `#0F172A` = 16.7:1 ✓
  - `#94A3B8` on `#0F172A` = 8.2:1 ✓ (muted text)
  - `#0F172A` on `#22C55E` = 8.4:1 ✓ (on accent)
- **Color Only:** never convey information by color alone. Status cells
  must show text label (Норма / Авария) in addition to border color.
  **Already enforced in B.3 sensor cells.** ✓
- **Keyboard Navigation:** all interactive elements reachable via Tab.
  Focus visible via 2px ring. Currently partial — sensor cells need
  Tab-stop support (B.4.5 scope).
- **Form Labels:** all inputs have associated labels (Qt: `setBuddy`).
  Currently scattered, B.4.5 not in scope, future audit.

### Layout (HIGH)

- **Z-Index Management:** stacking context conflicts cause hidden elements.
  Qt has its own z-order via `raise_()` / `lower()` — not CSS z-index.
  No conflict observed in current code.
- **Content Jumping:** layout shift when content loads is jarring. Sensor
  cells have fixed dimensions, plot widgets reserve their zones — no
  jumping observed.

### Interaction (HIGH)

- **Focus States:** keyboard users need visible focus indicators.
  Need to verify that all clickable cells, buttons, and menu items
  have visible focus rings. **B.4.5 explicitly addresses this** via
  global QSS `*:focus { outline: 2px solid {Ring}; }`.
- **Loading Buttons:** prevent double submission. Already handled in
  ZmqCommandWorker pattern.
- **Error Feedback:** users need to know when something fails.
  Operator log catches engine errors, alarm panel for safety state.
- **Confirmation Dialogs:** prevent accidental destructive actions.
  Already implemented for "Завершить эксперимент", missing for some
  context menu actions in B.3 (e.g. "Скрыть" — instant, no confirm).
  **Backlog: confirm before hide.**

### Animation (HIGH)

- **Excessive Motion:** documented above as forbidden
- **Reduced Motion:** documented above (backlog)
- **Loading States:** show feedback during async operations
- **Hover vs Tap:** hover effects don't work on touch — N/A for desktop
  Qt but worth noting

### Typography (HIGH)

- **Contrast Readability:** body text needs good contrast — verified above

### Performance (HIGH)

- **Image Optimization:** N/A (no large images in CryoDAQ UI)

### Feedback (HIGH)

- **Loading Indicators:** show system status during waits

### Pre-delivery checklist for every new dashboard widget

When implementing or reviewing a dashboard widget for B.5+ blocks, verify:

- [ ] No emojis as icons (use SVG: Lucide bundled in `resources/icons/`)
- [ ] Cursor changes to pointer on clickable elements (`setCursor(Qt.PointingHandCursor)`)
- [ ] Hover transitions 150-300ms via QSS
- [ ] Text contrast ≥ 4.5:1 against background
- [ ] Focus states visible for keyboard navigation
- [ ] No pulse/blink/glow animations
- [ ] Russian language for all operator-facing text
- [ ] Cyrillic Т (U+0422) in temperature channel filtering
- [ ] Cleanup hooks: closeEvent + destroyed signal for any subscription
- [ ] Multi-variable state transitions explicitly checked (B.3 lesson 2)
- [ ] Status hint text always present alongside color (no color-only meaning)
- [ ] Long labels use ElideRight + tooltip
- [ ] Tab-stop reachable if interactive
- [ ] Error path logged via `logger.warning` for debuggability

---

## Token names: from skill abstract to CryoDAQ Python identifiers

The skill provides semantic English token names (`Primary`, `Card Foreground`,
`Muted`, etc). For CryoDAQ Python `theme.py`, we adopt these names with
ALL_CAPS convention matching the existing module style:

```python
# Base palette (from Smart Home/IoT Dashboard, verbatim)
PRIMARY = "#1E293B"
ON_PRIMARY = "#FFFFFF"
SECONDARY = "#334155"
ON_SECONDARY = "#FFFFFF"
ACCENT = "#22C55E"
ON_ACCENT = "#0F172A"
BACKGROUND = "#0F172A"
FOREGROUND = "#F8FAFC"
CARD = "#1B2336"
CARD_FOREGROUND = "#F8FAFC"
MUTED = "#272F42"
MUTED_FOREGROUND = "#94A3B8"
BORDER = "#475569"
DESTRUCTIVE = "#EF4444"
ON_DESTRUCTIVE = "#FFFFFF"
RING = "#1E293B"

# Status tier extensions (CryoDAQ specific)
STATUS_OK = "#22C55E"
STATUS_WARNING = "#F59E0B"
STATUS_CAUTION = "#FB923C"
STATUS_FAULT = "#EF4444"
STATUS_STALE = "#64748B"
COLD_HIGHLIGHT = "#38BDF8"

# Backwards compatibility aliases (deprecate gradually)
# These map old token names to new ones. Each callsite that uses an
# old alias should be migrated, then alias removed in B.7 cleanup.
TEXT_PRIMARY = FOREGROUND
TEXT_SECONDARY = MUTED_FOREGROUND
TEXT_MUTED = MUTED_FOREGROUND
TEXT_INVERSE = ON_PRIMARY
SURFACE_PANEL = CARD
SURFACE_CARD = CARD
BORDER_SUBTLE = BORDER
ACCENT_400 = ACCENT
SUCCESS_400 = STATUS_OK
WARNING_400 = STATUS_WARNING
DANGER_400 = STATUS_FAULT

# Typography
FONT_DISPLAY = "Fira Code"  # numeric, headings, labels
FONT_BODY = "Fira Sans"     # prose, menus, descriptions
FONT_MONO = "Fira Code"     # alias

# Type scale
FONT_SIZE_XS = 11
FONT_SIZE_SM = 12
FONT_SIZE_BASE = 14
FONT_SIZE_LG = 16
FONT_SIZE_XL = 20
FONT_SIZE_2XL = 28
FONT_SIZE_3XL = 40

FONT_WEIGHT_REGULAR = 400
FONT_WEIGHT_MEDIUM = 500
FONT_WEIGHT_SEMIBOLD = 600
FONT_WEIGHT_BOLD = 700

# Spacing
SPACE_0 = 0
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 24
SPACE_6 = 32

# Layout
HEADER_HEIGHT = 56
TOOL_RAIL_WIDTH = 56
BOTTOM_BAR_HEIGHT = 28
ROW_HEIGHT = 36
CARD_PADDING = 12
GRID_GAP = 8

# Radius
RADIUS_NONE = 0
RADIUS_SM = 4
RADIUS_MD = 6
RADIUS_LG = 8
RADIUS_FULL = 9999

# Motion
TRANSITION_FAST_MS = 150
TRANSITION_BASE_MS = 200
TRANSITION_SLOW_MS = 300
```

The backwards compatibility aliases are critical. Without them, B.4.5
adoption would require a flag-day migration of every QSS string in
the codebase. With aliases, existing code keeps working and we migrate
callsites gradually as they are touched.

---

## Verification checklist (run before declaring B.4.5 complete)

After applying the new theme, verify visually:

- [ ] Engine starts (`CRYODAQ_MOCK=1 cryodaq-engine`)
- [ ] GUI launches (`CRYODAQ_MOCK=1 cryodaq`)
- [ ] After 60s uptime:
  - [ ] Background is dark slate (`#0F172A`)
  - [ ] Sensor cells have `#1B2336` card surface
  - [ ] Sensor cell borders are status-colored (green for OK)
  - [ ] Numeric values render in Fira Code
  - [ ] Channel labels render in Fira Sans
  - [ ] TopWatchBar persistent context strip uses Fira Code for numbers
  - [ ] T_min/T_max in cyan `#38BDF8` (cold highlight) — distinguishable
    from regular text
- [ ] Open overlay panel (e.g. calibration via ToolRail icon)
  - [ ] TopWatchBar context strip remains visible
  - [ ] Overlay panel inherits dark theme (no white flash)
- [ ] Right-click sensor cell:
  - [ ] Context menu uses theme colors, not OS native colors
  - [ ] Russian labels readable
- [ ] Double-click sensor cell:
  - [ ] Inline edit mode visible focus ring
  - [ ] QLineEdit uses theme background, not white
- [ ] Tests still pass (~966+, no regressions)

---

## What is NOT in B.4.5 scope (deferred)

These are mentioned for completeness but explicitly out of scope:

- **Removing old Inter / JetBrains Mono fonts** — kept during transition
  for safety. B.7 cleanup removes them.
- **Removing backwards-compatible alias tokens** — kept during transition
  for code that still uses old names. B.7 cleanup removes aliases after
  all callsites migrated.
- **Reduced motion settings toggle** — UX backlog item, not adopted now
- **Confirmation dialogs for destructive context menu actions** — backlog
- **Tab-stop audit** for all interactive widgets — backlog
- **Per-widget keyboard shortcut documentation** — backlog
- **High-contrast theme variant** for accessibility — backlog
- **Light theme variant** — explicitly not planned (CryoDAQ is dark only
  per operator preference and skill recommendation for monitoring dashboards)

---

## Future blocks reference this document

When writing B.5 (PhaseAwareWidget), B.6 (QuickLogWidget), B.7 (legacy
cleanup), and any future polish blocks, reference this document via:

```markdown
## Design system reference

This widget follows the design system documented in
`docs/design-system/MASTER.md` (created by Block B.4.5). Use only
tokens defined in `theme.py`. If a new token is needed, add it to
`theme.py` first AND update `MASTER.md` AND update this findings
document.

Specifically this widget uses:
- Background: `theme.CARD`
- Text: `theme.FOREGROUND` for primary, `theme.MUTED_FOREGROUND` for labels
- Status colors: `theme.STATUS_OK / STATUS_WARNING / STATUS_FAULT / STATUS_STALE`
- Font: `theme.FONT_BODY` for labels, `theme.FONT_DISPLAY` for numbers
- Spacing: `theme.SPACE_2 / SPACE_3 / SPACE_4`
- Radius: `theme.RADIUS_SM` for default, `theme.RADIUS_MD` for cards
```

This is the **mandatory reference pattern** for all future block specs.
No more ad-hoc color picking, no more "use whatever theme has".

---

## Backlog items generated by this analysis

Added to Phase UI-1 v2 backlog during design system review:

| ID | Sev | Description |
|----|-----|-------------|
| DS-1 | LOW | Add reduced motion toggle to settings, respect prefers-reduced-motion |
| DS-2 | MED | Audit Tab-stop reachability for all interactive widgets |
| DS-3 | LOW | Confirmation dialog for "Скрыть" context menu action in sensor cell |
| DS-4 | LOW | High-contrast theme variant for accessibility |
| DS-5 | LOW | Per-widget keyboard shortcut documentation in operator manual |
| DS-6 | LOW | Migrate all backwards-compatible alias tokens, remove aliases (B.7 task) |

---

## Document changelog

- **2026-04-15** — Initial extraction from UI UX Pro Max v2.5.0 skill
  databases. Style: hybrid Real-Time Monitoring + Data-Dense Dashboard.
  Palette: Smart Home/IoT Dashboard + 5 status tier extensions.
  Typography: Dashboard Data (Fira Code + Fira Sans).
