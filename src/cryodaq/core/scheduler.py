"""Scheduler — планировщик опроса приборов.

Для каждого InstrumentDriver создаёт изолированную asyncio-задачу.
Исключение: приборы на одной GPIB-шине группируются в один task
и опрашиваются последовательно (NI GPIB-USB-HS не переносит
параллельный доступ даже с asyncio.Lock + run_in_executor).

Таймаут одного прибора не блокирует приборы на другой шине.
При ошибке соединения — экспоненциальный backoff с переподключением.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import InstrumentDriver

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 1.0
MAX_BACKOFF_S = 60.0
INITIAL_BACKOFF_S = 1.0
READ_TIMEOUT_S = 10.0

# Standalone (non-GPIB) instrument disconnect backoff
_STANDALONE_INITIAL_BACKOFF_S = 30.0
_STANDALONE_MAX_BACKOFF_S = 300.0

_GPIB_PREFIX = "GPIB"


@dataclass
class InstrumentConfig:
    """Конфигурация опроса одного прибора."""

    driver: InstrumentDriver
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S
    read_timeout_s: float = READ_TIMEOUT_S
    enabled: bool = True
    resource_str: str = ""


@dataclass
class _InstrumentState:
    """Внутреннее состояние задачи опроса."""

    config: InstrumentConfig
    task: asyncio.Task[None] | None = None
    consecutive_errors: int = 0
    total_reads: int = 0
    total_errors: int = 0
    backoff_s: float = field(default=INITIAL_BACKOFF_S)


def _gpib_bus_prefix(resource_str: str) -> str | None:
    """Extract GPIB bus prefix (e.g. 'GPIB0') or None if not GPIB."""
    if resource_str.upper().startswith(_GPIB_PREFIX):
        return resource_str.split("::")[0]
    return None


class Scheduler:
    """Планировщик: GPIB приборы на одной шине → один последовательный task.

    Использование::

        scheduler = Scheduler(broker)
        scheduler.add(InstrumentConfig(driver=lakeshore1, resource_str="GPIB0::12::INSTR"))
        scheduler.add(InstrumentConfig(driver=lakeshore2, resource_str="GPIB0::11::INSTR"))
        scheduler.add(InstrumentConfig(driver=keithley, resource_str="USB0::..."))
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
        drain_timeout_s: float = 5.0,
    ) -> None:
        self._broker = broker
        self._safety_broker = safety_broker
        self._sqlite_writer = sqlite_writer
        self._adaptive_throttle = adaptive_throttle
        self._calibration_acquisition = calibration_acquisition
        self._drain_timeout_s = drain_timeout_s
        self._instruments: dict[str, _InstrumentState] = {}
        self._running = False
        self._gpib_tasks: dict[str, asyncio.Task[None]] = {}

    def add(self, config: InstrumentConfig) -> None:
        """Зарегистрировать прибор. Вызывать до start()."""
        name = config.driver.name
        if name in self._instruments:
            raise ValueError(f"Прибор '{name}' уже зарегистрирован")
        self._instruments[name] = _InstrumentState(config=config)
        logger.info("Прибор '%s' добавлен (интервал=%.1fs)", name, config.poll_interval_s)

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
                    await driver.connect()
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
                    try:
                        await driver.disconnect()
                    except Exception:
                        logger.exception("Ошибка отключения '%s'", name)
                    state.backoff_s = max(state.backoff_s, _STANDALONE_INITIAL_BACKOFF_S)
                    await self._backoff(state, max_s=_STANDALONE_MAX_BACKOFF_S)
                    continue
            except Exception:
                state.consecutive_errors += 1
                state.total_errors += 1
                logger.warning(
                    "Ошибка опроса '%s', ошибок подряд: %d", name, state.consecutive_errors
                )
                if state.consecutive_errors >= 3:
                    logger.warning(
                        "'%s': %d consecutive errors, disconnect + backoff",
                        name,
                        state.consecutive_errors,
                    )
                    try:
                        await driver.disconnect()
                    except Exception:
                        logger.exception("Ошибка отключения '%s'", name)
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

    async def _gpib_poll_loop(self, bus_prefix: str, states: list[_InstrumentState]) -> None:
        """Последовательный опрос всех приборов на одной GPIB шине в одном task.

        Гарантирует: ни в какой момент два run_in_executor вызова к одной GPIB
        шине не выполняются параллельно. Один сбойный прибор не блокирует остальные.
        """
        poll_interval = max(s.config.poll_interval_s for s in states)
        _CONNECT_TIMEOUT_S = 3.0
        _POLL_TIMEOUT_S = 3.0
        _RECONNECT_INTERVAL_S = 30.0
        _PREVENTIVE_CLEAR_INTERVAL_S = 300.0
        _IFC_COOLDOWN_S = 2.0
        last_reconnect: dict[str, float] = {}
        last_preventive_clear: dict[str, float] = {}
        bus_error_count: int = 0  # consecutive errors across ALL devices on this bus

        # Подключить все последовательно — skip failures
        for state in states:
            driver = state.config.driver
            try:
                await asyncio.wait_for(driver.connect(), timeout=_CONNECT_TIMEOUT_S)
                state.consecutive_errors = 0
                logger.info("Прибор '%s' подключён (GPIB bus %s)", driver.name, bus_prefix)
            except Exception:
                logger.warning(
                    "Не удалось подключить '%s' на %s — skipping", driver.name, bus_prefix
                )
                driver._connected = False

        loop = asyncio.get_event_loop()
        next_deadline = loop.time() + poll_interval

        while self._running:
            now = loop.time()

            for state in states:
                driver = state.config.driver
                name = driver.name

                # Reconnect failed devices — rate-limited
                if not driver.connected:
                    last_try = last_reconnect.get(name, 0.0)
                    if now - last_try < _RECONNECT_INTERVAL_S:
                        continue
                    last_reconnect[name] = now
                    try:
                        await asyncio.wait_for(driver.connect(), timeout=_CONNECT_TIMEOUT_S)
                        state.consecutive_errors = 0
                        logger.info("Прибор '%s' переподключён (GPIB bus %s)", name, bus_prefix)
                    except Exception:
                        logger.warning("Не удалось переподключить '%s' — skipping", name)
                        driver._connected = False
                        continue

                # Preventive clear — every 5 minutes per device
                last_clear = last_preventive_clear.get(name, 0.0)
                if now - last_clear > _PREVENTIVE_CLEAR_INTERVAL_S:
                    transport = getattr(driver, "_transport", None)
                    if transport is not None and hasattr(transport, "clear_bus"):
                        try:
                            await asyncio.wait_for(transport.clear_bus(), timeout=2.0)
                            last_preventive_clear[name] = now
                        except Exception:
                            pass

                # Poll
                try:
                    readings = await asyncio.wait_for(driver.safe_read(), timeout=_POLL_TIMEOUT_S)
                    await self._process_readings(state, readings)
                    bus_error_count = 0  # reset on success
                except Exception as exc:
                    state.consecutive_errors += 1
                    state.total_errors += 1
                    bus_error_count += 1
                    logger.warning(
                        "Ошибка опроса '%s': %s (device: %d, bus: %d)",
                        name,
                        exc,
                        state.consecutive_errors,
                        bus_error_count,
                    )

                    transport = getattr(driver, "_transport", None)

                    if bus_error_count <= 2:
                        # Level 1: SDC on the specific device
                        if transport is not None and hasattr(transport, "clear_bus"):
                            try:
                                await asyncio.wait_for(transport.clear_bus(), timeout=2.0)
                            except Exception:
                                logger.warning("SDC failed after '%s' error", name)
                    elif bus_error_count <= 5:
                        # Level 2: IFC — reset entire bus
                        if transport is not None and hasattr(transport, "send_ifc"):
                            try:
                                await asyncio.wait_for(transport.send_ifc(), timeout=3.0)
                            except Exception:
                                logger.warning("IFC failed on bus %s", bus_prefix)
                            await asyncio.sleep(_IFC_COOLDOWN_S)
                            # After IFC, all devices need reconnect
                            for s in states:
                                try:
                                    await s.config.driver.disconnect()
                                except Exception:
                                    pass
                                s.config.driver._connected = False
                            break  # restart the for-loop (all devices disconnected)
                    else:
                        # Level 3: Close and reopen ResourceManager
                        logger.error(
                            "GPIB bus %s: %d consecutive errors, resetting ResourceManager",
                            bus_prefix,
                            bus_error_count,
                        )
                        from cryodaq.drivers.transport.gpib import GPIBTransport

                        GPIBTransport.close_all_managers()
                        for s in states:
                            s.config.driver._connected = False
                        bus_error_count = 0
                        break  # restart the for-loop

                    if state.consecutive_errors >= 3:
                        logger.warning("'%s': 3+ ошибок, disconnect + skip", name)
                        try:
                            await driver.disconnect()
                        except Exception:
                            pass
                        driver._connected = False

            next_deadline += poll_interval
            now = loop.time()
            if next_deadline < now:
                missed = int((now - next_deadline) / poll_interval) + 1
                next_deadline += missed * poll_interval
            sleep_remaining = max(0, next_deadline - loop.time())
            await asyncio.sleep(sleep_remaining)

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
                srdg_to_persist, srdg_pending_state = (
                    self._calibration_acquisition.prepare_srdg_readings(readings, srdg)
                )
            except Exception:
                logger.warning(
                    "Failed to read SRDG for calibration on '%s'",
                    name,
                    exc_info=True,
                )

        # Step 1b: Persist KRDG + SRDG atomically in one transaction
        combined = list(persisted_readings) + srdg_to_persist
        if self._sqlite_writer is not None and combined:
            try:
                await self._sqlite_writer.write_immediate(combined)
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

        # Step 1c: Notify calibration acquisition (no longer writes — already persisted)
        if srdg_to_persist:
            self._calibration_acquisition.on_srdg_persisted(
                len(srdg_to_persist), srdg_pending_state
            )

        # Step 2: Publish to brokers
        if persisted_readings:
            await self._broker.publish_batch(persisted_readings)
        if self._safety_broker is not None:
            await self._safety_broker.publish_batch(readings)

    async def _handle_error(self, state: _InstrumentState) -> None:
        """При 3+ ошибках подряд — переподключение с backoff."""
        if state.consecutive_errors >= 3:
            driver = state.config.driver
            logger.warning(
                "Переподключение '%s' после %d ошибок", driver.name, state.consecutive_errors
            )
            try:
                await driver.disconnect()
            except Exception:
                logger.exception("Ошибка отключения '%s'", driver.name)
            await self._backoff(state)

    async def _backoff(self, state: _InstrumentState, *, max_s: float = MAX_BACKOFF_S) -> None:
        """Экспоненциальная задержка перед переподключением."""
        delay = min(state.backoff_s, max_s)
        logger.info("Backoff '%s': %.1fs", state.config.driver.name, delay)
        await asyncio.sleep(delay)
        state.backoff_s = min(state.backoff_s * 2, max_s)

    async def start(self) -> None:
        """Запустить все циклы опроса.

        Приборы на одной GPIB-шине группируются в один последовательный task.
        Все остальные — каждый в своём task.
        """
        self._running = True

        # Group GPIB instruments by bus prefix
        gpib_groups: dict[str, list[_InstrumentState]] = defaultdict(list)
        standalone: list[_InstrumentState] = []

        for name, state in self._instruments.items():
            if not state.config.enabled:
                continue
            bus = _gpib_bus_prefix(state.config.resource_str)
            if bus is not None:
                gpib_groups[bus].append(state)
            else:
                standalone.append(state)

        # Launch one task per GPIB bus
        for bus_prefix, states in gpib_groups.items():
            names = [s.config.driver.name for s in states]
            logger.info(
                "GPIB bus %s: последовательный опрос %d приборов %s",
                bus_prefix,
                len(states),
                names,
            )
            task = asyncio.create_task(
                self._gpib_poll_loop(bus_prefix, states),
                name=f"gpib_poll_{bus_prefix}",
            )
            self._gpib_tasks[bus_prefix] = task
            # Point each state's task ref to the shared task for stop()
            for state in states:
                state.task = task

        # Launch individual tasks for non-GPIB instruments
        for state in standalone:
            state.task = asyncio.create_task(
                self._poll_loop(state), name=f"poll_{state.config.driver.name}"
            )

        total = sum(len(g) for g in gpib_groups.values()) + len(standalone)
        logger.info(
            "Scheduler запущен (%d приборов, %d GPIB bus, %d standalone)",
            total,
            len(gpib_groups),
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
        for task in self._gpib_tasks.values():
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
            try:
                await state.config.driver.disconnect()
            except Exception:
                logger.exception("Ошибка отключения '%s' при остановке", state.config.driver.name)
        self._gpib_tasks.clear()
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
