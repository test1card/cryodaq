"""Базовые классы для драйверов приборов."""

from __future__ import annotations

import asyncio
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
        """Потокобезопасный опрос с блокировкой (один запрос за раз)."""
        async with self._lock:
            return await self.read_channels()

    async def __aenter__(self) -> InstrumentDriver:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.disconnect()
