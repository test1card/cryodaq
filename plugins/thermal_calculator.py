"""Плагин расчёта теплового сопротивления для CryoDAQ.

Вычисляет тепловое сопротивление R_thermal = (T_hot - T_cold) / P
по трём каналам: два термометра и канал мощности нагревателя.
Поддерживает накопление последних известных значений, что позволяет
корректно работать при частичных пакетах показаний.
"""

from __future__ import annotations

import logging
import math
import statistics
import time
from collections import deque
from typing import Any

from cryodaq.analytics.base_plugin import (
    BROKER_INGRESS_MONOTONIC_METADATA_KEY,
    AnalyticsPlugin,
    DerivedMetric,
)
from cryodaq.drivers.base import ChannelStatus, Reading

_log = logging.getLogger(__name__)

_BOOTSTRAP_FRESHNESS_HORIZON_S = 30.0


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
        self._last_required_input_arrival_monotonic: dict[str, float] = {}
        self._last_required_input_ingress_monotonic: dict[str, float | None] = {}
        self._required_input_arrival_intervals: dict[str, deque[float]] = {}
        # The first arrival interval larger than the bootstrap horizon is not
        # certified as cadence (a single outage gap must not certify
        # freshness). It is held here instead; a second arrival interval
        # consistent with it certifies a genuinely slow producer cadence that
        # the bootstrap bound alone could never establish. Mirrors the cooldown
        # service's source-cadence escape hatch (cooldown_service.py).
        self._arrival_cadence_candidate: dict[str, float | None] = {}

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

        self._last = {}
        self._last_required_input_arrival_monotonic = {}
        self._last_required_input_ingress_monotonic = {}
        self._required_input_arrival_intervals = {
            self._hot_sensor: deque(maxlen=5),
            self._cold_sensor: deque(maxlen=5),
            self._heater_channel: deque(maxlen=5),
        }
        self._arrival_cadence_candidate = {
            self._hot_sensor: None,
            self._cold_sensor: None,
            self._heater_channel: None,
        }

    # ------------------------------------------------------------------
    # Основная логика
    # ------------------------------------------------------------------

    def _freshness_horizon_s(self, channel: str) -> float | None:
        intervals = self._required_input_arrival_intervals.get(channel)
        if not intervals:
            return None
        return 3.0 * float(statistics.median(intervals))

    def _is_input_stale(self, channel: str, *, now_monotonic: float) -> bool:
        last_arrival = self._last_required_input_arrival_monotonic.get(channel)
        if last_arrival is None:
            return True

        horizon = self._freshness_horizon_s(channel)
        if horizon is None:
            if (now_monotonic - last_arrival) > _BOOTSTRAP_FRESHNESS_HORIZON_S:
                return True
            ingress = self._last_required_input_ingress_monotonic.get(channel)
            if ingress is None:
                return True
            return (now_monotonic - ingress) > _BOOTSTRAP_FRESHNESS_HORIZON_S

        if (now_monotonic - last_arrival) > horizon:
            return True

        ingress = self._last_required_input_ingress_monotonic.get(channel)
        if ingress is None:
            return True
        return (now_monotonic - ingress) > horizon

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
            _log.warning("ThermalCalculator: конфигурация не задана, вычисление пропущено")
            return []

        # Обновить последние известные значения из текущего пакета.
        # Показания сортируются по времени, чтобы последнее значение
        # гарантированно перезаписало более раннее.
        target_channels = {self._hot_sensor, self._cold_sensor, self._heater_channel}
        relevant = [r for r in readings if r.channel in target_channels and r.status is ChannelStatus.OK]
        relevant.sort(key=lambda r: r.timestamp)

        now_monotonic = time.monotonic()
        for reading in relevant:
            self._last[reading.channel] = reading.value

            intervals = self._required_input_arrival_intervals.get(reading.channel)
            previous_arrival = self._last_required_input_arrival_monotonic.get(reading.channel)
            if intervals is not None and previous_arrival is not None:
                arrival_interval = now_monotonic - previous_arrival
                if arrival_interval > 0.0:
                    established_horizon = self._freshness_horizon_s(reading.channel)
                    if established_horizon is not None:
                        if arrival_interval <= established_horizon:
                            intervals.append(arrival_interval)
                    elif arrival_interval <= _BOOTSTRAP_FRESHNESS_HORIZON_S:
                        intervals.append(arrival_interval)
                        self._arrival_cadence_candidate[reading.channel] = None
                    else:
                        # The first interval larger than the bootstrap horizon
                        # could be an early outage gap OR the start of a
                        # genuinely slow producer cadence (e.g. a replayed curve
                        # sampled every 10 minutes). One observation cannot
                        # distinguish them, so do not certify either; hold it as
                        # a candidate. A SECOND arrival interval of the same
                        # magnitude certifies the cadence: a real slow producer
                        # repeats its interval, while a one-off gap does not.
                        # Without this path a slow-cadence source could never
                        # establish an arrival cadence, collapsing the horizon
                        # to the bootstrap bound and withholding every R_thermal
                        # from a healthy producer. Mirrors the cooldown
                        # service's source-cadence escape hatch.
                        candidate = self._arrival_cadence_candidate[reading.channel]
                        if (
                            candidate is not None
                            and arrival_interval <= 3.0 * candidate
                            and candidate <= 3.0 * arrival_interval
                        ):
                            intervals.append(candidate)
                            intervals.append(arrival_interval)
                            self._arrival_cadence_candidate[reading.channel] = None
                        else:
                            self._arrival_cadence_candidate[reading.channel] = arrival_interval
            self._last_required_input_arrival_monotonic[reading.channel] = now_monotonic
            raw_ingress = reading.metadata.get(BROKER_INGRESS_MONOTONIC_METADATA_KEY)
            if raw_ingress is None:
                self._last_required_input_ingress_monotonic[reading.channel] = None
            else:
                try:
                    ingress = float(raw_ingress)
                except (TypeError, ValueError):
                    ingress = math.nan
                self._last_required_input_ingress_monotonic[reading.channel] = (
                    ingress if math.isfinite(ingress) else None
                )

        # An unusable target-channel update is EVIDENCE THE FEED IS BROKEN, not
        # an absence of news. The last legible value stays cached (a failed
        # reading must not overwrite it), but the channel's freshness anchors
        # are invalidated so process() cannot re-emit R_thermal from that
        # cached input as if it were current. A usable reading at or after the
        # failed one in the same batch supersedes it.
        latest_usable_by_channel: dict[str, float | None] = {channel: None for channel in target_channels}
        for reading in relevant:
            ts = reading.timestamp.timestamp()
            latest = latest_usable_by_channel[reading.channel]
            if latest is None or ts >= latest:
                latest_usable_by_channel[reading.channel] = ts
        for reading in readings:
            if reading.channel not in target_channels or reading.status is ChannelStatus.OK:
                continue
            latest_usable = latest_usable_by_channel[reading.channel]
            if latest_usable is not None and latest_usable >= reading.timestamp.timestamp():
                continue
            self._last_required_input_arrival_monotonic.pop(reading.channel, None)
            self._last_required_input_ingress_monotonic.pop(reading.channel, None)

        # Проверить, что все три канала известны
        missing = target_channels - self._last.keys()
        if missing:
            _log.debug(
                "ThermalCalculator: недостаточно данных, отсутствуют каналы: %s",
                ", ".join(sorted(missing)),
            )
            return []

        stale_channels = [
            channel for channel in target_channels if self._is_input_stale(channel, now_monotonic=now_monotonic)
        ]
        if stale_channels:
            _log.debug(
                "ThermalCalculator: required input freshness check failed for %s",
                ", ".join(sorted(stale_channels)),
            )
            return []

        T_hot = self._last[self._hot_sensor]
        T_cold = self._last[self._cold_sensor]
        P = self._last[self._heater_channel]

        if P == 0.0:
            _log.debug("ThermalCalculator: мощность нагревателя равна нулю, тепловое сопротивление не определено")
            return []

        if P < 0.0:
            _log.warning(
                "ThermalCalculator: мощность нагревателя отрицательна (P=%.6g Вт), вычисление пропущено",
                P,
            )
            return []

        R_thermal = (T_hot - T_cold) / P

        _log.debug(
            "ThermalCalculator: T_hot=%.4f K, T_cold=%.4f K, P=%.6g Вт → R_thermal=%.6g К/Вт",
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
