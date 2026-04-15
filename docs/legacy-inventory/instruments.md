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
  PanelHeader: "Приборы"
  
  QHBoxLayout (card grid, dynamic):
    _InstrumentCard per instrument
      Each card:
        [Instrument name] (bold)
        [Channel: value unit] × N readings
        [Last seen: Xs ago] (adaptive timeout)
        Left edge: 3px colored border (green/yellow/red)
  
  SensorDiagPanel (embedded, separate class)
```

## _InstrumentCard details

Each card auto-created on first reading from unknown instrument:
- Name: `reading.instrument_id` (e.g., "LS218_1", "Keithley_1", "VSP63D_1")
- Per-channel values: last reading value + unit
- Liveness: adaptive timeout = median(update_intervals) × 5
- Visual states:
  - OK (green): fresh data within timeout
  - Stale (yellow): no data > timeout
  - Offline (red): no data > 3× timeout
  - Error (red): reading.status != OK
- Left edge 3px colored border (`_InstrumentCard` visual style)

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
2. **Diagnose stale instrument** — yellow/red card → instrument lost data
3. **Check per-channel values** — card shows last value per channel
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
- Color-coded left-edge border (OK/stale/offline/error)
- Per-channel last-reading display

**COULD defer:**
- Auto-creation of cards for new instruments (could be config-driven)
- Complex timeout calculation (could use fixed 30s)

**SHOULD cut:**
- Hardcoded color hex in card styling (use theme.STATUS_* tokens)
- _InstrumentCard class name in QSS (use #objectName per A.7)

Panel is low-priority for rebuild — operators check it only when
something is wrong. Wrap approach (theme token modernization) is
sufficient.
