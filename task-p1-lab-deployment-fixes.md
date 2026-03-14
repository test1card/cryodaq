# Задача: P1 — исправления до первого лабораторного запуска (8 дефектов)

P1 блокирует деплой на стенд. Выполнять после P0 (commit 1bd6c4e, 217 тестов).

---

## P1-01. Синхронный ZMQ блокирует GUI при аварийном отключении

**Severity:** CRITICAL
**Файлы:** `src/cryodaq/gui/widgets/keithley_panel.py`, `src/cryodaq/gui/widgets/autosweep_panel.py`

### Проблема

`_send_command()` — синхронный ZMQ REQ с таймаутом 3000мс. Вызывается в GUI-потоке при нажатии кнопки «АВАРИЙНОЕ ОТКЛ.». Если engine завис или порт недоступен — интерфейс замораживается на 3 секунды. Оператор не знает, отработала ли команда.

Дополнительно: каждый вызов создаёт новый ZMQ socket и закрывает его. При частых командах (AutoSweep — каждый шаг) — overhead на TCP handshake.

### Решение

1. **Persistent ZMQ socket** — создать один раз при инициализации панели, переиспользовать.

2. **Async отправка через QThread worker:**

```python
class ZmqCommandWorker(QThread):
    """Фоновый поток для отправки ZMQ команд."""
    finished = Signal(dict)  # результат команды
    
    def __init__(self, cmd: dict, addr: str = DEFAULT_CMD_ADDR):
        super().__init__()
        self._cmd = cmd
        self._addr = addr
    
    def run(self):
        """Выполняется в фоновом потоке."""
        try:
            result = _send_command_sync(self._cmd, self._addr)
            self.finished.emit(result)
        except Exception as exc:
            self.finished.emit({"ok": False, "error": str(exc)})
```

3. **Кнопка emergency — non-blocking UX:**
   - По нажатию: немедленно показать визуальный feedback (кнопка серая, текст «Отправка...»)
   - Отправить команду через worker
   - Callback: обновить статус (зелёный «Отключено» или красный «Engine не отвечает»)
   - Таймаут worker: 2с (не 3с — быстрее feedback)

4. **AutoSweep** импортирует `_send_command` из keithley_panel. Сделать единый модуль:
   - Создать `src/cryodaq/gui/zmq_client.py` — persistent socket + async send
   - keithley_panel и autosweep_panel импортируют из zmq_client
   - Убрать дублирование кода

### НЕ менять:
- Протокол ZMQ REQ/REP остаётся — только обёртка async
- Engine-side ZMQCommandServer — без изменений

### Тесты:
- `test_zmq_client_send_timeout`: mock socket не отвечает → timeout → ok=False, error
- `test_zmq_client_reuses_socket`: два вызова → один connect (mock verify)

---

## P1-02. AutoSweep — hardcoded compliance 40V / 3A

**Severity:** CRITICAL
**Файл:** `src/cryodaq/gui/widgets/autosweep_panel.py:415-420`

### Проблема

AutoSweep всегда отправляет `v_comp=40.0, i_comp=3.0` независимо от настроек оператора. При 4K сопротивление нагревателя ~1 Ом, I_comp=3.0A → потенциально P=9W. Оператор мог настроить I_comp=0.1A в Keithley Panel, но AutoSweep молча перезапишет.

Теперь SafetyManager проверяет лимиты (P0-03), но дефолтные compliance в AutoSweep всё равно могут превысить их.

### Решение

Добавить в AutoSweep panel два spinbox:

```python
# В layout, рядом с P_start/P_end:
self._v_comp_spin = QDoubleSpinBox()
self._v_comp_spin.setRange(0.1, 40.0)
self._v_comp_spin.setValue(10.0)  # консервативный дефолт, НЕ 40.0
self._v_comp_spin.setSuffix(" В")

self._i_comp_spin = QDoubleSpinBox()
self._i_comp_spin.setRange(0.001, 3.0)
self._i_comp_spin.setValue(0.1)  # консервативный дефолт, НЕ 3.0
self._i_comp_spin.setSuffix(" А")
```

При запуске sweep — читать из spinboxes:
```python
reply = _send_command({
    "cmd": "keithley_start",
    "channel": self._smu_channel,
    "p_target": p,
    "v_comp": self._v_comp_spin.value(),
    "i_comp": self._i_comp_spin.value(),
})
```

Дефолты — консервативные (10V, 0.1A), не максимальные. Оператор поднимает сознательно.

### Тесты:
- Нет новых тестов (GUI spinboxes, проверяется визуально)

---

## P1-03. Heartbeat detection на эвристике `/smu` in channel

**Severity:** MEDIUM
**Файл:** `src/cryodaq/core/safety_manager.py`

### Проблема

```python
if "/smu" in ch:  # string heuristic
```

1. Привязка к naming convention. Переименование канала → heartbeat деградирует.
2. Проверяется только свежесть, не `_status`. Reading с `status="sensor_error"` засчитывается как «Keithley жив».

### Решение

1. В SafetyConfig добавить:
```python
keithley_channel_patterns: list[str] = field(default_factory=lambda: [".*/smu.*"])
```

2. В safety.yaml:
```yaml
keithley_channels:
  - ".*/smu.*"
```

3. При загрузке конфига — компилировать regex один раз:
```python
self._keithley_patterns = [re.compile(p) for p in self._config.keithley_channel_patterns]
```

4. В _run_checks() проверять и свежесть И статус:
```python
for ch, (ts, _val, status) in self._latest.items():
    if any(p.match(ch) for p in self._keithley_patterns):
        if now - ts < self._config.heartbeat_timeout_s and status == "ok":
            keithley_fresh = True
            break
```

### Тесты:
- `test_heartbeat_rejects_sensor_error`: Reading с status="sensor_error" → keithley_fresh=False
- `test_heartbeat_uses_config_pattern`: custom pattern в конфиге → правильно матчится

---

## P1-04. Path("data") — cwd-зависимые пути в GUI

**Severity:** MEDIUM
**Файлы:** `main_window.py`, `autosweep_panel.py`, `overview_panel.py`

### Проблема

```python
Path("data")  # зависит от cwd при запуске
```

GUI запущен из другого каталога → экспорт, disk usage, sweep results ведут в неправильное место.

### Решение

Создать `src/cryodaq/paths.py`:
```python
import os
from pathlib import Path

def get_project_root() -> Path:
    if "CRYODAQ_ROOT" in os.environ:
        return Path(os.environ["CRYODAQ_ROOT"])
    return Path(__file__).resolve().parent.parent.parent

def get_data_dir() -> Path:
    return get_project_root() / "data"

def get_config_dir() -> Path:
    return get_project_root() / "config"
```

Заменить ВСЕ `Path("data")` на `get_data_dir()`:
- `main_window.py` — экспорт CSV/HDF5/XLSX
- `autosweep_panel.py` — сохранение результатов sweep
- `overview_panel.py` — disk usage path
- `web/server.py` — hardcoded `_DATA_DIR` (тоже заменить)

Также: `engine.py` уже использует `_PROJECT_ROOT` с `CRYODAQ_ROOT`. Привести к единому `get_project_root()`.

### Тесты:
- `test_get_data_dir_uses_env_var`: CRYODAQ_ROOT set → get_data_dir() возвращает правильный путь
- `test_get_data_dir_default_fallback`: CRYODAQ_ROOT not set → fallback на relative path

---

## P1-05. Experiment menu — только переключает кнопки, не связан с ExperimentManager

**Severity:** MEDIUM
**Файл:** `src/cryodaq/gui/main_window.py:310-319`

### Проблема

```python
def _on_start_experiment(self) -> None:
    self._start_action.setEnabled(False)
    self._stop_action.setEnabled(True)
    logger.info("Эксперимент: запись начата")
    # НЕТ: ZMQ command, нет ExperimentManager interaction
```

Меню «Эксперимент → Начать» — декоративное. ExperimentManager существует в engine, но GUI не отправляет команды.

### Решение

При «Начать эксперимент» — показать диалог (QDialog) с полями:
- Название эксперимента (QLineEdit, обязательное)
- Оператор (QLineEdit)
- Образец (QLineEdit)
- Описание (QTextEdit)

По OK → отправить ZMQ-команду:
```python
_send_command({
    "cmd": "experiment_start",
    "name": name,
    "operator": operator,
    "sample": sample,
    "description": description,
})
```

При «Остановить» → `{"cmd": "experiment_stop"}`.

В engine.py `_handle_gui_command` — добавить обработчики:
```python
if action == "experiment_start":
    return await experiment_manager.start(
        name=cmd.get("name", ""),
        operator=cmd.get("operator", ""),
        sample=cmd.get("sample", ""),
        description=cmd.get("description", ""),
    )
if action == "experiment_stop":
    return await experiment_manager.stop()
```

### Тесты:
- Нет unit-тестов (GUI dialog + ZMQ command). Проверяется визуально + через test_zmq_bridge если нужно.

---

## P1-06. aiohttp.ClientSession — создаётся заново каждый HTTP-запрос

**Severity:** MEDIUM
**Файлы:** `telegram.py`, `telegram_commands.py`, `periodic_report.py`

### Проблема

```python
async with aiohttp.ClientSession(timeout=timeout) as session:
    async with session.post(...) as resp:
```

Каждый запрос → новый TCP connection (TLS handshake). При Telegram polling 2с = 43200 handshakes/сутки.

### Решение

Для каждого из трёх классов — persistent session:

```python
class TelegramNotifier:
    def __init__(self, ...):
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout_s)
            )
        return self._session

    async def stop(self) -> None:  # или close()
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
```

Аналогично для TelegramCommandBot и PeriodicReporter.

В engine.py shutdown — вызывать `close()` для каждого.

### Тесты:
- `test_telegram_session_reused`: два send → один ClientSession created (mock verify)
- `test_telegram_session_closed_on_stop`: stop() → session.close() called

---

## P1-07. SQLite schema: TEXT timestamp вместо REAL

**Severity:** HIGH
**Файл:** `src/cryodaq/storage/sqlite_writer.py`

### Проблема

Schema: `timestamp TEXT NOT NULL` (isoformat string).
architecture.md: `timestamp REAL NOT NULL` (epoch seconds).

Последствия: +800MB/неделю overhead, медленные range queries, timezone ambiguity.

### Решение

**Новые файлы → REAL:**
```python
SCHEMA_READINGS = """
CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,
    instrument_id TEXT  NOT NULL,
    channel     TEXT    NOT NULL,
    value       REAL    NOT NULL,
    unit        TEXT    NOT NULL,
    status      TEXT    NOT NULL
);
"""
```

**Запись:**
```python
r.timestamp.timestamp()  # float epoch seconds UTC
```

**Обратная совместимость:** Старые TEXT-файлы продолжают существовать. При чтении (replay, export) — определять формат по первой строке:

```python
def _parse_timestamp(raw) -> datetime:
    if isinstance(raw, float):
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    # Legacy TEXT format
    return datetime.fromisoformat(str(raw))
```

Добавить `_parse_timestamp()` в:
- `csv_export.py`
- `hdf5_export.py`
- `xlsx_export.py`
- `replay.py`
- `web/server.py`

**НЕ мигрировать** старые .db файлы. Просто новые файлы пишутся в REAL. Старые читаются через `_parse_timestamp()`.

### Тесты:
- `test_sqlite_writes_real_timestamp`: write → read → timestamp is float
- `test_parse_timestamp_real`: float input → correct datetime
- `test_parse_timestamp_text_legacy`: isoformat string → correct datetime
- `test_csv_export_handles_both_formats`: mixed db → корректный export

---

## P1-08. SQLite — отсутствует composite index

**Severity:** MEDIUM
**Файл:** `src/cryodaq/storage/sqlite_writer.py`

### Решение

Добавить после существующих индексов:
```python
INDEX_CHANNEL_TS = """
CREATE INDEX IF NOT EXISTS idx_channel_ts ON readings (channel, timestamp);
"""
```

Вызвать в `_ensure_connection()` после `INDEX_SOURCE_DATA_TS`.

Одна строка SQL. При 4.7M строк/день — существенное ускорение запросов по каналу.

### Тесты:
- Нет отдельных (покрывается существующими sqlite тестами)

---

## Команда

| Роль | Модель | Scope |
|------|--------|-------|
| Backend Engineer | Opus | safety_manager.py (heartbeat patterns + status check), engine.py (experiment commands, aiohttp close), sqlite_writer.py (REAL timestamp + composite index), paths.py (новый), telegram*.py + periodic_report.py (persistent session) |
| GUI Engineer | Sonnet | zmq_client.py (новый, persistent socket + async), keithley_panel.py (использовать zmq_client), autosweep_panel.py (compliance spinboxes + zmq_client), main_window.py (experiment dialog + get_data_dir), overview_panel.py (get_data_dir) |
| Test Engineer | Sonnet | Тесты для P1-01,03,04,06,07 |

Dependencies: GUI ← Backend (paths.py), Backend ← GUI (zmq_client.py для autosweep тоже через ZMQ).

## Критерии приёмки

1. Кнопка «АВАРИЙНОЕ ОТКЛ.» не замораживает GUI — immediate visual feedback, async send
2. AutoSweep: V_comp и I_comp spinboxes с консервативными дефолтами (10V, 0.1A)
3. Heartbeat проверяет и свежесть И status (sensor_error → not fresh)
4. Все Path("data") заменены на get_data_dir()
5. «Эксперимент → Начать» → диалог с полями → ZMQ command → ExperimentManager
6. aiohttp session persistent, close() при shutdown
7. Новые .db файлы: timestamp REAL. Старые TEXT-файлы читаются через _parse_timestamp()
8. Composite index idx_channel_ts создаётся
9. Все 217 + новые тесты проходят
10. Обновить CLAUDE.md, README.md, CHANGELOG.md (test count, [0.10.0] entry)
