"""Асинхронная обёртка над pyvisa для GPIB-коммуникации.

Open-per-query: VISA resource открывается и закрывается на каждую операцию.
NI GPIB-USB-HS зависает навсегда после VI_ERROR_TMO если ресурс остаётся
открытым. IFC (Interface Clear) сбрасывает шину после таймаута.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS = 10_000


class GPIBTransport:
    """Асинхронный GPIB транспорт: open-per-query + IFC bus reset.

    Каждая операция (query / write) атомарно открывает VISA resource,
    выполняет команду и закрывает resource. Это предотвращает зависание
    NI GPIB-USB-HS после VI_ERROR_TMO.

    GPIB — half-duplex шина: все операции на одном контроллере (``GPIB0``)
    сериализуются через общий ``asyncio.Lock``.

    При таймауте автоматически отправляется IFC (Interface Clear) для
    сброса шины без power cycle.

    Parameters
    ----------
    mock:
        Если ``True`` — работает без реального VISA-бэкенда.
    """

    _bus_locks: dict[str, asyncio.Lock] = {}
    _resource_managers: dict[str, Any] = {}

    def __init__(self, *, mock: bool = False) -> None:
        self.mock = mock
        self._resource_str: str = ""
        self._bus_prefix: str = ""
        self._bus_lock: asyncio.Lock | None = None
        self._timeout_ms: int = _DEFAULT_TIMEOUT_MS

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @classmethod
    def get_bus_lock(cls, resource_str: str) -> asyncio.Lock:
        """Get or create the shared bus lock for a GPIB controller prefix."""
        bus_prefix = resource_str.split("::")[0]
        if bus_prefix not in cls._bus_locks:
            cls._bus_locks[bus_prefix] = asyncio.Lock()
        return cls._bus_locks[bus_prefix]

    @classmethod
    def _get_rm(cls, bus_prefix: str) -> Any:
        """Get or create a shared ResourceManager for a bus prefix."""
        if bus_prefix not in cls._resource_managers:
            import pyvisa
            cls._resource_managers[bus_prefix] = pyvisa.ResourceManager()
        return cls._resource_managers[bus_prefix]

    async def open(self, resource_str: str, *, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> None:
        """Сохранить параметры подключения. Не открывает VISA resource.

        Parameters
        ----------
        resource_str:
            VISA-строка ресурса, например ``"GPIB0::12::INSTR"``.
        timeout_ms:
            Таймаут по умолчанию для query/write операций.
        """
        self._resource_str = resource_str
        self._bus_prefix = resource_str.split("::")[0]
        self._bus_lock = self.get_bus_lock(resource_str)
        self._timeout_ms = timeout_ms

        if self.mock:
            log.info("GPIB [mock]: имитация открытия ресурса %s", resource_str)
            return

        log.info("GPIB: ресурс %s зарегистрирован (open-per-query)", resource_str)

    async def close(self) -> None:
        """No-op: ресурсы закрываются после каждой операции."""
        if self.mock:
            log.info("GPIB [mock]: имитация закрытия ресурса %s", self._resource_str)
            return
        log.info("GPIB: ресурс %s отключён", self._resource_str)

    async def write(self, cmd: str) -> None:
        """Отправить команду прибору (open → write → close).

        Parameters
        ----------
        cmd:
            SCPI-команда, например ``"*RST"``.
        """
        if self.mock:
            log.debug("GPIB [mock] write: %s", cmd)
            return

        loop = asyncio.get_running_loop()
        assert self._bus_lock is not None
        async with self._bus_lock:
            try:
                await loop.run_in_executor(
                    None, self._blocking_write, cmd, self._timeout_ms
                )
                log.debug("GPIB write → %s: %s", self._resource_str, cmd)
            except Exception as exc:
                log.error("GPIB: ошибка записи '%s' в %s — %s", cmd, self._resource_str, exc)
                await self._try_ifc(loop)
                raise

    async def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        """Отправить запрос и вернуть ответ (open → query → close).

        Parameters
        ----------
        cmd:
            SCPI-запрос, например ``"*IDN?"``.
        timeout_ms:
            Таймаут в миллисекундах. По умолчанию значение из open().

        Returns
        -------
        str
            Ответ прибора.
        """
        if self.mock:
            response = self._mock_response(cmd)
            log.debug("GPIB [mock] query '%s' → '%s'", cmd, response)
            return response

        effective_timeout = timeout_ms if timeout_ms is not None else self._timeout_ms
        loop = asyncio.get_running_loop()
        assert self._bus_lock is not None
        async with self._bus_lock:
            try:
                response: str = await loop.run_in_executor(
                    None, self._blocking_query, cmd, effective_timeout
                )
                log.debug("GPIB query '%s' → '%s'", cmd, response)
                return response
            except Exception as exc:
                log.error("GPIB: ошибка запроса '%s' к %s — %s", cmd, self._resource_str, exc)
                await self._try_ifc(loop)
                raise

    async def flush_input(self) -> None:
        """No-op: open-per-query не имеет буфера для очистки."""

    # ------------------------------------------------------------------
    # IFC bus reset
    # ------------------------------------------------------------------

    async def _try_ifc(self, loop: asyncio.AbstractEventLoop) -> None:
        """Попытка IFC (Interface Clear) для сброса GPIB шины после ошибки."""
        try:
            await loop.run_in_executor(None, self._blocking_ifc)
            log.warning("GPIB: IFC sent on %s — bus reset", self._bus_prefix)
        except Exception as ifc_exc:
            log.error("GPIB: IFC failed on %s — %s", self._bus_prefix, ifc_exc)

    # ------------------------------------------------------------------
    # Блокирующие методы (выполняются в executor)
    # ------------------------------------------------------------------

    def _blocking_query(self, cmd: str, timeout_ms: int) -> str:
        """Open → query → close. Атомарная операция в одном потоке."""
        rm = self._get_rm(self._bus_prefix)
        resource = rm.open_resource(self._resource_str)
        try:
            resource.timeout = timeout_ms
            return resource.query(cmd).strip()
        finally:
            try:
                resource.close()
            except Exception:
                pass

    def _blocking_write(self, cmd: str, timeout_ms: int) -> None:
        """Open → write → close. Атомарная операция в одном потоке."""
        rm = self._get_rm(self._bus_prefix)
        resource = rm.open_resource(self._resource_str)
        try:
            resource.timeout = timeout_ms
            resource.write(cmd)
        finally:
            try:
                resource.close()
            except Exception:
                pass

    def _blocking_ifc(self) -> None:
        """Послать IFC (Interface Clear) через GPIB controller interface."""
        rm = self._get_rm(self._bus_prefix)
        intf = rm.open_resource(f"{self._bus_prefix}::INTFC")
        try:
            intf.send_ifc()
        finally:
            try:
                intf.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Mock-утилиты
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_response(cmd: str) -> str:
        """Сформировать имитированный ответ для известных SCPI-команд."""
        cmd_upper = cmd.strip().upper()
        if cmd_upper == "*IDN?":
            return "LSCI,MODEL218S,MOCK001,010101"
        if cmd_upper.startswith("KRDG?"):
            return (
                "+004.235E+0,+004.891E+0,+004.100E+0,+003.998E+0,"
                "+004.567E+0,+004.123E+0,+003.876E+0,+004.321E+0"
            )
        if cmd_upper.startswith("SRDG?"):
            return (
                "+8.298000E+1,+8.017000E+1,+1.738000E+1,+1.728000E+1,"
                "+8.204000E+1,+8.332000E+1,+8.433000E+1,+5.114000E+0"
            )
        return ""
