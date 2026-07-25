---
title: Operator Snapshot Components
keywords: F36, operator, snapshot, status, readiness, attention, freshness, provenance, navigation
applies_to: pure Qt presentation of immutable operator-snapshot summaries
status: implemented
implements: src/cryodaq/gui/shell/operator_components/
last_updated: 2026-07-11
references: patterns/operator-snapshot-presentation.md, patterns/state-visualization.md, components/card.md
---

# Operator Snapshot Components

Pure presentation atoms for the F36 Primary Operating Display. They consume
typed immutable summaries from `cryodaq.operator_snapshot`; they do not poll,
decode transport, infer truth, execute routes, or send commands.

## When to use

- Present one canonical six-state backend value.
- Explain a readiness blocker and its required evidence.
- Present a virtualized backend-owned attention queue.
- Show source, revision, mode, source age, and transport age together.
- Offer a reviewed navigation destination without performing the navigation.
- Compose a summary card whose header and footer share one revision.

Do not use these components to derive READY/RECORDING/OK from readings, infer a
route from free text, acknowledge alarms, recover safety, or mutate hardware.

## Anatomy

```text
SnapshotCardShell
┌─────────────────────────────────────────────────────────┐
│ Title                     [shape] CANONICAL STATE       │
│ Backend-owned operator summary text                     │
│                                                         │
│ typed content: blocker rows / virtualized attention     │
│                                                         │
│ [shape] STATE   LIVE or ARCHIVE REPLAY                  │
│ Source + coherent revision                              │
│ Source age + transport age                              │
└─────────────────────────────────────────────────────────┘
```

| Part | Class | Contract |
|---|---|---|
| State label | `CanonicalStatusLabel` | Exactly six states; token color + distinct painted shape + persistent Russian text |
| Freshness footer | `FreshnessProvenanceFooter` | One `SnapshotCut` and `SummaryStatus`; rejects revision regression and same-revision truth replacement |
| Blocker row | `ReadinessBlockerRow` | One `ReadinessBlocker`; shows both reason and required evidence |
| Attention row | `AttentionRow` | One `AttentionItem`; persistent status label and full accessible detail |
| Attention list | `AttentionList` | One `AttentionQueue`; model/delegate virtualization retains every item; becomes card-owner-bound when composed |
| Next action | `NextActionNavigationControl` | Emits a typed `NavigationIntent` only; disabled without an intent |
| Card shell | `SnapshotCardShell` | One typed F36.1 summary plus an optional supported typed body per atomic render; neutral single surface |

## Invariants

1. State is exactly `ok | caution | warning | fault | stale | disconnected`.
   No component adds a seventh state. (RULE-COLOR-002)
2. State is visible in text and shape/position as well as color.
   (RULE-A11Y-002)
3. Fault body text stays `FOREGROUND`; status tokens paint shape/chrome.
   (RULE-A11Y-003)
4. A render accepts one typed immutable backend object. Older revisions and
   different truth under the same revision are rejected in a pure preflight
   plan before replacement. Card commit rechecks its own and every child
   baseline before the first widget mutation; child rejection leaves every
   visible, accessible, and internal field unchanged.
   (RULE-DATA-001)
5. Optional card body content is constructor-bound and typed. The current
   supported composition is `AttentionQueue` + `AttentionList`. Binding gives
   the card a private identity-only owner token; independent body/footer
   renders then reject. Card preflight stages parent, footer, and body plans for
   the same summary object and revision. There is no public `set_content()`.
6. The card starts behind a presentation barrier: title, disconnected status,
   and explicit `Данные недоступны` are visible, while any pre-rendered bound
   body and the empty footer remain hidden. The first successful transaction
   commits parent/body/footer truth and reveals body/footer only as the final
   visible step. Failed/stale/racing first renders preserve the hidden barrier.
   Any unexpected Qt mutation/reveal failure hides the whole card, marks it
   failed closed, and prohibits another render.
7. Long protocol-valid strings retain a visible prefix and suffix plus a
   digest/explicit truncation marker. C0/C1 and bidi-format characters become
   visible `U+NNNN` markers. The complete safe representation remains in
   accessible description; tooltips use owned Qt rich-text chrome containing
   only HTML-escaped payload. Backend markup is always displayed literally.
8. `AttentionList` is virtualized. It never creates one QWidget per fleet item.
   Its Qt model and replacement operation are owner-locked; callers cannot
   substitute another model to bypass queue revision/truth checks.
9. The card has one painted `SURFACE_CARD` surface, symmetric `SPACE_5`
   padding, `RADIUS_LG`, and no shadow. (RULE-SURF-001, RULE-SURF-003,
   RULE-SURF-010)
10. The navigation control has strong keyboard focus, a visible `FOCUS_RING`,
   and Space/Enter activation. It emits intent only and owns no router or
   command callback. (RULE-INTER-001, RULE-INTER-003)
11. New code uses `theme` tokens, Qt palettes, and the package painter helpers.
   It contains no raw color literal or per-widget stylesheet.
12. All transitions snap. There is no pulse, fade, count-up, or layout motion.
    Fault presentation is immediate. (RULE-DATA-009, RULE-INTER-006)
13. Navigation identifiers match `[a-z][a-z0-9_-]*`, use at most 64 ASCII
    bytes, and contain no path syntax. Navigation copy is NFC-normalized,
    bounded to 256 UTF-8 bytes, and rejects markup delimiters, C0/C1, and bidi
    format controls.

## Public API

```python
CanonicalStatusLabel.set_state(state: OperatorPresentationState) -> None
FreshnessProvenanceFooter.render(cut: SnapshotCut, status: SummaryStatus) -> None
ReadinessBlockerRow.render(blocker: ReadinessBlocker) -> None
AttentionRow.render(item: AttentionItem) -> None
AttentionList.render(queue: AttentionQueue) -> None
NextActionNavigationControl.set_intent(intent: NavigationIntent | None) -> None
SnapshotCardShell.render(summary: OperatorSummary) -> None
```

`AttentionList.render()` is public only while the list is standalone. After
`SnapshotCardShell(..., content=attention)` binds it, only the card transaction
may plan or commit its queue. The same rule applies to the card-owned footer.
Future revisioned body types must implement the same private plan / can-commit /
commit owner contract before they can be admitted; arbitrary QWidget content
is rejected.

A pre-rendered standalone list may be bound as a staged baseline, but its rows
immediately become hidden. They are not operator-visible authority until a
successful card render accepts the same or newer `AttentionQueue` and reveals
all three card regions at one revision.

`NextActionNavigationControl.navigation_requested` emits the exact immutable
`NavigationIntent`. A shell adapter may interpret it later; this primitive
never imports routes, ZMQ, REST, SafetyManager, or command helpers.

## States

| State | Visible text | Shape | Token |
|---|---|---|---|
| ok | `НОРМА` | filled circle | `STATUS_OK` |
| caution | `ВНИМАНИЕ` | filled triangle | `STATUS_CAUTION` |
| legacy warning input | `ВНИМАНИЕ` | filled triangle | `STATUS_CAUTION` |
| fault | `АВАРИЯ` | filled square / 3px list edge | `STATUS_FAULT` |
| stale | `УСТАРЕЛО` | hollow circle | `STATUS_STALE` |
| disconnected | `НЕТ СВЯЗИ` | dashed diamond | `STATUS_STALE` |

## Examples

```python
attention = AttentionList()
card = SnapshotCardShell("Требует внимания", content=attention)
card.render(snapshot.attention)  # header + rows + footer commit one cut

readiness_card = SnapshotCardShell("Готовность")
readiness_card.render(snapshot.readiness)  # summary text + footer, no arbitrary body

next_step = NextActionNavigationControl(
    NavigationIntent(
        intent_id="inspect-alarm",
        destination="alarm_evidence",
        operator_text="Открыть доказательства тревоги",
    )
)
```

## Accessibility and performance evidence

The focused offscreen suite verifies all six accessible state names, complete
accessible long text, hostile markup/entities/control/bidi exposure, escaped
Qt tooltips, Space activation, visible focus
ownership, fail-closed no-intent state, and full attention model access. The
2,000-item queue test measures model replacement under the 16 ms frame-work
budget on the local verification host. Real Windows ONEDIR DPI at 100%, 125%,
150%, and 200%, NVDA, contrast, and 12-hour memory evidence remain open gates.

## Common mistakes

1. Building a `QLabel` with green text and no shape/state word.
2. Passing a presentation-overlaid or locally synthesized object as authority.
3. Reusing one revision with changed text because “only wording changed.”
4. Creating 2,000 child widgets for an attention queue.
5. Eliding away the evidence or provenance without an accessible full value.
6. Connecting `navigation_requested` directly to hardware or generic commands.
7. Adding widget-local QSS/raw hex instead of the shared token painter.
8. Putting a second painted card inside `SnapshotCardShell`.
9. Mutating a card label before a child footer has accepted the same revision.
10. Returning raw backend strings through `Qt.ToolTipRole`.
11. Calling `AttentionList.render()` separately after binding it to a card.
12. Reintroducing a generic `set_content(QWidget)` escape hatch.
13. Revealing pre-rendered rows before the first coherent card/footer cut.

## Related

- `patterns/operator-snapshot-presentation.md`
- `patterns/state-visualization.md`
- `patterns/real-time-data.md`
- `components/card.md`
- `components/button.md`

## Changelog

- 2026-07-11 (v1.1.0): Initial implemented F36 pure presentation atoms;
  transactional card preflight, escaped tooltips, and strict navigation IDs
  included after independent verification; owner-bound typed body transactions
  and a cold-start presentation barrier added after composed-card verification.
