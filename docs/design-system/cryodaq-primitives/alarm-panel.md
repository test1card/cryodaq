---
title: AlarmPanel
keywords: alarms, acknowledge, v2, exact identity, fail-open, K1 safety
applies_to: YAML-driven phase-aware alarm overlay
status: active
implements: src/cryodaq/gui/shell/overlays/alarm_panel.py
last_updated: 2026-07-16
references: rules/data-display-rules.md, rules/color-rules.md, patterns/operator-evidence-and-retention.md
---

# AlarmPanel

K1-critical operator surface for the single authoritative phase-aware alarm
engine. The retired threshold-alarm table and `Reading` ingress MUST NOT be
restored: the engine no longer publishes that protocol, and a second GUI truth
owner would permit divergent counts and name-only acknowledgement.

## Operator contract

- Poll `alarm_v2_status` while connected and retain the last accepted rows on
  disconnect or transport failure.
- Accept a snapshot only when it has a non-empty engine instance, a
  non-negative integer revision, non-empty string alarm identifiers, mapping
  rows, and exact activation identifiers for every actionable row.
- A malformed snapshot MUST retain last-known evidence, revoke ACK authority,
  and show an explicit unavailable/stale cue. It MUST NOT partially apply,
  silently filter rows, erase the table, or raise into the event loop.
- Ignore lower revisions from the same engine instance.
- Capture the accepted engine instance and activation identifier in each row's
  ACK callback. A delayed click MUST NOT substitute a newer activation with the
  same alarm name.
- ACK changes attention and audible responsibility only. It never clears the
  hazard or invokes recovery/control. Acknowledged evidence remains visible
  until the authoritative engine removes it.
- Replay/read-only and disconnected states retain evidence but disable ACK.

## Presentation

The table presents severity, stable identifier, full message (tooltip when
visually abbreviated), channels, elapsed time, and action/state. Severity has a
Russian text cue as well as color. `WARNING` and `CAUTION` share the canonical
caution presentation; `CRITICAL` and unknown severity use fault presentation.
Acknowledged rows are muted and marked `✓`, but remain readable.

The cooldown footer is evidence, not a safety-health verdict. Active monitoring
uses `ACCENT`, deviations use caution/fault, and completed/within-threshold
comparisons use `ACCENT` rather than safety green. Unknown backend state or
missing decision evidence is explicit and neutral; it MUST NOT render as
`НОРМА` or `STATUS_OK`.

## Design-system tradeoff record

1. **Better:** one authoritative table eliminates divergent alarm truth and
   name-only ACK; malformed data can no longer erase evidence or grant action.
2. **Worse:** operators lose the obsolete threshold table and see retained
   last-known rows during protocol faults rather than an apparently fresh list.
3. **Justification:** exact activation identity and persistent evidence align
   with fail-closed acknowledgement and operator-centric anomaly review.
4. **Mitigation:** an explicit unavailable cue distinguishes retained evidence;
   focused tests cover delayed ACK, malformed nested rows, disconnect, replay,
   acknowledged retention, and non-green cooldown completion.
5. **Revisit trigger:** restore or replace an additional table only if a new
   authoritative producer is designed with stable identity, revisioning, and a
   reviewed migration contract; revise neutral cooldown treatment only with
   validated decision metrics and operator evidence.

## Host integration

`MainWindowV2` constructs the panel eagerly, registers it under `alarms`, wires
`v2_alarm_summary_changed` and `v2_alarm_availability_changed` to the top watch
bar, and mirrors connection state from its status tick. The panel is the sole
validated owner of alarm count, worst presentation severity, revision, and
availability. Generic measurement readings are not routed to the panel.

## Changelog

- **2026-07-16 (v2.0.0):** retired obsolete v1 GUI/protocol ingress; made v2 the
  sole truth owner; added whole-snapshot validation, retained-evidence failure
  cues, exact ACK identity, and neutral cooldown evidence semantics.
- **2026-07-15 (v1.3.0):** required exact engine-instance/activation identity
  for v2 ACK and retained acknowledged rows.
