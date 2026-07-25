---
title: Operator Snapshot Presentation
keywords: F36, atomic snapshot, authority, revision, provenance, operator task
applies_to: composing typed operator-snapshot summaries into operator-facing surfaces
status: canonical
last_updated: 2026-07-11
references: cryodaq-primitives/operator-snapshot-components.md, patterns/state-visualization.md, patterns/information-hierarchy.md
---

# Operator Snapshot Presentation

## Problem

Live readings, heartbeat, disk-free text, cached panel state, and replay data can
all be individually real while still failing to answer the operator's question:
“Is this one coherent current truth?” This pattern renders only immutable F36.1
summary cuts and keeps source, freshness, state, reason, and next inspection
destination together.

## Composition

1. A state/ingress owner supplies a complete typed summary from one accepted
   `OperatorSnapshot`. Presentation widgets do not access the owner directly.
2. `SnapshotCardShell.render(summary)` atomically updates status, optional
   typed body, and provenance for the same revision. The supported attention
   composition binds `AttentionList` in the card constructor; callers never
   render its body separately.
3. Domain content uses typed rows or a virtualized list. Missing data is an
   explicit stale/disconnected/unavailable presentation, never an empty green
   surface.
4. After the first coherent cut, `FreshnessProvenanceFooter` remains visible as
   Tier 3 evidence. Before that cut, the footer and any bound body are hidden;
   only explicit disconnected/unavailable shell truth is visible. Urgent
   state/reason remains Tier 1/2 and is never visually displaced by provenance.
5. A next step is optional and navigation-only. Absence of reviewed intent
   disables the control instead of guessing a destination.

## Worked example: unsafe preconditions

- Card input: one `ReadinessSummary` from revision 412.
- Header: `АВАРИЯ` or `ПРЕДУПРЕЖДЕНИЕ` exactly as supplied.
- Summary body: the backend-owned operator summary text. Individual
  `ReadinessBlockerRow` atoms may be used in a standalone drill-down, but they
  cannot be attached to this atomic card until a reviewed revisioned blocker
  collection implements the owner-bound transaction contract. No caller may
  install a free-form blocker QWidget and still claim one-cut composition.
- Footer: live/replay mode, source, r412, source age, transport age.
- Optional action: navigation intent to the reviewed evidence surface. It does
  not acknowledge safety or enable output.

This supports `f36.operator.unsafe_preconditions` and
`f36.operator.safety_recovery` without extending the allowed interaction class.

## Worked example: disconnected attention queue

- The last accepted queue remains present under the conservative presentation
  provided by F36.1.
- Every row keeps its urgent last-known text. The card/footer additionally says
  `НЕТ СВЯЗИ`, names the source, and shows transport age.
- No reading or process heartbeat turns the card back to `НОРМА`; only a newer
  accepted backend cut can do so.

This supports `f36.operator.engine_disconnected`,
`f36.operator.stale_critical_data`, and `f36.operator.replay`.

## Atomic-render rule

A component may re-render an identical revision idempotently. It must reject:

- a lower revision;
- different truth under the same revision;
- an untyped mapping or free-form transport payload.

The containing shell must call one render method with one immutable object. A
pure render plan validates and stages every derived state/text plus each child
baseline. Commit rechecks those baselines before its first mutation. If a child
has advanced independently, the whole card attempt rejects with byte-for-byte
unchanged visible, accessible, and internal parent/child state. The shell must
not update status, body, and footer in separate asynchronous callbacks.
(RULE-DATA-001)

Revisioned body widgets are owner-bound at composition time. Once bound, their
standalone render API and the footer's standalone render API reject. The card
admits only a reviewed typed body whose plan consumes the same immutable
summary object; arbitrary QWidget installation is prohibited. Model-reset
reentry into the card transaction also rejects.

## First-presentation barrier

Binding never grants visibility. A standalone body may already hold r42, but
reparenting it into an unrendered card hides it immediately. Until the card
accepts one coherent cut, it shows only its title, canonical disconnected
status, and explicit unavailable summary; body and footer carry no visible
authority. The first valid r43 transaction commits all internal state with
updates suppressed, then reveals body/footer as its last step. A failed plan or
race leaves the barrier byte-for-byte unchanged. An unexpected Qt setter or
deleted-widget failure hides the entire card and permanently fails that
instance closed instead of exposing partial truth.

## Text and fleet-scale rule

Protocol-valid text is untrusted layout input. The visible bounded form keeps
both ends, an explicit truncation marker, and a digest. The full string remains
accessible and selectable via tooltip; it is always rendered as plain text.
Collections at the 2,000-channel bound use a model/view delegate, not one child
widget per entry. C0/C1 and Unicode bidi-format controls are made visible as
`U+NNNN` markers. Tooltips use owned Qt markup around HTML-escaped payloads, so
tags and entities remain literal evidence. (RULE-DATA-002, RULE-A11Y-005)

## Cross-surface consistency

The same state maps to the same Russian label and shape on every F36 surface.
Replay always says `АРХИВНЫЙ ПОВТОР`. Live provenance says `ПРЯМОЙ ЭФИР`.
“No intent” always disables the navigation control. Later POD compositions may
rearrange these atoms but may not alter their state vocabulary, authority,
revision, accessibility, or no-command boundary.

## Anti-patterns

- Constructing a summary from chart readings or `_last_reading_time`.
- Showing an OK card before the first accepted snapshot.
- Hiding stale/disconnected provenance behind a hover-only tooltip.
- Updating the footer to r413 while body rows still show r412.
- Turning backend reason text into a route or command identifier.
- Rendering every fleet item as a QWidget.
- Using color without visible state text/shape.
- Animating a fault or freshness transition.
- Passing raw backend strings to `setToolTip()` or `Qt.ToolTipRole`.
- Accepting a route ID with path syntax, whitespace, controls, or bidi marks.
- Attaching a pre-rendered QWidget body without a revisioned owner contract.
- Rendering an attention body and its card in two caller-managed steps.
- Showing staged pre-bound rows before the card has source/revision/provenance.

## Evidence

Focused tests cover all canonical states, atomic revision rejection, long text,
accessibility metadata, keyboard intent activation, 2,000-item virtualization,
and forbidden dependency/QSS/raw-color scans. Scenario closure still requires
the real composed POD, Windows ONEDIR DPI/NVDA checks, operator decision-time
measurement, and long-session memory evidence.

## Related

- `cryodaq-primitives/operator-snapshot-components.md`
- `patterns/state-visualization.md`
- `patterns/information-hierarchy.md`
- `patterns/real-time-data.md`
- `docs/operator_scenario_baseline.md`

## Changelog

- 2026-07-11 (v1.1.0): Initial atomic F36 operator-snapshot presentation
  pattern, including transactional child preflight and plain-safe Qt tooltip
  semantics after independent verification, plus owner-bound typed body
  transactions and a first-presentation barrier after composed-card
  verification.
