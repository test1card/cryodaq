"""Асинхронная обёртка над pyserial-asyncio для последовательной коммуникации (RS-232/USB-Serial)."""  # noqa: E501

from __future__ import annotations

import asyncio
import logging
import math
import threading
from concurrent.futures import Future
from typing import Any

log = logging.getLogger(__name__)

# Таймаут чтения по умолчанию (секунды).  Если прибор не отвечает за это
# время, read_line() бросает asyncio.TimeoutError вместо вечного зависания.
_DEFAULT_READ_TIMEOUT_S: float = 3.0

# Mock-ответы для известных команд
_MOCK_IDN = "Thyracont,VSP63D,MOCK001,1.0"
_MOCK_PRESSURE_RESPONSE = "0,1.234E-06\r"


def _start_serial_open(serial_for_url, port: str, baudrate: int) -> Future[Any]:
    """Start the potentially blocking OS serial open on a daemon thread."""

    future: Future[Any] = Future()

    def _open() -> None:
        if not future.set_running_or_notify_cancel():
            return
        try:
            serial_instance = serial_for_url(port, baudrate=baudrate)
        except BaseException as exc:
            future.set_exception(exc)
        else:
            future.set_result(serial_instance)

    threading.Thread(
        target=_open,
        daemon=True,
        name=f"serial-open-{port}",
    ).start()
    return future


def _reap_late_serial_open(future: Future[Any], port: str) -> None:
    """Close a handle returned after its async caller timed out/cancelled."""

    def _close() -> None:
        try:
            serial_instance = future.result()
        except BaseException as exc:
            log.warning("Serial: late open for %s eventually failed: %s", port, exc)
            return
        try:
            serial_instance.close()
        except BaseException as exc:
            log.critical("Serial: late-open handle cleanup failed for %s: %s", port, exc)

    threading.Thread(
        target=_close,
        daemon=True,
        name=f"serial-close-late-{port}",
    ).start()


class SerialTransport:
    """Асинхронный транспорт RS-232/USB-Serial на основе pyserial-asyncio.

    Все I/O-операции неблокирующие: используется asyncio StreamReader/StreamWriter
    через ``serial_asyncio.open_serial_connection``.

    Parameters
    ----------
    mock:
        Если ``True`` — работает без реального порта, возвращает
        предопределённые ответы.
    """

    def __init__(self, *, mock: bool = False) -> None:
        self.mock = mock
        self._reader = None
        self._writer = None
        self._resource_str: str = ""
        self._read_timeout_s: float = _DEFAULT_READ_TIMEOUT_S

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    async def open(self, port: str, baudrate: int = 9600, timeout: float = 2.0) -> None:  # noqa: ASYNC109
        """Открыть последовательный порт.

        Parameters
        ----------
        port:
            Имя порта, например ``"COM3"`` или ``"/dev/ttyUSB0"``.
        baudrate:
            Скорость обмена в бодах (по умолчанию 9600).
        timeout:
            Таймаут открытия и чтения в секундах (по умолчанию 2.0).
        """
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(float(timeout))
            or float(timeout) <= 0
        ):
            raise ValueError("Serial timeout must be a finite positive number")
        timeout = float(timeout)
        self._resource_str = port
        self._read_timeout_s = timeout

        if self.mock:
            log.info("Serial [mock]: имитация открытия порта %s @ %d бод", port, baudrate)
            return

        try:
            import serial_asyncio  # type: ignore[import]

            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            open_future = _start_serial_open(serial_asyncio.serial.serial_for_url, port, baudrate)
            try:
                serial_instance = await asyncio.wait_for(
                    asyncio.shield(asyncio.wrap_future(open_future)),
                    timeout=timeout,
                )
            except (TimeoutError, asyncio.CancelledError):
                open_future.add_done_callback(lambda completed: _reap_late_serial_open(completed, port))
                raise

            remaining = deadline - loop.time()
            if remaining <= 0:
                await asyncio.to_thread(serial_instance.close)
                raise TimeoutError(f"Serial open timed out for {port}")

            reader = asyncio.StreamReader(loop=loop)
            protocol = asyncio.StreamReaderProtocol(reader, loop=loop)
            try:
                serial_transport, _ = await asyncio.wait_for(
                    serial_asyncio.connection_for_serial(
                        loop,
                        lambda: protocol,
                        serial_instance,
                    ),
                    timeout=remaining,
                )
            except BaseException:
                await asyncio.to_thread(serial_instance.close)
                raise
            self._reader = reader
            self._writer = asyncio.StreamWriter(serial_transport, protocol, reader, loop)
            log.info("Serial: порт %s @ %d бод успешно открыт", port, baudrate)
        except Exception as exc:
            log.error("Serial: ошибка открытия порта %s — %s", port, exc)
            raise

    async def close(self) -> None:
        """Закрыть соединение (идемпотентно)."""
        if self.mock:
            log.info("Serial [mock]: имитация закрытия порта %s", self._resource_str)
            return

        if self._writer is None:
            return

        try:
            self._writer.close()
            await self._writer.wait_closed()
            log.info("Serial: порт %s закрыт", self._resource_str)
        except Exception as exc:
            log.warning("Serial: ошибка при закрытии порта %s — %s", self._resource_str, exc)
        finally:
            self._reader = None
            self._writer = None

    async def query(self, command: str, *, terminator: str = "\r") -> str:
        """Отправить команду и вернуть ответ прибора.

        Parameters
        ----------
        command:
            Команда для отправки (без терминатора).
        terminator:
            Символ-терминатор (по умолчанию ``"\\r"``).

        Returns
        -------
        str
            Ответ прибора (с терминатором, без дополнительной очистки).
        """
        if self.mock:
            response = self._mock_response(command)
            log.debug("Serial [mock] query '%s' → '%s'", command, response.strip())
            return response

        await self.write(command, terminator=terminator)
        return await self.read_line(terminator=terminator)

    async def write(self, data: str, *, terminator: str = "\r") -> None:
        """Отправить данные в порт.

        Parameters
        ----------
        data:
            Строка для отправки (без терминатора).
        terminator:
            Символ-терминатор (по умолчанию ``"\\r"``).
        """
        if self.mock:
            log.debug("Serial [mock] write: %s", data)
            return

        if self._writer is None:
            raise RuntimeError("Serial: порт не открыт")

        payload = (data + terminator).encode()
        self._writer.write(payload)
        await self._writer.drain()
        log.debug("Serial write → %s: %s", self._resource_str, data)

    async def read_line(self, *, terminator: str = "\r", timeout: float | None = None) -> str:  # noqa: ASYNC109
        """Читать байты из порта до терминатора.

        Parameters
        ----------
        terminator:
            Символ-терминатор (по умолчанию ``"\\r"``).
        timeout:
            Таймаут чтения в секундах (``None`` → использует значение из ``open()``).

        Returns
        -------
        str
            Прочитанная строка, включая терминатор.

        Raises
        ------
        asyncio.TimeoutError
            Если прибор не ответил за отведённое время.
        """
        if self.mock:
            return _MOCK_PRESSURE_RESPONSE

        if self._reader is None:
            raise RuntimeError("Serial: порт не открыт")

        effective_timeout = timeout if timeout is not None else self._read_timeout_s
        data = await asyncio.wait_for(
            self._reader.readuntil(terminator.encode()),
            timeout=effective_timeout,
        )
        return data.decode(errors="replace")

    async def flush_input(self) -> None:
        """Очистить входной буфер (сбросить незапрошенные данные).

        Полезно между probe-запросами в connect(), когда предыдущая попытка
        могла оставить мусор в буфере.
        """
        if self.mock or self._reader is None:
            return
        try:
            # Прочитать всё, что есть в буфере, с минимальным таймаутом
            while True:
                data = await asyncio.wait_for(self._reader.read(4096), timeout=0.1)
                if not data:
                    break
        except TimeoutError:
            pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Mock-утилиты
    # ------------------------------------------------------------------

    @staticmethod
    def _mock_response(command: str) -> str:
        """Сформировать имитированный ответ для известных команд."""
        cmd_stripped = command.strip()
        cmd_upper = cmd_stripped.upper()
        if cmd_upper in ("*IDN?", "IDN?"):
            return _MOCK_IDN
        if cmd_upper.startswith("MV"):
            return _MOCK_PRESSURE_RESPONSE
        # Protocol V1: "<addr>M^" → "<addr>M<5digits><checksum>\r"
        if len(cmd_stripped) >= 5 and cmd_stripped[3] == "M":
            addr = cmd_stripped[:3]
            return f"{addr}M100023D\r"
        return "\r"
