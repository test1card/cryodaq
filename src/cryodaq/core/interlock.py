"""Движок блокировок (InterlockEngine) — защита криогенного оборудования.

ВНИМАНИЕ: данный модуль является критичным для безопасности.
Любые изменения требуют ревью и тестирования перед деплоем.

Принцип работы:
  1. InterlockEngine подписывается на DataBroker и получает все Reading.
  2. Для каждого показания проверяются все ARMED-блокировки, чей channel_pattern
     совпадает с Reading.channel.
  3. При срабатывании условия: состояние → TRIPPED, вызывается action-коллбэк,
     событие записывается в лог и историю.
  4. TRIPPED-блокировка не срабатывает повторно до явного acknowledge().
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

# Имя подписки InterlockEngine в DataBroker
_SUBSCRIPTION_NAME = "interlock_engine"


class InterlockState(Enum):
    """Состояние блокировки."""

    ARMED = "armed"          # Активна, ожидает срабатывания
    TRIPPED = "tripped"      # Сработала — действие выполнено, ожидает подтверждения
    ACKNOWLEDGED = "acknowledged"  # Подтверждена оператором, возврат в ARMED


@dataclass
class InterlockCondition:
    """Описание одного условия блокировки.

    Параметры
    ----------
    name:
        Уникальное имя блокировки (идентификатор).
    description:
        Текстовое описание — отображается в интерфейсе и логах.
    channel_pattern:
        Регулярное выражение, которому должен соответствовать Reading.channel.
        Пример: ``"Т[1-8] .*"`` — каналы Т1–Т8 с любым суффиксом.
    threshold:
        Пороговое значение для сравнения с Reading.value.
    comparison:
        Оператор сравнения: ``">"`` (больше) или ``"<"`` (меньше).
    action:
        Имя действия из словаря actions, переданного в InterlockEngine.
        Например: ``"emergency_off"`` или ``"stop_source"``.
    cooldown_s:
        Минимальный интервал в секундах между повторными срабатываниями
        одной и той же блокировки. По умолчанию 0 (без ограничения).
    """

    name: str
    description: str
    channel_pattern: str
    threshold: float
    comparison: str  # ">" или "<"
    action: str
    cooldown_s: float = 0.0

    # Скомпилированное регулярное выражение — заполняется в __post_init__
    _pattern: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.comparison not in (">", "<"):
            raise ValueError(
                f"Блокировка '{self.name}': недопустимый оператор сравнения "
                f"'{self.comparison}'. Допустимы: '>' и '<'."
            )
        try:
            self._pattern = re.compile(self.channel_pattern)
        except re.error as exc:
            raise ValueError(
                f"Блокировка '{self.name}': некорректный channel_pattern "
                f"'{self.channel_pattern}': {exc}"
            ) from exc

    def matches_channel(self, channel: str) -> bool:
        """Проверить, соответствует ли имя канала шаблону блокировки."""
        return bool(self._pattern.match(channel))

    def is_triggered(self, value: float) -> bool:
        """Проверить, выполнено ли условие срабатывания для данного значения."""
        if self.comparison == ">":
            return value > self.threshold
        return value < self.threshold


@dataclass(frozen=True)
class InterlockEvent:
    """Запись о срабатывании блокировки.

    Неизменяемый объект — безопасен для хранения в истории и передачи.
    """

    timestamp: datetime
    interlock_name: str
    channel: str
    value: float
    threshold: float
    action_taken: str


@dataclass
class _InterlockRecord:
    """Внутренняя запись состояния одной блокировки."""

    condition: InterlockCondition
    state: InterlockState = InterlockState.ARMED
    last_trip_time: datetime | None = None
    trip_count: int = 0


class InterlockEngine:
    """Движок блокировок: мониторинг показаний и защитные действия.

    Параметры
    ----------
    broker:
        DataBroker, из которого получаются показания.
    actions:
        Словарь действий: имя → async-коллбэк.
        Пример: ``{"emergency_off": keithley.emergency_off}``.

    Пример использования::

        engine = InterlockEngine(
            broker=broker,
            actions={"emergency_off": keithley.emergency_off,
                     "stop_source": keithley.stop_source},
        )
        engine.load_config(Path("config/interlocks.yaml"))
        await engine.start()
        # ...
        await engine.stop()
    """

    def __init__(
        self,
        broker: DataBroker,
        actions: dict[str, Callable[[], Any]],
        *,
        trip_handler: Callable[[InterlockCondition, Reading], Any] | None = None,
    ) -> None:
        """Initialize.

        Parameters
        ----------
        actions:
            Dict of action_name → zero-arg callable. The callable is called
            from ``_trip`` after the trip event is logged. Backward-compatible
            with existing tests.
        trip_handler:
            Optional async/sync callback receiving the full ``InterlockCondition``
            and ``Reading`` context. Called from ``_trip`` ALONGSIDE the
            actions-dict callable. Used by SafetyManager wiring (Phase 2a
            Codex I.1) so the action name, condition name, channel, and value
            survive the trip path instead of being collapsed by zero-arg
            callbacks.
        """
        self._broker = broker
        self._actions = actions
        self._trip_handler = trip_handler
        self._interlocks: dict[str, _InterlockRecord] = {}
        self._events: deque[InterlockEvent] = deque(maxlen=_MAX_EVENTS)
        self._queue: asyncio.Queue[Reading] | None = None
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Загрузка конфигурации
    # ------------------------------------------------------------------

    def load_config(self, config_path: Path) -> None:
        """Загрузить блокировки из YAML-файла.

        Ожидаемая структура файла::

            interlocks:
              - name: "имя_блокировки"
                description: "Описание"
                channel_pattern: "регулярное выражение"
                threshold: 350.0
                comparison: ">"
                action: "emergency_off"
                cooldown_s: 10.0

        Параметры
        ----------
        config_path:
            Путь к YAML-файлу конфигурации блокировок.

        Исключения
        ----------
        FileNotFoundError:
            Если файл не найден.
        ValueError:
            Если конфигурация содержит ошибки (дублирование имён, неизвестные действия).
        """
        if not config_path.exists():
            raise FileNotFoundError(
                f"Файл конфигурации блокировок не найден: {config_path}"
            )

        with config_path.open(encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh)

        entries = raw.get("interlocks", [])
        if not isinstance(entries, list):
            raise ValueError(
                f"Некорректный формат файла блокировок: ключ 'interlocks' должен "
                f"содержать список, получен {type(entries).__name__}."
            )

        loaded = 0
        for entry in entries:
            condition = InterlockCondition(
                name=entry["name"],
                description=entry["description"],
                channel_pattern=entry["channel_pattern"],
                threshold=float(entry["threshold"]),
                comparison=entry["comparison"],
                action=entry["action"],
                cooldown_s=float(entry.get("cooldown_s", 0.0)),
            )
            self.add_condition(condition)
            loaded += 1

        logger.info(
            "Конфигурация блокировок загружена из '%s': %d блокировок.",
            config_path,
            loaded,
        )

    def add_condition(self, condition: InterlockCondition) -> None:
        """Добавить блокировку программно.

        Параметры
        ----------
        condition:
            Описание условия блокировки.

        Исключения
        ----------
        ValueError:
            Если блокировка с таким именем уже зарегистрирована или
            действие не найдено в словаре actions.
        """
        if condition.name in self._interlocks:
            raise ValueError(
                f"Блокировка '{condition.name}' уже зарегистрирована."
            )
        if condition.action not in self._actions:
            raise ValueError(
                f"Блокировка '{condition.name}': неизвестное действие "
                f"'{condition.action}'. Доступные действия: "
                f"{list(self._actions.keys())}."
            )
        self._interlocks[condition.name] = _InterlockRecord(condition=condition)
        logger.info(
            "Блокировка добавлена: '%s' | канал: '%s' | порог: %s %s | "
            "действие: '%s' | кулдаун: %.1f с.",
            condition.name,
            condition.channel_pattern,
            condition.comparison,
            condition.threshold,
            condition.action,
            condition.cooldown_s,
        )

    # ------------------------------------------------------------------
    # Управление жизненным циклом
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Запустить движок блокировок.

        Подписывается на DataBroker и запускает цикл проверки показаний.
        Повторный вызов без предварительного stop() игнорируется.
        """
        if self._task is not None and not self._task.done():
            logger.warning("InterlockEngine уже запущен — повторный start() проигнорирован.")
            return

        self._queue = await self._broker.subscribe(
            _SUBSCRIPTION_NAME,
            maxsize=10_000,
        )
        self._task = asyncio.create_task(
            self._check_loop(), name="interlock_check_loop"
        )
        logger.info(
            "InterlockEngine запущен. Активных блокировок: %d.",
            len(self._interlocks),
        )

    async def stop(self) -> None:
        """Остановить движок блокировок.

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
        logger.info("InterlockEngine остановлен.")

    # ------------------------------------------------------------------
    # Основной цикл проверки
    # ------------------------------------------------------------------

    async def _check_loop(self) -> None:
        """Основной цикл проверки блокировок.

        Непрерывно читает показания из очереди и проверяет все ARMED-блокировки,
        чей channel_pattern совпадает с каналом пришедшего показания.
        """
        assert self._queue is not None, "Очередь не инициализирована — вызовите start()"

        logger.debug("Цикл проверки блокировок запущен.")
        try:
            while True:
                reading: Reading = await self._queue.get()
                await self._process_reading(reading)
        except asyncio.CancelledError:
            logger.debug("Цикл проверки блокировок завершён по отмене задачи.")
            raise

    async def _process_reading(self, reading: Reading) -> None:
        """Проверить показание против всех подходящих ARMED-блокировок."""
        for record in self._interlocks.values():
            condition = record.condition

            # Проверяем только ARMED-блокировки
            if record.state != InterlockState.ARMED:
                continue

            # Проверяем совпадение канала с шаблоном
            if not condition.matches_channel(reading.channel):
                continue

            # Проверяем кулдаун
            if condition.cooldown_s > 0 and record.last_trip_time is not None:
                now = datetime.now(UTC)
                elapsed = (now - record.last_trip_time).total_seconds()
                if elapsed < condition.cooldown_s:
                    logger.debug(
                        "Блокировка '%s': кулдаун активен (%.1f / %.1f с) — "
                        "срабатывание пропущено.",
                        condition.name,
                        elapsed,
                        condition.cooldown_s,
                    )
                    continue

            # Проверяем условие срабатывания
            if condition.is_triggered(reading.value):
                await self._trip(record, reading)

    async def _trip(self, record: _InterlockRecord, reading: Reading) -> None:
        """Выполнить срабатывание блокировки.

        Устанавливает состояние TRIPPED, вызывает защитное действие,
        записывает событие и логирует CRITICAL.
        """
        condition = record.condition
        now = datetime.now(UTC)

        # Смена состояния
        record.state = InterlockState.TRIPPED
        record.last_trip_time = now
        record.trip_count += 1

        # Запись события
        event = InterlockEvent(
            timestamp=now,
            interlock_name=condition.name,
            channel=reading.channel,
            value=reading.value,
            threshold=condition.threshold,
            action_taken=condition.action,
        )
        self._events.append(event)

        # КРИТИЧЕСКИЙ лог — виден в любой конфигурации логирования
        logger.critical(
            "!!! БЛОКИРОВКА СРАБОТАЛА !!! "
            "Имя: '%s' | Описание: %s | "
            "Канал: '%s' | Значение: %.4g | "
            "Порог: %s %.4g | Действие: '%s' | "
            "Время: %s | Всего срабатываний: %d",
            condition.name,
            condition.description,
            reading.channel,
            reading.value,
            condition.comparison,
            condition.threshold,
            condition.action,
            now.isoformat(),
            record.trip_count,
        )

        # Вызов защитного действия
        action_callable = self._actions[condition.action]
        try:
            await action_callable()
            logger.critical(
                "Действие '%s' для блокировки '%s' выполнено успешно.",
                condition.action,
                condition.name,
            )
        except Exception as exc:
            # Ошибка действия не должна прерывать цикл, но логируется как CRITICAL
            logger.critical(
                "ОШИБКА выполнения действия '%s' для блокировки '%s': %s. "
                "Требуется немедленное вмешательство оператора!",
                condition.action,
                condition.name,
                exc,
                exc_info=True,
            )

        # Phase 2a Codex I.1: notify the optional trip_handler with FULL
        # context. SafetyManager uses this to differentiate "stop_source"
        # (soft stop, no fault latch) from "emergency_off" (full latch).
        # The handler is called even if the actions-dict callable above
        # raised — both paths run independently.
        if self._trip_handler is not None:
            try:
                result = self._trip_handler(condition, reading)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.critical(
                    "trip_handler failed for interlock '%s': %s",
                    condition.name, exc, exc_info=True,
                )

    # ------------------------------------------------------------------
    # Управление состоянием
    # ------------------------------------------------------------------

    def acknowledge(self, interlock_name: str) -> None:
        """Подтвердить срабатывание блокировки и перевести её обратно в ARMED.

        Оператор несёт ответственность за устранение причины срабатывания
        перед подтверждением. После вызова блокировка снова активна.

        Параметры
        ----------
        interlock_name:
            Имя блокировки, которую необходимо подтвердить.

        Исключения
        ----------
        KeyError:
            Если блокировка с таким именем не найдена.
        """
        if interlock_name not in self._interlocks:
            raise KeyError(
                f"Блокировка '{interlock_name}' не найдена. "
                f"Зарегистрированные блокировки: {list(self._interlocks.keys())}."
            )

        record = self._interlocks[interlock_name]
        previous_state = record.state
        record.state = InterlockState.ARMED

        logger.warning(
            "Блокировка '%s' подтверждена оператором и переведена в ARMED. "
            "Предыдущее состояние: %s. "
            "УБЕДИТЕСЬ, ЧТО ПРИЧИНА СРАБАТЫВАНИЯ УСТРАНЕНА!",
            interlock_name,
            previous_state.value,
        )

    def get_state(self) -> dict[str, InterlockState]:
        """Вернуть текущее состояние всех зарегистрированных блокировок.

        Возвращает
        ----------
        dict[str, InterlockState]:
            Словарь {имя_блокировки: состояние}.
        """
        return {name: record.state for name, record in self._interlocks.items()}

    def get_events(self) -> list[InterlockEvent]:
        """Вернуть историю срабатываний (до последних 1000 событий).

        Возвращает
        ----------
        list[InterlockEvent]:
            Список событий в хронологическом порядке (от старых к новым).
        """
        return list(self._events)
