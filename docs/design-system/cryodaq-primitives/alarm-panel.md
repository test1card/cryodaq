---
title: AlarmPanel
keywords: alarms, acknowledge, v1, v2, severity chip, fail-open, K1 safety, tray count
applies_to: Dual-engine alarm overlay (v1 threshold + v2 YAML-driven phase-aware)
status: active
implements: src/cryodaq/gui/shell/overlays/alarm_panel.py (Phase II.4); legacy src/cryodaq/gui/widgets/alarm_panel.py retained (DEPRECATED) until Phase II.13
last_updated: 2026-04-18
references: rules/data-display-rules.md, rules/copy-rules.md, rules/color-rules.md, cryodaq-primitives/alarm-badge.md, components/card.md, components/button.md
---

# AlarmPanel

K1-critical overlay. Shows two tables — v1 threshold-based engine (fed via `on_reading()` readings with `metadata["alarm_name"]`) and v2 YAML-driven phase-aware engine (fed via 3 s polling of `alarm_v2_status`). This is the primary surface for **acknowledging safety alarms**; it must be readable, unambiguous, and never hide active faults.

## Rebuild scope (II.4)

Legacy widget at `src/cryodaq/gui/widgets/alarm_panel.py` used emoji severity icons (🔴/🟡/🔵), hardcoded `theme.STONE_400` / `theme.TEXT_INVERSE` on the ACK button QSS, and eager registration at module import. Replacement at `src/cryodaq/gui/shell/overlays/alarm_panel.py` resolves all three:

- Emoji → `SeverityChip` pill widget using `STATUS_FAULT` / `STATUS_WARNING` / `STATUS_INFO` tokens with Russian short labels (`КРИТ` / `ПРЕД` / `ИНФО`).
- Deprecated `STONE_400` / `TEXT_INVERSE` → `SURFACE_MUTED` / `MUTED_FOREGROUND` for disabled state, `STATUS_FAULT` + `ON_PRIMARY` for active state.
- Host Integration Contract: `set_connected(bool)` gates ACK buttons and pauses v2 polling. The overlay is still eagerly built (it feeds the top-bar alarm count before the user ever opens the tab), but `_tick_status` now explicitly mirrors connection state into the panel.

## Tokens

- **Background / surfaces:** `BACKGROUND` (panel root), `SURFACE_CARD` (v1 + v2 cards and tables), `SURFACE_MUTED` (disabled ACK + table header).
- **Borders:** `BORDER_SUBTLE` (card + table outline, header separator, gridlines).
- **Text:** `FOREGROUND` (titles, data), `MUTED_FOREGROUND` (summary chip, empty-state label, disabled ACK text, table header text).
- **Status tokens:** `STATUS_FAULT` (CRITICAL chip + ACK), `STATUS_WARNING` (WARNING chip + ACK), `STATUS_INFO` (INFO chip + ACK + fallback).
- **Contrast base:** `ON_PRIMARY` (chip + ACK text on colored background).
- **Spacing:** `SPACE_0 / SPACE_1 / SPACE_2 / SPACE_3 / SPACE_4` only.
- **Radii:** `RADIUS_MD` (cards), `RADIUS_SM` (chip, tables, ACK button).
- **Typography:** `FONT_BODY` with `FONT_BODY_SIZE` / `FONT_LABEL_SIZE`, `FONT_SIZE_XL` for the title, `FONT_SIZE_LG` for section titles, `FONT_SIZE_XS` for the chip, `FONT_MONO` for numeric cells and chip label.

No hardcoded hex. No emoji. No deprecated tokens.

## Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ АЛАРМЫ                             N критических, M предупр.    │
├─────────────────────────────────────────────────────────────────┤
│ ┌ Card: Текущие тревоги (v1) ──────────────────────────────┐   │
│ │  [КРИТ] | Имя | Канал | Значение | Порог | Время | N | ACK   │
│ │  ...                                                       │   │
│ └──────────────────────────────────────────────────────────┘   │
│ ┌ Card: Физические тревоги (v2) ───────────────────────────┐   │
│ │  [КРИТ] | alarm_id | Сообщение | Каналы | Время | ACK        │
│ │  ...                                                       │   │
│ │  Нет активных алармов                                      │   │
│ └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

- Root: `QVBoxLayout`, margins `(SPACE_4, SPACE_3, SPACE_4, SPACE_3)`, spacing `SPACE_3`.
- Header: title (`FONT_SIZE_XL` + SEMIBOLD) left, aggregate severity chip right (`MUTED_FOREGROUND`).
- v1 and v2 cards: `SURFACE_CARD` with `RADIUS_MD` and `BORDER_SUBTLE`, inner margin `SPACE_3`.
- v2 card has an empty-state label `«Нет активных алармов»` under the table; visible when the active map is empty.
- Tables: stretched last-column-resize except the chip (col 0) and state (last col) columns which are `ResizeToContents`.
- v1 and v2 sort order: `CRITICAL` → `WARNING` → `INFO`, then by name / alarm_id.

## Public API

```python
class AlarmPanel(QWidget):
    v2_alarm_count_changed = Signal(int)  # preserved for tray-icon consumer

    def on_reading(self, reading: Reading) -> None: ...
    def set_connected(self, connected: bool) -> None: ...
    def update_v2_status(self, payload: dict) -> None: ...
    def get_active_v1_count(self) -> int: ...
    def get_active_v2_count(self) -> int: ...
```

- `on_reading(reading)`: v1 reading sink. Drops readings without `metadata["alarm_name"]`. Updates row severity / value / state based on `event_type` (`activated` | `acknowledged` | `cleared`).
- `set_connected(bool)`: gates ACK buttons (disabled when disconnected) and pauses the v2 poll timer. Idempotent for repeated values.
- `update_v2_status(payload)`: accepts the raw `alarm_v2_status` response. Host / tests may call this directly without going through the 3 s poll. Emits `v2_alarm_count_changed`.
- `get_active_v1_count()` / `get_active_v2_count()`: accessors reserved for future finalize / report-generation guards.

## Interaction

- **Connected + alarm active** → ACK button colored by severity token, enabled. Click dispatches `alarm_acknowledge` (v1) or `alarm_v2_ack` (v2) via `ZmqCommandWorker`.
- **Disconnected** → ACK buttons disabled via `SURFACE_MUTED` + `MUTED_FOREGROUND`. Row data remains visible (fail-OPEN — stale data is better than hidden alarms).
- **Engine error during poll** → existing v2 map is preserved; no table wipe. Logged as warning.
- **Alarm transitions** — v1 `activated` increments `trigger_count`; `acknowledged` / `cleared` update the state cell (`Подтв.` / `Сброшена`).

## Severity chip

`SeverityChip(severity)` renders a small centered pill:

- Background: `STATUS_FAULT` / `STATUS_WARNING` / `STATUS_INFO`.
- Foreground: `ON_PRIMARY`.
- Label: `КРИТ` / `ПРЕД` / `ИНФО` (Russian short, `FONT_MONO` + SEMIBOLD, `FONT_SIZE_XS`).
- Padding: `SPACE_0 SPACE_2`; radius `RADIUS_SM`.

Reused by both tables.

## Host integration contract

`MainWindowV2` must:

1. Construct `AlarmPanel` eagerly (it supplies the top-bar alarm count before the user opens the tab).
2. Connect `v2_alarm_count_changed` to `TopWatchBar.set_alarm_count`.
3. Register the panel under the `"alarms"` key on `OverlayContainer`.
4. Mirror connection state into the panel from `_tick_status` — same pattern as KeithleyPanel / OperatorLogPanel / ArchivePanel / ConductivityPanel / CalibrationPanel.
5. Route every reading through `self._alarm_panel.on_reading(reading)` from `_dispatch_reading`.

See `src/cryodaq/gui/shell/main_window_v2.py` lines 38, 148, 168, 178, 332 and the `_tick_status` block for the canonical wiring.

## Rules cross-reference

- `rules/color-rules.md` RULE-COLOR-010 — no hardcoded hex (satisfied: only DS tokens).
- `rules/color-rules.md` RULE-COLOR-015 — status colors reserved for semantic status (CRITICAL / WARNING / INFO).
- `rules/copy-rules.md` RULE-COPY-005 — no emoji in operator-facing labels (satisfied: chip replaces 🔴🟡🔵).
- `rules/data-display-rules.md` RULE-TABLE-002 — monospace numeric cells with tabular figures.
- `rules/interaction-rules.md` RULE-INTERACT-003 — destructive / high-impact actions (ACK) gated by connection state.

## Changelog

- **2026-04-18 (Phase II.4)** — rebuild landed. Emoji removed; DS v1.0.1 tokens throughout; `set_connected` hook added; eager registration kept by design (tray-count path).
