"""Scheduler — планировщик опроса приборов.

Для каждого InstrumentDriver создаёт изолированную asyncio-задачу.
Исключение: приборы с одним явным registry-owned BusDescriptor группируются
в один task и опрашиваются последовательно. Текст resource не является
источником topology/authority.

Таймаут одного прибора не блокирует приборы на другой шине.
При ошибке соединения — экспоненциальный backoff с переподключением.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Any

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import InstrumentDriver, Reading
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    BusRecoveryLevel,
    DriverRuntimeBinding,
    DriverTrustClass,
    SharedBusParticipant,
    SharedBusRecoveryCoordinator,
    is_issued_runtime_binding,
)

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 1.0
MAX_BACKOFF_S = 60.0
INITIAL_BACKOFF_S = 1.0
READ_TIMEOUT_S = 10.0

# Standalone (non-GPIB) instrument disconnect backoff
_STANDALONE_INITIAL_BACKOFF_S = 30.0
_STANDALONE_MAX_BACKOFF_S = 300.0
_DISCONNECT_TIMEOUT_S = 5.0


class ReviewedSourceSettlementIncomplete(RuntimeError):
    """Reviewed-source authority still owns live or failed cleanup work."""


class _ReviewedConnectAbandoned(RuntimeError):
    pass


@dataclass
class _ReviewedConnectAttempt:
    generation: object | None = None
    owner_task: asyncio.Task[None] | None = None
    abandon_requested: bool = False
    generation_issued: bool = False
    driver_io_started: bool = False
    connected_committed: bool = False
    settled_safe: bool = False
    operation_error: BaseException | None = None
    failure: BaseException | None = None
    abandon_event: asyncio.Event = field(default_factory=asyncio.Event)
    revocation_observed: asyncio.Event = field(default_factory=asyncio.Event)
    driver_task: asyncio.Task[None] | None = None
    cleanup_retry_task: asyncio.Task[bool] | None = None


@dataclass
class InstrumentConfig:
    """Конфигурация опроса одного прибора."""

    driver: InstrumentDriver
    poll_interval_s: float | None = None
    read_timeout_s: float | None = None
    connect_timeout_s: float | None = None
    enabled: bool = True
    resource_str: str = ""
    runtime_binding: DriverRuntimeBinding | None = None

    def __post_init__(self) -> None:
        from cryodaq.drivers.registry import runtime_binding_for_driver

        supplied = self.runtime_binding
        canonical = runtime_binding_for_driver(self.driver)
        if canonical is not None:
            if supplied is not None and supplied is not canonical:
                raise ValueError("canonical registry runtime binding cannot be replaced")
            binding = canonical
        else:
            binding = supplied
            if binding is not None:
                raise ValueError("unregistered driver cannot supply runtime binding directly")
        if binding is not None and binding.driver is not self.driver:
            raise ValueError("runtime binding belongs to a different driver instance")
        if binding is not None:
            timing = binding.timing
            for field_name in ("poll_interval_s", "read_timeout_s", "connect_timeout_s"):
                supplied = getattr(self, field_name)
                expected = getattr(timing, field_name)
                if supplied is not None and float(supplied) != expected:
                    raise ValueError(f"legacy {field_name} contradicts registry runtime binding")
                setattr(self, field_name, expected)
            self.runtime_binding = binding
        else:
            self.poll_interval_s = (
                DEFAULT_POLL_INTERVAL_S if self.poll_interval_s is None else float(self.poll_interval_s)
            )
            self.read_timeout_s = READ_TIMEOUT_S if self.read_timeout_s is None else float(self.read_timeout_s)
            self.connect_timeout_s = READ_TIMEOUT_S if self.connect_timeout_s is None else float(self.connect_timeout_s)
            timing = AcquisitionTiming(
                connect_timeout_s=self.connect_timeout_s,
                read_timeout_s=self.read_timeout_s,
                poll_interval_s=self.poll_interval_s,
            )
            self.connect_timeout_s = timing.connect_timeout_s
            self.read_timeout_s = timing.read_timeout_s
            self.poll_interval_s = timing.poll_interval_s


@dataclass
class _InstrumentState:
    """Внутреннее состояние задачи опроса."""

    config: InstrumentConfig
    task: asyncio.Task[None] | None = None
    consecutive_errors: int = 0
    total_reads: int = 0
    total_errors: int = 0
    backoff_s: float = field(default=INITIAL_BACKOFF_S)
    reviewed_source_generation: object | None = None
    reviewed_source_settlement_task: asyncio.Task[None] | None = None
    reviewed_source_attempt: _ReviewedConnectAttempt | None = None
    reviewed_source_disconnect_task: asyncio.Task[bool] | None = None
    reviewed_source_disconnect_required: bool = False
    reviewed_source_disconnect_revision: int = 0
    reviewed_source_disconnect_task_revision: int | None = None


class Scheduler:
    """Планировщик: explicit shared-bus binding → один последовательный task.

    Использование::

        scheduler = Scheduler(broker)
        scheduler.add(InstrumentConfig(driver=lakeshore1))
        scheduler.add(InstrumentConfig(driver=lakeshore2))
        scheduler.add(InstrumentConfig(driver=keithley))
        await scheduler.start()
        ...
        await scheduler.stop()
    """

    def __init__(
        self,
        broker: DataBroker,
        *,
        safety_broker: Any | None = None,
        sqlite_writer: Any | None = None,
        adaptive_throttle: Any | None = None,
        calibration_acquisition: Any | None = None,
        reviewed_source_connect_begin: (
            Callable[[InstrumentDriver, DriverRuntimeBinding, str], Awaitable[object]] | None
        ) = None,
        reviewed_source_connect_complete: (
            Callable[[InstrumentDriver, DriverRuntimeBinding, object, str], Awaitable[bool]] | None
        ) = None,
        reviewed_source_uncertain: (
            Callable[[InstrumentDriver, DriverRuntimeBinding, object, str], Awaitable[None]] | None
        ) = None,
        reviewed_source_connect_abandon: (
            Callable[[InstrumentDriver, DriverRuntimeBinding, object, str], None] | None
        ) = None,
        reviewed_source_disconnect: (
            Callable[[InstrumentDriver, DriverRuntimeBinding, object | None, str], Awaitable[bool]] | None
        ) = None,
        drain_timeout_s: float = 5.0,
        shared_bus_clock: Callable[[], float] | None = None,
        shared_bus_sleep: Callable[[float], Awaitable[None]] | None = None,
        persistence_commit_observer: Callable[[object], None] | None = None,
        persistence_rejection_observer: Callable[[int, str], None] | None = None,
        persistence_ambiguity_observer: Callable[[], None] | None = None,
    ) -> None:
        self._broker = broker
        self._safety_broker = safety_broker
        self._sqlite_writer = sqlite_writer
        self._adaptive_throttle = adaptive_throttle
        self._calibration_acquisition = calibration_acquisition
        self._reviewed_source_connect_begin = reviewed_source_connect_begin
        self._reviewed_source_connect_complete = reviewed_source_connect_complete
        self._reviewed_source_uncertain = reviewed_source_uncertain
        self._reviewed_source_connect_abandon = reviewed_source_connect_abandon
        self._reviewed_source_disconnect = reviewed_source_disconnect
        self._drain_timeout_s = drain_timeout_s
        self._shared_bus_clock = shared_bus_clock
        self._shared_bus_sleep = shared_bus_sleep
        self._persistence_commit_observer = persistence_commit_observer
        self._persistence_rejection_observer = persistence_rejection_observer
        self._persistence_ambiguity_observer = persistence_ambiguity_observer
        self._instruments: dict[str, _InstrumentState] = {}
        self._running = False
        self._shared_bus_tasks: dict[str, asyncio.Task[None]] = {}
        self._unsettled_bus_operations: dict[str, asyncio.Task[Any]] = {}
        self._terminal_bus_authority: set[str] = set()

    def add(self, config: InstrumentConfig) -> None:
        """Зарегистрировать прибор. Вызывать до start()."""
        name = config.driver.name
        if name in self._instruments:
            raise ValueError(f"Прибор '{name}' уже зарегистрирован")
        state = _InstrumentState(config=config)
        binding = config.runtime_binding
        if (
            binding is not None
            and binding.trust_class is DriverTrustClass.REVIEWED_SOURCE
            and is_issued_runtime_binding(binding)
            and binding.driver is config.driver
        ):
            # A source already connected before scheduler ownership has no
            # scheduler-issued generation.  It must be proven OFF and
            # disconnected before any connect or read can be attempted.
            state.reviewed_source_disconnect_required = config.driver.connected is True
        self._instruments[name] = state
        logger.info("Прибор '%s' добавлен (интервал=%.1fs)", name, config.poll_interval_s)

    async def _disconnect_driver(
        self,
        driver: InstrumentDriver,
        *,
        timeout_s: float = _DISCONNECT_TIMEOUT_S,
        context: str = "",
    ) -> bool:
        """Disconnect with a bounded wait so wedged transports do not hang recovery."""
        state = self._instruments.get(driver.name)
        binding = self._reviewed_binding(state) if state is not None else None
        configured_binding = state.config.runtime_binding if state is not None else None
        configured_as_reviewed = (
            configured_binding is not None and configured_binding.trust_class is DriverTrustClass.REVIEWED_SOURCE
        )
        if configured_as_reviewed:
            # The InstrumentConfig binding was sealed when this state was
            # created.  A later registry removal/replacement must never
            # downgrade a reviewed source into the raw disconnect path.
            if binding is None or self._reviewed_source_disconnect is None or state is None:
                logger.critical(
                    "Reviewed source '%s' cannot be disconnected without matching sealed authority (%s)",
                    driver.name,
                    context,
                )
                return False
            state.reviewed_source_disconnect_required = True
            try:
                task = state.reviewed_source_disconnect_task
                if task is not None and task.done():
                    task_revision = state.reviewed_source_disconnect_task_revision
                    state.reviewed_source_disconnect_task = None
                    state.reviewed_source_disconnect_task_revision = None
                    try:
                        if (
                            task.result() is True
                            and task_revision == state.reviewed_source_disconnect_revision
                            and state.reviewed_source_disconnect_required is False
                            and getattr(driver, "connected", None) is False
                        ):
                            state.reviewed_source_disconnect_required = False
                            return True
                    except BaseException:
                        logger.exception(
                            "Reviewed source '%s' retained disconnect failed (%s)",
                            driver.name,
                            context,
                        )
                    # A completed failed task owns no work.  Consume it now so
                    # this invocation can create one exact retry owner.
                    task = None
                if task is None:
                    task_revision = state.reviewed_source_disconnect_revision
                    task = asyncio.create_task(
                        self._disconnect_reviewed_exact(
                            state,
                            context,
                            revision=task_revision,
                        ),
                        name=f"reviewed_disconnect_{driver.name}",
                    )
                    state.reviewed_source_disconnect_task = task
                    state.reviewed_source_disconnect_task_revision = task_revision
                done, _pending = await asyncio.wait({task}, timeout=timeout_s)
                if not done:
                    logger.critical(
                        "Reviewed source '%s' disconnect remains owned after %.1fs (%s)",
                        driver.name,
                        timeout_s,
                        context,
                    )
                    return False
                task_revision = state.reviewed_source_disconnect_task_revision
                state.reviewed_source_disconnect_task = None
                state.reviewed_source_disconnect_task_revision = None
                if (
                    task.result() is True
                    and task_revision == state.reviewed_source_disconnect_revision
                    and state.reviewed_source_disconnect_required is False
                    and getattr(driver, "connected", None) is False
                ):
                    state.reviewed_source_disconnect_required = False
                    return True
                return False
            except TimeoutError:
                logger.critical(
                    "Таймаут безопасного отключения reviewed source '%s' за %.1fs (%s)",
                    driver.name,
                    timeout_s,
                    context,
                )
                return False
            except asyncio.CancelledError:
                raise
            except Exception:
                if state is not None and state.reviewed_source_disconnect_task is not None:
                    if state.reviewed_source_disconnect_task.done():
                        state.reviewed_source_disconnect_task = None
                        state.reviewed_source_disconnect_task_revision = None
                logger.exception(
                    "Ошибка безопасного отключения reviewed source '%s' (%s)",
                    driver.name,
                    context,
                )
                return False
        try:
            await asyncio.wait_for(driver.disconnect(), timeout=timeout_s)
            return True
        except TimeoutError:
            if context:
                logger.warning(
                    "Таймаут отключения '%s' за %.1fs (%s)",
                    driver.name,
                    timeout_s,
                    context,
                )
            else:
                logger.warning("Таймаут отключения '%s' за %.1fs", driver.name, timeout_s)
            return False
        except Exception:
            if context:
                logger.exception("Ошибка отключения '%s' (%s)", driver.name, context)
            else:
                logger.exception("Ошибка отключения '%s'", driver.name)
            return False

    @staticmethod
    def _reviewed_binding(state: _InstrumentState) -> DriverRuntimeBinding | None:
        binding = state.config.runtime_binding
        if (
            binding is not None
            and binding.trust_class is DriverTrustClass.REVIEWED_SOURCE
            and is_issued_runtime_binding(binding)
            and binding.driver is state.config.driver
        ):
            return binding
        return None

    async def _mark_reviewed_uncertain(
        self,
        state: _InstrumentState,
        context: str,
        generation: object | None = None,
    ) -> None:
        binding = self._reviewed_binding(state)
        if binding is None:
            raise RuntimeError("reviewed source lost exact sealed runtime binding")
        if generation is None:
            generation = state.reviewed_source_generation
        if generation is None:
            return
        callback = self._reviewed_source_uncertain
        if callback is None:
            raise RuntimeError("reviewed source uncertainty requires SafetyManager authority")
        await callback(state.config.driver, binding, generation, context)
        if generation is state.reviewed_source_generation:
            state.reviewed_source_generation = None

    async def _disconnect_reviewed_exact(
        self,
        state: _InstrumentState,
        context: str,
        *,
        revision: int | None = None,
    ) -> bool:
        binding = self._reviewed_binding(state)
        callback = self._reviewed_source_disconnect
        if binding is None or callback is None:
            return False
        if revision is None:
            revision = state.reviewed_source_disconnect_revision
        state.reviewed_source_disconnect_required = True
        result = await callback(state.config.driver, binding, state.reviewed_source_generation, context)
        disconnected = getattr(state.config.driver, "connected", None) is False
        if result is True and disconnected:
            state.reviewed_source_generation = None
            if revision == state.reviewed_source_disconnect_revision:
                state.reviewed_source_disconnect_required = False
            return True
        if result is True and not disconnected:
            logger.critical(
                "Reviewed source '%s' returned disconnect success without connected=False (%s)",
                state.config.driver.name,
                context,
            )
        return False

    @staticmethod
    def _invalidate_reviewed_disconnect_receipt(state: _InstrumentState) -> None:
        """Require a receipt newer than a still-live ambiguous operation."""
        state.reviewed_source_disconnect_revision += 1
        state.reviewed_source_disconnect_required = True

    def _adjudicate_reviewed_attempt(
        self,
        state: _InstrumentState,
        *,
        raise_operation_error: bool = False,
    ) -> bool:
        attempt = state.reviewed_source_attempt
        if attempt is None:
            return True
        task = attempt.owner_task
        if task is None or not task.done():
            return False
        try:
            task.result()
        except BaseException as exc:
            attempt.failure = exc
        if attempt.failure is not None:
            raise ReviewedSourceSettlementIncomplete(
                f"reviewed source settlement failed: {attempt.failure}"
            ) from attempt.failure
        if not (attempt.connected_committed or attempt.settled_safe):
            raise ReviewedSourceSettlementIncomplete("reviewed source settlement has no safe terminal result")
        operation_error = attempt.operation_error
        state.reviewed_source_attempt = None
        state.reviewed_source_settlement_task = None
        if attempt.settled_safe:
            state.reviewed_source_generation = None
        if raise_operation_error and operation_error is not None:
            raise RuntimeError(f"reviewed source connect failed: {operation_error}") from operation_error
        return True

    async def _own_reviewed_connect(
        self,
        state: _InstrumentState,
        attempt: _ReviewedConnectAttempt,
        binding: DriverRuntimeBinding,
        context: str,
    ) -> None:
        driver = state.config.driver
        begin = self._reviewed_source_connect_begin
        complete = self._reviewed_source_connect_complete
        assert begin is not None and complete is not None
        try:
            generation = await begin(driver, binding, context)
            attempt.generation = generation
            attempt.generation_issued = True
            state.reviewed_source_generation = generation
            if attempt.abandon_requested:
                raise _ReviewedConnectAbandoned("connect abandoned after generation issue")
            attempt.driver_io_started = True
            state.reviewed_source_disconnect_required = True
            connect_task = asyncio.create_task(
                driver.connect(),
                name=f"reviewed_driver_connect_{driver.name}",
            )
            attempt.driver_task = connect_task
            abandon_wait = asyncio.create_task(attempt.abandon_event.wait())
            done, _pending = await asyncio.wait(
                {connect_task, abandon_wait},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if connect_task not in done:
                raise _ReviewedConnectAbandoned("connect abandoned during driver I/O")
            abandon_wait.cancel()
            await asyncio.gather(abandon_wait, return_exceptions=True)
            connect_task.result()
            if attempt.abandon_requested:
                raise _ReviewedConnectAbandoned("connect abandoned after driver I/O")
            committed = await complete(driver, binding, generation, context)
            if committed is not True:
                raise RuntimeError("connect completed without exact both-channel OFF proof")
            if attempt.abandon_requested:
                raise _ReviewedConnectAbandoned("connect abandoned during completion")
            attempt.connected_committed = True
            state.reviewed_source_disconnect_required = False
            return
        except BaseException as exc:
            attempt.operation_error = exc

        cleanup_failures: list[BaseException] = []
        if attempt.generation_issued and attempt.generation is not None:
            try:
                await self._mark_reviewed_uncertain(
                    state,
                    f"{context}: abandoned or failed connect",
                    generation=attempt.generation,
                )
                state.reviewed_source_generation = None
            except BaseException as exc:
                cleanup_failures.append(exc)
            finally:
                attempt.revocation_observed.set()
        disconnect_safe = not attempt.driver_io_started
        if attempt.driver_io_started:
            try:
                if attempt.driver_task is not None and not attempt.driver_task.done():
                    try:
                        await attempt.driver_task
                    except BaseException:
                        pass
                disconnect_safe = await self._disconnect_reviewed_exact(
                    state,
                    f"{context}: retained connect cleanup",
                )
                if not disconnect_safe:
                    cleanup_failures.append(RuntimeError("reviewed source disconnect was not exact True"))
            except BaseException as exc:
                disconnect_safe = False
                cleanup_failures.append(exc)
        # Exact full OFF+disconnect supersedes a failed uncertainty callback:
        # the disconnect authority revokes the same generation under its lock.
        if disconnect_safe:
            attempt.failure = None
            attempt.settled_safe = True
            return
        if cleanup_failures:
            attempt.failure = cleanup_failures[0]
            return

    async def _settle_failed_reviewed_attempt(
        self,
        state: _InstrumentState,
        attempt: _ReviewedConnectAttempt,
        context: str,
    ) -> bool:
        revocation_safe = not attempt.generation_issued
        if attempt.generation_issued and attempt.generation is not None:
            try:
                await self._mark_reviewed_uncertain(state, context, generation=attempt.generation)
                revocation_safe = True
            except BaseException as exc:
                attempt.failure = exc
        if attempt.driver_io_started:
            try:
                # Full exact disconnect revokes the same generation itself,
                # so it is authoritative even if narrow revocation failed.
                return await self._disconnect_reviewed_exact(state, context)
            except BaseException as exc:
                attempt.failure = exc
                return False
        return revocation_safe

    async def _retry_failed_reviewed_attempt(
        self,
        state: _InstrumentState,
        attempt: _ReviewedConnectAttempt,
        context: str,
        *,
        timeout_s: float,
    ) -> bool:
        if attempt.owner_task is None or not attempt.owner_task.done():
            return False
        retry = attempt.cleanup_retry_task
        if retry is not None and retry.done():
            attempt.cleanup_retry_task = None
            try:
                if retry.result() is True:
                    attempt.failure = None
                    attempt.settled_safe = True
                    state.reviewed_source_generation = None
                    state.reviewed_source_disconnect_required = False
                    return True
            except BaseException as exc:
                attempt.failure = exc
            retry = None
        if retry is None:
            retry = asyncio.create_task(
                self._settle_failed_reviewed_attempt(state, attempt, context),
                name=f"reviewed_cleanup_retry_{state.config.driver.name}",
            )
            attempt.cleanup_retry_task = retry
        done, _pending = await asyncio.wait({retry}, timeout=timeout_s)
        if not done:
            return False
        attempt.cleanup_retry_task = None
        try:
            settled = retry.result() is True
        except BaseException as exc:
            attempt.failure = exc
            settled = False
        if not settled:
            if attempt.failure is None:
                attempt.failure = RuntimeError("reviewed source cleanup retry did not prove safe")
            return False
        attempt.failure = None
        attempt.settled_safe = True
        state.reviewed_source_generation = None
        state.reviewed_source_disconnect_required = False
        return True

    async def _settle_reviewed_poll_barrier(
        self,
        state: _InstrumentState,
        context: str,
    ) -> bool:
        """Boundedly retry failed retained cleanup before any new I/O."""
        attempt = state.reviewed_source_attempt
        if attempt is None:
            return True
        try:
            return self._adjudicate_reviewed_attempt(state)
        except ReviewedSourceSettlementIncomplete:
            logger.exception(
                "Reviewed source '%s' settlement failed (%s)",
                state.config.driver.name,
                context,
            )
        if not await self._retry_failed_reviewed_attempt(
            state,
            attempt,
            context,
            timeout_s=state.config.connect_timeout_s,
        ):
            return False
        try:
            return self._adjudicate_reviewed_attempt(state)
        except ReviewedSourceSettlementIncomplete:
            logger.exception(
                "Reviewed source '%s' cleanup retry remained unsettled (%s)",
                state.config.driver.name,
                context,
            )
            return False

    async def _settle_reviewed_read_uncertainty(
        self,
        state: _InstrumentState,
        context: str,
    ) -> bool:
        """Revoke and disconnect on the first ambiguous reviewed read."""
        if self._reviewed_binding(state) is None:
            return True
        revocation_error: BaseException | None = None
        try:
            await self._mark_reviewed_uncertain(state, context)
        except BaseException as exc:
            revocation_error = exc
            logger.exception("Reviewed source uncertainty revocation failed (%s)", context)
        disconnected = await self._disconnect_driver(
            state.config.driver,
            timeout_s=state.config.connect_timeout_s,
            context=context,
        )
        if disconnected:
            return True
        if revocation_error is not None:
            logger.critical(
                "Reviewed source remains unsettled after revocation and disconnect failures (%s): %s",
                context,
                revocation_error,
            )
        return False

    async def _connect_driver(self, state: _InstrumentState, *, context: str) -> None:
        driver = state.config.driver
        binding = self._reviewed_binding(state)
        if binding is None:
            await asyncio.wait_for(driver.connect(), timeout=state.config.connect_timeout_s)
            return

        begin = self._reviewed_source_connect_begin
        complete = self._reviewed_source_connect_complete
        if (
            begin is None
            or complete is None
            or self._reviewed_source_uncertain is None
            or self._reviewed_source_connect_abandon is None
            or self._reviewed_source_disconnect is None
        ):
            raise RuntimeError("reviewed source connect requires complete SafetyManager lifecycle authority")
        if state.reviewed_source_disconnect_required or state.reviewed_source_disconnect_task is not None:
            if not await self._disconnect_driver(
                driver,
                timeout_s=state.config.connect_timeout_s,
                context=f"{context}: settle prior disconnect",
            ):
                raise ReviewedSourceSettlementIncomplete("reviewed source disconnect did not prove safe")
        if not self._adjudicate_reviewed_attempt(state):
            raise ReviewedSourceSettlementIncomplete("reviewed source has an unsettled prior connect")

        attempt = _ReviewedConnectAttempt()
        state.reviewed_source_attempt = attempt
        owner = asyncio.create_task(
            self._own_reviewed_connect(state, attempt, binding, context),
            name=f"reviewed_connect_owner_{driver.name}",
        )
        attempt.owner_task = owner
        state.reviewed_source_settlement_task = owner
        try:
            done, _pending = await asyncio.wait(
                {owner},
                timeout=state.config.connect_timeout_s,
            )
        except asyncio.CancelledError:
            self._request_reviewed_connect_abandon(state, attempt, binding, context)
            raise
        if not done:
            self._request_reviewed_connect_abandon(state, attempt, binding, context)
            raise TimeoutError(f"reviewed source connect exceeded {state.config.connect_timeout_s:.1f}s")
        self._adjudicate_reviewed_attempt(state, raise_operation_error=True)

    def _request_reviewed_connect_abandon(
        self,
        state: _InstrumentState,
        attempt: _ReviewedConnectAttempt,
        binding: DriverRuntimeBinding,
        context: str,
    ) -> None:
        attempt.abandon_requested = True
        attempt.abandon_event.set()
        generation = attempt.generation
        if not attempt.generation_issued or generation is None:
            return
        try:
            self._revoke_reviewed_generation_now(
                state,
                binding,
                generation,
                f"{context}: caller abandoned",
            )
        except BaseException as exc:
            attempt.failure = exc
            logger.exception("Reviewed source synchronous abandonment failed (%s)", context)

    def _revoke_reviewed_generation_now(
        self,
        state: _InstrumentState,
        binding: DriverRuntimeBinding,
        generation: object,
        context: str,
    ) -> None:
        """Synchronously remove RUN authority before returning an uncertain cut."""
        self._invalidate_reviewed_disconnect_receipt(state)
        callback = self._reviewed_source_connect_abandon
        if callback is None:
            raise RuntimeError("reviewed source abandonment lacks synchronous authority")
        result = callback(state.config.driver, binding, generation, context)
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise TypeError("reviewed source synchronous abandonment returned an awaitable")
        if result is not None:
            raise TypeError("reviewed source synchronous abandonment must return None")
        state.reviewed_source_generation = None

    def _retain_reviewed_disconnect_settlement(
        self,
        state: _InstrumentState,
        context: str,
    ) -> None:
        """Start one exact disconnect owner without awaiting it in the caller."""
        state.reviewed_source_disconnect_required = True
        if state.reviewed_source_disconnect_task is None:
            revision = state.reviewed_source_disconnect_revision
            state.reviewed_source_disconnect_task = asyncio.create_task(
                self._disconnect_reviewed_exact(state, context, revision=revision),
                name=f"reviewed_disconnect_{state.config.driver.name}",
            )
            state.reviewed_source_disconnect_task_revision = revision

    async def _poll_loop(self, state: _InstrumentState) -> None:
        """Цикл опроса одного прибора с reconnect и backoff."""
        cfg = state.config
        driver = cfg.driver
        name = driver.name
        loop = asyncio.get_event_loop()
        next_deadline = loop.time() + cfg.poll_interval_s

        while self._running:
            if state.reviewed_source_attempt is not None:
                settled = await self._settle_reviewed_poll_barrier(
                    state,
                    "standalone reviewed-source connect cleanup",
                )
                if not settled:
                    await self._backoff(state)
                    continue
                continue
            if self._reviewed_binding(state) is not None and (
                state.reviewed_source_disconnect_required or state.reviewed_source_disconnect_task is not None
            ):
                await self._disconnect_driver(
                    driver,
                    timeout_s=cfg.connect_timeout_s,
                    context="standalone reviewed-source disconnect barrier",
                )
                await self._backoff(state)
                continue
            if (
                self._reviewed_binding(state) is not None
                and driver.connected
                and state.reviewed_source_generation is None
            ):
                await self._disconnect_driver(
                    driver,
                    context="reviewed source lacks current connection generation",
                )
                await self._backoff(state)
                continue
            if not driver.connected:
                try:
                    await self._connect_driver(state, context="standalone connect")
                    state.consecutive_errors = 0
                    state.backoff_s = INITIAL_BACKOFF_S
                    logger.info("Прибор '%s' подключён", name)
                except Exception:
                    logger.exception("Не удалось подключить '%s'", name)
                    await self._backoff(state)
                    continue

            try:
                readings = await asyncio.wait_for(driver.safe_read(), timeout=cfg.read_timeout_s)
                state.consecutive_errors = 0
                state.backoff_s = INITIAL_BACKOFF_S
                await self._process_readings(state, readings)
            except asyncio.CancelledError:
                await self._settle_reviewed_read_uncertainty(state, "standalone read cancelled")
                raise
            except TimeoutError:
                reviewed = self._reviewed_binding(state) is not None
                if reviewed:
                    await self._settle_reviewed_read_uncertainty(state, "standalone read timeout")
                state.consecutive_errors += 1
                state.total_errors += 1
                logger.warning(
                    "Таймаут опроса '%s' (%.1fs), ошибок подряд: %d",
                    name,
                    cfg.read_timeout_s,
                    state.consecutive_errors,
                )
                if reviewed:
                    await self._backoff(state, max_s=_STANDALONE_MAX_BACKOFF_S)
                    continue
                if state.consecutive_errors >= 3:
                    logger.warning(
                        "'%s': %d consecutive errors, disconnect + backoff",
                        name,
                        state.consecutive_errors,
                    )
                    await self._disconnect_driver(driver, context="standalone timeout recovery")
                    state.backoff_s = max(state.backoff_s, _STANDALONE_INITIAL_BACKOFF_S)
                    await self._backoff(state, max_s=_STANDALONE_MAX_BACKOFF_S)
                    continue
            except Exception:
                reviewed = self._reviewed_binding(state) is not None
                if reviewed:
                    await self._settle_reviewed_read_uncertainty(state, "standalone read error")
                state.consecutive_errors += 1
                state.total_errors += 1
                logger.warning("Ошибка опроса '%s', ошибок подряд: %d", name, state.consecutive_errors)
                if reviewed:
                    await self._backoff(state, max_s=_STANDALONE_MAX_BACKOFF_S)
                    continue
                if state.consecutive_errors >= 3:
                    logger.warning(
                        "'%s': %d consecutive errors, disconnect + backoff",
                        name,
                        state.consecutive_errors,
                    )
                    await self._disconnect_driver(driver, context="standalone error recovery")
                    state.backoff_s = max(state.backoff_s, _STANDALONE_INITIAL_BACKOFF_S)
                    await self._backoff(state, max_s=_STANDALONE_MAX_BACKOFF_S)
                    continue

            next_deadline += cfg.poll_interval_s
            now = loop.time()
            if next_deadline < now:
                missed = int((now - next_deadline) / cfg.poll_interval_s) + 1
                next_deadline += missed * cfg.poll_interval_s
            sleep_remaining = max(0, next_deadline - loop.time())
            await asyncio.sleep(sleep_remaining)

    async def _mark_disconnected(self, state: _InstrumentState, bus_id: str) -> None:
        binding = state.config.runtime_binding
        participant: SharedBusParticipant | None = binding.participant if binding else None
        if participant is not None:
            try:
                await participant.mark_disconnected()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Public disconnect marker failed for '%s'", state.config.driver.name)
        await self._disconnect_driver(state.config.driver, context=f"shared bus {bus_id}")

    async def _abort_partial_connect(self, state: _InstrumentState) -> None:
        binding = state.config.runtime_binding
        if binding is None or binding.lifecycle is None:
            await self._disconnect_driver(state.config.driver, context="partial connect cleanup")
            return
        try:
            await asyncio.wait_for(binding.lifecycle.abort_connect(), timeout=state.config.connect_timeout_s)
        except asyncio.CancelledError:
            cleanup = asyncio.create_task(binding.lifecycle.abort_connect())
            try:
                await asyncio.shield(asyncio.wait_for(cleanup, timeout=state.config.connect_timeout_s))
            except Exception:
                cleanup.cancel()
            raise
        except Exception:
            logger.exception("Partial connect cleanup failed for '%s'", state.config.driver.name)

    async def _bounded_bus_recovery(
        self,
        operation: Any,
        *,
        timeout_s: float,
        bus_id: str,
        label: str,
        completion_is_success: bool = False,
    ) -> bool | None:
        if bus_id in self._terminal_bus_authority:
            return None
        if not inspect.iscoroutinefunction(operation):
            logger.critical("Bus-scoped %s for %s is not an async contract", label, bus_id)
            self._terminal_bus_authority.add(bus_id)
            return None
        try:
            task = asyncio.create_task(operation(), name=f"bus_{bus_id}_{label}")
        except Exception:
            logger.exception("Bus-scoped %s could not start for %s", label, bus_id)
            return False
        try:
            done, _pending = await asyncio.wait({task}, timeout=timeout_s)
        except asyncio.CancelledError:
            settlement = asyncio.create_task(
                self._cancel_bus_recovery(
                    task,
                    timeout_s=timeout_s,
                    bus_id=bus_id,
                    label=label,
                )
            )
            try:
                await asyncio.shield(settlement)
            except asyncio.CancelledError:
                # A second caller cancellation cannot cancel settlement;
                # the separately owned task will terminalize if necessary.
                pass
            raise
        if done:
            try:
                result = task.result()
                return True if completion_is_success else bool(result)
            except asyncio.CancelledError:
                return False
            except Exception:
                logger.exception("Bus-scoped %s failed for %s", label, bus_id)
                return False
        if await self._cancel_bus_recovery(
            task,
            timeout_s=timeout_s,
            bus_id=bus_id,
            label=label,
        ):
            return False
        return None

    async def _bounded_bus_read(
        self,
        operation: Any,
        *,
        timeout_s: float,
        bus_id: str,
        label: str,
    ) -> list[Any] | None:
        """Run one shared-bus read or terminalize if cancellation resists."""

        if bus_id in self._terminal_bus_authority:
            return None
        if not inspect.iscoroutinefunction(operation):
            logger.critical("Bus-scoped %s for %s is not an async contract", label, bus_id)
            self._terminal_bus_authority.add(bus_id)
            return None
        task = asyncio.create_task(operation(), name=f"bus_{bus_id}_{label}")
        try:
            done, _pending = await asyncio.wait({task}, timeout=timeout_s)
        except asyncio.CancelledError:
            settlement = asyncio.create_task(
                self._cancel_bus_recovery(
                    task,
                    timeout_s=timeout_s,
                    bus_id=bus_id,
                    label=label,
                )
            )
            try:
                await asyncio.shield(settlement)
            except asyncio.CancelledError:
                pass
            raise
        if done:
            result = task.result()
            if not isinstance(result, list):
                raise TypeError("shared-bus driver read must return a list")
            return result
        if await self._cancel_bus_recovery(
            task,
            timeout_s=timeout_s,
            bus_id=bus_id,
            label=label,
        ):
            raise TimeoutError(f"bus-scoped {label} timed out")
        return None

    async def _cancel_bus_recovery(
        self,
        task: asyncio.Task[Any],
        *,
        timeout_s: float,
        bus_id: str,
        label: str,
    ) -> bool:
        """Cancel one recovery generation or terminalize its bus authority."""

        task.cancel()
        done, _pending = await asyncio.wait({task}, timeout=timeout_s)
        if done:
            try:
                task.result()
            except (asyncio.CancelledError, Exception):
                pass
            return True
        logger.critical(
            "Bus-scoped %s for %s resisted cancellation; bus authority is terminal",
            label,
            bus_id,
        )
        self._terminal_bus_authority.add(bus_id)
        self._unsettled_bus_operations[bus_id] = task

        def _settled(late: asyncio.Task[Any]) -> None:
            self._unsettled_bus_operations.pop(bus_id, None)
            try:
                late.exception()
            except (asyncio.CancelledError, Exception):
                pass

        task.add_done_callback(_settled)
        return False

    async def _shared_bus_poll_loop(self, bus_id: str, states: list[_InstrumentState]) -> None:
        """Serialize one explicit registry-bound bus while preserving per-device cadence."""

        loop = asyncio.get_running_loop()
        clock = self._shared_bus_clock or loop.time
        sleep = self._shared_bus_sleep or asyncio.sleep
        next_due = {state.config.driver.name: clock() for state in states}
        next_eligible = {state.config.driver.name: clock() for state in states}
        recovery_backoff = {state.config.driver.name: 0.01 for state in states}
        correlated_failures = 0
        failure_generation: set[str] = set()
        participant_names = {state.config.driver.name for state in states}
        ifc_succeeded = False
        descriptor = states[0].config.runtime_binding.bus_descriptor  # type: ignore[union-attr]
        coordinators = {
            id(binding.coordinator): binding.coordinator
            for state in states
            if (binding := state.config.runtime_binding) is not None and binding.coordinator is not None
        }
        if len(coordinators) > 1:
            raise RuntimeError(f"bus {bus_id} has contradictory recovery coordinators")
        coordinator: SharedBusRecoveryCoordinator | None = next(iter(coordinators.values()), None)

        while self._running:
            now = clock()
            due = [
                state
                for state in states
                if next_due[state.config.driver.name] <= now and next_eligible[state.config.driver.name] <= now
            ]
            if not due:
                wake = min(
                    max(next_due[state.config.driver.name], next_eligible[state.config.driver.name]) for state in states
                )
                await sleep(max(0.0, wake - clock()))
                continue
            failures = 0
            successes = 0
            for state in due:
                cfg = state.config
                driver = cfg.driver
                reviewed = self._reviewed_binding(state) is not None
                if state.reviewed_source_attempt is not None:
                    settled = await self._settle_reviewed_poll_barrier(
                        state,
                        f"shared bus {bus_id}: reviewed-source connect cleanup",
                    )
                    if not settled:
                        failures += 1
                        state.consecutive_errors += 1
                        state.total_errors += 1
                        next_eligible[driver.name] = clock() + recovery_backoff[driver.name]
                        continue
                if reviewed and (
                    state.reviewed_source_disconnect_required or state.reviewed_source_disconnect_task is not None
                ):
                    if not await self._disconnect_driver(
                        driver,
                        timeout_s=cfg.connect_timeout_s,
                        context=f"shared bus {bus_id}: settle disconnect barrier",
                    ):
                        failures += 1
                        state.consecutive_errors += 1
                        state.total_errors += 1
                        next_eligible[driver.name] = clock() + recovery_backoff[driver.name]
                        continue
                if reviewed and driver.connected and state.reviewed_source_generation is None:
                    await self._disconnect_driver(
                        driver,
                        timeout_s=cfg.connect_timeout_s,
                        context=f"shared bus {bus_id}: missing connection generation",
                    )
                    failures += 1
                    state.consecutive_errors += 1
                    state.total_errors += 1
                    next_eligible[driver.name] = clock() + recovery_backoff[driver.name]
                    continue
                reviewed_read_started = False
                try:
                    if not driver.connected:
                        await self._connect_driver(state, context=f"shared bus {bus_id} connect")
                    reviewed_read_started = reviewed
                    readings = await self._bounded_bus_read(
                        driver.safe_read,
                        timeout_s=cfg.read_timeout_s,
                        bus_id=bus_id,
                        label=f"read {driver.name}",
                    )
                    if readings is None:
                        if reviewed and reviewed_read_started:
                            binding = self._reviewed_binding(state)
                            generation = state.reviewed_source_generation
                            if binding is not None and generation is not None:
                                self._revoke_reviewed_generation_now(
                                    state,
                                    binding,
                                    generation,
                                    f"shared bus {bus_id} read resisted cancellation",
                                )
                            self._retain_reviewed_disconnect_settlement(
                                state,
                                f"shared bus {bus_id} terminal read settlement",
                            )
                        return
                    await self._process_readings(state, readings)
                    successes += 1
                    recovery_backoff[driver.name] = 0.01
                except asyncio.CancelledError:
                    if reviewed:
                        if reviewed_read_started:
                            await self._settle_reviewed_read_uncertainty(
                                state,
                                f"shared bus {bus_id} read cancelled",
                            )
                        # A cancelled reviewed connect is owned by its retained
                        # _ReviewedConnectAttempt.  A generic lifecycle abort
                        # would create a second cleanup owner racing it.
                    elif bus_id not in self._terminal_bus_authority:
                        await self._abort_partial_connect(state)
                    raise
                except Exception:
                    if reviewed:
                        if reviewed_read_started:
                            await self._settle_reviewed_read_uncertainty(
                                state,
                                f"shared bus {bus_id} first read uncertainty",
                            )
                        failures += 1
                        state.consecutive_errors += 1
                        state.total_errors += 1
                        next_eligible[driver.name] = clock() + recovery_backoff[driver.name]
                        recovery_backoff[driver.name] = min(recovery_backoff[driver.name] * 2, 1.0)
                        continue
                    if not driver.connected:
                        await self._abort_partial_connect(state)
                    failures += 1
                    state.consecutive_errors += 1
                    state.total_errors += 1
                    binding = cfg.runtime_binding
                    if (
                        binding is not None
                        and binding.participant is not None
                        and binding.bus_descriptor is not None
                        and BusRecoveryLevel.DEVICE_CLEAR in binding.bus_descriptor.supported_recovery
                    ):
                        recovered = await self._bounded_bus_recovery(
                            binding.participant.recover_device,
                            timeout_s=cfg.connect_timeout_s,
                            bus_id=bus_id,
                            label=f"device recovery {driver.name}",
                            completion_is_success=True,
                        )
                        if recovered is None:
                            return
                        if not recovered:
                            logger.warning("Device recovery failed for '%s'", driver.name)
                    if state.consecutive_errors >= 3:
                        await self._mark_disconnected(state, bus_id)
                    next_eligible[driver.name] = clock() + recovery_backoff[driver.name]
                    recovery_backoff[driver.name] = min(recovery_backoff[driver.name] * 2, 1.0)
                finally:
                    interval = cfg.poll_interval_s
                    deadline = next_due[driver.name] + interval
                    now_after = clock()
                    if deadline <= now_after:
                        deadline += (int((now_after - deadline) / interval) + 1) * interval
                    next_due[driver.name] = deadline

            if successes:
                failure_generation.clear()
                correlated_failures = 0
                ifc_succeeded = False
            elif failures:
                failure_generation.update(state.config.driver.name for state in due)
            completed_epoch = failure_generation == participant_names
            if completed_epoch:
                correlated_failures += 1
                failure_generation.clear()
            if completed_epoch and coordinator is not None and descriptor is not None:
                levels = descriptor.supported_recovery
                if correlated_failures >= 3 and not ifc_succeeded and BusRecoveryLevel.INTERFACE_CLEAR in levels:
                    ifc_result = await self._bounded_bus_recovery(
                        coordinator.interface_clear,
                        timeout_s=descriptor.recovery_timeout_s,
                        bus_id=bus_id,
                        label="interface clear",
                    )
                    if ifc_result is None:
                        return
                    ifc_succeeded = ifc_result
                    if ifc_succeeded:
                        for state in states:
                            await self._mark_disconnected(state, bus_id)
                if correlated_failures >= 6 and BusRecoveryLevel.REOPEN_BUS in levels:
                    reopened = await self._bounded_bus_recovery(
                        coordinator.reopen_bus,
                        timeout_s=descriptor.recovery_timeout_s,
                        bus_id=bus_id,
                        label="reopen",
                    )
                    if reopened is None:
                        return
                    if reopened:
                        for state in states:
                            await self._mark_disconnected(state, bus_id)
                        correlated_failures = 0
                        ifc_succeeded = False

    async def _process_readings(self, state: _InstrumentState, readings: list[Any]) -> None:
        """Persist, calibrate, and publish readings — shared by both loop types."""
        driver = state.config.driver
        name = driver.name

        # Disk-full graceful degradation (Phase 2a H.1).
        # If the writer has detected disk-full, skip the entire pipeline:
        # we cannot persist (so persistence-first invariant blocks publish),
        # and SafetyManager has already latched a fault via the writer's
        # callback. Returning here keeps the loop alive (so when disk
        # recovers and the operator acknowledges, polling resumes cleanly)
        # without spamming CRITICAL logs.
        if self._sqlite_writer is not None and getattr(self._sqlite_writer, "is_disk_full", False):
            return

        persisted_readings = list(readings)
        if self._adaptive_throttle is not None:
            persisted_readings = self._adaptive_throttle.filter_for_archive(readings)
        state.total_reads += 1
        state.consecutive_errors = 0
        state.backoff_s = INITIAL_BACKOFF_S

        # Step 1a: If calibration acquisition active, read SRDG BEFORE persisting
        # so KRDG+SRDG can be written atomically in one transaction (H.10).
        srdg_to_persist: list = []
        srdg_pending_state = None
        if (
            self._calibration_acquisition is not None
            and self._calibration_acquisition.is_active
            and hasattr(driver, "read_srdg_channels")
        ):
            try:
                srdg = await driver.read_srdg_channels()
                srdg_to_persist, srdg_pending_state = self._calibration_acquisition.prepare_srdg_readings(
                    readings, srdg
                )
            except Exception:
                logger.warning(
                    "Failed to read SRDG for calibration on '%s'",
                    name,
                    exc_info=True,
                )

        # Step 1b: Persist KRDG + SRDG atomically in one transaction
        combined = list(persisted_readings) + srdg_to_persist
        persistence_authoritative = False
        committed_publish_readings = list(persisted_readings)
        # F35 D4: descriptor envelopes positionally aligned with
        # committed_publish_readings. None (default/non-authoritative path)
        # is passed explicitly to DataBroker — never fabricated.
        descriptor_envelopes: list[bytes | None] | None = None
        if self._sqlite_writer is not None and combined:
            try:
                if getattr(self._sqlite_writer, "descriptor_authoritative", False) is True:
                    settlement = None
                    try:
                        begin = getattr(self._sqlite_writer, "begin_committed", None)
                        if callable(begin):
                            settlement = begin(combined)
                            receipt = await settlement.wait()
                            release = getattr(self._sqlite_writer, "release_committed", None)
                            if callable(release):
                                release(settlement)
                        else:
                            receipt = await self._sqlite_writer.write_committed(combined)
                    except asyncio.CancelledError:
                        settle = getattr(self._sqlite_writer, "settle_committed", None)
                        if settlement is not None and callable(settle):
                            try:
                                receipt = await settle(settlement)
                                if receipt is not None:
                                    self._observe_persistence_commit(receipt)
                                else:
                                    self._observe_persistence_ambiguity()
                            except BaseException:
                                self._observe_persistence_ambiguity()
                        else:
                            self._observe_persistence_ambiguity()
                        raise
                    except Exception:
                        self._observe_persistence_ambiguity()
                        raise
                    if receipt is None:
                        self._observe_persistence_rejection(len(combined), "descriptor_commit_refused")
                        return
                    entries = self._sqlite_writer.entries_from_commit(receipt)
                    if len(entries) != len(combined):
                        self._observe_persistence_ambiguity()
                        raise RuntimeError("commit receipt cardinality disagrees with persisted batch")
                    for admitted, entry in zip(combined, entries, strict=True):
                        committed = entry.reading
                        if (
                            type(committed) is not Reading
                            or replace(
                                committed,
                                channel=admitted.channel,
                            )
                            != admitted
                        ):
                            self._observe_persistence_ambiguity()
                            raise RuntimeError("commit receipt payload disagrees with the admitted batch")
                    committed_publish_readings = [entry.reading for entry in entries[: len(persisted_readings)]]
                    descriptor_envelopes = [entry.descriptor_envelope for entry in entries[: len(persisted_readings)]]
                    persisted = True
                    self._observe_persistence_commit(receipt)
                else:
                    persisted = await self._sqlite_writer.write_immediate(combined)
            except Exception:
                logger.exception(
                    "CRITICAL: Ошибка записи '%s' — данные НЕ отправлены подписчикам",
                    name,
                )
                state.consecutive_errors += 1
                state.total_errors += 1
                return

            # If write_immediate silently absorbed a disk-full error
            if getattr(self._sqlite_writer, "is_disk_full", False):
                return

            # R1 (Phase A recheck, CRITICAL): a locked/busy write below the A6
            # signalling threshold is swallowed without raising (see
            # sqlite_writer._write_day_batch) — write_immediate() reports this
            # via its per-call return value, NOT shared writer state (a shared
            # flag could be reset by a concurrent poll task's later, successful
            # write on the same writer before this caller checked it). Mirror
            # the disk-full gate above: skip publish to both brokers. The drop
            # itself stays loud via A6's existing warning/critical log.
            if not persisted:
                return
            persistence_authoritative = True

        # Step 1c: Notify calibration acquisition (no longer writes — already persisted)
        if srdg_to_persist:
            self._calibration_acquisition.on_srdg_persisted(len(srdg_to_persist), srdg_pending_state)

        # Step 2: Publish to brokers
        if committed_publish_readings:
            await self._broker.publish_batch(
                committed_publish_readings,
                persistence_authoritative=persistence_authoritative,
                descriptor_envelopes=descriptor_envelopes,
            )
        if self._safety_broker is not None:
            await self._safety_broker.publish_batch(readings)

    def _observe_persistence_commit(self, receipt: object) -> None:
        observer = self._persistence_commit_observer
        if observer is None:
            return
        try:
            observer(receipt)
        except Exception:
            logger.exception("Direct persistence observation failed after a proven SQLite commit")
            self._observe_persistence_ambiguity()

    def _observe_persistence_rejection(self, record_count: int, reason: str) -> None:
        observer = self._persistence_rejection_observer
        if observer is None:
            return
        try:
            observer(record_count, reason)
        except Exception:
            logger.exception("Direct persistence rejection observation failed")
            self._observe_persistence_ambiguity()

    def _observe_persistence_ambiguity(self) -> None:
        observer = self._persistence_ambiguity_observer
        if observer is None:
            return
        try:
            observer()
        except Exception:
            logger.exception("Direct persistence ambiguity observation failed")

    async def _handle_error(self, state: _InstrumentState) -> None:
        """При 3+ ошибках подряд — переподключение с backoff."""
        if state.consecutive_errors >= 3:
            driver = state.config.driver
            logger.warning("Переподключение '%s' после %d ошибок", driver.name, state.consecutive_errors)
            await self._disconnect_driver(driver, context="generic error recovery")
            await self._backoff(state)

    async def _backoff(self, state: _InstrumentState, *, max_s: float = MAX_BACKOFF_S) -> None:
        """Экспоненциальная задержка перед переподключением."""
        delay = min(state.backoff_s, max_s)
        logger.info("Backoff '%s': %.1fs", state.config.driver.name, delay)
        await asyncio.sleep(delay)
        state.backoff_s = min(state.backoff_s * 2, max_s)

    async def start(self) -> None:
        """Запустить все циклы опроса.

        Приборы с одним явным bus descriptor группируются в последовательный
        task. Все остальные — каждый в своём task.
        """
        self._running = True

        shared_groups: dict[str, list[_InstrumentState]] = {}
        standalone: list[_InstrumentState] = []

        for name, state in self._instruments.items():
            if not state.config.enabled:
                continue
            binding = state.config.runtime_binding
            descriptor = binding.bus_descriptor if binding is not None else None
            if descriptor is not None:
                shared_groups.setdefault(descriptor.bus_id, []).append(state)
            else:
                standalone.append(state)

        # Validate every group before creating any task: one bad later group
        # cannot leave an earlier bus running after start() raises.
        for bus_id, states in shared_groups.items():
            descriptors = {
                state.config.runtime_binding.bus_descriptor  # type: ignore[union-attr]
                for state in states
            }
            if len(descriptors) != 1:
                self._running = False
                raise ValueError(f"bus {bus_id} has contradictory immutable descriptors")
            coordinators: set[int | None] = {
                id(binding.coordinator) if binding.coordinator is not None else None
                for state in states
                if (binding := state.config.runtime_binding) is not None
            }
            if len(coordinators) > 1:
                self._running = False
                raise ValueError(f"bus {bus_id} has contradictory recovery coordinators")

        # Launch one task per explicitly bound shared bus.
        for bus_id, states in shared_groups.items():
            names = [s.config.driver.name for s in states]
            logger.info(
                "Shared bus %s: последовательный опрос %d приборов %s",
                bus_id,
                len(states),
                names,
            )
            task = asyncio.create_task(
                self._shared_bus_poll_loop(bus_id, states),
                name=f"shared_bus_poll_{bus_id}",
            )
            self._shared_bus_tasks[bus_id] = task
            # Point each state's task ref to the shared task for stop()
            for state in states:
                state.task = task

        # Launch individual tasks for non-GPIB instruments
        for state in standalone:
            state.task = asyncio.create_task(self._poll_loop(state), name=f"poll_{state.config.driver.name}")

        total = sum(len(g) for g in shared_groups.values()) + len(standalone)
        logger.info(
            "Scheduler запущен (%d приборов, %d GPIB bus, %d standalone)",
            total,
            len(shared_groups),
            len(standalone),
        )

    async def stop(self) -> None:
        """Остановить все циклы, отключить приборы.

        Two-phase shutdown (P1 fix):
        Phase 1 — graceful drain: set _running=False and wait for in-flight
        polls to complete their persist+publish cycle naturally.
        Phase 2 — forced cancel: if drain times out, cancel remaining tasks.
        """
        self._running = False

        # Gather all unique tasks
        all_tasks: set[asyncio.Task[None]] = set()
        for state in self._instruments.values():
            if state.task and not state.task.done():
                all_tasks.add(state.task)
        for task in self._shared_bus_tasks.values():
            if not task.done():
                all_tasks.add(task)

        if all_tasks:
            # Phase 1: graceful drain — let polls finish persist+publish
            completed, pending = await asyncio.wait(
                all_tasks,
                timeout=self._drain_timeout_s,
            )
            if not pending:
                logger.info("Scheduler: graceful drain complete")
            else:
                logger.warning(
                    "Scheduler: drain timed out after %.1fs, force-cancelling",
                    self._drain_timeout_s,
                )
                for task in pending:
                    task.cancel()
                forced_completed, pending = await asyncio.wait(
                    pending,
                    timeout=self._drain_timeout_s,
                )
                completed.update(forced_completed)
            for task in completed:
                try:
                    task.result()
                except (asyncio.CancelledError, Exception):
                    pass

        # A deadline cannot strand RUN authority behind a poll that
        # suppresses cancellation.  Cut the exact generation synchronously
        # and retain one exact disconnect owner before adjudication.
        for state in self._instruments.values():
            poll_task = state.task
            binding = self._reviewed_binding(state)
            if poll_task is None or poll_task.done() or binding is None:
                continue
            generation = state.reviewed_source_generation
            if generation is not None:
                self._revoke_reviewed_generation_now(
                    state,
                    binding,
                    generation,
                    "scheduler stop: poll task resisted cancellation",
                )
            else:
                self._invalidate_reviewed_disconnect_receipt(state)
            self._retain_reviewed_disconnect_settlement(
                state,
                "scheduler stop: retained poll settlement",
            )

        settlement_deadline = asyncio.get_running_loop().time() + self._drain_timeout_s
        reviewed_tasks: set[asyncio.Task[Any]] = set()
        for state in self._instruments.values():
            attempt = state.reviewed_source_attempt
            if attempt is not None:
                attempt.abandon_requested = True
                attempt.abandon_event.set()
                if attempt.owner_task is not None and not attempt.owner_task.done():
                    reviewed_tasks.add(attempt.owner_task)
                if attempt.cleanup_retry_task is not None and not attempt.cleanup_retry_task.done():
                    reviewed_tasks.add(attempt.cleanup_retry_task)
            disconnect_task = state.reviewed_source_disconnect_task
            if disconnect_task is not None and not disconnect_task.done():
                reviewed_tasks.add(disconnect_task)
        if reviewed_tasks:
            await asyncio.wait(reviewed_tasks, timeout=self._drain_timeout_s)

        reviewed_incomplete: dict[str, list[str]] = {}
        ordinary_incomplete: list[str] = []

        def _record_reviewed(name: str, reason: str) -> None:
            reviewed_incomplete.setdefault(name, []).append(reason)

        for state in self._instruments.values():
            name = state.config.driver.name
            reviewed = self._reviewed_binding(state) is not None
            poll_task = state.task
            if poll_task is not None and not poll_task.done():
                if reviewed:
                    # A disconnect completed while this ambiguous operation
                    # remained live is stale; require a later exact receipt.
                    self._invalidate_reviewed_disconnect_receipt(state)
                    _record_reviewed(name, "poll task still pending after forced-cancel window")
                else:
                    ordinary_incomplete.append(f"{name} (poll task still pending)")
                continue
            state.task = None
            attempt = state.reviewed_source_attempt
            if attempt is not None:
                if attempt.owner_task is None or not attempt.owner_task.done():
                    _record_reviewed(name, "connect owner still pending")
                    continue
                try:
                    attempt.owner_task.result()
                except BaseException as exc:
                    attempt.failure = exc
                if attempt.failure is not None:
                    remaining = max(0.0, settlement_deadline - asyncio.get_running_loop().time())
                    settled = await self._retry_failed_reviewed_attempt(
                        state,
                        attempt,
                        "scheduler stop retry",
                        timeout_s=remaining,
                    )
                    if not settled:
                        reason = attempt.failure or "cleanup retry still pending"
                        _record_reviewed(name, f"connect cleanup unproved: {reason}")
                        continue
                try:
                    if not self._adjudicate_reviewed_attempt(state):
                        _record_reviewed(name, "connect settlement is not terminal")
                        continue
                except ReviewedSourceSettlementIncomplete as exc:
                    _record_reviewed(name, str(exc))
                    continue
            binding = state.config.runtime_binding
            descriptor = binding.bus_descriptor if binding is not None else None
            if descriptor is not None and descriptor.bus_id in self._terminal_bus_authority:
                unsettled = self._unsettled_bus_operations.get(descriptor.bus_id)
                if unsettled is not None and not unsettled.done():
                    logger.critical(
                        "Deferring disconnect on terminal bus %s while its retained operation is live",
                        descriptor.bus_id,
                    )
                    if reviewed:
                        self._invalidate_reviewed_disconnect_receipt(state)
                        _record_reviewed(
                            name,
                            f"terminal shared-bus operation {descriptor.bus_id} still pending",
                        )
                    else:
                        ordinary_incomplete.append(
                            f"{name} (terminal shared-bus operation {descriptor.bus_id} still pending)"
                        )
                    continue
                logger.critical(
                    "Terminal acquisition authority remains disabled on settled bus %s; proceeding with teardown",
                    descriptor.bus_id,
                )
            if reviewed:
                needs_disconnect = bool(
                    state.reviewed_source_disconnect_required
                    or state.reviewed_source_disconnect_task is not None
                    or state.reviewed_source_generation is not None
                    or state.config.driver.connected is True
                )
                if needs_disconnect:
                    remaining = max(0.0, settlement_deadline - asyncio.get_running_loop().time())
                    if not await self._disconnect_driver(
                        state.config.driver,
                        timeout_s=remaining,
                        context="scheduler stop",
                    ):
                        task = state.reviewed_source_disconnect_task
                        reason = (
                            "disconnect owner still pending"
                            if task is not None and not task.done()
                            else ("disconnect did not return exact True")
                        )
                        _record_reviewed(name, reason)
                continue
            if not await self._disconnect_driver(state.config.driver, context="scheduler stop"):
                ordinary_incomplete.append(name)
        if reviewed_incomplete:
            details = "; ".join(
                f"{name}: {', '.join(reasons)}" for name, reasons in sorted(reviewed_incomplete.items())
            )
            raise ReviewedSourceSettlementIncomplete(
                f"reviewed-source shutdown incomplete for {len(reviewed_incomplete)} instrument(s): {details}"
            )
        if ordinary_incomplete:
            names = ", ".join(sorted(set(ordinary_incomplete)))
            raise RuntimeError(f"instrument shutdown incomplete: {names}")
        self._shared_bus_tasks.clear()
        logger.info("Scheduler остановлен")

    @property
    def stats(self) -> dict[str, dict[str, Any]]:
        """Статистика по приборам."""
        return {
            name: {
                "connected": state.config.driver.connected,
                "total_reads": state.total_reads,
                "total_errors": state.total_errors,
                "consecutive_errors": state.consecutive_errors,
            }
            for name, state in self._instruments.items()
        }
