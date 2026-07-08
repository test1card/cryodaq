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

С IV.4 F1 `pyarrow` входит в базовые зависимости, extra `[archive]`
сохранён как no-op alias для обратной совместимости со старыми
install-строками. На Linux базовая установка также подтягивает
`pysqlite3-binary`: если системный SQLite попадает в опасный WAL-диапазон,
runtime автоматически выбирает bundled SQLite через `cryodaq.storage._sqlite`.

```powershell
pip install -e ".[dev,web]"
```

Минимальная runtime-установка без dev/web extras:

```powershell
pip install -e .                     # Parquet поддержка в базе
pip install -e ".[dev,web,archive]"  # старая строка — по-прежнему работает
```

Если нужен только web dashboard, используйте:

```powershell
pip install -e ".[web]"
```

Эта установка подтягивает и GUI dependencies, включая:

- `PySide6`
- `pyqtgraph`
- `python-docx`
- `openpyxl`
- `scipy`

Именно этот install path считается поддерживаемым и для локального тестирования. Запуск `pytest` по произвольной распакованной копии исходников без предварительного `pip install -e ...` не считается гарантированным сценарием.

Windows helper `install.bat` проверяет Python 3.12+, выполняет
`pip install -e ".[dev,web,archive]"` (обратимо совместимый alias) и вызывает
`create_shortcut.py` для ярлыка на рабочем столе.

### Bootstrap predictor model

При развёртывании CryoDAQ на новой машине модель предиктора охлаждения
необходимо скопировать из канонического источника.

```bash
make bootstrap-predictor
```

Эта команда копирует `cooldown_v5/predictor_model.json` в
`data/cooldown_model/predictor_model.json`. Ручной аналог:

```bash
mkdir -p data/cooldown_model
cp cooldown_v5/predictor_model.json data/cooldown_model/
```

Если модель не развёрнута, лаунчер выводит подсказку при старте.

## 4. Локальная конфигурация

Создайте machine-specific overrides:

```powershell
Copy-Item config\instruments.local.yaml.example config\instruments.local.yaml
Copy-Item config\notifications.local.yaml.example config\notifications.local.yaml
Copy-Item config\web.local.yaml.example config\web.local.yaml
```

Проверьте и заполните:

- `config/instruments.local.yaml`
- `config/notifications.local.yaml`
- `config/web.local.yaml` — нужен только для write-действий web dashboard;
  сгенерируйте случайный `web.api_token`

Также в репозитории уже используются:

- `config/alarms.yaml`
- `config/interlocks.yaml`
- `config/housekeeping.yaml`
- `config/safety.yaml`
- `config/experiment_templates/*.yaml`

## 5. Что настроить в instruments.local.yaml

Актуальный стек:

- три `LakeShore 218S`
- `Keithley 2604B`
- опционально вакуумметр

Обратите внимание:

- calibration GUI читает LakeShore channels из `instruments.yaml` / `instruments.local.yaml`
- допустимы разные shapes channel config, но конфигурация должна оставаться валидным YAML
- Keithley runtime использует dual-channel model (`smua`, `smub`)
- Любые старые инструкции про отключение или скрытие `smub` считать устаревшими
- TSP watchdog выбирается в `keithley.watchdog.mode`: `"off"`,
  `"best_effort"` или `"required"`; значение должно быть строкой, потому что
  bare `off/on` в YAML превращаются в boolean

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

Скрипты из корня репозитория запускают тот же launcher:

```text
.\start.bat       # Windows
./start.sh        # Linux / macOS
.\start_mock.bat  # Windows mock mode, CRYODAQ_MOCK=1
./start_mock.sh   # Linux / macOS mock mode, CRYODAQ_MOCK=1
```

Mock mode:

```powershell
cryodaq-engine --mock
```

Optional web dashboard:

```powershell
uvicorn cryodaq.web.server:app --host 127.0.0.1 --port 8080
```

GET-эндпоинты web dashboard остаются read-only и работают по loopback-модели
доверия — биндите только `127.0.0.1`. Публичный доступ возможен только через
reverse proxy с авторизацией или SSH-туннель.

Write-действия web dashboard ограничены двумя REST routes:
`POST /api/v1/log` и `POST /api/v1/alarms/{id}/ack`. Они требуют
`Authorization: Bearer <token>`; токен читается из gitignored
`config/web.local.yaml` (`web.api_token`). Пока токен не задан, write routes
отвечают 403. Неверный или отсутствующий bearer-токен даёт 401.

Этот путь запуска относится к optional web-компоненту и требует установленного extra `web`
(или полного dev/test install path `.[dev,web]`).

## 7. Проверка после запуска

Проверьте минимум следующее:

- ToolRail slot `Дашборд` получает свежие данные
- ToolRail slot `Источник мощности` открывается и показывает каналы A/B
- ToolRail slot `Тревоги` не содержит unexpected active alarms
- ToolRail slot `Служебный лог` может загрузить записи
- ToolRail: `Ещё` → `Архив` открывается без ошибок
- ToolRail: `Ещё` → `Калибровка` либо видит LakeShore channels, либо честно показывает, что они недоступны
- ToolRail slot `База знаний` открывается; при пустом индексе показывает управляемое empty/error state
- tray icon, если системный трей доступен, не показывает healthy без backend truth

Текущая GUI-компоновка — MainWindowV2 shell, не вкладки:

- TopWatchBar
- ToolRail
- OverlayContainer с дашбордом и полноэкранными surfaces
- BottomStatusBar

Порядок основных ToolRail slots: `Дашборд`, `Новый эксперимент`,
`Эксперимент`, `Источник мощности`, `Аналитика`, `Теплопроводность`,
`MultiLine`, `Тревоги`, `Служебный лог`, `База знаний`, `Приборы`.
Меню `Ещё`: `Архив`, `Калибровка`, `Настройки`, `Открыть Web-панель`,
`Перезапустить Engine`.

## 8. Данные и артефакты

Операторская интерпретация `data/experiments/<experiment_id>/`:

- один каталог соответствует одной experiment card
- в каждый момент времени должна быть открыта только одна активная experiment card
- workflow `Отладка` не должен создавать архивные карточки эксперимента

Основные runtime-файлы:

- daily SQLite databases: `data/data_YYYY-MM-DD.db`
- cold archive: `data/archive/` (zstd Parquet + `index.json`)
- experiment artifacts: `data/experiments/<experiment_id>/`
- calibration sessions: `data/calibration/sessions/<session_id>/`
- calibration curves: `data/calibration/curves/<sensor_id>/<curve_id>/`

Housekeeping:

- while `cold_rotation.enabled: true`, daily DB lifecycle belongs to cold
  rotation: old `data/data_YYYY-MM-DD.db` files move to zstd Parquet under
  `data/archive`
- retention compresses only when cold rotation is off; legacy `.db.gz` files
  are ingested by rotation before deletion
- does not delete experiment-linked DBs
- does not delete experiment artifact folders

Read paths are hot ∪ cold: GUI history, archive views, CSV/XLSX/HDF5 export,
reports, operator log and replay continue to see days already rotated out of
hot SQLite.

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

## 10. Известные caveat'ы

- Runtime apply калибровки доступен через global on/off и per-channel policy; отсутствие curve, assignment или сбой вычисления нужно трактовать как консервативный fallback к `KRDG` с явным логированием.
- Поведение на живом LakeShore требует отдельной lab verification и не считается автоматически подтверждённым одним только unit/mock coverage.
- PDF-артефакт остаётся best-effort и зависит от внешнего `LibreOffice` / `soffice`.

## 11. Smoke-test commands

```powershell
python -m pytest tests/core -q
python -m pytest tests/storage -q
python -m pytest tests/drivers -q
python -m pytest tests/analytics -q
python -m pytest tests/gui -q
python -m pytest tests/reporting -q
```

Запускайте эти команды из корня репозитория в том же environment, где выполнен `pip install -e ".[dev,web]"` (или старая строка `.[dev,web,archive]` — работает так же, extra-alias без эффекта). GUI tests требуют установленного `PySide6` и `pyqtgraph`. Web dashboard в этот smoke-набор не входит и требует отдельного `.[web]` install path.

Если установка выполняется для операторской машины без dev workflow, достаточно убедиться, что эти команды проходили до развёртывания, а локальный smoke check ограничить запуском engine + GUI + mock mode.

## SQLite version requirement

CryoDAQ uses SQLite WAL mode with multiple concurrent connections (writer +
history readers + reporting + web dashboard). Due to a WAL-reset race
condition documented at https://www.sqlite.org/wal.html, the runtime must use
a safe SQLite implementation.

### Linux

On Linux, `pyproject.toml` includes `pysqlite3-binary>=0.5.4` as a base
dependency. `cryodaq.storage._sqlite` selects the implementation once at
import time:

- safe stdlib SQLite → use stdlib
- unsafe stdlib SQLite + safe `pysqlite3` → use bundled `pysqlite3`
- both unsafe/absent → `SQLiteWriter` hard-fails at startup unless the operator
  explicitly sets `CRYODAQ_ALLOW_BROKEN_SQLITE=1`

Do not mix direct `import sqlite3` connections with CryoDAQ storage code on the
same DB. All runtime readers/writers must go through `cryodaq.storage._sqlite`.
`CRYODAQ_SQLITE_SYNC=FULL` remains an emergency throughput tradeoff, not the
normal deployment path.

### Windows 11 / macOS

No `pysqlite3-binary` dependency is installed by default. The stdlib SQLite is
used; if a future platform build falls into the unsafe range, the same
`SQLiteWriter` gate refuses startup.

## Reproducible builds via lockfile

CryoDAQ pins all runtime dependencies in `requirements-lock.txt`, generated
via `pip-compile` from `pyproject.toml`. Production bundle builds install
from this lockfile so two operators building on different days get the
exact same transitive dependencies — important for safety-critical lab
deployments where a silent transitive bump can change behaviour.

### Regenerating the lockfile

After changing `pyproject.toml` dependencies:

```bash
pip install pip-tools
pip-compile --extra=dev --extra=web --output-file=requirements-lock.txt pyproject.toml
git add requirements-lock.txt
git commit -m "deps: update lockfile"
```

The build scripts (`build.sh` / `build.bat`) install from
`requirements-lock.txt` automatically before invoking PyInstaller.

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


## Qt theme on Linux

Qt style is forced to **Fusion** with an explicit dark palette pinned
to the design-system theme tokens. Both application entry points
(`cryodaq` launcher and `cryodaq-gui`) call
`cryodaq.gui.app.apply_fusion_dark_palette(app)` immediately after
`QApplication` construction and before any widget is created.

If the lab PC's system theme leaks through — white backgrounds inside
`QLineEdit` / `QSpinBox` / `QComboBox`, or a white top-level window
background — confirm that `apply_fusion_dark_palette` was reached at
startup:

```python
from PySide6.QtWidgets import QApplication
app = QApplication.instance()
assert app.property("_cryodaq_fusion_applied") is True
```

If the property is missing, the helper was bypassed (custom entry
point, PyQt5 fallback, etc.) and the GTK / Plasma native theme will
bleed into the dark UI. The fix is to call `apply_fusion_dark_palette`
before any widget is constructed on that entry path.
