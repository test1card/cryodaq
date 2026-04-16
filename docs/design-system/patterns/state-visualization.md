---
title: State Visualization
keywords: state, visualization, ok, warning, caution, fault, stale, status, color, border, icon, redundant-channels
applies_to: how to visually communicate state (OK, warning, caution, fault, stale, disconnected)
status: canonical
references: rules/color-rules.md, rules/accessibility-rules.md, tokens/colors.md
last_updated: 2026-04-17
---

# State Visualization

Rules for communicating state — is this healthy, warning-approaching, faulted, stale, or disconnected — consistently across every surface. Addresses: operator should recognize «red-bordered thick rectangle» as fault on any panel, not relearn per panel.

## The state vocabulary

Every stateful element in CryoDAQ uses one of exactly six states:

| State | Meaning | Token | Common visual |
|---|---|---|---|
| **ok** | Healthy, normal operation | STATUS_OK | Default chrome, or subtle green accent for active |
| **caution** | Approaching soft limit, worth noticing | STATUS_CAUTION | Orange tint |
| **warning** | Exceeding soft limit or unusual state | STATUS_WARNING | Amber color |
| **fault** | Hard limit crossed, or system fault | STATUS_FAULT | Red color + thick border + icon |
| **stale** | Data not updating; unknown current state | STATUS_STALE | Grey, dimmed |
| **disconnected** | System offline / not talking | STATUS_STALE + different chrome | Grey + dashed border or «—» |

No sub-states, no "orange-red gradient", no "fault-but-not-quite-fault". Six states exhaust what we express.

## Two-channel signaling rule

**Status is NEVER communicated by color alone.** Every status signal uses two of these three channels:

1. **Color** (STATUS_OK, STATUS_WARNING, etc.)
2. **Shape / position** (border thickness, left-edge accent, icon presence)
3. **Text** (status label, value readout, tooltip)

This serves two purposes: (a) accessibility for color-blind operators (RULE-A11Y-002), and (b) defensibility — if one channel is noisy (dimly-lit monitor washes out colors), the other still communicates.

Examples:
- **SensorCell in fault:** STATUS_FAULT 2px border (shape) + alert-triangle icon (shape) + STATUS_FAULT color (color) = three channels.
- **BottomStatusBar dot + label:** color dot + text label = two channels.
- **Mode badge:** filled STATUS_OK color + «Эксперимент» text = two channels.

Never:
- Red text alone without border or icon.
- Green dot without label.

## Contrast-aware color application

STATUS_FAULT (`#c44545`) and STATUS_INFO (`#4a7ba8`) **fail WCAG AA body text contrast** (3.94:1 and 4.31:1 respectively against BACKGROUND). Per RULE-A11Y-003:

- **Do NOT color body text with STATUS_FAULT.** The value «4.21 K» on a faulted channel stays `FOREGROUND` color; fault is signaled by border + icon.
- **Do NOT color body text with STATUS_INFO.** Use at large (18pt+) sizes only, or use as a chrome color (dot, filled pill background).
- **STATUS_OK** (4.67:1) passes AA body → safe for body text.
- **STATUS_WARNING, STATUS_CAUTION** (both pass AA) → safe for body text.
- **STATUS_STALE** (2.94:1) fails all → intentional; stale items are visually de-emphasized by design.

Filled pill contexts (e.g., filled STATUS_FAULT badge with ON_DESTRUCTIVE text) pass contrast because the white-ish text on dark-red background is different math from red text on dark background.

## State expression by element type

### Numeric values (ExecutiveKpiTile, SensorCell, TopWatchBar vitals)

| State | Value color | Border | Icon |
|---|---|---|---|
| ok | FOREGROUND | BORDER 1px | — |
| caution | STATUS_CAUTION | BORDER 1px | — |
| warning | STATUS_WARNING | BORDER 1px | — |
| fault | FOREGROUND | STATUS_FAULT 2px | alert-triangle inline |
| stale | STATUS_STALE | BORDER 1px | dim — |
| disconnected | TEXT_DISABLED | BORDER 1px dashed | — |

Note: fault keeps value FOREGROUND per RULE-A11Y-003 (contrast); the border + icon carry the red signal.

### Inline status indicators (BottomStatusBar, InlineIndicator)

| State | Dot color | Label color |
|---|---|---|
| ok | STATUS_OK | MUTED_FOREGROUND |
| caution | STATUS_CAUTION | MUTED_FOREGROUND |
| warning | STATUS_WARNING | MUTED_FOREGROUND |
| fault | STATUS_FAULT | MUTED_FOREGROUND |
| stale | STATUS_STALE | MUTED_FOREGROUND |

Label stays MUTED_FOREGROUND; dot carries color. Avoids RULE-A11Y-003 body contrast failure.

### Filled pills / badges (Mode badge, AlarmBadge, filled StatusBadge)

| State | Background | Text / icon |
|---|---|---|
| ok | STATUS_OK fill | ON_DESTRUCTIVE text |
| warning | STATUS_WARNING fill | ON_DESTRUCTIVE text |
| caution | STATUS_CAUTION fill | ON_DESTRUCTIVE text |
| fault | STATUS_FAULT fill | ON_DESTRUCTIVE text |
| stale / empty | transparent | MUTED_FOREGROUND |

Filled pill context passes contrast because the ON_* paired token is contrast-tested with its background.

### Large containers (Card, BentoTile, proposed PanelCard)

Cards generally **stay neutral** even when their contents are about a faulted thing. The fault signal lives on the content (values, SensorCells), not on the card chrome.

Exception: if the entire card represents one faulted subject (e.g., entire ExperimentCard during fault), add a **3px left border** in STATUS_FAULT. Rest of card stays SURFACE_CARD. This keeps the card's role as container distinct from its contents' state.

### Plots (ChartTile)

- Line series color stays from PLOT_LINE_PALETTE (series distinction) — does NOT change to STATUS_FAULT based on data.
- A faulted series may be highlighted via per-series color override OR separate annotation (vertical line at fault time).
- Axis + gridline + chart background stay neutral regardless of data state.

## State transitions

All state transitions follow RULE-INTER-006 (instant for faults) and RULE-DATA-001 (atomic for live data):

- **ok → warning:** snap; no animation.
- **warning → fault:** snap; no animation. Additional: fault event fires Toast (transient) or Dialog (blocking ack) as per severity.
- **fault → ok:** snap after operator acknowledges fault. Auto-clear without ack is a potential data-loss issue — don't design for it.
- **any → stale:** snap when `stale_timeout_s` elapsed without update.
- **stale → ok:** snap when first fresh data arrives.

No tween, no fade, no pulsing. Transitions reflect actual system state changes — the visual must match the real event, not prettify it.

## State on derived / computed values

Computed values (e.g., delta-T per minute, cooldown rate) have state derived from the source channels' state:

- Source channels all ok → computed value ok
- Any source channel warning → computed warning
- Any source channel fault → computed value `—` (not computable during fault, display as missing rather than stale)
- Any source channel stale → computed value stale

Don't independently compute state for derived values — propagate from inputs. Otherwise a green derived value over a red source channel contradicts itself.

## State for non-data elements

- **Buttons:** state = interaction state (default, hover, pressed, focus, disabled). Not a data status. Don't color a button STATUS_FAULT unless it's a Destructive button (where STATUS_FAULT IS the base tone).
- **Inputs:** default / focus / error / disabled. Error state uses STATUS_FAULT border + error message; not fault status semantics.
- **Tabs / Navigation:** selected / hover / default / disabled. Not data status.
- **Progress / loading:** use STATUS_INFO sparingly + textual "Loading…"; don't conflate with data ok/fault.

## Ambiguous-state resolution

Sometimes a thing is in two states at once (e.g., channel is stale AND approaching a warning threshold as last-known). Precedence:

1. **fault** wins over all
2. **warning / caution** win over ok
3. **stale** wins over ok (unknown > known-ok)
4. **stale** loses to warning/fault (last-known hot value is more urgent than stale signal)
5. **disconnected** wins over stale (don't know AND can't talk)

Display the winning state's chrome. Tooltip may explain the secondary state («Последнее значение: 350 K (устарело 12с)»).

## State persistence

- **Transient states** (display-only) persist until underlying data changes.
- **Fault-latched states** (RULE-INTER-006-adjacent) require operator acknowledgement to clear. Even if underlying condition resolved, display stays in fault until acked.
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

10. **Warning at same chrome as fault.** Both red-ish. Must distinguish — warning is amber (STATUS_WARNING), fault is red (STATUS_FAULT).

## Related patterns

- `patterns/real-time-data.md` — how stale state is detected and expressed on live data
- `patterns/information-hierarchy.md` — fault is Tier-1; stale may be Tier-3 depending on context
- `patterns/destructive-actions.md` — Destructive button chrome uses STATUS_FAULT semantically differently

## Changelog

- 2026-04-17: Initial version. Six-state vocabulary (ok/caution/warning/fault/stale/disconnected). Two-channel redundancy rule. Contrast-aware application tables per element type. State transition and persistence rules.
