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
  [Начать калибровочный прогон] button
  StatusBanner
  QGroupBox "Импорт внешней кривой"
    [Импорт .330] [Импорт .340] [Импорт JSON]
  QGroupBox "Существующие кривые"
    QTableWidget: [Датчик | Curve ID | Зон | RMSE | Источник]
```

- Channels loaded from `config/instruments.yaml` (LakeShore 218S only)
- Channel refs include instrument prefix: `LS218_1:Т1 Криостат верх`
- Start creates a calibration experiment via `experiment_start`

### Mode 2: Acquisition (CalibrationAcquisitionWidget)

```
QVBoxLayout:
  Header: "Сбор данных — активен"
  Stats form: [Эксперимент] [Время] [Точек записано] [Диапазон T_ref]
  QGroupBox "Покрытие" — CoverageBar (custom histogram widget)
  Live readings label
  Note: "Запись идёт автоматически..."
```

- CoverageBar: paints colored bins (green = enough data, amber = sparse, red = empty)
- Stats from `calibration_acquisition_status` polling response
- No controls — operator watches until coverage sufficient, then stops experiment

### Mode 3: Results (CalibrationResultsWidget)

```
QVBoxLayout:
  Header: "Результаты калибровки"
  Channel selector: [Канал: QComboBox]
  Metrics form: Raw пар / После downsample / Breakpoints / Зон Chebyshev / RMSE / Max ошибка
  QGroupBox "Экспорт": [.330] [.340] [JSON] [CSV] buttons (4 format buttons)
  QGroupBox "Применить"
    [Глобально: SRDG + calibration curves]
    [Политика канала: Наследовать / Включить / Выключить]
    [Применить в CryoDAQ]
    [Δ:]
  StatusBanner
```

- Results page currently displays metrics only; it does NOT contain a results table.
- Export buttons and runtime-apply controls are present in the UI but are not wired to actions in this widget as of `cf72942`.
- FYI: a previous version of this inventory documented a per-channel fit table and functional export workflow. That does not match source as of `cf72942`.

## ZMQ commands used

| Command | Payload | Trigger |
|---------|---------|---------|
| `experiment_start` | `{cmd, template_id: "calibration", name, title, operator, custom_fields: {reference_channel, target_channels: "<comma-joined string>"}}` | Начать калибровочный прогон button |
| `calibration_acquisition_status` | `{cmd}` | 3-second poll timer |

Note: export commands and fit pipeline commands are handled at engine level,
not directly from this panel. Panel only displays results from polling.

## Live data subscriptions

- `CalibrationPanel.on_reading()` appends `_raw` / `sensor_unit` readings into the acquisition-mode live label
- Primary mode selection and stats still arrive via polling `calibration_acquisition_status`

## External dependencies
- yaml (instruments.yaml parsing for LakeShore channels)
- No pyqtgraph
- Custom CoverageBar widget (QPainter-based histogram)

## Operator workflows (K3 — calibration workflow)

1. **Setup**: select reference channel + target channels from LakeShore instruments
2. **Start**: click Начать, creates calibration experiment, panel auto-switches to Acquisition
3. **Monitor**: watch coverage histogram fill, check stats (points, channels, duration)
4. **Wait**: acquisition runs until operator stops experiment (via ExperimentWorkspace/overlay)
5. **Review**: after stop, panel auto-switches to Results and shows aggregate fit metrics for the selected channel
6. **Export / apply**: export/apply buttons are visible in Results mode, but this widget does not currently wire them to actions

## Comparison: legacy vs new

| Feature | Legacy | New | Status |
|---------|--------|-----|--------|
| Setup mode | Channel selection from instruments.yaml | Not in dashboard | ✗ NOT COVERED |
| Acquisition mode | Live stats + coverage histogram | Not in dashboard | ✗ NOT COVERED |
| Results mode | Channel selector + metrics form + export/apply controls | Not in dashboard | ✗ NOT COVERED |
| .330/.340/JSON/CSV export | 4-button export row present but not wired in widget | Not available | ✗ NOT COVERED |
| Coverage histogram | Custom CoverageBar widget | Not available | ✗ NOT COVERED |

## Recommendations for Phase II overlay rebuild

**MUST preserve (K3 — calibration workflow):**
- Three-mode architecture (Setup → Acquisition → Results)
- Auto-switching based on calibration_acquisition_status polling
- Reference + target channel selection from instruments.yaml
- Coverage histogram (CoverageBar or equivalent)
- Results metrics surface (selected channel + aggregate fit metrics)
- Visible export/apply affordances if these workflows remain part of the redesign
- Instrument prefix stripping for backend commands

**COULD defer:**
- CoverageBar custom painting (could use simple QProgressBar per bin)
- Import/existing-curves management if Phase II focuses only on active-run workflow

**SHOULD cut:**
- 3-second poll interval (5-10s sufficient for calibration which runs hours)
- QGroupBox colored borders (use theme tokens)

Calibration is used 1-2 times per year but is K3-critical. Rebuild
complexity is MEDIUM — the three-mode QStackedWidget pattern is
well-established and could be preserved as-is with theme token
modernization (Wrap approach per strategy).

## Preserve-feature appendix

This inventory anchors the following K# preserve features (per `docs/phase-ui-1/ui_refactor_context.md` §3):

- K3: three-mode calibration workflow (setup / acquisition / results) (`calibration_panel.py:141-499`)
- K3: reference + target channel selection and calibration experiment start payload (`calibration_panel.py:141-277`)
- K3: coverage histogram during acquisition (`calibration_panel.py:103-136`, `calibration_panel.py:282-344`)
- K6: partial export affordances only — `.330`, `.340`, `JSON`, `CSV` buttons are visible in Results mode, but not wired in this widget (`calibration_panel.py:382-408`)

Verified anchors: K3, partial K6 (visible affordance only)
NOT anchored by this inventory: K1, K2, K4, K5, K7

---
*Coverage claims in this inventory verified against new-shell code at commit `cf72942` (date 2026-04-16). Re-verify before treating as authoritative for Phase II rebuilds.*
