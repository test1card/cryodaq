# Задача: Critical safety fixes по результатам внешнего код-ревью

Внешний специалист провёл полный аудит репозитория. Ниже — исправления по приоритету.
**Это safety-critical изменения. Каждый фикс должен сопровождаться тестом.**

---

## CRITICAL — блокируют эксплуатацию

### Fix 1: FAULT_LATCHED не должен стираться через stop/emergency_off

**Файлы:** `src/cryodaq/core/safety_manager.py`

**Проблема:** `request_stop()` безусловно вызывает `_safe_off()`, которая переводит систему в SAFE_OFF. Если система в FAULT_LATCHED — latch стирается. `emergency_off()` тоже затирает latched state.

**Решение:**
1. Ввести метод `_ensure_output_off()` — только выключает железо (вызывает callback), НЕ меняет state.
2. `_safe_off()`: если текущее состояние FAULT_LATCHED → вызвать `_ensure_output_off()`, НЕ менять state, вернуть `ok=False, reason="Авария не сброшена"`.
3. `request_stop()`: если state == FAULT_LATCHED → вызвать `_ensure_output_off()`, вернуть `ok=False, reason="Система в аварии. Источник уже отключён. Используйте acknowledge для сброса."`.
4. `emergency_off()`: вызывать `_ensure_output_off()` ВСЕГДА. Если state != FAULT_LATCHED → переход в SAFE_OFF. Если FAULT_LATCHED → остаться в FAULT_LATCHED (железо выключено, но авария сохранена).
5. Единственный путь из FAULT_LATCHED → MANUAL_RECOVERY → READY: через `acknowledge_fault()` с причиной.

**Тесты:**
- test_fault_latched_not_cleared_by_stop: RUNNING → fault → request_stop() → state остаётся FAULT_LATCHED
- test_fault_latched_not_cleared_by_emergency: FAULT_LATCHED → emergency_off() → state остаётся FAULT_LATCHED, но output OFF
- test_fault_recovery_only_through_acknowledge: FAULT_LATCHED → acknowledge_fault() → MANUAL_RECOVERY → READY

---

### Fix 2: SafetyManager должен проверять Reading.status

**Файлы:** `src/cryodaq/core/safety_manager.py`

**Проблема:** `_collect_loop()` сохраняет `(timestamp, value)`, теряя status. Канал может быть свежим, но с status=ERROR/STALE/NaN.

**Решение:**
1. В `_latest` хранить полный Reading (не tuple).
2. В `_check_preconditions()` для critical channels: требовать `reading.status == ReadingStatus.OK`.
3. В `_run_checks()`: если reading.status != OK для critical channel → fault.
4. Отдельная проверка: `math.isnan(reading.value)` или `math.isinf(reading.value)` → fault для critical channels.
5. В `_collect_loop()`: при получении reading с status != OK — логировать warning.

**Тесты:**
- test_error_status_blocks_run: reading с status=ERROR на critical channel → preconditions fail
- test_nan_value_triggers_fault: reading с value=NaN в RUNNING → FAULT_LATCHED
- test_ok_status_passes: reading с status=OK → нормальная работа

---

### Fix 3: heartbeat_timeout_s — реализовать или удалить

**Файлы:** `src/cryodaq/core/safety_manager.py`, `config/safety.yaml`

**Проблема:** Параметр загружается, но нигде не используется. Создаёт ложную видимость защиты.

**Решение:** Реализовать host-side heartbeat supervision.
1. В `_run_checks()` добавить проверку: если Keithley source ON (state == RUNNING) и последний heartbeat_response от Keithley старше `heartbeat_timeout_s` → FAULT.
2. Heartbeat response — это любой свежий Reading от Keithley driver (канал matching `keithley*/smua/*` или по instrument_id из metadata).
3. Если Keithley-каналов в `_latest` нет и state == RUNNING → fault (нет данных от прибора с источником).

**Если реализация сложная** — альтернатива: удалить `heartbeat_timeout_s` из `config/safety.yaml` и `SafetyConfig`, добавить комментарий `# TODO: host-side heartbeat supervision`. Не оставлять мёртвый параметр.

**Тесты:**
- test_keithley_heartbeat_timeout: Keithley readings прекращаются в RUNNING → через heartbeat_timeout_s → FAULT

---

### Fix 4: dT/dt rate limit только для температурных каналов

**Файлы:** `src/cryodaq/core/safety_manager.py`

**Проблема:** `_rate_buffers` наполняются для ВСЕХ каналов. Rate limit `max_dT_dt_K_per_min` применяется к V, I, P, давлению — ложные срабатывания.

**Решение:**
1. В `_collect_loop()`: добавлять в `_rate_buffers` только каналы с `reading.unit == "K"`.
2. Альтернативно: в `config/safety.yaml` добавить `rate_limit_channels_pattern: "^(LS218|Т|T).*"` — regex для каналов, к которым применяется rate limit.
3. Не менять остальную логику — только фильтр на входе в `_rate_buffers`.

**Тесты:**
- test_rate_limit_ignores_non_temperature: reading с unit="V" и огромным dV/dt → НЕ вызывает fault
- test_rate_limit_catches_temperature: reading с unit="K" и dT/dt > limit → fault

---

## HIGH — чинить до production

### Fix 5: SafetyEvent должен хранить channel и value

**Файлы:** `src/cryodaq/core/safety_manager.py`

**Проблема:** `_transition()` создаёт SafetyEvent без channel/value. `_fault()` принимает их, но теряет.

**Решение:**
1. `_transition()`: добавить параметры `channel: str = ""`, `value: float = 0.0`, передавать в SafetyEvent.
2. `_fault()`: передавать channel и value в `_transition()`.
3. Убедиться что история событий содержит forensic context.

**Тест:**
- test_fault_event_has_channel_and_value: вызвать fault с channel="T7" и value=350.0 → в event_history последний event содержит эти данные

---

### Fix 6: smub — disable в GUI, убрать из docs как «работающую»

**Файлы:** `src/cryodaq/gui/widgets/keithley_panel.py`, `CLAUDE.md`, `README.md`

**Проблема:** GUI показывает вкладку smub, backend игнорирует channel. Ложное обещание.

**Решение:**
1. В KeithleyPanel: вкладка smub — задизейблить (setEnabled(False)), добавить label «Не реализовано / Planned».
2. В CLAUDE.md и README.md: `smua+smub` → `smua (smub planned)`. Везде где упоминается smub — пометить как planned.
3. НЕ удалять код — только disable UI и честно документировать.

---

### Fix 7: Alarm event types + acknowledge через backend

**Файлы:** `src/cryodaq/core/alarm.py`, `src/cryodaq/gui/widgets/alarm_panel.py`, `src/cryodaq/engine.py`

**Проблема:**
- Backend шлёт `"activated"`, GUI ожидает `"active"` — несогласованность.
- Acknowledge в GUI — локальный, backend не знает.

**Решение:**
1. В `alarm.py`: изменить `event_type` с `"activated"` на `"active"` (или наоборот — главное одинаково).
2. В `alarm_panel.py`: обработчик должен правильно маппить event_type.
3. Добавить команду `alarm_acknowledge` в ZMQCommandServer handler (engine.py):
   ```python
   elif cmd == "alarm_acknowledge":
       alarm_engine.acknowledge(data.get("alarm_name", ""))
       return {"ok": True}
   ```
4. В `alarm_panel.py`: кнопка acknowledge → отправляет ZMQ команду, НЕ меняет локальное состояние. Состояние обновляется только по event от backend.

**Тесты:**
- test_alarm_acknowledge_via_command: отправить команду alarm_acknowledge → AlarmEngine.acknowledge() вызван

---

### Fix 8: HDF5 export — не перезаписывать файл

**Файлы:** `src/cryodaq/gui/main_window.py`, `src/cryodaq/storage/hdf5_export.py`

**Проблема:** GUI перебирает daily DB, каждый раз вызывает exporter с одним output_path, mode="w" — каждый проход затирает предыдущий.

**Решение:**
Два варианта (выбрать один):
- **(a)** Один .h5 файл на каждую daily DB: `data_2026-03-14.h5`, `data_2026-03-15.h5`. GUI показывает список файлов.
- **(b)** Изменить HDF5Exporter: первый вызов mode="w", последующие mode="a" (append). Group name включает дату: `/2026-03-14/readings/...`

Рекомендация: вариант (a) — проще и надёжнее.

**Тест:**
- test_hdf5_multiple_daily_dbs: создать 2 daily DB, экспортировать, проверить что данные из обоих присутствуют.

---

## MEDIUM — архитектурный долг (в этом же коммите если успевается)

### Fix 9: Статус «Подключено» по liveness

**Файл:** `src/cryodaq/gui/main_window.py`

`connected = self._reading_count > 0` → добавить `self._last_reading_ts`, проверять `time.monotonic() - self._last_reading_ts < 3.0`.

### Fix 10: broker stats ключ `size` → `queued`

**Файл:** `src/cryodaq/engine.py`

Исправить `s.get("size", 0)` на `s.get("queued", 0)`.

### Fix 11: XLSX export из GUI — подключить или убрать

**Файл:** `src/cryodaq/gui/main_window.py`

Если XLSX handler — заглушка, подключить реальный вызов XLSXExporter. Или убрать пункт меню.

### Fix 12: source_data таблица — убрать если не используется

**Файлы:** `src/cryodaq/storage/sqlite_writer.py`

Если `_write_source_row()` нигде не вызывается — удалить метод и schema. Или оставить schema но добавить комментарий `# Reserved for future Keithley raw data`.

### Fix 13: Scheduler drift — фиксированный cadence

**Файл:** `src/cryodaq/core/scheduler.py`

```python
next_deadline = time.monotonic() + cfg.poll_interval_s
# ... poll ...
sleep_remaining = max(0, next_deadline - time.monotonic())
await asyncio.sleep(sleep_remaining)
```

### Fix 14: Хрупкий тест disk_monitor

**Файл:** `tests/core/test_disk_monitor.py`

Мокать `shutil.disk_usage()` вместо проверки реальной файловой системы.

---

## Команда

| Роль | Модель | Scope |
|------|--------|-------|
| Backend Engineer | Opus | Fix 1-5 (SafetyManager — это safety-critical код), Fix 10, 12, 13 |
| GUI Engineer | Sonnet | Fix 6 (smub disable), Fix 7 (alarm panel), Fix 8 (HDF5), Fix 9 (liveness), Fix 11 (XLSX) |
| Test Engineer | Sonnet | Тесты для каждого fix, Fix 14 (disk monitor test) |

**Backend Engineer получает Opus** — SafetyManager это самый чувствительный код в проекте.

## Критерии приёмки

1. FAULT_LATCHED переживает stop и emergency_off
2. Reading.status проверяется в safety path
3. heartbeat_timeout_s либо работает, либо удалён из конфига
4. dT/dt rate limit только для unit="K"
5. SafetyEvent содержит channel и value при fault
6. smub задизейблен в GUI, честно помечен как planned в docs
7. Alarm acknowledge идёт через ZMQ в backend
8. HDF5 не перезаписывает при нескольких daily DB
9. Все 194 + новые тесты проходят
10. CLAUDE.md и README.md обновлены
