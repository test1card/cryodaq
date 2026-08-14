"""Движок блокировок (InterlockEngine) — защита криогенного оборудования.

ВНИМАНИЕ: данный модуль является критичным для безопасности.
Любые изменения требуют ревью и тестирования перед деплоем.

Принцип работы:
  1. InterlockEngine подписывается на DataBroker и получает все Reading.
  2. Для каждого показания проверяются все ARMED-блокировки, чьи объявленные
     физические привязки разрешены в Reading.channel.
  3. При срабатывании условия: состояние → TRIPPED, вызывается action-коллбэк,
     событие записывается в лог и историю.
  4. TRIPPED-блокировка не срабатывает повторно до явного acknowledge().
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from cryodaq._owned_yaml import owned_safe_load
from cryodaq.core.broker import DataBroker, PublishedReading
from cryodaq.core.descriptor_transport import encode_descriptor_envelope
from cryodaq.core.physical_policy import PhysicalPolicyReceipt, receipt_for_applied_policy
from cryodaq.core.shutdown_settlement import cancel_and_settle_tasks
from cryodaq.drivers.base import Reading


class InterlockConfigError(RuntimeError):
    """Raised when interlocks.yaml cannot be loaded in a fail-closed manner."""


@dataclass(frozen=True, slots=True)
class InterlockChannelBinding:
    """One declared sensor identity and its exact persisted descriptor."""

    instrument_id: str
    source_key: str
    channel_id: str
    descriptor_envelope: bytes


def resolve_interlock_channel_bindings(
    entry: dict[str, Any], *, config_path: Path, descriptor_catalog: Any | None
) -> frozenset[InterlockChannelBinding]:
    """Resolve an interlock's declared physical sensor bindings exactly."""
    bindings = entry.get("channel_bindings")
    if type(bindings) is not list or not bindings:
        raise ValueError("channel_bindings must be a non-empty list")
    if descriptor_catalog is None:
        from cryodaq.storage.channel_descriptors import load_live_channel_descriptor_catalog

        descriptor_catalog = load_live_channel_descriptor_catalog(config_path.parent / "channel_descriptors.yaml")
    catalog = descriptor_catalog.storage_catalog_snapshot()
    resolved: set[InterlockChannelBinding] = set()
    for binding in bindings:
        if type(binding) is not dict or set(binding) != {"instrument_id", "source_key"}:
            raise ValueError("channel_bindings entries must contain only instrument_id and source_key")
        instrument_id = binding["instrument_id"]
        source_key = binding["source_key"]
        if type(instrument_id) is not str or type(source_key) is not str:
            raise ValueError("channel_bindings identity values must be strings")
        descriptor = catalog.by_source.get((instrument_id, source_key))
        if descriptor is None:
            raise ValueError(f"channel binding {instrument_id!r}/{source_key!r} is absent from the descriptor catalog")
        resolved.add(
            InterlockChannelBinding(
                instrument_id=instrument_id,
                source_key=source_key,
                channel_id=descriptor.channel_id,
                descriptor_envelope=encode_descriptor_envelope(descriptor),
            )
        )
    if len(resolved) != len(bindings):
        raise ValueError("channel_bindings must resolve to unique declared sensors")
    return frozenset(resolved)


def resolve_interlock_channel_ids(
    entry: dict[str, Any], *, config_path: Path, descriptor_catalog: Any | None
) -> frozenset[str]:
    """Resolve the canonical channel IDs for declared interlock sensors."""
    return frozenset(
        binding.channel_id
        for binding in resolve_interlock_channel_bindings(
            entry,
            config_path=config_path,
            descriptor_catalog=descriptor_catalog,
        )
    )


logger = logging.getLogger(__name__)

# Максимальное количество событий, хранимых в памяти
_MAX_EVENTS = 1000

# Имя подписки InterlockEngine в DataBroker
_SUBSCRIPTION_NAME = "interlock_engine"

# NaN-доктрина P2-5: дебаунс непригодных показаний (NaN / error-status) на
# interlock-каналах. Пороги по умолчанию — переопределяются в interlocks.yaml
# (секция nonusable_escalation), читаются fail-closed (строгие типы).
_DEFAULT_NONUSABLE_MIN_DURATION_S = 10.0
_DEFAULT_NONUSABLE_MIN_SAMPLES = 5


class InterlockState(Enum):
    """Состояние блокировки."""

    ARMED = "armed"  # Активна, ожидает срабатывания
    TRIPPED = "tripped"  # Сработала — действие выполнено, ожидает подтверждения
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
    channel_ids:
        Канонические идентификаторы, разрешённые из объявленных физических
        ``(instrument_id, source_key)`` привязок конфигурации.
    threshold:
        Пороговое значение для сравнения с Reading.value.
    comparison:
        Оператор сравнения: ``">"`` (больше) или ``"<"`` (меньше).
    action:
        Имя действия из словаря actions, переданного в InterlockEngine.
        Например: ``"emergency_off"`` или ``"stop_source"``.
    cooldown_s:
        Минимальный интервал в секундах между громкими УВЕДОМЛЕНИЯМИ о повторном
        срабатывании одной и той же блокировки. Защитное действие выполняется при
        КАЖДОМ нарушении (после re-arm через acknowledge) — кулдаун дедуплицирует
        только уведомление, но не защиту. По умолчанию 0 (без ограничения).
    """

    name: str
    description: str
    channel_ids: frozenset[str]
    threshold: float
    comparison: str  # ">" или "<"
    action: str
    channel_bindings: frozenset[InterlockChannelBinding] = frozenset()
    cooldown_s: float = 0.0

    def __post_init__(self) -> None:
        if self.comparison not in (">", "<"):
            raise ValueError(
                f"Блокировка '{self.name}': недопустимый оператор сравнения '{self.comparison}'. Допустимы: '>' и '<'."
            )
        if (
            type(self.channel_ids) is not frozenset
            or not self.channel_ids
            or any(type(channel_id) is not str or not channel_id for channel_id in self.channel_ids)
        ):
            raise ValueError(f"Блокировка '{self.name}': channel_ids must be a non-empty frozenset of strings")
        if type(self.channel_bindings) is not frozenset or any(
            type(binding) is not InterlockChannelBinding for binding in self.channel_bindings
        ):
            raise ValueError(f"Блокировка '{self.name}': channel_bindings must be a frozenset of resolved bindings")
        if (
            self.channel_bindings
            and frozenset(binding.channel_id for binding in self.channel_bindings) != self.channel_ids
        ):
            raise ValueError(f"Блокировка '{self.name}': channel_ids disagree with channel_bindings")

    def matches_channel(self, channel: str) -> bool:
        """Проверить точное совпадение с объявленной привязкой датчика."""
        return channel in self.channel_ids

    def matches_reading(self, reading: Reading, descriptor_envelope: bytes | None) -> bool:
        """Match the full declared runtime identity, including source provenance."""
        if not self.channel_bindings:
            return self.matches_channel(reading.channel)
        if type(descriptor_envelope) is not bytes:
            return False
        return any(
            reading.instrument_id == binding.instrument_id
            and reading.channel == binding.channel_id
            and descriptor_envelope == binding.descriptor_envelope
            for binding in self.channel_bindings
        )

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


@dataclass
class _NonUsableWindow:
    """Окно дебаунса непригодных показаний одного interlock-канала (P2-5).

    ``first_ts`` — время измерения ПЕРВОГО непригодного показания в текущей
    серии подряд (используется measurement-time, не wall-clock — как F23:
    корректно под backlog и детерминированно в тестах). ``count`` — число
    непригодных показаний подряд (сбрасывается годным показанием).
    ``escalated`` — эскалация в SafetyManager уже выполнена для этого окна
    (не дублируем на каждом последующем непригодном показании).
    """

    first_ts: datetime
    count: int = 0
    escalated: bool = False


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
        engine.load_config(
            Path("config/interlocks.yaml"),
            poll_intervals_s_by_instrument={"LS218_1": 2.0, "LS218_2": 2.0},
        )
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
        alarm_publisher: Any | None = None,
        dead_channel_handler: Callable[[InterlockCondition, Reading], Any] | None = None,
        dead_channel_recovery_handler: Callable[[InterlockCondition, Reading], Any] | None = None,
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
            I.1) so the action name, condition name, channel, and value
            survive the trip path instead of being collapsed by zero-arg
            callbacks.
        alarm_publisher:
            Optional object exposing ``publish_diagnostic_alarm(channel_id,
            severity, age_seconds)`` (AlarmStateManager). Used by P2-5 to emit
            an alarm-v2 event when a non-usable reading lands on an
            interlock-protected channel. May be set later via
            :meth:`set_alarm_publisher`.
        dead_channel_handler:
            Optional async/sync callback ``(InterlockCondition, Reading)`` fired
            by P2-5 when a channel is PERSISTENTLY non-usable (see
            ``nonusable_escalation`` config). SafetyManager wiring routes this to
            ``on_interlock_dead_channel`` which gates the fault on the active
            source lifecycle (RUN_PERMITTED or RUNNING) — SafetyManager remains
            the sole authority.
        dead_channel_recovery_handler:
            Optional async/sync callback invoked only after a usable reading is
            observed for the same canonical protected channel. A callback error
            leaves the debounce window intact so recovery fails closed.
        """
        self._broker = broker
        self._actions = actions
        self._trip_handler = trip_handler
        self._alarm_publisher = alarm_publisher
        self._dead_channel_handler = dead_channel_handler
        self._dead_channel_recovery_handler = dead_channel_recovery_handler
        self._interlocks: dict[str, _InterlockRecord] = {}
        self._events: deque[InterlockEvent] = deque(maxlen=_MAX_EVENTS)
        self._queue: asyncio.Queue[PublishedReading] | None = None
        self._task: asyncio.Task[None] | None = None

        # P2-5 debounce state: per-channel non-usable window + thresholds.
        self._nonusable_windows: dict[str, _NonUsableWindow] = {}
        self._nonusable_min_duration_s = _DEFAULT_NONUSABLE_MIN_DURATION_S
        self._nonusable_min_samples = _DEFAULT_NONUSABLE_MIN_SAMPLES

    def set_alarm_publisher(self, alarm_publisher: Any) -> None:
        """Register the alarm-v2 publisher after construction (engine wiring).

        The AlarmStateManager is built after InterlockEngine in engine startup,
        so this setter lets the engine wire the P2-5 alarm-v2 surface without
        reordering construction.
        """
        self._alarm_publisher = alarm_publisher

    # ------------------------------------------------------------------
    # Загрузка конфигурации
    # ------------------------------------------------------------------

    def load_config(
        self,
        config_path: Path,
        *,
        snapshot: bytes | None = None,
        descriptor_catalog: Any | None = None,
        poll_intervals_s_by_instrument: Mapping[str, float] | None = None,
    ) -> PhysicalPolicyReceipt:
        """Загрузить блокировки из YAML-файла.

        Ожидаемая структура файла::

            interlocks:
              - name: "имя_блокировки"
                description: "Описание"
                channel_bindings:
                  - instrument_id: "LS218_1"
                    source_key: "input.1.temperature"
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
            raise InterlockConfigError(
                f"interlocks.yaml not found at {config_path} — refusing to start "
                f"interlock engine without interlock configuration"
            )

        if snapshot is None:
            snapshot = config_path.read_bytes()
        try:
            raw: dict[str, Any] = owned_safe_load(snapshot)
        except yaml.YAMLError as exc:
            raise InterlockConfigError(f"interlocks.yaml at {config_path}: YAML parse error — {exc}") from exc

        if not isinstance(raw, dict):
            raise InterlockConfigError(f"interlocks.yaml at {config_path}: expected mapping, got {type(raw).__name__}")

        entries = raw.get("interlocks", [])
        if not isinstance(entries, list):
            raise InterlockConfigError(
                f"interlocks.yaml at {config_path}: 'interlocks' must be a list, got {type(entries).__name__}"
            )

        loaded = 0
        for entry in entries:
            try:
                channel_bindings = resolve_interlock_channel_bindings(
                    entry,
                    config_path=config_path,
                    descriptor_catalog=descriptor_catalog,
                )
                condition = InterlockCondition(
                    name=entry["name"],
                    description=entry["description"],
                    channel_ids=frozenset(binding.channel_id for binding in channel_bindings),
                    threshold=float(entry["threshold"]),
                    comparison=entry["comparison"],
                    action=entry["action"],
                    channel_bindings=channel_bindings,
                    cooldown_s=float(entry.get("cooldown_s", 0.0)),
                )
                self.add_condition(condition)
                loaded += 1
            except (KeyError, ValueError, TypeError) as exc:
                raise InterlockConfigError(
                    f"interlocks.yaml at {config_path}: invalid interlock entry — {type(exc).__name__}: {exc}"
                ) from exc

        self._load_nonusable_escalation(
            raw,
            config_path,
            poll_intervals_s_by_instrument=poll_intervals_s_by_instrument,
        )

        logger.info(
            "Конфигурация блокировок загружена из '%s': %d блокировок.",
            config_path,
            loaded,
        )
        return receipt_for_applied_policy("interlocks", config_path, snapshot)

    def _load_nonusable_escalation(
        self,
        raw: dict[str, Any],
        config_path: Path,
        *,
        poll_intervals_s_by_instrument: Mapping[str, float] | None,
    ) -> None:
        """Parse and cadence-bound the optional failed-sample escalation."""
        block = raw.get("nonusable_escalation")
        if block is None:
            return
        if not isinstance(block, dict):
            raise InterlockConfigError(
                f"interlocks.yaml at {config_path}: 'nonusable_escalation' must be a "
                f"mapping, got {type(block).__name__}"
            )

        duration_value = block.get("min_duration_s", _DEFAULT_NONUSABLE_MIN_DURATION_S)
        samples_value = block.get("min_samples", _DEFAULT_NONUSABLE_MIN_SAMPLES)
        if type(duration_value) not in (int, float) or type(samples_value) is not int:
            raise InterlockConfigError(
                f"interlocks.yaml at {config_path}: nonusable_escalation requires an exact numeric "
                "min_duration_s and exact integer min_samples"
            )
        min_duration_s = float(duration_value)
        min_samples = samples_value
        if not math.isfinite(min_duration_s) or min_duration_s <= 0 or min_samples <= 0:
            raise InterlockConfigError(
                f"interlocks.yaml at {config_path}: nonusable_escalation requires "
                f"positive finite min_duration_s and positive min_samples "
                f"(got min_duration_s={min_duration_s}, min_samples={min_samples})"
            )
        if min_samples > _DEFAULT_NONUSABLE_MIN_SAMPLES:
            raise InterlockConfigError(
                f"interlocks.yaml at {config_path}: nonusable_escalation min_samples={min_samples} "
                f"exceeds the reviewed maximum {_DEFAULT_NONUSABLE_MIN_SAMPLES}"
            )
        if not isinstance(poll_intervals_s_by_instrument, Mapping):
            raise InterlockConfigError(
                f"interlocks.yaml at {config_path}: nonusable_escalation requires configured poll intervals "
                "for every protected instrument"
            )

        protected_instruments = {
            binding.instrument_id
            for record in self._interlocks.values()
            for binding in record.condition.channel_bindings
        }
        if not protected_instruments:
            raise InterlockConfigError(
                f"interlocks.yaml at {config_path}: nonusable_escalation has no protected instrument bindings"
            )
        for instrument_id in sorted(protected_instruments):
            cadence_value = poll_intervals_s_by_instrument.get(instrument_id)
            if type(cadence_value) not in (int, float):
                raise InterlockConfigError(
                    f"interlocks.yaml at {config_path}: missing exact poll interval for protected instrument "
                    f"{instrument_id!r}"
                )
            cadence_s = float(cadence_value)
            if not math.isfinite(cadence_s) or cadence_s <= 0:
                raise InterlockConfigError(
                    f"interlocks.yaml at {config_path}: protected instrument {instrument_id!r} has invalid "
                    f"poll interval {cadence_value!r}"
                )
            max_duration_s = cadence_s * min_samples
            if min_duration_s > max_duration_s:
                raise InterlockConfigError(
                    f"interlocks.yaml at {config_path}: nonusable_escalation min_duration_s={min_duration_s} "
                    f"exceeds {instrument_id!r} cadence bound {max_duration_s} "
                    f"({cadence_s}s * {min_samples} samples)"
                )

        self._nonusable_min_duration_s = min_duration_s
        self._nonusable_min_samples = min_samples

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
            raise ValueError(f"Блокировка '{condition.name}' уже зарегистрирована.")
        if condition.action not in self._actions:
            raise ValueError(
                f"Блокировка '{condition.name}': неизвестное действие "
                f"'{condition.action}'. Доступные действия: "
                f"{list(self._actions.keys())}."
            )
        self._interlocks[condition.name] = _InterlockRecord(condition=condition)
        logger.info(
            "Блокировка добавлена: '%s' | канал: '%s' | порог: %s %s | действие: '%s' | кулдаун: %.1f с.",
            condition.name,
            sorted(condition.channel_ids),
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
            wants_descriptor_envelope=True,
        )
        self._task = asyncio.create_task(self._check_loop(), name="interlock_check_loop")
        logger.info(
            "InterlockEngine запущен. Активных блокировок: %d.",
            len(self._interlocks),
        )

    async def stop(self) -> None:
        """Остановить движок блокировок.

        Отменяет задачу проверки и отписывается от DataBroker.
        """
        task = self._task
        settlement = await cancel_and_settle_tasks(() if task is None else (task,))
        self._task = None
        queue = self._queue
        if queue is not None:
            removed = await self._broker.unsubscribe(
                _SUBSCRIPTION_NAME,
                expected_queue=queue,
            )
            if removed is not True:
                raise RuntimeError("interlock broker did not release the exact queue owner")
            self._queue = None
        settlement.raise_if_unsuccessful()
        logger.info("InterlockEngine остановлен.")

    # ------------------------------------------------------------------
    # Основной цикл проверки
    # ------------------------------------------------------------------

    async def _check_loop(self) -> None:
        """Основной цикл проверки блокировок.

        Непрерывно читает показания из очереди и проверяет все ARMED-блокировки,
        чьи объявленные привязки совпадают с каналом пришедшего показания.
        """
        assert self._queue is not None, "Очередь не инициализирована — вызовите start()"

        logger.debug("Цикл проверки блокировок запущен.")
        try:
            while True:
                published: PublishedReading = await self._queue.get()
                await self._process_reading(
                    published.reading,
                    descriptor_envelope=published.descriptor_envelope,
                )
        except asyncio.CancelledError:
            logger.debug("Цикл проверки блокировок завершён по отмене задачи.")
            raise

    async def _process_reading(self, reading: Reading, *, descriptor_envelope: bytes | None = None) -> None:
        """Проверить показание против всех подходящих ARMED-блокировок."""
        # ARMED-блокировки, чьи объявленные привязки совпали с каналом показания.
        matching = [
            record
            for record in self._interlocks.values()
            if record.state == InterlockState.ARMED and record.condition.matches_reading(reading, descriptor_envelope)
        ]
        protected_matching = [
            record
            for record in self._interlocks.values()
            if record.condition.matches_reading(reading, descriptor_envelope)
        ]

        # NaN-доктрина P2-5: непригодное показание (NaN / error-status) на
        # interlock-защищённом канале. Пороговое сравнение с NaN всегда даёт
        # False (IEEE-754), поэтому без этой ветки блокировка молча слепнет на
        # мёртвом датчике (fail-open на нагреваемой зоне — Т1–Т10 защищены
        # ТОЛЬКО интерлоками). Годное показание сбрасывает дебаунс; непригодное
        # обрабатывается и НЕ идёт в пороговое сравнение (иначе ±inf ложно
        # сработало бы как реальное превышение).
        if reading.is_usable():
            if protected_matching:
                await self._handle_usable(reading, protected_matching[0].condition)
        elif protected_matching:
            if math.isinf(reading.value) and any(record.condition.is_triggered(reading.value) for record in matching):
                # S2 fail-closed: ±inf carries DIRECTIONAL evidence. +inf (sensor
                # pegged HIGH / OVL) satisfies any above-threshold ('>') interlock;
                # -inf (pegged LOW) satisfies any below-threshold ('<') interlock.
                # That is direct evidence of the guarded hazard — fall through to
                # the normal threshold-trip loop (is_triggered trips at once), do
                # NOT wait out the non-usable debounce. NaN (is_triggered False
                # both ways) and finite-value+error-status carry no direction and
                # keep the debounce path below. -inf on a '>' interlock (or +inf on
                # a '<' interlock) is the SAFE side → also debounce. Reset the
                # window so a prior blip series does not linger past this trip.
                self._nonusable_windows.pop(reading.channel, None)
            else:
                await self._handle_nonusable(reading, protected_matching[0].condition)
                return

        for record in matching:
            condition = record.condition

            # Проверяем условие срабатывания
            if condition.is_triggered(reading.value):
                # Кулдаун подавляет ТОЛЬКО дублирующее уведомление, но НЕ само
                # защитное действие. Блокировки латчащие (TRIPPED → ARMED только
                # через acknowledge оператора); если после acknowledge нарушение
                # сохраняется, защита обязана сработать снова. Старое поведение
                # пропускало срабатывание в окне кулдауна — защита «слепла» на
                # остаток окна. Теперь действие выполняется всегда, а громкое
                # уведомление — не чаще раза в cooldown_s.
                in_cooldown = (
                    condition.cooldown_s > 0
                    and record.last_trip_time is not None
                    and (datetime.now(UTC) - record.last_trip_time).total_seconds() < condition.cooldown_s
                )
                await self._trip(record, reading, suppress_notification=in_cooldown)

    async def _handle_usable(self, reading: Reading, condition: InterlockCondition) -> None:
        """Clear dead-channel state only after recovery authority accepts this sample."""
        handler = self._dead_channel_recovery_handler
        if handler is not None:
            try:
                result = handler(condition, reading)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.critical(
                    "dead_channel_recovery_handler failed for interlock '%s' channel '%s': %s",
                    condition.name,
                    reading.channel,
                    exc,
                    exc_info=True,
                )
                return
        self._nonusable_windows.pop(reading.channel, None)

    async def _handle_nonusable(self, reading: Reading, condition: InterlockCondition) -> None:
        """Обработать непригодное показание на interlock-защищённом канале (P2-5).

        Транзиент (одиночный blip): громкий CRITICAL-лог + alarm-v2, БЕЗ trip —
        оператор не должен терять эксперимент из-за мгновенного сбоя датчика.
        Персистентность (≥ min_samples подряд И ≥ min_duration_s по времени
        измерения) → эскалация в SafetyManager (``dead_channel_handler``),
        который сам решает, латчить ли fault (в RUN_PERMITTED или RUNNING).
        """
        window = self._nonusable_windows.get(reading.channel)
        if window is None:
            window = _NonUsableWindow(first_ts=reading.timestamp)
            self._nonusable_windows[reading.channel] = window
        window.count += 1
        span_s = (reading.timestamp - window.first_ts).total_seconds()

        # Транзиент: громкий лог + alarm-v2 (защитное действие НЕ выполняется).
        logger.critical(
            "!!! НЕПРИГОДНОЕ ПОКАЗАНИЕ НА INTERLOCK-КАНАЛЕ !!! "
            "Канал: '%s' | Статус: %s | Значение: %.4g | Блокировка: '%s' | "
            "Непригодных подряд: %d | Длительность серии: %.1f с. "
            "Транзиент — защитное действие НЕ выполнено.",
            reading.channel,
            reading.status.value,
            reading.value,
            condition.name,
            window.count,
            span_s,
        )
        if self._alarm_publisher is not None:
            try:
                self._alarm_publisher.publish_diagnostic_alarm(reading.channel, "critical", span_s)
            except Exception as exc:
                logger.error(
                    "Interlock: alarm-v2 publish failed for '%s': %s",
                    reading.channel,
                    exc,
                )

        # Персистентность → эскалация. S1 fail-closed: окно помечается
        # escalated ТОЛЬКО когда handler подтвердил латч fault (вернул True).
        # Если SafetyManager отклонил эскалацию вне активного жизненного цикла
        # источника (например, SAFE_OFF или READY), окно остаётся
        # не-escalated и КАЖДОЕ последующее непригодное показание повторяет
        # попытку; первое же показание после перехода в RUN_PERMITTED/RUNNING
        # латчит fault. Без этого мёртвый канал молча утекал бы навсегда.
        if (
            not window.escalated
            and window.count >= self._nonusable_min_samples
            and span_s >= self._nonusable_min_duration_s
        ):
            logger.critical(
                "Interlock-канал '%s' непригоден ≥%.0f с и ≥%d показаний подряд — "
                "эскалация в SafetyManager (блокировка '%s').",
                reading.channel,
                self._nonusable_min_duration_s,
                self._nonusable_min_samples,
                condition.name,
            )
            # No handler wired (standalone/test): nothing can latch a fault, so
            # mark escalated to avoid re-logging every subsequent sample.
            escalated = True
            if self._dead_channel_handler is not None:
                try:
                    result = self._dead_channel_handler(condition, reading)
                    if asyncio.iscoroutine(result):
                        result = await result
                    escalated = bool(result)
                except Exception as exc:
                    logger.critical(
                        "dead_channel_handler failed for interlock '%s' channel '%s': %s",
                        condition.name,
                        reading.channel,
                        exc,
                        exc_info=True,
                    )
                    # Handler raised → no confirmed latch → retry next sample.
                    escalated = False
            window.escalated = escalated

    async def _trip(
        self,
        record: _InterlockRecord,
        reading: Reading,
        *,
        suppress_notification: bool = False,
    ) -> None:
        """Выполнить срабатывание блокировки.

        Устанавливает состояние TRIPPED, вызывает защитное действие,
        записывает событие и логирует CRITICAL.

        ``suppress_notification=True`` — повторное срабатывание в окне кулдауна:
        защитное действие выполняется как обычно, но громкое CRITICAL-уведомление
        и обновление ``last_trip_time`` пропускаются. Кулдаун дедуплицирует только
        уведомление, не саму защиту.
        """
        condition = record.condition
        now = datetime.now(UTC)

        # Смена состояния
        record.state = InterlockState.TRIPPED
        record.trip_count += 1

        # Запись события (аудит — всегда; защитное действие реально выполняется ниже)
        event = InterlockEvent(
            timestamp=now,
            interlock_name=condition.name,
            channel=reading.channel,
            value=reading.value,
            threshold=condition.threshold,
            action_taken=condition.action,
        )
        self._events.append(event)

        if suppress_notification:
            logger.warning(
                "Блокировка '%s': повторное срабатывание в окне кулдауна "
                "(%.4g %s %.4g) — защитное действие выполнено, "
                "дублирующее уведомление подавлено.",
                condition.name,
                reading.value,
                condition.comparison,
                condition.threshold,
            )
        else:
            record.last_trip_time = now
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
            logger.info(
                "Локальный обработчик действия '%s' для блокировки '%s' завершился; "
                "авторитетный результат защиты не подтверждён.",
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

        # Phase 2a I.1: notify the optional trip_handler with FULL
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
                    condition.name,
                    exc,
                    exc_info=True,
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
