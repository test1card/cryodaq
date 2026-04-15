# Legacy Calibration Panel Feature Inventory

## File overview
- File: `src/cryodaq/gui/widgets/calibration_panel.py`
- Total lines: 499
- Major sections:
  - Lines 1-46: imports, config path
  - Lines 49-100: helpers (_strip_instrument_prefix, _load_lakeshore_channels)
  - Lines 103-136: CoverageBar custom widget (visual histogram)
  - Lines 141-277: CalibrationSetupWidget (mode 1: channel selection + start)
  - Lines 282-344: CalibrationAcquisitionWidget (mode 2: live stats + coverage)
  - Lines 347-432: CalibrationResultsWidget (mode 3: fit results + export)
  - Lines 435-499: CalibrationPanel container (QStackedWidget, mode switching, polling)

## Three-mode architecture

**QStackedWidget** with 3 pages, auto-switched via 3-second polling of
`calibration_acquisition_status` ZMQ command:

- acquisition active → page 1 (AcquisitionWidget)
- completed data exists → page 2 (ResultsWidget)
- otherwise → page 0 (SetupWidget)

### Mode 1: Setup (CalibrationSetupWidget)

```
QVBoxLayout:
  QGroupBox "Опорный канал"
    QComboBox: LakeShore channels grouped by instrument
  QGroupBox "Целевые каналы"
    QCheckBox per LakeShore channel
  [Начать калибровку] button
  StatusBanner
```

- Channels loaded from `config/instruments.yaml` (LakeShore 218S only)
- Channel refs include instrument prefix: `LS218_1:Т1 Криостат верх`
- Start creates a calibration experiment via `experiment_start`

### Mode 2: Acquisition (CalibrationAcquisitionWidget)

```
QVBoxLayout:
  Header: "Калибровочный сбор идёт"
  Stats row: [Точек: N] [Каналов: N] [Длительность: Xч Yмин]
  QGroupBox "Покрытие" — CoverageBar (custom histogram widget)
  StatusBanner
```

- CoverageBar: paints colored bins (green = enough data, amber = sparse, red = empty)
- Stats from `calibration_acquisition_status` polling response
- No controls — operator watches until coverage sufficient, then stops experiment

### Mode 3: Results (CalibrationResultsWidget)

```
QVBoxLayout:
  Header: "Результаты калибровки"
  QTableWidget: columns [Канал | Зоны | Остаток | R² | Файл]
  QGroupBox "Экспорт": [.330] [.340] [JSON] [CSV] buttons (4 format buttons)
  StatusBanner
```

- Results from calibration fit pipeline (Chebyshev fit post-processing)
- Export buttons generate files in experiment artifact directory
- Table shows per-channel fit quality (R², residual, zone count)

## ZMQ commands used

| Command | Payload | Trigger |
|---------|---------|---------|
| `experiment_start` | `{cmd, template_id: "calibration", name, operator, custom_fields: {reference_channel, target_channels: [...]}}` | Начать калибровку button |
| `calibration_acquisition_status` | `{cmd}` | 3-second poll timer |

Note: export commands and fit pipeline commands are handled at engine level,
not directly from this panel. Panel only displays results from polling.

## Live data subscriptions

- No direct on_reading handler in CalibrationPanel
- Data arrives via polling `calibration_acquisition_status` response

## External dependencies
- yaml (instruments.yaml parsing for LakeShore channels)
- No pyqtgraph (results table only, no plots)
- Custom CoverageBar widget (QPainter-based histogram)

## Operator workflows (K3 — calibration workflow)

1. **Setup**: select reference channel + target channels from LakeShore instruments
2. **Start**: click Начать, creates calibration experiment, panel auto-switches to Acquisition
3. **Monitor**: watch coverage histogram fill, check stats (points, channels, duration)
4. **Wait**: acquisition runs until operator stops experiment (via ExperimentWorkspace/overlay)
5. **Review**: after stop, panel auto-switches to Results, shows fit quality per channel
6. **Export**: click .330 / .340 / JSON / CSV for export files (K3 preserve)

## Comparison: legacy vs new

| Feature | Legacy | New | Status |
|---------|--------|-----|--------|
| Setup mode | Channel selection from instruments.yaml | Not in dashboard | ✗ NOT COVERED |
| Acquisition mode | Live stats + coverage histogram | Not in dashboard | ✗ NOT COVERED |
| Results mode | Fit results table + export | Not in dashboard | ✗ NOT COVERED |
| .330/.340/JSON/CSV export | 4-button export row | Not available | ✗ NOT COVERED |
| Coverage histogram | Custom CoverageBar widget | Not available | ✗ NOT COVERED |

## Recommendations for Phase II overlay rebuild

**MUST preserve (K3 — calibration workflow):**
- Three-mode architecture (Setup → Acquisition → Results)
- Auto-switching based on calibration_acquisition_status polling
- Reference + target channel selection from instruments.yaml
- Coverage histogram (CoverageBar or equivalent)
- Fit results table with R², residual, zone count
- .330 / .340 / JSON / CSV export buttons (K3 + K6 preserve)
- Instrument prefix stripping for backend commands

**COULD defer:**
- CoverageBar custom painting (could use simple QProgressBar per bin)
- Per-channel fit detail view (table rows are sufficient)

**SHOULD cut:**
- 3-second poll interval (5-10s sufficient for calibration which runs hours)
- QGroupBox colored borders (use theme tokens)

Calibration is used 1-2 times per year but is K3-critical. Rebuild
complexity is MEDIUM — the three-mode QStackedWidget pattern is
well-established and could be preserved as-is with theme token
modernization (Wrap approach per strategy).
