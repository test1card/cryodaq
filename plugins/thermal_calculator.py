"""Плагин расчёта теплового сопротивления для CryoDAQ.

Вычисляет тепловое сопротивление R_thermal = (T_hot - T_cold) / P
по трём каналам: два термометра и канал мощности нагревателя.
Поддерживает накопление последних известных значений, что позволяет
корректно работать при частичных пакетах показаний.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Any

from cryodaq.analytics.base_plugin import AnalyticsPlugin, DerivedMetric
from cryodaq.core.channel_identity import channel_id_of, matches_channel_id
from cryodaq.core.reading_freshness import judge_freshness
from cryodaq.drivers.base import ChannelStatus, Reading

# Calculation-specific maximum input age, deliberately STRICTER than the shared
# reporting default (core.reading_freshness.READING_STALE_AFTER_S, 60 s). It is
# passed explicitly to judge_freshness and does not change that default for any
# other caller.
#
# The two answer different questions. A report shows an operator a number to
# read, where a value a minute old is still informative if its age is stated.
# This combines three inputs into a derived quantity, where a temperature from
# before a sensor failed silently corrupts the result rather than merely aging
# it. Instruments poll at 1-2 s, so 30 s still covers a normal batch and any
# ordinary hiccup.
#
# Measured against an explicit processing reference, never against the cache
# itself — see the note in process().
_INPUT_WINDOW_S = 30.0

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
        self._binding_error: str | None = "конфигурация не применена"
        self._awaiting_selection: bool = True

        # channel ID -> (value, timestamp, status). Provenance travels with the
        # value: caching bare floats let a fresh power reading republish stale
        # temperatures as a new result.
        self._last: dict[str, tuple[float, datetime, ChannelStatus]] = {}
        # Frozen ID <-> runtime-label binding, resolved once per run.
        self._resolved: dict[str, str] = {}
        self._runtime_label: dict[str, str] = {}
        self._unavailable_note: str | None = None

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

        self._hot_sensor = str(config.get("hot_sensor", "")).strip()
        self._cold_sensor = str(config.get("cold_sensor", "")).strip()
        self._heater_channel = str(config.get("heater_channel", "")).strip()

        # Rebinding starts a new calculation. Carrying the previous run's
        # temperatures across would let a single fresh power reading publish a
        # result built from the sensors the operator just stopped using.
        self._last.clear()
        self._resolved.clear()
        self._runtime_label.clear()
        self._unavailable_note = None

        self._binding_error = self._validate_bindings()
        if self._binding_error is not None:
            # Said once, at configure time. This used to be a per-tick DEBUG
            # line: between 2026-09-03 02:38 and 09:53 it printed 26 044 times
            # and the operator had no idea the calculation was dead.
            #
            # Awaiting an operator choice is a NORMAL state and is reported as
            # such; a binding that cannot resolve is a configuration fault.
            if self._awaiting_selection:
                _log.info(
                    "ThermalCalculator: %s. Вычисление недоступно, пока датчики не выбраны.",
                    self._binding_error,
                )
            else:
                _log.error(
                    "ThermalCalculator: %s. Вычисление НЕДОСТУПНО до исправления конфигурации.",
                    self._binding_error,
                )
            return

        _log.info(
            "ThermalCalculator сконфигурирован: горячий=%r, холодный=%r, нагреватель=%r",
            self._hot_sensor,
            self._cold_sensor,
            self._heater_channel,
        )

    def _log_unavailable(self, note: str) -> None:
        """Say why there is no result — once per distinct reason, not per tick.

        The per-tick DEBUG line this replaces printed 26 044 times in seven
        hours while the calculation was dead, which is indistinguishable from
        healthy silence.
        """

        if note == self._unavailable_note:
            return
        self._unavailable_note = note
        _log.info("ThermalCalculator: результат недоступен — %s", note)

    def _validate_bindings(self) -> str | None:
        """Bind to stable channel IDs. Names are presentation; IDs are identity.

        A sensor's display name is operator-editable free text. On 2026-09-02
        the names in ``channels.yaml`` were rewritten (``Т1`` became
        "1 Верх образец 2"), and this plugin — configured as
        ``hot_sensor: "Т1 Криостат верх"``, an ID glued to a since-replaced
        display name — silently stopped matching anything.

        There is deliberately no fuzzy resolution here. ``ChannelManager``
        offers ``find_by_name`` and ``normalize_channel_id``; using either would
        make the physics depend on editable text again, and would make a rename
        change which sensor the answer came from rather than making it fail.
        An unresolvable binding makes the calculation unavailable, and says so.
        """

        self._awaiting_selection = False
        missing = [
            label
            for label, value in (
                ("hot_sensor", self._hot_sensor),
                ("cold_sensor", self._cold_sensor),
                ("heater_channel", self._heater_channel),
            )
            if not value
        ]
        if missing:
            # Hot and cold are chosen per run: shipping unbound is expected, not
            # a fault. A default pair would emit R_thermal for whichever sensors
            # were written down last, and a run on a different pair would get a
            # confident wrong number with nothing to indicate it.
            self._awaiting_selection = set(missing) <= {"hot_sensor", "cold_sensor"}
            return f"не выбраны датчики: {', '.join(missing)}"

        # The inventory is the authority on what a channel ID is. If it cannot
        # be read we refuse rather than accept an unverifiable bare ID: logging
        # "configured" over an unchecked binding is the silent-success failure
        # this plugin already suffered once.
        try:
            from cryodaq.core.channel_manager import get_channel_manager

            known = set(get_channel_manager().get_all())
        except Exception as exc:  # noqa: BLE001 - configuration must not crash the engine
            return f"инвентарь каналов недоступен ({type(exc).__name__}), привязки не проверены"
        if not known:
            return "инвентарь каналов пуст, привязки не проверены"

        # One sensor cannot be both ends of a thermal path. dT is identically
        # zero, so R = dT/P publishes a confident 0 K/W — an operator
        # configuration mistake rendered as valid physics, which is worse than
        # no number at all.
        if self._hot_sensor == self._cold_sensor:
            return f"hot_sensor и cold_sensor указывают на один канал ({self._hot_sensor!r})"

        problems: list[str] = []
        for label, value in (("hot_sensor", self._hot_sensor), ("cold_sensor", self._cold_sensor)):
            if value not in known:
                hint = ""
                # The classic mis-binding: "<id> <display name>".
                head = channel_id_of(value)
                if head != value and head in known:
                    hint = f" — похоже на идентификатор с приписанным именем; используйте {head!r}"
                problems.append(f"{label}={value!r} не является известным идентификатором канала{hint}")
        if problems:
            return "; ".join(problems)
        return None

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
        if self._binding_error is not None:
            # Already reported at configure time; do not repeat it every tick.
            return []

        # Instruments label readings with the string from instruments.yaml —
        # the stable ID with a human name appended ("Т1 Криостат верх"). The
        # configuration stores the ID. Comparing Reading.channel against the
        # bare ID matched NOTHING in production, silently, once per tick.
        #
        # Each configured ID is projected onto the runtime label once, through
        # the shared rule in core.channel_identity, and the label is then frozen
        # for the run. Afterwards matching is exact against that frozen label,
        # so a sensor renamed mid-run is a hard mismatch rather than a silent
        # re-binding to a different physical sensor.
        target_ids = (self._hot_sensor, self._cold_sensor, self._heater_channel)
        accepted_this_batch = False
        for reading in sorted(readings, key=lambda r: r.timestamp):
            frozen = self._runtime_label.get(reading.channel)
            if frozen is None:
                matched = next(
                    (cid for cid in target_ids if matches_channel_id(reading.channel, cid)),
                    None,
                )
                if matched is None:
                    continue
                if matched in self._resolved and self._resolved[matched] != reading.channel:
                    _log.error(
                        "ThermalCalculator: канал %s теперь приходит как %r, а был %r — "
                        "привязка заморожена, вычисление остановлено",
                        matched,
                        reading.channel,
                        self._resolved[matched],
                    )
                    self._binding_error = f"метка канала {matched} изменилась во время прогона"
                    return []
                self._resolved[matched] = reading.channel
                self._runtime_label[reading.channel] = matched
                frozen = matched
            # Retain status and timestamp, not just the value: a cached number
            # with no provenance let a fresh power reading republish stale
            # temperatures as a new result.
            self._last[frozen] = (reading.value, reading.timestamp, reading.status)
            accepted_this_batch = True

        # A result must be caused by this batch. Without this, a later call
        # carrying no selected channel left the cache untouched and republished
        # the previous answer as a brand-new DerivedMetric.now().
        if not accepted_this_batch:
            self._log_unavailable("в пакете нет выбранных каналов")
            return []

        missing = [cid for cid in target_ids if cid not in self._last]
        if missing:
            # An ID that is never observed is LOGGED unavailable — it is not
            # surfaced in the GUI or the report, so an operator watching either
            # of those sees no metric and no reason. The configuration check
            # proves only that the ID exists in channels.yaml; it is NOT proof
            # that the sensor is on this stand's instrument roster. First
            # observation is what establishes that.
            self._log_unavailable("нет показаний по каналам: " + ", ".join(missing))
            return []

        # Freshness is measured against an explicit processing reference, NOT
        # against the newest cached input. Comparing the cache to itself tests
        # coherence, not currency: three mutually aligned readings from five
        # hours ago agreed with each other perfectly and were published as a new
        # result.
        reference = datetime.now(UTC)
        unusable: list[str] = []
        for cid in target_ids:
            value, ts, status = self._last[cid]
            if status is not ChannelStatus.OK or not math.isfinite(value):
                unusable.append(f"{cid}: статус {getattr(status, 'value', status)}")
                continue
            verdict = judge_freshness(ts.timestamp(), now_epoch=reference.timestamp(), max_age_s=_INPUT_WINDOW_S)
            if not verdict.is_current:
                unusable.append(f"{cid}: {verdict.reason}")
        if unusable:
            self._log_unavailable("вход не годен — " + "; ".join(unusable))
            return []

        T_hot = self._last[self._hot_sensor][0]
        T_cold = self._last[self._cold_sensor][0]
        P = self._last[self._heater_channel][0]

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
