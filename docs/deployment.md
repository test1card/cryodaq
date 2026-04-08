# Развёртывание CryoDAQ

Практическая инструкция для установки CryoDAQ на операторский ПК.

## 1. Требования

- Windows 10/11 или Linux
- Python `>=3.12`
- Git
- доступ к интернету для установки Python dependencies
- установленный VISA backend / драйверы приборов по фактическому стеку

Дополнительно, если нужен best-effort PDF export для отчётов:

- `LibreOffice` / `soffice`

## 2. Получение кода

```powershell
git clone https://github.com/test1card/cryodaq.git
cd cryodaq
```

## 3. Установка пакета

```powershell
pip install -e ".[dev,web,archive]"
```

Минимальная runtime-установка без dev/web extras:

```powershell
pip install -e .          # без Parquet архива
pip install -e ".[archive]"  # + Parquet (рекомендуется)
```

Если нужен только web dashboard, используйте:

```powershell
pip install -e ".[web,archive]"
```

Эта установка подтягивает и GUI dependencies, включая:

- `PySide6`
- `pyqtgraph`
- `python-docx`
- `openpyxl`
- `scipy`

Именно этот install path считается поддерживаемым и для локального тестирования. Запуск `pytest` по произвольной распакованной копии исходников без предварительного `pip install -e ...` не считается гарантированным сценарием.

## 4. Локальная конфигурация

Создайте machine-specific overrides:

```powershell
Copy-Item config\instruments.local.yaml.example config\instruments.local.yaml
Copy-Item config\notifications.local.yaml.example config\notifications.local.yaml
```

Проверьте и заполните:

- `config/instruments.local.yaml`
- `config/notifications.local.yaml`

Также в репозитории уже используются:

- `config/alarms.yaml`
- `config/interlocks.yaml`
- `config/housekeeping.yaml`
- `config/experiment_templates/*.yaml`

## 5. Что настроить в instruments.local.yaml

Актуальный стек первой RC-версии:

- три `LakeShore 218S`
- `Keithley 2604B`
- опционально вакуумметр

Обратите внимание:

- calibration GUI читает LakeShore channels из `instruments.yaml` / `instruments.local.yaml`
- допустимы разные shapes channel config, но конфигурация должна оставаться валидным YAML
- Keithley runtime использует dual-channel model (`smua`, `smub`)
- Любые старые инструкции про отключение или скрытие `smub` считать устаревшими

## 6. Запуск

Рекомендуемый ручной порядок:

```powershell
cryodaq-engine
cryodaq-gui
```

Для оператора также доступен launcher:

```powershell
cryodaq
```

Mock mode:

```powershell
cryodaq-engine --mock
```

Optional web dashboard:

```powershell
uvicorn cryodaq.web.server:app --host 0.0.0.0 --port 8080
```

Этот путь запуска относится к optional web-компоненту и требует установленного extra `web`
(или полного dev/test install path `.[dev,web]`).

## 7. Проверка после запуска

Проверьте минимум следующее:

- `Обзор` получает свежие данные
- вкладка `Источник мощности` открывается и показывает каналы A/B
- вкладка `Алармы` не содержит unexpected active alarms
- вкладка `Служебный лог` может загрузить записи
- вкладка `Архив` открывается без ошибок
- вкладка `Калибровка` либо видит LakeShore channels, либо честно показывает, что они недоступны
- tray icon, если системный трей доступен, не показывает healthy без backend truth

Текущая GUI-компоновка содержит 10 вкладок:

- `Обзор`
- `Эксперимент`
- `Источник мощности`
- `Аналитика`
- `Теплопроводность` (включает автоизмерение)
- `Алармы`
- `Служебный лог`
- `Архив`
- `Калибровка`
- `Приборы`

## 8. Данные и артефакты

Операторская интерпретация `data/experiments/<experiment_id>/`:

- один каталог соответствует одной experiment card
- в каждый момент времени должна быть открыта только одна активная experiment card
- workflow `Отладка` не должен создавать архивные карточки эксперимента

Основные runtime-файлы:

- daily SQLite databases: `data/data_YYYY-MM-DD.db`
- experiment artifacts: `data/experiments/<experiment_id>/`
- calibration sessions: `data/calibration/sessions/<session_id>/`
- calibration curves: `data/calibration/curves/<sensor_id>/<curve_id>/`

Housekeeping:

- compresses only unlinked old daily DBs
- does not delete experiment-linked DBs
- does not delete experiment artifact folders

## 9. Отчёты и архив

Целевой внешний отчётный контракт:

- `report_raw.pdf`
- `report_editable.docx`


Генерация отчёта опирается на архивную карточку эксперимента, её артефакты и template-defined sections; для части данных текущий contour всё ещё может использовать fallback-чтение из SQLite.

Гарантированный артефакт:

- `report_editable.docx`

Опциональный артефакт:

- `report_raw.pdf`

Генерация PDF не является обязательным критерием развёртывания.

## 10. Известные caveat'ы RC

- Runtime apply калибровки доступен через global on/off и per-channel policy; отсутствие curve, assignment или сбой вычисления нужно трактовать как консервативный fallback к `KRDG` с явным логированием.
- Поведение на живом LakeShore требует отдельной lab verification и не считается автоматически подтверждённым одним только unit/mock coverage.
- PDF-артефакт остаётся best-effort и зависит от внешнего `LibreOffice` / `soffice`.
- На новых версиях Python сохраняются `WindowsSelectorEventLoopPolicy` deprecation warnings.

## 11. Smoke-test commands

```powershell
python -m pytest tests/core -q
python -m pytest tests/storage -q
python -m pytest tests/drivers -q
python -m pytest tests/analytics -q
python -m pytest tests/gui -q
python -m pytest tests/reporting -q
```

Запускайте эти команды из корня репозитория в том же environment, где выполнен `pip install -e ".[dev,web,archive]"`. GUI tests требуют установленного `PySide6` и `pyqtgraph`. Web dashboard в этот smoke-набор не входит и требует отдельного `.[web]` install path.

Если установка выполняется для операторской машины без dev workflow, достаточно убедиться, что эти команды проходили до развёртывания, а локальный smoke check ограничить запуском engine + GUI + mock mode.

## SQLite version requirement

CryoDAQ uses SQLite WAL mode with multiple concurrent connections (writer +
history readers + reporting + web dashboard). Due to a WAL-reset race
condition documented at https://www.sqlite.org/wal.html, production
deployments **must** run SQLite >= 3.51.3.

### Ubuntu 22.04

Ubuntu 22.04 ships `libsqlite3-0 3.37.2`, which is inside the affected range.
Options, in order of preference:

1. **Recommended.** Build SQLite from source under `/opt/sqlite-3.51.3/` and
   preload it: `LD_PRELOAD=/opt/sqlite-3.51.3/lib/libsqlite3.so cryodaq`.
2. Bundle a custom `libsqlite3` in the PyInstaller frozen build (see
   `build_scripts/cryodaq.spec`).
3. (Fallback) Set `CRYODAQ_SQLITE_SYNC=FULL` to reduce the race window at the
   cost of write throughput.

The engine emits a WARNING on startup if it detects an affected version.

### Ubuntu 24.04 / Windows 11

SQLite >= 3.51.3 is available natively. No action required.

## Frozen-app build (PyInstaller)

```bash
pip install -e ".[dev,web]"   # ensures pyinstaller is installed
./build_scripts/build.sh       # Linux / macOS
build_scripts\build.bat        # Windows
```

The build produces `dist/CryoDAQ/CryoDAQ[.exe]` plus a runtime tree of
`config/`, `data/`, `logs/`, `plugins/` next to the exe (NOT inside
`_internal/_MEIPASS`). Operators copy the entire `dist/CryoDAQ/` directory
to the lab PC.

## USB Selective Suspend (Windows)

Windows по умолчанию отключает USB-устройства для экономии энергии.
На лабораторном ПК это приводит к потере связи с приборами через 20+ часов.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\disable_usb_suspend.ps1
```

Дополнительно: Device Manager → каждый USB Root Hub → Properties →
Power Management → убрать "Allow the computer to turn off this device to save power".
