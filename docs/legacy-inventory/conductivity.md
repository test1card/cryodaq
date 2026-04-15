# Legacy Conductivity Panel Feature Inventory

## File overview
- File: `src/cryodaq/gui/widgets/conductivity_panel.py`
- Total lines: 1068
- Major sections:
  - Lines 1-79: imports, constants, helper functions
  - Lines 80-145: ConductivityPanel init, state vars, auto-measurement state machine
  - Lines 145-380: _build_ui (sensor selection, controls, auto-measurement group, table, plot)
  - Lines 384-430: channel selection handlers (check, move up/down, power changed)
  - Lines 430-530: on_reading, channel resolution, handle_reading
  - Lines 531-700: refresh, table update, banner update, prediction lines, stability
  - Lines 700-730: plot update
  - Lines 730-810: auto-measurement: generate power list, preview, send cmd, start, stop
  - Lines 810-920: auto_tick (stabilization check with min_wait guard), record point, complete
  - Lines 920-1068: auto export CSV, plot helpers

## Layout structure

```
ConductivityPanel: QVBoxLayout
  PanelHeader: "Теплопроводность"
  
  HBox main layout
    Left vertical QSplitter (fixed width 240px)
      Top section: датчики + источник мощности + reorder + экспорт
        Scrollable list of QCheckBox per visible Т-channel
        [↑] [↓] buttons for chain ordering
        SMU channel selector (QComboBox: smua / smub)
        [Экспорт CSV]
        Power display label
      Bottom section: QGroupBox "Автоизмерение"
        Начальная P: QDoubleSpinBox
        Шаг P: QDoubleSpinBox
        Кол-во шагов: QSpinBox
        Стабилизация: QDoubleSpinBox (%)
        Мин. ожидание: QDoubleSpinBox (с)  ← min_wait guard
        Preview label (N точек: P₁, P₂, ... Pₙ)
        [Старт автоизмерения] [Стоп]
        QProgressBar (hidden until running)
        Status label
    
    Right panel: QVBoxLayout
      Results table (QTableWidget)
        Columns:
          Пара | T гор. (К) | T хол. (К) | dT (К) | R (К/Вт) | G (Вт/К) |
          T∞ прогноз | τ (мин) | Готово % | R прогноз | G прогноз
      
      Temperature plot (pyqtgraph PlotWidget)
        Multi-line: one per chain channel
        Full history with right-side forecast zone
      
      StatusBanner
```

## Auto-measurement workflow (state machine)

States: `idle` → `stabilizing` → `done` (or back to `idle` on stop)

1. **Start**: operator sets P range (start/end/step), settled% threshold, min_wait
2. **Generate power list**: linspace from P_start to P_end with step
3. **Set first power**: sends `keithley_set_target` with P₁
4. **Stabilization tick** (1Hz timer):
   - Reads `percent_settled` from SteadyStatePredictor for ALL chain channels
   - Checks: elapsed ≥ min_wait AND min(all settled%) ≥ threshold
   - If stable: records R/G point, advances to next power step
5. **Repeat** until all power steps done
6. **Complete**: stops Keithley, shows summary dialog; CSV export remains a separate operator action via `Экспорт CSV`

**min_wait guard** (line 841): `elapsed >= min_wait and min_settled >= threshold`
- Prevents false positive from initial transient after power change
- Default 30 seconds, configurable 10-600s
- This is a CRITICAL operator safety feature per user preferences

## ZMQ commands used

| Command | Payload | Trigger |
|---------|---------|---------|
| `keithley_set_target` | `{cmd, channel: "smua"/"smub", p_target: float}` | Auto-measurement step + manual power input |
| `keithley_stop` | `{cmd, channel: "smua"/"smub"}` | Auto-measurement stop / complete |

## Live data subscriptions

- `Т*` channels (unit=K) → temperature buffers + table update + plot
- `Keithley_*/smua/power` or `*/smub/power` → power display label
- SteadyStatePredictor fed locally from temperature readings (not ZMQ)

## External dependencies
- pyqtgraph (PlotWidget, PlotDataItem, InfiniteLine)
- `cryodaq.analytics.steady_state.SteadyStatePredictor` — T∞ prediction + percent_settled
- csv module — auto-measurement result export

## Operator workflows

1. **Manual conductivity check**: select 2+ sensors, observe R/G table, compare with known values
2. **Auto-measurement sweep**: set P range, click Start, wait for completion, export CSV
3. **Monitor stabilization**: watch percent_settled column + prediction lines on plot
4. **Adjust min_wait**: if measurements oscillate, increase min_wait for longer settling
5. **Export results**: CSV export with P, T_hot, T_cold, dT, R, G, settled% columns

## Comparison: legacy vs new

| Feature | Legacy | New | Status |
|---------|--------|-----|--------|
| Sensor chain selection | QCheckBox list + ordering | Not in dashboard | ✗ NOT COVERED |
| R/G table | Full table with T∞, settled% | PhaseAwareWidget inline R_thermal | ⚠ PARTIAL |
| Auto-measurement | Full sweep state machine | Not in dashboard | ✗ NOT COVERED |
| Temperature plot | Multi-line per chain | TempPlotWidget (all channels) | ⚠ PARTIAL |
| CSV export | Auto-measurement results | Not available | ✗ NOT COVERED |
| SteadyStatePredictor | T∞ + percent_settled | Not in dashboard | ✗ NOT COVERED |

## Recommendations for Phase II overlay rebuild

**MUST preserve:**
- Auto-measurement workflow (state machine with min_wait guard)
- SteadyStatePredictor integration (T∞ + percent_settled)
- Sensor chain selection + ordering (critical for thermal link definition)
- R/G table with live values + stability indicators
- CSV export of auto-measurement results

**COULD defer:**
- T∞ prediction lines on plot (informational, table has same data)
- Power preview label (convenience, not critical)

**SHOULD cut:**
- Hardcoded color palette (use theme tokens)
- Fixed 320px left panel width (use proportional)
- StatusBanner duplicate (TopWatchBar covers general status)

This is a complex panel with embedded state machine. Rebuild requires
careful preservation of auto-measurement timing logic (min_wait + settled%
threshold). ChartTile primitive from Phase I could hold the temperature
plot component.

## Preserve-feature appendix

This inventory anchors the following K# preserve features (per `docs/phase-ui-1/ui_refactor_context.md` §3):

- K5: live temperature plot for the selected conductivity chain (`conductivity_panel.py:330-380`, `conductivity_panel.py:700-729`)
- K6: CSV export of conductivity auto-measurement results only (`conductivity_panel.py:213-220`, `conductivity_panel.py:948-1017`)

Verified anchors: K5, partial K6 (CSV only)
NOT anchored by this inventory: K1, K2, K3, K4, K7

---
*Coverage claims in this inventory verified against new-shell code at commit `cf72942` (date 2026-04-16). Re-verify before treating as authoritative for Phase II rebuilds.*
