# Legacy Instruments Panel Feature Inventory

## File overview
- File: `src/cryodaq/gui/widgets/instrument_status.py`
- Total lines: 308
- Major sections:
  - Lines 1-43: imports, constants (color mapping, stale timeout)
  - Lines 45-177: _InstrumentCard (per-instrument status card)
  - Lines 180-308: InstrumentStatusPanel (card grid + sensor diagnostics)

## Layout structure

```
InstrumentStatusPanel: QVBoxLayout
  Scroll area
    dynamic card grid
    _InstrumentCard per instrument
      Each card:
        [Instrument name] (bold)
        [Статус: ожидание данных / Норма / Предупреждение / Нет связи]
        [Последний ответ: только что / X с назад / X мин назад]
        [Показания: N | Ошибки: M]
        Full card border colored by state
  
  SensorDiagPanel (embedded, separate class)
```

## _InstrumentCard details

Each card auto-created on first reading from unknown instrument:
- Name: `reading.instrument_id` (e.g., "LS218_1", "Keithley_1", "VSP63D_1")
- Liveness: adaptive timeout = median(update_intervals) × 5
- Before enough readings: default timeout = 300s, floor = 10s
- Visual states:
  - OK (green): fresh data within timeout
  - Warning (yellow): latest reading had non-OK `reading.status`
  - Offline/error (red): no data > timeout
- Full border color, not a thin left-edge strip

FYI: a previous version of this inventory documented per-channel value rows
and a stale→offline 2-step timeout ladder. Those features do not exist in
source as of `cf72942`.

## ZMQ commands used

None. InstrumentStatusPanel is purely passive — receives data via on_reading.

## Live data subscriptions

- ALL readings → routes to _InstrumentCard by `instrument_id`
- Cards auto-created for new instruments on first reading
- Liveness refresh: 1Hz QTimer checks adaptive timeout per card

## Embedded SensorDiagPanel

InstrumentStatusPanel embeds SensorDiagPanel (separate file, 211 lines).
Accessed via `self.sensor_diag_panel` property.

## Operator workflows

1. **Check all instruments** — glance at cards, all green = OK
2. **Diagnose warning/offline instrument** — yellow = non-OK reading status, red = timeout / no data
3. **Check response recency** — card shows last response age and accumulated counters
4. **Review sensor diagnostics** — scroll down to embedded diagnostics table

## Comparison: legacy vs new

| Feature | Legacy | New | Status |
|---------|--------|-----|--------|
| Instrument card grid | Auto-created per instrument | Not in dashboard | ✗ NOT COVERED |
| Liveness detection | Adaptive timeout | Not in dashboard | ✗ NOT COVERED |
| Color-coded status | Green/yellow/red border | Not in dashboard | ✗ NOT COVERED |
| Sensor diagnostics | Embedded SensorDiagPanel | Not in dashboard | ✗ NOT COVERED |

## Recommendations for Phase II overlay rebuild

**MUST preserve:**
- Per-instrument status cards with liveness detection
- Adaptive timeout mechanism (median × 5 for stale detection)
- Color-coded card border / indicator (OK, warning, offline)
- Response recency + counters (`Показания`, `Ошибки`)

**COULD defer:**
- Auto-creation of cards for new instruments (could be config-driven)
- Complex timeout calculation (could use fixed 30s)

**SHOULD cut:**
- Hardcoded color hex in card styling (use theme.STATUS_* tokens)
- _InstrumentCard class name in QSS (use #objectName per A.7)

Panel is low-priority for rebuild — operators check it only when
something is wrong. Wrap approach (theme token modernization) is
sufficient.

## Preserve-feature appendix

This inventory anchors the following K# preserve features (per `docs/phase-ui-1/ui_refactor_context.md` §3):

- No direct K1-K7 preserve features. This panel is operational status UI, not a preserve-list owner.

Verified anchors: none of K1-K7
NOT anchored by this inventory: K1, K2, K3, K4, K5, K6, K7

---
*Coverage claims in this inventory verified against new-shell code at commit `cf72942` (date 2026-04-16). Re-verify before treating as authoritative for Phase II rebuilds.*
