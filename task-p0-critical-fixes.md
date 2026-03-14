# Задача: P0 — критические исправления (5 дефектов)

БЛОКИРУЮЩИЕ дефекты. Ничего другого не делать пока P0 не закрыт.

---

## P0-01. Alarm pipeline не собран end-to-end (3 разрыва)

### 1a. Event type → internal state: канонизация

**Проблема:** AlarmEngine шлёт `event_type="activated"`. AlarmPanel хранит `row.state` и проверяет его в рендере, кнопке acknowledge и визуальном выделении. Но панель ожидает `"active"`, а получает `"activated"`.

**Решение:** GUI канонизирует входящий event_type в internal state. Event — это событие, state — это состояние. Маппинг:

```
event_type "activated"    → row.state = "active"
event_type "acknowledged" → row.state = "acknowledged"  
event_type "cleared"      → row.state = "cleared"
```

Этот маппинг применяется в ОДНОМ месте — при получении Reading. Весь остальной рендер (визуальное выделение строки, показ кнопки «Подтвердить», цвет) работает с internal state `"active"` / `"acknowledged"` / `"cleared"` и НЕ меняется.

**Файлы:** `alarm_panel.py` — изменить обработку входящего event:
- При получении Reading с `event_type="activated"` → сохранить `row.state = "active"`
- Все проверки `row.state == "active"` в рендере, кнопке acknowledge, визуальном выделении — оставить как есть (они уже правильные для internal state)

### 1b. AlarmEngine не публикует events в DataBroker

**Проблема:** AlarmPanel ожидает Reading на канале `alarm/{alarm_name}`. AlarmEngine вызывает notifier callbacks, но не публикует Reading в DataBroker.

**Решение:** Добавить два helper-метода в AlarmEngine:

```python
async def _publish_alarm_reading(self, event: AlarmEvent) -> None:
    """Опубликовать alarm event как Reading в DataBroker."""
    reading = Reading.now(
        channel=f"alarm/{event.alarm_name}",
        value=event.value,
        unit="",
        metadata={
            "alarm_name": event.alarm_name,
            "event_type": event.event_type,       # строка, не enum
            "severity": event.severity.value,      # строка, не enum объект!
            "threshold": event.threshold,
            "channel": event.channel,
        },
    )
    await self._broker.publish(reading)

async def _publish_alarm_count(self) -> None:
    """Опубликовать текущее количество unresolved alarms."""
    # unresolved = ACTIVE + ACKNOWLEDGED (подтверждённая но не снятая — всё ещё unresolved)
    unresolved = self.get_active_alarms()  # возвращает ACTIVE + ACKNOWLEDGED
    reading = Reading.now(
        channel="analytics/alarm_count",
        value=float(len(unresolved)),
        unit="",
        metadata={"active_names": [a.name for a in unresolved]},
    )
    await self._broker.publish(reading)
```

Вызывать `_publish_alarm_reading(event)` и `_publish_alarm_count()` из метода диспатча, сразу после изменения state.

**ВАЖНО — metadata:** Все значения в metadata должны быть строками/числами, НЕ enum-объектами. Иначе GUI сломается на `.upper()` / строковых операциях. Проверить: `event.severity.value` (строка "warning"), не `event.severity` (enum SeverityLevel.WARNING).

**AlarmEngine уже имеет self._broker.** Отдельный publish_broker не нужен. Использовать существующий.

### Защита от feedback loop

AlarmEngine подписан на DataBroker и получает все readings. Alarm readings (`alarm/...`, `analytics/...`) не должны обрабатываться как данные приборов.

**Двухуровневая защита:**

1. **filter_fn на подписке** (первичная защита, убирает шум из очереди):
   В `AlarmEngine.start()` при подписке на DataBroker использовать `filter_fn`:
   ```python
   queue = await broker.subscribe(
       "alarm_engine",
       filter_fn=lambda r: not r.channel.startswith(("alarm/", "analytics/", "system/")),
   )
   ```

2. **Guard в evaluate** (defense-in-depth):
   ```python
   if reading.channel.startswith(("alarm/", "analytics/", "system/")):
       return
   ```

### 1c. analytics/alarm_count — initial snapshot

**Проблема:** До первой тревоги alarm_count вообще не публикуется. OverviewPanel показывает «—» вместо «0».

**Решение:** В `AlarmEngine.start()`, после подписки и загрузки конфига, вызвать `_publish_alarm_count()` один раз. Это опубликует начальный `alarm_count=0`.

### Тесты P0-01:
- `test_alarm_publishes_reading_on_activate`: trigger alarm → DataBroker получает Reading на `alarm/{name}` с metadata `event_type="activated"`, `severity` — строка
- `test_alarm_publishes_reading_on_clear`: clear alarm → Reading с `event_type="cleared"`
- `test_alarm_publishes_alarm_count_on_activate`: activate → count=1
- `test_alarm_publishes_alarm_count_on_acknowledge`: activate → ack → count ОСТАЁТСЯ 1 (acknowledged ≠ resolved)
- `test_alarm_publishes_alarm_count_on_clear`: activate → ack → clear → count=0
- `test_alarm_no_feedback_loop`: alarm Reading с channel `alarm/...` не триггерит повторный evaluate
- `test_alarm_initial_count_zero`: start → DataBroker получает alarm_count=0

---

## P0-02. OverviewPanel слушает несуществующий `analytics/safety_state`

**Файлы:** `safety_manager.py`, `engine.py`

### Решение

SafetyManager публикует `analytics/safety_state` через DataBroker:

1. **При каждом `_transition()`** — после смены состояния:
   ```python
   async def _publish_state(self, reason: str = "") -> None:
       if self._data_broker is None:
           return
       r = Reading.now(
           channel="analytics/safety_state",
           value=0.0,
           unit="",
           metadata={"state": self._state.value, "reason": reason},
       )
       try:
           await self._data_broker.publish(r)
       except Exception as exc:
           logger.warning("Не удалось опубликовать safety state: %s", exc)
   ```
   Обернуть в try/except — публикация state не должна ронять safety path.

2. **При `start()`** — initial snapshot:
   ```python
   async def start(self) -> None:
       # ... existing start logic ...
       await self._publish_state("initial")
   ```
   Это гарантирует что OverviewPanel увидит SAFE_OFF сразу при запуске, без ожидания первого перехода.

**Wiring в engine.py:** Добавить `data_broker=broker` в конструктор SafetyManager. SafetyManager уже принимает SafetyBroker — DataBroker добавляется как отдельный опциональный параметр.

### analytics/keithley_status — УБРАТЬ из P0

OverviewPanel сейчас обновляет Keithley strip по power readings напрямую, не через отдельный канал. Добавление `analytics/keithley_status` — расширение scope без потребителя. Убрать из P0, вернуть в P2 если понадобится.

### Тесты P0-02:
- `test_safety_start_publishes_initial_state_safe_off`: start() → DataBroker получает Reading на `analytics/safety_state` с `state="safe_off"`
- `test_safety_publishes_state_on_transition`: transition → Reading с новым state
- `test_safety_publishes_on_fault`: FAULT → Reading с `state="fault_latched"` и reason
- `test_safety_publish_failure_does_not_crash`: broker.publish raises → SafetyManager продолжает работать

---

## P0-03. Backend не валидирует P/V/I limits при request_run

**Файлы:** `safety_manager.py`, `config/safety.yaml`

### Решение

**SafetyConfig — добавить поля с дефолтами:**
```python
max_power_w: float = 5.0
max_voltage_v: float = 40.0
max_current_a: float = 1.0
```

Дефолты обязательны — тесты и mock-режим работают без файла конфига.

**safety.yaml — добавить секцию:**
```yaml
source_limits:
  max_power_w: 5.0
  max_voltage_v: 40.0
  max_current_a: 1.0
```

**Загрузка:** В методе загрузки конфига парсить `source_limits` dict и устанавливать в SafetyConfig.

**Проверка в request_run():** ПЕРЕД переходом в RUN_PERMITTED. Порядок:
1. Базовые state checks (уже есть)
2. Preconditions (уже есть)
3. **Лимиты P/V/I** ← НОВОЕ, здесь
4. `_transition(RUN_PERMITTED)` ← только после всех проверок
5. `start_source()`

**Политика на границе:** `>` — reject, `==` — allow. То есть `p_target == max_power_w` допустимо.

```python
if p_target > self._config.max_power_w:
    return {"ok": False, "state": self._state.value,
            "error": f"P={p_target}W превышает лимит {self._config.max_power_w}W"}
if v_comp > self._config.max_voltage_v:
    return {"ok": False, "state": self._state.value,
            "error": f"V_comp={v_comp}V превышает лимит {self._config.max_voltage_v}V"}
if i_comp > self._config.max_current_a:
    return {"ok": False, "state": self._state.value,
            "error": f"I_comp={i_comp}A превышает лимит {self._config.max_current_a}A"}
```

### Тесты P0-03:
- `test_request_run_rejects_over_power_limit`: P=10W > 5W → ok=False
- `test_request_run_rejects_over_voltage_limit`: V=50V > 40V → ok=False
- `test_request_run_rejects_over_current_limit`: I=2A > 1A → ok=False
- `test_request_run_accepts_within_limits`: P=5W, V=40V, I=1A → ok=True (exactly on limit)
- `test_request_run_accepts_exact_limits`: P=5.0, V=40.0, I=1.0 → ok=True
- `test_safety_config_loads_source_limits`: загрузка safety.yaml → config.max_power_w == значение из файла

---

## P0-04. emergency_off() возвращает ok:True при FAULT_LATCHED

**Файл:** `safety_manager.py:282-290`

### Решение

```python
async def emergency_off(self) -> dict[str, Any]:
    await self._ensure_output_off()
    if self._state != SafetyState.FAULT_LATCHED:
        self._transition(SafetyState.SAFE_OFF, "Аварийное отключение оператором")
        return {"ok": True, "state": self._state.value}
    else:
        logger.warning("emergency_off: FAULT_LATCHED сохранён, выход выключен")
        return {
            "ok": True,
            "state": self._state.value,
            "latched": True,
            "warning": "Выход отключён, но авария не снята — используйте acknowledge_fault",
        }
```

### Тест P0-04:
- `test_emergency_off_returns_latched_flag_in_fault`: FAULT_LATCHED → emergency_off → response содержит `latched=True` и `warning`

---

## P0-05. Документация

**Файлы:** `README.md`, `CLAUDE.md`, `CHANGELOG.md`

### Решение

После завершения P0-01..P0-04:

1. Прогнать `pytest --co -q | tail -1` — записать точное количество тестов
2. Обновить ВСЕ упоминания количества тестов:
   - `README.md` (3 места: быстрый старт, stats таблица, tests/ описание)
   - `CLAUDE.md` (2 места: заголовок, build commands)
   - `CHANGELOG.md` (все записи где указана статистика)

3. smub — явный список мест для обновления:
   - `README.md`: GUI table строка Keithley, таблица приборов
   - `keithley_panel.py`: верхний docstring ("Два SMU-канала") → "SMU канал smua (smub planned)"
   - `autosweep_panel.py`: `addItems(["smua", "smub"])` → `addItems(["smua"])`
   - `overview_panel.py`: smub label/routing в KeithleyStrip → убрать или скрыть

4. CHANGELOG.md: добавить запись [0.9.0] с P0 fixes, точный test count

---

## Команда

| Роль | Модель | Scope |
|------|--------|-------|
| Backend Engineer | Opus | alarm.py (publish helpers + filter_fn + initial count), safety_manager.py (publish state + initial snapshot + P/V/I limits + emergency_off), engine.py (wiring: data_broker в SafetyManager), safety.yaml (source_limits) |
| GUI Engineer | Sonnet | alarm_panel.py (канонизация activated→active, НЕ менять рендер), smub cleanup в GUI файлах |
| Test Engineer | Sonnet | Все тесты из каждого раздела выше |

Dependencies: Backend → GUI (формат event_type и metadata), Backend → Test (API).

## Критерии приёмки

1. `cryodaq-engine --mock` → AlarmEngine публикует `alarm_count=0` при старте
2. Trigger alarm → AlarmPanel показывает строку в состоянии "active" (визуальная проверка в mock)
3. OverviewPanel StatusStrip показывает SAFE_OFF при запуске (initial publish)
4. ZMQ-команда `{"cmd": "keithley_start", "p_target": 100.0, ...}` → отклонена: "P > лимит"
5. ZMQ-команда с P=5.0, V=40.0, I=1.0 → принята (exactly on limit)
6. emergency_off() при FAULT_LATCHED → `"latched": True` в response
7. AlarmEngine с filter_fn: readings на `alarm/...` не попадают в evaluate
8. metadata в alarm readings: severity — строка (`"warning"`), не enum object
9. Нет smub в autosweep dropdown
10. Все 203 + новые тесты проходят
11. README, CLAUDE, CHANGELOG обновлены с точным test count
