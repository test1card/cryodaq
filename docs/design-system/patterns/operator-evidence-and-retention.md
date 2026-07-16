---
title: Operator Evidence and Information Retention
keywords: operator evidence, panorama, stale, acknowledgement, alarms, coalescing, skew, responsive, projector
applies_to: every operator-visible CryoDAQ surface
status: canonical
last_updated: 2026-07-15
references: README.md, patterns/information-hierarchy.md, patterns/real-time-data.md, patterns/state-visualization.md, governance/testing-strategy.md
---

# Operator Evidence and Information Retention

This pattern records reviewed operator decisions for laboratory use. Visual
hierarchy may guide attention, but no GUI may improve calmness or beauty by
removing current values, last-known values, units, provenance, validity,
freshness, connectivity, acknowledgement state, or access to the complete
evidence set.

## Information that never disappears

- A numeric or derived value remains visible when it is still computable. A
  fault, caution, stale source, or identity problem is shown alongside it; it
  does not replace the value with an em dash unless no numeric result exists.
- Prioritization and aggregation may reorder evidence but must retain the total
  count, omitted severity, and a direct route to the complete list.
- Multiple simultaneous alerts remain countable and inspectable. The hierarchy
  may emphasize the most urgent item but may not present only one alert.
- Hidden channels are an intentional per-campaign operator choice. Automatic
  layout never hides channels. The interface may show a quiet hidden count and
  reveal control without treating intentional filtering as a fault.
- Exactly one experiment may be active on one machine. More than one is an
  invariant fault; the GUI must not silently select one.

## State is multi-dimensional

The operator-facing severity ladder is `safe | caution | fault`. `warning` is
not a separate visual severity because it is not reliably distinguishable from
`caution`; existing backend values migrate through an explicit compatibility
mapping rather than being silently reinterpreted.

Severity, freshness, connectivity, acknowledgement, identity validity, and
replay/live provenance are independent axes. A surface may show, for example,
an acknowledged fault with stale data and refused identity. No single state
label is allowed to erase the other axes.

- Stale/unknown data remains deliberately grey and visually quieter. It means
  last-known truth whose current validity is unknown, not good or bad. The
  static stale/disconnected text or shape remains visible; color is not the
  only cue.
- Safety colors are exclusive semantic signals. Green means safe/healthy,
  yellow-orange means caution, and red means fault. Series identity, physical
  quantity, selection, active phase, and active experiment use neutral or
  category colors, never safety colors.
- Activity is not health. Running/active experiment and phase indicators use a
  neutral selection/progress treatment plus a separate health indication.

## Acknowledgement and alarm onset

Acknowledgement transfers responsibility to the operator and removes the item
from the unacknowledged active-attention count. It does not rewrite history or
mean the physical condition resolved. The acknowledged condition remains in
the journal/handover evidence until resolution is recorded by the owning
backend workflow.

Current runtime annunciation has two owners: TopWatchBar sounds newly observed
alarm events, while BottomStatusBar repeats a bell every three seconds for
`fault_latched`. This fail-loud behavior is retained until the engine exposes
stable alarm-activation identity and an audio-only acknowledgement contract.
It is not the final design-system target: duplicate ownership, acknowledgement
of the exact activation, recurrence cadence, and visible muted/unavailable
audio remain an open consolidation gate. The fault remains static and fully
perceivable through text, shape, and color; pulsing/blinking is prohibited.

Emergency OFF hold-to-confirm remains an open hazard decision. No design-system
change may remove or add the hold without a separately reviewed tradeoff between
continued hazardous energy during the hold and accidental experiment/process
interruption.

## Live data and plots

- Numeric repaint and chart refresh remain capped at 2 Hz for human legibility.
  Acquisition, persistence, alarms, and event capture are not downsampled by
  this display budget. A short excursion must leave bounded evidence such as an
  interval extremum or event marker rather than becoming a faster-flickering
  digit.
- Operators retain control of plot ranges and time windows. A 60-second window
  remains useful for preparation and sensor tests; other phases may select a
  longer window. Automatic layout adjustment does not imply automatic axis
  selection.
- Cross-channel comparisons expose observation-time skew. Derived or comparative
  views show whether inputs form a coherent cut, the maximum skew, or the age
  of each input; they never imply simultaneity from merely adjacent values.

## Dense, beautiful, and responsive

“Avoid LabVIEW-like UI” means modernize typography, spacing, hierarchy,
plotting, interaction, and visual finish. It does not mean removing the dense
panoramic evidence that makes an operator dashboard useful.

Layout adjusts automatically from logical size and effective DPI:

1. reflow controls vertically before clipping;
2. recompute grid columns and cell density without hiding channels;
3. use deliberate scrolling for dense grids and tables;
4. preserve complete value/state/unit/provenance access at every supported
   size; and
5. leave room for a future operator density/scale override without claiming it
   exists in the current runtime.

Raw 720/800-pixel assumptions are not acceptance criteria. Validate supported
logical sizes at 100/125/150/200% scaling. A deferred fleet/projector mode for
100+ sensors and 4K wall displays will add virtualization, search/filter,
aggregation, semantic zoom, and projector-scale typography without replacing
the ordinary lab dashboard.

## Per-change evidence

Every GUI slice records:

1. operator benefit;
2. operator cost;
3. safety/workflow justification;
4. mitigation and tests; and
5. observable revise/revert trigger.

Operator feedback is evidence, not a waiver for truthful state, accessibility,
or fail-closed behavior.
