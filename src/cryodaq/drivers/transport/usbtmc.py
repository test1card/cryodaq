"""Асинхронная обёртка над pyvisa для USB-TMC коммуникации."""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)

# Имитированные ответы Keithley 2604B для mock-режима
_MOCK_IDN = "Keithley Instruments Inc., Model 2604B, MOCK00001, 3.0.0"
# smua.measure.iv() возвращает ток\tнапряжение
_MOCK_IV_RESPONSE = "0.01\t5.0"
_CLOSE_TIMEOUT_S = 1.0


def _run_with_timeout(fn, *, timeout_s: float, label: str) -> None:
    """Run a blocking cleanup function with a bounded wait."""
    done = threading.Event()
    error: list[Exception] = []

    def _runner() -> None:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            error.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=_runner, daemon=True, name=f"usbtmc-close-{label}")
    thread.start()
    if not done.wait(timeout_s):
        log.warning(
            "USBTMC: timed out closing %s after %.1fs; detaching close thread",
            label,
            timeout_s,
        )
        return
    if error:
        raise error[0]


class USBTMCTransport:
    """Асинхронный транспорт USB-TMC на основе pyvisa.

    Все блокирующие вызовы pyvisa выполняются в пуле потоков через
    ``run_in_executor``, чтобы не блокировать event loop.

    Интерфейс аналогичен :class:`~cryodaq.drivers.transport.gpib.GPIBTransport`,
    адаптирован для USB-TMC приборов (в частности Keithley 2604B с TSP).

    Parameters
    ----------
    mock:
        Если ``True`` — работает без реального VISA-бэкенда,
        возвращает предопределённые ответы Keithley 2604B.
    """

    def __init__(self, *, mock: bool = False) -> None:
        self.mock = mock
        self._resource: Any = None
        self._rm: Any = None
        self._resource_str: str = ""
        self._lock: asyncio.Lock = asyncio.Lock()
        # Phase 2b F.2: dedicated single-worker executor — see GPIBTransport.
        self._executor: ThreadPoolExecutor | None = None
        # Внутренний счётчик для mock: имитация буфера измерений
        self._mock_buf_index: int = 0

    def _get_executor(self) -> ThreadPoolExecutor:
        """Lazily create the per-transport executor on first use."""
        if self._executor is None:
            label = self._resource_str or "usbtmc"
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix=f"visa_usbtmc_{label}",
            )
        return self._executor

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    async def open(self, resource_str: str) -> None:
        """Открыть соединение с USB-TMC ресурсом.

        Parameters
        ----------
        resource_str:
            VISA-строка ресурса, например
            ``"USB0::0x05E6::0x2604::SERIALNUM::INSTR"``.
        """
        async with self._lock:
            self._resource_str = resource_str

            if self.mock:
                log.info("USBTMC [mock]: имитация открытия ресурса %s", resource_str)
                return

            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(self._get_executor(), self._blocking_open, resource_str)
                log.info("USBTMC: ресурс %s успешно открыт", resource_str)
            except Exception as exc:
                log.error("USBTMC: ошибка открытия ресурса %s — %s", resource_str, exc)
                raise

    async def close(self) -> None:
        """Закрыть соединение с ресурсом (идемпотентно)."""
        async with self._lock:
            if self.mock:
                log.info("USBTMC [mock]: имитация закрытия ресурса %s", self._resource_str)
                return

            if self._resource is None:
                return

            resource = self._resource
            manager = self._rm
            self._resource = None
            self._rm = None
            try:
                await asyncio.to_thread(
                    _run_with_timeout,
                    lambda: self._blocking_close_handles(resource, manager),
                    timeout_s=_CLOSE_TIMEOUT_S,
                    label=self._resource_str or "usbtmc",
                )
                log.info("USBTMC: ресурс %s закрыт", self._resource_str)
            except Exception as exc:
                log.warning(
                    "USBTMC: ошибка при закрытии ресурса %s — %s",
                    self._resource_str,
                    exc,
                )
            finally:
                # Shut down the dedicated executor so threads do not
                # accumulate across reconnects.
                if self._executor is not None:
                    self._executor.shutdown(wait=False, cancel_futures=True)
                    self._executor = None

    async def write(self, cmd: str) -> None:
        """Отправить TSP-команду прибору без ожидания ответа.

        Parameters
        ----------
        cmd:
            TSP-команда на языке Lua, например
            ``"smua.source.output = smua.OUTPUT_OFF"``.
        """
        if self.mock:
            log.debug("USBTMC [mock] write: %s", cmd)
            return

        async with self._lock:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(self._get_executor(), self._resource.write, cmd)
                log.debug("USBTMC write → %s: %s", self._resource_str, cmd)
            except Exception as exc:
                log.error(
                    "USBTMC: ошибка записи команды '%s' в %s — %s",
                    cmd,
                    self._resource_str,
                    exc,
                )
                raise

    async def write_raw(self, data: bytes) -> None:
        """Отправить сырые байты прибору (для загрузки больших TSP-скриптов).

        Parameters
        ----------
        data:
            Байтовая последовательность для передачи в прибор.
        """
        if self.mock:
            log.debug(
                "USBTMC [mock] write_raw: %d байт",
                len(data),
            )
            return

        async with self._lock:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(self._get_executor(), self._resource.write_raw, data)
                log.debug(
                    "USBTMC write_raw → %s: %d байт",
                    self._resource_str,
                    len(data),
                )
            except Exception as exc:
                log.error(
                    "USBTMC: ошибка write_raw в %s — %s",
                    self._resource_str,
                    exc,
                )
                raise

    async def query(self, cmd: str, timeout_ms: int = 5000) -> str:
        """Отправить TSP-запрос и вернуть ответ прибора.

        Parameters
        ----------
        cmd:
            TSP-команда, возвращающая значение через ``print()``,
            например ``"print(smua.measure.iv())"``.
        timeout_ms:
            Таймаут ожидания ответа в миллисекундах (по умолчанию 5000).

        Returns
        -------
        str
            Ответ прибора без завершающих пробелов и символов новой строки.
        """
        if self.mock:
            response = self._mock_response(cmd)
            log.debug("USBTMC [mock] query '%s' → '%s'", cmd, response)
            return response

        async with self._lock:
            loop = asyncio.get_running_loop()
            try:
                response: str = await loop.run_in_executor(
                    self._get_executor(), self._blocking_query, cmd, timeout_ms
                )
                log.debug("USBTMC query '%s' → '%s'", cmd, response)
                return response
            except Exception as exc:
                log.error(
                    "USBTMC: ошибка запроса '%s' к %s — %s",
                    cmd,
                    self._resource_str,
                    exc,
                )
                raise

    # ------------------------------------------------------------------
    # Блокирующие вспомогательные методы (выполняются в executor)
    # ------------------------------------------------------------------

    def _blocking_open(self, resource_str: str) -> None:
        """Синхронное открытие VISA-ресурса (вызывается в executor)."""
        import pyvisa  # импорт здесь, чтобы не падать при отсутствии библиотеки в mock-режиме

        self._rm = pyvisa.ResourceManager()
        self._resource = self._rm.open_resource(resource_str)

    def _blocking_close(self) -> None:
        """Синхронное закрытие VISA-ресурса (вызывается в executor)."""
        self._resource.close()
        if self._rm is not None:
            self._rm.close()
            self._rm = None

    def _blocking_close_handles(self, resource: Any, manager: Any) -> None:
        """Close explicit resource/manager handles outside the worker executor."""
        try:
            resource.close()
        finally:
            if manager is not None:
                manager.close()

    def _blocking_query(self, cmd: str, timeout_ms: int) -> str:
        """Синхронный query с установкой таймаута (вызывается в executor)."""
        self._resource.timeout = timeout_ms
        return self._resource.query(cmd).strip()

    # ------------------------------------------------------------------
    # Mock-утилиты
    # ------------------------------------------------------------------

    def _mock_response(self, cmd: str) -> str:
        """Сформировать имитированный ответ для известных TSP-команд Keithley."""
        cmd_stripped = cmd.strip()
        cmd_upper = cmd_stripped.upper()

        if cmd_upper == "*IDN?":
            return _MOCK_IDN

        # print(smua.measure.iv()) — возвращает ток\tнапряжение
        if "SMUA.MEASURE.IV" in cmd_upper:
            return _MOCK_IV_RESPONSE

        # Чтение буфера через printbuffer(...)
        if cmd_upper.startswith("PRINTBUFFER"):
            self._mock_buf_index += 1
            # Имитируем: timestamp, voltage, current
            ts = float(self._mock_buf_index) * 0.5
            return f"{ts}\t5.0\t0.01"

        # Чтение флага ошибки TSP-скрипта
        if "SCRIPT_ERROR" in cmd_upper:
            return "NONE"

        # Общий print() без распознанного паттерна
        if cmd_stripped.startswith("print("):
            return "0"

        return ""
