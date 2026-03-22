# CryoDAQ

## Текущее состояние (v0.13.0)

- Источник истины по продуктовой модели: один эксперимент равен одной experiment card, и во время активного эксперимента открыта ровно одна карточка.
- Основной операторский workflow различает режимы `Эксперимент` и `Отладка`; в `Отладке` не должны появляться архивные карточки и автоматические отчёты по эксперименту.
- Целевой внешний отчётный контракт в текущем коде: `report_raw.pdf` и `report_editable.docx`.
- Dual-channel Keithley (`smua`, `smub`, `smua + smub`) остаётся актуальной моделью. Старые ожидания про disable/hide/remove `smub` устарели.
- Calibration v2: непрерывный сбор SRDG при калибровочных экспериментах, post-run pipeline (extract → downsample → Chebyshev fit), `.330` / `.340` export, runtime apply с global/per-channel policy.

CryoDAQ — система сбора данных и управления для криогенной лаборатории АКЦ ФИАН (проект Millimetron). Полнофункциональная система с experiment/report/archive/operator-log/calibration/housekeeping/shift-handover workflow.

## Текущая форма системы

- `cryodaq-engine` — headless runtime-процесс. Он опрашивает приборы, проверяет safety/alarm/interlock-логику, пишет данные и обслуживает GUI-команды.
- `cryodaq-gui` — отдельный настольный клиент. Его можно перезапускать без остановки сбора данных.
- `cryodaq` — операторский launcher для Windows.
- `cryodaq.web.server:app` — опциональный web-доступ для мониторинга.

## GUI

`MainWindow` сейчас содержит 10 операторских вкладок:

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
  - `.330` / `.340` / JSON / CSV import/export
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

- `config/instruments.yaml`
- `config/instruments.local.yaml`
- `config/alarms.yaml`
- `config/interlocks.yaml`
- `config/notifications.yaml`
- `config/housekeeping.yaml`
- `config/experiment_templates/*.yaml`

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

Актуальная runtime-опора:

- `tsp/p_const.lua`

В дереве также присутствует:

- `tsp/p_const_single.lua`

`p_const_single.lua` остаётся legacy/fallback-артефактом, но текущая архитектурная опора для runtime — `p_const.lua`.

## Структура проекта

```text
src/cryodaq/
  analytics/
  core/
  drivers/
  gui/
  reporting/
  storage/
  web/
tsp/
tests/
config/
```

Ключевые файлы для операторских workflow:

- `src/cryodaq/gui/main_window.py`
- `src/cryodaq/gui/tray_status.py`
- `src/cryodaq/gui/widgets/archive_panel.py`
- `src/cryodaq/gui/widgets/operator_log_panel.py`
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
