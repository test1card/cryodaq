# fix-batch-02 — результаты устранения false-confidence тестов

Дата: 2026-06-22

## Таблица по находкам

| # | Файл | Тест | Статус | Причина |
|---|------|------|--------|---------|
| HIGH-1 | test_engine_leak_rate_command.py:57 | все `test_leak_rate_*` через локальный `_dispatch` | DEFERRED-NEEDS-PROD-EXTRACTION | Вызов реального `engine._handle_gui_command` требует рефакторинга production-кода (`engine.py` — монолит 3700+ строк, команда не экспортирована). Изменение src/ запрещено заданием. |
| MED-1 | test_engine_leak_rate_command.py:70 | `test_leak_rate_start_with_duration_override` | FIXED | Добавлено `assert est._window_override == 120.0`. `_window_override` устанавливается в `start_measurement(window_s=...)` — теперь тест проваливается если duration_s игнорируется. |
| HIGH-2 | test_engine_force_kill.py:8 | `test_force_kill_reads_pid_via_os_open` | FIXED | Заменён inspect.getsource grep тремя поведенческими тестами: (1) мёртвый PID → lock удалён (monkeypatch `_is_pid_alive=False`); (2) lock отсутствует → no-op; (3) битый PID → lock удалён. Примечание: PID 0 нельзя использовать — `os.kill(0, 0)` на macOS возвращает успех (сигналит группе процессов), что убивало test runner с SIGKILL. Решение: monkeypatch `_is_pid_alive`. |
| HIGH-3 | test_cooldown_alarm_v0_55_12.py:170 | `test_cooldown_alarm_critical_swallows_latch_fault_exception` | FIXED | Добавлены три утверждения: `latch_fault.assert_awaited_once()`, `alarm.state == CooldownState.FIRED`, `alarm_mgr.process` вызван с non-None (CRITICAL) event. `cdp.predict` теперь восстанавливается через try/finally (как в соседнем тесте). `alarm_mgr` захвачен (был `_`). |
| MED-2 | test_deep_review.py:14 | `test_correlation_with_tiny_timestamp_offset` | НЕ В SCOPE | Файл не указан в batch-02 touch-list (3 HIGH + 2 MED + 1 LOW по заданию охватывают только файлы batch-02). |
| LOW-1 | test_event_logger.py:65 | `test_silently_fails_on_error` | НЕ В SCOPE | Аналогично — за пределами явно указанных файлов batch-02. |

## Pytest

```
tests/core/test_engine_leak_rate_command.py  6 passed   (0.01s)
tests/core/test_engine_force_kill.py         3 passed   (0.34s)
tests/core/test_cooldown_alarm_v0_55_12.py  32 passed   (0.53s)
```

## Ruff

```
All checks passed!
```

## Изменённые файлы

- `tests/core/test_engine_leak_rate_command.py` — добавлен `assert est._window_override == 120.0`
- `tests/core/test_engine_force_kill.py` — полностью заменён: 3 поведенческих теста вместо getsource grep
- `tests/core/test_cooldown_alarm_v0_55_12.py` — усилен `test_cooldown_alarm_critical_swallows_latch_fault_exception`: захват alarm_mgr, try/finally для cdp.predict, 3 новых assert

## DEFERRED-NEEDS-PROD-EXTRACTION

**HIGH test_engine_leak_rate_command.py:57** — все `test_leak_rate_*` тестируют локальную копию `_dispatch` (строки 23–49), а не `engine._handle_gui_command`. Копия уже расходится с продакшном: продакшн валидирует `duration_s` (numeric/positive/finite), копия — нет. Чтобы тестировать реальный обработчик, нужно извлечь логику команды leak_rate в отдельную импортируемую функцию в `src/cryodaq/engine.py`. Это изменение production-кода, которое выходит за рамки задания.
