"""Асинхронная обёртка над pyvisa для GPIB-коммуникации.

Open-per-query: VISA resource открывается и закрывается на каждую операцию.
Сериализация доступа к шине обеспечивается единым asyncio task на каждую
GPIB-шину в Scheduler.

Query реализован как write → sleep(0.1) → read (LabVIEW-совместимо).
resource.clear() (SDC) НЕ вызывается в горячем пути — LS218 serial LSB183
сбрасывает channel mux при SDC. clear() используется только в IFC recovery.
"""
from __future__ import annotations

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS = 10_000
_WRITE_READ_DELAY_S = 0.1


class GPIBTransport:
    """Асинхронный GPIB транспорт: open-per-query, write-delay-read.

    Каждая операция (query / write) атомарно открывает VISA resource,
    выполняет команду и закрывает resource.

    Query использует явный write → sleep(100ms) → read вместо
    resource.query() для совместимости с LakeShore 218S.

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
        """Отправить запрос и вернуть ответ (open → write → delay → read → close).

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

    def _open_resource(self, rm: Any, timeout_ms: int) -> Any:
        """Open VISA resource with timeout and termination configured."""
        resource = rm.open_resource(self._resource_str)
        resource.timeout = timeout_ms
        resource.write_termination = "\n"
        resource.read_termination = "\n"
        return resource

    def _blocking_query(self, cmd: str, timeout_ms: int) -> str:
        """Open → write → sleep(0.1) → read → close, с IFC recovery."""
        rm = self._get_rm(self._bus_prefix)
        resource = self._open_resource(rm, timeout_ms)
        try:
            resource.write(cmd)
            time.sleep(_WRITE_READ_DELAY_S)
            result = resource.read().strip()
        except Exception as first_err:
            try:
                resource.close()
            except Exception:
                pass
            log.warning("GPIB: query '%s' failed on %s, attempting IFC recovery", cmd, self._resource_str)
            return self._ifc_retry_query(rm, cmd, timeout_ms, first_err)
        try:
            resource.close()
        except Exception:
            pass
        return result

    def _blocking_write(self, cmd: str, timeout_ms: int) -> None:
        """Open → write → close, с IFC recovery при ошибке."""
        rm = self._get_rm(self._bus_prefix)
        resource = self._open_resource(rm, timeout_ms)
        try:
            resource.write(cmd)
        except Exception as first_err:
            try:
                resource.close()
            except Exception:
                pass
            log.warning("GPIB: write '%s' failed on %s, attempting IFC recovery", cmd, self._resource_str)
            self._ifc_retry_write(rm, cmd, timeout_ms, first_err)
            return
        try:
            resource.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # IFC recovery (clear() used only here, not in hot path)
    # ------------------------------------------------------------------

    def _ifc_retry_query(self, rm: Any, cmd: str, timeout_ms: int, original_err: Exception) -> str:
        """IFC + sleep + clear + write-delay-read retry."""
        try:
            self._send_ifc(rm)
        except Exception as ifc_err:
            log.error("GPIB: IFC failed on %s — %s", self._bus_prefix, ifc_err)
            raise original_err from ifc_err
        time.sleep(0.5)
        resource = self._open_resource(rm, timeout_ms)
        try:
            resource.clear()
            time.sleep(_WRITE_READ_DELAY_S)
            resource.write(cmd)
            time.sleep(_WRITE_READ_DELAY_S)
            result = resource.read().strip()
        except Exception:
            try:
                resource.close()
            except Exception:
                pass
            raise
        try:
            resource.close()
        except Exception:
            pass
        log.info("GPIB: IFC recovery succeeded for '%s' on %s", cmd, self._resource_str)
        return result

    def _ifc_retry_write(self, rm: Any, cmd: str, timeout_ms: int, original_err: Exception) -> None:
        """IFC + sleep + clear + retry write."""
        try:
            self._send_ifc(rm)
        except Exception as ifc_err:
            log.error("GPIB: IFC failed on %s — %s", self._bus_prefix, ifc_err)
            raise original_err from ifc_err
        time.sleep(0.5)
        resource = self._open_resource(rm, timeout_ms)
        try:
            resource.clear()
            time.sleep(_WRITE_READ_DELAY_S)
            resource.write(cmd)
        except Exception:
            try:
                resource.close()
            except Exception:
                pass
            raise
        try:
            resource.close()
        except Exception:
            pass
        log.info("GPIB: IFC recovery succeeded for write '%s' on %s", cmd, self._resource_str)

    def _send_ifc(self, rm: Any) -> None:
        """Send IFC (Interface Clear) to reset the GPIB bus."""
        intf = rm.open_resource(f"{self._bus_prefix}::INTFC")
        try:
            intf.send_ifc()
            log.warning("GPIB: IFC sent on %s", self._bus_prefix)
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
            ch = cmd_upper.replace("KRDG?", "").strip()
            if ch and ch != "0":
                # Per-channel query: return single value
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
            if ch and ch != "0":
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
