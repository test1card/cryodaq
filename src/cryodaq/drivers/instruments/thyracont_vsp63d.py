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
    """Вакуумметр Thyracont VSP63D / VSM77DL.

    Поддерживает два протокола:

    **VSP63D (по умолчанию):**
      RS-232/USB-Serial, 9600 бод.
      Команда: ``"MV00\\r"`` → ответ: ``"status,value\\r"``

    **Thyracont Protocol V1 (VSM77DL и аналоги):**
      RS-232/USB-Serial, 115200 бод.
      Команда: ``"<addr>M^\\r"`` → ответ: ``"<addr>M<5digits><checksum>\\r"``
      Кодировка значения: ``pressure = 10^((value - 80000) / 4000)`` mbar.

    Протокол определяется автоматически по формату ответа, а также может
    быть форсирован через параметр ``protocol``.

    Parameters
    ----------
    name:
        Уникальное имя экземпляра прибора (используется в метаданных Reading).
    resource_str:
        Имя последовательного порта, например ``"COM3"`` или ``"/dev/ttyUSB0"``.
    baudrate:
        Скорость обмена в бодах (по умолчанию 9600).
    address:
        Адрес прибора для Protocol V1 (по умолчанию ``"001"``).
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
        address: str = "001",
        mock: bool = False,
    ) -> None:
        super().__init__(name, mock=mock)
        self._resource_str = resource_str
        self._baudrate = baudrate
        self._address = address
        self._transport = SerialTransport(mock=mock)
        self._instrument_id: str = ""
        self._protocol_v1: bool = False

    # ------------------------------------------------------------------
    # InstrumentDriver — обязательный интерфейс
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Открыть последовательный порт и верифицировать связь с прибором.

        Thyracont VSP63D не поддерживает SCPI (``*IDN?``).  Вместо этого
        отправляем measurement-запрос Protocol V1 (``"<addr>M^\\r"``) и
        проверяем, что ответ начинается с ``"<addr>M"``.

        Устанавливает флаг ``_connected = True`` при успехе.
        """
        log.info("%s: подключение к %s @ %d бод", self.name, self._resource_str, self._baudrate)
        await self._transport.open(self._resource_str, baudrate=self._baudrate)

        cmd = f"{self._address}M^"
        expected_prefix = f"{self._address}M"
        last_exc: Exception | None = None

        for attempt in range(3):
            if attempt > 0:
                await self._transport.flush_input()
            try:
                resp = await self._transport.query(cmd)
                resp_stripped = resp.strip()
                if resp_stripped.startswith(expected_prefix):
                    self._protocol_v1 = True
                    self._instrument_id = f"Thyracont-V1@{self._address}"
                    log.info(
                        "%s: Protocol V1 detected (address=%s, probe=%r, attempt=%d)",
                        self.name, self._address, resp_stripped, attempt + 1,
                    )
                    self._connected = True
                    return
            except Exception as exc:
                last_exc = exc
                log.debug(
                    "%s: probe attempt %d failed — %s", self.name, attempt + 1, exc,
                )

        await self._transport.close()
        raise RuntimeError(
            f"{self.name}: прибор не ответил на Protocol V1 probe ({cmd!r})"
        ) from last_exc

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

        if self._protocol_v1:
            cmd = f"{self._address}M^"
            raw_response = await self._transport.query(cmd)
            log.debug("%s: %s → %s", self.name, cmd, raw_response.strip())
            return [self._parse_v1_response(raw_response)]

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
                instrument_id=self.name,
                status=ChannelStatus.SENSOR_ERROR,
                raw=None,
                metadata={"raw_response": response_stripped},
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
            instrument_id=self.name,
            status=ch_status,
            raw=value,
            metadata={"status_code": status_code},
        )

    # ------------------------------------------------------------------
    # Разбор ответа Protocol V1 (VSM77DL)
    # ------------------------------------------------------------------

    def _parse_v1_response(self, response: str) -> Reading:
        """Разобрать ответ Thyracont Protocol V1.

        Формат: ``"<addr>M<5digits><checksum>\\r"``, например ``"001M100023D\\r"``.

        Кодировка 5-значного значения::

            pressure_mbar = 10 ^ ((value - 80000) / 4000)

        Пример: ``92002`` → 10^((92002 − 80000) / 4000) = 10^3.0005 ≈ 1001 mbar

        Parameters
        ----------
        response:
            Сырая строка ответа от прибора.

        Returns
        -------
        Reading
            Показание давления.
        """
        channel = f"{self.name}/pressure"
        response_stripped = response.strip()

        try:
            # Ожидаемый формат: <addr><cmd><5digits><checksum>
            # Например: "001M100023D" → addr="001", cmd="M", value="10002", checksum="3D"
            if not response_stripped.startswith(self._address):
                raise ValueError(f"Неверный адрес в ответе: '{response_stripped}'")

            # Пропустить адрес (3 символа) + команду (1 символ)
            payload = response_stripped[len(self._address) + 1:]

            if len(payload) < 5:
                raise ValueError(f"Слишком короткий payload: '{payload}'")

            # Первые 5 символов = кодированное значение давления
            value_str = payload[:5]
            value_int = int(value_str)
            pressure_mbar = 10.0 ** ((value_int - 80000) / 4000.0)

        except (ValueError, IndexError) as exc:
            log.error(
                "%s: не удалось разобрать V1 ответ '%s' — %s",
                self.name, response_stripped, exc,
            )
            return Reading.now(
                channel=channel,
                value=float("nan"),
                unit="mbar",
                instrument_id=self.name,
                status=ChannelStatus.SENSOR_ERROR,
                raw=None,
                metadata={"raw_response": response_stripped},
            )

        return Reading.now(
            channel=channel,
            value=pressure_mbar,
            unit="mbar",
            instrument_id=self.name,
            status=ChannelStatus.OK,
            raw=pressure_mbar,
            metadata={"raw_response": response_stripped, "protocol": "v1"},
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
                instrument_id=self.name,
                status=ChannelStatus.OK,
                raw=value,
            )
        ]
