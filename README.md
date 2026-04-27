# CryoDAQ

## Текущее состояние (v0.33.0)

- Источник истины по продуктовой модели: один эксперимент равен одной experiment card, и во время активного эксперимента открыта ровно одна карточка.
- Основной операторский workflow различает режимы `Эксперимент` и `Отладка`; в `Отладке` не должны появляться архивные карточки и автоматические отчёты по эксперименту.
- Целевой внешний отчётный контракт в текущем коде: `report_raw.pdf` и `report_editable.docx`.
- Dual-channel Keithley (`smua`, `smub`, `smua + smub`) остаётся актуальной моделью. Старые ожидания про disable/hide/remove `smub` устарели.
- Calibration v2: непрерывный сбор SRDG при калибровочных экспериментах, post-run pipeline (extract → downsample → Chebyshev fit), `.cof` (raw Chebyshev coefficients) / `.340` / JSON / CSV export; `.340` / JSON import; runtime apply с global/per-channel policy.

CryoDAQ — система сбора данных и управления для криогенной лаборатории АКЦ ФИАН (проект Millimetron). Полнофункциональная система с experiment/report/archive/operator-log/calibration/housekeeping/shift-handover workflow.

## Текущая форма системы

- `cryodaq-engine` — headless runtime-процесс. Он опрашивает приборы, проверяет safety/alarm/interlock-логику, пишет данные и обслуживает GUI-команды.
- `cryodaq-gui` — отдельный настольный клиент. Его можно перезапускать без остановки сбора данных.
- `cryodaq` — операторский launcher для Windows.
- `cryodaq.web.server:app` — опциональный web-доступ для мониторинга.

## GUI

Начиная с v0.33.0 CryoDAQ использует новый `MainWindowV2` (Phase UI-1 v2)
как primary shell. Это ambient information radiator layout с dashboard
из пяти зон, разработанный для недельных экспериментов без постоянного
переключения вкладок.

Legacy `MainWindow` с десятью вкладками остаётся активным параллельно
в режиме transition state до завершения блока B.7 (миграция всех legacy
панелей в dashboard zones). Оба shell получают readings из engine;
operator видит только `MainWindowV2`.

### MainWindowV2 (primary, с v0.33.0)

- `TopWatchBar` — engine indicator, experiment status, time window echo
- `ToolRail` — иконки для overlay navigation
- `DashboardView` с пятью зонами:
  1. Sensor grid (placeholder в v0.33.0, заполняется в блоке B.3)
  2. Temperature plot (multi-channel, clickable legend, time window picker)
  3. Pressure plot (compact log-Y)
  4. Phase widget (placeholder, блоки B.4-B.5)
  5. Quick log (placeholder, блок B.6)
- `BottomStatusBar` — safety state indicator
- `OverlayContainer` — host для legacy tab panels через overlay mechanism

### Legacy MainWindow (fallback, до блока B.7)

10 операторских вкладок:

1. `Обзор`
2. `Эксперимент`
3. `Источник мощности`
4. `Аналитика`
5. `Теплопроводность` (включает автоизмерение)
6. `Алармы`
7. `Служебный лог`
8. `Архив`
9. `Калибровка`
10. `Приборы`

Также в окне есть:

- меню `Файл` с экспортом CSV / HDF5 / Excel
- меню `Эксперимент` со стартом и завершением эксперимента
- меню `Настройки` с редактором каналов и настройками подключений приборов
- строка состояния с соединением, uptime и скоростью потока данных
- системный tray со статусами `healthy / warning / fault`

Tray не показывает `healthy`, если у GUI нет достаточной backend-truth информации. `fault` выставляется при unresolved alarms или safety-state `fault` / `fault_latched`.

## Реализованные workflow-блоки

- safety/alarm pipeline с acknowledge/clear publish path
- backend-driven GUI для safety/alarm/status
- dual-channel Keithley 2604B runtime для `smua`, `smub` и `smua + smub`
- журнал оператора в SQLite с GUI и command access
- experiment templates, lifecycle metadata и artifact folders
- шаблонно-управляемая генерация отчётов
- архив экспериментов с просмотром артефактов и повторной генерацией отчёта
- housekeeping с conservative adaptive throttle и retention/compression policy
- calibration backend:
  - LakeShore raw/SRDG acquisition
  - calibration sessions
  - multi-zone Chebyshev fit
  - `.cof` (Chebyshev coefficients) / `.340` / JSON / CSV export
  - `.340` / JSON import
- calibration GUI для capture / fit / export

## Установка

### Требования

- Windows 10/11 или Linux
- Python `>=3.12`
- Git
- VISA backend / драйверы, необходимые для фактического набора приборов

### Установка Python-пакета

```bash
pip install -e ".[dev,web]"
```

Минимальная runtime-установка без dev/web extras:

```bash
pip install -e .
```

Если нужен только web dashboard, используйте:

```bash
pip install -e ".[web]"
```

Поддерживаемый локальный dev/test workflow предполагает установку пакета из корня репозитория в активное окружение. Запуск `pytest` по произвольной распакованной копии исходников без `pip install -e ...` не считается поддерживаемым сценарием.

Ключевые runtime-зависимости из `pyproject.toml`:

- `PySide6`
- `pyqtgraph`
- `pyvisa`
- `pyserial-asyncio`
- `pyzmq`
- `python-docx`
- `scipy`
- `matplotlib`
- `openpyxl`

## Запуск

Рекомендуемый ручной порядок запуска:

```bash
cryodaq-engine
cryodaq-gui
```

Дополнительные пути:

```bash
cryodaq
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
```

Команда `uvicorn cryodaq.web.server:app` относится к optional web-path и требует установленного extra `web`
(или полного dev/test install path `.[dev,web]`).

Mock mode:

```bash
cryodaq-engine --mock
```

## Конфигурация

Основные конфигурационные файлы:

- `config/instruments.yaml` — GPIB/serial/USB адреса, каналы LakeShore
- `config/instruments.local.yaml` — machine-specific override (gitignored)
- `config/safety.yaml` — SafetyManager FSM timeouts, rate limits, drain timeout
- `config/alarms.yaml` — legacy alarm definitions
- `config/alarms_v3.yaml` — v2 alarm engine: temperature limits, rate, composite, phase-dependent
- `config/interlocks.yaml` — interlock conditions and action mappings
- `config/channels.yaml` — channel display names, visibility, groupings
- `config/notifications.yaml` — Telegram bot_token, chat_ids, escalation
- `config/housekeeping.yaml` — data throttle, retention, compression
- `config/plugins.yaml` — sensor_diagnostics и vacuum_trend feature flags
- `config/cooldown.yaml` — cooldown predictor model parameters
- `config/shifts.yaml` — shift definitions (GUI-only)
- `config/experiment_templates/*.yaml` — experiment type templates

`*.local.yaml` переопределяют базовые файлы и предназначены для machine-specific настроек.

## Эксперименты и артефакты

Доступные шаблоны:

- `config/experiment_templates/thermal_conductivity.yaml`
- `config/experiment_templates/cooldown_test.yaml`
- `config/experiment_templates/calibration.yaml`
- `config/experiment_templates/debug_checkout.yaml`
- `config/experiment_templates/custom.yaml`

Артефакты эксперимента:

```text
data/experiments/<experiment_id>/
  metadata.json
  reports/
    report_editable.docx
    report_raw.pdf      # optional, best effort if soffice/libreoffice is available
    report_raw.docx
    assets/
```

Артефакты калибровки:

```text
data/calibration/sessions/<session_id>/
data/calibration/curves/<sensor_id>/<curve_id>/
```

`metadata.json` хранит payload эксперимента, payload шаблона, `data_range` и `artifacts`.

## Отчёты

Подсистема отчётов находится в `src/cryodaq/reporting/` и использует template-defined sections.
Основой для генерации отчёта служат архивная карточка эксперимента и её артефакты; для части данных текущий contour всё ещё может использовать fallback-чтение из SQLite.

Реализованные section renderers:

- `title_page`
- `cooldown_section`
- `thermal_section`
- `pressure_section`
- `operator_log_section`
- `alarms_section`
- `config_section`

Гарантированный артефакт:

- `report_editable.docx`

Опциональный артефакт:

- `report_raw.pdf`

PDF-конвертация остаётся best-effort и зависит от наличия внешнего `soffice` / `LibreOffice`.

## Keithley TSP

TSP-скрипты для Keithley 2604B:

- `tsp/p_const.lua` — draft TSP supervisor для P=const feedback на SMU
- `tsp/p_const_single.lua` — legacy single-channel вариант

**Важно:** `p_const.lua` в текущей версии **не загружается** на прибор.
P=const feedback loop выполняется host-side в `keithley_2604b.py`.
TSP supervisor запланирован для Phase 3 (требует hardware verification).

## Структура проекта

```text
src/cryodaq/
  analytics/          # calibration fitter, cooldown, plugins, vacuum trend
  core/               # safety, scheduler, broker, alarms, experiments
  drivers/            # LakeShore, Keithley, Thyracont + transports
  gui/
    shell/            # MainWindowV2, TopWatchBar, ToolRail, BottomStatusBar (v0.33.0)
    dashboard/        # DashboardView, temp/pressure plots, channel buffer (v0.33.0)
    widgets/          # legacy tab panels (active until block B.7)
  reporting/          # ГОСТ R 2.105-2019 report generator
  storage/            # SQLiteWriter, Parquet, CSV, HDF5, XLSX export
  web/                # FastAPI monitoring dashboard
tsp/                  # Keithley TSP scripts (not loaded, see above)
tests/
config/
```

Ключевые файлы для операторских workflow:

- `src/cryodaq/gui/shell/main_window_v2.py` — primary shell (с v0.33.0)
- `src/cryodaq/gui/dashboard/dashboard_view.py` — 5-zone dashboard
- `src/cryodaq/gui/main_window.py` — legacy 10-tab shell (fallback)
- `src/cryodaq/gui/widgets/calibration_panel.py`
- `src/cryodaq/core/experiment.py`
- `src/cryodaq/reporting/generator.py`

## Тесты

Референсная regression matrix:

```bash
python -m pytest tests/core -q
python -m pytest tests/storage -q
python -m pytest tests/drivers -q
python -m pytest tests/analytics -q
python -m pytest tests/gui -q
python -m pytest tests/reporting -q
```

Запускайте эти команды из корня репозитория после `pip install -e ".[dev,web]"`. GUI tests требуют установленного `PySide6` и `pyqtgraph`. Web dashboard в этот smoke set не входит и требует отдельного `.[web]` install path.

## Известные ограничения

- Runtime calibration policy реализована: глобальный режим `on/off` и per-channel policy переключают `KRDG` / `SRDG + curve`. При отсутствии curve, assignment, `SRDG` или ошибке вычисления backend консервативно возвращается к `KRDG`; поведение на живом LakeShore требует отдельной lab verification.
- PDF для отчётов не гарантирован. Гарантированный результат — DOCX.
- На новых версиях Python сохраняются deprecation warnings, связанные с `asyncio.WindowsSelectorEventLoopPolicy`.

## Статус

Этот README намеренно ограничен только подтверждённым текущим поведением и актуальными caveat-ограничениями RC-ветки.
