"""Базовые классы для драйверов приборов."""

from __future__ import annotations

import asyncio
import math
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class ChannelStatus(Enum):
    """Статус канала измерения."""

    OK = "ok"
    OVERRANGE = "overrange"
    UNDERRANGE = "underrange"
    SENSOR_ERROR = "sensor_error"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class Reading:
    """Единичное измерение с прибора.

    Неизменяемый, легковесный, безопасен для передачи между потоками/процессами.
    """

    timestamp: datetime
    instrument_id: str
    channel: str
    value: float
    unit: str
    status: ChannelStatus = ChannelStatus.OK
    raw: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_usable(self) -> bool:
        """Единственный предикат годности показания (NaN-доктрина).

        Годно ⇔ статус OK-класса И значение конечно. Иначе — NON-FINITE-ERROR
        (не годно): не конечное значение (NaN/±inf) ИЛИ статус ошибки.

        OK-класс = ровно {OK}. Драйверы всегда сопровождают любой не-OK
        статус не конечным sentinel-значением (LakeShore OVL → value=inf +
        OVERRANGE; SENSOR_ERROR / TIMEOUT → NaN), поэтому ограничение годного
        множества до OK совпадает с прежней float-проверкой, но делает
        дискриминатором именно статус. Downstream-код не должен различать
        показания по float-значению — только через этот предикат.

        Не числовое значение (junk из defensive GUI-путей) — не годно (False),
        а не исключение: годность падает закрыто на safety-пути.
        """
        try:
            return self.status is ChannelStatus.OK and math.isfinite(self.value)
        except TypeError:
            return False

    @staticmethod
    def now(channel: str, value: float, unit: str, *, instrument_id: str = "", **kwargs: Any) -> Reading:
        """Создать Reading с текущим временем UTC."""
        return Reading(
            timestamp=datetime.now(UTC),
            instrument_id=instrument_id,
            channel=channel,
            value=value,
            unit=unit,
            **kwargs,
        )


class InstrumentDriver(ABC):
    """Абстрактный драйвер прибора.

    Контракт:
    - connect/disconnect — управление ресурсом (VISA session, serial port)
    - read_channels — один цикл опроса, возвращает список Reading
    - Все I/O — async, никогда не блокировать event loop
    - mock_mode — работа без реального прибора (для тестов и разработки GUI)
    """

    def __init__(self, name: str, *, mock: bool = False) -> None:
        self.name = name
        self.mock = mock
        self._connected = False
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._connected

    @abstractmethod
    async def connect(self) -> None:
        """Открыть соединение с прибором."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Закрыть соединение. Должен быть идемпотентным."""

    @abstractmethod
    async def read_channels(self) -> list[Reading]:
        """Опросить все каналы. Вернуть список показаний."""

    async def safe_read(self) -> list[Reading]:
        """Потокобезопасный опрос с блокировкой (один запрос за раз).

        F81 finding: the acquisition epoch is stamped at the base polling
        boundary, not per driver. Every driver that does not stamp its own
        ``acquisition_started_monotonic``/``acquisition_started_at`` on each
        Reading still gets one here, so the conductivity panel's per-sample
        freshness proof works for a temperature channel from any
        ``InstrumentDriver`` — the panel offers a generic Т-prefixed channel
        contract and must not reject every sample of a driver that never stamps
        its own epoch. Drivers that stamp their own values are left untouched.
        """
        async with self._lock:
            epoch_wall = time.time()
            epoch_monotonic = time.monotonic()
            readings = await self.read_channels()
        if isinstance(readings, list):
            for reading in readings:
                if type(reading) is not Reading:
                    continue
                metadata = reading.metadata if isinstance(reading.metadata, dict) else None
                if metadata is not None and "acquisition_started_monotonic" not in metadata:
                    metadata["acquisition_started_monotonic"] = epoch_monotonic
                    metadata["acquisition_started_at"] = epoch_wall
        return readings

    def failure_readings(self) -> list[Reading]:
        """Return current non-usable readings when a whole poll fails.

        This hook performs no I/O. Drivers with a fixed channel inventory
        override it so Scheduler can publish a failed poll normally.
        """
        return []

    async def __aenter__(self) -> InstrumentDriver:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.disconnect()
