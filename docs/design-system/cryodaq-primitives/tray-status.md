---
title: Tray Status
keywords: tray, status, coarse, non-authoritative, alarm, unknown, provenance, shutdown
applies_to: system tray icon and tooltip
status: canonical
last_updated: 2026-07-20
version: 4.0.3
references: patterns/operator-evidence-and-retention.md, patterns/state-visualization.md, cryodaq-primitives/alarm-panel.md
---

# Tray Status

The tray is a coarse attention and navigation surface. It is never the
authoritative operating display and never closes a safety, readiness, alarm,
verified-OFF, persistence, or laboratory gate.

## Required truth contract

1. The tray combines only evidence whose provenance and freshness are known.
2. Missing alarm authority is **unknown**, not zero alarms. An absent,
   unavailable, stale, or malformed alarm count cannot render a healthy tray.
3. A green/healthy tray means only that the limited inputs accepted by the
   tray's current mapping reported no exception. It does not prove
   `verified_off`, READY preconditions, experiment health, complete channel
   coverage, persistence, or absence of hazards.
4. `safe_off` means there is no RUN authority. It is not independent evidence
   that the final element is physically OFF.
5. Fault and disconnect states fail visibly with icon shape and Russian text;
   color is never the only cue.
6. The tooltip names connection, mapped safety state, alarm count, data
   freshness, reporting health, and the limited/coarse nature of the view.
   It keeps the disclaimer first and fits the Windows 127 UTF-16-unit bound.
7. Clicking the tray may open or focus the main window. It must not acquire
   source-control authority or expose a one-click hazardous action.
8. Once launcher shutdown is requested, the tray remains visible until every
   owned process, thread, queue, descriptor, capability, and event loop is
   proven terminal. Incomplete settlement is fault-colored with Russian text
   and a non-color notification; it cannot reuse a healthy or disconnected
   presentation.

## State precedence

| Evidence | Tray presentation |
|---|---|
| Shutdown settling | caution icon and explicit controlled-shutdown text |
| Any shutdown owner remains unsettled | fault icon and explicit incomplete-shutdown text; launcher remains alive and locked |
| Disconnected engine or unknown required authority | unavailable/caution text; never healthy |
| Fault-latched/fault input or active fault attention | fault |
| Connected, fresh accepted inputs, no reported exception | coarse healthy summary |

Acknowledged-active hazards may leave the audible/attention count, but remain
visible in the authoritative alarm panel until backend resolution. The tray
must not imply that acknowledgement cleared the underlying condition.

## Current implementation status

`src/cryodaq/gui/tray_status.py` preserves unavailable or malformed connection,
alarm, freshness, and reporting inputs as unknown. Unknown, stale,
disconnected, or reporting-fault evidence renders caution, while a known
active alarm or safety fault takes fault precedence. Healthy is available only
for exact connection, accepted safety, zero-alarm, fresh-data, and
known-good-reporting truth. Backend safety enums map to compact Russian text;
unknown private values are not leaked into the operator tooltip.

The launcher currently has no authoritative alarm-count feed and therefore
passes unknown. It also requires an observed reading before data can be fresh
and passes the periodic-reporting fault latch into the resolver. Its tray
deliberately cannot become healthy until alarm wiring exists. This is
fail-visible behavior, not evidence that the wiring gate is closed. The
software contract and non-color silhouette tests are present; authoritative
wiring and Windows release-candidate visual evidence remain open.

During normal launcher exit, shutdown presentation temporarily takes precedence
over the coarse runtime resolver. A failed attempt keeps the same tray owner
visible, emits one bounded notification, retains exact resource handles and the
single-instance lock, and schedules a bounded retry. The tray hides only after
all owners are terminal and Qt exit has been requested. This presentation says
nothing about physical final-element state and does not close a hardware gate.

## Verification

- Unknown alarm input never produces healthy presentation.
- Unknown/stale data or unknown/faulted reporting never produces healthy.
- `safe_off` text never says or implies verified physical OFF.
- Icon, text, and tooltip communicate fault/disconnect without color alone.
- Tooltip remains at most 127 UTF-16 units and retains its disclaimer first.
- Tray actions cannot send control commands.
- Shutdown caution remains visible while owners settle; any incomplete owner
  becomes fault-visible without quitting the application or releasing the lock.
- Retry exercises only unresolved owners and never respawns engine or assistant
  after the shutdown latch.
- Windows system-tray visual behavior is verified on the release candidate.

## Changelog

- 2026-07-17 (v4.0.1): Initial canonical coarse/non-authoritative tray
  contract; unknown alarm authority is explicitly distinct from zero.
- 2026-07-17 (v4.0.1): Implemented fail-visible unknown/malformed handling,
  distinct check/triangle/octagon silhouettes, and explicit coarse tooltip;
  retained the authoritative launcher wiring and Windows visual gates.
- 2026-07-17 (v4.0.2): Added freshness/reporting truth, Russian safety mapping,
  startup-unknown handling, and a Windows-bounded disclaimer-first tooltip.
- 2026-07-17 (v4.0.2): Added fail-visible, lock-retaining shutdown precedence;
  incomplete resource settlement remains visible and retryable instead of
  disappearing behind application exit.
