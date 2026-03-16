"""Драйвер термометра LakeShore 218S (8-канальный, GPIB)."""
from __future__ import annotations

import logging
import random
from typing import Any

from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.transport.gpib import GPIBTransport

log = logging.getLogger(__name__)

# Реалистичные базовые температуры для mock-режима (Кельвин)
_MOCK_BASE_TEMPS: tuple[float, ...] = (4.2, 4.8, 77.0, 77.5, 4.5, 4.1, 3.9, 300.0)


def _mock_sensor_unit(temp_k: float) -> float:
    # Monotonic synthetic sensor-units curve for calibration workflows in mock mode.
    return round((1600.0 / (temp_k + 15.0)) + 0.08, 6)


class LakeShore218S(InstrumentDriver):
    """Драйвер LakeShore Model 218S — восьмиканального измерителя температуры.

    Связь осуществляется по GPIB. Все 8 каналов считываются одной командой
    ``KRDG? 0``, что минимизирует нагрузку на шину.

    Parameters
    ----------
    name:
        Уникальное имя экземпляра прибора (используется в метаданных Reading).
    resource_str:
        VISA-строка ресурса, например ``"GPIB0::12::INSTR"``.
    channel_labels:
        Словарь {номер_канала (1–8): метка}, например
        ``{1: "Т1 Криостат верх", 2: "Т2 Криостат низ"}``.
        Каналы без метки получают имя ``CH<n>``.
    mock:
        Если ``True`` — работает без реального прибора, возвращает
        имитированные температуры в диапазоне 4–300 К.
    """

    def __init__(
        self,
        name: str,
        resource_str: str,
        *,
        channel_labels: dict[int, str] | None = None,
        mock: bool = False,
    ) -> None:
        super().__init__(name, mock=mock)
        self._resource_str = resource_str
        self._channel_labels: dict[int, str] = channel_labels or {}
        self._transport = GPIBTransport(mock=mock)
        self._instrument_id: str = ""

    # ------------------------------------------------------------------
    # InstrumentDriver — обязательный интерфейс
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Установить соединение с прибором и верифицировать идентификацию.

        Отправляет ``*IDN?`` и сохраняет ответ в ``_instrument_id``.
        Устанавливает флаг ``_connected = True`` при успехе.
        """
        log.info("%s: подключение к %s", self.name, self._resource_str)
        await self._transport.open(self._resource_str)

        try:
            idn = await self._transport.query("*IDN?")
            self._instrument_id = idn
            log.info("%s: IDN = %s", self.name, idn)
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
        """Считать показания всех 8 каналов одной командой ``KRDG? 0``.

        Returns
        -------
        list[Reading]
            Список из 8 объектов :class:`~cryodaq.drivers.base.Reading`
            в порядке каналов 1–8. Единица измерения — Кельвин (``"K"``).

        Raises
        ------
        RuntimeError
            Если прибор не подключён.
        """
        if not self._connected:
            raise RuntimeError(f"{self.name}: прибор не подключён")

        if self.mock:
            return self._mock_readings()

        raw_response = await self._transport.query("KRDG? 0")
        log.debug("%s: KRDG? 0 → %s", self.name, raw_response)
        return self._parse_response(raw_response, unit="K", reading_kind="temperature")

    async def read_srdg_channels(self) -> list[Reading]:
        """Read all 8 channels in sensor units via ``SRDG? 0``."""
        if not self._connected:
            raise RuntimeError(f"{self.name}: прибор не подключён")

        if self.mock:
            return self._mock_sensor_readings()

        raw_response = await self._transport.query("SRDG? 0")
        log.debug("%s: SRDG? 0 → %s", self.name, raw_response)
        return self._parse_response(raw_response, unit="sensor_unit", reading_kind="raw_sensor")

    async def read_calibration_pair(
        self,
        *,
        reference_channel: int | str,
        sensor_channel: int | str,
    ) -> dict[str, Any]:
        temperatures = await self.read_channels()
        raw_readings = await self.read_srdg_channels()
        reference_reading = self._resolve_channel_reading(temperatures, reference_channel)
        sensor_reading = self._resolve_channel_reading(raw_readings, sensor_channel)
        return {
            "reference": reference_reading,
            "sensor": sensor_reading,
        }

    # ------------------------------------------------------------------
    # Разбор ответа прибора
    # ------------------------------------------------------------------

    def _parse_response(self, response: str, *, unit: str, reading_kind: str) -> list[Reading]:
        """Разобрать строку ответа ``KRDG? 0`` в список Reading.

        Формат ответа: восемь значений через запятую, например::

            +004.235E+0,+004.891E+0,...

        Специальные значения ``+OVL`` и ``OVL`` интерпретируются как
        :attr:`~cryodaq.drivers.base.ChannelStatus.OVERRANGE`.
        """
        tokens = [t.strip() for t in response.split(",")]
        readings: list[Reading] = []

        for i, token in enumerate(tokens[:8]):
            channel_num = i + 1
            channel_name = self._channel_labels.get(channel_num, f"CH{channel_num}")
            metadata: dict[str, Any] = {
                "raw_channel": channel_num,
                "reading_kind": reading_kind,
            }

            token_upper = token.upper().lstrip("+")
            if token_upper in ("OVL", "+OVL"):
                readings.append(
                    Reading.now(
                        channel=channel_name,
                        value=float("inf"),
                        unit=unit,
                        instrument_id=self.name,
                        status=ChannelStatus.OVERRANGE,
                        raw=None,
                        metadata=metadata,
                    )
                )
                log.warning(
                    "%s: канал %s — переполнение диапазона (OVL)",
                    self.name,
                    channel_name,
                )
                continue

            try:
                value = float(token)
            except ValueError:
                log.error(
                    "%s: канал %s — не удалось преобразовать значение '%s'",
                    self.name,
                    channel_name,
                    token,
                )
                readings.append(
                    Reading.now(
                        channel=channel_name,
                        value=float("nan"),
                        unit=unit,
                        instrument_id=self.name,
                        status=ChannelStatus.SENSOR_ERROR,
                        raw=None,
                        metadata=metadata,
                    )
                )
                continue

            readings.append(
                    Reading.now(
                        channel=channel_name,
                        value=value,
                        unit=unit,
                        instrument_id=self.name,
                        status=ChannelStatus.OK,
                        raw=value,
                    metadata=metadata,
                )
            )

        return readings

    # ------------------------------------------------------------------
    # Mock-режим
    # ------------------------------------------------------------------

    def _mock_readings(self) -> list[Reading]:
        """Сгенерировать реалистичные имитированные показания (4–300 К)."""
        readings: list[Reading] = []
        for i, base_temp in enumerate(_MOCK_BASE_TEMPS):
            channel_num = i + 1
            channel_name = self._channel_labels.get(channel_num, f"CH{channel_num}")
            # Небольшой случайный шум ±0.5% от базовой температуры
            noise = base_temp * random.uniform(-0.005, 0.005)
            value = round(base_temp + noise, 4)
            readings.append(
                Reading.now(
                        channel=channel_name,
                        value=value,
                        unit="K",
                    instrument_id=self.name,
                    status=ChannelStatus.OK,
                    raw=value,
                        metadata={
                            "raw_channel": channel_num,
                            "reading_kind": "temperature",
                        },
                    )
            )
        return readings

    def _mock_sensor_readings(self) -> list[Reading]:
        readings: list[Reading] = []
        for i, base_temp in enumerate(_MOCK_BASE_TEMPS):
            channel_num = i + 1
            channel_name = self._channel_labels.get(channel_num, f"CH{channel_num}")
            raw_base = _mock_sensor_unit(base_temp)
            noise = raw_base * random.uniform(-0.002, 0.002)
            value = round(raw_base + noise, 6)
            readings.append(
                Reading.now(
                    channel=channel_name,
                    value=value,
                    unit="sensor_unit",
                    instrument_id=self.name,
                    status=ChannelStatus.OK,
                    raw=value,
                    metadata={
                        "raw_channel": channel_num,
                        "reading_kind": "raw_sensor",
                    },
                )
            )
        return readings

    def _resolve_channel_reading(
        self,
        readings: list[Reading],
        channel_spec: int | str,
    ) -> Reading:
        if isinstance(channel_spec, int):
            channel_num = channel_spec
            channel_name = self._channel_labels.get(channel_num, f"CH{channel_num}")
            for reading in readings:
                if reading.metadata.get("raw_channel") == channel_num:
                    return reading
            raise KeyError(f"LakeShore channel {channel_num} not found.")

        channel_name = str(channel_spec).strip()
        if not channel_name:
            raise ValueError("LakeShore channel must not be empty.")

        if channel_name.upper().startswith("CH") and channel_name[2:].isdigit():
            channel_num = int(channel_name[2:])
            for reading in readings:
                if reading.metadata.get("raw_channel") == channel_num:
                    return reading

        for reading in readings:
            if reading.channel == channel_name:
                return reading

        raise KeyError(f"LakeShore channel '{channel_name}' not found.")
