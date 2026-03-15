# Задача: GUI polish + Phase 3 финализация

---

## Часть 1: GUI polish — вкладка «Обзор»

### 1a. Ось X графиков — человеческое время

**Проблема:** Ось X показывает Unix timestamp (1.7735050 ×1e+09) вместо человеческого времени.

**Файл:** `src/cryodaq/gui/widgets/overview_panel.py`

**Решение:** Использовать pyqtgraph `DateAxisItem` для обоих графиков (температуры и давление):

```python
from pyqtgraph import DateAxisItem

# При создании PlotWidget:
date_axis = DateAxisItem(orientation='bottom')
plot_widget = pg.PlotWidget(axisItems={'bottom': date_axis})
```

`DateAxisItem` автоматически форматирует Unix timestamp в ЧЧ:ММ:СС или ЧЧ:ММ в зависимости от масштаба.

Применить к:
- Основному графику температур
- Мини-графику давления в PressureStrip

Синхронизировать оси X обоих графиков:
```python
self._pressure_plot.setXLink(self._temp_plot)
```

### 1b. Сетка карточек — максимум 8 столбцов

**Проблема:** На широком экране 14 столбцов, имена датчиков обрезаются.

**Решение:** В `TempCardGrid` (или аналогичном классе):
- Максимум 8 столбцов
- Минимальная ширина карточки: 120px
- Если имя длиннее ширины — уменьшить шрифт до 8pt (QLabel с `setMinimumWidth`)
- `elide` через `QFontMetrics.elidedText()` если совсем не влезает

```python
MAX_COLUMNS = 8
MIN_CARD_WIDTH = 120
```

### 1c. Полоса давления — крупнее

**Проблема:** Полоса слишком узкая, значение мелкое.

**Решение:**
- Высота PressureStrip: 100px (setFixedHeight или setMinimumHeight)
- Значение давления: шрифт 16pt bold
- График давления занимает ~70% ширины полосы
- Число слева ~30% ширины

### 1d. Кнопка «Всё» — полная история из SQLite

**Проблема:** Только [1ч] [6ч] [24ч]. Нет возможности посмотреть весь cooldown от начала.

**Решение:** Добавить кнопку [Всё] после [24ч]:

```python
self._btn_all = QPushButton("Всё")
self._btn_all.clicked.connect(lambda: self._set_time_range("all"))
```

При нажатии «Всё»:
- Загрузить данные из SQLite (все записи за текущий день из `data/data_YYYY-MM-DD.db`)
- Использовать `get_data_dir()` из `paths.py` для нахождения файлов
- Decimate: если > 50000 точек — прореживать до 1 точки/мин (или каждую N-ю)
- Показать весь диапазон на графике

Загрузка из SQLite — в QThread чтобы не блокировать GUI:
```python
class SqliteLoadWorker(QThread):
    loaded = Signal(dict)  # {channel: [(t, val), ...]}
    
    def run(self):
        # sqlite3.connect(), SELECT, decimate, emit
```

### 1e. Debug mode toggle

**Проблема:** Нет возможности включить verbose logging для диагностики.

**Решение:** Добавить галочку в меню «Настройки»:

```python
# main_window.py — в меню «Настройки»:
self._debug_action = QAction("Режим отладки", self, checkable=True)
self._debug_action.toggled.connect(self._on_debug_toggle)
settings_menu.addAction(self._debug_action)
```

При включении:
1. Все loggers `cryodaq.*` переводятся на `logging.DEBUG`
2. Добавляется `RotatingFileHandler` в `logs/cryodaq_debug.log` (max 50MB, 3 backup)
3. `logs/` директория создаётся автоматически (рядом с `data/`)
4. В StatusStrip показать индикатор «🔧 DEBUG» когда режим включён

При выключении:
1. Loggers возвращаются на `logging.INFO`
2. FileHandler удаляется
3. Файл лога остаётся на диске

Состояние debug mode НЕ персистируется — при перезапуске всегда OFF. Оператор включает вручную если нужно.

Отправить ZMQ-команду `{"cmd": "set_debug", "enabled": true}` в engine чтобы engine тоже переключил уровень:
```python
# engine.py — в _handle_gui_command:
if action == "set_debug":
    level = logging.DEBUG if cmd.get("enabled", False) else logging.INFO
    logging.getLogger("cryodaq").setLevel(level)
    return {"ok": True, "level": logging.getLevelName(level)}
```

---

## Часть 2: Phase 3 финализация

### 2a. NSSM service scripts

Создать `scripts/install_service.bat`:
```batch
@echo off
echo === CryoDAQ Service Installer ===
echo.

REM Check NSSM
where nssm >nul 2>&1 || (
    echo ОШИБКА: NSSM не найден. Скачайте с https://nssm.cc/
    exit /b 1
)

REM Find Python
for /f "tokens=*" %%i in ('where python') do set PYTHON=%%i

REM Install service
nssm install CryoDAQ "%PYTHON%" "-m" "cryodaq.engine"
nssm set CryoDAQ AppDirectory "%~dp0.."
nssm set CryoDAQ AppStdout "%~dp0..\logs\service.log"
nssm set CryoDAQ AppStderr "%~dp0..\logs\service.log"
nssm set CryoDAQ AppStdoutCreationDisposition 4
nssm set CryoDAQ AppStderrCreationDisposition 4
nssm set CryoDAQ AppRotateFiles 1
nssm set CryoDAQ AppRotateBytes 10485760
nssm set CryoDAQ AppRestartDelay 3000
nssm set CryoDAQ Description "CryoDAQ Engine - система сбора данных криогенного стенда"
nssm set CryoDAQ Start SERVICE_AUTO_START

echo.
echo Служба CryoDAQ установлена. Запуск:
echo   nssm start CryoDAQ
echo.
```

Создать `scripts/uninstall_service.bat`:
```batch
@echo off
nssm stop CryoDAQ 2>nul
nssm remove CryoDAQ confirm
echo Служба CryoDAQ удалена.
```

Обновить `docs/deployment.md` — добавить секцию «Установка как Windows Service».

### 2b. Plugin developer guide

Создать `docs/plugin_guide.md` на русском, 2-3 страницы:

1. **Введение** — что такое плагин, зачем нужен
2. **Структура плагина** — .py файл + .yaml конфиг, размещение в `plugins/`
3. **API** — наследование от `AnalyticsPlugin`, метод `process(readings) → list[DerivedMetric]`, метод `configure(config)`
4. **Жизненный цикл** — загрузка при старте engine, hot-reload при изменении файла
5. **Пример: thermal_calculator.py** — разобрать по строкам
6. **Пример YAML конфига** — `plugins/thermal_calculator.yaml`
7. **Ограничения** — не блокировать event loop, не ронять engine (исключения ловятся), не хранить unbounded collections
8. **Тестирование** — как тестировать плагин отдельно от engine

### 2c. Architecture roadmap cleanup

В `docs/architecture.md` найти Phase 3 checklist. Если есть пункт «Config versioning (git hook on save)» — заменить на:
```
- [x] Config snapshot at experiment start (ExperimentManager) — реализовано
```

### 2d. CHANGELOG.md — запись [0.12.0]

Добавить новую версию с GUI polish и Phase 3 close.

---

## Команда

| Роль | Модель | Scope |
|------|--------|-------|
| GUI Engineer | Opus | overview_panel.py (DateAxisItem, карточки 8 col, давление 100px, кнопка «Всё» + SQLite loader), main_window.py (debug toggle + ZMQ command) |
| Backend Engineer | Sonnet | engine.py (set_debug command handler), scripts/ (NSSM bat), docs/deployment.md (service section) |
| Docs Engineer | Sonnet | docs/plugin_guide.md, docs/architecture.md (roadmap cleanup), CHANGELOG.md, CLAUDE.md, README.md |

## Критерии приёмки

1. Ось X графиков: ЧЧ:ММ:СС, не Unix timestamp
2. Оси X температур и давления синхронизированы
3. Максимум 8 столбцов карточек, имена не обрезаются
4. Полоса давления: высота 100px, значение 16pt bold
5. Кнопка [Всё] загружает полную историю из SQLite с decimate
6. Debug mode: галочка в настройках → DEBUG logging + файл + engine тоже переключается
7. `scripts/install_service.bat` + `scripts/uninstall_service.bat` работают
8. `docs/plugin_guide.md` — на русском, с примером thermal_calculator
9. Phase 3 checklist в architecture.md обновлён
10. Все 254 + новые тесты проходят
11. CLAUDE.md, README.md, CHANGELOG.md обновлены
