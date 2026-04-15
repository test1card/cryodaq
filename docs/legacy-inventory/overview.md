# Legacy Overview Panel Feature Inventory

## File overview
- File: `src/cryodaq/gui/widgets/overview_panel.py`
- Total lines: 1729
- Major sections:
  - Lines 1-50: module docstring, imports
  - Lines 52-200: `StatusStrip` — horizontal status bar (~40px)
  - Lines 202-450: `CompactTempCard` — mini temperature card (~100x60)
  - Lines 452-540: `TempCardGrid` — fixed 8-per-row grid
  - Lines 542-600: `PressureCard` — pressure readout card
  - Lines 602-800: `KeithleyStrip` — smua/smub status strip (~50px)
  - Lines 802-900: `ExperimentStatusWidget` — experiment status bar
  - Lines 902-980: `QuickLogWidget` — inline log entry widget
  - Lines 982-1300: `OverviewPanel._build_ui` — main layout construction
  - Lines 1300-1500: `OverviewPanel._handle_reading` — reading dispatch
  - Lines 1500-1729: plot refresh, time window, history loading

## Layout structure

```
Top level: QVBoxLayout
  StatusStrip: HBox (~40px)
    [Safety] [Аптайм] [Alarm count] [Keithley status] [Cooldown ETA] [Disk]
  
  ExperimentStatusWidget: HBox
    [Experiment name + phase + elapsed]

  QSplitter (horizontal, main content)
    Left (2/3): QVBoxLayout
      Temperature plot (pyqtgraph PlotWidget, ~350px)
        - Multi-channel lines from ChannelManager visible channels
        - Time window picker: [1мин][5мин][1ч][6ч][24ч][Всё]
        - Legend toggleable per channel
        - Cooldown prediction overlay (ML curve + CI band + ETA text)
      Pressure plot (pyqtgraph PlotWidget, ~120px, log Y)
        - Single orange line for vacuum channel
    
    Right (1/3): QVBoxLayout
      TempCardGrid: QGridLayout
        8 CompactTempCards per row, variable rows
        Each card: [channel name] [value K] [status dot]
        Click toggles plot line visibility
      PressureCard
        [Давление] [value mbar] [status indicator]
      KeithleyStrip: HBox
        [smua: ВКЛ 0.5W | smub: ВЫКЛ]
      QuickLogWidget: HBox
        [QLabel "Журнал:"] [QLineEdit "Заметка оператора..."] [QPushButton "Записать"]
        [Recent entries label, up to 5 current-experiment lines]
```

## ZMQ commands used

| Command | Payload | Trigger |
|---------|---------|---------|
| `experiment_status` | `{cmd}` | 5-second poll via `ExperimentStatusWidget` QTimer |
| `log_entry` | `{cmd, message, source: "overview", current_experiment: true}` | Quick log submit |
| `log_get` | `{cmd, limit: 5, current_experiment: true}` | Log widget refresh |
| `readings_history` | `{cmd, from_ts, to_ts, channels: [...], limit_per_channel}` | "Все" time window / history load |

## Live data subscriptions (on_reading channels)

- `Т*` (temperature, unit=K) → card update + plot buffer
- any reading with `unit == "mbar"` → pressure card + pressure plot buffer
- `/smua/*`, `/smub/*` → KeithleyStrip values
- `analytics/keithley_channel_state/*` → KeithleyStrip state
- `analytics/cooldown_eta` → prediction curve on temp plot
- `analytics/cooldown_eta_hours` → StatusStrip ETA text
- `analytics/safety_state` → StatusStrip + KeithleyStrip safety
- `analytics/alarm_count` → StatusStrip alarm badge

## Operator workflows

1. **Ambient monitoring** — glance at status strip (safety, alarms, Keithley, ETA), scan temp cards for anomalies
2. **Sensor check** — click temp cards to toggle plot lines, visually verify sensor response
3. **Quick note** — type in quick log, press Enter, log entry saved to experiment
4. **Time window zoom** — click 1мин/5мин/1ч/6ч/24ч/Всё to adjust plot range
5. **Cooldown tracking** — watch ETA overlay on temperature plot, ML prediction curve

## Comparison: legacy vs new dashboard

| Feature | Legacy Overview | New Dashboard (B.1-B.7) | Status |
|---------|----------------|------------------------|--------|
| StatusStrip | In-panel widget | TopWatchBar (separate) | ✓ COVERED |
| TempCardGrid | Fixed 8-per-row | DynamicSensorGrid (B.3) | ✓ COVERED |
| Temperature plot | Embedded in panel | TempPlotWidget (B.2) | ✓ COVERED |
| Pressure plot | Embedded in panel | PressurePlotWidget (B.2) | ✓ COVERED |
| Cooldown ETA overlay | On temp plot | Inline in PhaseAwareWidget | ⚠ PARTIAL (no ML curve) |
| KeithleyStrip | In sidebar | TopWatchBar context strip (B.4) | ✓ COVERED |
| QuickLogWidget | In sidebar | QuickLogBlock (B.7) | ⚠ PARTIAL (legacy shows 5 current-experiment entries; dashboard shows 2 global entries, no author/tags) |
| ExperimentStatus | In panel | TopWatchBar zone 2 | ✓ COVERED |
| Card toggle → plot line | Click card | Not implemented | ✗ DROPPED |
| Pressure card | Sidebar widget | TopWatchBar context strip | ✓ COVERED |

## Recommendations for Phase II overlay rebuild

**MUST preserve:**
- ML prediction curve overlay on temperature plot (K5 preserve)
- Time window picker with zoom/pan (K5 preserve)
- Card-click toggle for plot line visibility (useful operator workflow)

**COULD defer:**
- Readings history load for 24h+ time windows (readings_history ZMQ)
- Disk space indicator (already in BottomStatusBar)

**SHOULD cut:**
- KeithleyStrip duplicate (TopWatchBar context strip covers)
- ExperimentStatusWidget duplicate (TopWatchBar zone 2 covers)
- StatusStrip duplicate (TopWatchBar + BottomStatusBar cover)
- Fixed 8-per-row card grid (DynamicSensorGrid replaces)

Legacy Overview is almost entirely superseded by the new dashboard.
Only the ML prediction curve overlay and card-click toggle are unique
features not yet in new surfaces.

## Preserve-feature appendix

This inventory anchors the following K# preserve features (per `docs/phase-ui-1/ui_refactor_context.md` §3):

- K5: plot history with zoom/pan via the embedded temperature/pressure plots, time-window presets, and history loading path (`overview_panel.py:1548-1668`)
- K1: partial operator note chronology via `QuickLogWidget` current-experiment submit + 5-entry refresh (`overview_panel.py:906-990`)

Verified anchors: K5
NOT anchored by this inventory: K2, K3, K4, K6, K7

---
*Coverage claims in this inventory verified against new-shell code at commit `cf72942` (date 2026-04-16). Re-verify before treating as authoritative for Phase II rebuilds.*
