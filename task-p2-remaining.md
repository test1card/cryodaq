# Задача: P2 — 9 дефектов до стабильной эксплуатации

Выполнять ПОСЛЕ task-p2-02-instrument-id.md (Reading dataclass уже стабилен).

---

## P2-01. smub cleanup по всему GUI и docs

**Severity:** LOW
**Файлы:** keithley_panel.py, autosweep_panel.py, overview_panel.py, README.md

### Проблема
smub упоминается как рабочий функционал, но фактически disabled/planned.

### Решение
Grep `smub` по всему проекту. Для каждого вхождения:
- **Драйвер (keithley_2604b.py):** оставить — driver готов к smub
- **GUI:** убрать или скрыть:
  - `keithley_panel.py` docstring: "Два SMU-канала" → "SMU канал smua (smub planned)"
  - `autosweep_panel.py`: если smub ещё в dropdown `addItems` — убрать
  - `overview_panel.py`: smub label/routing в KeithleyStrip — убрать виджеты, оставить только smua
- **Docs:** "smua+smub" → "smua (smub planned)" где ещё осталось

---

## P2-03. SafetyBroker overflow callback — хрупкая lambda→coroutine

**Severity:** MEDIUM
**Файлы:** `safety_manager.py`, `safety_broker.py`

### Проблема
Lambda возвращает coroutine, SafetyBroker проверяет `asyncio.iscoroutine()`. Хрупкий контракт.

### Решение

В `safety_broker.py` — типизировать и упростить:
```python
from typing import Callable, Coroutine

def set_overflow_callback(
    self, callback: Callable[[], Coroutine[None, None, None]]
) -> None:
    self._overflow_callback = callback

# В publish():
if self._overflow_callback:
    await self._overflow_callback()  # всегда await — контракт: callback async
```

Убрать `asyncio.iscoroutine()` проверку — callback ВСЕГДА async по контракту.

### Тесты:
- `test_overflow_callback_is_awaited`: overflow → callback awaited

---

## P2-04. Disk full → нет alarm, нет FAULT

**Severity:** HIGH
**Файлы:** `scheduler.py`, `disk_monitor.py`, `safety_manager.py`

### Проблема
При disk full: SQLiteWriter падает, Scheduler логирует CRITICAL и делает continue. Данные тихо теряются. Нет alarm, нет FAULT. Оператор не знает.

### Решение

**В Scheduler:** Считать consecutive write failures. При >=3 подряд — вызвать callback:
```python
class Scheduler:
    def __init__(self, ..., on_write_failure: Callable[[str, int], Any] | None = None):
        self._on_write_failure = on_write_failure
        
    # В _poll_loop, после write failure:
    state.consecutive_write_errors += 1
    if state.consecutive_write_errors >= 3 and self._on_write_failure:
        self._on_write_failure(name, state.consecutive_write_errors)
```

**В engine.py wiring:**
```python
def _on_write_failure(name: str, count: int):
    asyncio.create_task(
        safety_manager._fault(f"Ошибка записи {name}: {count} раз подряд — возможно диск заполнен")
    )

scheduler = Scheduler(broker, sqlite_writer=writer, on_write_failure=_on_write_failure)
```

**Reset:** При успешной записи — `state.consecutive_write_errors = 0`.

### Тесты:
- `test_scheduler_calls_write_failure_callback`: 3 consecutive failures → callback вызван
- `test_scheduler_resets_on_success`: failure, failure, success, failure → callback НЕ вызван (count reset)

---

## P2-05. Keithley heartbeat failure → задержка 15с до FAULT

**Severity:** MEDIUM
**Файл:** `keithley_2604b.py`, `engine.py`

### Проблема
При сбое heartbeat driver вызывает `emergency_off()` самостоятельно. SafetyManager узнаёт через 15с (heartbeat_timeout_s) — слишком медленно.

### Решение

Добавить callback в Keithley constructor:
```python
def __init__(self, ..., on_heartbeat_failure: Callable[[str, str], None] | None = None):
    self._on_heartbeat_failure = on_heartbeat_failure
```

В `_heartbeat_loop`, при exception (после emergency_off):
```python
if self._on_heartbeat_failure:
    try:
        self._on_heartbeat_failure(self.name, str(exc))
    except Exception:
        log.exception("Ошибка в heartbeat failure callback")
```

В engine.py:
```python
def _on_keithley_heartbeat_failure(name: str, error: str):
    asyncio.create_task(
        safety_manager._fault(f"Heartbeat сбой {name}: {error}")
    )

keithley = Keithley2604B(..., on_heartbeat_failure=_on_keithley_heartbeat_failure)
```

### Тесты:
- `test_keithley_heartbeat_failure_calls_callback`: heartbeat exception → callback вызван с name и error

---

## P2-06. Replay загружает все строки в память

**Severity:** MEDIUM
**Файл:** `src/cryodaq/storage/replay.py`

### Проблема
`_load_rows()` возвращает `list` всех строк. При 4.7M строк/день — 1.4 GB в памяти.

### Решение

Заменить list на generator/cursor iteration:
```python
def _iter_rows(self, db_path: Path, ...):
    """Generator: yields rows one by one from SQLite cursor."""
    conn = sqlite3.connect(str(db_path))
    try:
        cursor = conn.execute(query, params)
        for row in cursor:
            yield row
    finally:
        conn.close()
```

В `play()` — использовать `_iter_rows()` вместо `_load_rows()`. Обработка построчно, не целиком в память.

Если `_load_rows()` используется в других местах — проверить и заменить тоже.

### Тесты:
- Существующие тесты replay должны пройти без изменений (поведение не меняется, только memory footprint)

---

## P2-07. SteadyStatePredictor — 204 строки без тестов

**Severity:** MEDIUM
**Файл:** `src/cryodaq/analytics/steady_state.py`

### Решение

Создать `tests/analytics/test_steady_state.py` с 5 тестами:

```python
def test_exponential_decay_correct_t_inf():
    """Known exponential T(t) = 10 + 90*exp(-t/5) → T_inf ≈ 10."""
    # Подать 100 точек, проверить T_inf ≈ 10 ± 0.5

def test_flat_data_settled():
    """Constant temperature → percent_settled ≈ 100%."""
    # 50 точек T = 4.5K → settled ≈ 100%

def test_noisy_data_lower_confidence():
    """Noisy signal → confidence < 1.0."""
    # T = 10 + 90*exp(-t/5) + noise(σ=5) → confidence < 0.9

def test_insufficient_data_invalid():
    """Too few points → valid=False."""
    # 3 точки → predictor returns valid=False

def test_negative_tau_graceful():
    """Non-physical data (heating) → graceful handling, not crash."""
    # Increasing temperature → valid=False or tau < 0 handled
```

Прочитать `steady_state.py` чтобы понять API (class name, method names, return type) перед написанием тестов.

---

## P2-08. SafetyManager rate-of-change — endpoints вместо sliding window

**Severity:** MEDIUM
**Файл:** `src/cryodaq/core/safety_manager.py`

### Проблема
Rate = `(last - first) / (t_last - t_first)` по всему буферу (~120 точек). Это средняя за 2 минуты, не мгновенная. Быстрый скачок 10K за 30с замаскируется медленным хвостом.

### Решение

Фиксированное 60-секундное окно:
```python
# Найти точку ≥ 60s назад
RATE_WINDOW_S = 60.0

for ch, buf in self._rate_buffers.items():
    if len(buf) < 5:
        continue
    now_ts = buf[-1][0]
    now_val = buf[-1][1]
    target_ts = now_ts - RATE_WINDOW_S
    
    # Найти ближайшую точку к target_ts
    for t, v in buf:
        if t >= target_ts:
            dt_s = now_ts - t
            if dt_s > 5.0:  # минимум 5с для расчёта
                rate_k_min = abs(now_val - v) / (dt_s / 60.0)
                if rate_k_min > self._config.max_rate_k_min:
                    ...
            break
```

RATE_WINDOW_S = 60.0 — можно добавить в SafetyConfig для настройки.

### Тесты:
- `test_rate_detects_fast_spike`: 10K за 30с среди стабильных данных → FAULT
- `test_rate_ignores_slow_drift`: 3K за 120с → ниже порога → не FAULT

---

## P2-09. Pydantic models для safety-critical config

**Severity:** MEDIUM
**Файлы:** `safety_manager.py`, `alarm.py`, `interlock.py`

### Проблема
pydantic>=2.5 в dependencies, но не используется. Конфиги парсятся через `yaml.safe_load()` без валидации. Некорректный конфиг (отрицательный timeout, строка вместо числа) → runtime crash.

### Решение

Создать `src/cryodaq/core/config_models.py`:

```python
from pydantic import BaseModel, Field, field_validator

class SourceLimits(BaseModel):
    max_power_w: float = Field(5.0, gt=0)
    max_voltage_v: float = Field(40.0, gt=0)
    max_current_a: float = Field(1.0, gt=0)

class SafetyConfig(BaseModel):
    critical_channels: list[str] = []
    stale_timeout_s: float = Field(10.0, gt=0)
    max_rate_k_min: float = Field(5.0, gt=0)
    cooldown_before_rearm_s: float = Field(60.0, ge=0)
    heartbeat_timeout_s: float = Field(15.0, gt=0)
    keithley_channel_patterns: list[str] = [".*/smu.*"]
    source_limits: SourceLimits = SourceLimits()
    
    @field_validator("stale_timeout_s")
    @classmethod
    def stale_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("stale_timeout_s must be > 0")
        return v

class AlarmCondition(BaseModel):
    name: str
    channel_pattern: str
    condition: str  # "< 10" or "> 300"
    severity: str = "warning"
    hysteresis: float = Field(0.0, ge=0)
    message: str = ""

class InterlockCondition(BaseModel):
    name: str
    channel_pattern: str
    threshold: float
    comparison: str  # ">" or "<"
    action: str  # "emergency_off" or "stop_source"
    cooldown_s: float = Field(60.0, ge=0)
```

В SafetyManager.load_config():
```python
from cryodaq.core.config_models import SafetyConfig

raw = yaml.safe_load(fh) or {}
try:
    self._config = SafetyConfig(**raw)
except ValidationError as exc:
    logger.critical("Некорректная конфигурация safety: %s", exc)
    raise SystemExit(f"Safety config validation failed: {exc}") from exc
```

Аналогично для AlarmEngine и InterlockEngine.

**При ошибке валидации — engine НЕ запускается.** `SystemExit` с понятным сообщением.

### Тесты:
- `test_safety_config_validates_positive_stale`: stale_timeout_s=-1 → ValidationError
- `test_safety_config_validates_source_limits`: max_power_w=0 → ValidationError
- `test_safety_config_loads_from_yaml`: valid yaml → SafetyConfig object
- `test_alarm_config_validates`: missing name → ValidationError
- `test_engine_exits_on_bad_config`: invalid safety.yaml → SystemExit

---

## P2-10. Telegram HTTP 429 — нет retry

**Severity:** LOW
**Файл:** `src/cryodaq/notifications/telegram.py`

### Решение

В методе отправки, после получения response:
```python
if resp.status == 429:
    try:
        body = await resp.json()
        retry_after = body.get("parameters", {}).get("retry_after", 5)
    except Exception:
        retry_after = 5
    logger.warning("Telegram rate limit, retry after %ds", retry_after)
    await asyncio.sleep(retry_after)
    # Один retry
    async with session.post(self._api_url, json=payload) as resp2:
        if resp2.status != 200:
            logger.error("Telegram retry failed: %d", resp2.status)
```

Один retry, не бесконечный цикл. При повторном 429 — залогировать и сдаться.

### Тесты:
- `test_telegram_retries_on_429`: mock 429 response → sleep → retry → success

---

## Команда

| Роль | Модель | Scope |
|------|--------|-------|
| Backend Engineer | Opus | safety_manager.py (rate-of-change window, overflow callback), scheduler.py (write failure callback), keithley_2604b.py (heartbeat callback), replay.py (generator), config_models.py (новый, pydantic), engine.py (wiring callbacks), telegram.py (429 retry) |
| GUI Engineer | Sonnet | smub cleanup (keithley_panel, autosweep_panel, overview_panel), docs (README) |
| Test Engineer | Sonnet | test_steady_state.py (5 тестов), тесты для P2-03,04,05,08,09,10 |

## Критерии приёмки

1. Нет smub в GUI dropdowns и overview strip
2. SafetyBroker overflow callback — всегда await, без iscoroutine check
3. Scheduler: 3 consecutive write failures → safety FAULT
4. Keithley heartbeat failure → немедленный callback → FAULT (не ждать 15с)
5. Replay: memory constant при большом файле (generator, не list)
6. SteadyStatePredictor: 5 тестов покрывают happy path + edge cases
7. Rate-of-change: 60с скользящее окно, не endpoints всего буфера
8. Pydantic: невалидный safety.yaml → engine отказывается стартовать с понятной ошибкой
9. Telegram: 429 → retry after delay → success
10. Все 237+ тестов проходят
11. CLAUDE.md, README.md, CHANGELOG.md обновлены
