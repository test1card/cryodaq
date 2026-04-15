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
  Header frame "ДИАГНОСТИКА ДАТЧИКОВ" + summary badge
  
  QTableWidget
    Columns: Канал | T (K) | Шум (мК) | Дрейф (мК/мин) | Выбросы | Корр. | Здоровье
    Per-channel row with color-coded health score
  
  Summary badge:
    [healthy✓] [warning⚠] [critical✘]
```

## ZMQ commands used

| Command | Payload | Trigger |
|---------|---------|---------|
| `get_sensor_diagnostics` | `{cmd}` | 10-second poll timer |

Response fields consumed by this widget:
`{ok, channels: {ch_id: {channel_name, health_score, current_T, noise_mK, drift_mK_per_min, outlier_count, correlation}}, summary: {healthy, warning, critical}}`

## Health scoring

- Health score: 0-100 per channel
- Color: green (≥80), yellow (50-79), red (<50)
- Current T: current temperature value in K
- Noise: `noise_mK`
- Drift: `drift_mK_per_min`
- Outliers: count of detected outliers
- Correlation: optional correlation score

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
| Summary badge | healthy / warning / critical counts | Not available | ✗ NOT COVERED |

## Recommendations for Phase II overlay rebuild

**MUST preserve:**
- Health score per channel with color coding
- Noise / drift / outlier / correlation columns (diagnostic value for sensor troubleshooting)
- Summary badge (healthy / warning / critical counts)
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

## Preserve-feature appendix

This inventory anchors the following K# preserve features (per `docs/phase-ui-1/ui_refactor_context.md` §3):

- No direct K1-K7 preserve features. This panel is a diagnostics surface, not a preserve-list owner.

Verified anchors: none of K1-K7
NOT anchored by this inventory: K1, K2, K3, K4, K5, K6, K7

---
*Coverage claims in this inventory verified against new-shell code at commit `cf72942` (date 2026-04-16). Re-verify before treating as authoritative for Phase II rebuilds.*
