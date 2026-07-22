---
title: BottomStatusBar
keywords: status-bar, bottom-bar, connection, safety-state, uptime, disk, data-rate, local-time
applies_to: bottom chrome strip showing passive system-level evidence
status: active
implements: src/cryodaq/gui/shell/bottom_status_bar.py
last_updated: 2026-07-20
references: rules/color-rules.md, rules/data-display-rules.md, rules/content-voice-rules.md, governance/change-impact.md
---

# BottomStatusBar

The shipped `BottomStatusBar` is the thin, persistent technical strip at the
bottom of the v2 shell. Its active contract is the production implementation,
not the older proposed Engine/Safety/ZMQ four-field mock-up.

The bar presents six fields in this order:

1. current SafetyManager state supplied by the host;
2. launcher/UI uptime measured from this widget's construction;
3. free space for the configured data directory;
4. the latest data rate supplied by the host;
5. recent-reading connection evidence supplied by the host;
6. the GUI host's current local time.

This is supporting evidence, not the primary alarm or verified-OFF surface.
Nothing in the bar grants control authority.

## When to use

- Instantiate once in `MainWindowV2` and keep it visible across shell views.
- Use it for passive, glanceable technical evidence that must not replace the
  primary physical vitals, alarm list, source controls, or experiment state.
- Keep values static between updates; do not animate, cycle, or hide them.

Do not use it for per-panel state, transient action feedback, alarm
acknowledgement, or any command.

## Shipped anatomy

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ ● safety │ Лаунчер 00:00:00 │ Диск 120 ГБ │ 10 изм/с │ ● Подключено │ 14:32:15 │
└──────────────────────────────────────────────────────────────────────────────┘
```

| Part | Owner and provenance | Current presentation |
|---|---|---|
| Safety | `MainWindowV2` calls `set_safety_state` from backend state | lowercase state ID with a dot glyph |
| Launcher uptime | widget-local monotonic clock | `Лаунчер HH:MM:SS` |
| Data disk | `MainWindowV2` passes fresh, incarnation-bound `disk_monitor` evidence | `Диск N ГБ`; stale or disconnected history is marked explicitly |
| Data rate | last value passed to `set_data_rate` | integer `изм/с` |
| Connection | host calls `set_connected` from recent-reading evidence | Russian connected/disconnected label |
| Clock | widget-local wall clock | local `HH:MM:SS` |

Separators are visible `│` glyphs using `BORDER_SUBTLE`. The rightmost clock is
pushed to the far edge by a stretch.

## Invariants

1. The strip is exactly `BOTTOM_BAR_HEIGHT` (28 px), uses `SURFACE_PANEL`, and
   has a one-pixel `BORDER_SUBTLE` top edge.
2. Safety IDs remain lowercase (`safe_off`, `ready`, `run_permitted`,
   `running`, `fault_latched`) so the display matches authoritative log/state
   vocabulary.
3. Missing safety evidence renders `● —` in muted text. Unknown states remain
   muted; they never become green.
4. `running` and `run_permitted` use `ACCENT`, because activity or permission is
   not evidence of health. `ready` uses `STATUS_INFO`.
5. Any safety state containing `fault` uses `STATUS_FAULT`.
   Exact `fault_latched` also sounds immediately and repeats the application
   beep every three seconds until the state changes or becomes unavailable.
6. Disk free space below 10 GiB uses `STATUS_FAULT`; 10 GiB through less than
   50 GiB uses `STATUS_CAUTION`; 50 GiB or more is muted technical information.
7. Connected and disconnected states include both text and a dot glyph. The
   connected color is `STATUS_OK`; disconnected is `STATUS_FAULT`.
8. “Connected” currently means the host has recent-reading evidence. It is not
   an independent ZMQ heartbeat, engine-process proof, persistence proof, or
   verified-OFF proof.
9. Disconnect does not erase the last supplied rate. The retained number is
   last-known evidence and must not be interpreted as current without the
   adjacent connection state.
10. The clock is local host time in `HH:MM:SS`. The shipped widget does not
    display a timezone or UTC offset.
11. The bar is passive and has no click, hover-command, or keyboard-command
    behavior.

## Safety state mapping

| Backend text | Token | Meaning |
|---|---|---|
| missing/empty | `TEXT_MUTED` | no current safety evidence |
| contains `fault` | `STATUS_FAULT` | fault evidence; exact `fault_latched` repeats the beep |
| contains `running` | `ACCENT` | current activity, not health |
| contains `permitted` | `ACCENT` | authorization, not health |
| contains `ready` | `STATUS_INFO` | informational readiness, not health |
| any other value | `TEXT_MUTED` | bounded unknown state |

Substring matching is the current implementation. It is intentionally
fail-conservative for green: no safety-state string maps to `STATUS_OK`.

## Public API

The active public setter contract is exactly:

```python
class BottomStatusBar(QWidget):
    def set_safety_state(self, state: str | None) -> None: ...
    def set_data_rate(self, rate_per_sec: float) -> None: ...
    def set_disk_evidence(
        self,
        value: float,
        *,
        source: str,
        state: str,
    ) -> bool: ...
    def set_connected(
        self,
        connected: bool,
        label: str | None = None,
    ) -> None: ...
```

There is no shipped `StatusItem`, `set_engine`, `set_safety`, `set_heartbeat`,
or `set_time` API. Documentation and tests must not imply otherwise.

## Update ownership and failure behavior

- A one-second widget timer updates only uptime and local time.
- Safety, rate, and connection change only through the public setters.
- Disk evidence is accepted only from the exact `disk_monitor` source when its
  typed state agrees with the numeric threshold. Invalid, negative, non-finite,
  foreign-source, or state/value-inconsistent input is rejected without
  replacing the last accepted evidence.
- `MainWindowV2` owns disk freshness and bridge-incarnation binding. On expiry
  or disconnect it retains the last numeric value only with an explicit
  stale/disconnected marker; no retained number is presented as current.
- The last data rate is not cleared or marked stale on disconnect.
- The connection field receives already-derived host evidence; it cannot
  distinguish a disconnected socket from a live transport with silent
  acquisition.
- The fault beep timer is owned by the widget and stops on every non-latched or
  missing safety state.

## Accessibility and operator trade-offs

Better:

- all six values stay visible in one fixed, quiet strip;
- lowercase safety text, Russian connection text, and dot glyphs provide
  non-color cues;
- activity no longer trains operators to interpret green as “running”;
- caution and fault disk thresholds use the canonical three-rung safety
  language.

Worse or still open:

- status color is applied to body text rather than to a separate high-contrast
  shape; physical contrast/NVDA evidence remains open;
- the clock is proportional, has no timezone, and may jitter;
- the rate can remain last-known without its own explicit stale cue;
- disk evidence still depends on the backend monitor and GUI transport path;
- recent-reading connection evidence is weaker than an independent transport
  heartbeat;
- audible alarm ownership is not yet consolidated across all producers.

No future improvement may hide these fields or replace an explicit unavailable
state with optimistic green. A desired heartbeat/timezone redesign belongs in
`GUI_MIGRATION_INVENTORY.md` and requires live wiring plus tests before it can
replace this contract.

## Responsive and performance evidence

The bar is a single non-wrapping row. Its supported geometry is the shell's
minimum width and above; it is not a small-screen responsive layout. At the
supported floor, every current value and status must remain visible. If future
fields make that impossible, low-priority technical fields may move into an
accessible secondary row or deliberate detail surface, but current
safety/connection/provenance evidence must not be clipped without a complete
keyboard-accessible path.

The one-second timer bounds ordinary presentation updates. No task, thread, or
queue is created per tick. Full Windows ONEDIR high-DPI, long-session memory,
screen-reader, and operator-night-shift evidence remains open.

## Regression evidence

- `test_ready_is_informational_not_healthy` prevents readiness from becoming a
  green health assertion.
- `test_activity_state_uses_accent_without_claiming_healthy` locks running and
  run-permitted activity to `ACCENT`.
- `test_disk_space_thresholds_use_canonical_safety_rungs` covers both disk
  boundaries.
- fault-beep tests cover exact activation, immediate/repeating timer ownership,
  idempotent repeated updates, and stop-on-state-change behavior.
- documentation freshness must assert that this setter list exactly matches the
  live production setter list and that no fictional `StatusItem` API returns.

## Common mistakes

1. Calling launcher/UI uptime “engine uptime.”
2. Calling recent-reading evidence a ZMQ heartbeat.
3. Treating `ready`, `running`, or `run_permitted` as healthy/safe.
4. Clearing a retained value merely because freshness is unknown.
5. Presenting a retained rate or disk number as current without adjacent
   freshness/connection truth.
6. Adding a seventh field without checking the supported minimum-width truth
   path.
7. Claiming timezone, monospace clock, independent heartbeat, or stale markers
   before they are implemented and tested.

## Related components

- `cryodaq-primitives/top-watch-bar.md` — primary physical vitals and provenance
- `cryodaq-primitives/alarm-badge.md` — alarm attention
- `cryodaq-primitives/tool-rail.md` — persistent navigation chrome
- `governance/change-impact.md` — better/worse review record
- `GUI_MIGRATION_INVENTORY.md` — open heartbeat, provenance, accessibility, and
  performance work

## Changelog

- **2026-07-20 (v4.0.3)** — reconciled the active specification to the shipped
  six-field widget, removed the fictional `StatusItem`/four-setter API,
  documented activity and readiness colors, and recorded the open heartbeat,
  stale-provenance, accessibility, and timer-performance gaps.
- **2026-04-17** — initial proposed four-field Engine/Safety/ZMQ/time
  specification; superseded as an active contract by the v4.0.3 reconciliation.
