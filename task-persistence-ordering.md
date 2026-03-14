# Задача: Формализовать persistence ordering — SQLite commit BEFORE ZMQ publish

## Контекст проблемы

Сейчас Scheduler публикует readings в DataBroker, который fan-out'ит всем подписчикам одновременно (SQLiteWriter, ZMQPublisher, AlarmEngine, PluginPipeline). SQLiteWriter потребляет из своей очереди и делает batch commit раз в 1с. ZMQ доставляет мгновенно. 

**Нарушение инварианта:** оператор может видеть данные в GUI до того, как они персистированы на диск. При отключении электричества — данные, которые оператор видел, потеряны.

**Целевой инвариант:** если строка данных отобразилась в GUI — она уже на диске (SQLite WAL commit). Гарантия: power loss в любой момент не теряет данные, которые оператор видел.

## Целевая архитектура

```
Scheduler._poll_loop():
  readings = await driver.safe_read()
  await sqlite_writer.write_immediate(readings)   # WAL commit, через executor
  await broker.publish_batch(readings)             # ZMQ, Alarms, Plugins — ПОСЛЕ commit
  await safety_broker.publish_batch(readings)      # Safety — параллельно, свой канал
```

SQLiteWriter **выходит из подписчиков DataBroker**. Scheduler сначала пишет в SQLite (await, через ThreadPoolExecutor), и только после успешного commit публикует в DataBroker.

## Что менять

### 1. SQLiteWriter — новый метод `write_immediate(readings: list[Reading]) -> None`
- async, внутри вызывает `self._write_batch(readings)` через `self._executor` (ThreadPoolExecutor)
- Ждёт завершения (await). После возврата — данные на диске (WAL commit done).
- Timeout: 5 секунд. При таймауте — `logger.critical()`, данные этого batch теряются, но система НЕ зависает.
- Старый `_consume_loop` на очереди — удалить. `start(queue)` больше не нужен.
- `start()` без аргументов — только инициализация (создать файл, PRAGMA).
- `stop()` — закрыть connection, shutdown executor. Без cancel task (задачи больше нет).

### 2. Scheduler — вызов write_immediate перед publish
- Конструктор получает `sqlite_writer: SQLiteWriter | None` (None для тестов без persistence).
- В `_poll_loop()`, после `driver.safe_read()`:
  - Если `self._sqlite_writer` — `await self._sqlite_writer.write_immediate(readings)`
  - При исключении: `logger.error()`, НЕ публиковать в broker (данные не персистированы → GUI не должен видеть).
  - Затем: `await self._broker.publish_batch(readings)` — как сейчас.
  - SafetyBroker: публикация остаётся как есть (safety не зависит от persistence ordering).

### 3. engine.py — изменение wiring
- SQLiteWriter больше НЕ подписывается на DataBroker (`broker.subscribe("sqlite_writer", ...)` — удалить).
- `writer.start()` вызывается без queue.
- Scheduler получает `sqlite_writer=writer` в конструкторе.

## Чего НЕ менять
- SafetyBroker / SafetyManager — свой канал, не зависит от persistence. Безопасность выше порядка записи.
- DataBroker — интерфейс тот же, просто SQLiteWriter больше не подписчик.
- ZMQPublisher, AlarmEngine, PluginPipeline — остаются подписчиками DataBroker, без изменений.
- Формат данных, Reading dataclass — без изменений.

## Критерии приёмки

1. **Тест ordering:** SQLiteWriter.write_immediate() вызван → данные в SQLite → затем DataBroker.publish_batch() → ZMQ subscriber получает. Последовательность верифицирована.
2. **Тест failure:** SQLiteWriter.write_immediate() бросает исключение → DataBroker.publish_batch() НЕ вызван → ZMQ subscriber ничего не получает.
3. **Тест timeout:** SQLiteWriter._write_batch() зависает >5с → timeout → CRITICAL log → следующий poll cycle работает нормально.
4. **Все 151 существующих тестов проходят.** Адаптировать test_scheduler и test_sqlite_writer под новый интерфейс.
5. **Latency:** write_immediate через executor — non-blocking для event loop. Watchdog heartbeat latency не деградирует.
6. **Обновить документацию:**
   - CLAUDE.md: data flow диаграмма (Scheduler → SQLiteWriter → DataBroker), architectural invariants
   - architecture.md §4.2: обновить data flow описание

## Команда

Backend Engineer (Opus) — Scheduler, SQLiteWriter, engine.py wiring. Это safety-critical change: гарантия persistence ordering.
Test Engineer (Sonnet) — тесты ordering, failure, timeout. Адаптация существующих тестов.

## Риски

- Если disk I/O stall (bad sector, антивирус) — Scheduler блокирует poll loop на 5с (timeout). Это допустимо: 5с пропуска данных лучше чем потеря данных которые оператор видел.
- SafetyBroker продолжает получать данные напрямую, safety monitoring не затрагивается.
