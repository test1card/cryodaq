"""Асинхронная обёртка над pyvisa для GPIB-коммуникации.

Persistent sessions: VISA resource открывается один раз в connect(),
используется для всех query/write, закрывается в close().
Точное воспроизведение LabVIEW-схемы: open → VISA Clear → loop { write → wait 100ms → read }.

Сериализация доступа к шине обеспечивается единым asyncio task на каждую
GPIB-шину в Scheduler. Никакого IFC, никаких retry — при ошибке raise,
scheduler пропустит прибор и попробует на следующем цикле.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS = 2000
_WRITE_READ_DELAY_S = 0.1


class GPIBTransport:
    """Асинхронный GPIB транспорт: persistent session, write-delay-read.

    connect() открывает VISA resource один раз + VISA Clear.
    query() использует write → sleep(100ms) → read на persistent resource.
    close() закрывает resource.

    Никаких IFC, retry, open-per-query. При ошибке — raise.
    Scheduler пропускает сбойный прибор и продолжает опрос остальных.

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
        self._resource: Any = None
        self._timeout_ms: int = _DEFAULT_TIMEOUT_MS

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @classmethod
    def close_all_managers(cls) -> None:
        """Close all cached ResourceManagers. Call at engine shutdown."""
        for bus, rm in cls._resource_managers.items():
            try:
                rm.close()
                log.info("GPIB: ResourceManager for %s closed", bus)
            except Exception as exc:
                log.warning("GPIB: error closing RM for %s — %s", bus, exc)
        cls._resource_managers.clear()

    @classmethod
    def _get_rm(cls, bus_prefix: str) -> Any:
        """Get or create a shared ResourceManager for a bus prefix."""
        if bus_prefix not in cls._resource_managers:
            import pyvisa
            cls._resource_managers[bus_prefix] = pyvisa.ResourceManager()
        return cls._resource_managers[bus_prefix]

    async def open(self, resource_str: str, *, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> None:
        """Open VISA resource, configure termination, VISA Clear once.

        Parameters
        ----------
        resource_str:
            VISA resource string, e.g. ``"GPIB0::12::INSTR"``.
        timeout_ms:
            Default timeout for query/write operations.
        """
        self._resource_str = resource_str
        self._bus_prefix = resource_str.split("::")[0]
        self._timeout_ms = timeout_ms

        if self.mock:
            log.info("GPIB [mock]: open %s", resource_str)
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._blocking_connect)
        log.info("GPIB: %s opened (persistent session)", resource_str)

    async def close(self) -> None:
        """Close the persistent VISA resource."""
        if self.mock:
            log.info("GPIB [mock]: close %s", self._resource_str)
            return

        if self._resource is not None:
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, self._resource.close)
            except Exception as exc:
                log.warning("GPIB: error closing %s — %s", self._resource_str, exc)
            self._resource = None
            log.info("GPIB: %s closed", self._resource_str)

    async def write(self, cmd: str) -> None:
        """Write command to persistent resource.

        Parameters
        ----------
        cmd:
            SCPI command, e.g. ``"*RST"``.
        """
        if self.mock:
            log.debug("GPIB [mock] write: %s", cmd)
            return

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._resource.write, cmd)
        log.debug("GPIB write → %s: %s", self._resource_str, cmd)

    async def query(self, cmd: str, timeout_ms: int | None = None) -> str:
        """Write → sleep(100ms) → read on persistent resource.

        Parameters
        ----------
        cmd:
            SCPI query, e.g. ``"KRDG?"``.
        timeout_ms:
            Per-query timeout override in milliseconds. If ``None``,
            uses the default timeout set at connect time.

        Returns
        -------
        str
            Instrument response, stripped.
        """
        if self.mock:
            response = self._mock_response(cmd)
            log.debug("GPIB [mock] query '%s' → '%s'", cmd, response)
            return response

        loop = asyncio.get_running_loop()
        response: str = await loop.run_in_executor(
            None, self._blocking_query, cmd, timeout_ms
        )
        log.debug("GPIB query '%s' → '%s'", cmd, response)
        return response

    async def flush_input(self) -> None:
        """No-op for API compatibility."""

    # ------------------------------------------------------------------
    # Blocking methods (run in executor)
    # ------------------------------------------------------------------

    def _blocking_connect(self) -> None:
        """Open resource once, configure, VISA Clear once."""
        rm = self._get_rm(self._bus_prefix)
        res = rm.open_resource(self._resource_str)
        try:
            res.write_termination = "\n"
            res.read_termination = "\n"
            res.timeout = self._timeout_ms
            res.clear()
        except Exception:
            # Don't leak the VISA handle if clear() or config fails
            try:
                res.close()
            except Exception:
                pass
            raise
        self._resource = res

    def _blocking_query(self, cmd: str, timeout_ms: int | None = None) -> str:
        """Write → sleep(100ms) → read. LabVIEW-style."""
        res = self._resource
        if res is None:
            raise RuntimeError("GPIB resource not connected")
        old_timeout = None
        if timeout_ms is not None and timeout_ms != self._timeout_ms:
            old_timeout = res.timeout
            res.timeout = timeout_ms
        try:
            res.write(cmd)
            time.sleep(_WRITE_READ_DELAY_S)
            return res.read().strip()
        finally:
            if old_timeout is not None:
                res.timeout = old_timeout

    # ------------------------------------------------------------------
    # Mock
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_response(cmd: str) -> str:
        """Mock responses for known SCPI commands."""
        cmd_upper = cmd.strip().upper()
        if cmd_upper == "*IDN?":
            return "LSCI,MODEL218S,MOCK001,010101"
        if cmd_upper.startswith("KRDG?"):
            ch = cmd_upper.replace("KRDG?", "").strip()
            if ch:
                idx = int(ch) - 1
                values = [
                    "+004.235E+0", "+004.891E+0", "+004.100E+0", "+003.998E+0",
                    "+004.567E+0", "+004.123E+0", "+003.876E+0", "+004.321E+0",
                ]
                return values[idx] if 0 <= idx < 8 else "+000.000E+0"
            return (
                "+004.235E+0,+004.891E+0,+004.100E+0,+003.998E+0,"
                "+004.567E+0,+004.123E+0,+003.876E+0,+004.321E+0"
            )
        if cmd_upper.startswith("SRDG?"):
            ch = cmd_upper.replace("SRDG?", "").strip()
            if ch:
                idx = int(ch) - 1
                values = [
                    "+8.298000E+1", "+8.017000E+1", "+1.738000E+1", "+1.728000E+1",
                    "+8.204000E+1", "+8.332000E+1", "+8.433000E+1", "+5.114000E+0",
                ]
                return values[idx] if 0 <= idx < 8 else "+0.000000E+0"
            return (
                "+8.298000E+1,+8.017000E+1,+1.738000E+1,+1.728000E+1,"
                "+8.204000E+1,+8.332000E+1,+8.433000E+1,+5.114000E+0"
            )
        return ""
