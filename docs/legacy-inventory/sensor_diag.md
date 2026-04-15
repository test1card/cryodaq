# Legacy Sensor Diagnostics Panel Feature Inventory

## File overview
- File: `src/cryodaq/gui/widgets/sensor_diag_panel.py`
- Total lines: 211
- Major sections:
  - Lines 1-53: imports, helpers (_health_color, _fmt)
  - Lines 55-110: SensorDiagPanel init + _build_ui
  - Lines 111-128: _poll_diagnostics (10s poll via ZMQ)
  - Lines 129-210: set_diagnostics, _refresh_table, _refresh_summary, helpers

## Layout structure

```
SensorDiagPanel: QVBoxLayout
  QLabel "Диагностика датчиков"
  
  QTableWidget
    Columns: Канал | Здоровье | Шум (σ) | Дрифт | Последнее
    Per-channel row with color-coded health score
  
  Summary row:
    [Средний балл: X/100] [Каналов: N] [Нездоровых: M]
```

## ZMQ commands used

| Command | Payload | Trigger |
|---------|---------|---------|
| `get_sensor_diagnostics` | `{cmd}` | 10-second poll timer |

Response fields: `{ok, channels: {ch_id: {health, noise_sigma, drift, last_value}}, summary: {mean_health, total, unhealthy}}`

## Health scoring

- Health score: 0-100 per channel
- Color: green (≥80), yellow (50-79), red (<50)
- Noise (σ): standard deviation of recent readings
- Drift: rate of change trend
- Last: last known reading value

## Operator workflows

1. **Routine check** — scan health column for red/yellow entries
2. **Noise diagnosis** — high σ indicates sensor instability or loose connection
3. **Drift detection** — non-zero drift when expecting stable reading
4. **Compare channels** — table shows all channels side-by-side

## Comparison: legacy vs new

| Feature | Legacy | New | Status |
|---------|--------|-----|--------|
| Health score table | Full table, all channels | Not in dashboard | ✗ NOT COVERED |
| Noise (σ) display | Per-channel | Not available | ✗ NOT COVERED |
| Drift display | Per-channel | Not available | ✗ NOT COVERED |
| Summary stats | Mean health, unhealthy count | Not available | ✗ NOT COVERED |

## Recommendations for Phase II overlay rebuild

**MUST preserve:**
- Health score per channel with color coding
- Noise and drift columns (diagnostic value for sensor troubleshooting)
- Summary statistics (mean health, unhealthy count)
- 10-second polling interval (sensor health changes slowly)

**COULD defer:**
- Inline in sensor grid right-click menu (per Strategy Q4 resolution)
- Advanced noise/drift trending over time (not in current panel)

**SHOULD cut:**
- Separate overlay slot (fold into Instruments overlay or sensor grid popover)
- Hardcoded color thresholds (expose as config or theme tokens)

Per Strategy §11.5 Q4 resolution: SensorDiagPanel should fold into
right-click sensor cell → inline popover. This moves diagnostics
from a separate tab to context-relevant display, reducing tab-switching
(solves P1 for diagnostics).
