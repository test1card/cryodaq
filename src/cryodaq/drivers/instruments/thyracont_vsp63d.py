"""Драйвер вакуумметра Thyracont VSP63D (RS-232/USB-Serial)."""

from __future__ import annotations

import logging
import math
import random
import re
import time

from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.transport.serial import SerialTransport

log = logging.getLogger(__name__)

# Известные пары baudrate ↔ fallback для автоопределения протокола
_FALLBACK_BAUDRATES: dict[int, int] = {9600: 115200, 115200: 9600}

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
_MV00_STATUS_RE = re.compile(r"[0-9]\Z", re.ASCII)
_V1_VALUE_RE = re.compile(r"[0-9]{6}\Z", re.ASCII)
_V1_ADDRESS_RE = re.compile(r"[0-9]{3}\Z", re.ASCII)


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
        # Phase 2c F.2: default flipped from False to True. Thyracont
        # protocol carries an explicit CS field; on noisy RS-232 lines a
        # silent corruption could otherwise produce an incorrect pressure
        # reading. Operators with known-bad firmware can opt back out via
        # `validate_checksum: false` in instruments.local.yaml.
        validate_checksum: bool = True,
    ) -> None:
        super().__init__(name, mock=mock)
        if type(baudrate) is not int or baudrate <= 0:
            raise ValueError(f"baudrate must be a positive integer, got {baudrate!r}")
        if not isinstance(address, str) or _V1_ADDRESS_RE.fullmatch(address) is None:
            raise ValueError(f"address must contain exactly three ASCII digits, got {address!r}")
        if type(validate_checksum) is not bool:
            raise ValueError(f"validate_checksum must be a boolean, got {validate_checksum!r}")
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

        Пробует Protocol V1 (``"<addr>M^"``), затем MV00. Если ни один
        протокол не отвечает на сконфигурированном baudrate, пробует
        fallback baudrate (9600 ↔ 115200). Устанавливает флаг
        ``_connected = True`` при успехе.
        """
        baudrates_to_try = [self._baudrate]
        fallback = _FALLBACK_BAUDRATES.get(self._baudrate)
        if fallback is not None:
            baudrates_to_try.append(fallback)

        last_error = ""
        for baud in baudrates_to_try:
            log.info("%s: подключение к %s @ %d бод", self.name, self._resource_str, baud)
            try:
                await self._transport.open(self._resource_str, baudrate=baud)
            except Exception as exc:
                log.warning("%s: failed to open port @ %d baud: %s", self.name, baud, exc)
                last_error = str(exc)
                continue

            try:
                # Try Protocol V1
                if await self._try_v1_probe():
                    self._protocol_v1 = True
                    self._instrument_id = f"Thyracont-V1@{self._address}"
                    self._connected = True
                    if baud != self._baudrate:
                        log.info(
                            "%s: connected via Protocol V1 @ %d baud (fallback from %d)",
                            self.name,
                            baud,
                            self._baudrate,
                        )
                    else:
                        log.info("%s: connected via Protocol V1", self.name)
                    return

                # Try MV00
                if await self._try_mv00_probe():
                    self._protocol_v1 = False
                    self._instrument_id = f"Thyracont-MV00@{self._resource_str}"
                    self._connected = True
                    if baud != self._baudrate:
                        log.info(
                            "%s: connected via MV00 @ %d baud (fallback from %d)",
                            self.name,
                            baud,
                            self._baudrate,
                        )
                    else:
                        log.info("%s: connected via MV00", self.name)
                    return
            except BaseException:
                try:
                    await self._transport.close()
                except BaseException as close_exc:
                    log.critical("%s: probe-abort transport cleanup failed: %s", self.name, close_exc)
                finally:
                    self._connected = False
                raise

            await self._transport.close()
            last_error = f"neither V1 nor MV00 responded @ {baud} baud"

        raise RuntimeError(f"{self.name}: {last_error}")

    async def _try_v1_probe(self) -> bool:
        """Attempt Protocol V1 probe. Returns True on success."""
        cmd = f"{self._address}M^"
        expected_prefix = f"{self._address}M"
        for attempt in range(3):
            if attempt > 0:
                await self._transport.flush_input()
            try:
                resp = await self._transport.query(cmd)
                resp_stripped = resp.strip()
                if resp_stripped.startswith(expected_prefix):
                    payload = resp_stripped[len(expected_prefix) :]
                    if len(payload) != 7 or _V1_VALUE_RE.fullmatch(payload[:6]) is None:
                        continue
                    if int(payload[:4]) <= 0:
                        continue
                    if self._validate_checksum and not self._verify_v1_checksum(resp_stripped):
                        log.warning(
                            "%s: V1 probe checksum mismatch in '%s'",
                            self.name,
                            resp_stripped,
                        )
                        continue
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
            parts = resp_stripped.split(",")
            if len(parts) == 2:
                status_token = parts[0].strip()
                if _MV00_STATUS_RE.fullmatch(status_token) is None:
                    return False
                status_code = int(status_token)
                value = float(parts[1].strip())
                if status_code not in _STATUS_MAP or not math.isfinite(value):
                    return False
                if status_code == _STATUS_OK and value <= 0:
                    return False
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
        try:
            await self._transport.close()
        finally:
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

            status_token = parts[0].strip()
            if _MV00_STATUS_RE.fullmatch(status_token) is None:
                raise ValueError(f"invalid MV00 status token: {status_token!r}")
            status_code = int(status_token)
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
        reported_value = value
        finite_value = math.isfinite(reported_value)
        if not finite_value:
            ch_status = ChannelStatus.SENSOR_ERROR
        if ch_status is ChannelStatus.OK and reported_value <= 0:
            ch_status = ChannelStatus.SENSOR_ERROR
        if ch_status is ChannelStatus.OK:
            value = reported_value
        elif ch_status is ChannelStatus.OVERRANGE:
            value = float("inf")
        elif ch_status is ChannelStatus.UNDERRANGE:
            value = float("-inf")
        else:
            value = float("nan")
        metadata: dict[str, object] = {"status_code": status_code}
        if finite_value:
            metadata["reported_value"] = reported_value
        else:
            metadata["reported_value"] = None
            metadata["reported_value_raw"] = repr(reported_value)

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
            raw=reported_value if finite_value else None,
            metadata=metadata,
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
                    self.name,
                    response_stripped,
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
            expected_prefix = f"{self._address}M"
            if not response_stripped.startswith(expected_prefix):
                raise ValueError(f"Неверный адрес в ответе: '{response_stripped}'")

            # Skip the exact address+command prefix. The remaining frame is
            # six ASCII digits plus one checksum byte.
            payload = response_stripped[len(expected_prefix) :]

            if len(payload) != 7:
                raise ValueError(f"Неверная длина payload: '{payload}'")

            # Первые 6 символов: 4 мантисса + 2 экспонента
            value_str = payload[:6]
            if _V1_VALUE_RE.fullmatch(value_str) is None:
                raise ValueError(f"V1 pressure payload must contain six ASCII digits: {value_str!r}")
            mantissa = int(value_str[:4])
            exponent = int(value_str[4:6])
            pressure_mbar = (mantissa / 1000.0) * (10.0 ** (exponent - 20))
            if not math.isfinite(pressure_mbar) or pressure_mbar <= 0:
                raise ValueError(f"V1 pressure must be finite and positive: {pressure_mbar!r}")

        except (ValueError, IndexError) as exc:
            log.error(
                "%s: не удалось разобрать V1 ответ '%s' — %s",
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
