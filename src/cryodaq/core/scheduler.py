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
    ) -> None:
        self._broker = broker
        self._safety_broker = safety_broker
        self._sqlite_writer = sqlite_writer
        self._adaptive_throttle = adaptive_throttle
        self._calibration_acquisition = calibration_acquisition
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
                readings = await asyncio.wait_for(
                    driver.safe_read(), timeout=cfg.read_timeout_s
                )
                await self._process_readings(state, readings)
            except TimeoutError:
                state.consecutive_errors += 1
                state.total_errors += 1
                logger.warning(
                    "Таймаут опроса '%s' (%.1fs), ошибок подряд: %d",
                    name, cfg.read_timeout_s, state.consecutive_errors,
                )
                await self._handle_error(state)
            except Exception:
                state.consecutive_errors += 1
                state.total_errors += 1
                logger.exception("Ошибка опроса '%s', ошибок подряд: %d", name, state.consecutive_errors)
                await self._handle_error(state)

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
        last_reconnect: dict[str, float] = {}
        last_preventive_clear: dict[str, float] = {}

        # Подключить все последовательно — skip failures
        for state in states:
            driver = state.config.driver
            try:
                await asyncio.wait_for(driver.connect(), timeout=_CONNECT_TIMEOUT_S)
                state.consecutive_errors = 0
                logger.info("Прибор '%s' подключён (GPIB bus %s)", driver.name, bus_prefix)
            except Exception:
                logger.warning("Не удалось подключить '%s' на %s — skipping", driver.name, bus_prefix)
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
                    transport = getattr(driver, '_transport', None)
                    if transport is not None and hasattr(transport, 'clear_bus'):
                        try:
                            await asyncio.wait_for(transport.clear_bus(), timeout=2.0)
                            last_preventive_clear[name] = now
                        except Exception:
                            pass

                # Poll
                try:
                    readings = await asyncio.wait_for(
                        driver.safe_read(), timeout=_POLL_TIMEOUT_S
                    )
                    await self._process_readings(state, readings)
                except Exception as exc:
                    state.consecutive_errors += 1
                    state.total_errors += 1
                    logger.warning("Ошибка опроса '%s': %s (подряд: %d)", name, exc, state.consecutive_errors)

                    # Clear bus after error to unblock other instruments
                    transport = getattr(driver, '_transport', None)
                    if transport is not None and hasattr(transport, 'clear_bus'):
                        try:
                            await asyncio.wait_for(transport.clear_bus(), timeout=2.0)
                        except Exception:
                            logger.warning("Bus clear failed after '%s' error", name)

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

    async def _process_readings(
        self, state: _InstrumentState, readings: list[Any]
    ) -> None:
        """Persist, calibrate, and publish readings — shared by both loop types."""
        driver = state.config.driver
        name = driver.name
        persisted_readings = list(readings)
        if self._adaptive_throttle is not None:
            persisted_readings = self._adaptive_throttle.filter_for_archive(readings)
        state.total_reads += 1
        state.consecutive_errors = 0
        state.backoff_s = INITIAL_BACKOFF_S

        # Step 1: Persist to disk FIRST
        if self._sqlite_writer is not None and persisted_readings:
            try:
                await self._sqlite_writer.write_immediate(persisted_readings)
            except Exception:
                logger.exception(
                    "CRITICAL: Ошибка записи '%s' — данные НЕ отправлены подписчикам",
                    name,
                )
                state.consecutive_errors += 1
                state.total_errors += 1
                return

        # Step 1b: If calibration acquisition active, read SRDG
        if (
            self._calibration_acquisition is not None
            and self._calibration_acquisition.is_active
            and hasattr(driver, "read_srdg_channels")
        ):
            try:
                srdg = await driver.read_srdg_channels()
                await self._calibration_acquisition.on_readings(readings, srdg)
            except Exception:
                logger.warning(
                    "Failed to read SRDG for calibration on '%s'",
                    name,
                    exc_info=True,
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
            logger.warning("Переподключение '%s' после %d ошибок", driver.name, state.consecutive_errors)
            try:
                await driver.disconnect()
            except Exception:
                logger.exception("Ошибка отключения '%s'", driver.name)
            await self._backoff(state)

    async def _backoff(self, state: _InstrumentState) -> None:
        """Экспоненциальная задержка перед переподключением."""
        delay = min(state.backoff_s, MAX_BACKOFF_S)
        logger.info("Backoff '%s': %.1fs", state.config.driver.name, delay)
        await asyncio.sleep(delay)
        state.backoff_s = min(state.backoff_s * 2, MAX_BACKOFF_S)

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
                bus_prefix, len(states), names,
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
            total, len(gpib_groups), len(standalone),
        )

    async def stop(self) -> None:
        """Остановить все циклы, отключить приборы."""
        self._running = False

        # Gather all unique tasks
        all_tasks: set[asyncio.Task[None]] = set()
        for state in self._instruments.values():
            if state.task and not state.task.done():
                all_tasks.add(state.task)
        for task in self._gpib_tasks.values():
            if not task.done():
                all_tasks.add(task)

        for task in all_tasks:
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
