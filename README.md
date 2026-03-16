# CryoDAQ

CryoDAQ is a Python-based DAQ and control system for the cryogenic laboratory of AKTs FIAN (Millimetron project). The current release candidate already includes runtime control, safety/alarm handling, experiment metadata, operator log, report generation, archive browsing, calibration backend + GUI, housekeeping, and desktop GUI integration with tray status.

## Current system shape

- `cryodaq-engine` is the headless runtime process. It polls instruments, evaluates alarms/interlocks, writes data, and serves GUI commands.
- `cryodaq-gui` is a separate desktop client. It can be restarted without stopping acquisition.
- `cryodaq` is the launcher path for operator use on Windows.
- Optional web access is available through `cryodaq.web.server:app`.

### Main GUI tabs

The current `MainWindow` contains 10 operator-facing tabs:

1. `Обзор`
2. `Keithley 2604B`
3. `Аналитика`
4. `Теплопроводность`
5. `Автоизмерение`
6. `Алармы`
7. `Журнал оператора`
8. `Архив`
9. `Калибровка`
10. `Приборы`

The window also contains:

- menu `Файл` with CSV / HDF5 / Excel export
- menu `Эксперимент` with experiment start/finalize actions
- menu `Настройки` with channel editor and instrument connection settings
- status bar with connection, uptime, and rate
- Windows tray integration with conservative `healthy / warning / fault` mapping

## Implemented workflow blocks

- Safety and alarm pipeline with acknowledge/clear publish path
- Backend-truth-driven GUI safety/alarm/status behavior
- Dual-channel Keithley 2604B runtime for `smua`, `smub`, and `smua + smub`
- Operator log persisted to SQLite and available in GUI / command path
- Experiment templates and lifecycle metadata with artifact folders
- Report generator MVP with template-selected modular sections
- Archive GUI for browsing stored experiments and report artifacts
- Housekeeping with conservative adaptive throttle and retention/compression policy
- Calibration backend:
  - LakeShore raw/SRDG acquisition
  - calibration sessions
  - multi-zone Chebyshev fitting
  - JSON/CSV export/import
- Calibration GUI for session capture, fit, and export

## Installation

### Requirements

- Windows 10/11 or Linux
- Python `>=3.12`
- Git
- Instrument drivers / VISA backend as required by the hardware stack

### Python package install

```bash
pip install -e ".[dev,web]"
```

Supported local development and test flow assumes the package is installed from the repository root into the active environment. Running `pytest` against an arbitrary unpacked source tree without installing CryoDAQ first is not a supported path.

Key declared runtime dependencies include:

- `PySide6`
- `pyqtgraph`
- `pyvisa`
- `pyserial-asyncio`
- `pyzmq`
- `python-docx`
- `scipy`
- `matplotlib`
- `openpyxl`

## Launch

Recommended manual startup order:

```bash
cryodaq-engine
cryodaq-gui
```

Optional paths:

```bash
cryodaq                 # operator launcher
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
```

Mock mode:

```bash
cryodaq-engine --mock
```

## Configuration

Main configuration files:

- `config/instruments.yaml`
- `config/instruments.local.yaml`
- `config/alarms.yaml`
- `config/interlocks.yaml`
- `config/notifications.yaml`
- `config/housekeeping.yaml`
- `config/experiment_templates/*.yaml`

`*.local.yaml` overrides base config and is intended for machine-specific deployment data.

## Experiment and artifact layout

Experiment templates live in:

- `config/experiment_templates/thermal_conductivity.yaml`
- `config/experiment_templates/cooldown_test.yaml`
- `config/experiment_templates/calibration.yaml`
- `config/experiment_templates/debug_checkout.yaml`
- `config/experiment_templates/custom.yaml`

Experiment artifacts are stored under:

```text
data/experiments/<experiment_id>/
  metadata.json
  reports/
    report.docx
    report.pdf          # optional, best effort
    assets/
```

Calibration artifacts are stored under:

```text
data/calibration/sessions/<session_id>/
data/calibration/curves/<sensor_id>/<curve_id>/
```

## Reporting

The report generator is modular and template-driven.

Implemented section renderers:

- `title_page`
- `cooldown_section`
- `thermal_section`
- `pressure_section`
- `operator_log_section`
- `alarms_section`
- `config_section`

Primary guaranteed artifact: `DOCX`.

PDF conversion is best-effort only and depends on external `soffice` / `libreoffice` availability.

## Project structure

```text
src/cryodaq/
  analytics/
    calibration.py
  core/
    alarm.py
    experiment.py
    housekeeping.py
    operator_log.py
    safety_manager.py
    smu_channel.py
  drivers/
    instruments/
      keithley_2604b.py
      lakeshore_218s.py
  gui/
    app.py
    main_window.py
    tray_status.py
    widgets/
      archive_panel.py
      calibration_panel.py
      common.py
      experiment_dialogs.py
      keithley_panel.py
      operator_log_panel.py
      overview_panel.py
  reporting/
    data.py
    generator.py
    sections.py
  storage/
    sqlite_writer.py
tsp/
  p_const.lua
  p_const_single.lua
tests/
  analytics/
  core/
  drivers/
  gui/
  reporting/
  storage/
```

## Tests

Reference regression commands:

```bash
python -m pytest tests/core -q
python -m pytest tests/storage -q
python -m pytest tests/drivers -q
python -m pytest tests/analytics -q
python -m pytest tests/gui -q
python -m pytest tests/reporting -q
```

Run these commands from the repository root after `pip install -e ".[dev,web]"`. GUI tests assume that the environment includes the declared GUI/runtime dependencies such as `PySide6` and `pyqtgraph`.

Current RC baseline:

- required regression matrix:
  - `tests/core`: `169 passed`
  - `tests/storage`: `20 passed`
  - `tests/drivers`: `29 passed`
  - `tests/analytics`: `45 passed`
  - `tests/gui`: `57 passed`
  - `tests/reporting`: `6 passed`
  - total: `326 passed`

## Known limitations

- Calibration apply path into runtime is not implemented. The GUI keeps `Применить в CryoDAQ` disabled.
- Report PDF generation is best-effort. DOCX is the guaranteed output.
- `asyncio.WindowsSelectorEventLoopPolicy` still produces deprecation warnings on newer Python versions.

## Status

The current `CRYODAQ-CODEX` branch represents the release-candidate implementation state. Documentation in this file is intentionally limited to implemented behavior and confirmed caveats.
