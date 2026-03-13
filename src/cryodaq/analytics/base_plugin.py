"""Базовые классы аналитического слоя CryoDAQ.

Определяет DerivedMetric — результат вычисления плагина — и
абстрактный класс AnalyticsPlugin, от которого наследуются все
аналитические плагины (расчёт тепловых сопротивлений, прогноз
времени охлаждения и т.д.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from cryodaq.drivers.base import Reading


@dataclass(frozen=True, slots=True)
class DerivedMetric:
    """Производная метрика, вычисленная аналитическим плагином.

    Неизменяемый объект — безопасен для передачи между сопрограммами.

    Атрибуты:
        timestamp:  Метка времени UTC момента вычисления.
        plugin_id:  Уникальный идентификатор плагина-источника.
        metric:     Имя метрики (например, ``"R_thermal"``, ``"cooldown_eta_s"``).
        value:      Числовое значение метрики.
        unit:       Единица измерения (например, ``"K/W"``, ``"s"``).
        metadata:   Произвольные аннотации (параметры алгоритма, версия модели и т.п.).
    """

    timestamp: datetime
    plugin_id: str
    metric: str
    value: float
    unit: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def now(
        plugin_id: str,
        metric: str,
        value: float,
        unit: str,
        **kwargs: Any,
    ) -> DerivedMetric:
        """Создать DerivedMetric с текущей меткой времени UTC.

        Аргументы:
            plugin_id:  Идентификатор плагина.
            metric:     Имя метрики.
            value:      Значение метрики.
            unit:       Единица измерения.
            **kwargs:   Дополнительные поля (например, ``metadata={}``).

        Возвращает:
            Экземпляр :class:`DerivedMetric` с ``timestamp = datetime.now(UTC)``.
        """
        return DerivedMetric(
            timestamp=datetime.now(timezone.utc),
            plugin_id=plugin_id,
            metric=metric,
            value=value,
            unit=unit,
            **kwargs,
        )


class AnalyticsPlugin(ABC):
    """Абстрактный аналитический плагин.

    Каждый конкретный плагин наследует этот класс и реализует метод
    :meth:`process`.  Жизненный цикл управляется :class:`PluginPipeline`:
    загрузка из файловой системы, опциональная конфигурация через YAML,
    горячая перезагрузка при изменении файла.

    Пример минимального плагина::

        class MyPlugin(AnalyticsPlugin):
            async def process(self, readings):
                ...
                return [DerivedMetric.now(self.plugin_id, "my_metric", 42.0, "arb")]
    """

    def __init__(self, plugin_id: str) -> None:
        """Инициализировать плагин.

        Аргументы:
            plugin_id:  Уникальный идентификатор плагина в рамках пайплайна.
                        Обычно совпадает с именем файла без расширения.
        """
        self._plugin_id = plugin_id
        self._config: dict[str, Any] = {}

    @property
    def plugin_id(self) -> str:
        """Уникальный идентификатор плагина (только для чтения)."""
        return self._plugin_id

    @abstractmethod
    async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
        """Обработать пакет показаний и вернуть производные метрики.

        Вызывается :class:`PluginPipeline` на каждом интервале сбора данных.
        Метод не должен генерировать исключения: внутренние ошибки следует
        логировать и возвращать пустой список.

        Аргументы:
            readings:  Список :class:`~cryodaq.drivers.base.Reading`,
                       накопленных за последний интервал.

        Возвращает:
            Список :class:`DerivedMetric`.  Допустимо вернуть пустой список,
            если данных недостаточно для вычисления.
        """

    def configure(self, config: dict[str, Any]) -> None:
        """Применить конфигурацию из YAML-файла.

        Переопределите этот метод для валидации и разбора специфичных
        параметров плагина.  Реализация по умолчанию просто сохраняет
        словарь в ``self._config``.

        Аргументы:
            config:  Десериализованный словарь из YAML (``yaml.safe_load``).
        """
        self._config = config
