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
      Команда: ``"<addr>M^\\r"`` → ответ: ``"<addr>M<6digits><checksum>\\r"``
      Кодировка 6-значного значения (ABCDEF): ABCD = мантисса, EF = экспонента.
      ``pressure = (ABCD / 1000) * 10^(EF - 20)`` mbar.

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
        validate_checksum: bool = False,
    ) -> None:
        super().__init__(name, mock=mock)
        self._resource_str = resource_str
        self._baudrate = baudrate
        self._address = address
        self._transport = SerialTransport(mock=mock)
        self._instrument_id: str = ""
        self._protocol_v1: bool = False
        self._validate_checksum: bool = validate_checksum

    # ------------------------------------------------------------------
    # InstrumentDriver — обязательный интерфейс
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Открыть последовательный порт и верифицировать связь с прибором.

        Пробует Protocol V1 (``"<addr>M^"``), затем MV00. Устанавливает
        флаг ``_connected = True`` при успехе.
        """
        log.info("%s: подключение к %s @ %d бод", self.name, self._resource_str, self._baudrate)
        await self._transport.open(self._resource_str, baudrate=self._baudrate)

        # Try Protocol V1
        if await self._try_v1_probe():
            self._protocol_v1 = True
            self._instrument_id = f"Thyracont-V1@{self._address}"
            self._connected = True
            log.info("%s: connected via Protocol V1", self.name)
            return

        # Fallback: try MV00
        if await self._try_mv00_probe():
            self._protocol_v1 = False
            self._instrument_id = f"Thyracont-MV00@{self._resource_str}"
            self._connected = True
            log.info("%s: connected via MV00", self.name)
            return

        await self._transport.close()
        raise RuntimeError(f"{self.name}: neither V1 nor MV00 responded")

    async def _try_v1_probe(self) -> bool:
        """Attempt Protocol V1 probe. Returns True on success."""
        cmd = f"{self._address}M^"
        expected_prefix = f"{self._address}M"
        for attempt in range(3):
            if attempt > 0:
                await self._transport.flush_input()
            try:
                resp = await self._transport.query(cmd)
                if resp.strip().startswith(expected_prefix):
                    log.debug("%s: V1 probe OK (attempt %d)", self.name, attempt + 1)
                    return True
            except Exception as exc:
                log.debug("%s: V1 probe attempt %d failed: %s", self.name, attempt + 1, exc)
        return False

    async def _try_mv00_probe(self) -> bool:
        """Attempt MV00 protocol probe. Returns True on success."""
        await self._transport.flush_input()
        try:
            resp = await self._transport.query("MV00")
            resp_stripped = resp.strip()
            # MV00 returns "<status>,<value>" e.g. "0,1.234E-06"
            if "," in resp_stripped:
                log.debug("%s: MV00 probe OK: %s", self.name, resp_stripped)
                return True
        except Exception as exc:
            log.debug("%s: MV00 probe failed: %s", self.name, exc)
        return False

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

    @staticmethod
    def _verify_v1_checksum(response: str) -> bool:
        """Verify Thyracont Protocol V1 checksum.

        Format: <payload><checksum_char>
        Checksum = XOR of all bytes in payload, masked to 0x7F.
        """
        if len(response) < 2:
            return False
        payload = response[:-1]
        expected_char = response[-1]
        computed = 0
        for byte in payload.encode("ascii", errors="replace"):
            computed ^= byte
        computed &= 0x7F
        return chr(computed) == expected_char

    def _parse_v1_response(self, response: str) -> Reading:
        """Разобрать ответ Thyracont Protocol V1.

        Формат: ``"<addr>M<6digits><checksum>\\r"``, например ``"001M260017N\\r"``.

        Кодировка 6-значного значения ABCDEF::

            ABCD = мантисса (4 цифры)
            EF   = экспонента (2 цифры)
            pressure_mbar = (ABCD / 1000) × 10^(EF − 20)

        Примеры:
        - ``260017`` → (2600/1000) × 10^(17−20) = 2.6e-3 mbar
        - ``100023`` → (1000/1000) × 10^(23−20) = 1000 mbar

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

        # Validate checksum if enabled and response has expected structure
        if self._validate_checksum and len(response_stripped) >= 2:
            if not self._verify_v1_checksum(response_stripped):
                log.warning(
                    "%s: V1 checksum mismatch in '%s' — possible RS-232 corruption",
                    self.name, response_stripped,
                )
                return Reading.now(
                    channel=channel,
                    value=float("nan"),
                    unit="mbar",
                    instrument_id=self.name,
                    status=ChannelStatus.SENSOR_ERROR,
                    raw=None,
                    metadata={"raw_response": response_stripped, "error": "checksum_mismatch"},
                )

        try:
            # Ожидаемый формат: <addr><cmd><6digits><checksum>
            # Например: "001M260017N" → addr="001", cmd="M", value="260017", checksum="N"
            if not response_stripped.startswith(self._address):
                raise ValueError(f"Неверный адрес в ответе: '{response_stripped}'")

            # Пропустить адрес (3 символа) + команду (1 символ)
            payload = response_stripped[len(self._address) + 1:]

            if len(payload) < 6:
                raise ValueError(f"Слишком короткий payload: '{payload}'")

            # Первые 6 символов: 4 мантисса + 2 экспонента
            value_str = payload[:6]
            mantissa = int(value_str[:4])
            exponent = int(value_str[4:6])
            pressure_mbar = (mantissa / 1000.0) * (10.0 ** (exponent - 20))

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
