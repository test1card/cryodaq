# Legacy Analytics Panel Feature Inventory

## File overview
- Main file: `src/cryodaq/gui/widgets/analytics_panel.py` (521 lines)
- Related file: `src/cryodaq/gui/widgets/vacuum_trend_panel.py` (413 lines)
- Total scope: 934 LOC

### analytics_panel.py sections:
- Lines 1-54: imports, constants (_R_THERMAL_BUFFER = 3600, _T_COLD_BUFFER = 7200)
- Lines 55-87: AnalyticsPanel init, buffers, timers (500ms refresh)
- Lines 92-300: _build_ui (R_thermal card, ETA card, plot, vacuum trend)
- Lines 306-362: on_reading / _handle_reading (R_thermal, cooldown_eta, T_cold live)
- Lines 363-500: ETA display update, plot refresh (R_thermal mode vs cooldown mode)
- Lines 500-521: helper functions

### vacuum_trend_panel.py sections:
- Lines 1-50: imports, VacuumTrendPrediction dataclass
- Lines 51-230: VacuumTrendPanel._build_ui (3 ETA targets, chart, model info)
- Lines 231-413: polling (10s via ZmqCommandWorker), chart rendering, extrapolation

## Layout structure

```
AnalyticsPanel: QVBoxLayout
  Row 1: HBox (two hero cards)
    R_thermal card: QFrame
      [Тепловое сопротивление]
      [value: 3.42 К/Вт]  (28pt bold mono)
      [± annotation]
    
    Cooldown ETA card: QFrame
      [ETA до 4.2 К]
      [value: 14ч 20мин]  (28pt bold mono)
      [Прогресс: 87%]  QProgressBar
      [Фаза: фаза_3]
      [Модель: ensemble_v2]
  
  Row 2: Plot (stretch=1)
    pyqtgraph PlotWidget
    Two modes:
      Mode A (R_thermal): R_thermal vs time, 1-hour window
      Mode B (cooldown active): T_cold vs time (relative hours),
        ML prediction curve + CI band
    Empty state overlay: "R_thermal и cooldown данные появятся..."
  
  Row 3: VacuumTrendPanel (stretch=1)
    3 target rows: [1×10⁻⁴] [1×10⁻⁵] [1×10⁻⁶]
      Each: ETA text + confidence text
    Vacuum chart: pressure log-scale + extrapolation curve
    Model info: [samples, BIC, R², model type]
```

## ZMQ commands used

| Command | Payload | Trigger | File |
|---------|---------|---------|------|
| `get_vacuum_trend` | `{cmd}` | 10s poll timer | vacuum_trend_panel.py:239 |

Analytics panel itself sends NO commands — purely display-driven.
VacuumTrendPanel polls backend for vacuum extrapolation data.

## Live data subscriptions (on_reading)

### analytics_panel.py:
- `*/R_thermal` → R_thermal buffer + hero card value update
- `*/cooldown_eta` → ETA card update + prediction meta + cooldown activation
- `*/cooldown_eta_s` → legacy compatibility (old plugin format)
- `*Детектор*` (unit=K) → T_cold live line during cooldown (relative hours)

### vacuum_trend_panel.py:
- No on_reading — uses polling via ZMQ command

## Two display modes

**Mode A — R_thermal (no cooldown):**
- Plot shows R_thermal vs absolute time
- Y axis: "R_thermal" units "К/Вт"
- R_thermal line + R_thermal hero card active
- ETA card shows "Ожидание cooldown..."

**Mode B — Cooldown active:**
- Plot switches to T_cold vs relative hours from cooldown start
- ML prediction curve (orange dashed) + confidence band (FillBetweenItem)
- Y axis: "Температура" units "K"
- ETA card shows hours remaining + progress bar + phase + model info
- Both R_thermal and cooldown data accumulate

Mode switching is automatic based on `cooldown_active` flag in cooldown_eta metadata.

## Vacuum trend panel details

Three target pressure thresholds: 1×10⁻⁴, 1×10⁻⁵, 1×10⁻⁶ mbar
Each shows:
- ETA text: "~2ч 14мин" or "достигнуто" or "—"
- Confidence: "±30мин" or "—"
- Status dot (green if reached, amber if approaching, gray if unknown)

Vacuum chart:
- Log-Y pressure vs time
- Observed data (blue line)
- Extrapolation curve (orange dashed, extending 2x window)
- Model info: sample count, BIC score, R² fit, selected model name

10-second polling: `get_vacuum_trend` returns `VacuumTrendPrediction` dataclass
with observed data, extrapolation data, target ETAs, model parameters.

## External dependencies
- pyqtgraph (PlotWidget, PlotDataItem, FillBetweenItem, DateAxisItem)
- No numpy/scipy direct — analytics backend does computation

## Operator workflows

1. **Monitor thermal resistance** — watch R_thermal hero card for stability during measurement phase
2. **Track cooldown progress** — ETA card + ML prediction curve + progress bar show estimated time to 4.2K
3. **Vacuum pump-down monitoring** — 3 target pressures with ETAs, chart shows extrapolation curve
4. **Compare model fit** — model info section shows which fit was selected (BIC-based), R² quality

## Comparison: legacy vs new

| Feature | Legacy Analytics | New Dashboard | Status |
|---------|-----------------|---------------|--------|
| R_thermal hero card | 28pt bold value | PhaseAwareWidget inline (cooldown/measurement) | ⚠ PARTIAL (inline only, no big readout) |
| Cooldown ETA card | Full card: ETA + progress + phase + model | PhaseAwareWidget inline text | ⚠ PARTIAL (no progress bar, no model info) |
| R_thermal plot | Full plot with time window | Not in dashboard | ✗ NOT COVERED |
| Cooldown ML prediction | Curve + CI band on plot | Not in dashboard | ✗ NOT COVERED |
| Vacuum trend panel | Full panel with 3 targets + chart | Not in dashboard | ✗ NOT COVERED |
| T_cold live line | During cooldown on plot | Not in dashboard | ✗ NOT COVERED |

## Recommendations for Phase II overlay rebuild

**MUST preserve (K5 — plots with zoom/pan):**
- R_thermal plot with 1-hour rolling window (K5 preserve)
- Cooldown ML prediction curve + CI band on temperature plot (K5 preserve)
- Vacuum trend chart with extrapolation (K5 preserve)
- R_thermal hero readout card (HeroReadout primitive from B.5.5)
- Cooldown ETA hero readout card (EtaDisplay primitive from B.5.5)
- Vacuum trend 3-target ETA display
- Mode switching: R_thermal mode vs cooldown mode (auto based on phase)

**COULD defer:**
- Progress bar for cooldown (informational, ETA is primary)
- Model info display (BIC, R², model name — developer debugging info)
- Vacuum trend model parameters section

**SHOULD cut:**
- Empty state overlay text (generic, not actionable)
- Legacy cooldown_eta_s compatibility path (old plugin, can remove)
- Hardcoded colors in card borders (use theme tokens)

This is the LEAST covered legacy panel by new surfaces. Dashboard shows
inline snippets (ETA text, R_thermal value) but NO full plots or
detailed analytics. Phase II Analytics overlay is the highest-priority
rebuild — it enables the entire cooldown monitoring workflow that
operators depend on daily during week-long experiments.

B.5.5 primitives (HeroReadout, EtaDisplay) are designed for this overlay.
VacuumTrendPanel can potentially be wrapped with theme tokens and used
as-is inside the new overlay.
