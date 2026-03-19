"""Асинхронная обёртка над pyvisa для GPIB-коммуникации.

Open-per-query: VISA resource открывается и закрывается на каждую операцию.
Сериализация доступа к шине обеспечивается не asyncio.Lock, а единым
asyncio task на каждую GPIB-шину в Scheduler.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS = 10_000


class GPIBTransport:
    """Асинхронный GPIB транспорт: open-per-query.

    Каждая операция (query / write) атомарно открывает VISA resource,
    выполняет команду и закрывает resource. Это предотвращает зависание
    NI GPIB-USB-HS после VI_ERROR_TMO.

    Сериализация гарантируется Scheduler — все приборы на одной GPIB-шине
    опрашиваются в одном asyncio task последовательно.

    Parameters
    ----------
    mock:
        Если ``True`` — работает без реального VISA-бэкенда.
    """

    _resource_managers: dict[str, Any] = {}

    def __init__(self, *, mock: bool = False) -> None:
        self.mock = mock
        self._resource_str: str = ""
        self._bus_prefix: str = ""
        self._timeout_ms: int = _DEFAULT_TIMEOUT_MS

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

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

        import asyncio
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, self._blocking_write, cmd, self._timeout_ms
            )
            log.debug("GPIB write → %s: %s", self._resource_str, cmd)
        except Exception as exc:
            log.error("GPIB: ошибка записи '%s' в %s — %s", cmd, self._resource_str, exc)
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
        import asyncio
        loop = asyncio.get_running_loop()
        try:
            response: str = await loop.run_in_executor(
                None, self._blocking_query, cmd, effective_timeout
            )
            log.debug("GPIB query '%s' → '%s'", cmd, response)
            return response
        except Exception as exc:
            log.error("GPIB: ошибка запроса '%s' к %s — %s", cmd, self._resource_str, exc)
            raise

    async def flush_input(self) -> None:
        """No-op: open-per-query не имеет буфера для очистки."""

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
