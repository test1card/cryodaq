# REPO_INVENTORY.md

**Generated:** 2026-04-14
**Version:** 0.13.0
**Python:** 3.12+ (dev: 3.14.3)
**Tests:** 895 passed, 1 skipped (Phase 2e)

---

## Scale

| Metric | Count |
|---|---|
| Source files (src/cryodaq/) | 102 |
| Source LOC | ~33,990 |
| Test files (tests/) | 113 |
| Test LOC | ~20,850 |
| Total Python files | 215 |
| Total LOC | ~54,840 |
| Test-to-source ratio | 0.61 |
| Config files (YAML) | 16 |
| Plugin files | 3 .py + 3 .yaml |
| Entry points | 7 (4 standard + 3 frozen) |

---

## Source files by directory

| Directory | Files | LOC | % |
|---|---|---|---|
| Root level (engine, launcher, etc.) | 13 | 2,178 | 6.4 |
| core/ | 25 | 7,942 | 23.4 |
| gui/widgets/ | 21 | 10,105 | 29.7 |
| gui/ (app, window, tray) | 6 | 1,028 | 3.0 |
| analytics/ | 9 | 4,347 | 12.8 |
| drivers/instruments/ | 4 | 1,535 | 4.5 |
| drivers/transport/ | 4 | 823 | 2.4 |
| drivers/ (base) | 2 | 94 | 0.3 |
| storage/ | 7 | 1,848 | 5.4 |
| notifications/ | 6 | 1,356 | 4.0 |
| reporting/ | 4 | 1,141 | 3.4 |
| web/ | 2 | 512 | 1.5 |
| tools/ | 2 | 252 | 0.7 |
| config/ | 1 | 0 | 0.0 |
| **Total** | **102** | **33,990** | |

---

## Test coverage map

### Well-tested (test-to-source ratio > 1.0)

| Module | Ratio | Key test files |
|---|---|---|
| core/ | 1.31 | test_safety_manager, test_scheduler, test_alarm_v2, test_experiment |
| root level | 0.34 | test_engine_config_error, test_launcher_backoff, test_paths_frozen |

### Adequately tested (0.5–1.0)

| Module | Ratio | Key test files |
|---|---|---|
| analytics/ | 0.67 | test_calibration, test_cooldown_predictor, test_vacuum_trend |
| drivers/ | 0.69 | test_keithley_2604b, test_lakeshore_218s, test_thyracont |
| storage/ | 0.65 | test_csv_export, test_hdf5_export, test_xlsx_export, test_parquet_export |

### Under-tested (< 0.5)

| Module | Ratio | Notes |
|---|---|---|
| gui/ | 0.26 | 11 of 28 modules covered |
| notifications/ | 0.41 | Only telegram.py tested |
| reporting/ | 0 | Zero test files |
| web/ | 0 | test_web_dashboard in root tests only |
| tools/ | 0 | Zero test files |

### Untested modules (no corresponding test file)

**Core (4):** alarm_providers, channel_manager, safety_broker, smu_channel
**Analytics (4):** base_plugin, plugin_loader, steady_state, (one __init__)
**Drivers (4):** base, transport/gpib, transport/serial, transport/usbtmc
**GUI (17):** app, alarm_panel, analytics_panel, autosweep_panel, channel_editor, common, conductivity_panel, connection_settings, instrument_status, keithley_panel, overview_panel, pressure_panel, temp_panel, zmq_client, and more
**Notifications (5):** _secrets, escalation, periodic_report, telegram_commands
**Reporting (3):** data, generator, sections
**Web (1):** server

---

## Configuration files

### Primary config (config/)

| File | Lines | Purpose |
|---|---|---|
| alarms_v3.yaml | 307 | V3 alarm rules, temperature limits, rate thresholds |
| alarms.yaml | 58 | Legacy alarm definitions |
| channels.yaml | 97 | Channel names, units, display ranges |
| safety.yaml | 48 | FSM states, fail-on-silence, rate limits, drain timeout |
| instruments.yaml | 53 | GPIB/serial addresses, timeouts |
| interlocks.yaml | 48 | Interlock conditions, action mappings |
| plugins.yaml | 38 | sensor_diagnostics, vacuum_trend params |
| notifications.yaml | 19 | Telegram tokens, chat IDs |
| housekeeping.yaml | 26 | Cleanup intervals, retention, adaptive throttle |
| cooldown.yaml | 15 | Cooldown model parameters |
| shifts.yaml | 12 | Shift definitions |

### Experiment templates (config/experiment_templates/)

cooldown_test.yaml (19), calibration.yaml (21), thermal_conductivity.yaml (20), debug_checkout.yaml (17), custom.yaml (14)

### Local overrides

`config/*.local.yaml` — gitignored, for machine-specific COM ports, GPIB addresses, notification credentials.

---

## Dependencies

### Runtime

| Package | Version | Purpose |
|---|---|---|
| pyside6 | >=6.6,<7 | Desktop GUI |
| pyqtgraph | >=0.13,<0.14 | Real-time plotting |
| numpy | >=1.26,<3 | Numerical computing |
| scipy | >=1.12,<2 | Scientific algorithms |
| matplotlib | >=3.8,<4 | Static plotting |
| pyvisa | >=1.14,<2 | GPIB/USB-TMC control |
| pyserial-asyncio | >=0.6,<1 | Async serial I/O |
| h5py | >=3.10,<4 | HDF5 file I/O |
| msgpack | >=1.0,<2 | Binary serialization |
| pyyaml | >=6.0,<7 | YAML parsing |
| openpyxl | >=3.1,<4 | Excel writing |
| python-docx | >=1.1,<2 | Word document generation |
| pyzmq | >=25,<27 | ZMQ messaging |
| aiohttp | >=3.9.5,<4 | Async HTTP |

### Optional groups

- **dev:** pytest, pytest-asyncio, pytest-cov, ruff, pyinstaller, pip-tools
- **web:** fastapi, uvicorn[standard]
- **archive:** pyarrow>=15.0

---

## Entry points

| Command | Entry | Purpose |
|---|---|---|
| `cryodaq` | launcher:main | Operator launcher |
| `cryodaq-engine` | engine:main | Headless engine |
| `cryodaq-gui` | gui.app:main | Standalone GUI |
| `cryodaq-cooldown` | tools.cooldown_cli:main | Cooldown CLI |
| `cryodaq-frozen` | _frozen_main:main_launcher | PyInstaller launcher |
| `cryodaq-frozen-engine` | _frozen_main:main_engine | PyInstaller engine |
| `cryodaq-frozen-gui` | _frozen_main:main_gui | PyInstaller GUI |

---

## Plugins

| Plugin | LOC | YAML | Purpose |
|---|---|---|---|
| thermal_calculator | 177 | 3 | Thermal conductivity auto-measurement |
| phase_detector | 226 | 10 | Experiment phase detection |
| cooldown_estimator | 327 | 3 | Cooldown ETA prediction |

Discovery: hot-reload via plugin_loader.py (5s mtime polling). Registration: config/plugins.yaml.
