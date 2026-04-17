"""Движок оповещений (AlarmEngine) — мониторинг пороговых нарушений.

Принцип работы:
  1. AlarmEngine подписывается на DataBroker и получает все Reading.
  2. Для каждого показания проверяются все зарегистрированные тревоги,
     чей channel_pattern совпадает с Reading.channel.
  3. При срабатывании условия: состояние → ACTIVE, вызываются notifier-коллбэки,
     событие записывается в историю.
  4. Тревога автоматически сбрасывается (→ OK), когда значение уходит ниже
     (или выше) порога с учётом гистерезиса.
  5. Оператор может подтвердить тревогу (ACTIVE → ACKNOWLEDGED); из состояния
     ACKNOWLEDGED сброс происходит так же, как из ACTIVE.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from cryodaq.core.broker import DataBroker
from cryodaq.drivers.base import Reading

logger = logging.getLogger(__name__)

# Максимальное количество событий, хранимых в памяти
_MAX_EVENTS = 1000

# Имя подписки AlarmEngine в DataBroker
_SUBSCRIPTION_NAME = "alarm_engine"


class AlarmSeverity(Enum):
    """Уровень критичности тревоги."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlarmState(Enum):
    """Состояние тревоги.

    Диаграмма переходов::

        OK ──(условие выполнено)──► ACTIVE
                                      │
                          (оператор)  │
                        acknowledge() │
                                      ▼
                                 ACKNOWLEDGED
                                      │
                 (условие снято)      │  (условие снято)
                      ◄──────────────┘  ──────────────►
                      OK                              OK
        ACTIVE ──(условие снято, без подтверждения)──► OK
    """

    OK = "ok"
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"


@dataclass
class AlarmCondition:
    """Описание одного условия тревоги.

    Параметры
    ----------
    name:
        Уникальное имя тревоги (идентификатор).
    description:
        Текстовое описание — отображается в интерфейсе и логах.
    channel_pattern:
        Регулярное выражение, которому должен соответствовать Reading.channel.
        Пример: ``".*/smua/power"`` — канал power любого источника Keithley.
    threshold:
        Пороговое значение для сравнения с Reading.value.
    comparison:
        Оператор сравнения: ``">"`` (больше) или ``"<"`` (меньше).
    severity:
        Уровень критичности: INFO, WARNING или CRITICAL.
    hysteresis_k:
        Зона нечувствительности при сбросе тревоги. Тревога сбрасывается только
        когда значение пройдёт через ``threshold ± hysteresis_k``. По умолчанию 0.0.
    enabled:
        Если False — тревога не проверяется. По умолчанию True.
    """

    name: str
    description: str
    channel_pattern: str
    threshold: float
    comparison: str  # ">" или "<"
    severity: AlarmSeverity
    hysteresis_k: float = 0.0
    enabled: bool = True

    # Скомпилированное регулярное выражение — заполняется в __post_init__
    _pattern: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.comparison not in (">", "<"):
            raise ValueError(
                f"Тревога '{self.name}': недопустимый оператор сравнения "
                f"'{self.comparison}'. Допустимы: '>' и '<'."
            )
        try:
            self._pattern = re.compile(self.channel_pattern)
        except re.error as exc:
            raise ValueError(
                f"Тревога '{self.name}': некорректный channel_pattern "
                f"'{self.channel_pattern}': {exc}"
            ) from exc

    def matches_channel(self, channel: str) -> bool:
        """Проверить, соответствует ли имя канала шаблону тревоги."""
        return bool(self._pattern.match(channel))

    def is_triggered(self, value: float) -> bool:
        """Проверить, выполнено ли условие срабатывания для данного значения."""
        if self.comparison == ">":
            return value > self.threshold
        return value < self.threshold

    def is_cleared(self, value: float) -> bool:
        """Проверить, снято ли условие тревоги с учётом гистерезиса.

        Для ``">"``: снято, если ``value < threshold - hysteresis_k``.
        Для ``"<"``: снято, если ``value > threshold + hysteresis_k``.
        """
        if self.comparison == ">":
            return value < (self.threshold - self.hysteresis_k)
        return value > (self.threshold + self.hysteresis_k)


@dataclass(frozen=True)
class AlarmEvent:
    """Запись о событии тревоги.

    Неизменяемый объект — безопасен для хранения в истории и передачи notifier-ам.
    """

    timestamp: datetime
    alarm_name: str
    channel: str
    value: float
    threshold: float
    severity: AlarmSeverity
    event_type: str  # "activated" | "cleared" | "acknowledged"


@dataclass
class _AlarmRecord:
    """Внутренняя запись состояния одной тревоги."""

    condition: AlarmCondition
    state: AlarmState = AlarmState.OK
    last_activated: datetime | None = None
    activation_count: int = 0


class AlarmEngine:
    """Движок оповещений: мониторинг пороговых нарушений с диспетчеризацией уведомлений.

    Параметры
    ----------
    broker:
        DataBroker, из которого получаются показания.
    notifiers:
        Список async-коллбэков для отправки уведомлений (Telegram, WebSocket и т.д.).
        Каждый коллбэк получает один аргумент — ``AlarmEvent``.
        Ошибка в одном notifier не останавливает остальные.

    Пример использования::

        async def telegram_notify(event: AlarmEvent) -> None:
            await bot.send_message(chat_id, f"Тревога: {event.alarm_name}")

        engine = AlarmEngine(
            broker=broker,
            notifiers=[telegram_notify],
        )
        engine.load_config(Path("config/alarms.yaml"))
        await engine.start()
        # ...
        await engine.stop()
    """

    def __init__(
        self,
        broker: DataBroker,
        notifiers: list[Callable[[AlarmEvent], Any]] | None = None,
    ) -> None:
        self._broker = broker
        self._notifiers: list[Callable[[AlarmEvent], Any]] = notifiers or []
        self._alarms: dict[str, _AlarmRecord] = {}
        self._events: deque[AlarmEvent] = deque(maxlen=_MAX_EVENTS)
        self._queue: asyncio.Queue[Reading] | None = None
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Загрузка конфигурации
    # ------------------------------------------------------------------

    def load_config(self, config_path: Path) -> None:
        """Загрузить тревоги из YAML-файла.

        Ожидаемая структура файла::

            alarms:
              - name: "имя_тревоги"
                description: "Описание"
                channel_pattern: "регулярное выражение"
                threshold: 100.0
                comparison: ">"
                severity: "WARNING"
                hysteresis_k: 5.0
                enabled: true

        Параметры
        ----------
        config_path:
            Путь к YAML-файлу конфигурации тревог.

        Исключения
        ----------
        FileNotFoundError:
            Если файл не найден.
        ValueError:
            Если конфигурация содержит ошибки (дублирование имён, некорректные поля).
        """
        if not config_path.exists():
            raise FileNotFoundError(f"Файл конфигурации тревог не найден: {config_path}")

        with config_path.open(encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh)

        entries = raw.get("alarms", [])
        if not isinstance(entries, list):
            raise ValueError(
                f"Некорректный формат файла тревог: ключ 'alarms' должен "
                f"содержать список, получен {type(entries).__name__}."
            )

        loaded = 0
        for entry in entries:
            severity_raw = entry["severity"]
            try:
                severity = AlarmSeverity[severity_raw.upper()]
            except KeyError:
                raise ValueError(
                    f"Тревога '{entry['name']}': неизвестный уровень критичности "
                    f"'{severity_raw}'. Допустимы: {[s.name for s in AlarmSeverity]}."
                )

            condition = AlarmCondition(
                name=entry["name"],
                description=entry["description"],
                channel_pattern=entry["channel_pattern"],
                threshold=float(entry["threshold"]),
                comparison=entry["comparison"],
                severity=severity,
                hysteresis_k=float(entry.get("hysteresis_k", 0.0)),
                enabled=bool(entry.get("enabled", True)),
            )
            self.add_condition(condition)
            loaded += 1

        logger.info(
            "Конфигурация тревог загружена из '%s': %d тревог.",
            config_path,
            loaded,
        )

    def add_condition(self, condition: AlarmCondition) -> None:
        """Добавить тревогу программно.

        Параметры
        ----------
        condition:
            Описание условия тревоги.

        Исключения
        ----------
        ValueError:
            Если тревога с таким именем уже зарегистрирована.
        """
        if condition.name in self._alarms:
            raise ValueError(f"Тревога '{condition.name}' уже зарегистрирована.")
        self._alarms[condition.name] = _AlarmRecord(condition=condition)
        logger.info(
            "Тревога добавлена: '%s' | канал: '%s' | порог: %s %s | "
            "уровень: %s | гистерезис: %.4g.",
            condition.name,
            condition.channel_pattern,
            condition.comparison,
            condition.threshold,
            condition.severity.value,
            condition.hysteresis_k,
        )

    # ------------------------------------------------------------------
    # Управление жизненным циклом
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Запустить движок оповещений.

        Подписывается на DataBroker и запускает цикл проверки показаний.
        Повторный вызов без предварительного stop() игнорируется.
        """
        if self._task is not None and not self._task.done():
            logger.warning("AlarmEngine уже запущен — повторный start() проигнорирован.")
            return

        self._queue = await self._broker.subscribe(
            _SUBSCRIPTION_NAME,
            maxsize=10_000,
            filter_fn=lambda r: not r.channel.startswith(("alarm/", "analytics/", "system/")),
        )
        self._task = asyncio.create_task(self._check_loop(), name="alarm_check_loop")
        logger.info(
            "AlarmEngine запущен. Зарегистрировано тревог: %d.",
            len(self._alarms),
        )
        # Опубликовать начальное значение alarm_count=0
        await self._publish_alarm_count()

    async def stop(self) -> None:
        """Остановить движок оповещений.

        Отменяет задачу проверки и отписывается от DataBroker.
        """
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        await self._broker.unsubscribe(_SUBSCRIPTION_NAME)
        self._queue = None
        logger.info("AlarmEngine остановлен.")

    # ------------------------------------------------------------------
    # Управление состоянием
    # ------------------------------------------------------------------

    async def acknowledge(self, alarm_name: str) -> None:
        """Подтвердить активную тревогу (ACTIVE → ACKNOWLEDGED).

        Оператор принимает к сведению нарушение; тревога остаётся в поле
        зрения до момента, когда условие само снимется.

        Параметры
        ----------
        alarm_name:
            Имя тревоги, которую необходимо подтвердить.

        Исключения
        ----------
        KeyError:
            Если тревога с таким именем не найдена.
        """
        if alarm_name not in self._alarms:
            raise KeyError(
                f"Тревога '{alarm_name}' не найдена. "
                f"Зарегистрированные тревоги: {list(self._alarms.keys())}."
            )

        record = self._alarms[alarm_name]
        if record.state != AlarmState.ACTIVE:
            logger.warning(
                "Попытка подтвердить тревогу '%s', которая не находится в состоянии "
                "ACTIVE (текущее состояние: %s) — операция проигнорирована.",
                alarm_name,
                record.state.value,
            )
            return

        record.state = AlarmState.ACKNOWLEDGED

        now = datetime.now(UTC)
        event = AlarmEvent(
            timestamp=now,
            alarm_name=alarm_name,
            channel="",
            value=float("nan"),
            threshold=record.condition.threshold,
            severity=record.condition.severity,
            event_type="acknowledged",
        )
        self._events.append(event)

        logger.warning(
            "Тревога '%s' подтверждена оператором (ACTIVE → ACKNOWLEDGED). Описание: %s.",
            alarm_name,
            record.condition.description,
        )
        await self._publish_alarm_reading(event)
        await self._publish_alarm_count()

    def get_state(self) -> dict[str, AlarmState]:
        """Вернуть текущее состояние всех зарегистрированных тревог.

        Возвращает
        ----------
        dict[str, AlarmState]:
            Словарь {имя_тревоги: состояние}.
        """
        return {name: record.state for name, record in self._alarms.items()}

    def get_active_alarms(self) -> list[str]:
        """Вернуть имена тревог в состоянии ACTIVE или ACKNOWLEDGED.

        Возвращает
        ----------
        list[str]:
            Список имён активных или подтверждённых тревог.
        """
        return [
            name
            for name, record in self._alarms.items()
            if record.state in (AlarmState.ACTIVE, AlarmState.ACKNOWLEDGED)
        ]

    def get_events(self) -> list[AlarmEvent]:
        """Вернуть историю событий (до последних 1000).

        Возвращает
        ----------
        list[AlarmEvent]:
            Список событий в хронологическом порядке (от старых к новым).
        """
        return list(self._events)

    # ------------------------------------------------------------------
    # Основной цикл проверки
    # ------------------------------------------------------------------

    async def _check_loop(self) -> None:
        """Основной цикл проверки тревог.

        Непрерывно читает показания из очереди и проверяет все тревоги,
        чей channel_pattern совпадает с каналом пришедшего показания.
        """
        assert self._queue is not None, "Очередь не инициализирована — вызовите start()"

        logger.debug("Цикл проверки тревог запущен.")
        try:
            while True:
                reading: Reading = await self._queue.get()
                await self._process_reading(reading)
        except asyncio.CancelledError:
            logger.debug("Цикл проверки тревог завершён по отмене задачи.")
            raise

    async def _publish_alarm_reading(self, event: AlarmEvent) -> None:
        """Опубликовать событие тревоги как Reading в DataBroker."""
        reading = Reading.now(
            channel=f"alarm/{event.alarm_name}",
            value=event.value,
            unit="",
            instrument_id="alarm_engine",
            metadata={
                "alarm_name": event.alarm_name,
                "event_type": event.event_type,
                "severity": event.severity.value,
                "threshold": event.threshold,
                "channel": event.channel,
            },
        )
        await self._broker.publish(reading)

    async def _publish_alarm_count(self) -> None:
        """Опубликовать текущее количество активных тревог."""
        unresolved = self.get_active_alarms()
        reading = Reading.now(
            channel="analytics/alarm_count",
            value=float(len(unresolved)),
            unit="",
            instrument_id="alarm_engine",
            metadata={"active_names": unresolved},
        )
        await self._broker.publish(reading)

    async def _process_reading(self, reading: Reading) -> None:
        """Проверить показание против всех подходящих тревог.

        Логика переходов:
        - OK + is_triggered → ACTIVE (активировать, диспетчеризировать).
        - ACTIVE/ACKNOWLEDGED + is_cleared → OK (сбросить, диспетчеризировать).
        """
        # Не обрабатывать собственные публикации и системные каналы
        if reading.channel.startswith(("alarm/", "analytics/", "system/")):
            return

        for record in self._alarms.values():
            condition = record.condition

            # Отключённые тревоги пропускаем
            if not condition.enabled:
                continue

            # Проверяем совпадение канала с шаблоном
            if not condition.matches_channel(reading.channel):
                continue

            now = datetime.now(UTC)

            if record.state == AlarmState.OK and condition.is_triggered(reading.value):
                # Переход OK → ACTIVE
                record.state = AlarmState.ACTIVE
                record.last_activated = now
                record.activation_count += 1

                event = AlarmEvent(
                    timestamp=now,
                    alarm_name=condition.name,
                    channel=reading.channel,
                    value=reading.value,
                    threshold=condition.threshold,
                    severity=condition.severity,
                    event_type="activated",
                )
                self._events.append(event)

                logger.warning(
                    "ТРЕВОГА АКТИВИРОВАНА: '%s' | Уровень: %s | "
                    "Описание: %s | Канал: '%s' | "
                    "Значение: %.4g | Порог: %s %.4g | "
                    "Время: %s | Всего активаций: %d.",
                    condition.name,
                    condition.severity.value,
                    condition.description,
                    reading.channel,
                    reading.value,
                    condition.comparison,
                    condition.threshold,
                    now.isoformat(),
                    record.activation_count,
                )
                await self._dispatch(event)
                await self._publish_alarm_reading(event)
                await self._publish_alarm_count()

            elif record.state in (
                AlarmState.ACTIVE,
                AlarmState.ACKNOWLEDGED,
            ) and condition.is_cleared(reading.value):
                # Переход ACTIVE/ACKNOWLEDGED → OK
                previous_state = record.state
                record.state = AlarmState.OK

                event = AlarmEvent(
                    timestamp=now,
                    alarm_name=condition.name,
                    channel=reading.channel,
                    value=reading.value,
                    threshold=condition.threshold,
                    severity=condition.severity,
                    event_type="cleared",
                )
                self._events.append(event)

                logger.info(
                    "Тревога сброшена: '%s' | Предыдущее состояние: %s | "
                    "Канал: '%s' | Значение: %.4g | Порог: %s %.4g | Время: %s.",
                    condition.name,
                    previous_state.value,
                    reading.channel,
                    reading.value,
                    condition.comparison,
                    condition.threshold,
                    now.isoformat(),
                )
                await self._dispatch(event)
                await self._publish_alarm_reading(event)
                await self._publish_alarm_count()

    async def _dispatch(self, event: AlarmEvent) -> None:
        """Вызвать все notifier-коллбэки для данного события.

        Ошибка в одном notifier логируется и не останавливает остальные.

        Параметры
        ----------
        event:
            Событие тревоги для передачи notifier-ам.
        """
        for notifier in self._notifiers:
            try:
                await notifier(event)
            except Exception as exc:
                logger.exception(
                    "Ошибка в notifier '%s' при обработке события '%s' (тревога '%s'): %s.",
                    getattr(notifier, "__name__", repr(notifier)),
                    event.event_type,
                    event.alarm_name,
                    exc,
                )
