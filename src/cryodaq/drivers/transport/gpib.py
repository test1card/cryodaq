"""Асинхронная обёртка над pyvisa для GPIB-коммуникации."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)


class GPIBTransport:
    """Асинхронный транспорт GPIB на основе pyvisa.

    Все блокирующие вызовы pyvisa выполняются в пуле потоков через
    ``run_in_executor``, чтобы не блокировать event loop.

    Parameters
    ----------
    mock:
        Если ``True`` — работает без реального VISA-бэкенда,
        возвращает предопределённые ответы.
    """

    def __init__(self, *, mock: bool = False) -> None:
        self.mock = mock
        self._resource: Any = None
        self._rm: Any = None
        self._resource_str: str = ""

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    async def open(self, resource_str: str) -> None:
        """Открыть соединение с GPIB-ресурсом.

        Parameters
        ----------
        resource_str:
            VISA-строка ресурса, например ``"GPIB0::12::INSTR"``.
        """
        self._resource_str = resource_str

        if self.mock:
            log.info("GPIB [mock]: имитация открытия ресурса %s", resource_str)
            return

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._blocking_open, resource_str)
            log.info("GPIB: ресурс %s успешно открыт", resource_str)
        except Exception as exc:
            log.error("GPIB: ошибка открытия ресурса %s — %s", resource_str, exc)
            raise

    async def close(self) -> None:
        """Закрыть соединение с ресурсом (идемпотентно)."""
        if self.mock:
            log.info("GPIB [mock]: имитация закрытия ресурса %s", self._resource_str)
            return

        if self._resource is None:
            return

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._blocking_close)
            log.info("GPIB: ресурс %s закрыт", self._resource_str)
        except Exception as exc:
            log.warning("GPIB: ошибка при закрытии ресурса %s — %s", self._resource_str, exc)
        finally:
            self._resource = None

    async def write(self, cmd: str) -> None:
        """Отправить команду прибору без ожидания ответа.

        Parameters
        ----------
        cmd:
            SCPI-команда, например ``"*RST"``.
        """
        if self.mock:
            log.debug("GPIB [mock] write: %s", cmd)
            return

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._resource.write, cmd)
            log.debug("GPIB write → %s: %s", self._resource_str, cmd)
        except Exception as exc:  # pyvisa.errors.VisaIOError и прочие
            log.error("GPIB: ошибка записи команды '%s' в %s — %s", cmd, self._resource_str, exc)
            raise

    async def query(self, cmd: str, timeout_ms: int = 5000) -> str:
        """Отправить запрос и вернуть ответ прибора.

        Parameters
        ----------
        cmd:
            SCPI-запрос, например ``"*IDN?"``.
        timeout_ms:
            Таймаут ожидания ответа в миллисекундах (по умолчанию 5000).

        Returns
        -------
        str
            Ответ прибора без завершающих пробелов и символов новой строки.
        """
        if self.mock:
            response = self._mock_response(cmd)
            log.debug("GPIB [mock] query '%s' → '%s'", cmd, response)
            return response

        loop = asyncio.get_running_loop()
        try:
            response: str = await loop.run_in_executor(
                None, self._blocking_query, cmd, timeout_ms
            )
            log.debug("GPIB query '%s' → '%s'", cmd, response)
            return response
        except Exception as exc:  # pyvisa.errors.VisaIOError и прочие
            log.error(
                "GPIB: ошибка запроса '%s' к %s — %s", cmd, self._resource_str, exc
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

    def _blocking_query(self, cmd: str, timeout_ms: int) -> str:
        """Синхронный query с установкой таймаута (вызывается в executor)."""
        self._resource.timeout = timeout_ms
        return self._resource.query(cmd).strip()

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
            # Восемь реалистичных криогенных температур (Кельвин)
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
