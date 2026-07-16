---
title: State Visualization
keywords: state, visualization, ok, warning, caution, fault, stale, status, color, border, icon, redundant-channels
applies_to: how to visually communicate state (OK, warning, caution, fault, stale, disconnected)
status: canonical
references: rules/color-rules.md, rules/accessibility-rules.md, tokens/colors.md
last_updated: 2026-07-15
---

# State Visualization

Rules for communicating state — is this healthy, warning-approaching, faulted, stale, or disconnected — consistently across every surface. Addresses: operator should recognize «red-bordered thick rectangle» as fault on any panel, not relearn per panel.

## The severity vocabulary and orthogonal state axes

Operator-facing severity uses three evenly separated steps:

| State | Meaning | Token | Common visual |
|---|---|---|---|
| **safe** | Healthy, normal operation | STATUS_OK | Default chrome + explicit safe text/shape where needed |
| **caution** | Abnormal or approaching a limit; investigate | STATUS_CAUTION | Yellow-orange + text/shape |
| **fault** | Hard limit crossed, or system fault | STATUS_FAULT | Red color + thick border + icon |

`warning` is not a separate visual severity. Existing backend `warning` values
map explicitly to `caution` during migration. Freshness (`fresh | stale`),
connectivity (`connected | disconnected`), acknowledgement, identity validity,
and replay/live provenance are independent axes and remain simultaneously
visible. They are not mutually exclusive severity states.

| Accepted source value | Operator text | Token | Presentation |
|---|---|---|---|
| `ok` | `НОРМА` | `STATUS_OK` | safe |
| `caution` / legacy `warning` | `ВНИМАНИЕ` | `STATUS_CAUTION` | caution |
| `fault` / alarm `CRITICAL` | `АВАРИЯ` / `КРИТ` | `STATUS_FAULT` | fault |
| `stale` | `УСТАРЕЛО` | `STATUS_STALE` | freshness axis |
| `disconnected` | `НЕТ СВЯЗИ` | `STATUS_STALE` + disconnected shape | connectivity axis |
| unknown alarm level | `НЕИЗВ` | `STATUS_FAULT` | conspicuous unknown; never caution |

Backend payloads, stored history, alarm ordering, acknowledgement, and
escalation are not rewritten. New presentation producers must not emit
`warning`; compatibility remains until all supported history/backends stop.

## Two-channel signaling rule

**Status is NEVER communicated by color alone.** Every status signal uses two of these three channels:

1. **Color** (STATUS_OK, STATUS_CAUTION, STATUS_FAULT, etc.)
2. **Shape / position** (border thickness, left-edge accent, icon presence)
3. **Text** (status label, value readout, tooltip)

This serves two purposes: (a) accessibility for color-blind operators (RULE-A11Y-002), and (b) defensibility — if one channel is noisy (dimly-lit monitor washes out colors), the other still communicates.

Examples:
- **SensorCell in fault:** STATUS_FAULT 2px border (shape) + alert-triangle icon (shape) + STATUS_FAULT color (color) = three channels.
- **BottomStatusBar dot + label:** color dot + text label = two channels.
- **Active phase:** ACCENT border + phase text = two non-health channels;
  experiment health remains a separate safe/caution/fault fact.

Never:
- Red text alone without border or icon.
- Green dot without label.

## Contrast-aware color application

STATUS_FAULT (`#c44545`) and STATUS_STALE (`#5a5d68`) fail WCAG AA body-text contrast against the default dark background. Per RULE-A11Y-003:

- **Do NOT color body text with STATUS_FAULT.** The value «4.21 K» on a faulted channel stays `FOREGROUND` color; fault is signaled by border + icon.
- **Do NOT color numeric value text with STATUS_STALE.** Dim the stale chrome
  and explicit label while keeping the last-known value legible.
- **STATUS_OK** (4.67:1) passes AA body → safe for body text.
- **STATUS_CAUTION** (and the legacy WARNING alias) passes AA on the default dark background.
- **STATUS_STALE** (2.94:1) fails all → intentional; stale items are visually de-emphasized by design.

Filled pill contexts (e.g., filled STATUS_FAULT badge with ON_DESTRUCTIVE text) pass contrast because the white-ish text on dark-red background is different math from red text on dark background.

## State expression by element type

### Numeric values (ExecutiveKpiTile, SensorCell, TopWatchBar vitals)

| State | Value color | Border | Icon |
|---|---|---|---|
| ok | FOREGROUND | BORDER 1px | — |
| caution | STATUS_CAUTION | BORDER 1px | — |
| fault | FOREGROUND | STATUS_FAULT 2px | alert-triangle inline |
| stale | FOREGROUND | STATUS_STALE 1px | static stale text/icon |
| disconnected | TEXT_DISABLED | BORDER 1px dashed | — |

Note: fault keeps value FOREGROUND per RULE-A11Y-003 (contrast); the border + icon carry the red signal.

### Inline status indicators (BottomStatusBar, InlineIndicator)

| State | Dot color | Label color |
|---|---|---|
| ok | STATUS_OK | MUTED_FOREGROUND |
| caution | STATUS_CAUTION | MUTED_FOREGROUND |
| fault | STATUS_FAULT | MUTED_FOREGROUND |
| stale | STATUS_STALE | MUTED_FOREGROUND |

Label stays MUTED_FOREGROUND; dot carries color. Avoids RULE-A11Y-003 body contrast failure.

### Filled pills / badges (Mode badge, AlarmBadge, filled StatusBadge)

| State | Background | Text / icon |
|---|---|---|
| ok | STATUS_OK fill | ON_DESTRUCTIVE text |
| caution | STATUS_CAUTION fill | ON_DESTRUCTIVE text |
| fault | STATUS_FAULT fill | ON_DESTRUCTIVE text |
| stale / empty | transparent | MUTED_FOREGROUND |

Filled-pill text does not automatically pass contrast. Use the paired token,
measured context, and redundant icon/shape/adjacent label; caution pill text is
supplementary rather than the sole state signal.

### Large containers (Card, BentoTile, proposed PanelCard)

Cards generally **stay neutral** even when their contents are about a faulted thing. The fault signal lives on the content (values, SensorCells), not on the card chrome.

Exception: if the entire card represents one faulted subject (e.g., entire ExperimentCard during fault), add a **3px left border** in STATUS_FAULT. Rest of card stays SURFACE_CARD. This keeps the card's role as container distinct from its contents' state.

### Plots (ChartTile)

- Line series color stays from PLOT_LINE_PALETTE (series distinction) — does NOT change to STATUS_FAULT based on data.
- A faulted series keeps its identity color; a labeled threshold region or event annotation carries fault meaning.
- Axis + gridline + chart background stay neutral regardless of data state.

## State transitions

All state transitions follow RULE-INTER-006 (instant for faults) and RULE-DATA-001 (atomic for live data):

- **safe → caution:** snap; no animation.
- **caution → fault:** snap; persistent static fault plus the bounded onset cue
  from `operator-evidence-and-retention.md`.
- **fault acknowledgement:** stops the onset warning and transfers attention
  responsibility; it does not assert physical resolution.
- **any → stale:** snap when `stale_timeout_s` elapsed without update.
- **stale → ok:** snap when first fresh data arrives.

No tween, no fade, no pulsing. Transitions reflect actual system state changes — the visual must match the real event, not prettify it.

## State on derived / computed values

Computed values (e.g., delta-T per minute, cooldown rate) have state derived from the source channels' state:

- Source channels all safe → computed severity safe
- Any source channel caution → computed severity caution
- A source fault does not erase a still-computable numeric result. Keep the
  value and show fault/validity alongside it; use `—` only when computation is
  actually impossible.
- Any stale source adds visible stale truth without erasing severity.

Don't independently compute state for derived values — propagate from inputs. Otherwise a green derived value over a red source channel contradicts itself.

## State for non-data elements

- **Buttons:** state = interaction state (default, hover, pressed, focus, disabled). Not a data status. Don't color a button STATUS_FAULT unless it's a Destructive button (where STATUS_FAULT IS the base tone).
- **Inputs:** default / focus / error / disabled. Error state uses STATUS_FAULT border + error message; not fault status semantics.
- **Tabs / Navigation:** selected / hover / default / disabled. Not data status.
- **Progress / loading:** use STATUS_INFO sparingly + textual "Loading…"; don't conflate with data ok/fault.

## Multi-dimensional state presentation

Do not choose one winning label and hide the rest. Severity may determine the
primary border, while freshness, connectivity, acknowledgement, identity, and
provenance remain visible as adjacent static text or shape. For example:
`FAULT · УСТАРЕЛО 12 с · ПОДТВЕРЖДЕНО ОПЕРАТОРОМ`. A tooltip may add detail but
cannot be the only place where a secondary safety-relevant axis appears.

## State persistence

- **Transient states** (display-only) persist until underlying data changes.
- Acknowledgement and resolution are independent. Acknowledgement removes the
  onset warning and unacknowledged-attention count; backend resolution owns the
  condition state.
- **Stale** clears automatically when fresh data arrives.

## Rules applied

- **RULE-COLOR-002** — status color semantics locked
- **RULE-A11Y-002** — never color alone; two-channel redundancy
- **RULE-A11Y-003** — contrast-aware color application (STATUS_FAULT / INFO body fail AA)
- **RULE-INTER-006** — fault events render instantly
- **RULE-DATA-001** — atomic state updates

## Common mistakes

1. **Red text on dark background for fault.** Fails body contrast (3.94:1). Use border + icon; keep text FOREGROUND.

2. **Gradient from green to red.** "To show severity level". Stick to discrete states; gradient is ambiguous and hard to act on.

3. **Pulsing red border on fault.** Distracting. RULE-INTER-006 says instant + persistent, not animated.

4. **Color-only indicator.** A red dot with no text. Fails RULE-A11Y-002.

5. **Same color for different semantics.** Green both for "OK running" and "Selected tab". Green reserved for STATUS_OK; selection uses ACCENT (RULE-COLOR-004).

6. **Fault chrome on the wrong element.** Making the whole dashboard red because one channel faulted. Signal the faulted element (sensor cell, card with 3px border); keep unrelated elements neutral.

7. **Derived state inconsistent with sources.** Computing «средняя T = 100K, ok» while individual sensors are all stale. Show derived as stale too.

8. **Stale-as-default for just-connected.** On app startup, all channels read stale until first data. Show as stale, not ok — otherwise operator may trust uninitialized zeros.

9. **Disconnected shown as fault.** Engine offline ≠ hardware fault. Use disconnected state (grey, dashed border), not red.

10. **Warning as a second yellow-orange step.** Operators cannot reliably
distinguish it from caution. Map legacy warning to caution and keep the next
step visually and semantically distinct: fault.

## Related patterns

- `patterns/real-time-data.md` — how stale state is detected and expressed on live data
- `patterns/information-hierarchy.md` — fault is Tier-1; stale may be Tier-3 depending on context
- `patterns/destructive-actions.md` — Destructive button chrome uses STATUS_FAULT semantically differently

## Changelog

- 2026-07-15 (v4.0.0): Added the canonical legacy-warning compatibility table, conspicuous unknown fallback, and presentation-boundary migration rule.
- 2026-07-15 (v4.0.0): Replaced overlapping caution/warning severity with
  safe/caution/fault, made freshness/connectivity/acknowledgement/identity
  orthogonal, and prohibited erasing computable values.
- 2026-04-17: Initial six-state vocabulary and visual rules.
