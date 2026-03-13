"""Плагин расчёта теплового сопротивления для CryoDAQ.

Вычисляет тепловое сопротивление R_thermal = (T_hot - T_cold) / P
по трём каналам: два термометра и канал мощности нагревателя.
Поддерживает накопление последних известных значений, что позволяет
корректно работать при частичных пакетах показаний.
"""

from __future__ import annotations

import logging
from typing import Any

from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric
from cryodaq.drivers.base import ChannelStatus, Reading

_log = logging.getLogger(__name__)


class ThermalCalculator(AnalyticsPlugin):
    """Расчёт теплового сопротивления между двумя точками криостата.

    Использует формулу установившегося режима теплопередачи:

        R_thermal = (T_hot - T_cold) / P   [К/Вт]

    где T_hot и T_cold — температуры горячего и холодного датчиков,
    P — мощность, рассеиваемая нагревателем.

    Конфигурация (YAML):
        hot_sensor:      Имя канала горячего датчика.
        cold_sensor:     Имя канала холодного датчика.
        heater_channel:  Имя канала показаний мощности нагревателя.

    Особенности:
        - Хранит последние известные значения каждого из трёх каналов,
          поэтому работает корректно даже при неполных пакетах.
        - Учитывает только показания со статусом OK.
        - При P == 0 или недостатке данных возвращает пустой список.
    """

    plugin_id = "thermal_calculator"

    def __init__(self) -> None:
        """Инициализировать плагин с пустым состоянием."""
        super().__init__(self.plugin_id)

        # Имена каналов (заполняются при configure())
        self._hot_sensor: str = ""
        self._cold_sensor: str = ""
        self._heater_channel: str = ""

        # Последние известные значения каналов: channel -> float
        self._last: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Конфигурация
    # ------------------------------------------------------------------

    def configure(self, config: dict[str, Any]) -> None:
        """Применить конфигурацию плагина.

        Ожидаемые ключи:
            hot_sensor (str):      Канал горячего датчика.
            cold_sensor (str):     Канал холодного датчика.
            heater_channel (str):  Канал мощности нагревателя.

        Аргументы:
            config: Словарь параметров из YAML-файла.
        """
        super().configure(config)

        self._hot_sensor = str(config.get("hot_sensor", ""))
        self._cold_sensor = str(config.get("cold_sensor", ""))
        self._heater_channel = str(config.get("heater_channel", ""))

        _log.info(
            "ThermalCalculator сконфигурирован: горячий=%r, холодный=%r, нагреватель=%r",
            self._hot_sensor,
            self._cold_sensor,
            self._heater_channel,
        )

    # ------------------------------------------------------------------
    # Основная логика
    # ------------------------------------------------------------------

    async def process(self, readings: list[Reading]) -> list[DerivedMetric]:
        """Обработать пакет показаний и вычислить тепловое сопротивление.

        Сканирует readings в поисках значений трёх целевых каналов
        (берёт последнее по времени в текущем пакете).  Объединяет
        найденные значения с ранее накопленными.

        Аргументы:
            readings: Список показаний за текущий интервал опроса.

        Возвращает:
            Список из одного :class:`~cryodaq.analytics.base_plugin.DerivedMetric`
            с метрикой ``"R_thermal"`` (K/W), либо пустой список,
            если данных недостаточно или P == 0.
        """
        if not self._hot_sensor or not self._cold_sensor or not self._heater_channel:
            _log.warning(
                "ThermalCalculator: конфигурация не задана, вычисление пропущено"
            )
            return []

        # Обновить последние известные значения из текущего пакета.
        # Показания сортируются по времени, чтобы последнее значение
        # гарантированно перезаписало более раннее.
        target_channels = {self._hot_sensor, self._cold_sensor, self._heater_channel}
        relevant = [
            r
            for r in readings
            if r.channel in target_channels and r.status is ChannelStatus.OK
        ]
        relevant.sort(key=lambda r: r.timestamp)

        for reading in relevant:
            self._last[reading.channel] = reading.value

        # Проверить, что все три канала известны
        missing = target_channels - self._last.keys()
        if missing:
            _log.debug(
                "ThermalCalculator: недостаточно данных, отсутствуют каналы: %s",
                ", ".join(sorted(missing)),
            )
            return []

        T_hot = self._last[self._hot_sensor]
        T_cold = self._last[self._cold_sensor]
        P = self._last[self._heater_channel]

        if P == 0.0:
            _log.debug(
                "ThermalCalculator: мощность нагревателя равна нулю, "
                "тепловое сопротивление не определено"
            )
            return []

        if P < 0.0:
            _log.warning(
                "ThermalCalculator: мощность нагревателя отрицательна (P=%.6g Вт), "
                "вычисление пропущено",
                P,
            )
            return []

        R_thermal = (T_hot - T_cold) / P

        _log.debug(
            "ThermalCalculator: T_hot=%.4f K, T_cold=%.4f K, P=%.6g Вт "
            "→ R_thermal=%.6g К/Вт",
            T_hot,
            T_cold,
            P,
            R_thermal,
        )

        return [
            DerivedMetric.now(
                self.plugin_id,
                "R_thermal",
                R_thermal,
                "K/W",
                metadata={
                    "hot_T": T_hot,
                    "cold_T": T_cold,
                    "P": P,
                    "hot_sensor": self._hot_sensor,
                    "cold_sensor": self._cold_sensor,
                    "heater_channel": self._heater_channel,
                },
            )
        ]
