"""Драйвер вакуумметра Thyracont VSP63D (RS-232/USB-Serial)."""
from __future__ import annotations

import logging
import math
import random
import time

from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.transport.serial import SerialTransport

log = logging.getLogger(__name__)

# Коды статуса из ответа прибора
_STATUS_OK = 0
_STATUS_UNDERRANGE = 1
_STATUS_OVERRANGE = 2
_STATUS_SENSOR_ERROR = 3

# Карта кода статуса → ChannelStatus
_STATUS_MAP: dict[int, ChannelStatus] = {
    _STATUS_OK: ChannelStatus.OK,
    _STATUS_UNDERRANGE: ChannelStatus.UNDERRANGE,
    _STATUS_OVERRANGE: ChannelStatus.OVERRANGE,
    _STATUS_SENSOR_ERROR: ChannelStatus.SENSOR_ERROR,
}

# Mock-параметры: реалистичный вакуум
_MOCK_BASE_PRESSURE_MBAR: float = 1.5e-6


class ThyracontVSP63D(InstrumentDriver):
    """Вакуумметр Thyracont VSP63D.

    Протокол: RS-232/USB-Serial, 9600 бод.
    Команда: ``"MV00\\r"`` → ответ: ``"status,value\\r"``

    Статусы ответа:
      0 = OK (измерение в норме)
      1 = underrange (давление ниже диапазона)
      2 = overrange (давление выше диапазона)
      3 = sensor error

    Parameters
    ----------
    name:
        Уникальное имя экземпляра прибора (используется в метаданных Reading).
    resource_str:
        Имя последовательного порта, например ``"COM3"`` или ``"/dev/ttyUSB0"``.
    baudrate:
        Скорость обмена в бодах (по умолчанию 9600).
    mock:
        Если ``True`` — работает без реального прибора, возвращает
        имитированное давление ~1.5e-6 мбар.
    """

    def __init__(
        self,
        name: str,
        resource_str: str,
        *,
        baudrate: int = 9600,
        mock: bool = False,
    ) -> None:
        super().__init__(name, mock=mock)
        self._resource_str = resource_str
        self._baudrate = baudrate
        self._transport = SerialTransport(mock=mock)
        self._instrument_id: str = ""

    # ------------------------------------------------------------------
    # InstrumentDriver — обязательный интерфейс
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Открыть последовательный порт и верифицировать связь с прибором.

        Устанавливает флаг ``_connected = True`` при успехе.
        """
        log.info("%s: подключение к %s @ %d бод", self.name, self._resource_str, self._baudrate)
        await self._transport.open(self._resource_str, baudrate=self._baudrate)

        try:
            idn = await self._transport.query("*IDN?")
            self._instrument_id = idn.strip()
            log.info("%s: IDN = %s", self.name, self._instrument_id)
        except Exception as exc:
            log.error("%s: не удалось получить IDN — %s", self.name, exc)
            await self._transport.close()
            raise

        self._connected = True
        log.info("%s: соединение установлено", self.name)

    async def disconnect(self) -> None:
        """Разорвать соединение с прибором (идемпотентно)."""
        if not self._connected:
            return
        log.info("%s: отключение", self.name)
        await self._transport.close()
        self._connected = False

    async def read_channels(self) -> list[Reading]:
        """Считать давление командой ``MV00``.

        Returns
        -------
        list[Reading]
            Список из одного объекта :class:`~cryodaq.drivers.base.Reading`.
            Единица измерения — миллибар (``"mbar"``).

        Raises
        ------
        RuntimeError
            Если прибор не подключён.
        """
        if not self._connected:
            raise RuntimeError(f"{self.name}: прибор не подключён")

        if self.mock:
            return self._mock_readings()

        raw_response = await self._transport.query("MV00")
        log.debug("%s: MV00 → %s", self.name, raw_response.strip())
        return [self._parse_response(raw_response)]

    # ------------------------------------------------------------------
    # Разбор ответа прибора
    # ------------------------------------------------------------------

    def _parse_response(self, response: str) -> Reading:
        """Разобрать строку ответа ``"status,value\\r"`` в Reading.

        Формат ответа: ``"<код_статуса>,<значение_давления>\\r"``, например::

            0,1.234E-06\\r

        Parameters
        ----------
        response:
            Сырая строка ответа от прибора.

        Returns
        -------
        Reading
            Показание давления с соответствующим статусом.
        """
        response_stripped = response.strip()
        channel = f"{self.name}/pressure"

        try:
            parts = response_stripped.split(",", 1)
            if len(parts) != 2:
                raise ValueError(f"Неверный формат ответа: '{response_stripped}'")

            status_code = int(parts[0].strip())
            value = float(parts[1].strip())
        except (ValueError, IndexError) as exc:
            log.error(
                "%s: не удалось разобрать ответ '%s' — %s",
                self.name,
                response_stripped,
                exc,
            )
            return Reading.now(
                channel=channel,
                value=float("nan"),
                unit="mbar",
                status=ChannelStatus.SENSOR_ERROR,
                raw=None,
                metadata={"instrument_id": self.name, "raw_response": response_stripped},
            )

        ch_status = _STATUS_MAP.get(status_code, ChannelStatus.SENSOR_ERROR)

        if ch_status != ChannelStatus.OK:
            log.warning(
                "%s: статус ответа %d (%s), значение=%s мбар",
                self.name,
                status_code,
                ch_status.value,
                value,
            )

        return Reading.now(
            channel=channel,
            value=value,
            unit="mbar",
            status=ch_status,
            raw=value,
            metadata={"instrument_id": self.name, "status_code": status_code},
        )

    # ------------------------------------------------------------------
    # Mock-режим
    # ------------------------------------------------------------------

    def _mock_readings(self) -> list[Reading]:
        """Сгенерировать реалистичное имитированное давление (~1.5e-6 мбар)."""
        noise = random.uniform(0.8, 1.2)
        drift = math.sin(time.monotonic() * 0.001) * _MOCK_BASE_PRESSURE_MBAR * 0.05
        value = _MOCK_BASE_PRESSURE_MBAR * noise + drift

        return [
            Reading.now(
                channel=f"{self.name}/pressure",
                value=value,
                unit="mbar",
                status=ChannelStatus.OK,
                raw=value,
                metadata={"instrument_id": self.name},
            )
        ]
