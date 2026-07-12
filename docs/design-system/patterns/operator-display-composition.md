---
title: Primary Operator Display Composition
keywords: F36, POD, shift briefing, atomic composition, attention, replay, navigation
applies_to: composing all eight operator-snapshot summaries into the Primary Operating Display
status: implemented composition; shell and operator evidence open
implements: src/cryodaq/gui/shell/views/operator_display.py
last_updated: 2026-07-11
references: patterns/operator-snapshot-presentation.md, patterns/information-hierarchy.md, accessibility/keyboard-navigation.md, governance/performance-budget.md
---

# Primary Operator Display Composition

## Problem and boundary

The Primary Operator Display (POD) answers four bounded questions from one
immutable `OperatorSnapshot`: may work continue, what is happening, what needs
attention, and what evidence should be inspected next. It is a presentation
and navigation surface only. It does not poll transport, acknowledge an alarm,
recover Safety, change an experiment, or command hardware.

This pattern does not close the twelve F36 operator scenarios by itself. Those
scenarios include later destination behavior, acknowledgement requests,
recovery preparation, handover writing, support capture, and measured human
performance. POD tests cover only the truth and navigation subset they
actually exercise.

## Information hierarchy

1. The page title, source/revision provenance, and a persistent
   stale/disconnected/replay banner establish whether the cut is current.
2. `Можно ли продолжать?`, `Что происходит?`, and the highest-priority
   attention reason form the first scan path. Backend-owned fault or warning
   truth outranks normal cards.
3. Data integrity, plant, infrastructure, cooldown, and support evidence stay
   visible as supporting cards. Provenance remains subordinate but never
   hover-only.
4. `Следующий безопасный шаг` is a typed navigation intent. It never performs
   the destination action.

Quiet normal state uses neutral card surfaces. Canonical state text and shape
remain visible; no decorative status color competes with an exception.

## Cold-start and irreversible failure barrier

Before the first coherent snapshot, every card presents explicit unavailable
truth and the root says that readiness, recording, and safety are unavailable.
No child body or provenance from an earlier object is visible.

An unexpected Qt mutation failure permanently retires that POD instance. The
truth-bearing page is detached, hidden, and disabled behind an explicit
non-authoritative integrity-failure barrier. Calling ordinary `show()` may
show the barrier, but cannot reveal partially committed cards. Recovery means
constructing a fresh display from a fresh accepted snapshot, not reusing the
failed instance.

## Root transaction and ownership

All eight cards bind to one private POD render owner at construction time.
Unbound `SnapshotCardShell` instances retain their standalone public `render`
API; a card composed into the POD rejects it. Only the root may plan, recheck,
and commit each child with the exact owner token.

The root transaction:

1. validates one typed immutable snapshot and revision ordering;
2. prepares all child, facts, banner, provenance, accessibility, navigation,
   and attention-geometry plans without changing widgets;
3. rechecks the complete root and child baselines;
4. suppresses updates and commits all eight cards and root fields;
5. verifies every card summary/revision/state/footer/body plus every root text,
   accessibility, and navigation field after synchronous Qt signals return;
6. accepts the root snapshot only after that coherence check passes.

`AttentionList.modelReset` is synchronous. A listener cannot independently
render a sibling card while the root is committing. Any other synchronous
mutation detected by the post-commit check enters the irreversible failure
barrier. This is atomic presentation, not rollback: Qt mutations are not
reliably reversible after an arbitrary deleted-widget failure.

## Attention projection and geometry

The POD deterministically sorts by canonical state precedence, observation
time, then stable identity and projects at most eight items. The list is
virtualized. A row is exactly two `ROW_HEIGHT` lines: title/state and full
bounded detail. The viewport always fits at least the complete most-urgent
row, shows at most four complete rows, and scrolls for items five through
eight. The adjacent count states both projected and total queue size.

Detail is never removed merely to reduce card height. Full hostile text remains
available through the atom's accessible text and safe tooltip boundary.

## Navigation, replay, and handover

Section controls emit bounded legacy route keys and typed navigation intents
only. Backend text never becomes a route. Handover navigation requires the
exact reviewed backend reason code `handover_pending`; generic `caution` plus
recording is insufficient.

Replay keeps the prominent archive banner and chooses analysis as the next
inspection step. Section routes intentionally remain navigation-only in this
composition. Before shell cutover, every replay destination must prove that
live acknowledgement or control affordances are disabled or explicitly
observational. The POD alone does not make those destination panels safe.

## Accessibility and performance

- Visual order and Qt construction order match the information hierarchy.
- Every navigation control has persistent Russian copy, an accessible name,
  visible focus, and Enter/Space behavior from the shared atom.
- State uses canonical text and painted shape in addition to color.
- Bidi/control characters are visible rather than allowed to alter layout.
- Attention uses model/view virtualization and a hard eight-item projection.
- The local 2,000-item projection/render regression requires a median below
  the canonical 16 ms main-thread budget; a separate 50 ms maximum guards
  noisy hosts without redefining the acceptance budget.

Open evidence: real Windows ONEDIR rendering, 100/125/150/200% DPI,
keyboard-only whole-shell traversal, NVDA Russian announcements, screenshots,
long-session memory, and measured operator decision time.

## Anti-patterns

- Independently rendering any card after it is bound to the POD.
- Treating a root `_committing` flag as sufficient while child render APIs
  remain writable.
- Re-showing partially committed cards after an unexpected Qt failure.
- Sizing a two-line attention row with one `ROW_HEIGHT`.
- Claiming all twelve scenarios from locally synthesized snapshots.
- Inferring handover from generic severity.
- Treating replay navigation as permission to use live controls.
- Measuring only on a developer Mac and calling Windows/DPI/NVDA gates closed.

## Worked examples

### Disconnected cold start

The banner says `НЕТ СВЯЗИ`; readiness and recording remain unknown; every card
contains unavailable text. Navigation may open diagnostics but cannot imply
that a diagnostic panel restored authority.

### Recorded run with a non-handover caution

The active experiment remains visible. A generic caution is ranked by its
actual domain state and routes to that evidence. The journal/handover route is
selected only when the accepted attention summary includes
`handover_pending`.

## Related

- `patterns/operator-snapshot-presentation.md`
- `cryodaq-primitives/operator-snapshot-components.md`
- `docs/operator_scenario_baseline.md`
- `governance/performance-budget.md`

## Changelog

- 2026-07-11 (v1.2.0): Initial composed POD contract with root ownership,
  post-commit coherence, irreversible failure barrier, complete attention-row
  geometry, honest scenario scope, and explicit replay shell-cutover gate.
