"""Scheduler — планировщик опроса приборов.

Для каждого InstrumentDriver создаёт изолированную asyncio-задачу.
Таймаут одного прибора не блокирует остальные.
При ошибке соединения — экспоненциальный backoff с переподключением.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import InstrumentDriver

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_S = 1.0
MAX_BACKOFF_S = 60.0
INITIAL_BACKOFF_S = 1.0
READ_TIMEOUT_S = 10.0


@dataclass
class InstrumentConfig:
    """Конфигурация опроса одного прибора."""

    driver: InstrumentDriver
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S
    read_timeout_s: float = READ_TIMEOUT_S
    enabled: bool = True


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
    """Планировщик: запускает независимые циклы опроса для каждого прибора.

    Использование::

        scheduler = Scheduler(broker)
        scheduler.add(InstrumentConfig(driver=lakeshore, poll_interval_s=0.5))
        scheduler.add(InstrumentConfig(driver=keithley, poll_interval_s=1.0))
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
    ) -> None:
        self._broker = broker
        self._safety_broker = safety_broker
        self._sqlite_writer = sqlite_writer
        self._adaptive_throttle = adaptive_throttle
        self._instruments: dict[str, _InstrumentState] = {}
        self._running = False

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

        while self._running:
            next_deadline = asyncio.get_event_loop().time() + cfg.poll_interval_s

            # Подключение / переподключение
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

            # Опрос
            try:
                readings = await asyncio.wait_for(
                    driver.safe_read(), timeout=cfg.read_timeout_s
                )
                persisted_readings = list(readings)
                if self._adaptive_throttle is not None:
                    persisted_readings = self._adaptive_throttle.filter_for_archive(readings)
                state.total_reads += 1
                state.consecutive_errors = 0
                state.backoff_s = INITIAL_BACKOFF_S

                # Step 1: Persist to disk FIRST (blocking until WAL commit)
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
                        continue  # Do NOT publish unpersisted data

                # Step 2: ONLY AFTER disk commit, publish to DataBroker and SafetyBroker
                if persisted_readings:
                    await self._broker.publish_batch(persisted_readings)
                if self._safety_broker is not None:
                    await self._safety_broker.publish_batch(readings)
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

            # Пауза до следующего цикла (fixed cadence — компенсирует время опроса)
            sleep_remaining = max(0, next_deadline - asyncio.get_event_loop().time())
            await asyncio.sleep(sleep_remaining)

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
        """Запустить все циклы опроса."""
        self._running = True
        for name, state in self._instruments.items():
            if state.config.enabled:
                state.task = asyncio.create_task(
                    self._poll_loop(state), name=f"poll_{name}"
                )
        logger.info("Scheduler запущен (%d приборов)", len(self._instruments))

    async def stop(self) -> None:
        """Остановить все циклы, отключить приборы."""
        self._running = False
        tasks = [s.task for s in self._instruments.values() if s.task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for state in self._instruments.values():
            state.task = None
            try:
                await state.config.driver.disconnect()
            except Exception:
                logger.exception("Ошибка отключения '%s' при остановке", state.config.driver.name)
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
