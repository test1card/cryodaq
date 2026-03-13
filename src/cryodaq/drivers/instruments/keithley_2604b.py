"""Драйвер источника-измерителя Keithley 2604B (TSP, USB-TMC).

ВНИМАНИЕ — СИСТЕМА БЕЗОПАСНОСТИ КРИТИЧЕСКОГО УРОВНЯ.
Данный драйвер управляет нагревателем при температуре 4 К.
Любая неисправность может привести к разрушению криостата или
потере образца. Все изменения должны проходить ревизию безопасности.

Прибор использует TSP (Test Script Processor) — Lua-совместимый язык
командного управления. Команды НЕ являются SCPI.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from pathlib import Path
from typing import Any

from cryodaq.drivers.base import ChannelStatus, InstrumentDriver, Reading
from cryodaq.drivers.transport.usbtmc import USBTMCTransport

log = logging.getLogger(__name__)

# Путь к TSP-скриптам по умолчанию относительно корня проекта
_DEFAULT_TSP_DIR = Path(__file__).parents[4] / "tsp"

# Интервал сердцебиения (секунды) — должен быть меньше таймаута watchdog на приборе
_HEARTBEAT_INTERVAL_S: float = 10.0

# Параметры mock-симуляции охлаждения
_MOCK_R0: float = 100.0          # сопротивление при комнатной температуре, Ом
_MOCK_T0: float = 300.0          # начальная температура, К
_MOCK_T_BASE: float = 1.0        # базовая температура при 4 К, Ом (конечное значение)
_MOCK_ALPHA: float = 0.0033      # ТКС (1/К) — линейная модель
_MOCK_COOLING_RATE: float = 0.1  # скорость охлаждения, К/цикл


class Keithley2604B(InstrumentDriver):
    """Драйвер источника-измерителя Keithley 2604B.

    Управляет одним SMU-каналом (smua) через TSP-скрипты,
    загружаемые в прибор перед запуском эксперимента.

    СИСТЕМА БЕЗОПАСНОСТИ:
    - ``disconnect()`` **всегда** вызывает ``emergency_off()`` перед закрытием.
    - Фоновая задача heartbeat сбрасывает watchdog-таймер каждые 10 с.
    - Сбой heartbeat → CRITICAL лог + аварийное отключение.
    - ``__del__`` делает попытку аварийного отключения как последний рубеж.

    Parameters
    ----------
    name:
        Уникальное имя экземпляра (используется в метаданных Reading).
    resource_str:
        VISA-строка ресурса, например
        ``"USB0::0x05E6::0x2604::SERIALNUM::INSTR"``.
    tsp_dir:
        Директория с TSP-скриптами (.lua файлы).
        По умолчанию — папка ``tsp/`` в корне проекта.
    mock:
        Если ``True`` — работает без реального прибора, симулирует
        охлаждение криостата от 300 К до ~4 К.
    """

    def __init__(
        self,
        name: str,
        resource_str: str,
        *,
        tsp_dir: Path | None = None,
        mock: bool = False,
    ) -> None:
        super().__init__(name, mock=mock)
        self._resource_str = resource_str
        self._tsp_dir = tsp_dir or _DEFAULT_TSP_DIR
        self._transport = USBTMCTransport(mock=mock)
        self._instrument_id: str = ""

        # Фоновая задача heartbeat
        self._heartbeat_task: asyncio.Task[None] | None = None

        # Параметры текущего источника (используются в mock-режиме)
        self._p_target: float = 0.0

        # Состояние mock-симуляции охлаждения
        self._mock_temp: float = _MOCK_T0       # текущая температура, К
        self._mock_read_count: int = 0

    # ------------------------------------------------------------------
    # InstrumentDriver — обязательный интерфейс
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Установить USB-TMC соединение и верифицировать модель прибора.

        Отправляет ``*IDN?`` и проверяет наличие строки ``"2604B"``
        в ответе прибора. При несоответствии — закрывает соединение
        и выбрасывает исключение.

        Raises
        ------
        RuntimeError
            Если прибор не отвечает или IDN не содержит ``"2604B"``.
        """
        log.info("%s: подключение к %s", self.name, self._resource_str)
        await self._transport.open(self._resource_str)

        try:
            idn = await self._transport.query("*IDN?")
            self._instrument_id = idn
            log.info("%s: IDN = %s", self.name, idn)

            if "2604B" not in idn:
                raise RuntimeError(
                    f"{self.name}: IDN не содержит '2604B' — получено: '{idn}'"
                )
        except Exception as exc:
            log.error("%s: ошибка верификации прибора — %s", self.name, exc)
            await self._transport.close()
            raise

        self._connected = True
        log.info("%s: соединение установлено", self.name)

    async def disconnect(self) -> None:
        """Отключиться от прибора (идемпотентно).

        ВАЖНО: перед закрытием соединения **всегда** вызывает
        :meth:`emergency_off` для безопасного отключения нагревателя.
        """
        if not self._connected:
            return

        log.info("%s: отключение — аварийное отключение выхода", self.name)
        await self.emergency_off()
        await self._transport.close()
        self._connected = False
        log.info("%s: соединение закрыто", self.name)

    async def read_channels(self) -> list[Reading]:
        """Считать текущие показания SMU-канала smua.

        Запрашивает ток и напряжение одной командой ``print(smua.measure.iv())``,
        вычисляет сопротивление и мощность. Возвращает 4 объекта
        :class:`~cryodaq.drivers.base.Reading`.

        Примечание: ``smua.measure.iv()`` возвращает значения в порядке
        **ток\\tнапряжение** (I, V).

        Returns
        -------
        list[Reading]
            Четыре показания: напряжение (V), ток (A),
            сопротивление (Ohm), мощность (W).

        Raises
        ------
        RuntimeError
            Если прибор не подключён.
        """
        if not self._connected:
            raise RuntimeError(f"{self.name}: прибор не подключён")

        if self.mock:
            return self._mock_readings()

        raw = await self._transport.query("print(smua.measure.iv())")
        log.debug("%s: smua.measure.iv() → %s", self.name, raw)

        try:
            parts = raw.strip().split("\t")
            if len(parts) != 2:
                raise ValueError(f"ожидалось 2 значения, получено {len(parts)}: '{raw}'")
            current = float(parts[0])
            voltage = float(parts[1])
        except Exception as exc:
            log.error("%s: ошибка разбора IV-ответа '%s' — %s", self.name, raw, exc)
            return self._error_readings()

        resistance = (voltage / current) if current != 0.0 else float("nan")
        power = voltage * current

        metadata: dict[str, Any] = {
            "instrument_id": self._instrument_id,
            "resource_str": self._resource_str,
        }

        return [
            Reading.now(
                channel=f"{self.name}/smua/voltage",
                value=voltage,
                unit="V",
                status=ChannelStatus.OK,
                raw=voltage,
                metadata=metadata,
            ),
            Reading.now(
                channel=f"{self.name}/smua/current",
                value=current,
                unit="A",
                status=ChannelStatus.OK,
                raw=current,
                metadata=metadata,
            ),
            Reading.now(
                channel=f"{self.name}/smua/resistance",
                value=resistance,
                unit="Ohm",
                status=ChannelStatus.OK if math.isfinite(resistance) else ChannelStatus.SENSOR_ERROR,
                raw=resistance if math.isfinite(resistance) else None,
                metadata=metadata,
            ),
            Reading.now(
                channel=f"{self.name}/smua/power",
                value=power,
                unit="W",
                status=ChannelStatus.OK,
                raw=power,
                metadata=metadata,
            ),
        ]

    # ------------------------------------------------------------------
    # TSP-управление
    # ------------------------------------------------------------------

    async def load_tsp(self, script_path: Path) -> None:
        """Загрузить и запустить TSP-скрипт из файла.

        Использует конструкцию ``loadandrunscript`` / ``endscript``.
        Скрипт читается с диска, обёртывается TSP-заголовком и
        хвостом, затем отправляется в прибор целиком через
        :meth:`~cryodaq.drivers.transport.usbtmc.USBTMCTransport.write_raw`.

        Parameters
        ----------
        script_path:
            Полный путь к .lua файлу.

        Raises
        ------
        FileNotFoundError
            Если файл не найден.
        RuntimeError
            Если прибор не подключён.
        """
        if not self._connected:
            raise RuntimeError(f"{self.name}: прибор не подключён")

        if not script_path.exists():
            raise FileNotFoundError(f"{self.name}: TSP-скрипт не найден: {script_path}")

        log.info("%s: загрузка TSP-скрипта %s", self.name, script_path)

        script_body = script_path.read_text(encoding="utf-8")

        # TSP loadandrunscript выполняет скрипт немедленно после endscript
        payload = f"loadandrunscript\n{script_body}\nendscript\n"
        await self._transport.write_raw(payload.encode("utf-8"))

        log.info("%s: TSP-скрипт %s загружен и запущен", self.name, script_path.name)

    async def start_source(
        self,
        p_target: float,
        v_compliance: float,
        i_compliance: float,
    ) -> None:
        """Запустить режим источника постоянной мощности.

        Устанавливает TSP-переменные ``P_target``, ``V_compliance``,
        ``I_compliance``, загружает скрипт ``p_const_single.lua``
        из директории tsp_dir, затем запускает фоновую задачу
        :meth:`_heartbeat_loop`.

        Parameters
        ----------
        p_target:
            Целевая мощность нагревателя, Вт.
        v_compliance:
            Предельное напряжение источника, В.
        i_compliance:
            Предельный ток источника, А.

        Raises
        ------
        RuntimeError
            Если прибор не подключён.
        ValueError
            Если p_target <= 0 или compliance-значения некорректны.
        """
        if not self._connected:
            raise RuntimeError(f"{self.name}: прибор не подключён")

        if p_target <= 0:
            raise ValueError(f"{self.name}: P_target должна быть > 0, получено {p_target}")
        if v_compliance <= 0:
            raise ValueError(
                f"{self.name}: V_compliance должна быть > 0, получено {v_compliance}"
            )
        if i_compliance <= 0:
            raise ValueError(
                f"{self.name}: I_compliance должна быть > 0, получено {i_compliance}"
            )

        log.info(
            "%s: запуск источника — P=%.4f Вт, Vcomp=%.3f В, Icomp=%.4f А",
            self.name,
            p_target,
            v_compliance,
            i_compliance,
        )

        # Установить переменные в пространство имён TSP прибора
        await self._transport.write(f"P_target = {p_target}")
        await self._transport.write(f"V_compliance = {v_compliance}")
        await self._transport.write(f"I_compliance = {i_compliance}")

        self._p_target = p_target

        # Загрузить и запустить управляющий скрипт
        script_path = self._tsp_dir / "p_const_single.lua"
        await self.load_tsp(script_path)

        # Запустить heartbeat
        self._start_heartbeat()

        log.info("%s: источник запущен, heartbeat активен", self.name)

    async def stop_source(self) -> None:
        """Остановить режим источника.

        Отправляет TSP-вызов ``emergency_stop()`` (определён в скрипте),
        отменяет задачу heartbeat, затем верифицирует, что выход отключён.
        """
        log.info("%s: остановка источника", self.name)

        self._cancel_heartbeat()

        if self._connected:
            try:
                await self._transport.write("emergency_stop()")
                log.info("%s: emergency_stop() отправлена в прибор", self.name)
            except Exception as exc:
                log.error("%s: ошибка при отправке emergency_stop() — %s", self.name, exc)

            # Верифицировать, что выход действительно выключен
            await self._verify_output_off()

        self._p_target = 0.0

    async def heartbeat(self) -> None:
        """Сбросить watchdog-таймер на приборе.

        Отправляет TSP-вызов ``heartbeat()``, определённый в загруженном
        скрипте. Должен вызываться не реже чем раз в период watchdog.
        """
        if not self._connected:
            return
        await self._transport.write("heartbeat()")
        log.debug("%s: heartbeat отправлен", self.name)

    async def read_buffer(
        self,
        start_idx: int = 1,
        count: int = 100,
    ) -> list[dict[str, float]]:
        """Считать данные из буфера измерений nvbuffer1.

        Читает временны́е метки, напряжение и ток через
        ``printbuffer``, вычисляет сопротивление и мощность.

        Parameters
        ----------
        start_idx:
            Начальный индекс буфера (1-based).
        count:
            Количество точек для чтения.

        Returns
        -------
        list[dict]
            Список словарей с ключами:
            ``timestamp``, ``voltage``, ``current``,
            ``resistance``, ``power``.

        Raises
        ------
        RuntimeError
            Если прибор не подключён.
        """
        if not self._connected:
            raise RuntimeError(f"{self.name}: прибор не подключён")

        end_idx = start_idx + count - 1

        if self.mock:
            return self._mock_buffer(start_idx, count)

        # Запросить временны́е метки, затем ток и напряжение из буфера
        # nvbuffer1 хранит ток (smua.measure.iv сохраняет I и V)
        tsp_cmd = (
            f"printbuffer({start_idx}, {end_idx}, "
            f"nvbuffer1.timestamps, nvbuffer1.sourcevalues, nvbuffer1)"
        )
        raw = await self._transport.query(tsp_cmd, timeout_ms=10_000)
        log.debug("%s: буфер [%d:%d] → %s", self.name, start_idx, end_idx, raw[:120])

        return self._parse_buffer_response(raw)

    async def emergency_off(self) -> None:
        """АВАРИЙНОЕ отключение выхода smua.

        Отправляет команду немедленного отключения выхода:
        ``smua.source.output = smua.OUTPUT_OFF``.

        Данный метод **не должен** генерировать исключения —
        он вызывается в деструкторе и аварийных обработчиках.
        """
        log.critical(
            "%s: АВАРИЙНОЕ ОТКЛЮЧЕНИЕ ВЫХОДА smua",
            self.name,
        )

        self._cancel_heartbeat()

        if self.mock:
            log.critical("%s: [mock] выход smua отключён", self.name)
            self._p_target = 0.0
            return

        if not self._connected:
            return

        try:
            await self._transport.write("smua.source.output = smua.OUTPUT_OFF")
            log.critical("%s: smua.OUTPUT_OFF отправлена", self.name)
        except Exception as exc:
            log.critical(
                "%s: КРИТИЧЕСКАЯ ОШИБКА при аварийном отключении — %s",
                self.name,
                exc,
            )

        self._p_target = 0.0

    async def check_error(self) -> str | None:
        """Проверить флаг ошибки TSP-скрипта.

        Запрашивает переменную ``script_error`` из пространства имён прибора.

        Returns
        -------
        str | None
            Строка с описанием ошибки или ``None`` если ошибок нет.

        Raises
        ------
        RuntimeError
            Если прибор не подключён.
        """
        if not self._connected:
            raise RuntimeError(f"{self.name}: прибор не подключён")

        response = await self._transport.query("print(script_error)")
        response = response.strip()

        if response.upper() == "NONE" or response == "0" or response == "":
            return None

        log.warning("%s: TSP ошибка скрипта: %s", self.name, response)
        return response

    # ------------------------------------------------------------------
    # Heartbeat — фоновая задача
    # ------------------------------------------------------------------

    def _start_heartbeat(self) -> None:
        """Запустить фоновую задачу сердцебиения."""
        self._cancel_heartbeat()
        self._heartbeat_task = asyncio.get_event_loop().create_task(
            self._heartbeat_loop(),
            name=f"heartbeat:{self.name}",
        )
        log.debug("%s: задача heartbeat запущена", self.name)

    def _cancel_heartbeat(self) -> None:
        """Отменить задачу сердцебиения (идемпотентно)."""
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            log.debug("%s: задача heartbeat отменена", self.name)
        self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        """Фоновая петля: отправляет heartbeat каждые ``_HEARTBEAT_INTERVAL_S`` секунд.

        При сбое немедленно инициирует аварийное отключение и
        записывает сообщение CRITICAL в журнал.
        """
        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL_S)
                await self.heartbeat()
        except asyncio.CancelledError:
            log.debug("%s: heartbeat_loop завершён по отмене", self.name)
            raise
        except Exception as exc:
            log.critical(
                "%s: СБОЙ HEARTBEAT — аварийное отключение нагревателя! Ошибка: %s",
                self.name,
                exc,
            )
            # Попытка аварийного отключения — не бросаем исключение дальше,
            # чтобы не уронить event loop
            try:
                await self.emergency_off()
            except Exception as inner:
                log.critical(
                    "%s: КРИТИЧЕСКАЯ ОШИБКА при аварийном отключении после сбоя heartbeat — %s",
                    self.name,
                    inner,
                )

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    async def _verify_output_off(self) -> None:
        """Верифицировать, что выход smua действительно отключён.

        Запрашивает ``smua.source.output`` и проверяет,
        что значение равно ``0`` (OUTPUT_OFF).
        """
        if self.mock:
            return
        try:
            response = await self._transport.query(
                "print(smua.source.output)", timeout_ms=3000
            )
            val = response.strip()
            if val != "0":
                log.critical(
                    "%s: ВНИМАНИЕ — smua.source.output = %s (ожидалось 0/OUTPUT_OFF)",
                    self.name,
                    val,
                )
            else:
                log.info("%s: выход smua подтверждён как OUTPUT_OFF", self.name)
        except Exception as exc:
            log.error(
                "%s: не удалось верифицировать состояние выхода — %s",
                self.name,
                exc,
            )

    def _parse_buffer_response(self, raw: str) -> list[dict[str, float]]:
        """Разобрать ответ printbuffer в список словарей.

        Ожидаемый формат строки: значения через Tab или запятую,
        сгруппированные тройками: timestamp, sourcevalue (V), current (I).
        """
        # printbuffer возвращает все значения через запятую в одной строке
        tokens = [t.strip() for t in raw.replace("\t", ",").split(",")]

        results: list[dict[str, float]] = []
        # Три столбца: timestamps, sourcevalues, nvbuffer1 (current)
        n = len(tokens) // 3
        for i in range(n):
            try:
                ts = float(tokens[i])
                voltage = float(tokens[n + i])
                current = float(tokens[2 * n + i])
                resistance = (voltage / current) if current != 0.0 else float("nan")
                power = voltage * current
                results.append(
                    {
                        "timestamp": ts,
                        "voltage": voltage,
                        "current": current,
                        "resistance": resistance,
                        "power": power,
                    }
                )
            except (ValueError, IndexError) as exc:
                log.warning(
                    "%s: ошибка разбора точки буфера [%d] — %s",
                    self.name,
                    i,
                    exc,
                )

        return results

    # ------------------------------------------------------------------
    # Mock-режим
    # ------------------------------------------------------------------

    def _mock_r_of_t(self) -> float:
        """Вычислить модельное сопротивление при текущей mock-температуре.

        Использует линейную модель: R(T) = R0 * (1 + alpha*(T - T0)).
        При температуре ниже 10 К ограничивает R снизу значением 1 Ом
        (реалистично для резистивного нагревателя при 4 К).
        """
        r = _MOCK_R0 * (1.0 + _MOCK_ALPHA * (self._mock_temp - _MOCK_T0))
        return max(r, 1.0)

    def _mock_readings(self) -> list[Reading]:
        """Сгенерировать реалистичные mock-показания с симуляцией охлаждения."""
        # Продвигаем температуру охлаждения
        self._mock_read_count += 1
        if self._mock_temp > 4.0:
            self._mock_temp = max(4.0, self._mock_temp - _MOCK_COOLING_RATE)

        r = self._mock_r_of_t()

        # Если источник активен — вычисляем V, I из P = P_target и R
        if self._p_target > 0.0:
            # P = V^2 / R  →  V = sqrt(P * R)
            voltage = math.sqrt(self._p_target * r)
            current = voltage / r  # = sqrt(P / R)
        else:
            voltage = 0.0
            current = 0.0

        power = voltage * current
        resistance = r

        metadata: dict[str, Any] = {
            "instrument_id": "MOCK_2604B",
            "mock_temp_K": round(self._mock_temp, 3),
            "resource_str": self._resource_str,
        }

        return [
            Reading.now(
                channel=f"{self.name}/smua/voltage",
                value=round(voltage, 6),
                unit="V",
                status=ChannelStatus.OK,
                raw=voltage,
                metadata=metadata,
            ),
            Reading.now(
                channel=f"{self.name}/smua/current",
                value=round(current, 7),
                unit="A",
                status=ChannelStatus.OK,
                raw=current,
                metadata=metadata,
            ),
            Reading.now(
                channel=f"{self.name}/smua/resistance",
                value=round(resistance, 4),
                unit="Ohm",
                status=ChannelStatus.OK,
                raw=resistance,
                metadata=metadata,
            ),
            Reading.now(
                channel=f"{self.name}/smua/power",
                value=round(power, 7),
                unit="W",
                status=ChannelStatus.OK,
                raw=power,
                metadata=metadata,
            ),
        ]

    def _mock_buffer(self, start_idx: int, count: int) -> list[dict[str, float]]:
        """Сгенерировать mock-данные буфера измерений."""
        results: list[dict[str, float]] = []
        r = self._mock_r_of_t()
        voltage = math.sqrt(self._p_target * r) if self._p_target > 0.0 else 0.0
        current = voltage / r if r > 0.0 else 0.0

        for i in range(count):
            ts = float(start_idx + i) * 0.5
            results.append(
                {
                    "timestamp": ts,
                    "voltage": round(voltage, 6),
                    "current": round(current, 7),
                    "resistance": round(r, 4),
                    "power": round(voltage * current, 7),
                }
            )
        return results

    def _error_readings(self) -> list[Reading]:
        """Сформировать список Reading с состоянием SENSOR_ERROR для всех каналов."""
        metadata: dict[str, Any] = {
            "instrument_id": self._instrument_id,
            "resource_str": self._resource_str,
        }
        channels = [
            (f"{self.name}/smua/voltage", "V"),
            (f"{self.name}/smua/current", "A"),
            (f"{self.name}/smua/resistance", "Ohm"),
            (f"{self.name}/smua/power", "W"),
        ]
        return [
            Reading.now(
                channel=ch,
                value=float("nan"),
                unit=unit,
                status=ChannelStatus.SENSOR_ERROR,
                raw=None,
                metadata=metadata,
            )
            for ch, unit in channels
        ]

    # ------------------------------------------------------------------
    # Деструктор — последний рубеж безопасности
    # ------------------------------------------------------------------

    def __del__(self) -> None:
        """Попытка аварийного отключения при сборке мусора.

        Это лишь «последний рубеж» — не гарантирует выполнение.
        Правильный способ: использовать ``async with`` или явно
        вызывать ``disconnect()``.
        """
        if self._p_target > 0.0 or self._connected:
            # В деструкторе нет event loop — можно только попытаться
            # создать новый или использовать существующий
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # Планируем задачу в существующем loop
                    loop.create_task(
                        self.emergency_off(),
                        name=f"destructor_emergency_off:{self.name}",
                    )
                else:
                    loop.run_until_complete(self.emergency_off())
            except Exception:
                # В деструкторе никогда не бросаем исключений
                pass
