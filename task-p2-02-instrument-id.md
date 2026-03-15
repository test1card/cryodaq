# Задача: P2-02 — instrument_id как first-class поле Reading

Отдельная задача. Выполнять ДО остальных P2. Breaking change на центральный dataclass.

**НЕ использовать agent team.** Один агент (Opus), последовательная работа. Параллелизм здесь опасен — все файлы зависят от одного dataclass.

---

## Проблема

`instrument_id` — ключевое поле для идентификации источника данных в SQLite. Но оно хранится в `Reading.metadata` (произвольный dict), а не как first-class field:

```python
# sqlite_writer.py
r.metadata.get("instrument_id", "unknown")  # fragile
```

Если путь создания Reading не положит `instrument_id` в metadata — записи попадут в БД как `"unknown"`.

## Решение

### 1. Изменить Reading dataclass

**Файл:** `src/cryodaq/drivers/base.py`

```python
@dataclass(frozen=True, slots=True)
class Reading:
    timestamp: datetime
    instrument_id: str        # ← НОВОЕ обязательное поле
    channel: str
    value: float
    unit: str
    status: ChannelStatus = ChannelStatus.OK
    raw: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

Также обновить `Reading.now()` classmethod (если есть):
```python
@classmethod
def now(cls, *, instrument_id: str = "", channel: str, value: float, unit: str, ...) -> Reading:
```

`instrument_id` в `now()` — keyword с дефолтом `""` (пустая строка). Это позволяет системным readings (alarm, analytics, disk_monitor) не указывать instrument_id.

### 2. Обновить все места создания Reading

Найти ВСЕ места через: `grep -rn "Reading(" src/ plugins/ tests/ --include="*.py"`

Ожидаемые места (проверить каждое):

**Драйверы (инструменты):**
- `lakeshore_218s.py` — Reading() в read_channels() и mock. instrument_id = self.name (e.g. "LS218_1")
- `keithley_2604b.py` — Reading() в read_channels() и mock. instrument_id = self.name (e.g. "Keithley_1")
- `thyracont_vsp63d.py` — Reading() в read_channels() и mock. instrument_id = self.name

**Analytics/Services:**
- `cooldown_service.py` — Reading.now() для DerivedMetric publish. instrument_id = "cooldown_predictor"
- `plugin_loader.py` — DerivedMetric → Reading conversion. instrument_id = plugin_id или "analytics"

**Core:**
- `alarm.py` — Reading.now() для alarm events и alarm_count. instrument_id = "alarm_engine"
- `safety_manager.py` — Reading.now() для safety_state. instrument_id = "safety_manager"
- `disk_monitor.py` — Reading.now() для disk_free_gb. instrument_id = "system"

**Storage:**
- `sqlite_writer.py` — УБРАТЬ `r.metadata.get("instrument_id", "unknown")`, заменить на `r.instrument_id`
- `replay.py` — Reading() при воспроизведении. instrument_id из БД поля
- `csv_export.py`, `hdf5_export.py`, `xlsx_export.py` — если создают Reading при чтении

**Тесты (ВСЕ):**
- Каждый тест создающий Reading() — добавить instrument_id. Их много (~30+).
- Найти все через grep, обновить каждый.

### 3. SQLiteWriter — прямое поле

```python
# Было:
r.metadata.get("instrument_id", "unknown")

# Стало:
r.instrument_id
```

### 4. Обратная совместимость metadata

Если кто-то ещё кладёт `instrument_id` в metadata — это нормально, просто избыточно. НЕ ломать старый код — просто поле в metadata игнорируется в пользу first-class field.

В Reading.__post_init__ или factory — НЕ копировать из metadata. Поле обязательное, caller должен передать.

---

## Порядок работы

1. Изменить `base.py` — Reading dataclass
2. Обновить `sqlite_writer.py` — использовать r.instrument_id
3. Обновить все драйверы (3 файла)
4. Обновить все core сервисы (alarm, safety_manager, disk_monitor) 
5. Обновить analytics (cooldown_service, plugin_loader)
6. Обновить storage (replay, exporters)
7. Обновить тесты (~30 файлов) — САМАЯ БОЛЬШАЯ ЧАСТЬ
8. Прогнать все 236 тестов

## Тесты

Новых тестов не нужно. Все существующие 236 тестов должны пройти — это и есть проверка что ничего не сломано.

Единственный новый тест:
- `test_reading_has_instrument_id_field`: Reading(..., instrument_id="X") → r.instrument_id == "X"

## Критерии приёмки

1. `Reading` dataclass имеет `instrument_id: str` как второе поле (после timestamp)
2. `sqlite_writer.py` использует `r.instrument_id`, не `r.metadata.get(...)`
3. Нигде в проекте нет `metadata.get("instrument_id"` — grep возвращает 0 результатов
4. Все 236 + 1 тестов проходят
5. CLAUDE.md: обновить описание Reading в module index
