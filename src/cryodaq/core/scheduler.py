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
from dataclasses import dataclass, field
from typing import Any

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import InstrumentDriver
from cryodaq.drivers.contracts import (
    AcquisitionTiming,
    BusRecoveryLevel,
    DriverRuntimeBinding,
    DriverTrustClass,
    SharedBusParticipant,
    SharedBusRecoveryCoordinator,
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
        reviewed_source_disconnect: Callable[[InstrumentDriver, str], Awaitable[bool]] | None = None,
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
        self._instruments[name] = _InstrumentState(config=config)
        logger.info("Прибор '%s' добавлен (интервал=%.1fs)", name, config.poll_interval_s)

    async def _disconnect_driver(
        self,
        driver: InstrumentDriver,
        *,
        timeout_s: float = _DISCONNECT_TIMEOUT_S,
        context: str = "",
    ) -> bool:
        """Disconnect with a bounded wait so wedged transports do not hang recovery."""
        from cryodaq.drivers.registry import runtime_binding_for_driver

        binding = runtime_binding_for_driver(driver)
        if binding is not None and binding.trust_class is DriverTrustClass.REVIEWED_SOURCE:
            callback = self._reviewed_source_disconnect
            if callback is None:
                logger.critical(
                    "Reviewed source '%s' cannot be disconnected without SafetyManager authority (%s)",
                    driver.name,
                    context,
                )
                return False
            try:
                result = await asyncio.wait_for(callback(driver, context), timeout=timeout_s)
                return result is True
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

    async def _poll_loop(self, state: _InstrumentState) -> None:
        """Цикл опроса одного прибора с reconnect и backoff."""
        cfg = state.config
        driver = cfg.driver
        name = driver.name
        loop = asyncio.get_event_loop()
        next_deadline = loop.time() + cfg.poll_interval_s

        while self._running:
            if not driver.connected:
                try:
                    await asyncio.wait_for(driver.connect(), timeout=cfg.connect_timeout_s)
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
            except TimeoutError:
                state.consecutive_errors += 1
                state.total_errors += 1
                logger.warning(
                    "Таймаут опроса '%s' (%.1fs), ошибок подряд: %d",
                    name,
                    cfg.read_timeout_s,
                    state.consecutive_errors,
                )
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
                state.consecutive_errors += 1
                state.total_errors += 1
                logger.warning("Ошибка опроса '%s', ошибок подряд: %d", name, state.consecutive_errors)
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
                try:
                    if not driver.connected:
                        await asyncio.wait_for(driver.connect(), timeout=cfg.connect_timeout_s)
                    readings = await self._bounded_bus_read(
                        driver.safe_read,
                        timeout_s=cfg.read_timeout_s,
                        bus_id=bus_id,
                        label=f"read {driver.name}",
                    )
                    if readings is None:
                        return
                    await self._process_readings(state, readings)
                    successes += 1
                    recovery_backoff[driver.name] = 0.01
                except asyncio.CancelledError:
                    if bus_id not in self._terminal_bus_authority:
                        await self._abort_partial_connect(state)
                    raise
                except Exception:
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
                    try:
                        receipt = await self._sqlite_writer.write_committed(combined)
                    except asyncio.CancelledError:
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
            try:
                await asyncio.wait_for(
                    asyncio.gather(*all_tasks, return_exceptions=True),
                    timeout=self._drain_timeout_s,
                )
                logger.info("Scheduler: graceful drain complete")
            except TimeoutError:
                logger.warning(
                    "Scheduler: drain timed out after %.1fs, force-cancelling",
                    self._drain_timeout_s,
                )
                # Phase 2: forced cancel
                for task in all_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*all_tasks, return_exceptions=True)

        for state in self._instruments.values():
            state.task = None
            binding = state.config.runtime_binding
            descriptor = binding.bus_descriptor if binding is not None else None
            if descriptor is not None and descriptor.bus_id in self._terminal_bus_authority:
                logger.critical(
                    "Skipping disconnect on terminal unsettled bus authority %s",
                    descriptor.bus_id,
                )
                continue
            await self._disconnect_driver(state.config.driver, context="scheduler stop")
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
