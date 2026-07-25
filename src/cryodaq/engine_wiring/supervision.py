"""Надзор за долгоживущими задачами движка (A2) — вынесен из ``_run_engine``.

Тихая смерть задачи — риск №1 в ночную смену: долгоживущий цикл движка, чья
корутина падает, умирает без следа, и мониторинг/тревоги гаснут. Политика
надзора собрана здесь как импортируемый, тестируемый в изоляции код (тот же
резон, что и у ``_drain_dispatch_tasks``): решающее ядро
``_handle_supervised_task_exit`` тестируется без подъёма всего движка, а
``TaskSupervisor`` держит мутабельное состояние (``engine_stopping`` + реестры
задач), которое раньше было локальными переменными ``_run_engine``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from cryodaq.core.event_bus import EngineEvent
from cryodaq.core.safety_manager import SafetyShutdownUnverifiedError

_SUPERVISE_BACKOFF_BASE_S = 1.0  # first restart delay; doubles each crash
_SUPERVISE_BACKOFF_MAX_S = 60.0  # cap so a hard-down task never spins hot
_SAFETY_TASK_MAX_RESTARTS = 2  # safety_collect/safety_monitor: latch FAULT after this
# The safety policy is "after 2 failed restarts" — consecutive, not lifetime.
# A task that ran at least this long before dying
# had its previous incarnation recover; its restart count resets to 0 before
# incrementing, so sparse/transient crashes hours apart never false-latch
# FAULT the way a genuine rapid crash loop must.
_SUPERVISE_RESET_WINDOW_S = 300.0


async def stop_safety_manager_with_hold(
    safety_manager: Any,
    logger_: logging.Logger,
    *,
    retry_delay_s: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Retain shutdown until SafetyManager supplies a complete safe settlement.

    Caller cancellation is recorded but cannot abandon the owned stop attempt
    or turn an unverified OFF into process-exit permission. The rest of engine
    teardown starts only after this function returns successfully.
    """

    caller_cancelled = False
    while True:
        stop_task = asyncio.create_task(safety_manager.stop(), name="safety_manager_shutdown_owner")
        while not stop_task.done():
            try:
                await asyncio.shield(stop_task)
            except asyncio.CancelledError:
                caller_cancelled = True
                continue
            except Exception:
                break
        try:
            stop_task.result()
        except (SafetyShutdownUnverifiedError, asyncio.CancelledError) as exc:
            failure: BaseException | None = exc
        except Exception as exc:  # fail closed: an unknown stop failure is still HOLD
            failure = exc
        else:
            failure = None

        if failure is None:
            if caller_cancelled:
                logger_.critical("Safety shutdown caller cancellation was retained until exact settlement")
            return

        logger_.critical(
            "Safety shutdown HOLD; process and safety authority remain owned: %s",
            failure,
            exc_info=(type(failure), failure, failure.__traceback__),
        )
        delay_task = asyncio.create_task(sleep(retry_delay_s), name="safety_shutdown_hold_retry")
        while not delay_task.done():
            try:
                await asyncio.shield(delay_task)
            except asyncio.CancelledError:
                caller_cancelled = True
                continue
            except Exception:
                break
        delay_task.result()


def _handle_supervised_task_exit(
    *,
    name: str,
    task: asyncio.Task[Any],
    stopping: bool,
    restart_counts: dict[str, int],
    logger_: logging.Logger,
    on_alarm: Callable[[str, BaseException], None],
    on_restart: Callable[[float], None],
    on_fault_latch: Callable[[str, BaseException], None],
    safety_critical: bool = False,
    running_s: float = 0.0,
) -> str:
    """Decide + act on a supervised long-lived task's termination.

    A2(b): the done-callback core. An ordinary task alarms/restarts only on an
    exception. For a safety-critical task, every terminal outcome while the
    engine is live—including cancellation or a clean return—is authority loss
    and follows the same alarm/restart path. During shutdown every outcome is
    expected. After ``_SAFETY_TASK_MAX_RESTARTS`` failed safety restarts the
    supervisor latches FAULT via SafetyManager instead of looping forever.
    Side effects are injected so the policy is testable in isolation.

    ``running_s`` (F3) is how long THIS incarnation ran before dying. A run
    of at least ``_SUPERVISE_RESET_WINDOW_S`` means the previous restart
    recovered, so the count resets before incrementing — only consecutive
    rapid restarts accumulate toward the safety latch / backoff escalation.

    Returns one of ``"ignored" | "restart" | "fault_latch"``.
    """
    # Engine shutdown is the only context where every terminal outcome is
    # expected. Ordinary-task cancellation remains ignored; safety-child
    # cancellation while live is authority loss.
    if stopping:
        return "ignored"
    if task.cancelled():
        if not safety_critical:
            return "ignored"
        exc: BaseException | None = RuntimeError(f"safety-critical task {name} was cancelled unexpectedly")
    else:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            if not safety_critical:
                return "ignored"
            exc = RuntimeError(f"safety-critical task {name} was cancelled unexpectedly")
    if exc is None:
        if not safety_critical:
            return "ignored"
        exc = RuntimeError(f"safety-critical task {name} returned unexpectedly")

    logger_.critical(
        "Надзор: служебная задача %s аварийно завершилась — %r",
        name,
        exc,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    on_alarm(name, exc)  # operator-visible/audible alert via existing alarm path

    if running_s >= _SUPERVISE_RESET_WINDOW_S:
        # F3: previous incarnation recovered and ran healthily — this crash
        # is not consecutive with any earlier one. Reset before incrementing.
        restart_counts[name] = 0

    count = restart_counts.get(name, 0) + 1
    restart_counts[name] = count

    if safety_critical and count > _SAFETY_TASK_MAX_RESTARTS:
        logger_.critical(
            "Надзор: %s не восстановилась за %d перезапуска — латч FAULT",
            name,
            _SAFETY_TASK_MAX_RESTARTS,
        )
        on_fault_latch(name, exc)
        return "fault_latch"

    delay = min(_SUPERVISE_BACKOFF_BASE_S * 2 ** (count - 1), _SUPERVISE_BACKOFF_MAX_S)
    on_restart(delay)
    return "restart"


class TaskSupervisor:
    """Реестр надзора за долгоживущими задачами движка.

    Держит то, что раньше было локальными переменными ``_run_engine``:
    флаг ``engine_stopping`` (мутируется при завершении, чтобы done-callback
    не перезапускал только что отменённую задачу) и реестры задач/счётчиков
    перезапуска/времени старта. Тревога и латч FAULT идут по штатному каналу
    ``alarm_fired`` — нового канала не изобретаем.
    """

    def __init__(
        self,
        *,
        event_bus: Any,
        experiment_manager: Any,
        safety_manager: Any,
        alarm_dispatch_tasks: set[asyncio.Task[Any]],
        logger_: logging.Logger,
    ) -> None:
        self._event_bus = event_bus
        self._experiment_manager = experiment_manager
        self._safety_manager = safety_manager
        self._alarm_dispatch_tasks = alarm_dispatch_tasks
        self._logger = logger_
        self.engine_stopping = False
        self.supervised_tasks: dict[str, asyncio.Task[Any]] = {}
        self._restarts: dict[str, int] = {}
        # F3: per-task spawn timestamp, so the done-callback can tell how long
        # each incarnation ran before dying (see _SUPERVISE_RESET_WINDOW_S).
        self._spawn_times: dict[str, float] = {}

    def dispatch_supervisor_alarm(self, task_name: str, exc: BaseException) -> None:
        # Штатный путь тревоги: то же событие alarm_fired, что и у alarm-v2 —
        # GUI/оператор получают его через event_bus (звук/панель), новый канал
        # не изобретаем.
        ev = asyncio.create_task(
            self._event_bus.publish(
                EngineEvent(
                    event_type="alarm_fired",
                    timestamp=datetime.now(UTC),
                    payload={
                        "alarm_id": f"task_supervisor_{task_name}",
                        "level": "CRITICAL",
                        "message": (f"Служебная задача {task_name} аварийно завершилась: {exc!r}"),
                        "channels": [],
                        "values": [],
                    },
                    experiment_id=self._experiment_manager.active_experiment_id,
                )
            ),
            name=f"supervisor_alarm_{task_name}",
        )
        self._alarm_dispatch_tasks.add(ev)
        ev.add_done_callback(self._alarm_dispatch_tasks.discard)

    def dispatch_safety_fault_latch(self, task_name: str, exc: BaseException) -> None:
        ft = asyncio.create_task(
            self._safety_manager.latch_fault(
                reason=(
                    f"Задача мониторинга безопасности {task_name} аварийно завершилась и не восстановилась: {exc!r}"
                ),
                source=task_name,
            ),
            name=f"{task_name}_fault_latch",
        )
        self._alarm_dispatch_tasks.add(ft)
        ft.add_done_callback(self._alarm_dispatch_tasks.discard)

    def register(
        self,
        name: str,
        task: asyncio.Task[Any],
        factory: Callable[[], Any],
        *,
        safety_critical: bool = False,
        on_spawn: Callable[[asyncio.Task[Any]], None] | None = None,
    ) -> asyncio.Task[Any]:
        self.supervised_tasks[name] = task
        self._spawn_times[name] = time.monotonic()
        if on_spawn is not None:
            on_spawn(task)

        def _done(t: asyncio.Task[Any]) -> None:
            spawned_at = self._spawn_times.get(name, time.monotonic())
            _handle_supervised_task_exit(
                name=name,
                task=t,
                stopping=self.engine_stopping,
                restart_counts=self._restarts,
                logger_=self._logger,
                on_alarm=self.dispatch_supervisor_alarm,
                on_restart=lambda delay: asyncio.get_running_loop().call_later(
                    delay,
                    lambda: self.spawn(name, factory, safety_critical=safety_critical, on_spawn=on_spawn),
                ),
                on_fault_latch=self.dispatch_safety_fault_latch,
                safety_critical=safety_critical,
                running_s=time.monotonic() - spawned_at,
            )

        task.add_done_callback(_done)
        return task

    def spawn(
        self,
        name: str,
        factory: Callable[[], Any],
        *,
        safety_critical: bool = False,
        on_spawn: Callable[[asyncio.Task[Any]], None] | None = None,
    ) -> asyncio.Task[Any]:
        if self.engine_stopping:
            return self.supervised_tasks[name]
        task = asyncio.create_task(factory(), name=name)
        return self.register(name, task, factory, safety_critical=safety_critical, on_spawn=on_spawn)

    def stop(self) -> None:
        """A2: гасим надзор до отмены задач — иначе done-callback перезапустит
        только что отменённую задачу прямо во время завершения."""
        self.engine_stopping = True


def install_loop_exception_backstop(loop: asyncio.AbstractEventLoop, logger_: logging.Logger) -> None:
    """Последний рубеж: всё, что ускользнуло от надзора (fire-and-forget
    задачи, баги в самом loop), логируем CRITICAL, а не роняем молча."""

    def _backstop(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        exc = context.get("exception")
        _tname = ""
        fut = context.get("future") or context.get("task")
        if isinstance(fut, asyncio.Task):
            _tname = fut.get_name()
        logger_.critical(
            "Необработанное исключение в event loop: %s | task=%s | %r",
            context.get("message", ""),
            _tname or "-",
            exc,
        )

    loop.set_exception_handler(_backstop)
