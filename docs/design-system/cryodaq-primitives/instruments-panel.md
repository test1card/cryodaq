---
title: InstrumentsPanel
keywords: instruments, sensor diagnostics, liveness, adaptive timeout, health score, card grid, K2 pre-experiment
applies_to: Instrument card grid + sensor diagnostics overlay (merged)
status: active
implements: src/cryodaq/gui/shell/overlays/instruments_panel.py (Phase II.8); legacy src/cryodaq/gui/widgets/instrument_status.py and sensor_diag_panel.py retained (DEPRECATED) until Phase II.13
last_updated: 2026-07-14
references: rules/data-display-rules.md, rules/color-rules.md, cryodaq-primitives/alarm-panel.md (SeverityChip reuse), components/card.md
---

# InstrumentsPanel

K2-critical overlay. The pre-experiment verification surface: operator opens it once before starting any measurement to confirm every instrument is live and every sensor is healthy. Two sections — instrument cards and sensor diagnostics — merged into a single overlay (both ship/unship together, both consume the readings feed).

## Rebuild scope (II.8)

Two legacy widgets folded into one overlay:

- `src/cryodaq/gui/widgets/instrument_status.py` — card grid + 1 s liveness timer + adaptive timeout.
- `src/cryodaq/gui/widgets/sensor_diag_panel.py` — 7-column health table + 10 s polling + summary.

Changes on merge:

- Unicode circle indicator glyph replaced by `_StatusIndicator` (painted `QFrame` with QSS `border-radius`). No glyph dependency, no font fallback surprises.
- Summary emoji replaced by `SeverityChip` widgets imported from `shell/overlays/alarm_panel.py` (reuse the exact DS status pill pattern). Labels become plain Russian («ОК / ПРЕД / КРИТ»).
- Row tints migrated from hardcoded `QColor(r, g, b, a)` to `QColor(theme.STATUS_*)` with an alpha setter. No raw rgba.
- `apply_panel_frame_style` helper and `TEXT_MUTED` / `TEXT_PRIMARY` deprecated tokens replaced by direct DS QSS + `FOREGROUND` / `MUTED_FOREGROUND`.
- `set_connected(bool)` gates 10 s diag polling only — cards keep drawing stale indicators by design.

Adaptive liveness constants are unchanged (verified against real hardware — do NOT tune):

- `_TIMEOUT_MULTIPLIER = 5.0`
- `_MIN_TIMEOUT_S = 10.0`
- `_DEFAULT_TIMEOUT_S = 300.0`
- `_MIN_READINGS_FOR_ADAPTIVE = 3`

Instrument cards use the GUI-thread-owned `DescriptorStore` as their sole
identity authority. A card is created or updated only from an exact
`DescriptorView` whose identity is `authoritative`, transport is `connected`,
and `(channel_id, instrument_id, unit)` exactly matches the `Reading`.
`Reading.instrument_id` remains driver provenance and a descriptor-integrity
check; by itself it never attributes a card. Channel prefixes, vendor/model
names, and LakeShore `Т1…Т24` ranges are not identity fallbacks.

Descriptor absence is shown as «Идентификация прибора недоступна:
описание канала отсутствует». A refused, malformed, mismatched, or
capacity-exhausted identity is shown as «Идентификация прибора
недоступна: описание канала отклонено». Both strings are fixed and
bounded: raw channel, vendor, diagnostic, and payload text is never echoed.

## Tokens

- `SURFACE_WINDOW` — overlay root background.
- `SURFACE_CARD` — instrument card + diag section backgrounds.
- `SURFACE_MUTED` — table header background.
- `BORDER_SUBTLE` — section + card + table + indicator outline.
- `FOREGROUND` — titles, card name, card status text, diag cell text.
- `MUTED_FOREGROUND` — last-response / counters / empty-state / summary placeholder.
- `STATUS_OK` — healthy card border + indicator fill + health cell text (≥80).
- `STATUS_CAUTION` — warning card border + indicator fill + health cell text (50–79) + row tint base.
- `STATUS_FAULT` — fault card border + indicator fill + health cell text (<50) + row tint base.
- `STATUS_STALE` — cold-start indicator before first reading.
- `STATUS_INFO` / `STATUS_WARNING` — `SeverityChip` summary pills.
- Spacing: `SPACE_1 / SPACE_2 / SPACE_3 / SPACE_4`.
- Radii: `RADIUS_MD` (sections + cards), `RADIUS_SM` (table + chip).
- Typography: `FONT_BODY` throughout; `FONT_MONO` for card counters + diag numeric cells.

No hardcoded hex outside DS tokens. No emoji (including `⬤ ✓ ⚠ ✘`). No deprecated tokens or helpers.

## Layout

```
┌────────────────────────────────────────────────────────────────┐
│ ПРИБОРЫ И ДИАГНОСТИКА                                          │
├────────────────────────────────────────────────────────────────┤
│ ┌ Card: Приборы ─────────────────────────────────────────────┐ │
│ │ Ожидание данных приборов… (empty state)                    │ │
│ │ ┌────┐ ┌────┐ ┌────┐    (3-column QGridLayout)             │ │
│ │ │ ○  │ │ ○  │ │ ○  │                                       │ │
│ │ │LS1 │ │LS2 │ │K1  │                                       │ │
│ │ │...  │ │...  │ │...  │                                    │ │
│ │ └────┘ └────┘ └────┘                                       │ │
│ └────────────────────────────────────────────────────────────┘ │
│ ┌ Card: ДИАГНОСТИКА ДАТЧИКОВ     [18 ОК][1 ПРЕД][1 КРИТ] ───┐  │
│ │ Канал | T(K) | Шум | Дрейф | Выбр. | Корр. | Здоровье    │  │
│ │  ...                                                      │  │
│ └───────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

- Root: `QVBoxLayout`, outer margins `(SPACE_4, SPACE_3)`, spacing `SPACE_3`.
- `QScrollArea` wraps the two inner cards so they share vertical scroll.
- Instrument card: 240×140 minimum size, `Preferred / Fixed` size policy.
- Indicator: 12 px `_StatusIndicator` painted circle with `border-radius: 6`.

## Public API

```python
class InstrumentsPanel(QWidget):
    def on_descriptor_reading(
        self, reading: Reading, view: DescriptorView | None
    ) -> None: ...
    def set_connected(self, connected: bool) -> None: ...

    # Sensor diag — tests / host can bypass polling
    def update_diagnostics(self, payload: dict) -> None: ...
    def set_diagnostics(self, channels: dict, summary: dict) -> None: ...

    # Accessors
    def get_instrument_count(self) -> int: ...
    def get_sensor_summary_text(self) -> str: ...  # plain — no emoji
```

## Host Integration Contract

`MainWindowV2` wires:

1. Lazy construction via `_OVERLAY_FACTORIES["instruments"]`.
2. `_tick_status` mirror into `set_connected(bool)`.
3. `_ensure_overlay("instruments")` replay — sets the connected flag from `_last_reading_time` on first open.
4. `dispatch_qualified_reading` ingests the descriptor, reads the resulting
   frozen `DescriptorView`, dispatches the bare reading to legacy sinks exactly
   once, then calls `on_descriptor_reading(reading, view)` exactly once.
   `_dispatch_reading` never feeds the instrument-card grid directly.

See `src/cryodaq/gui/shell/main_window_v2.py` for the canonical wiring.

## Accessibility evidence

- Unavailable and refused states use fixed Russian text in `FOREGROUND` plus a
  `STATUS_STALE` or `STATUS_FAULT` left border. Status is therefore conveyed by
  text and shape/color, never color alone (RULE-A11Y-002/003).
- Both messages are at most 256 UTF-8 bytes and contain no raw channel, vendor,
  diagnostic, metadata, or payload text. Hostile markup cannot enter the label.
- The notice is static, contains no motion, and keeps the existing body-font
  minimum. Real Windows ONEDIR DPI/NVDA evidence remains open.

## Performance evidence

- Notice text, visibility, and QSS are mutated only when presentation changes
  among `waiting | hidden | absent | refused`; steady accepted/refused readings
  perform no repeated notice stylesheet work.
- Per-reading identity bookkeeping uses bounded dictionary `get`/assignment/
  `pop` and a cached refused count: O(1) expected work with at most
  `MAX_CATALOG_DESCRIPTORS == 4096` issue entries.
- Descriptor presentation performs no file, database, socket, network, or
  sleep call. It remains synchronous on the GUI owner thread and only mutates
  existing Qt state. Full lab-PC frame timing and long-session memory evidence
  remain open.

## v1 to v2 migration

This is a v2.0.0 breaking API change. Callers must replace
`on_reading(reading)` with `on_descriptor_reading(reading, view)` where `view`
comes from the GUI-owned `DescriptorStore` after qualified ingress. Restoring a
bare-reading compatibility adapter would restore the unsafe identity fallback
and is prohibited.

## Rules cross-reference

- `rules/color-rules.md` RULE-COLOR-010 — no hardcoded hex (satisfied).
- `rules/color-rules.md` RULE-COLOR-015 — status tokens used semantically.
- `rules/copy-rules.md` RULE-COPY-005 — no emoji in labels (SeverityChip + plain Russian).
- `rules/data-display-rules.md` RULE-TABLE-002 — monospace numeric cells with tabular figures.
- `rules/interaction-rules.md` RULE-INTERACT-001 — connection-dependent operations (diag polling) explicitly gated.

## Fail-conservative identity

- Disconnect pauses polling but leaves diag rows + summary chips in place.
- Cards continue drawing; adaptive liveness reacts to the silent feed on its own (transitions to `STATUS_FAULT` after `timeout_s`).
- Engine error in poll result preserves the prior diag map (no wipe).
- Absent/refused identity leaves existing last-known cards visible but cannot
  create or update an attributed card; the fixed unavailable notice remains
  visible until that channel is requalified by an authoritative connected view.
- Descriptors and their views grant no control authority.

## Changelog

- **2026-04-18 (Phase II.8)** — merged rebuild landed. Unicode circle indicator replaced by painted widget; summary emoji replaced by `SeverityChip`; `apply_panel_frame_style` + deprecated `TEXT_*` tokens removed.
- **2026-07-14 (F35 D7.2)** — removed vendor/channel-name identity inference;
  instrument cards now consume only authoritative connected descriptor views,
  with bounded Russian unavailable/refused presentation.
